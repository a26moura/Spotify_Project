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
        self.assertEqual(game.undo(self.store, A), T2)
        self.assertNotIn(T2, game.decisions(self.store, A))
        self.assertEqual(game.undo(self.store, A), T1)
        self.assertEqual(game.decisions(self.store, A), {})
        self.assertIsNone(game.undo(self.store, A))

    def test_queue_puts_tracks_with_data_first_grouped(self):
        tracks = {t['id']: t for t in self.store.tracks(A)}
        tracks[T3].update(languages=['Espanhol'], genres=['Pop'])
        tracks[T2].update(languages=['Espanhol'], genres=['Reggaeton'])
        for t in tracks.values(): self.store.put(A, t)
        self.assertEqual(game.queue(self.store, A), [T3, T2, T1])


if __name__ == '__main__':
    unittest.main()
