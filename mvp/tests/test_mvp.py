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
        self.db.set_names('a',DEFAULT_PLAYLISTS)
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
        if not (Path(__file__).resolve().parents[1]/'data/revisao-consolidada.json').is_file():
            self.skipTest('Amostra pessoal opcional não distribuída com o aplicativo.')
        self.db.seed('demo:local',Path(__file__).resolve().parents[1]/'data')
        tracks=self.db.tracks('demo:local',True)
        sets=desired_sets(tracks,DEFAULT_PLAYLISTS)
        self.assertEqual({n:len(v) for n,v in sets.items()},{'POP':13,'Sertanejo':4,'Reggaeton':7,'Espanhol':9,'Frances':3,'Trap':6,'Rock':7,'Funk':1})
        self.assertEqual(sum(t['review']['exclude'] for t in tracks),1)
        self.assertEqual(next(t for t in tracks if t['title']=='A Million Dreams')['review']['languages'],['Inglês'])
    def test_combined_rules_rename_and_manual_override(self):
        self.db.import_tracks('a',[raw(),raw(ID2)])
        track=next(t for t in self.db.tracks('a') if t['id']==ID2)
        track.update(genres=['dance pop'],languages=['Espanhol'])
        self.db.put('a',track)
        self.db.target('a','POP','existing')
        self.db.set_rules('a',[{'previous_name':'POP','name':'Pop latino','genres':['Pop'],'languages':['Espanhol']},
                               {'name':'Meu artista','artists':['Artist']}, {'name':'Manual'}])
        names=self.db.names('a');rules=self.db.rules('a')
        self.assertEqual(suggest(track,names,rules),['Pop latino','Meu artista'])
        self.assertEqual(self.db.targets('a'),{'Pop latino':'existing'})
        self.assertEqual(self.db.tracks('a')[0]['review']['playlists'],['Pop latino'])
        track['languages']=['Inglês']
        self.assertEqual(suggest(track,names,rules),['Meu artista'])
        track['review']={'exclude':True,'playlists':['Pop latino']}
        self.assertEqual(suggest(track,names,rules),[])

    def test_automatic_review_uses_corrected_metadata(self):
        self.db.set_rules('a',[{'name':'POP','genres':['Pop'],'languages':['Espanhol']}])
        self.db.review('a',ID1,{'genres':['Pop'],'languages':['Espanhol'],'playlists':[], 'exclude':False,'automatic':True})
        plan=prepare_plan(self.db,'a',FakeSpotify(),{})
        self.assertEqual(plan[0]['uris'],['spotify:track:'+ID1])
        self.db.review('a',ID1,{'genres':['Pop'],'languages':['Espanhol'],'playlists':[], 'exclude':False,'automatic':False})
        self.assertEqual(prepare_plan(self.db,'a',FakeSpotify(),{})[0]['uris'],[])

    def test_invalid_rules_leave_saved_data_unchanged(self):
        before=self.db.rules('a')
        with self.assertRaises(ValueError):self.db.set_rules('a',[{'name':'POP'}, {'name':' pop '}])
        with self.assertRaises(ValueError):self.db.set_rules('a',[{'name':'POP','genres':'Pop'}])
        with self.assertRaises(ValueError):self.db.set_rules('a',[{'name':'Rock'}])
        self.assertEqual(self.db.rules('a'),before)
        self.assertEqual(self.db.rules('b'),[])

    def test_start_without_private_sample(self):
        self.assertEqual(self.db.seed('demo:empty',Path(self.tmp.name)/'missing'),0)
        self.assertEqual(self.db.tracks('demo:empty'),[])
        self.assertEqual(self.db.names('demo:empty'),[])

    def test_import_classify_create_and_update_by_custom_rules(self):
        self.db.names('new')
        self.db.set_rules('new',[{'name':'Minha seleção','artists':['Artist']}])
        self.db.import_tracks('new',[raw()])
        api=FakeSpotify()
        execute_plan(self.db,'new',api,prepare_plan(self.db,'new',api,{}))
        self.db.import_tracks('new',[raw(),raw(ID2)])
        execute_plan(self.db,'new',api,prepare_plan(self.db,'new',api,{}))
        self.assertEqual(len(api.lists),1)
        self.assertEqual(api.lists['p1']['name'],'Minha seleção')
        self.assertEqual(set(api.items['p1']),{'spotify:track:'+ID1,'spotify:track:'+ID2})
        self.assertEqual(len(api.items['p1']),2)
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
        enricher=Enricher(self.db,complements=False)
        candidate={'id':'x','title':'Song','artist-credit':[{'artist':{'name':'Artist'}}]}
        with patch.object(enricher,'mb',return_value={'recordings':[candidate,candidate]}):
            self.assertEqual(enricher.enrich(record(raw()))['genres'],[])
    def test_spotify_pagination_and_relink(self):
        api=Spotify({'account':'a'},'id','redirect')
        pages=[{'items':[{'item':{'uri':'spotify:track:new','linked_from':{'uri':'spotify:track:old'}}}],'next':'https://api.spotify.com/v1/playlists/p/items?offset=1'}, {'items':[{'item':None}],'next':None}]
        with patch.object(api,'call',side_effect=pages): self.assertEqual(api.contents('p'),{'spotify:track:new','spotify:track:old'})
        with patch.object(api,'call',return_value={'items':[],'next':'https://evil.invalid/token'}):
            with self.assertRaises(RemoteError): api.pages('/me/tracks')

