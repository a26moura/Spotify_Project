from pathlib import Path
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collector import Collector, pending
from core import Store, record
from providers import Enricher, RemoteError, QUICK_VERSION
from helpers import HTTPTests

A = 'spotify:user'
T1, T2 = 'a' * 22, 'b' * 22
PREVIEW = 'https://cdnt-preview.dzcdn.net/api/1/1/a/b/c/0/abc.mp3?hdnea=exp=1~acl=x'


def deezer(url, cache=True):
    """Fake public APIs: Deezer track/album by ISRC and LRCLIB lyrics."""
    if 'deezer.com/track/isrc:' in url or url.endswith('/track/77'):
        return {'id': 77, 'title': 'Song', 'bpm': 96.0, 'preview': PREVIEW, 'artist': {'name': 'Artist'}, 'album': {'id': 5, 'title': 'Disco'}}
    if 'deezer.com/album/5' in url:
        return {'title': 'Disco', 'genres': {'data': [{'name': 'Reggaeton'}, {'name': 'Latin Music'}]}}
    if 'lrclib.net' in url:
        return {'trackName': 'Song', 'artistName': 'Artist', 'plainLyrics': 'yo quiero bailar contigo esta noche porque la vida es una fiesta y no quiero que se acabe nunca ' * 3}
    raise AssertionError(url)


class QuickTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / 'db.sqlite3')
        self.enricher = Enricher(self.store)
        self.track = record({'id': T1, 'name': 'Song', 'artists': [{'name': 'Artist'}], 'external_ids': {'isrc': 'USAAA1234567'}})

    def tearDown(self):
        self.dir.cleanup()

    def test_quick_fills_genre_language_bpm_without_musicbrainz(self):
        with patch.object(self.enricher, 'get', side_effect=deezer) as get:
            result = self.enricher.quick(self.track)
        self.assertFalse(any('musicbrainz' in c.args[0] for c in get.call_args_list))
        self.assertEqual((result['genres'], result['genre_origin']), (['Reggaeton'], 'album'))
        self.assertEqual((result['languages'], result['language_origin']), (['Espanhol'], 'letra'))
        self.assertEqual((result['deezer_id'], result['bpm']), (77, 96.0))
        self.assertTrue(result['quick_checked'])

    def test_quick_keeps_stronger_sources(self):
        self.track.update(genres=['Trap'], genre_origin='faixa', languages=['Inglês'], language_origin='faixa')
        with patch.object(self.enricher, 'get', side_effect=deezer) as get:
            result = self.enricher.quick(self.track)
        self.assertNotIn('genres', result); self.assertNotIn('languages', result)
        self.assertFalse(any('lrclib' in c.args[0] for c in get.call_args_list))
        self.assertIn('Reggaeton', [l['label'] for l in result['source_labels']])

    def test_temporary_failure_leaves_track_pending(self):
        def offline(url, cache=True): raise RemoteError('offline', transient=True)
        with patch.object(self.enricher, 'get', side_effect=offline):
            self.assertNotIn('quick_checked', self.enricher.quick(self.track))

    def test_preview_is_fetched_fresh_and_checked(self):
        with patch.object(self.enricher, 'get', side_effect=deezer) as get:
            self.assertEqual(self.enricher.preview(self.track), PREVIEW)
            self.assertEqual(self.enricher.preview(dict(self.track, deezer_id=77)), PREVIEW)
        self.assertTrue(all(c.kwargs.get('cache') is False for c in get.call_args_list))
        with patch.object(self.enricher, 'get', return_value={'id': 1, 'preview': 'http://evil/x.mp3', 'artist': {'name': 'Artist'}}):
            self.assertIsNone(self.enricher.preview(self.track))
        with patch.object(self.enricher, 'get', return_value={'id': 1, 'preview': PREVIEW, 'artist': {'name': 'Outro'}}):
            self.assertIsNone(self.enricher.preview(self.track))
        self.assertIsNone(self.enricher.preview(dict(self.track, isrc=None)))


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.dir.name) / 'db.sqlite3')
        self.store.import_tracks(A, [{'id': T1, 'name': 'Song', 'artists': [{'name': 'Artist'}]}, {'id': T2, 'name': 'Other', 'artists': [{'name': 'Artist'}]}])

    def tearDown(self):
        self.dir.cleanup()

    def test_run_collects_and_keeps_reviews(self):
        rows = {t['id']: t for t in self.store.tracks(A)}
        rows[T2]['review'] = {'genres': ['Pop'], 'languages': [], 'playlists': [], 'exclude': False}
        self.store.put(A, rows[T2])
        class Fake:
            calls = []
            def quick(self, track):
                self.calls.append(track['id']); return {'genres': ['Rock'], 'quick_checked': QUICK_VERSION}
        fake = Fake()
        c = Collector(self.store, fake, threading.RLock(), pause=0)
        self.assertEqual([t['id'] for t in pending(self.store, A)], [T1])
        self.assertTrue(c.start(A)); c.threads[A].join(5)
        self.assertEqual(fake.calls, [T1])
        self.assertEqual({t['id']: t['genres'] for t in self.store.tracks(A)}, {T1: ['Rock'], T2: []})
        self.assertEqual(c.status(A)['remaining'], 0)
        self.assertEqual(c.status(A)['message'], 'Informações coletadas.')

    def test_failures_are_retried_then_reported(self):
        class Flaky:
            calls = 0
            def quick(self, track):
                Flaky.calls += 1; return {}
        c = Collector(self.store, Flaky(), threading.RLock(), pause=0)
        c.start(A); c.threads[A].join(5)
        self.assertEqual(Flaky.calls, 6)  # 2 tracks x 3 passes
        self.assertEqual(c.status(A)['remaining'], 2)
        self.assertIn('2 músicas', c.status(A)['message'])
        self.assertFalse(c.status(A)['running'])


class PreviewEndpointTests(HTTPTests):
    def test_preview_endpoint(self):
        account = self.session['account']
        self.server.STORE.put(account, record({'id': T1, 'name': 'Song', 'artists': [{'name': 'Artist'}]}))
        with patch.object(self.server.ENRICHER, 'preview', return_value=PREVIEW):
            with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/api/preview?id={T1}', headers={'Cookie': self.cookie})) as r:
                self.assertEqual(json.load(r), {'url': PREVIEW})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/api/preview?id={T2}', headers={'Cookie': self.cookie}))
        self.assertEqual(error.exception.code, 404); error.exception.close()
        self.assertEqual(self.post('collect-start', {})[1]['started'], True)
        self.assertEqual(self.collector.started, [account])


if __name__ == '__main__':
    unittest.main()
