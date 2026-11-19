import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core import Store, record, broad, suggest, DEFAULT_PLAYLISTS
from providers import choose_recording, Enricher, RemoteError
from classification import Ollama, merge_metadata, sample_tracks, expanded_rules
import test_mvp


def track():return record({'id':'q'*22,'name':'Song (feat. Guest)','artists':[{'name':'Artist'},{'name':'Guest'}],'duration_ms':200000,'external_ids':{'isrc':'XX123'}})
def candidate(title='Song',length=200000,ident='one',artist='Artist'):
    return {'id':ident,'title':title,'length':length,'artist-credit':[{'artist':{'name':artist}}]}


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.db')
    def tearDown(self):self.tmp.cleanup()
    def test_credit_normalization_duration_and_version_guard(self):
        t=track()
        self.assertEqual(choose_recording(t,[candidate()])['id'],'one')
        self.assertIsNone(choose_recording(t,[candidate(title='Song - Live')]))
        self.assertIsNone(choose_recording(t,[candidate(artist='Other')]))
        self.assertIsNone(choose_recording(t,[candidate(length=230000)]))
        self.assertEqual(choose_recording(t,[candidate(),candidate(length=204000,ident='two')])['id'],'one')
        self.assertIsNone(choose_recording(t,[candidate(),candidate(length=201000,ident='two')]))
        t.pop('duration_ms');self.assertIsNone(choose_recording(t,[candidate(),candidate(ident='two')]))
    def test_isrc_failure_falls_back_to_title(self):
        enricher=Enricher(self.store,complements=False)
        with patch.object(enricher,'mb',side_effect=[{'recordings':[]},{'recordings':[candidate()]},{'id':'one','genres':[{'name':'metalcore','count':2}]},{'artists':[]}]) as mb:
            result=enricher.enrich(track())
        self.assertEqual(result['genres'],['metalcore'])
        self.assertIn('recording:',mb.call_args_list[1].kwargs['query'])
    def response(self,**changes):
        answer={'genres':['Pop'],'languages':['Português'],'uncertain':False,'reason':'Sugestão para revisão.'}
        answer.update(changes)
        return {'done':True,'message':{'content':json.dumps(answer)}}
    def model(self):return Ollama(self.store,'local:3b')
    def test_structured_output_cache_and_minimal_input(self):
        model=self.model()
        with patch.object(model,'models',return_value=[{'name':'local:3b','digest':'abc'}]),patch('classification.ollama_request',return_value=self.response()) as request:
            result=model.enrich(track());self.assertEqual(result['genres'],['Pop'])
            self.assertEqual(model.enrich(track()),result);self.assertEqual(request.call_count,1)
            body=request.call_args.args[1]
            self.assertFalse(body['stream']);self.assertEqual(body['model'],'local:3b')
            self.assertNotIn('spotify',body['messages'][1]['content'])
            model.enrich(track(),force=True)
            self.assertEqual(request.call_count,2)
            model.model='other:3b'
            with self.assertRaises(ValueError):model.enrich(track())
    def test_uncertain_response_abstains(self):
        model=self.model()
        with patch.object(model,'models',return_value=[{'name':'local:3b'}]),patch('classification.ollama_request',return_value=self.response(uncertain=True)):
            result=model.enrich(track())
        self.assertEqual(result['genres'],[]);self.assertEqual(result['languages'],[])
    def test_invalid_or_failed_response_not_cached(self):
        model=self.model()
        for value in [self.response(genres=['invented']),self.response(languages='Português'),self.response(uncertain='false'),{'done':False},None]:
            with patch.object(model,'models',return_value=[{'name':'local:3b'}]),patch('classification.ollama_request',return_value=value):
                with self.assertRaises(RemoteError):model.enrich(track())
        with patch.object(model,'models',return_value=[{'name':'local:3b'}]),patch('classification.ollama_request',side_effect=RemoteError('offline')):
            with self.assertRaises(RemoteError):model.enrich(track())
        with self.store.connect() as db:self.assertEqual(db.execute('select count(*) from cache').fetchone()[0],0)
    def test_cloud_models_are_excluded(self):
        model=self.model()
        with patch('classification.ollama_request',return_value={'models':[{'name':'local:3b'},{'name':'model:cloud'},{'name':'remote','remote_host':'example.org'}]}):
            self.assertEqual(model.models(),[{'name':'local:3b'}])
    def test_merge_preserves_reviews_and_metadata(self):
        t=track();t.update(genres=['Rock'],languages=['Francês'],review={'genres':['Jazz'],'languages':['Francês'],'playlists':['POP'],'exclude':False})
        before=copy.deepcopy(t)
        result=merge_metadata(t,{'genres':['Pop'],'languages':[],'sources':[],'lookup':'done'})
        self.assertEqual(t,before);self.assertEqual(result['review'],before['review']);self.assertEqual(result['languages'],['Francês']);self.assertEqual(result['genres'],['Rock','Pop'])
    def test_extra_categories_separate_from_rock(self):
        self.assertEqual(broad('metalcore'),['Metal']);self.assertEqual(broad('electro house'),['Eletrônica']);self.assertEqual(broad('hip hop'),['Hip-Hop/Rap'])
    def test_representative_sample_excludes_reviewed_and_assigned(self):
        rules=expanded_rules([]);tracks=[]
        for i in range(45):
            t=track();t['id']=str(i);t['lookup']='done'
            if i%3==0:t['lookup_note']='Identidade ambígua'
            elif i%3==1:t['genres']=['electronic']
            tracks.append(t)
        tracks[0]['review']={'exclude':True,'playlists':[]}
        result=sample_tracks(tracks,DEFAULT_PLAYLISTS,None)
        self.assertEqual(len(result),30);self.assertNotIn('0',[t['id'] for t in result])
        self.assertEqual(len(expanded_rules(rules)),3)
    def test_duration_and_provenance_survive_import(self):
        self.store.names('a');t=track();t['artist_genres']=['Pop'];self.store.put('a',t)
        self.store.import_tracks('a',[{'id':t['id'],'name':t['title'],'artists':[{'name':'Artist'}],'duration_ms':210000}])
        saved=self.store.tracks('a')[0];self.assertEqual(saved['duration_ms'],210000);self.assertEqual(saved['artist_genres'],['Pop'])


