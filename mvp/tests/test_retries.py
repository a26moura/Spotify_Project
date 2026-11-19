import io
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from providers import Enricher, RemoteError, request_json, retry_delay

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite3')
        self.enricher=Enricher(self.store)
        self.url='https://lrclib.net/api/get?track_name=test'
        self.error=RemoteError('LRCLIB HTTP 503',status=503,transient=True)
    def tearDown(self):self.tmp.cleanup()

    def test_transient_failure_recovers_and_caches(self):
        with patch('providers.request_json',side_effect=[self.error,self.error,{'recordings':[]}]) as get,patch('providers.time.sleep') as sleep:
            self.assertEqual(self.enricher.get(self.url),{'recordings':[]})
            self.assertEqual(get.call_count,3)
            self.assertIn(2,[c.args[0] for c in sleep.call_args_list])
            self.assertIn(4,[c.args[0] for c in sleep.call_args_list])
            self.enricher.get(self.url)
            self.assertEqual(get.call_count,3)

    def test_exhausted_retries_pause_source_and_do_not_cache_failure(self):
        with patch('providers.request_json',side_effect=self.error) as get,patch('providers.time.sleep'):
            with self.assertRaisesRegex(RemoteError,'3 tentativa'):self.enricher.get(self.url)
            with self.assertRaisesRegex(RemoteError,'consultas pausadas'):self.enricher.get(self.url)
            self.assertEqual(get.call_count,3)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM cache').fetchone()[0],0)
        self.enricher.cooldowns.clear()
        with patch('providers.request_json',return_value={'recordings':[]}),patch('providers.time.sleep'):
            self.assertEqual(self.enricher.get(self.url),{'recordings':[]})

    def test_long_retry_after_does_not_block_thread_or_retry_early(self):
        error=RemoteError('Limited',status=429,transient=True,retry_after=120)
        with patch('providers.request_json',side_effect=error) as get,patch('providers.time.sleep') as sleep:
            with self.assertRaisesRegex(RemoteError,'120 segundos'):self.enricher.get(self.url)
            self.assertEqual(get.call_count,1)
            self.assertTrue(all(c.args[0]<2 for c in sleep.call_args_list))

    def test_nontransient_error_not_retried(self):
        with patch('providers.request_json',side_effect=RemoteError('Bad request',status=400)) as get,patch('providers.time.sleep'):
            with self.assertRaises(RemoteError):self.enricher.get(self.url)
            self.assertEqual(get.call_count,1)

    def test_http_error_identifies_source_and_retry_after(self):
        error=urllib.error.HTTPError(self.url,503,'Busy',{'Retry-After':'7'},io.BytesIO(b'busy'))
        with patch('providers.urllib.request.urlopen',side_effect=error):
            with self.assertRaises(RemoteError) as caught:request_json(self.url)
        self.assertIn('LRCLIB',str(caught.exception))
        self.assertNotIn('grava',str(caught.exception))
        self.assertTrue(caught.exception.transient)
        self.assertEqual(caught.exception.retry_after,7)

    def test_spotify_post_is_never_retried(self):
        url='https://api.spotify.com/v1/me/playlists'
        error=urllib.error.HTTPError(url,503,'Busy',{},io.BytesIO())
        with patch('providers.urllib.request.urlopen',side_effect=error) as send:
            with self.assertRaisesRegex(RemoteError,'Não houve repetição automática'):request_json(url,'POST',{'name':'test'})
            self.assertEqual(send.call_count,1)

    def test_retry_after_formats(self):
        self.assertEqual(retry_delay('12'),12)
        self.assertEqual(retry_delay('garbage'),0)
        self.assertEqual(retry_delay(None),0)
        with patch('providers.time.time',return_value=0):
            self.assertEqual(retry_delay('Thu, 01 Jan 1970 00:01:00 GMT'),61)

if __name__=='__main__':unittest.main()
