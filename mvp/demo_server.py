"""Servidor de demonstração com dados fictícios: http://127.0.0.1:8799 (sem Spotify real, sem rede).
Uso: cd mvp; python demo_server.py"""
import os, sys, tempfile
from pathlib import Path
os.environ['PORT'] = '8799'
os.environ['SPOTIFY_PROJECT_DB'] = str(Path(tempfile.mkdtemp()) / 'demo.sqlite3')
os.environ['SPOTIFY_PROJECT_CONFIG'] = str(Path(tempfile.mkdtemp()) / 'config.json')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server, game

A = 'spotify:demo'
def tid(i): return (chr(97 + i % 26) * 21 + chr(65 + i // 26))[:22]
names = [('Bailando', 'Enrique', 'Espanhol', 'Reggaeton'), ('Garota', 'Tom', 'Português', 'Bossa Nova'), ('Highway', 'AC', 'Inglês', 'Rock'),
         ('Envolver', 'Anitta', 'Espanhol', 'Reggaeton'), ('Evidências', 'Chitãozinho', 'Português', 'Sertanejo'), ('Yellow', 'Coldplay', 'Inglês', 'Pop')]
raw = [{'id': tid(i), 'name': n, 'artists': [{'name': a}], 'album': {'name': n + ' (álbum)', 'release_date': '2015'}} for i, (n, a, _, _) in enumerate(names)]
server.STORE.import_tracks(A, raw[:5], raw[5:])
for i, t in enumerate(server.STORE.tracks(A)):
    t.update(languages=[names[i][2]], genres=[names[i][3]], quick_checked=i < 4, duration_ms=200000 + i * 7000)
    if names[i][0] == 'Yellow': t['deezer_id'] = 3128096  # prévia real de 30 s (Deezer, pública)
    server.STORE.put(A, t)
lists = [{'id': 'pl1', 'name': 'Latinas', 'description': 'Para dançar', 'tracks': [{'id': tid(0)}]},
         {'id': 'pl2', 'name': 'Rock', 'description': '', 'tracks': [{'id': tid(2)}, {'id': tid(5)}]},
         {'id': 'pl3', 'name': 'Brasil', 'description': 'MPB e sertanejo', 'tracks': []}]
server.STORE.save_spotify_library(A, {'playlists': lists, 'synced_at': 1})
game.sync_profiles(server.STORE, A, lists)
game.update_profile(server.STORE, A, 'pl1', {'active': True, 'language': 'Espanhol'})
game.update_profile(server.STORE, A, 'pl2', {'active': True, 'genre': 'rock'})
game.update_profile(server.STORE, A, 'pl3', {'active': True, 'language': 'Português'})
game.create_profile(server.STORE, A, {'name': 'Treino', 'genre': 'reggaeton'})

original = server.new_session
def demo_session():
    key, s = original()
    s.update(account=A, display_name='Conta de demonstração', token={'access_token': 'fake'}, synced=True)
    return key, s
server.new_session = demo_session
server.CLIENT_ID = 'x' * 32
http = server.ThreadingHTTPServer(('127.0.0.1', 8799), server.Handler)
print('demo em http://127.0.0.1:8799', flush=True)
http.serve_forever()
