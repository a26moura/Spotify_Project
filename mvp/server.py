"""Local pilot. Bind only to loopback; tokens stay in memory until logout/restart."""
import base64
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.parse

from core import Store, suggest, norm, routing_key, infer_origin, needs_complements, needs_artist_labels, needs_routing, has_evidence, reset_routing, merge_routing
from providers import Enricher, RemoteError, Spotify, clear_playlist, execute_plan, prepare_plan, request_json
from classification import Ollama, merge_metadata, sample_tracks, expanded_rules, missing_reason
import game
from collector import Collector

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT','8765'))
ORIGIN = f'http://127.0.0.1:{PORT}'
REDIRECT = ORIGIN+'/callback'
STORE = Store(os.environ.get('SPOTIFY_PROJECT_DB',str(ROOT/'runtime/app.sqlite3')))
ENRICHER = Enricher(STORE)
SESSIONS = {}
LOCK = threading.RLock()
COLLECTOR = Collector(STORE, ENRICHER, LOCK)
CONFIG_PATH = Path(os.environ.get('SPOTIFY_PROJECT_CONFIG', str(ROOT/'runtime/config.json')))
def load_client_id():
    if os.environ.get('SPOTIFY_CLIENT_ID'):
        return os.environ['SPOTIFY_CLIENT_ID']
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding='utf-8')).get('client_id', '')
        return value if isinstance(value, str) and re.fullmatch('[a-fA-F0-9]{32}', value) else ''
    except (OSError, ValueError, AttributeError):
        return ''
CLIENT_ID = load_client_id()
METADATA_PATH = Path(os.environ.get('SPOTIFY_METADATA_CONFIG',str(ROOT/'runtime/metadata.json')))
def load_ollama_model():
    try:
        value=os.environ.get('OLLAMA_MODEL') or json.loads(METADATA_PATH.read_text(encoding='utf-8')).get('ollama_model','')
        return value if isinstance(value,str) and len(value)<=200 else ''
    except (OSError,ValueError,AttributeError):return ''
OLLAMA = Ollama(STORE,load_ollama_model())
SCOPE = 'user-library-read playlist-read-private playlist-modify-private playlist-modify-public'

