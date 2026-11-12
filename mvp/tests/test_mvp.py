import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import DEFAULT_PLAYLISTS, Store, desired_sets, record, suggest
from providers import Enricher, RemoteError, Spotify, execute_plan, prepare_plan

ID1='a'*22
ID2='b'*22
def raw(ident=ID1): return {'id':ident,'name':'Song','artists':[{'name':'Artist'}]}

class FakeSpotify:
    def __init__(self):
        self.lists={}
        self.items={}
        self.writes=[]
        self.lose_add=False
        self.lose_create=False
    def playlists(self): return list(self.lists.values())
    def contents(self,ident): return set(self.items[ident])
    def call(self,path,method='GET',body=None):
        self.writes.append((path,copy.deepcopy(body)))
        if path=='/me/playlists':
            ident='p'+str(len(self.lists)+1)
            self.lists[ident]={'id':ident,**body}; self.items[ident]=[]
            if self.lose_create:
                self.lose_create=False
                raise RemoteError('Resposta perdida após criação')
            return self.lists[ident]
        ident=path.split('/')[2]
        self.items[ident].extend(body['uris'])
        if self.lose_add:
            self.lose_add=False
            raise RemoteError('Resposta perdida após adição')
        return {}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Store(Path(self.tmp.name)/'app.sqlite3')
        self.db.names('a')
        self.db.import_tracks('a',[raw()])
        self.db.review('a',ID1,{'genres':['Pop'],'languages':['Inglês'],'playlists':['POP'],'exclude':False})
    def tearDown(self): self.tmp.cleanup()
    def test_import_keeps_review_and_marks_removed(self):
        self.db.import_tracks('a',[raw(),raw(ID1),raw(ID2)])
        self.assertEqual(len(self.db.tracks('a',True)),2)
        self.assertEqual(self.db.tracks('a')[0]['review']['playlists'],['POP'])
        self.db.import_tracks('a',[raw(ID2)])
        self.assertFalse(self.db.tracks('a')[0]['active'])
        self.db.import_tracks('a',[raw()])
        self.assertEqual(self.db.tracks('a',True)[0]['review']['playlists'],['POP'])
    def test_account_isolation(self):
        self.db.names('b');self.db.import_tracks('b',[raw()])
        self.assertIsNone(self.db.tracks('b')[0]['review'])
        self.db.target('a','POP','p1')
        self.assertEqual(self.db.targets('b'),{})
    def test_exclusion_and_empty_override(self):
        self.db.review('a',ID1,{'genres':[],'languages':[],'playlists':['POP'],'exclude':True})
        self.assertEqual(desired_sets(self.db.tracks('a'),DEFAULT_PLAYLISTS)['POP'],set())
        self.db.review('a',ID1,{'genres':[],'languages':[],'playlists':[],'exclude':False})
        self.assertEqual(suggest(self.db.tracks('a')[0],DEFAULT_PLAYLISTS),[])
    def test_invalid_destinations_and_account_track(self):
        with self.assertRaises(ValueError): self.db.review('a',ID2,{'playlists':[]})
        with self.assertRaises(ValueError): self.db.set_names('a',['Rock'])
        with self.assertRaises(ValueError): self.db.set_names('a',['POP','pop'])
    def test_seed_matches_user_decisions(self):
        self.db.seed('demo:local',Path(__file__).resolve().parents[1]/'data')
        tracks=self.db.tracks('demo:local',True)
        sets=desired_sets(tracks,DEFAULT_PLAYLISTS)
        self.assertEqual({n:len(v) for n,v in sets.items()},{'POP':13,'Sertanejo':4,'Reggaeton':7,'Espanhol':9,'Frances':3,'Trap':6,'Rock':7,'Funk':1})
        self.assertEqual(sum(t['review']['exclude'] for t in tracks),1)
        self.assertEqual(next(t for t in tracks if t['title']=='A Million Dreams')['review']['languages'],['Inglês'])
    def test_prepare_never_writes_and_repeat_never_duplicates(self):
        api=FakeSpotify()
        plan=prepare_plan(self.db,'a',api,{})
        self.assertEqual(api.writes,[])
        execute_plan(self.db,'a',api,plan)
        self.assertEqual(api.items['p1'],['spotify:track:'+ID1])
        plan=prepare_plan(self.db,'a',api,{})
        self.assertEqual(plan[0]['uris'],[])
        execute_plan(self.db,'a',api,plan)
        self.assertEqual(len(api.items['p1']),1)
        self.assertEqual(len(api.lists),1)
    def test_lost_add_response_can_resume(self):
        api=FakeSpotify();api.lose_add=True
        execute_plan(self.db,'a',api,prepare_plan(self.db,'a',api,{}))
        execute_plan(self.db,'a',api,prepare_plan(self.db,'a',api,{}))
        self.assertEqual(len(api.items['p1']),1)
    def test_lost_create_response_recovers_marker(self):
        api=FakeSpotify();api.lose_create=True
        execute_plan(self.db,'a',api,prepare_plan(self.db,'a',api,{}))
        execute_plan(self.db,'a',api,prepare_plan(self.db,'a',api,{}))
        self.assertEqual(len(api.lists),1)
        self.assertEqual(len(api.items['p1']),1)
    def test_duplicate_targets_rejected(self):
        api=FakeSpotify();api.lists['p1']={'id':'p1','name':'Existing'};api.items['p1']=[]
        with self.assertRaises(ValueError):prepare_plan(self.db,'a',api,{'POP':'p1','Rock':'p1'})
    def test_batches_and_unrelated_music_preserved(self):
        api=FakeSpotify();api.lists['p1']={'id':'p1','name':'Existing'};api.items['p1']=['spotify:track:unrelated']
        uris=['spotify:track:'+str(i).zfill(22) for i in range(205)]
        execute_plan(self.db,'a',api,[{'name':'POP','id':'p1','uris':uris}])
        self.assertEqual(len(api.items['p1']),206)
        self.assertEqual([len(b['uris']) for p,b in api.writes],[100,100,5])
    def test_candidate_ambiguity_stays_unknown(self):
        enricher=Enricher(self.db)
        candidate={'id':'x','title':'Song','artist-credit':[{'artist':{'name':'Artist'}}]}
        with patch.object(enricher,'mb',return_value={'recordings':[candidate,candidate]}):
            self.assertEqual(enricher.enrich(record(raw()))['genres'],[])
    def test_spotify_pagination_and_relink(self):
        api=Spotify({'account':'a'},'id','redirect')
        pages=[{'items':[{'item':{'uri':'spotify:track:new','linked_from':{'uri':'spotify:track:old'}}}],'next':'https://api.spotify.com/v1/playlists/p/items?offset=1'}, {'items':[{'item':None}],'next':None}]
        with patch.object(api,'call',side_effect=pages): self.assertEqual(api.contents('p'),{'spotify:track:new','spotify:track:old'})
        with patch.object(api,'call',return_value={'items':[],'next':'https://evil.invalid/token'}):
            with self.assertRaises(RemoteError): api.pages('/me/tracks')

class HTTPTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server=server
        self.tmp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(server,'STORE',Store(Path(self.tmp.name)/'test.sqlite3')),patch.object(server,'SESSIONS',{})]
        for p in self.patches:p.start()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.port=self.http.server_port
        self.patches.extend([patch.object(server,'PORT',self.port),patch.object(server,'ORIGIN',f'http://127.0.0.1:{self.port}')])
        for p in self.patches[2:]:p.start()
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/state') as r:
            self.cookie=r.headers['Set-Cookie'].split(';')[0];self.state=json.load(r)
        self.session=next(iter(server.SESSIONS.values()))
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def post(self,path,data,csrf=True,origin=True):
        headers={'Content-Type':'application/json','Cookie':self.cookie}
        if csrf:headers['X-CSRF-Token']=self.state['csrf']
        if origin:headers['Origin']=f'http://127.0.0.1:{self.port}'
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/'+path,data=json.dumps(data).encode(),headers=headers)
        try:
            with urllib.request.urlopen(request) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    def test_origin_csrf_and_demo_write_block(self):
        self.assertEqual(self.post('plan',{},csrf=False)[0],403)
        self.assertEqual(self.post('plan',{},origin=False)[0],403)
        self.assertEqual(self.post('plan',{})[0],400)
    def test_confirmation_expiry_staleness_and_replay(self):
        import time
        self.session['token']={'access_token':'fake'}
        def plan(): return {'id':'unique','revision':0,'expires':time.time()+100,'plans':[]}
        with patch.object(self.server,'execute_plan',return_value=[]) as execute:
            self.session['plan']=plan()
            self.assertEqual(self.post('execute',{'id':'unique','confirm':False})[0],400)
            execute.assert_not_called()
            self.session['plan']=dict(plan(),revision=2)
            self.assertEqual(self.post('execute',{'id':'unique','confirm':True})[0],400)
            self.session['plan']=dict(plan(),expires=0)
            self.assertEqual(self.post('execute',{'id':'unique','confirm':True})[0],400)
            self.session['plan']=plan()
            self.assertEqual(self.post('execute',{'id':'unique','confirm':True})[0],200)
            self.assertEqual(self.post('execute',{'id':'unique','confirm':True})[0],400)
            execute.assert_called_once()

if __name__=='__main__':unittest.main()
