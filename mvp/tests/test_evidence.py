"""Model routing needs evidence; bare 'funk' from sources is not Brazilian funk; reimport keeps flags."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store, suggest, routing_key, needs_routing, matches_rule

RULES=[{'name':'Funk','genres':['Funk'],'languages':[],'artists':[]},
       {'name':'Espanhol','genres':[],'languages':['Espanhol'],'artists':[]},
       {'name':'Viagem','description':'para a estrada','genres':[],'languages':[],'artists':[]}]
NAMES=[r['name'] for r in RULES]

def track(**changes):
    t={'id':'c'*22,'title':'Clint Eastwood','artists':['Gorillaz','Del The Funky Homosapien'],'genres':[],'languages':[],
       'review':None,'routing_required':True,'lookup':'done'}
    t.update(changes);return t

def routed(t,yes):
    t['routing']={'key':routing_key(t,RULES),'model':'m','decisions':[{'playlist':n,'verdict':'yes' if n in yes else 'no','reason':''} for n in NAMES]}
    return t

class EvidenceTests(unittest.TestCase):
    def test_no_metadata_no_model_destination_and_not_routed(self):
        t=routed(track(),{'Funk','Espanhol','Viagem'})
        self.assertEqual(suggest(t,NAMES,RULES),[])
        self.assertFalse(needs_routing(track(),RULES,'m'))
        self.assertTrue(needs_routing(track(genres=['Rock']),RULES,'m'))
        self.assertFalse(needs_routing(track(genres=['Rock'],review={'exclude':False}),RULES,'m'))

    def test_genre_criterion_needs_genre_language_needs_language(self):
        t=routed(track(languages=['Inglês']),{'Funk','Espanhol','Viagem'})
        self.assertEqual(suggest(t,NAMES,RULES),['Espanhol','Viagem'])
        t=routed(track(genres=['Hip-Hop/Rap']),{'Funk','Espanhol'})
        self.assertEqual(suggest(t,NAMES,RULES),['Funk'])

    def test_explicit_criteria_always_count(self):
        t=routed(track(languages=['Espanhol']),set())
        self.assertEqual(suggest(t,NAMES,RULES),['Espanhol'])
        stale=track(languages=['Espanhol'],routing={'key':'old','decisions':[{'playlist':'Funk','verdict':'yes'}]})
        self.assertEqual(suggest(stale,NAMES,RULES),['Espanhol'])

    def test_bare_funk_from_sources_is_american(self):
        rule=RULES[0]
        self.assertFalse(matches_rule(track(genres=['funk'],genre_origin='faixa'),rule))
        self.assertFalse(matches_rule(track(genres=['Funk'],genre_origin='album'),rule))
        self.assertTrue(matches_rule(track(genres=['funk carioca'],genre_origin='faixa'),rule))
        self.assertTrue(matches_rule(track(genres=['Funk'],genre_origin='ia'),rule))
        reviewed=track(genres=['funk'],genre_origin='faixa',review={'exclude':False,'genres':['Funk'],'languages':[],'playlists':[]})
        self.assertTrue(matches_rule(reviewed,rule))
        self.assertTrue(matches_rule(track(genres=['funk'],genre_origin='faixa'),{'name':'X','genres':['Funk Internacional']}))

    def test_reimport_keeps_complements_flag(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'t.sqlite3');raw={'id':'b'*22,'name':'X','artists':[{'name':'Y'}]}
            s.import_tracks('acc',[raw]);t=s.tracks('acc')[0];t['complements_checked']=True;s.put('acc',t)
            s.import_tracks('acc',[raw]);self.assertTrue(s.tracks('acc')[0]['complements_checked'])

if __name__=='__main__':unittest.main()
