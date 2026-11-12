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

from core import Store, suggest
from providers import Enricher, RemoteError, Spotify, execute_plan, prepare_plan, request_json

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT','8765'))
ORIGIN = f'http://127.0.0.1:{PORT}'
REDIRECT = ORIGIN+'/callback'
STORE = Store(os.environ.get('SPOTIFY_PROJECT_DB',str(ROOT/'runtime/app.sqlite3')))
ENRICHER = Enricher(STORE)
SESSIONS = {}
LOCK = threading.RLock()
CLIENT_ID = os.environ.get('SPOTIFY_CLIENT_ID','')
SCOPE = 'user-library-read playlist-read-private playlist-modify-private playlist-modify-public'

def new_session():
    key = secrets.token_urlsafe(32)
    session = {'account':'demo:local','csrf':secrets.token_urlsafe(32), 'expires':time.time()+12*3600, 'revision':0}
    SESSIONS[key] = session
    if not STORE.tracks('demo:local'): STORE.seed('demo:local',ROOT/'data')
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

    def do_GET(self):
        with LOCK:
            try:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}': return self.send(403,{'error':'Use '+ORIGIN})
                s = self.session()
                url = urllib.parse.urlsplit(self.path)
                if url.path == '/api/state':
                    names = STORE.names(s['account'])
                    tracks = STORE.tracks(s['account'],active=True)
                    for t in tracks: t['destinations'] = suggest(t,names)
                    return self.send(data={'account':s['account'],'display_name':s.get('display_name','Piloto local'), 'connected':bool(s.get('token')),
                         'configured':bool(CLIENT_ID), 'redirect':REDIRECT, 'csrf':s['csrf'],'playlists':names,'tracks':tracks,'targets':STORE.targets(s['account'])})
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
                if size>200000 or not self.headers.get('Content-Type','').startswith('application/json'): raise ValueError('Requisição inválida.')
                data = json.loads(self.rfile.read(size) or b'{}')
                path = urllib.parse.urlsplit(self.path).path
                account = s['account']
                if path == '/api/config':
                    client = data.get('client_id','').strip()
                    if not re.fullmatch('[a-fA-F0-9]{32}',client): raise ValueError('Client ID inválido. Copie o identificador de 32 caracteres do Spotify.')
                    if any(v.get('token') for v in SESSIONS.values()): raise ValueError('Desconecte as contas antes de trocar o aplicativo.')
                    CLIENT_ID = client
                    for other in SESSIONS.values(): other.pop('oauth',None)
                    return self.send(data={'message':'Client ID configurado para esta execução. Agora conecte sua conta.'})
                if path == '/api/logout':
                    SESSIONS.pop(self.session_key,None)
                    self.new_cookie,_ = new_session()
                    return self.send(data={'message':'Conta desconectada. Tokens descartados da memória.'})
                if path == '/api/import':
                    if not s.get('token'): raise ValueError('Conecte o Spotify para importar sua biblioteca atual.')
                    count = STORE.import_tracks(account,self.api(s).library())
                    self.invalidate(account)
                    return self.send(data={'message':f'{count} músicas importadas. Suas revisões anteriores foram preservadas.'})
                if path == '/api/demo':
                    if s.get('token'): raise ValueError('Desconecte para usar o piloto local.')
                    STORE.seed(account,ROOT/'data',full=data.get('full') is True)
                    self.invalidate(account)
                    return self.send(data={'message':'Biblioteca local carregada.'})
                if path == '/api/pilot-review':
                    count = STORE.seed(account,ROOT/'data')
                    self.invalidate(account)
                    return self.send(data={'message':f'{count} revisões aplicadas às músicas correspondentes. Edições existentes foram preservadas.'})
                if path == '/api/names':
                    STORE.set_names(account,data.get('names'))
                    self.invalidate(account)
                    return self.send(data={'message':'Playlists salvas.'})
                if path == '/api/review':
                    STORE.review(account,data.get('id'),data)
                    self.invalidate(account)
                    return self.send(data={'message':'Revisão salva.'})
                if path == '/api/enrich':
                    tracks = STORE.tracks(account,active=True)
                    pending = [t for t in tracks if t['lookup']=='pending']
                    if not pending: return self.send(data={'remaining':0,'message':'Consulta concluída.'})
                    t = pending[0]
                    # No replacement of user's review, even when source suggestions change.
                    result = ENRICHER.enrich(t)
                    t.update(result)
                    STORE.put(account,t)
                    self.invalidate(account)
                    return self.send(data={'remaining':len(pending)-1,'message':'Consultada: '+t['title']})
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
                if path == '/api/execute':
                    plan = s.pop('plan',None)
                    if not s.get('token') or not plan or data.get('confirm') is not True or not secrets.compare_digest(plan['id'],str(data.get('id',''))) or plan['revision']!=s['revision'] or plan['expires']<time.time(): raise ValueError('Confirmação ausente ou prévia expirada. Prepare outra prévia.')
                    results = execute_plan(STORE,account,self.api(s),plan['plans'])
                    self.invalidate(account)
                    return self.send(data={'results':results,'message':'Execução encerrada. Confira o resultado de cada playlist.'})
                return self.send(404,{'error':'Operação não encontrada.'})
            except (ValueError,RemoteError) as error: self.send(400,{'error':str(error)})
            except Exception:
                self.send(500,{'error':'Falha interna. Prepare uma nova prévia antes de repetir qualquer gravação.'})

    def invalidate(self, account):
        for s in SESSIONS.values():
            if s['account']==account:
                s['revision'] += 1
                s.pop('plan',None)

if __name__ == '__main__':
    print('Spotify Project: '+ORIGIN,flush=True)
    print('Piloto local. Para encerrar: Ctrl+C. Tokens não são gravados em disco.',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
