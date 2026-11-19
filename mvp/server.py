"""Servidor local do jogo. Escuta só em 127.0.0.1; tokens ficam na memória até sair ou reiniciar.

Fluxo: conectar → sincronizar (curtidas + suas playlists) → montar playlists → jogo → prévia →
gravar no Spotify. Só /api/publish-execute grava no Spotify, e só com uma prévia confirmada.
"""
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

from core import Store
from providers import Enricher, RemoteError, Spotify, request_json
from collector import Collector
import game
import publish

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT', '8765'))
ORIGIN = f'http://127.0.0.1:{PORT}'
REDIRECT = ORIGIN + '/callback'
STORE = Store(os.environ.get('SPOTIFY_PROJECT_DB', str(ROOT / 'runtime/app.sqlite3')))
ENRICHER = Enricher(STORE)
SESSIONS = {}
LOCK = threading.RLock()
COLLECTOR = Collector(STORE, ENRICHER, LOCK)
CONFIG_PATH = Path(os.environ.get('SPOTIFY_PROJECT_CONFIG', str(ROOT / 'runtime/config.json')))
SCOPE = 'user-library-read playlist-read-private playlist-modify-private playlist-modify-public'
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://i.scdn.co; "
       "media-src https://*.dzcdn.net; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
FILES = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
         '/style.css': ('style.css', 'text/css; charset=utf-8')}


def load_client_id():
    if os.environ.get('SPOTIFY_CLIENT_ID'):
        return os.environ['SPOTIFY_CLIENT_ID']
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding='utf-8')).get('client_id', '')
        return value if isinstance(value, str) and re.fullmatch('[a-fA-F0-9]{32}', value) else ''
    except (OSError, ValueError, AttributeError):
        return ''


CLIENT_ID = load_client_id()


