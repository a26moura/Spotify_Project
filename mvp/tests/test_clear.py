from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from providers import RemoteError, clear_playlist
import test_mvp

class FakeApi:
    def __init__(self):
        self.lists={'p1':{'id':'p1','name':'Pop'}}
        self.items={'p1':['spotify:track:a','spotify:track:b']}
        self.writes=[]
    def playlists(self):return list(self.lists.values())
    def contents(self,ident):return set(self.items[ident])
    def playlist_tracks(self,ident):return [{'name':u,'uri':u,'artists':[{'name':'X'}]} for u in self.items[ident]]
    def call(self,path,method='GET',body=None):
        self.writes.append((path,method,body));self.items[path.split('/')[2]]=list(body['uris']);return {}

class ClearPlaylistTests(unittest.TestCase):
    def test_clears_only_previewed_owned_playlist(self):
        api=FakeApi()
        self.assertEqual(clear_playlist(api,'p1',['spotify:track:a','spotify:track:b']),2)
        self.assertEqual(api.writes,[('/playlists/p1/items','PUT',{'uris':[]})])
        self.assertEqual(api.items['p1'],[])
    def test_refuses_changed_or_foreign_playlist(self):
        api=FakeApi()
        with self.assertRaises(ValueError):clear_playlist(api,'p1',['spotify:track:a'])
        with self.assertRaises(RemoteError):clear_playlist(api,'other',[])
        self.assertEqual(api.writes,[])
    def test_empty_playlist_needs_no_write(self):
        api=FakeApi();api.items['p1']=[]
        self.assertEqual(clear_playlist(api,'p1',[]),0)
        self.assertEqual(api.writes,[])

class ClearEndpointTests(unittest.TestCase):
    # Reuse the local server fixture without re-running the other HTTP tests.
    setUp=test_mvp.HTTPTests.setUp;tearDown=test_mvp.HTTPTests.tearDown;post=test_mvp.HTTPTests.post
    def test_preview_then_single_confirmed_clear(self):
        fake=FakeApi()
        self.session['token']={'access_token':'fake'}
        account=self.session['account']
        self.server.STORE.save_spotify_library(account,{'playlists':[{'id':'p1','name':'Pop','owned':True,'tracks':[{'title':'a'}]}],'synced_at':1})
        with patch.object(self.server.Handler,'api',return_value=fake):
            status,preview=self.post('clear-preview',{'id':'p1'})
            self.assertEqual(status,200,preview);self.assertEqual(preview['count'],2)
            self.assertEqual(fake.writes,[])
            self.assertEqual(self.post('clear-execute',{'id':preview['id'],'confirm':False})[0],400)
            self.assertEqual(fake.writes,[])  # a refused confirmation also discards the preview
            status,preview=self.post('clear-preview',{'id':'p1'})
            status,result=self.post('clear-execute',{'id':preview['id'],'confirm':True})
            self.assertEqual(status,200,result);self.assertEqual(result['removed'],2)
            self.assertEqual(self.post('clear-execute',{'id':preview['id'],'confirm':True})[0],400)
            self.assertEqual(len(fake.writes),1)
            self.assertEqual(self.post('clear-preview',{'id':'unknown'})[0],400)
        self.assertEqual(self.server.STORE.spotify_library(account)['playlists'][0]['tracks'],[])

if __name__=='__main__':unittest.main()

from unittest.mock import patch as _patch
from core import routing_key, suggest, needs_routing
from test_classification import track

class RoutingResetTests(unittest.TestCase):
    setUp=test_mvp.HTTPTests.setUp;tearDown=test_mvp.HTTPTests.tearDown;post=test_mvp.HTTPTests.post
    def test_reset_one_playlist_only_in_app(self):
        account=self.session['account'];store=self.server.STORE
        store.set_rules(account,[{'name':'Viagem','description':'rock'},{'name':'Festa','description':'dançar'}])
        rules=store.rules(account);names=store.names(account)
        t=track();t.update(lookup='done',genres=['Rock'],routing_required=True)
        t['routing']={'key':routing_key(t,rules),'model':'local','decisions':[{'playlist':'Viagem','verdict':'yes','reason':'r'},{'playlist':'Festa','verdict':'yes','reason':'f'}]}
        store.put(account,t)
        manual=track();manual.update(id='c'*22,uri='spotify:track:'+'c'*22,review={'exclude':False,'automatic':False,'playlists':['Viagem'],'genres':[],'languages':[]},routing=dict(t['routing']))
        store.put(account,manual)
        with _patch.object(self.server.OLLAMA,'model','local'):
            self.assertEqual(self.post('routing-reset',{'name':'Outra'})[0],400)
            status,result=self.post('routing-reset',{'name':'Viagem'})
            self.assertEqual(status,200,result);self.assertEqual(result['count'],1)
            saved={x['id']:x for x in store.tracks(account)}
            self.assertEqual(suggest(saved[t['id']],names,rules),['Festa'])
            self.assertEqual(suggest(saved[manual['id']],names,rules),['Viagem'])
            self.assertTrue(needs_routing(saved[t['id']],rules,'local'))
            partial={'key':'x','model':'local','decisions':[{'playlist':'Viagem','verdict':'no','reason':'n'}]}
            with _patch.object(self.server.OLLAMA,'route',return_value=partial) as route:
                self.assertEqual(self.post('route-step',{})[1]['remaining'],0)
            self.assertEqual([r['name'] for r in route.call_args[0][1]],['Viagem'])
            final=next(x for x in store.tracks(account) if x['id']==t['id'])
            self.assertFalse(needs_routing(final,rules,'local'))
            self.assertEqual(sorted((d['playlist'],d['verdict']) for d in final['routing']['decisions']),[('Festa','yes'),('Viagem','no')])
