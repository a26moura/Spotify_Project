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
        self.lists = {}; self.items = {}; self.writes = []; self.lose_create = False
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
        self.assertEqual(plan['totals'], {'playlists': 3, 'create': 1, 'add': 3, 'remove': 1})

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


class EmptyDescriptionTests(PublishTests):
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
