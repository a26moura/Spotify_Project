from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import game
import publish
from core import Store
from providers import RemoteError, Spotify
from helpers import HTTPTests

A = 'spotify:user'


def tid(i): return format(i, '022d').replace('0', 'a')


def raw(i): return {'id': tid(i), 'name': f'Song {i:03d}', 'artists': [{'name': 'Artist'}]}


class FakeSpotify:
    """Your playlists in memory; records every write."""
    def __init__(self):
        self.lists = {}; self.items = {}; self.writes = []; self.lose_create = False; self.unliked = []; self.liked = []
    def add(self, ident, name, uris, description=''):
        self.lists[ident] = {'id': ident, 'name': name, 'description': description}; self.items[ident] = list(uris)
    def playlists(self): return [dict(p) for p in self.lists.values()]
    def contents(self, ident): return set(self.items[ident])
    def call(self, path, method='GET', body=None):
        self.writes.append((method, path, body))
        if path == '/me/playlists':
            ident = 'new' + str(len(self.lists))
            self.add(ident, body['name'], [], body['description'])
            self.lists[ident]['public'] = body['public']
            if self.lose_create: self.lose_create = False; raise RemoteError('resposta perdida')
            return {'id': ident}
        if path.startswith('/me/library?'):
            from urllib.parse import parse_qs, urlsplit
            uris = parse_qs(urlsplit(path).query)['uris'][0].split(',')
            if method == 'DELETE': self.unliked += uris
            else: self.liked += uris
            return {}
        ident = path.split('/')[2]
        if method == 'PUT': self.lists[ident].update(body); return {}
        if method == 'POST': self.items[ident] += body['uris']; return {'snapshot_id': 'x'}
        if method == 'DELETE':
            gone = {i['uri'] for i in body['items']}
            self.items[ident] = [u for u in self.items[ident] if u not in gone]; return {'snapshot_id': 'x'}
        raise AssertionError(path)


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / 'db.sqlite3')
        self.store.import_tracks(A, [raw(i) for i in range(1, 6)])
        self.api = FakeSpotify()
        self.api.add('p1', 'Rock', ['spotify:track:' + tid(1), 'spotify:track:' + tid(2)], 'Guitarras &amp; mais')
        self.api.add('p2', 'Pop', [])
        self.sync()
        for k in ('p1', 'p2'): game.update_profile(self.store, A, k, {'active': True})

    def tearDown(self):
        self.dir.cleanup()

    def sync(self):
        lists = [{'id': i, 'name': p['name'], 'description': p['description'], 'tracks': [{'id': u.split(':')[2]} for u in self.api.items[i]]} for i, p in self.api.lists.items()]
        self.store.save_spotify_library(A, {'playlists': lists, 'synced_at': 1})
        game.sync_profiles(self.store, A, lists)

    def test_prepare_lists_changes_without_writing(self):
        self.assertEqual({p['key']: p['description'] for p in game.profiles(self.store, A)}['p1'], 'Guitarras & mais')
        new = game.create_profile(self.store, A, {'name': 'Treino', 'description': 'Para correr'})
        empty = game.create_profile(self.store, A, {'name': 'Vazia'})
        game.update_profile(self.store, A, 'p2', {'name': 'Pop 2000'})
        game.decide(self.store, A, tid(1), ['p2', new['key']])      # sai do Rock, entra no Pop e na nova
        game.decide(self.store, A, tid(3), ['p1'])
        plan = publish.prepare(self.store, A, self.api)
        self.assertEqual(self.api.writes, [])
        items = {i['key']: i for i in plan['items']}
        self.assertEqual([t['id'] for t in items['p1']['add']], [tid(3)])
        self.assertEqual([t['id'] for t in items['p1']['remove']], [tid(1)])
        self.assertEqual((items['p1']['before'], items['p1']['after'], items['p1']['rename'], items['p1']['describe']), (2, 2, None, None))
        self.assertEqual(items['p2']['rename'], {'from': 'Pop', 'to': 'Pop 2000'})
        self.assertEqual((items[new['key']]['action'], items[new['key']]['describe']), ('create', {'from': '', 'to': 'Para correr'}))
        self.assertEqual(items[empty['key']]['action'], 'skip')
        self.assertEqual(plan['totals'], {'playlists': 3, 'create': 1, 'add': 3, 'remove': 1, 'like': 0, 'unlike': 0})

    def test_execute_writes_and_next_preview_is_empty(self):
        new = game.create_profile(self.store, A, {'name': 'Treino', 'description': 'Para correr'})
        game.decide(self.store, A, tid(1), ['p2', new['key']])
        game.decide(self.store, A, tid(4), ['p1'])
        results = publish.execute(self.store, A, self.api, publish.prepare(self.store, A, self.api))
        self.assertEqual([r['status'] for r in results], ['Criada', 'Atualizada', 'Atualizada'])
        created = next(i for i, p in self.api.lists.items() if p['name'] == 'Treino')
        self.assertEqual((self.api.lists[created]['public'], self.api.lists[created]['description']), (False, 'Para correr'))
        self.assertEqual(self.api.items[created], ['spotify:track:' + tid(1)])
        self.assertEqual(self.api.items['p1'], ['spotify:track:' + tid(2), 'spotify:track:' + tid(4)])
        self.assertEqual(self.api.items['p2'], ['spotify:track:' + tid(1)])
        self.assertIn(('DELETE', '/playlists/p1/items', {'items': [{'uri': 'spotify:track:' + tid(1)}]}), self.api.writes)
        self.assertEqual(publish.prepare(self.store, A, self.api)['totals']['playlists'], 0)
        profile = next(p for p in game.profiles(self.store, A) if p['key'] == new['key'])
        self.assertEqual(profile['spotify_id'], created)
        with self.assertRaises(ValueError): game.delete_profile(self.store, A, new['key'])
        # After a new sync the created playlist keeps its profile (no duplicate) and its tracks.
        self.sync()
        self.assertEqual(len([p for p in game.profiles(self.store, A) if p['name'] == 'Treino']), 1)
        self.assertEqual(game.membership(self.store, A)[new['key']], {tid(1)})

    def test_refuses_playlist_changed_since_preview(self):
        game.decide(self.store, A, tid(3), ['p1', 'p2'])
        plan = publish.prepare(self.store, A, self.api)
        self.api.items['p1'].append('spotify:track:' + tid(5))  # alguém mudou o Rock no Spotify
        results = publish.execute(self.store, A, self.api, plan)
        self.assertEqual(results[-1]['status'], 'Falha')
        self.assertIn('mudou', results[-1]['error'])
        self.assertNotIn(('POST', '/playlists/p1/items', {'uris': ['spotify:track:' + tid(3)]}), self.api.writes)

    def test_lost_create_is_recovered_not_duplicated(self):
        new = game.create_profile(self.store, A, {'name': 'Treino'})
        game.decide(self.store, A, tid(2), ['p1', new['key']])
        self.api.lose_create = True
        results = publish.execute(self.store, A, self.api, publish.prepare(self.store, A, self.api))
        self.assertEqual(results[0]['status'], 'Falha')
        plan = publish.prepare(self.store, A, self.api)
        item = next(i for i in plan['items'] if i['key'] == new['key'])
        self.assertEqual((item['action'], item['describe']), ('update', {'from': '', 'to': ''}))
        publish.execute(self.store, A, self.api, plan)
        self.assertEqual(len([p for p in self.api.lists.values() if p['name'] == 'Treino']), 1)
        created = next(i for i, p in self.api.lists.items() if p['name'] == 'Treino')
        self.assertEqual((self.api.lists[created]['description'], self.api.items[created]), ('', ['spotify:track:' + tid(2)]))

    def test_writes_in_chunks_of_100(self):
        self.store.import_tracks(A, [raw(i) for i in range(1, 160)])
        for i in range(10, 160): game.decide(self.store, A, tid(i), ['p2'])
        publish.execute(self.store, A, self.api, publish.prepare(self.store, A, self.api))
        posts = [b for m, p, b in self.api.writes if m == 'POST' and p == '/playlists/p2/items']
        self.assertEqual([len(b['uris']) for b in posts], [100, 50])