def new_session():
    key = secrets.token_urlsafe(32)
    session = {'account':'demo:local','csrf':secrets.token_urlsafe(32), 'expires':time.time()+12*3600, 'revision':0}
    SESSIONS[key] = session
    STORE.names('demo:local')
    return key, session

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # OAuth authorization codes must not appear in request logs.

    def session(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie',''))
        except Exception: pass
        key = cookie['sp_session'].value if 'sp_session' in cookie else ''
        session = SESSIONS.get(key)
        if not session or session['expires']<time.time():
            SESSIONS.pop(key,None)
            key,session = new_session()
            self.new_cookie = key
        self.session_key = key
        return session

    def send(self, status=200, data=None, content_type='application/json; charset=utf-8', location=None):
        body = json.dumps(data,ensure_ascii=False).encode() if content_type.startswith('application/json') else (data.encode() if isinstance(data,str) else data or b'')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if getattr(self,'new_cookie',None): self.send_header('Set-Cookie','sp_session='+self.new_cookie+'; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200')
        if location: self.send_header('Location',location)
        self.end_headers()
        self.wfile.write(body)

    def api(self,s): return Spotify(s,CLIENT_ID,REDIRECT)

    def preview(self):
        """Deezer preview link for one track. The network call runs outside the global lock so the
        game stays responsive."""
        try:
            with LOCK:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}': return self.send(403,{'error':'Use '+ORIGIN})
                s = self.session()
                ident = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('id',[''])[0]
                track = next((t for t in STORE.tracks(s['account'],active=True) if t['id']==ident),None)
            if not track: return self.send(404,{'error':'Música não encontrada.'})
            try: url = ENRICHER.preview(track)
            except RemoteError: url = None
            return self.send(data={'url':url})
        except Exception:
            return self.send(500,{'error':'Falha ao buscar a prévia.'})

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == '/api/preview': return self.preview()
        with LOCK:
            try:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}': return self.send(403,{'error':'Use '+ORIGIN})
                s = self.session()
                url = urllib.parse.urlsplit(self.path)
                if url.path == '/api/state':
                    names = STORE.names(s['account'])
                    tracks = STORE.tracks(s['account'],active=True)
                    rules = STORE.rules(s['account'])
                    for t in tracks:
                        t['destinations'] = suggest(t,names,rules)
                        t['genre_origin'],t['language_origin']=infer_origin(t,'genre'),infer_origin(t,'language')
                        t['routing_pending']=needs_routing(t,rules,OLLAMA.model)
                    return self.send(data={'account':s['account'],'display_name':s.get('display_name','Piloto local'), 'connected':bool(s.get('token')),
                         'configured':bool(CLIENT_ID), 'redirect':REDIRECT, 'csrf':s['csrf'],'playlists':names,'rules':rules,'tracks':tracks,'targets':STORE.targets(s['account']),
                         'ollama_configured':bool(OLLAMA.model), 'ollama_model':OLLAMA.model,
                         'spotify_library':STORE.spotify_library(s['account']), 'needs_sync':bool(s.get('token')) and not s.get('synced',False),
                         'sample_available':False})
                if url.path == '/api/collect-status':
                    return self.send(data=COLLECTOR.status(s['account']))
                if url.path == '/auth/start':
                    if not CLIENT_ID: raise ValueError('Configure o Client ID primeiro.')
                    verifier = secrets.token_urlsafe(64)
                    state = secrets.token_urlsafe(32)
                    s['oauth'] = {'state':state,'verifier':verifier,'expires':time.time()+600}
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                    params = {'client_id':CLIENT_ID,'response_type':'code','redirect_uri':REDIRECT,'scope':SCOPE,'state':state,'code_challenge_method':'S256','code_challenge':challenge,'show_dialog':'true'}
                    return self.send(302,{},location='https://accounts.spotify.com/authorize?'+urllib.parse.urlencode(params))
                if url.path == '/callback':
                    params = urllib.parse.parse_qs(url.query)
                    oauth = s.pop('oauth',{})
                    if oauth.get('expires',0)<time.time() or not secrets.compare_digest(oauth.get('state',''),params.get('state',[''])[0]): raise ValueError('Login expirado ou inválido. Conecte novamente.')
                    if 'error' in params: raise ValueError('A conexão não foi autorizada.')
                    code = params.get('code',[''])[0]
                    if not code: raise ValueError('Código de autorização ausente.')
                    token = request_json('https://accounts.spotify.com/api/token','POST',{'grant_type':'authorization_code','code':code,'redirect_uri':REDIRECT,'client_id':CLIENT_ID,'code_verifier':oauth['verifier']},form=True)
                    token['expires_at'] = time.time()+token['expires_in']
                    fresh = {'token':token}
                    profile = self.api(fresh).call('/me')
                    with STORE.connect() as db:
                        existing_account = db.execute('SELECT 1 FROM accounts WHERE id=?', (profile['id'],)).fetchone()
                    if not existing_account:
                        # Carry the user's setup into their first login, never the personal track reviews.
                        STORE.set_rules(profile['id'], STORE.rules(s['account']))
                    new_key = secrets.token_urlsafe(32)
                    fresh.update(account=profile['id'],display_name=profile.get('display_name') or profile['id'], csrf=secrets.token_urlsafe(32),expires=time.time()+12*3600,revision=0)
                    SESSIONS[new_key] = fresh
                    SESSIONS.pop(self.session_key,None)
                    self.new_cookie = new_key
                    STORE.names(fresh['account'])
                    return self.send(302,{},location='/')
                files = {'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','application/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
                if url.path in files:
                    file,mime = files[url.path]
                    return self.send(data=(ROOT/'static'/file).read_bytes(), content_type=mime)
                return self.send(404,{'error':'Página não encontrada.'})
            except (ValueError,RemoteError) as error: self.send(400,{'error':str(error)})
            except Exception:
                self.send(500,{'error':'Falha interna. Os dados salvos foram preservados. Verifique o aplicativo local.'})

    def do_POST(self):
        global CLIENT_ID
        with LOCK:
            try:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}' or self.headers.get('Origin') != ORIGIN: return self.send(403,{'error':'Origem não permitida.'})
                s = self.session()
                if not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),s['csrf']): return self.send(403,{'error':'Recarregue a página para continuar.'})
                size = int(self.headers.get('Content-Length','0'))
                if not 0 <= size <= 200000 or not self.headers.get('Content-Type','').startswith('application/json'): raise ValueError('Requisição inválida.')
                data = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data, dict): raise ValueError('Requisição inválida.')
                path = urllib.parse.urlsplit(self.path).path
                account = s['account']
                if path == '/api/labels-start':
                    count=0
                    for t in STORE.tracks(account,active=True):
                        if not t.get('review'):
                            t['routing_required']=True
                            if not t.get('labels_collected') or not t.get('genres') and not t.get('artist_checked') or needs_complements(t) or needs_artist_labels(t):t['lookup']='pending'
                            if t.get('lookup')=='pending':count+=1
                            STORE.put(account,t)
                    self.invalidate(account)
                    return self.send(data={'count':count,'message':'Coleta de rótulos preparada, independente das playlists.'})
                if path == '/api/ai-fill-start':
                    if not OLLAMA.model:raise ValueError('Selecione um modelo Ollama local.')
                    count=0
                    for t in STORE.tracks(account,active=True):
                        if not t.get('review') and t.get('lookup')=='done' and (not t.get('genres') or not t.get('languages')) and t.get('ai_checked')!=OLLAMA.model:
                            t['lookup']='pending';STORE.put(account,t);count+=1
                    self.invalidate(account)
                    return self.send(data={'count':count,'message':f'{count} músicas sem gênero ou idioma preparadas para o Ollama.'})
                if path == '/api/route-start':
                    if not STORE.rules(account):raise ValueError('Defina suas playlists antes da distribuição local.')
                    if not OLLAMA.model:raise ValueError('Selecione um modelo Ollama local.')
                    for t in STORE.tracks(account,active=True):
                        if not t.get('review'):
                            t['routing_required']=True;STORE.put(account,t)
                    self.invalidate(account)
                    return self.send(data={'message':'Distribuição local preparada.'})
                if path == '/api/route-step':
                    rules=STORE.rules(account)
                    if not rules:raise ValueError('Defina suas playlists antes da distribuição local.')
                    # Tracks without any genre/language are not sent: the model would guess from names.
                    pending=[t for t in STORE.tracks(account,active=True) if needs_routing(t,rules,OLLAMA.model)]
                    if not pending:return self.send(data={'remaining':0,'message':'Distribuição local concluída.'})
                    t=pending[0]
                    previous=t.get('routing') or {}
                    redo=[r for r in rules if r['name'] in previous.get('redo',[])]
                    if redo and previous.get('key')==routing_key(t,rules) and previous.get('model')==OLLAMA.model:
                        # Only the playlists reset by the user are asked again; other decisions stay.
                        result=merge_routing(t,rules,previous,OLLAMA.route(t,redo))
                    else:result=OLLAMA.route(t,rules)
                    t['routing_required']=True;t['routing']=result
                    STORE.put(account,t);self.invalidate(account)
                    return self.send(data={'remaining':len(pending)-1,'message':'Playlists avaliadas: '+t['title'],'track':{'id':t['id'],'title':t['title'],'artists':t['artists']},'note':'; '.join(d['playlist']+': '+d['verdict'] for d in result['decisions'])})
                if path == '/api/collect-start':
                    started=COLLECTOR.start(account)
                    return self.send(data=dict(COLLECTOR.status(account),started=started))
                if path == '/api/sync-start':
                    if not s.get('token'):raise ValueError('Conecte o Spotify para carregar sua biblioteca.')
                    api=self.api(s)
                    liked=api.library()
                    playlists=api.playlists()  # only your own playlists
                    s['sync']={'id':secrets.token_urlsafe(24),'liked':liked,'queue':playlists,'playlists':[],'extra':[], 'expires':time.time()+3600}
                    return self.send(data={'id':s['sync']['id'],'remaining':len(playlists),'message':f'{len(liked)} curtidas carregadas. Lendo {len(playlists)} playlists…'})
                if path == '/api/sync-step':
                    sync=s.get('sync')
                    if not s.get('token') or not sync or sync['expires']<time.time() or not secrets.compare_digest(sync['id'],str(data.get('id',''))):raise ValueError('Sincronização expirada. Inicie novamente.')
                    if sync['queue']:
                        p=sync['queue'][0]
                        entry={'id':p['id'],'name':p.get('name','Playlist'),'description':p.get('description') or '','snapshot_id':p.get('snapshot_id'),'owned':True,'tracks':[],'unavailable':False}
                        try:
                            items=self.api(s).playlist_tracks(p['id'])
                            entry['tracks']=[{'id':t.get('id'),'uri':t.get('uri'),'title':t.get('name',''),'artists':[a['name'] for a in t.get('artists',[])]} for t in items]
                            sync['extra'].extend(items)
                        except RemoteError as error:
                            if error.status not in (403,404):raise
                            entry['unavailable']=True
                        sync['playlists'].append(entry);sync['queue'].pop(0)
                    if sync['queue']:return self.send(data={'remaining':len(sync['queue']),'message':f'Playlists carregadas: {len(sync["playlists"])}. Restantes: {len(sync["queue"])}.'})
                    count=STORE.import_tracks(account,sync['liked'],sync['extra'])
                    STORE.save_spotify_library(account,{'playlists':sync['playlists'],'synced_at':time.time()})
                    game.sync_profiles(STORE,account,[p for p in sync['playlists'] if not p['unavailable']])
                    s['synced']=True;s.pop('sync',None);self.invalidate(account)
                    COLLECTOR.start(account)
                    return self.send(data={'remaining':0,'message':f'{count} músicas ({len(sync["liked"])} curtidas) e {len(sync["playlists"])} playlists sincronizadas. Classificações anteriores preservadas.'})
                if path == '/api/adopt-playlist':
                    playlist=next((p for p in STORE.spotify_library(account)['playlists'] if p['id']==data.get('id') and p['owned']),None)
                    if not playlist:raise ValueError('Sincronize e escolha uma playlist da sua conta.')
                    rules=STORE.rules(account);targets=STORE.targets(account)
                    if playlist['id'] in targets.values():return self.send(data={'message':'Esta playlist já está configurada.'})
                    name=playlist['name'][:80] or 'Playlist'
                    if any(norm(r['name'])==norm(name) for r in rules):
                        raise ValueError('Já existe um critério com este nome. Use a escolha de destinos para vincular a playlist existente.')
                    STORE.set_rules(account,rules+[{'name':name,'description':(playlist.get('description') or '')[:1000],'genres':[],'languages':[],'artists':[]}])
                    STORE.target(account,name,playlist['id']);self.invalidate(account)
                    return self.send(data={'message':'Playlist vinculada. Defina os critérios para distribuir novas músicas nela.'})
                if path == '/api/ollama-models':
                    return self.send(data={'models':[m['name'] for m in OLLAMA.models()]})
                if path == '/api/metadata-config':
                    model=data.get('ollama_model','')
                    if not isinstance(model,str) or not model or len(model)>200:raise ValueError('Selecione um modelo local instalado.')
                    if model not in [m['name'] for m in OLLAMA.models()]:raise ValueError('Modelo local não encontrado no Ollama.')
                    METADATA_PATH.parent.mkdir(parents=True,exist_ok=True)
                    temporary=METADATA_PATH.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'ollama_model':model}),encoding='utf-8')
                    temporary.replace(METADATA_PATH)
                    OLLAMA.model=model
                    for session in SESSIONS.values(): session.pop('experiment',None)
                    return self.send(data={'message':'Modelo local salvo. Faça o teste de 30 músicas e revise os resultados.'})
                if path == '/api/extra-rules':
                    STORE.set_rules(account,expanded_rules(STORE.rules(account)))
                    self.invalidate(account)
                    return self.send(data={'message':'Critérios de Eletrônica, Hip-Hop/Rap e Metal adicionados. Nenhuma playlist foi criada no Spotify.'})
                if path == '/api/retry-unclassified':
                    only_empty=data.get('only_empty') is True
                    names,rules=STORE.names(account),STORE.rules(account)
                    count=0
                    for t in STORE.tracks(account,active=True):
                        if not t.get('review') and not suggest(t,names,rules) and (not only_empty or not t.get('genres') and not t.get('languages')):
                            t['lookup']='pending';STORE.put(account,t);count+=1
                    self.invalidate(account)
                    return self.send(data={'count':count,'message':f'{count} músicas sem revisão preparadas para nova consulta.'})
                if path == '/api/experiment-start':
                    source=data.get('source','saved')
                    if source not in ('saved','ollama','musicbrainz'):raise ValueError('Fonte inválida.')
                    if source=='ollama' and not OLLAMA.model:raise ValueError('Selecione um modelo do Ollama antes do teste.')
                    names,rules=STORE.names(account),STORE.rules(account)
                    sample=sample_tracks(STORE.tracks(account,active=True),names,rules)
                    s['experiment']={'id':secrets.token_urlsafe(24),'source':source,'queue':sample,'results':[],
                        'revision':s['revision'],'rules':expanded_rules(rules),'old_rules':rules,'expires':time.time()+3600}
                    return self.send(data={'id':s['experiment']['id'],'total':len(sample),'source':source,'next_track':sample[0] if sample else None})
                if path in ('/api/experiment-step','/api/experiment-apply'):
                    experiment=s.get('experiment')
                    if not experiment or experiment['expires']<time.time() or not secrets.compare_digest(experiment['id'],str(data.get('id',''))) or experiment['revision']!=s['revision']:
                        raise ValueError('Teste expirado ou biblioteca alterada. Inicie um novo teste.')
                    if path.endswith('apply'):
                        if experiment['queue'] or data.get('confirm') is not True:raise ValueError('Conclua e confira o teste antes de aplicar.')
                        # Same account/revision, serialized by LOCK; current reviews are never overwritten.
                        for row in experiment['results']:
                            if experiment['source']!='saved':STORE.put(account,row['track'])
                        STORE.set_rules(account,experiment['rules'])
                        s.pop('experiment',None);self.invalidate(account)
                        return self.send(data={'message':'Resultados e novos critérios aplicados localmente. Revise antes de salvar no Spotify.'})
                    if experiment['queue']:
                        t=experiment['queue'][0]
                        started=time.monotonic()
                        result=OLLAMA.enrich(t) if experiment['source']=='ollama' else ENRICHER.enrich(t) if experiment['source']=='musicbrainz' else {}
                        updated=merge_metadata(t,result)
                        experiment['results'].append({'track':updated,'seconds':round(time.monotonic()-started,2),
                            'reason':missing_reason(t,[r['name'] for r in experiment['old_rules']],experiment['old_rules']),
                            'before':suggest(t,[r['name'] for r in experiment['old_rules']],experiment['old_rules']),
                            'after':suggest(updated,[r['name'] for r in experiment['rules']],experiment['rules'])})
                        experiment['queue'].pop(0)
                    rows=experiment['results']
                    public=[dict(id=r['track']['id'],title=r['track']['title'],artists=r['track']['artists'],genres=r['track'].get('genres',[]),
                        languages=r['track'].get('languages',[]),artist_genres=r['track'].get('artist_genres',[]),note=r['track'].get('lookup_note',''),
                        before=r['before'],after=r['after'],reason=r['reason'],seconds=r['seconds']) for r in rows]
                    return self.send(data={'remaining':len(experiment['queue']),'results':public,'source':experiment['source'],
                        'assigned':sum(bool(r['after']) for r in rows),'artist_suggestions':sum(bool(r['track'].get('artist_genres')) for r in rows),
                        'seconds':round(sum(r['seconds'] for r in rows),2),'next_track':experiment['queue'][0] if experiment['queue'] else None})
                if path == '/api/config':
                    client = data.get('client_id','').strip()
                    if not re.fullmatch('[a-fA-F0-9]{32}',client): raise ValueError('Client ID inválido. Copie o identificador de 32 caracteres do Spotify.')
                    if any(v.get('token') for v in SESSIONS.values()): raise ValueError('Desconecte as contas antes de trocar o aplicativo.')
                    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                    temporary = CONFIG_PATH.with_suffix('.tmp')
                    temporary.write_text(json.dumps({'client_id':client}), encoding='utf-8')
                    temporary.replace(CONFIG_PATH)
                    CLIENT_ID = client
                    for other in SESSIONS.values(): other.pop('oauth',None)
                    return self.send(data={'message':'Client ID salvo neste computador. Agora conecte sua conta.'})
                if path == '/api/logout':
                    SESSIONS.pop(self.session_key,None)
                    self.new_cookie,_ = new_session()
                    return self.send(data={'message':'Conta desconectada. Tokens descartados da memória.'})
                if path == '/api/import':
                    if not s.get('token'): raise ValueError('Conecte o Spotify para importar sua biblioteca atual.')
                    count = STORE.import_tracks(account,self.api(s).library())
                    self.invalidate(account)
                    return self.send(data={'message':f'{count} músicas importadas. Suas revisões anteriores foram preservadas.'})
                if path in ('/api/demo','/api/pilot-review'):
                    raise ValueError('Amostras de teste desativadas. Conecte o Spotify para importar suas músicas.')
                if path == '/api/names':
                    STORE.set_names(account,data.get('names'))
                    self.invalidate(account)
                    return self.send(data={'message':'Playlists salvas.'})
                if path == '/api/rules':
                    STORE.set_rules(account,data.get('rules'))
                    self.invalidate(account)
                    return self.send(data={'message':'Critérios salvos. A distribuição foi recalculada; escolhas manuais foram preservadas.'})
                if path == '/api/review':
                    STORE.review(account,data.get('id'),data)
                    self.invalidate(account)
                    return self.send(data={'message':'Revisão salva.'})
                if path == '/api/enrich':
                    tracks = STORE.tracks(account,active=True)
                    pending = [t for t in tracks if t['lookup']=='pending' and not t.get('review')]
                    if data.get('only_empty') is True:
                        names,rules=STORE.names(account),STORE.rules(account)
                        pending=[t for t in pending if not t.get('genres') and not t.get('languages') and not suggest(t,names,rules)]
                    if not pending: return self.send(data={'remaining':0,'message':'Consulta concluída.'})
                    t = pending[0]
                    # No replacement of user's review, even when source suggestions change.
                    source=data.get('source','ollama')
                    if source not in ('ollama','musicbrainz'):raise ValueError('Fonte inválida.')
                    started=time.monotonic()
                    try:
                        result = (OLLAMA.enrich(t,force=True) if data.get('only_empty') is True else OLLAMA.enrich(t)) if source=='ollama' else ENRICHER.enrich(t)
                    except RemoteError as error:
                        # An invalid answer for one track must not block the rest of the library.
                        if source!='ollama' or not str(error).startswith('O modelo retornou'):raise
                        result={'lookup':'done','ai_checked':OLLAMA.model,'lookup_note':(t.get('lookup_note') or '').split(' · IA: ')[0]+' · IA: resposta inválida do modelo; classifique manualmente.'}
                    t=merge_metadata(t,result)
                    STORE.put(account,t)
                    self.invalidate(account)
                    return self.send(data={'remaining':len(pending)-1,'message':'Consultada: '+t['title'],'track':{'id':t['id'],'title':t['title'],'artists':t['artists']},'seconds':round(time.monotonic()-started,2),'note':t.get('lookup_note','')})
                if path == '/api/targets':
                    if not s.get('token'): raise ValueError('Conecte sua conta para escolher destinos existentes.')
                    owned = self.api(s).playlists()
                    return self.send(data={'playlists':[{'id':p['id'],'name':p['name']} for p in owned]})
                if path == '/api/plan':
                    if not s.get('token'): raise ValueError('A amostra local não grava no Spotify. Conecte e importe sua conta primeiro.')
                    targets = data.get('targets',{})
                    if not isinstance(targets,dict) or any(k not in STORE.names(account) or not isinstance(v,str) for k,v in targets.items()): raise ValueError('Destinos inválidos.')
                    plans = prepare_plan(STORE,account,self.api(s),targets)
                    ident = secrets.token_urlsafe(32)
                    s['plan'] = {'id':ident,'revision':s['revision'],'expires':time.time()+600,'plans':plans}
                    titles = {t['uri']:t['title'] for t in STORE.tracks(account)}
                    public = [dict(p,tracks=[{'uri':uri,'title':titles.get(uri,uri)} for uri in p['uris']]) for p in plans]
                    return self.send(data={'id':ident,'plans':public,'message':'Revise e confirme. Apenas adições serão realizadas.'})
                if path == '/api/routing-reset':
                    name=data.get('name')
                    if name not in STORE.names(account):raise ValueError('Playlist não encontrada nos critérios.')
                    count=0
                    for t in STORE.tracks(account):
                        if reset_routing(t,name):STORE.put(account,t);count+=1
                    self.invalidate(account)
                    return self.send(data={'count':count,'message':f'Decisões do Ollama para "{name}" apagadas só no app ({count} músicas). Nada mudou no Spotify. Clique em "Organizar nas playlists" (etapa 2) para reavaliar.'})
                if path == '/api/clear-preview':
                    if not s.get('token'): raise ValueError('Conecte sua conta para esvaziar uma playlist.')
                    api=self.api(s)
                    playlist=next((p for p in api.playlists() if p['id']==data.get('id')),None)
                    if not playlist: raise ValueError('Escolha uma playlist da sua conta.')
                    items=api.playlist_tracks(playlist['id'])
                    uris=api.contents(playlist['id'])
                    ident=secrets.token_urlsafe(32)
                    s['clear']={'id':ident,'playlist':playlist['id'],'name':playlist.get('name','Playlist'),'uris':sorted(uris),'expires':time.time()+600}
                    return self.send(data={'id':ident,'name':s['clear']['name'],'count':len(items),
                        'tracks':[{'title':t.get('name',''),'artists':[a['name'] for a in t.get('artists',[])]} for t in items],
                        'message':'Confira antes de confirmar. Todas as músicas desta playlist serão removidas no Spotify.'})
                if path == '/api/clear-execute':
                    pending=s.pop('clear',None)
                    if not s.get('token') or not pending or data.get('confirm') is not True or not secrets.compare_digest(pending['id'],str(data.get('id',''))) or pending['expires']<time.time():
                        raise ValueError('Confirmação ausente ou prévia expirada. Prepare outra prévia.')
                    removed=clear_playlist(self.api(s),pending['playlist'],pending['uris'])
                    library=STORE.spotify_library(account)
                    for p in library['playlists']:
                        if p['id']==pending['playlist']:p['tracks']=[]
                    STORE.save_spotify_library(account,library)
                    self.invalidate(account)
                    return self.send(data={'removed':removed,'message':f'Playlist "{pending["name"]}" esvaziada no Spotify ({removed} músicas removidas). Use "Organizar nas playlists" (etapa 2) para preenchê-la de novo.'})
                if path == '/api/execute':
                    plan = s.pop('plan',None)
                    if not s.get('token') or not plan or data.get('confirm') is not True or not secrets.compare_digest(plan['id'],str(data.get('id',''))) or plan['revision']!=s['revision'] or plan['expires']<time.time(): raise ValueError('Confirmação ausente ou prévia expirada. Prepare outra prévia.')
                    results = execute_plan(STORE,account,self.api(s),plan['plans'])
                    self.invalidate(account)
                    return self.send(data={'results':results,'message':'Execução encerrada. Confira o resultado de cada playlist.'})
                return self.send(404,{'error':'Operação não encontrada.'})
            except (ValueError,RemoteError) as error: self.send(400,{'error':str(error),'retry_after':getattr(error,'retry_after',0),'transient':getattr(error,'transient',False)})
            except Exception:
                self.send(500,{'error':'Falha interna. Prepare uma nova prévia antes de repetir qualquer gravação.'})

    def invalidate(self, account):
        for s in SESSIONS.values():
            if s['account']==account:
                s['revision'] += 1
                s.pop('plan',None)

if __name__ == '__main__':
    import sys
    import webbrowser
    print('Spotify Project: '+ORIGIN,flush=True)
    print('Piloto local. Para encerrar: Ctrl+C. Tokens não são gravados em disco.',flush=True)
    try:
        http = ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    except OSError:
        print('Não foi possível iniciar. A porta '+str(PORT)+' pode estar ocupada. Feche a execução anterior e tente novamente.',flush=True)
        raise SystemExit(1)
    if '--open-browser' in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(ORIGIN)).start()
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
