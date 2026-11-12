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
from core import broad, norm

class RemoteError(Exception): pass

def request_json(url, method='GET', body=None, headers=None, form=False):
    headers = dict(headers or {})
    data = None
    if body is not None:
        data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as e:
        if e.code == 429: raise RemoteError('Limite de consultas. Aguarde '+e.headers.get('Retry-After','60')+' segundos e tente novamente.') from None
        if e.code in (401,403): raise RemoteError(f'Acesso recusado ({e.code}). Reconecte a conta e confira as permissões e usuários autorizados do aplicativo.') from None
        raise RemoteError(f'O serviço respondeu HTTP {e.code}. Nenhuma repetição automática de gravação foi feita.') from None
    except (urllib.error.URLError, TimeoutError):
        message = 'Falha de rede ao consultar o serviço. O progresso foi preservado; tente novamente.' if method=='GET' else 'Falha de rede. Uma gravação pode ter sido recebida: prepare uma nova prévia antes de tentar novamente.'
        raise RemoteError(message) from None

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

    def contents(self, ident):
        present = set()
        for row in self.pages('/playlists/'+ident+'/items?limit=50'):
            item = (row or {}).get('item') or (row or {}).get('track') or {}
            if item.get('uri'): present.add(item['uri'])
            if item.get('linked_from',{}).get('uri'): present.add(item['linked_from']['uri'])
        return present

class Enricher:
    def __init__(self, store):
        self.store, self.lock, self.last = store, threading.Lock(), 0

    def get(self, url):
        key = hashlib.sha256(url.encode()).hexdigest()
        with self.store.connect() as db:
            cached = db.execute('SELECT data,expires FROM cache WHERE key=?',(key,)).fetchone()
        if cached and cached[1]>time.time(): return json.loads(cached[0])
        with self.lock:
            time.sleep(max(0,1.1-(time.monotonic()-self.last)))
            self.last = time.monotonic()
            data = request_json(url, headers={'User-Agent':os.environ.get('MUSICBRAINZ_USER_AGENT','SpotifyProjectLocalPilot/0.1 (personal noncommercial research)'), 'Accept':'application/json'})
        with self.store.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(key,json.dumps(data),time.time()+7*86400))
        return data

    def mb(self, entity, ident='', **params):
        return self.get('https://musicbrainz.org/ws/2/'+entity+'/'+ident+'?'+urllib.parse.urlencode({'fmt':'json',**params}))

    def enrich(self, track):
        query = 'isrc:'+track['isrc'] if track.get('isrc') else 'recording:"'+track['title'].replace('"','')+'" AND artist:"'+(track['artists'] or [''])[0].replace('"','')+'"'
        hits = self.mb('recording',query=query,limit=10).get('recordings',[])
        def compatible(r):
            if norm(r.get('title','')) != norm(track['title']): return False
            artists = [norm(a['artist']['name']) for a in r.get('artist-credit',[]) if 'artist' in a]
            return bool(track['artists']) and norm(track['artists'][0]) in artists
        candidates = [r for r in hits if compatible(r)]
        if len(candidates)!=1:
            return {'genres':[], 'languages':[], 'sources':[], 'lookup':'done', 'lookup_note':'Identidade ambígua ou não encontrada. Classifique manualmente.'}
        r = self.mb('recording',candidates[0]['id'],inc='genres+work-rels+url-rels+isrcs')
        genres = list(dict.fromkeys(x for g in r.get('genres',[]) if g.get('count',0)>0 for x in broad(g['name'])))
        langs, sources = [], [{'label':'MusicBrainz (candidato)', 'url':'https://musicbrainz.org/recording/'+r['id'],'level':'faixa'}]
        language_codes = {'eng':'Inglês','spa':'Espanhol','fra':'Francês','fre':'Francês','por':'Português','jpn':'Japonês','kor':'Coreano'}
        for rel in r.get('relations',[]):
            if 'work' in rel:
                w = self.mb('work',rel['work']['id'])
                langs += [language_codes.get(x,x) for x in w.get('languages',[]) if x not in ['und','mul','zxx']]
                sources.append({'label':'MusicBrainz (obra)','url':'https://musicbrainz.org/work/'+w['id'],'level':'obra'})
            # Query structured Wikidata only when a direct MusicBrainz link exists.
            target = rel.get('url',{}).get('resource','')
            match = re.fullmatch(r'https?://www.wikidata.org/wiki/(Q\d+)',target)
            if match:
                qid = match.group(1)
                entity = self.get('https://www.wikidata.org/wiki/Special:EntityData/'+qid+'.json')['entities'][qid]
                for prop,dest in [('P136',genres),('P407',langs)]:
                    for claim in entity.get('claims',{}).get(prop,[]):
                        if claim.get('rank')=='deprecated': continue
                        cid = claim.get('mainsnak',{}).get('datavalue',{}).get('value',{}).get('id','')
                        if not re.fullmatch(r'Q\d+',cid): continue
                        labels = self.get('https://www.wikidata.org/wiki/Special:EntityData/'+cid+'.json')['entities'][cid].get('labels',{})
                        label = next((labels[k]['value'] for k in ['pt','en'] if k in labels),None)
                        if label: dest.extend(broad(label) if prop=='P136' else [label.capitalize()])
                sources.append({'label':'Wikidata','url':target,'level':'faixa'})
        return {'genres':list(dict.fromkeys(genres)), 'languages':list(dict.fromkeys(langs)), 'sources':sources,
                'lookup':'done','lookup_note':'Candidato por título e artista. Revise versão e classificação antes de confirmar.'}

def prepare_plan(store, account, api, targets):
    from core import desired_sets
    names = store.names(account)
    owned = {p['id']:p for p in api.playlists()}
    saved = store.targets(account)
    desired = desired_sets(store.tracks(account,active=True),names)
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