class RepeatedSongTests(unittest.TestCase):
    setUp, tearDown, sync = PublishTests.setUp, PublishTests.tearDown, PublishTests.sync
    def test_removal_takes_out_every_version_and_add_uses_the_card(self):
        twin = {'id': tid(9), 'name': 'Song 001', 'artists': [{'name': 'Artist'}], 'external_ids': {'isrc': 'BRX000000001'}}
        first = dict(raw(1), external_ids={'isrc': 'BRX000000001'})
        self.store.import_tracks(A, [first] + [raw(i) for i in range(2, 6)], [twin])
        self.api.items['p1'].append('spotify:track:' + tid(9))   # both versions are in Rock
        self.sync()
        game.decide(self.store, A, tid(1), ['p2'])
        plan = publish.prepare(self.store, A, self.api)
        rock = next(i for i in plan['items'] if i['key'] == 'p1')
        self.assertEqual((len(rock['remove']), rock['before'], rock['after']), (1, 2, 1))
        publish.execute(self.store, A, self.api, plan)
        self.assertEqual(self.api.items['p1'], ['spotify:track:' + tid(2)])
        self.assertEqual(self.api.items['p2'], ['spotify:track:' + tid(1)])


class UnlikeTests(unittest.TestCase):
    setUp, tearDown, sync = PublishTests.setUp, PublishTests.tearDown, PublishTests.sync

    def test_unlike_goes_through_preview_after_playlists(self):
        game.decide(self.store, A, tid(1), ['p1'], like=False)     # stays in Rock
        game.decide(self.store, A, tid(3), [], like=False)         # in no playlist: leaves the app later
        game.decide(self.store, A, tid(4), ['p2'])
        self.assertFalse(game.card(self.store, A, tid(1))['like'])
        game.decide(self.store, A, tid(1), ['p1'])                  # None keeps the earlier choice
        self.assertIs(game.decisions(self.store, A)[tid(1)]['like'], False)
        plan = publish.prepare(self.store, A, self.api)
        self.assertEqual(self.api.writes, [])
        self.assertEqual([(u['id'], u['stays']) for u in plan['unlike']], [(tid(1), True), (tid(3), False)])
        self.assertEqual(plan['totals']['unlike'], 2)
        results = publish.execute(self.store, A, self.api, plan)
        self.assertEqual(results[-1], {'name': 'Curtidas: saem', 'status': 'Atualizada', 'added': 0, 'removed': 2})
        self.assertEqual(self.api.writes[-1][0:2], ('DELETE', '/me/library?uris=spotify%3Atrack%3A' + tid(1) + '%2Cspotify%3Atrack%3A' + tid(3)))
        liked = {t['id']: t['liked'] for t in self.store.tracks(A)}
        self.assertEqual((liked[tid(1)], liked[tid(3)], liked[tid(2)]), (False, False, True))
        self.assertNotIn('like', game.decisions(self.store, A)[tid(1)])
        self.assertEqual(publish.prepare(self.store, A, self.api)['totals']['unlike'], 0)

    def test_unlike_waits_when_a_playlist_fails(self):
        game.decide(self.store, A, tid(1), [], like=False)
        game.decide(self.store, A, tid(4), ['p1'])
        plan = publish.prepare(self.store, A, self.api)
        self.api.items['p1'].append('spotify:track:' + tid(5))      # Rock changed after the preview
        results = publish.execute(self.store, A, self.api, plan)
        self.assertEqual(results[-1]['status'], 'Falha')
        self.assertEqual(self.api.unliked, [])
        with self.assertRaises(ValueError): game.decide(self.store, A, tid(1), [], like='sim')

    def test_like_a_song_that_is_only_in_a_playlist(self):
        self.store.import_tracks(A, [raw(1)], [raw(7)])               # Song 7 is not liked
        game.decide(self.store, A, tid(7), ['p1'], like=True)
        game.decide(self.store, A, tid(1), [], like=True)             # already liked: nothing to do
        self.assertNotIn('like', game.decisions(self.store, A)[tid(1)])
        self.assertTrue(game.card(self.store, A, tid(7))['like'])
        plan = publish.prepare(self.store, A, self.api)
        self.assertEqual(([t['id'] for t in plan['like']], plan['totals']['like'], plan['unlike']), ([tid(7)], 1, []))
        results = publish.execute(self.store, A, self.api, plan)
        self.assertEqual(results[-1]['name'], 'Curtidas: entram')
        self.assertEqual(next(w for w in self.api.writes if w[1].startswith('/me/library'))[:2], ('PUT', '/me/library?uris=spotify%3Atrack%3A' + tid(7)))
        self.assertTrue(next(t for t in self.store.tracks(A) if t['id'] == tid(7))['liked'])

    def test_old_unlike_choice_still_counts(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO decisions VALUES (?,?,?)', (A, tid(2), '{"add": [], "remove": [], "skipped": false, "at": 1, "unlike": true}'))
        self.assertIs(game.decisions(self.store, A)[tid(2)]['like'], False)
        self.assertEqual([t['id'] for t in publish.prepare(self.store, A, self.api)['unlike']], [tid(2)])

    def test_unlike_in_chunks_of_40(self):
        self.store.import_tracks(A, [raw(i) for i in range(1, 90)])
        for i in range(1, 90): game.decide(self.store, A, tid(i), ['p1'] if i <= 2 else [], like=False)
        publish.execute(self.store, A, self.api, publish.prepare(self.store, A, self.api))
        calls = [p for m, p, b in self.api.writes if p.startswith('/me/library')]
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(self.api.unliked), 89)


