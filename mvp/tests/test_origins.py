import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store, infer_origin
from providers import Enricher
from classification import merge_metadata

TRACK={'id':'a'*22,'title':'Envolver','artists':['Anitta'],'genres':[],'languages':[],'duration_ms':None,'isrc':None}

def rec(rid,artist_id='art1',name='Anitta',title='Envolver'):
    return {'id':rid,'title':title,'artist-credit':[{'artist':{'id':artist_id,'name':name}}]}

class FakeEnricher(Enricher):
    def __init__(self,store,responses):
        super().__init__(store,complements=False);self.responses=responses;self.calls=[]
    def mb(self,entity,ident='',**params):
        self.calls.append((entity,ident,params.get('query')))
        return self.responses(entity,ident,params)
    def get(self,url):
        raise AssertionError('unexpected network call '+url)

class EnrichOriginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'t.sqlite3')
    def tearDown(self):self.tmp.cleanup()

    def test_ambiguous_recordings_with_same_artist_use_artist_genres(self):
        def r(entity,ident,params):
            if entity=='recording':return {'recordings':[rec('r1'),rec('r2')]}
            if entity=='artist' and ident=='art1':return {'name':'Anitta','genres':[{'name':'funk carioca','count':5},{'name':'pop','count':9}],'relations':[]}
            raise AssertionError((entity,ident))
        result=FakeEnricher(self.store,r).enrich(dict(TRACK))
        self.assertEqual(result['genre_origin'],'artista')
        self.assertEqual(result['genres'],['pop','funk carioca'])
        self.assertIn('ambígua',result['lookup_note'])
        self.assertIn('pelo artista',result['lookup_note'])
        self.assertNotIn('language_origin',result)

    def test_track_genres_keep_artist_as_extra_labels(self):
        def r(entity,ident,params):
            if entity=='recording' and not ident:return {'recordings':[rec('r1')]}
            if entity=='recording':return {'id':'r1','genres':[{'name':'reggaeton'}],'tags':[],'relations':[]}
            if entity=='artist' and ident=='art1':return {'name':'Anitta','genres':[{'name':'funk carioca','count':5}],'relations':[]}
            raise AssertionError((entity,ident))
        e=FakeEnricher(self.store,r);result=e.enrich(dict(TRACK))
        self.assertEqual(result['genre_origin'],'faixa');self.assertEqual(result['genres'],['reggaeton'])
        self.assertIn(('funk carioca','artist-genre'),[(l['label'],l['kind']) for l in result['source_labels']])
        self.assertTrue(result['artist_labels']);self.assertNotIn('artist_genres',result)

    def test_artist_search_ambiguous_name_gives_nothing(self):
        def r(entity,ident,params):
            if entity=='recording':return {'recordings':[]}
            if entity=='artist' and not ident:return {'artists':[{'id':'x','name':'Anitta'},{'id':'y','name':'ANITTA'}]}
            raise AssertionError((entity,ident))
        result=FakeEnricher(self.store,r).enrich(dict(TRACK))
        self.assertEqual(result['genres'],[]);self.assertNotIn('genre_origin',result)

    def test_artist_search_unique_exact_name(self):
        def r(entity,ident,params):
            if entity=='recording':return {'recordings':[]}
            if entity=='artist' and not ident:return {'artists':[{'id':'x','name':'Anitta'},{'id':'y','name':'Anitta Cover Band'}]}
            if entity=='artist' and ident=='x':return {'name':'Anitta','genres':[{'name':'pop','count':1}],'relations':[]}
            raise AssertionError((entity,ident))
        result=FakeEnricher(self.store,r).enrich(dict(TRACK))
        self.assertEqual((result['genres'],result['genre_origin']),(['pop'],'artista'))

    def test_existing_genres_are_not_replaced_by_artist(self):
        def r(entity,ident,params):
            if entity=='recording':return {'recordings':[]}
            if entity=='artist' and not ident:return {'artists':[{'id':'x','name':'Anitta'}]}
            if entity=='artist' and ident=='x':return {'name':'Anitta','genres':[{'name':'funk carioca','count':1}],'relations':[]}
            raise AssertionError((entity,ident))
        result=FakeEnricher(self.store,r).enrich(dict(TRACK,genres=['Pop'],genre_origin='ia'))
        self.assertEqual(result['genres'],[]);self.assertNotIn('genre_origin',result)
        self.assertIn(('funk carioca','artist-genre'),[(l['label'],l['kind']) for l in result['source_labels']])

    def test_wikidata_artist_genres_are_labels_even_with_musicbrainz_genres(self):
        class WD(FakeEnricher):
            def wikidata_labels(self,target,prop):return ['reggaeton','Latin trap']
        def r(entity,ident,params):
            if entity=='recording':return {'recordings':[rec('r1'),rec('r2')]}
            if entity=='artist':return {'name':'Bad Bunny','genres':[{'name':'latin','count':3}],
                                        'relations':[{'url':{'resource':'https://www.wikidata.org/wiki/Q1'}}]}
            raise AssertionError((entity,ident))
        result=WD(self.store,r).enrich(dict(TRACK))
        self.assertEqual((result['genres'],result['genre_origin']),(['latin'],'artista'))
        self.assertIn(('reggaeton','artist-genre'),[(l['label'],l['kind']) for l in result['source_labels']])