class StubCollector:
    def __init__(self): self.started=[]
    def start(self, account): self.started.append(account); return True
    def status(self, account): return {'running':False,'message':'','remaining':0}

class HTTPTests(unittest.TestCase):
    def test_startup_empty_and_samples_disabled(self):
        self.assertEqual(self.state['tracks'],[])
        self.assertEqual(self.state['playlists'],[])
        self.assertEqual(self.state['rules'],[])
        self.assertFalse(self.state['sample_available'])
        self.assertEqual(self.post('demo',{})[0],400)
        self.assertEqual(self.post('pilot-review',{})[0],400)
        self.assertEqual(self.post('rules',{'rules':[]})[0],200)
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/state') as response:
            state=json.load(response)
        self.assertEqual(state['tracks'],[])
        self.assertEqual(state['playlists'],[])
    def setUp(self):
        import server
        self.server=server
        self.tmp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(server,'STORE',Store(Path(self.tmp.name)/'test.sqlite3')),patch.object(server,'SESSIONS',{})]
        for p in self.patches:p.start()
        self.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        self.port=self.http.server_port
        # The background collector never runs in HTTP tests (it would reach the network).
        self.collector=StubCollector()
        self.patches.extend([patch.object(server,'PORT',self.port),patch.object(server,'ORIGIN',f'http://127.0.0.1:{self.port}'),patch.object(server,'COLLECTOR',self.collector)])
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
        except urllib.error.HTTPError as e:
            with e:return e.code,json.load(e)
    def test_origin_csrf_and_demo_write_block(self):
        self.assertEqual(self.post('plan',{},csrf=False)[0],403)
        self.assertEqual(self.post('plan',{},origin=False)[0],403)
        self.assertEqual(self.post('plan',{})[0],400)
    def test_rules_invalidate_preview_and_persist(self):
        self.session['plan']={'id':'old'}
        rules=[{'name':'POP','genres':['Pop'],'languages':[],'artists':[]}]
        rules[0]['name']='Meu Pop'
        status,result=self.post('rules',{'rules':rules})
        self.assertEqual(status,200,result)
        self.assertNotIn('plan',self.session)
        self.assertEqual(self.server.STORE.rules(self.session['account'])[0]['name'],'Meu Pop')

    def test_client_id_persists_without_tokens(self):
        path=Path(self.tmp.name)/'config.json'
        with patch.object(self.server,'CONFIG_PATH',path),patch.object(self.server,'CLIENT_ID',''):
            self.assertEqual(self.post('config',{'client_id':'a'*32})[0],200)
            self.assertEqual(json.loads(path.read_text()),{'client_id':'a'*32})
            self.assertEqual(self.server.load_client_id(),'a'*32)

    def test_first_login_keeps_rules_but_not_personal_tracks(self):
        import time
        rules=[{'name':'POP','genres':['Pop'],'languages':[],'artists':[]}]
        rules[0]['name']='Minha seleção'
        self.assertEqual(self.post('rules',{'rules':rules})[0],200)
        self.session['oauth']={'state':'test-state','verifier':'test-verifier','expires':time.time()+60}
        request=urllib.request.Request(f'http://127.0.0.1:{self.port}/callback?state=test-state&code=test-code',headers={'Cookie':self.cookie})
        with patch.object(self.server,'request_json',return_value={'access_token':'fake','refresh_token':'fake','expires_in':3600}),patch.object(self.server.Spotify,'call',return_value={'id':'real-account'}):
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status,200)
        self.assertEqual(self.server.STORE.rules('real-account')[0]['name'],'Minha seleção')
        self.assertEqual(self.server.STORE.tracks('real-account'),[])
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
