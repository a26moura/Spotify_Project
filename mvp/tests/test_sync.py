from unittest.mock import patch
from core import record
from providers import RemoteError, Spotify
import game
from test_mvp import HTTPTests, raw, ID1, ID2

class SyncTests(HTTPTests):
    def test_sync_preserves_reviews_and_reads_only_own_playlists(self):
        account=self.session['account'];self.session['token']={'access_token':'fake'}
        t=record(raw());t['genres']=['Jazz'];t['lookup']='done'
        self.server.STORE.put(account,t)
        playlists=[{'id':'owned','name':'Jazz','owner':{'id':account},'snapshot_id':'s1'}]
        only_in_playlist=dict(raw(ID2),album={'name':'Disco','release_date':'1999-05-01','images':[{'url':'big','width':640},{'url':'mid','width':300}]})
        with patch.object(Spotify,'library',return_value=[dict(raw(),added_at='2026-01-02T00:00:00Z')]),patch.object(Spotify,'playlists',return_value=playlists),patch.object(Spotify,'playlist_tracks',return_value=[raw(),only_in_playlist]) as contents:
            status,start=self.post('sync-start',{});self.assertEqual(status,200,start)
            self.assertIsNone(self.server.STORE.spotify_library(account)['synced_at'])
            status,result=self.post('sync-step',{'id':start['id']});self.assertEqual(result['remaining'],0)
            contents.assert_called_once_with('owned')
        tracks={t['id']:t for t in self.server.STORE.tracks(account)}
        self.assertEqual(tracks[ID1]['genres'],['Jazz'])
        self.assertEqual(tracks[ID1]['lookup'],'done')
        self.assertTrue(tracks[ID1]['liked']);self.assertEqual(tracks[ID1]['added_at'],'2026-01-02T00:00:00Z')
        self.assertFalse(tracks[ID2]['liked']);self.assertTrue(tracks[ID2]['active'])
        self.assertEqual((tracks[ID2]['album'],tracks[ID2]['year'],tracks[ID2]['cover']),('Disco',1999,'mid'))
        snapshot=self.server.STORE.spotify_library(account)
        self.assertEqual(len(snapshot['playlists'][0]['tracks']),2)
        self.assertEqual([p['key'] for p in game.profiles(self.server.STORE,account)],['owned'])
        self.assertEqual(self.post('adopt-playlist',{'id':'owned'})[0],200)
        self.assertEqual(self.server.STORE.targets(account),{'Jazz':'owned'})

    def test_failed_sync_preserves_library_and_can_resume(self):
        account=self.session['account'];self.session['token']={'access_token':'fake'}
        original=record(raw());original['genres']=['Rock'];self.server.STORE.put(account,original)
        self.server.STORE.save_spotify_library(account,{'playlists':[],'synced_at':123})
        with patch.object(Spotify,'library',return_value=[]),patch.object(Spotify,'playlists',return_value=[{'id':'p','name':'P','owner':{'id':account}}]):
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