def new_session():
    key = secrets.token_urlsafe(32)
    session = {'account': 'demo:local', 'csrf': secrets.token_urlsafe(32), 'expires': time.time() + 12 * 3600, 'revision': 0}
    SESSIONS[key] = session
    return key, session


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass  # OAuth authorization codes must not appear in request logs.

    def session(self):
        cookie = SimpleCookie()
        try: cookie.load(self.headers.get('Cookie', ''))
        except Exception: pass
        key = cookie['sp_session'].value if 'sp_session' in cookie else ''
        session = SESSIONS.get(key)
        if not session or session['expires'] < time.time():
            SESSIONS.pop(key, None)
            key, session = new_session()
            self.new_cookie = key
        self.session_key = key
        return session

    def send(self, status=200, data=None, content_type='application/json; charset=utf-8', location=None):
        body = json.dumps(data, ensure_ascii=False).encode() if content_type.startswith('application/json') else (data.encode() if isinstance(data, str) else data or b'')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        if getattr(self, 'new_cookie', None): self.send_header('Set-Cookie', 'sp_session=' + self.new_cookie + '; HttpOnly; SameSite=Lax; Path=/; Max-Age=43200')
        if location: self.send_header('Location', location)
        self.end_headers()
        self.wfile.write(body)

    def api(self, s): return Spotify(s, CLIENT_ID, REDIRECT)

    def invalidate(self, account):
        """Any change to choices or playlists makes a pending preview invalid."""
        for s in SESSIONS.values():
            if s['account'] == account:
                s['revision'] += 1
                s.pop('publish', None)

    # ---------- GET ----------

    def preview(self):
        """Deezer preview link for one track. The network call runs outside the global lock so the
        game stays responsive."""
        try:
            with LOCK:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}': return self.send(403, {'error': 'Use ' + ORIGIN})
                s = self.session()
                ident = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('id', [''])[0]
                track = next((t for t in STORE.tracks(s['account'], active=True) if t['id'] == ident), None)
            if not track: return self.send(404, {'error': 'Música não encontrada.'})
            try: url = ENRICHER.preview(track)
            except RemoteError: url = None
            return self.send(data={'url': url})
        except Exception:
            return self.send(500, {'error': 'Falha ao buscar a prévia.'})

    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == '/api/preview': return self.preview()
        with LOCK:
            try:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}': return self.send(403, {'error': 'Use ' + ORIGIN})
                s = self.session()
                url = urllib.parse.urlsplit(self.path)
                a = s['account']
                if url.path == '/api/game':
                    return self.send(data=dict(game.overview(STORE, a), account=a, display_name=s.get('display_name', 'Piloto local'),
                        connected=bool(s.get('token')), configured=bool(CLIENT_ID), redirect=REDIRECT, csrf=s['csrf'],
                        needs_sync=bool(s.get('token')) and not s.get('synced', False),
                        synced_at=STORE.spotify_library(a).get('synced_at'), collect=COLLECTOR.status(a)))
                if url.path == '/api/game-card':
                    ident = urllib.parse.parse_qs(url.query).get('id', [None])[0]
                    return self.send(data=game.card(STORE, a, ident))
                if url.path == '/api/collect-status':
                    return self.send(data=COLLECTOR.status(a))
                if url.path == '/auth/start':
                    if not CLIENT_ID: raise ValueError('Configure o Client ID primeiro.')
                    verifier = secrets.token_urlsafe(64)
                    state = secrets.token_urlsafe(32)
                    s['oauth'] = {'state': state, 'verifier': verifier, 'expires': time.time() + 600}
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                    params = {'client_id': CLIENT_ID, 'response_type': 'code', 'redirect_uri': REDIRECT, 'scope': SCOPE, 'state': state,
                              'code_challenge_method': 'S256', 'code_challenge': challenge, 'show_dialog': 'true'}
                    return self.send(302, {}, location='https://accounts.spotify.com/authorize?' + urllib.parse.urlencode(params))
                if url.path == '/callback':
                    params = urllib.parse.parse_qs(url.query)
                    oauth = s.pop('oauth', {})
                    if oauth.get('expires', 0) < time.time() or not secrets.compare_digest(oauth.get('state', ''), params.get('state', [''])[0]):
                        raise ValueError('Login expirado ou inválido. Conecte novamente.')
                    if 'error' in params: raise ValueError('A conexão não foi autorizada.')
                    code = params.get('code', [''])[0]
                    if not code: raise ValueError('Código de autorização ausente.')
                    token = request_json('https://accounts.spotify.com/api/token', 'POST', {'grant_type': 'authorization_code', 'code': code,
                        'redirect_uri': REDIRECT, 'client_id': CLIENT_ID, 'code_verifier': oauth['verifier']}, form=True)
                    token['expires_at'] = time.time() + token['expires_in']
                    fresh = {'token': token}
                    profile = self.api(fresh).call('/me')
                    new_key = secrets.token_urlsafe(32)
                    fresh.update(account=profile['id'], display_name=profile.get('display_name') or profile['id'],
                                 csrf=secrets.token_urlsafe(32), expires=time.time() + 12 * 3600, revision=0)
                    SESSIONS[new_key] = fresh
                    SESSIONS.pop(self.session_key, None)
                    self.new_cookie = new_key
                    return self.send(302, {}, location='/')
                if url.path in FILES:
                    file, mime = FILES[url.path]
                    return self.send(data=(ROOT / 'static' / file).read_bytes(), content_type=mime)
                return self.send(404, {'error': 'Página não encontrada.'})
            except (ValueError, RemoteError) as error: self.send(400, {'error': str(error)})
            except Exception:
                self.send(500, {'error': 'Falha interna. Os dados salvos foram preservados. Verifique o aplicativo local.'})

    # ---------- POST ----------

    def do_POST(self):
        global CLIENT_ID
        with LOCK:
            try:
                if self.headers.get('Host') != f'127.0.0.1:{PORT}' or self.headers.get('Origin') != ORIGIN: return self.send(403, {'error': 'Origem não permitida.'})
                s = self.session()
                if not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), s['csrf']): return self.send(403, {'error': 'Recarregue a página para continuar.'})
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 200000 or not self.headers.get('Content-Type', '').startswith('application/json'): raise ValueError('Requisição inválida.')
                data = json.loads(self.rfile.read(size) or b'{}')
                if not isinstance(data, dict): raise ValueError('Requisição inválida.')
                path = urllib.parse.urlsplit(self.path).path
                account = s['account']
                handler = getattr(self, 'post_' + path.removeprefix('/api/').replace('-', '_'), None) if path.startswith('/api/') else None
                if not handler: return self.send(404, {'error': 'Página não encontrada.'})
                return handler(s, account, data)
            except (ValueError, RemoteError) as error: self.send(400, {'error': str(error)})
            except Exception:
                self.send(500, {'error': 'Falha interna. Os dados salvos foram preservados. Verifique o aplicativo local.'})

    # Conta

    def post_config(self, s, account, data):
        global CLIENT_ID
        client = data.get('client_id', '').strip()
        if not re.fullmatch('[a-fA-F0-9]{32}', client): raise ValueError('Client ID inválido. Copie o identificador de 32 caracteres do Spotify.')
        if any(v.get('token') for v in SESSIONS.values()): raise ValueError('Desconecte as contas antes de trocar o aplicativo.')
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = CONFIG_PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps({'client_id': client}), encoding='utf-8')
        temporary.replace(CONFIG_PATH)
        CLIENT_ID = client
        for other in SESSIONS.values(): other.pop('oauth', None)
        return self.send(data={'message': 'Client ID salvo neste computador. Agora conecte sua conta.'})

    def post_logout(self, s, account, data):
        SESSIONS.pop(self.session_key, None)
        self.new_cookie, _ = new_session()
        return self.send(data={'message': 'Conta desconectada. Tokens descartados da memória.'})

    # Sincronização: curtidas + suas playlists, uma playlist por passo

    def post_sync_start(self, s, account, data):
        if not s.get('token'): raise ValueError('Conecte o Spotify para carregar sua biblioteca.')
        api = self.api(s)
        liked = api.library()
        playlists = api.playlists()  # only your own playlists
        s['sync'] = {'id': secrets.token_urlsafe(24), 'liked': liked, 'queue': playlists, 'playlists': [], 'extra': [], 'expires': time.time() + 3600}
        return self.send(data={'id': s['sync']['id'], 'remaining': len(playlists), 'message': f'{len(liked)} curtidas carregadas. Lendo {len(playlists)} playlists…'})

    def post_sync_step(self, s, account, data):
        sync = s.get('sync')
        if not s.get('token') or not sync or sync['expires'] < time.time() or not secrets.compare_digest(sync['id'], str(data.get('id', ''))):
            raise ValueError('Sincronização expirada. Inicie novamente.')
        if sync['queue']:
            p = sync['queue'][0]
            entry = {'id': p['id'], 'name': p.get('name', 'Playlist'), 'description': p.get('description') or '', 'snapshot_id': p.get('snapshot_id'),
                     'owned': True, 'tracks': [], 'unavailable': False}
            try:
                items = self.api(s).playlist_tracks(p['id'])
                entry['tracks'] = [{'id': t.get('id'), 'uri': t.get('uri'), 'title': t.get('name', ''), 'artists': [a['name'] for a in t.get('artists', [])]} for t in items]
                sync['extra'].extend(items)
            except RemoteError as error:
                if error.status not in (403, 404): raise
                entry['unavailable'] = True
            sync['playlists'].append(entry); sync['queue'].pop(0)
        if sync['queue']:
            return self.send(data={'remaining': len(sync['queue']), 'message': f'Playlists carregadas: {len(sync["playlists"])}. Restantes: {len(sync["queue"])}.'})
        count = STORE.import_tracks(account, sync['liked'], sync['extra'])
        STORE.save_spotify_library(account, {'playlists': sync['playlists'], 'synced_at': time.time()})
        game.sync_profiles(STORE, account, [p for p in sync['playlists'] if not p['unavailable']])
        s['synced'] = True; s.pop('sync', None); self.invalidate(account)
        COLLECTOR.start(account)
        return self.send(data={'remaining': 0, 'message': f'{count} músicas ({len(sync["liked"])} curtidas) e {len(sync["playlists"])} playlists sincronizadas. Informações anteriores preservadas.'})

    def post_collect_start(self, s, account, data):
        started = COLLECTOR.start(account)
        return self.send(data=dict(COLLECTOR.status(account), started=started))

    # Playlists

    def post_profile_update(self, s, account, data):
        if not isinstance(data.get('fields'), dict): raise ValueError('Requisição inválida.')
        p = game.update_profile(STORE, account, str(data.get('key', '')), data['fields'])
        self.invalidate(account)
        return self.send(data={'profile': p, 'message': 'Playlist atualizada. Nada foi gravado no Spotify ainda.'})

    def post_profile_create(self, s, account, data):
        if not isinstance(data.get('fields'), dict): raise ValueError('Requisição inválida.')
        p = game.create_profile(STORE, account, data['fields'])
        self.invalidate(account)
        return self.send(data={'profile': p, 'message': 'Playlist "' + p['name'] + '" criada no app. Ela só vai para o Spotify depois da prévia final.'})

    def post_profile_delete(self, s, account, data):
        game.delete_profile(STORE, account, str(data.get('key', '')))
        self.invalidate(account)
        return self.send(data={'message': 'Playlist nova apagada do app.'})

    # Jogo

    def post_game_decide(self, s, account, data):
        if not isinstance(data.get('playlists'), list): raise ValueError('Requisição inválida.')
        game.decide(STORE, account, str(data.get('id', '')), data['playlists'])
        self.invalidate(account)
        return self.send(data=game.card(STORE, account))

    def post_game_focus(self, s, account, data):
        key = data.get('key')
        if key is not None and not isinstance(key, str): raise ValueError('Requisição inválida.')
        round_ = game.set_focus(STORE, account, key)
        self.invalidate(account)
        return self.send(data=dict(game.card(STORE, account), message=f'Rodada só com "{round_["name"]}": {len(round_["tracks"])} músicas.' if round_ else 'Rodada com todas as músicas.'))

    def post_game_skip(self, s, account, data):
        game.skip(STORE, account, str(data.get('id', '')))
        self.invalidate(account)
        return self.send(data=game.card(STORE, account))

    def post_game_undo(self, s, account, data):
        ident, undone = game.undo(STORE, account)
        if ident is None: raise ValueError('Não há jogada para desfazer.')
        self.invalidate(account)
        return self.send(data=game.card(STORE, account, ident, preset=undone))

    # Prévia final e gravação

    def post_publish_preview(self, s, account, data):
        if not s.get('token'): raise ValueError('Conecte o Spotify para preparar a prévia.')
        plan = publish.prepare(STORE, account, self.api(s))
        s['publish'] = {'id': secrets.token_urlsafe(24), 'plan': plan, 'revision': s['revision'], 'expires': time.time() + 1800}
        view = dict(plan, items=[{k: v for k, v in i.items() if k != 'live'} for i in plan['items']])
        return self.send(data=dict(view, id=s['publish']['id']))

    def post_publish_execute(self, s, account, data):
        # A preview is used once: it is removed before writing, so a write is never repeated.
        pending = s.pop('publish', None)
        if not s.get('token') or not pending or pending['expires'] < time.time() or not secrets.compare_digest(pending['id'], str(data.get('id', ''))):
            raise ValueError('Prévia expirada ou já usada. Prepare uma nova prévia.')
        if pending['revision'] != s['revision']: raise ValueError('A biblioteca mudou depois da prévia. Prepare uma nova prévia.')
        results = publish.execute(STORE, account, self.api(s), pending['plan'])
        self.invalidate(account)
        return self.send(data={'results': results})


if __name__ == '__main__':
    import sys
    import webbrowser
    print('Spotify Project: ' + ORIGIN, flush=True)
    print('Piloto local. Para encerrar: Ctrl+C. Tokens não são gravados em disco.', flush=True)
    try:
        http = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    except OSError:
        print('Não foi possível iniciar. A porta ' + str(PORT) + ' pode estar ocupada. Feche a execução anterior e tente novamente.', flush=True)
        raise SystemExit(1)
    if '--open-browser' in sys.argv:
        threading.Timer(0.5, lambda: webbrowser.open(ORIGIN)).start()
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        http.server_close()