class ClassificationHTTPTests(test_mvp.HTTPTests):
    def test_retry_empty_skips_classified_reviewed_and_unrelated_pending(self):
        account=self.session['account']
        empty=track();empty['lookup']='done'
        classified=track();classified.update(id='c'*22,genres=['Jazz'],lookup='done')
        pending=track();pending.update(id='p'*22,languages=['Inglês'])
        reviewed=track();reviewed.update(id='r'*22,lookup='done',review={'genres':[],'languages':[],'playlists':[],'exclude':True})
        for t in [empty,classified,pending,reviewed]:self.server.STORE.put(account,t)
        status,result=self.post('retry-unclassified',{'only_empty':True})
        self.assertEqual(status,200);self.assertEqual(result['count'],1)
        with patch.object(self.server.OLLAMA,'enrich',return_value={'lookup':'done','genres':[],'languages':[],'sources':[]}) as enrich:
            status,result=self.post('enrich',{'source':'ollama','only_empty':True})
            self.assertEqual(status,200);self.assertEqual(result['remaining'],0)
            self.assertEqual(enrich.call_args.kwargs,{'force':True})
            self.assertEqual(enrich.call_args.args[0]['id'],empty['id'])
        saved={t['id']:t for t in self.server.STORE.tracks(account)}
        for t in [classified,pending,reviewed]:self.assertEqual(saved[t['id']],t)

    def test_experiment_is_preview_only_then_explicit_apply(self):
        account=self.session['account'];t=track();t.update(lookup='done',genres=['electronic']);self.server.STORE.put(account,t)
        before=self.server.STORE.tracks(account)
        status,start=self.post('experiment-start',{'source':'saved'});self.assertEqual(status,200,start)
        status,result=self.post('experiment-step',{'id':start['id']});self.assertEqual(status,200,result)
        self.assertEqual(result['assigned'],1);self.assertEqual(result['remaining'],0)
        self.assertEqual(self.server.STORE.tracks(account),before)
        self.assertEqual(self.post('experiment-apply',{'id':start['id'],'confirm':False})[0],400)
        self.assertEqual(self.post('experiment-apply',{'id':start['id'],'confirm':True})[0],200)
        self.assertIn('Eletrônica',self.server.STORE.names(account))
        self.assertEqual(self.server.STORE.tracks(account),before)
    def test_experiment_invalidated_by_review(self):
        t=track();self.server.STORE.put(self.session['account'],t)
        _,start=self.post('experiment-start',{'source':'saved'})
        self.post('review',{'id':t['id'],'genres':[],'languages':[],'playlists':[],'exclude':True})
        self.assertEqual(self.post('experiment-step',{'id':start['id']})[0],400)
    def test_ollama_config_validates_installed_model(self):
        with patch.object(self.server,'METADATA_PATH',Path(self.tmp.name)/'metadata.json'),patch.object(self.server.OLLAMA,'model',''),patch.object(self.server.OLLAMA,'models',return_value=[{'name':'local:3b'}]):
            self.assertEqual(self.post('experiment-start',{'source':'ollama'})[0],400)
            self.assertEqual(self.post('metadata-config',{'ollama_model':'absent'})[0],400)
            self.assertEqual(self.post('metadata-config',{'ollama_model':'local:3b'})[0],200)
            self.assertEqual(json.loads(self.server.METADATA_PATH.read_text()),{'ollama_model':'local:3b'})
            self.assertEqual(self.post('ollama-models',{})[1]['models'],['local:3b'])
            self.assertEqual(self.post('experiment-start',{'source':'lastfm'})[0],400)
    def test_enrich_progress_preserves_review_and_pending_on_error(self):
        account=self.session['account'];t=track();self.server.STORE.put(account,t)
        with patch.object(self.server.OLLAMA,'enrich',side_effect=RemoteError('offline')):
            self.assertEqual(self.post('enrich',{'source':'ollama'})[0],400)
        self.assertEqual(next(x for x in self.server.STORE.tracks(account) if x['id']==t['id'])['lookup'],'pending')
        with patch.object(self.server.OLLAMA,'enrich',return_value={'genres':['Pop'],'languages':[],'sources':[],'lookup':'done'}) as enrich:
            status,result=self.post('enrich',{'source':'ollama'})
            self.assertEqual(status,200,result);self.assertEqual(result['track']['title'],t['title']);self.assertGreaterEqual(result['seconds'],0)
            t['review']={'genres':['Jazz'],'languages':[],'playlists':[],'exclude':False};self.server.STORE.put(account,t)
            self.assertEqual(self.post('enrich',{'source':'ollama'})[1]['remaining'],0)
            self.assertEqual(enrich.call_count,1)
    def test_experiment_returns_next_track_and_does_not_save_on_error(self):
        t=track();self.server.STORE.put(self.session['account'],t)
        with patch.object(self.server.OLLAMA,'model','local:3b'):
            status,start=self.post('experiment-start',{'source':'ollama'})
        self.assertEqual(status,200);self.assertEqual(start['next_track']['id'],t['id'])
        with patch.object(self.server.OLLAMA,'enrich',side_effect=RemoteError('offline')):
            self.assertEqual(self.post('experiment-step',{'id':start['id']})[0],400)
        self.assertEqual(len(self.session['experiment']['queue']),1)
        self.assertEqual(self.session['experiment']['results'],[])



if __name__=='__main__':unittest.main()