class EmptyDescriptionTests(unittest.TestCase):
    setUp, tearDown, sync = PublishTests.setUp, PublishTests.tearDown, PublishTests.sync
    def test_refused_empty_description_is_only_a_warning(self):
        new = game.create_profile(self.store, A, {'name': 'Treino'})
        game.decide(self.store, A, tid(2), [new['key']])
        original = self.api.call
        def picky(path, method='GET', body=None):
            if method == 'PUT' and body == {'description': ''}: raise RemoteError('HTTP 400')
            return original(path, method, body)
        self.api.call = picky
        results = publish.execute(self.store, A, self.api, publish.prepare(self.store, A, self.api))
        self.assertEqual(results[0]['status'], 'Criada')
        self.assertIn('descrição temporária', results[0]['warning'])


class PublishEndpointTests(HTTPTests):
    def test_preview_is_used_once_and_invalidated_by_new_choices(self):
        account = self.session['account']; store = self.server.STORE
        self.assertEqual(self.post('publish-preview', {})[0], 400)  # sem conexão
        self.session['token'] = {'access_token': 'fake'}
        fake = FakeSpotify(); fake.add('p1', 'Rock', [])
        store.import_tracks(account, [raw(1), raw(2)])
        store.save_spotify_library(account, {'playlists': [{'id': 'p1', 'name': 'Rock', 'description': '', 'tracks': []}], 'synced_at': 1})
        game.sync_profiles(store, account, [{'id': 'p1', 'name': 'Rock'}])
        game.update_profile(store, account, 'p1', {'active': True})
        self.post('game-decide', {'id': tid(1), 'playlists': ['p1']})
        with patch.object(Spotify, 'playlists', side_effect=fake.playlists), patch.object(Spotify, 'contents', side_effect=fake.contents), patch.object(Spotify, 'call', side_effect=fake.call):
            status, preview = self.post('publish-preview', {})
            self.assertEqual(status, 200, preview)
            self.assertNotIn('live', preview['items'][0])
            self.post('game-decide', {'id': tid(2), 'playlists': ['p1']})   # mudou depois da prévia
            self.assertEqual(self.post('publish-execute', {'id': preview['id']})[0], 400)
            status, preview = self.post('publish-preview', {})
            self.assertEqual(preview['totals']['add'], 2)
            status, result = self.post('publish-execute', {'id': preview['id']})
            self.assertEqual((status, result['results'][0]['added']), (200, 2))
            self.assertEqual(self.post('publish-execute', {'id': preview['id']})[0], 400)  # nunca repete
        self.assertEqual(len(fake.items['p1']), 2)


