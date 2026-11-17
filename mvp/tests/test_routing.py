import copy
import json
from unittest.mock import patch
import unittest
import test_classification
from test_classification import track
import test_mvp
from classification import Ollama, merge_metadata
from core import suggest, routing_key
from providers import Enricher, RemoteError

class RoutingTests(unittest.TestCase):
    setUp=test_classification.ClassificationTests.setUp
    tearDown=test_classification.ClassificationTests.tearDown
    def test_raw_labels_preserved_and_not_collapsed(self):
        t=track();provider=Enricher(self.store,complements=False)
        with patch.object(provider,'mb',side_effect=[{'recordings':[{'id':'one','title':'Song','artist-credit':[{'artist':{'name':'Artist'}}],'length':200000}]},{'id':'one','genres':[{'name':'alternative rock','count':3},{'name':'indie rock','count':2}],'tags':[{'name':'energetic','count':1}]}]):
            result=provider.enrich(t)
        self.assertTrue(result['labels_collected'])
        self.assertTrue(merge_metadata(t,result)['labels_collected'])
        self.assertNotIn('labels_collected',merge_metadata(t,{'genres':['Rock']}))
        self.assertEqual(result['genres'],['alternative rock','indie rock'])
        self.assertEqual([x['label'] for x in result['source_labels']],['alternative rock','indie rock','energetic'])
        merged=merge_metadata(t,result)
        self.assertEqual(merge_metadata(merged,result)['source_labels'],merged['source_labels'])

    def test_model_routes_multiple_and_invalidates_changed_evidence(self):
        t=track();t.update(genres=['alternative rock','indie rock'],routing_required=True)
        rules=[{'name':'Estrada','description':'rock para viajar'},{'name':'Indie'}]
        answer={'decisions':[{'playlist':r['name'],'verdict':'yes','reason':'Rótulos compatíveis.'} for r in rules]}
        model=Ollama(self.store,'local')
        with patch.object(model,'models',return_value=[{'name':'local'}]),patch('classification.ollama_request',return_value={'done':True,'message':{'content':json.dumps(answer)}}):
            t['routing']=model.route(t,rules)
        self.assertEqual(suggest(t,['Estrada','Indie'],rules),['Estrada','Indie'])
        t['genres'].append('Jazz')
        self.assertEqual(suggest(t,['Estrada','Indie'],rules),[])
        t['review']={'exclude':False,'automatic':False,'playlists':['Indie']}
        self.assertEqual(suggest(t,['Estrada','Indie'],rules),['Indie'])

    def test_invalid_model_decisions_rejected(self):
        model=Ollama(self.store,'local')
        for decisions in [[],[{'playlist':'Wrong','verdict':'yes','reason':'X'}],[{'playlist':'Rock','verdict':'maybe','reason':'X'}]]:
            with patch.object(model,'models',return_value=[{'name':'local'}]),patch('classification.ollama_request',return_value={'done':True,'message':{'content':json.dumps({'decisions':decisions})}}):
                with self.assertRaises(RemoteError):model.route(track(),[{'name':'Rock'}])

class RoutingHTTPTests(test_mvp.HTTPTests):
    def test_independent_labels_and_routing_preserve_manual(self):
        account=self.session['account'];t=track();t['lookup']='done';t['genres']=['Rock']
        self.server.STORE.put(account,t)
        self.assertEqual(self.post('labels-start',{})[0],200)
        saved=self.server.STORE.tracks(account)[0]
        self.assertEqual(saved['lookup'],'pending');self.assertTrue(saved['routing_required'])
        self.server.STORE.set_rules(account,[{'name':'Viagem','description':'rock'}])
        rules=self.server.STORE.rules(account)
        with patch.object(self.server.OLLAMA,'model','local'):
            self.assertEqual(self.post('route-start',{})[0],200)
            with patch.object(self.server.OLLAMA,'route',side_effect=RemoteError('offline')):
                self.assertEqual(self.post('route-step',{})[0],400)
            self.assertNotIn('routing',self.server.STORE.tracks(account)[0])
            routing={'key':routing_key(saved,rules),'model':'local','decisions':[{'playlist':'Viagem','verdict':'yes','reason':'Rock'}]}
            with patch.object(self.server.OLLAMA,'route',return_value=routing) as route:
                self.assertEqual(self.post('route-step',{})[1]['remaining'],0)
                self.assertEqual(self.post('route-step',{})[1]['remaining'],0)
                self.assertEqual(route.call_count,1)
        self.assertEqual(self.server.STORE.tracks(account)[0]['genres'],['Rock'])