class MergeTests(unittest.TestCase):
    def test_priority(self):
        artist=merge_metadata(dict(TRACK),{'genres':['pop'],'genre_origin':'artista','artist_genres':['pop']})
        self.assertEqual((artist['genres'],artist['genre_origin'],artist['artist_genres']),(['pop'],'artista',['pop']))
        ai=merge_metadata(artist,{'genres':['Reggaeton'],'languages':['Espanhol'],'genre_origin':'ia','language_origin':'ia','ai_checked':'m'})
        self.assertEqual(ai['genres'],['pop']);self.assertEqual(ai['genre_origin'],'artista')
        self.assertEqual((ai['languages'],ai['language_origin'],ai['ai_checked']),(['Espanhol'],'ia','m'))
        track=merge_metadata(ai,{'genres':['reggaeton'],'genre_origin':'faixa','languages':['Português'],'language_origin':'faixa'})
        self.assertEqual((track['genres'],track['genre_origin']),(['reggaeton'],'faixa'))
        self.assertEqual((track['languages'],track['language_origin']),(['Português'],'faixa'))
        self.assertNotIn('artist_genres',track)

    def test_ai_keeps_previous_note(self):
        t=dict(TRACK,lookup_note='Gênero sugerido pelo artista X.')
        out=merge_metadata(t,{'languages':['Inglês'],'language_origin':'ia','genre_origin':'ia','lookup_note':'Sugestão de IA.'})
        self.assertEqual(out['lookup_note'],'Gênero sugerido pelo artista X. · IA: Sugestão de IA.')
        again=merge_metadata(out,{'genre_origin':'ia','lookup_note':'Outra.'})
        self.assertEqual(again['lookup_note'],'Gênero sugerido pelo artista X. · IA: Outra.')

    def test_infer_legacy(self):
        self.assertIsNone(infer_origin(TRACK,'genre'))
        self.assertEqual(infer_origin(dict(TRACK,genres=['pop']),'genre'),'faixa')
        self.assertEqual(infer_origin(dict(TRACK,genres=['pop'],classification_source='Ollama · m'),'genre'),'ia')
        self.assertEqual(infer_origin(dict(TRACK,genres=['pop'],artist_genres=['pop']),'genre'),'artista')

class ImportTests(unittest.TestCase):
    def test_reimport_preserves_origins(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'t.sqlite3');raw={'id':'b'*22,'name':'X','artists':[{'name':'Y'}]}
            s.import_tracks('acc',[raw]);t=s.tracks('acc')[0]
            t.update(genres=['pop'],genre_origin='artista',artist_checked=True,ai_checked='m');s.put('acc',t)
            s.import_tracks('acc',[raw]);t=s.tracks('acc')[0]
            self.assertEqual((t['genre_origin'],t['artist_checked'],t['ai_checked']),('artista',True,'m'))

if __name__=='__main__':unittest.main()
