"""Server basics: empty start, origin/CSRF checks, Client ID, login, store and Spotify adapter."""
from pathlib import Path
import json
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

from helpers import HTTPTests, ID1, ID2, raw
from core import Store
from providers import RemoteError, Spotify


class ServerTests(HTTPTests):
    def test_startup_is_empty_and_static_files_served(self):
        self.assertEqual((self.state['profiles'], self.state['progress']['total'], self.state['connected']), ([], 0, False))
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/') as r:
            self.assertIn('i.scdn.co', r.headers['Content-Security-Policy'])
            self.assertIn(b'screen-game', r.read())
        self.assertEqual(self.post('nao-existe', {})[0], 404)

    def test_origin_and_csrf_required(self):
        self.assertEqual(self.post('game-skip', {}, csrf=False)[0], 403)
        self.assertEqual(self.post('game-skip', {}, origin=False)[0], 403)
        self.assertEqual(self.post('game-skip', {'id': ID1})[0], 400)
        self.assertEqual(self.post('sync-start', {})[0], 400)  # sem conexão

    def test_old_endpoints_are_gone(self):
        for path in ('plan', 'execute', 'rules', 'route-start', 'clear-execute', 'ollama-models'):
            self.assertEqual(self.post(path, {})[0], 404, path)

    def test_client_id_persists_without_tokens(self):
        path = Path(self.tmp.name) / 'config.json'
        with patch.object(self.server, 'CONFIG_PATH', path), patch.object(self.server, 'CLIENT_ID', ''):
            self.assertEqual(self.post('config', {'client_id': 'x'})[0], 400)
            self.assertEqual(self.post('config', {'client_id': 'a' * 32})[0], 200)
            self.assertEqual(json.loads(path.read_text()), {'client_id': 'a' * 32})
            self.assertEqual(self.server.load_client_id(), 'a' * 32)

    def test_login_creates_a_new_session(self):
        self.session['oauth'] = {'state': 'test-state', 'verifier': 'test-verifier', 'expires': time.time() + 60}
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/callback?state=test-state&code=test-code', headers={'Cookie': self.cookie})
        with patch.object(self.server, 'request_json', return_value={'access_token': 'fake', 'refresh_token': 'fake', 'expires_in': 3600}), \
             patch.object(self.server.Spotify, 'call', return_value={'id': 'real-account', 'display_name': 'Eu'}):
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
        # The old session is dropped; the redirect itself (followed without cookies) opens another anonymous one.
        accounts = [s['account'] for s in self.server.SESSIONS.values()]
        self.assertIn('real-account', accounts)
        self.assertNotIn(self.session, self.server.SESSIONS.values())
        bad = urllib.request.Request(f'http://127.0.0.1:{self.port}/callback?state=wrong&code=x', headers={'Cookie': self.cookie})
        with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(bad)
        self.assertEqual(error.exception.code, 400); error.exception.close()


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.tmp.name) / 'app.sqlite3')

    def tearDown(self): self.tmp.cleanup()

    def test_import_keeps_collected_data_and_marks_removed(self):
        self.db.import_tracks('a', [raw()])
        t = self.db.tracks('a')[0]
        t.update(genres=['Pop'], genre_origin='album', quick_checked=True, deezer_id=7, bpm=120, review={'genres': ['Rock'], 'languages': []})
        self.db.put('a', t)
        self.db.import_tracks('a', [raw(ID2)])
        self.assertFalse(next(x for x in self.db.tracks('a') if x['id'] == ID1)['active'])
        self.db.import_tracks('a', [raw()])
        again = next(x for x in self.db.tracks('a', True) if x['id'] == ID1)
        self.assertEqual((again['genres'], again['quick_checked'], again['deezer_id'], again['bpm'], again['review']['genres']), (['Pop'], True, 7, 120, ['Rock']))

    def test_accounts_are_isolated(self):
        self.db.import_tracks('a', [raw()])
        self.assertEqual(self.db.tracks('b'), [])
        self.assertEqual(self.db.spotify_library('b'), {'playlists': [], 'synced_at': None})


class SpotifyAdapterTests(unittest.TestCase):
    def test_pagination_relink_and_foreign_next_link(self):
        api = Spotify({'account': 'a'}, 'id', 'redirect')
        pages = [{'items': [{'item': {'uri': 'spotify:track:new', 'linked_from': {'uri': 'spotify:track:old'}}}], 'next': 'https://api.spotify.com/v1/playlists/p/items?offset=1'},
                 {'items': [{'item': None}], 'next': None}]
        with patch.object(api, 'call', side_effect=pages): self.assertEqual(api.contents('p'), {'spotify:track:new', 'spotify:track:old'})
        with patch.object(api, 'call', return_value={'items': [], 'next': 'https://evil.invalid/token'}):
            with self.assertRaises(RemoteError): api.pages('/me/tracks')


if __name__ == '__main__':
    unittest.main()