if __name__ == '__main__':
    unittest.main()


class UnlikePermissionTests(HTTPTests):
    def test_old_login_without_permission_is_asked_to_reconnect(self):
        account = self.session['account']; store = self.server.STORE
        self.session['token'] = {'access_token': 'fake', 'scope': 'user-library-read playlist-modify-private'}
        fake = FakeSpotify(); fake.add('p1', 'Rock', [])
        store.import_tracks(account, [raw(1)])
        store.save_spotify_library(account, {'playlists': [{'id': 'p1', 'name': 'Rock', 'description': '', 'tracks': []}], 'synced_at': 1})
        game.sync_profiles(store, account, [{'id': 'p1', 'name': 'Rock'}])
        game.update_profile(store, account, 'p1', {'active': True})
        self.assertEqual(self.post('game-decide', {'id': tid(1), 'playlists': [], 'like': False})[0], 200)
        with patch.object(Spotify, 'playlists', side_effect=fake.playlists), patch.object(Spotify, 'contents', side_effect=fake.contents):
            status, result = self.post('publish-preview', {})
            self.assertEqual(status, 400)
            self.assertIn('conecte o Spotify de novo', result['error'])
            self.session['token']['scope'] += ' user-library-modify'
            status, result = self.post('publish-preview', {})
            self.assertEqual((status, result['totals']['unlike']), (200, 1))
        self.assertIn('user-library-modify', self.server.SCOPE)
