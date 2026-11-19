"""Official Spotify API adapter and conservative MusicBrainz enrichment."""
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
from core import broad, norm, ORIGIN_RANK, infer_origin
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
    service = {'musicbrainz.org':'MusicBrainz', 'www.wikidata.org':'Wikidata', 'api.deezer.com':'Deezer', 'lrclib.net':'LRCLIB',
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

    def library(self): return [r['track'] for r in self.pages('/me/tracks?limit=50') if r and r.get('track')]
    def playlists(self): return [p for p in self.pages('/me/playlists?limit=50') if p and p.get('owner',{}).get('id')==self.session['account']]

    def all_playlists(self):
        return [p for p in self.pages('/me/playlists?limit=50') if p]

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


def matching_hits(track, hits):
    """Recordings whose title and primary credited artist match the Spotify track."""
    out = []
    for r in hits:
        if title_key(r.get('title','')) != title_key(track['title']): continue
        credits = [a for a in r.get('artist-credit',[]) if 'artist' in a]
        if track['artists'] and credits and norm(credits[0]['artist']['name']) == norm(track['artists'][0]):
            out.append(r)
    return out


def primary_artist_id(track, hits):
    """Artist MBID only when every matching recording agrees on the same primary artist."""
    ids = {r['artist-credit'][0]['artist']['id'] for r in matching_hits(track, hits)
           if r.get('artist-credit') and r['artist-credit'][0].get('artist',{}).get('id')}
    return ids.pop() if len(ids) == 1 else None


def choose_recording(track, hits):
    ranked = []
    for r in hits:
        if title_key(r.get('title','')) != title_key(track['title']): continue
        credits = {norm(a['artist']['name']) for a in r.get('artist-credit',[]) if 'artist' in a}
        if not track['artists'] or norm(track['artists'][0]) not in credits: continue
        duration, length = track.get('duration_ms'), r.get('length')
        delta = abs(duration-length) if isinstance(duration,(int,float)) and isinstance(length,(int,float)) else None
        if delta is not None and delta > max(5000, duration*.025): continue
        ranked.append((delta,r))
    if len(ranked)==1: return ranked[0][1]
    # Unknown durations or near ties remain ambiguous; do not pick a search rank blindly.
    if len(ranked)>1 and all(d is not None for d,r in ranked):
        ranked.sort(key=lambda x:x[0])
        if ranked[0][0]<=2000 and ranked[1][0]-ranked[0][0]>=3000: return ranked[0][1]
    return None


# Minimum seconds between uncached requests to the same host.
SPACING = {'musicbrainz.org':1.1, 'www.wikidata.org':1.1, 'api.deezer.com':0.25, 'lrclib.net':0.7}
# Deezer album genres too broad to stand for a track's genre; kept as labels only.
GENERIC_ALBUM_GENRES = {'latin music','brazilian music','world music','films/games','african music','asian music','kids','international pop'}
USER_AGENT = 'SpotifyProjectLocalPilot/0.1 (personal noncommercial research)'


class Enricher:
    def __init__(self, store, complements=True):
        self.store, self.lock, self.last = store, threading.Lock(), {}
        self.cooldowns = {}
        # Deezer (album genre) and LRCLIB (lyrics language). Off only in tests that mock MusicBrainz alone.
        self.complements = complements

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
                raise RemoteError(f'{host}: consultas pausadas. Aguarde {int(remaining)+1} segundos e clique em Consultar gêneros e idiomas. Suas revisões estão salvas.', retry_after=int(remaining)+1, transient=True)
            for attempt in range(3):
                time.sleep(max(0,SPACING.get(host,1.1)-(time.monotonic()-self.last.get(host,0))))
                try:
                    data = request_json(url, headers={'User-Agent':os.environ.get('MUSICBRAINZ_USER_AGENT',USER_AGENT), 'Accept':'application/json', 'Accept-Language':'en'}, timeout=12)
                    break
                except RemoteError as error:
                    if not error.transient: raise
                    # Only public metadata GETs are repeated; Spotify writes never enter this loop.
                    if attempt == 2 or error.retry_after > 10:
                        pause = max(60, error.retry_after)
                        self.cooldowns[host] = time.monotonic() + pause
                        raise RemoteError(f'{error} Consulta pausada após {attempt+1} tentativa(s). Aguarde {pause} segundos e clique em Consultar gêneros e idiomas para retomar. As músicas pendentes e suas revisões foram preservadas.', status=error.status, retry_after=pause, transient=True) from None
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
            return {'album_id':int(album), 'album':info.get('title') or (data.get('album') or {}).get('title',''), 'genres':list(dict.fromkeys(genres))}
        try:
            return self.cached('deezer-isrc:'+isrc.upper(), 30*86400, compute)
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

    def mb(self, entity, ident='', **params):
        return self.get('https://musicbrainz.org/ws/2/'+entity+'/'+ident+'?'+urllib.parse.urlencode({'fmt':'json',**params}))

    def wikidata_labels(self, target, prop):
        match = re.fullmatch(r'https?://www.wikidata.org/wiki/(Q\d+)', target or '')
        if not match: return []
        qid = match.group(1)
        entity = self.get('https://www.wikidata.org/wiki/Special:EntityData/'+qid+'.json')['entities'][qid]
        found = []
        for claim in entity.get('claims',{}).get(prop,[]):
            if claim.get('rank')=='deprecated': continue
            cid = claim.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id','')
            if not re.fullmatch(r'Q\d+',cid): continue
            labels = self.get('https://www.wikidata.org/wiki/Special:EntityData/'+cid+'.json')['entities'][cid].get('labels',{})
            label = next((labels[k]['value'] for k in ['pt','en'] if k in labels),None)
            if label: found.append(label)
        return found

    def find_artist(self, track, hits):
        """Conservative artist identity: agreement among recording hits, else one exact-name match."""
        ident = primary_artist_id(track, hits)
        if ident or not track.get('artists'): return ident
        name = track['artists'][0]
        clean = re.sub(r'[^\w\s]', ' ', name).strip()
        if not clean: return None
        found = self.mb('artist', query='artist:"'+clean+'"', limit=10).get('artists',[])
        exact = [a for a in found if norm(a.get('name','')) == norm(name)
                 or any(norm(x.get('name','')) == norm(name) for x in a.get('aliases',[]) or [])]
        return exact[0]['id'] if len(exact) == 1 else None

    def artist_genres(self, track, hits):
        """Genres of the primary artist. A hypothesis about the track, never evidence of it."""
        ident = self.find_artist(track, hits)
        if not ident: return [], [], [], None
        a = self.mb('artist', ident, inc='genres+url-rels')
        url = 'https://musicbrainz.org/artist/'+ident
        ranked = sorted((g for g in a.get('genres',[]) if g.get('name')), key=lambda g: -(g.get('count') or 0))
        genres = [g['name'] for g in ranked][:4]
        labels = [{'label':g,'kind':'artist-genre','source':'MusicBrainz (artista)','url':url} for g in genres]
        sources = [{'label':'MusicBrainz (artista: '+a.get('name', track['artists'][0])+')','url':url,'level':'artista'}]
        # Wikidata artist genres are always kept as labels (e.g. reggaeton for Bad Bunny); they only
        # become the main genre when MusicBrainz has none.
        for rel in a.get('relations',[]):
            target = rel.get('url',{}).get('resource','')
            wd = self.wikidata_labels(target,'P136')[:6]
            if wd:
                if not genres: genres = wd[:4]
                labels += [{'label':g,'kind':'artist-genre','source':'Wikidata (artista)','url':target} for g in wd]
                sources.append({'label':'Wikidata (artista)','url':target,'level':'artista'})
                break
        return list(dict.fromkeys(genres)), labels, sources, a.get('name')

    def enrich(self, track):
        hits, candidate = [], None
        if track.get('isrc'):
            found = self.mb('recording',query='isrc:'+track['isrc'],limit=25).get('recordings',[])
            hits += found
            candidate = choose_recording(track,found)
        if candidate is None:
            clean_artist = re.sub(r'[^\w\s]', ' ', (track['artists'] or [''])[0])
            query = 'recording:"'+title_key(track['title'])+'" AND artist:"'+clean_artist+'"'
            found = self.mb('recording',query=query,limit=25).get('recordings',[])
            hits += found
            candidate = choose_recording(track,found)
        genres, langs, sources, source_labels = [], [], [], []
        note = 'Rótulos originais das fontes preservados. Revise versão e classificação antes de confirmar.'
        if candidate is None:
            note = 'Gravação ambígua ou não encontrada.'
        else:
            r = self.mb('recording',candidate['id'],inc='genres+tags+work-rels+url-rels+isrcs')
            source_labels=[{'label':g['name'],'kind':kind,'source':'MusicBrainz','url':'https://musicbrainz.org/recording/'+r['id']} for field,kind in [('genres','genre'),('tags','tag')] for g in r.get(field,[]) if g.get('name')]
            genres = list(dict.fromkeys(g['name'] for g in r.get('genres',[]) if g.get('name')))
            sources = [{'label':'MusicBrainz (candidato)', 'url':'https://musicbrainz.org/recording/'+r['id'],'level':'faixa'}]
            language_codes = {'eng':'Inglês','spa':'Espanhol','fra':'Francês','fre':'Francês','por':'Português','jpn':'Japonês','kor':'Coreano','ita':'Italiano','deu':'Alemão','ger':'Alemão'}
            for rel in r.get('relations',[]):
                if 'work' in rel:
                    w = self.mb('work',rel['work']['id'])
                    langs += [language_codes.get(x,x) for x in w.get('languages',[]) if x not in ['und','mul','zxx']]
                    sources.append({'label':'MusicBrainz (obra)','url':'https://musicbrainz.org/work/'+w['id'],'level':'obra'})
                # Query structured Wikidata only when a direct MusicBrainz link exists.
                target = rel.get('url',{}).get('resource','')
                if re.fullmatch(r'https?://www.wikidata.org/wiki/(Q\d+)',target):
                    for prop,dest,kind in [('P136',genres,'genre'),('P407',langs,'language')]:
                        for label in self.wikidata_labels(target,prop):
                            dest.append(label if prop=='P136' else label.capitalize())
                            source_labels.append({'label':label,'kind':kind,'source':'Wikidata','url':target})
                    sources.append({'label':'Wikidata','url':target,'level':'faixa'})
        result = {'genres':list(dict.fromkeys(genres)), 'languages':list(dict.fromkeys(langs)), 'sources':sources,
                  'source_labels':source_labels,'labels_collected':True,'lookup':'done','artist_checked':True}
        if genres: result['genre_origin'] = 'faixa'
        if langs: result['language_origin'] = 'faixa'
        complete = True
        if self.complements and not genres and ORIGIN_RANK.get(infer_origin(track,'genre'),0) < ORIGIN_RANK['album']:
            album = self.deezer_album_genres(track)
            if album is None:
                complete = False
            elif album.get('genres'):
                url = 'https://www.deezer.com/album/'+str(album['album_id'])
                result['source_labels'] += [{'label':g,'kind':'album-genre','source':'Deezer (álbum)','url':url} for g in album['genres']]
                specific = [g for g in album['genres'] if norm(g) not in GENERIC_ALBUM_GENRES]
                if specific:
                    result.update(genres=specific, genre_origin='album')
                    result['sources'].append({'label':'Deezer (álbum: '+(album.get('album') or '?')+')','url':url,'level':'álbum'})
                    note = ('Sem gênero documentado para a faixa. ' if candidate else 'Gravação não identificada no MusicBrainz. ') + \
                           'Gênero do álbum no Deezer; confira se esta música segue o álbum.'
        if self.complements and not langs and ORIGIN_RANK.get(infer_origin(track,'language'),0) < ORIGIN_RANK['letra']:
            lyrics = self.lyrics_languages(track)
            if lyrics is None:
                complete = False
            elif lyrics.get('languages'):
                result.update(languages=lyrics['languages'], language_origin='letra')
                result['sources'].append({'label':'LRCLIB (idioma detectado na letra)','url':'https://lrclib.net/','level':'letra'})
                result['lyrics_note'] = 'Idioma detectado localmente na letra (LRCLIB): '+', '.join(lyrics['languages'])+'.'
        if self.complements and complete: result['complements_checked'] = True
        # The artist's genres are always collected as extra labels: Deezer album genres are coarse and
        # track genres can be sparse. They only become the main genre when nothing else is known.
        artist_genres, labels, artist_sources, artist_name = self.artist_genres(track, hits)
        result['source_labels'] += labels
        result['artist_labels'] = True
        if not result['genres'] and not track.get('genres'):
            if artist_genres:
                result.update(genres=artist_genres, artist_genres=artist_genres, genre_origin='artista')
                result['sources'] += artist_sources
                note = ('Sem gênero documentado para a faixa. ' if candidate else note+' ') + \
                       'Gênero sugerido pelo artista '+(artist_name or track['artists'][0])+'; confira se esta música segue o estilo do artista.'
            elif candidate is None:
                note += ' Classifique manualmente ou use o Ollama.'
        if result.get('lyrics_note'): note += ' '+result.pop('lyrics_note')
        result['lookup_note'] = note
        return result

def prepare_plan(store, account, api, targets):
    from core import desired_sets
    names = store.names(account)
    owned = {p['id']:p for p in api.playlists()}
    saved = store.targets(account)
    desired = desired_sets(store.tracks(account,active=True),names,store.rules(account))
    plans = []
    for name in names:
        ident = targets.get(name, saved.get(name,''))
        if ident and ident not in owned: raise ValueError('Destino indisponível ou não pertence a esta conta: '+name)
        present = api.contents(ident) if ident else set()
        plans.append({'name':name,'id':ident,'target_name':owned[ident]['name'] if ident else name,
                      'uris':sorted(desired[name]-present), 'already':len(desired[name]&present), 'total':len(desired[name])})
    ids = [p['id'] for p in plans if p['id']]
    if len(ids)!=len(set(ids)): raise ValueError('Escolha uma playlist de destino diferente para cada categoria.')
    return plans

def execute_plan(store, account, api, plans):
    """Add only. Re-read before every attempt; never blindly retry writes."""
    results = []
    for plan in plans:
        ident = plan['id']
        try:
            if not ident and not plan['uris']:
                results.append({'name':plan['name'],'added':0,'status':'Sem músicas; não criada'})
                continue
            if not ident:
                marker = 'Spotify Project '+hashlib.sha256((account+'\0'+plan['name']).encode()).hexdigest()[:20]
                # Recover a prior create whose response was lost, without reusing a same-name unrelated playlist.
                candidates = [p for p in api.playlists() if p.get('description')==marker]
                if len(candidates)>1: raise RemoteError('Há mais de uma playlist gerenciada com este identificador. Escolha o destino na prévia.')
                ident = candidates[0]['id'] if candidates else api.call('/me/playlists','POST',{'name':plan['name'],'public':False,'description':marker})['id']
                store.target(account,plan['name'],ident)
            else:
                owned = {p['id'] for p in api.playlists()}
                if ident not in owned: raise RemoteError('A playlist não pertence mais à conta conectada.')
                store.target(account,plan['name'],ident)
            present = api.contents(ident)
            remaining = sorted(set(plan['uris'])-present)
            added = 0
            for start in range(0,len(remaining),100):
                chunk = remaining[start:start+100]
                api.call('/playlists/'+ident+'/items','POST',{'uris':chunk})
                added += len(chunk)
            results.append({'name':plan['name'],'added':added,'status':'Atualizada','url':'https://open.spotify.com/playlist/'+ident})
        except (RemoteError,ValueError) as error:
            results.append({'name':plan['name'],'status':'Falha; prepare nova prévia','error':str(error)})
            break
    return results
