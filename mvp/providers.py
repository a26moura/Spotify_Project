"""Spotify (API oficial) e fontes públicas de informação: Deezer (gênero do álbum, BPM, prévia de 30 s)
e LRCLIB (idioma detectado localmente na letra). Termos do Deezer: só uso pessoal, não comercial."""
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from email.utils import parsedate_to_datetime
from core import norm, ORIGIN_RANK, infer_origin
import lyrics_language

class RemoteError(Exception):
    def __init__(self, message, *, status=None, retry_after=0, transient=False):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.transient = transient

def retry_delay(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        try:
            return max(0, int(parsedate_to_datetime(value).timestamp() - time.time()) + 1)
        except (TypeError, ValueError, OverflowError):
            return 0

def request_json(url, method='GET', body=None, headers=None, form=False, timeout=25):
    host = urllib.parse.urlsplit(url).hostname
    service = {'api.deezer.com':'Deezer', 'lrclib.net':'LRCLIB',
               'api.spotify.com':'Spotify', 'accounts.spotify.com':'Spotify'}.get(host, 'Serviço externo')
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        status, delay = e.code, retry_delay(e.headers.get('Retry-After'))
        e.close()
        if status in (429, 500, 502, 503, 504):
            message = f'{service} temporariamente indisponível ou limitando consultas (HTTP {status}).'
        elif status in (401,403):
            message = f'{service}: acesso recusado (HTTP {status}).'
            if service == 'Spotify': message += ' Reconecte a conta e confira as permissões do aplicativo.'
        else:
            message = f'{service} respondeu HTTP {status}.'
        if method != 'GET': message += ' Não houve repetição automática. Prepare nova prévia antes de tentar gravar novamente.'
        raise RemoteError(message, status=status, retry_after=delay, transient=status in (429,500,502,503,504)) from None
    except (urllib.error.URLError, TimeoutError):
        message = f'Falha de rede ao consultar {service}. O progresso foi preservado.' if method=='GET' else f'Falha de rede em {service}. Uma gravação pode ter sido recebida: prepare uma nova prévia antes de tentar novamente.'
        raise RemoteError(message, transient=True) from None

class Spotify:
    def __init__(self, session, client_id, redirect):
        self.session, self.client_id, self.redirect = session, client_id, redirect

    def token(self):
        token = self.session.get('token')
        if not token: raise RemoteError('Conecte sua conta do Spotify.')
        if token['expires_at'] < time.time()+60:
            fresh = request_json('https://accounts.spotify.com/api/token', 'POST', {'grant_type':'refresh_token','refresh_token':token['refresh_token'],'client_id':self.client_id}, form=True)
            token.update(fresh)
            token['expires_at'] = time.time()+fresh['expires_in']
        return token['access_token']

    def call(self, path, method='GET', body=None):
        if not path.startswith('/') or path.startswith('//'): raise ValueError('Caminho inválido.')
        return request_json('https://api.spotify.com/v1'+path, method, body, {'Authorization':'Bearer '+self.token()})

    def pages(self, path):
        result, seen = [], set()
        while path:
            if path in seen: raise RemoteError('Paginação repetida recebida do Spotify.')
            seen.add(path)
            page = self.call(path)
            result.extend(page.get('items',[]))
            nxt = page.get('next')
            if nxt:
                u = urllib.parse.urlsplit(nxt)
                if u.scheme!='https' or u.netloc!='api.spotify.com' or not u.path.startswith('/v1/'): raise RemoteError('Paginação inválida.')
                path = u.path[3:]+('?' + u.query if u.query else '')
            else: path = None
        return result

    def library(self): return [dict(r['track'], added_at=r.get('added_at')) for r in self.pages('/me/tracks?limit=50') if r and r.get('track')]
    def playlists(self): return [p for p in self.pages('/me/playlists?limit=50') if p and p.get('owner',{}).get('id')==self.session['account']]

    def playlist_tracks(self, ident):
        return [item for row in self.pages('/playlists/'+ident+'/items?limit=50')
                if (item := (row or {}).get('item') or (row or {}).get('track')) and item.get('type','track')=='track']

    def contents(self, ident):
        present = set()
        for row in self.pages('/playlists/'+ident+'/items?limit=50'):
            item = (row or {}).get('item') or (row or {}).get('track') or {}
            if item.get('uri'): present.add(item['uri'])
            if item.get('linked_from',{}).get('uri'): present.add(item['linked_from']['uri'])
        return present

def title_key(title):
    """Ignore credit formatting, never live/remix/acoustic version identifiers."""
    title = norm(title)
    title = re.sub(r'\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|part\.?)\s+[^)\]]+[)\]]', '', title)
    title = re.sub(r'\s+(?:feat\.?|ft\.?|featuring|part\.?)\s+.*$', '', title)
    return ' '.join(re.findall(r'\w+', title))


SPACING = {'api.deezer.com':0.25, 'lrclib.net':0.7}
# Deezer album genres too broad to stand for a track's genre; kept as labels only.
GENERIC_ALBUM_GENRES = {'latin music','brazilian music','world music','films/games','african music','asian music','kids','international pop'}
USER_AGENT = 'SpotifyProjectLocalPilot/0.1 (personal noncommercial research)'


class Enricher:
    def __init__(self, store):
        self.store, self.lock, self.last = store, threading.Lock(), {}
        self.cooldowns = {}

    def cached(self, key, ttl, compute):
        """Cache a derived result only (never raw third-party payloads such as lyrics or images)."""
        with self.store.connect() as db:
            row = db.execute('SELECT data,expires FROM cache WHERE key=?',(key,)).fetchone()
        if row and row[1]>time.time(): return json.loads(row[0])
        value = compute()
        if value is not None:
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,json.dumps(value),time.time()+ttl))
        return value

    def get(self, url, cache=True):
        key = hashlib.sha256(url.encode()).hexdigest()
        if cache:
            with self.store.connect() as db:
                cached = db.execute('SELECT data,expires FROM cache WHERE key=?',(key,)).fetchone()
            if cached and cached[1]>time.time(): return json.loads(cached[0])
        with self.lock:
            host = urllib.parse.urlsplit(url).hostname
            remaining = self.cooldowns.get(host, 0) - time.monotonic()
            if remaining > 0:
                raise RemoteError(f'{host}: consultas pausadas. Aguarde {int(remaining)+1} segundos; a coleta tenta de novo depois. Suas escolhas estão salvas.', retry_after=int(remaining)+1, transient=True)
            for attempt in range(3):
                time.sleep(max(0,SPACING.get(host,1.1)-(time.monotonic()-self.last.get(host,0))))
                try:
                    data = request_json(url, headers={'User-Agent':USER_AGENT, 'Accept':'application/json', 'Accept-Language':'en'}, timeout=12)
                    break
                except RemoteError as error:
                    if not error.transient: raise
                    # Only public metadata GETs are repeated; Spotify writes never enter this loop.
                    if attempt == 2 or error.retry_after > 10:
                        pause = max(60, error.retry_after)
                        self.cooldowns[host] = time.monotonic() + pause
                        raise RemoteError(f'{error} Consulta pausada após {attempt+1} tentativa(s). Aguarde {pause} segundos; a coleta tenta de novo depois. Suas escolhas estão salvas.', status=error.status, retry_after=pause, transient=True) from None
                    time.sleep(max(2 ** (attempt + 1), error.retry_after))
                finally:
                    self.last[host] = time.monotonic()
        if cache:
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,json.dumps(data),time.time()+7*86400))
        return data

    def deezer_album_genres(self, track):
        """Album genres on Deezer for the exact ISRC, when the credited artist matches.
        Returns None on temporary failure (try again later), else a dict (possibly empty)."""
        isrc = track.get('isrc') or ''
        if not re.fullmatch(r'[A-Za-z0-9]{12}', isrc) or not track.get('artists'): return {}
        def compute():
            data = self.get('https://api.deezer.com/track/isrc:'+isrc.upper(), cache=False)
            error = data.get('error') if isinstance(data, dict) else None
            if error:
                # Code 4 = quota exceeded: temporary, do not cache.
                if error.get('code') == 4: raise RemoteError('Deezer: limite de consultas atingido.', transient=True)
                return {}
            names = {norm((data.get('artist') or {}).get('name',''))} | {norm(c.get('name','')) for c in data.get('contributors',[]) or []}
            album = (data.get('album') or {}).get('id')
            if norm(track['artists'][0]) not in names or not album: return {'mismatch':True}
            info = self.get('https://api.deezer.com/album/'+str(int(album)), cache=False)
            genres = [g['name'] for g in ((info.get('genres') or {}).get('data') or []) if isinstance(g, dict) and g.get('name')]
            return {'album_id':int(album), 'album':info.get('title') or (data.get('album') or {}).get('title',''), 'genres':list(dict.fromkeys(genres)),
                    'deezer_id':data.get('id'), 'bpm':data.get('bpm') or None}
        try:
            return self.cached('deezer-isrc2:'+isrc.upper(), 30*86400, compute)
        except RemoteError as error:
            if error.transient: return None
            return {}

    def lyrics_languages(self, track):
        """Language detected locally from LRCLIB lyrics. The lyrics text is never stored.
        Returns None on temporary failure, else {'languages':[...], 'found':bool, 'instrumental':bool}."""
        if not track.get('title') or not track.get('artists'): return {'languages':[], 'found':False}
        params = {'track_name':track['title'], 'artist_name':track['artists'][0]}
        if isinstance(track.get('duration_ms'), (int, float)) and 1000 <= track['duration_ms'] <= 3600000:
            params['duration'] = round(track['duration_ms']/1000)
        url = 'https://lrclib.net/api/get?'+urllib.parse.urlencode(params)
        def compute():
            try:
                data = self.get(url, cache=False)
            except RemoteError as error:
                if error.status == 404: return {'languages':[], 'found':False}
                raise
            if not isinstance(data, dict): return {'languages':[], 'found':False}
            if title_key(data.get('trackName','')) != title_key(track['title']) or norm(track['artists'][0]) not in norm(data.get('artistName','')):
                return {'languages':[], 'found':False}
            if data.get('instrumental'): return {'languages':['Instrumental'], 'found':True, 'instrumental':True}
            text = data.get('plainLyrics') or lyrics_language.strip_timestamps(data.get('syncedLyrics'))
            return {'languages':lyrics_language.detect(text), 'found':bool(text), 'id':data.get('id')}
        try:
            return self.cached('lrclib-lang:'+hashlib.sha256(url.encode()).hexdigest(), 30*86400, compute)
        except RemoteError as error:
            if error.transient: return None
            return {'languages':[], 'found':False}

    def quick(self, track):
        """Fast lookup for the game, without MusicBrainz: album genre, BPM and Deezer id by ISRC, and
        the language detected in the LRCLIB lyrics. Fills only what is missing or weaker (genre:
        faixa wins over album; language: faixa and letra are kept). 'quick_checked' is set only when
        no source failed temporarily, so the track is tried again later."""
        result, complete = {'source_labels':list(track.get('source_labels') or []), 'sources':list(track.get('sources') or [])}, True
        album = self.deezer_album_genres(track)
        if album is None: complete = False
        elif album.get('deezer_id'):
            result.update(deezer_id=album['deezer_id'], bpm=album.get('bpm'))
            url = 'https://www.deezer.com/album/'+str(album['album_id'])
            known = {(l.get('label'), l.get('kind')) for l in result['source_labels']}
            result['source_labels'] += [{'label':g,'kind':'album-genre','source':'Deezer (álbum)','url':url} for g in album['genres'] if (g,'album-genre') not in known]
            specific = [g for g in album['genres'] if norm(g) not in GENERIC_ALBUM_GENRES]
            weaker = ORIGIN_RANK.get(infer_origin(track,'genre'),0) < ORIGIN_RANK['album']
            if album['genres'] and weaker and (specific or not track.get('genres')):
                result.update(genres=specific or album['genres'], genre_origin='album')
                if not any(x.get('url')==url for x in result['sources']):
                    result['sources'].append({'label':'Deezer (álbum: '+(album.get('album') or '?')+')','url':url,'level':'álbum'})
        if ORIGIN_RANK.get(infer_origin(track,'language'),0) < ORIGIN_RANK['letra']:
            lyrics = self.lyrics_languages(track)
            if lyrics is None: complete = False
            elif lyrics.get('languages'):
                result.update(languages=lyrics['languages'], language_origin='letra')
                if not any(x.get('level')=='letra' for x in result['sources']):
                    result['sources'].append({'label':'LRCLIB (idioma detectado na letra)','url':'https://lrclib.net/','level':'letra'})
        if complete: result['quick_checked'] = True
        return result

    def preview(self, track):
        """30-second Deezer preview URL, fetched on demand and never stored (the link expires)."""
        if track.get('deezer_id'): path = str(int(track['deezer_id']))
        elif re.fullmatch(r'[A-Za-z0-9]{12}', track.get('isrc') or ''): path = 'isrc:'+track['isrc'].upper()
        else: return None
        data = self.get('https://api.deezer.com/track/'+path, cache=False)
        if not isinstance(data, dict) or data.get('error'): return None
        if not track.get('deezer_id'):
            names = {norm((data.get('artist') or {}).get('name',''))} | {norm(c.get('name','')) for c in data.get('contributors',[]) or []}
            if not track.get('artists') or norm(track['artists'][0]) not in names: return None
        url = data.get('preview') or ''
        return url if re.fullmatch(r'https://[A-Za-z0-9.-]+\.dzcdn\.net/\S+', url) else None
