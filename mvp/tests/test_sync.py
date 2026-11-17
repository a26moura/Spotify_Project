from unittest.mock import patch
from core import record
from providers import RemoteError, Spotify
from test_mvp import HTTPTests, raw

class SyncTests(HTTPTests):
    def test_sync_preserves_reviews_and_reads_playlist_content(self):
        account=self.session['account'];self.session['token']={'access_token':'fake'}
        t=record(raw());t['genres']=['Jazz'];t['lookup']='done'
        self.server.STORE.put(account,t)
        playlists=[{'id':'owned','name':'Jazz','owner':{'id':account}}, {'id':'followed','name':'Outra','owner':{'id':'other'}}]
        with patch.object(Spotify,'library',return_value=[raw()]),patch.object(Spotify,'all_playlists',return_value=playlists),patch.object(Spotify,'playlist_tracks',return_value=[raw()]) as contents:
            status,start=self.post('sync-start',{});self.assertEqual(status,200,start)
            status,result=self.post('sync-step',{'id':start['id']});self.assertEqual(result['remaining'],1)
            self.assertIsNone(self.server.STORE.spotify_library(account)['synced_at'])
            status,result=self.post('sync-step',{'id':start['id']});self.assertEqual(result['remaining'],0)
            contents.assert_called_once_with('owned')
        self.assertEqual(self.server.STORE.tracks(account)[0]['genres'],['Jazz'])
        self.assertEqual(self.server.STORE.tracks(account)[0]['lookup'],'done')
        snapshot=self.server.STORE.spotify_library(account)
        self.assertEqual(len(snapshot['playlists'][0]['tracks']),1)
        self.assertTrue(snapshot['playlists'][1]['unavailable'])
        self.assertEqual(self.post('adopt-playlist',{'id':'owned'})[0],200)
        self.assertEqual(self.server.STORE.targets(account),{'Jazz':'owned'})
        self.assertEqual(self.server.STORE.rules(account)[0]['genres'],[])
        self.assertEqual(self.post('adopt-playlist',{'id':'followed'})[0],400)

    def test_failed_sync_preserves_library_and_can_resume(self):
        account=self.session['account'];self.session['token']={'access_token':'fake'}
        original=record(raw());original['genres']=['Rock'];self.server.STORE.put(account,original)
        self.server.STORE.save_spotify_library(account,{'playlists':[],'synced_at':123})
        with patch.object(Spotify,'library',return_value=[]),patch.object(Spotify,'all_playlists',return_value=[{'id':'p','name':'P','owner':{'id':account}}]):
            _,start=self.post('sync-start',{})
        with patch.object(Spotify,'playlist_tracks',side_effect=RemoteError('offline')):
            self.assertEqual(self.post('sync-step',{'id':start['id']})[0],400)
        self.assertEqual(self.server.STORE.tracks(account),[original])
        self.assertEqual(self.server.STORE.spotify_library(account)['synced_at'],123)
        with patch.object(Spotify,'playlist_tracks',return_value=[]):
            self.assertEqual(self.post('sync-step',{'id':start['id']})[1]['remaining'],0)
        self.assertEqual(self.server.STORE.tracks(account,active=True),[])

    def test_playlist_item_formats(self):
        api=Spotify({'account':'a'},'', '')
        with patch.object(api,'pages',return_value=[{'item':raw()},{'track':raw()},None,{'item':{'type':'episode'}}]):
            self.assertEqual(len(api.playlist_tracks('p')),2)
