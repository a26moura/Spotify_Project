from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game
from core import Store

A = 'spotify:user'
T1, T2, T3 = 'a' * 22, 'b' * 22, 'c' * 22


def raw(ident, **extra):
    return dict({'id': ident, 'name': 'Song ' + ident[0], 'artists': [{'name': 'Artist'}]}, **extra)


class GameTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / 'db.sqlite3')
        self.store.import_tracks(A, [raw(T1), raw(T2)], [raw(T3)])
        self.library([('p1', 'Rock', [T1]), ('p2', 'Pop', [])])

    def tearDown(self):
        self.dir.cleanup()

    def library(self, playlists):
        lists = [{'id': i, 'name': n, 'description': 'desc ' + n, 'tracks': [{'id': t} for t in ts]} for i, n, ts in playlists]
        self.store.save_spotify_library(A, {'playlists': lists, 'synced_at': 1})
        game.sync_profiles(self.store, A, lists)

    def activate(self, *keys):
        for k in keys: game.update_profile(self.store, A, k, {'active': True})

    def test_import_keeps_playlist_only_tracks_as_not_liked(self):
        tracks = {t['id']: t for t in self.store.tracks(A)}
        self.assertEqual([tracks[T1]['liked'], tracks[T3]['liked']], [True, False])
        self.store.import_tracks(A, [raw(T1)], [raw(T1)])
        tracks = {t['id']: t for t in self.store.tracks(A)}
        self.assertTrue(tracks[T1]['liked'])
        self.assertFalse(tracks[T2]['active'])

    def test_sync_keeps_your_edits_and_follows_unedited_names(self):
        game.update_profile(self.store, A, 'p1', {'name': 'Rock pesado', 'language': 'Inglês'})
        self.library([('p1', 'Rock 2', [T1]), ('p2', 'Pop 2', [])])
        rows = {p['key']: p for p in game.profiles(self.store, A)}
        self.assertEqual((rows['p1']['name'], rows['p1']['language']), ('Rock pesado', 'Inglês'))
        self.assertEqual(rows['p2']['name'], 'Pop 2')
        self.activate('p2')
        self.library([('p1', 'Rock 2', [T1])])
        rows = {p['key']: p for p in game.profiles(self.store, A)}
        self.assertTrue(rows['p2']['missing']); self.assertFalse(rows['p2']['active'])
        with self.assertRaises(ValueError): self.activate('p2')

    def test_profile_limits(self):
        with self.assertRaises(ValueError): game.update_profile(self.store, A, 'p1', {'name': 'pop'})
        with self.assertRaises(ValueError): game.update_profile(self.store, A, 'p1', {'description': 'x' * 301})
        with self.assertRaises(ValueError): game.create_profile(self.store, A, {'name': ''})
        for i in range(8): game.create_profile(self.store, A, {'name': f'Nova {i}'})
        self.assertEqual(sum(p['active'] for p in game.profiles(self.store, A)), 8)
        extra = game.create_profile(self.store, A, {'name': 'Nona'})
        self.assertFalse(extra['active'])
        with self.assertRaises(ValueError): game.update_profile(self.store, A, extra['key'], {'active': True})
        with self.assertRaises(ValueError): game.delete_profile(self.store, A, 'p1')

    def test_decide_stores_changes_relative_to_spotify(self):
        self.activate('p1', 'p2')
        current = game.membership(self.store, A)
        self.assertEqual(game.marks(T1, None, current, ['p1', 'p2']), ['p1'])
        d = game.decide(self.store, A, T1, ['p2'])
        self.assertEqual((d['add'], d['remove']), (['p2'], ['p1']))
        self.assertEqual(game.marks(T1, d, current, ['p1', 'p2']), ['p2'])
        with self.assertRaises(ValueError): game.decide(self.store, A, T1, ['p9'])
        # A playlist outside the game keeps what was decided before.
        game.update_profile(self.store, A, 'p2', {'active': False})
        d = game.decide(self.store, A, T1, ['p1'])
        self.assertEqual((d['add'], d['remove']), (['p2'], []))

    def test_new_playlist_choices_dropped_when_deleted(self):
        new = game.create_profile(self.store, A, {'name': 'Treino', 'genre': 'trap'})
        game.decide(self.store, A, T2, [new['key']])
        game.delete_profile(self.store, A, new['key'])
        self.assertEqual(game.decisions(self.store, A)[T2]['add'], [])

    def test_undo_skip_and_queue(self):
        self.activate('p1')
        self.assertEqual(game.progress(self.store, A), {'total': 3, 'decided': 0, 'skipped': 0})
        game.decide(self.store, A, T1, [])
        game.skip(self.store, A, T2)
        self.assertEqual(game.queue(self.store, A)[-1], T2)
        self.assertNotIn(T1, game.queue(self.store, A))
        self.assertEqual(game.progress(self.store, A), {'total': 3, 'decided': 1, 'skipped': 1})
        self.assertEqual(game.undo(self.store, A)[0], T2)
        self.assertNotIn(T2, game.decisions(self.store, A))
        track, undone = game.undo(self.store, A)
        self.assertEqual((track, undone['add'], undone['remove']), (T1, [], ['p1']))
        self.assertEqual(game.decisions(self.store, A), {})
        self.assertEqual(game.undo(self.store, A), (None, None))

    def test_queue_puts_tracks_with_data_first_grouped(self):
        tracks = {t['id']: t for t in self.store.tracks(A)}
        tracks[T3].update(languages=['Espanhol'], genres=['Pop'])
        tracks[T2].update(languages=['Espanhol'], genres=['Reggaeton'])
        for t in tracks.values(): self.store.put(A, t)
        self.assertEqual(game.queue(self.store, A), [T3, T2, T1])


if __name__ == '__main__':
    unittest.main()


from helpers import HTTPTests
import json as _json
import urllib.request as _request


class ProfileEndpointTests(HTTPTests):
    def get(self, path):
        with _request.urlopen(_request.Request(f'http://127.0.0.1:{self.port}/api/' + path, headers={'Cookie': self.cookie})) as r:
            return _json.load(r)

    def test_overview_and_profile_endpoints(self):
        account = self.session['account']
        store = self.server.STORE
        store.import_tracks(account, [raw(T1)], [raw(T2)])
        lists = [{'id': 'p1', 'name': 'Rock', 'description': '', 'tracks': [{'id': T1}, {'id': T2}]}]
        store.save_spotify_library(account, {'playlists': lists, 'synced_at': 5})
        game.sync_profiles(store, account, lists)
        data = self.get('game')
        self.assertEqual((data['synced_at'], data['max_active'], data['progress']['total']), (5, 8, 2))
        self.assertEqual([(p['key'], p['count'], p['count_after']) for p in data['profiles']], [('p1', 2, 2)])
        status, r = self.post('profile-update', {'key': 'p1', 'fields': {'active': True, 'language': 'Inglês'}})
        self.assertEqual(status, 200, r)
        self.assertEqual(self.post('profile-update', {'key': 'p1', 'fields': {'name': ''}})[0], 400)
        self.assertEqual(self.post('profile-update', {'key': 'p1', 'fields': 'x'})[0], 400)
        status, r = self.post('profile-create', {'fields': {'name': 'Treino'}})
        self.assertEqual(status, 200, r)
        new = r['profile']['key']
        game.decide(store, account, T1, [new])
        rows = {p['key']: p for p in self.get('game')['profiles']}
        self.assertEqual((rows['p1']['count_after'], rows[new]['count_after']), (1, 1))
        self.assertEqual(self.post('profile-delete', {'key': 'p1'})[0], 400)
        self.assertEqual(self.post('profile-delete', {'key': new})[0], 200)
        self.assertEqual([p['key'] for p in self.get('game')['profiles']], ['p1'])


class CardTests(GameTests):
    def test_suggested_by_language_or_genre(self):
        t = {'languages': ['Espanhol'], 'genres': ['Reggaeton'], 'source_labels': []}
        self.assertTrue(game.suggested(t, {'language': 'espanhol'}))
        self.assertTrue(game.suggested(t, {'genre': 'reggaeton'}))
        self.assertFalse(game.suggested(t, {'language': 'Misto'}))
        self.assertFalse(game.suggested(t, {'genre': '', 'language': ''}))
        self.assertFalse(game.suggested(t, {'genre': 'rock'}))
        t['review'] = {'genres': ['Rock'], 'languages': [], 'playlists': [], 'exclude': False}
        self.assertTrue(game.suggested(t, {'genre': 'rock'}))

    def test_card_shows_marks_and_spotify_membership(self):
        self.activate('p1', 'p2')
        game.update_profile(self.store, A, 'p2', {'genre': 'pop'})
        rows = {t['id']: t for t in self.store.tracks(A)}
        rows[T1].update(genres=['Pop'], cover='https://i.scdn.co/image/x'); self.store.put(A, rows[T1])
        c = game.card(self.store, A)
        self.assertEqual(c['track']['id'], T1)
        self.assertEqual((c['marks'], c['in_spotify'], c['suggested']), (['p1'], ['p1'], ['p2']))
        self.assertTrue(c['track']['pending'])
        game.decide(self.store, A, T1, ['p2'])
        self.assertNotEqual(game.card(self.store, A)['track']['id'], T1)
        again = game.card(self.store, A, T1)
        self.assertEqual((again['marks'], again['decided']), (['p2'], True))
        for t in (T2, T3): game.decide(self.store, A, t, [])
        done = game.card(self.store, A)
        self.assertIsNone(done['track']); self.assertEqual(done['remaining'], 0)


class GameEndpointTests(ProfileEndpointTests):
    def test_game_moves(self):
        account = self.session['account']
        store = self.server.STORE
        store.import_tracks(account, [raw(T1), raw(T2)])
        lists = [{'id': 'p1', 'name': 'Rock', 'description': '', 'tracks': [{'id': T1}]}]
        store.save_spotify_library(account, {'playlists': lists, 'synced_at': 5})
        game.sync_profiles(store, account, lists)
        game.update_profile(store, account, 'p1', {'active': True})
        first = self.get('game-card')['track']['id']
        status, nxt = self.post('game-decide', {'id': first, 'playlists': ['p1']})
        self.assertEqual(status, 200, nxt)
        self.assertNotEqual(nxt['track']['id'], first)
        self.assertEqual(self.post('game-decide', {'id': first, 'playlists': ['zzz']})[0], 400)
        status, after = self.post('game-skip', {'id': nxt['track']['id']})
        self.assertEqual(after['track']['id'], nxt['track']['id'])  # only skipped left
        self.assertEqual(self.post('game-undo', {})[1]['track']['id'], nxt['track']['id'])
        undone = self.post('game-undo', {})[1]
        self.assertEqual((undone['track']['id'], undone['marks']), (first, ['p1']))
        self.assertNotIn(first, game.decisions(store, account))
        self.assertEqual(self.post('game-undo', {})[0], 400)
        self.assertEqual(self.get('game-card?id=' + first)['track']['id'], first)
