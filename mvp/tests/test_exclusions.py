"""Per-playlist "rótulos que não contam" (exclude_labels)."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store, suggest, routing_key, matches_rule, excluded_labels

TRAP={'name':'Trap - Br','genres':['Trap'],'languages':[],'artists':[],'exclude_labels':['trap latino','Latin Music']}
FUNK={'name':'Funk','genres':['Funk'],'languages':[],'artists':[],'exclude_labels':['funk internacional']}

def track(**changes):
    t={'id':'d'*22,'title':'Una Locura','artists':['Ozuna'],'genres':['reggaeton','latin','trap latino'],'languages':['Espanhol'],
       'genre_origin':'artista','source_labels':[{'label':'Latin Music','kind':'album-genre'},{'label':'trap latino','kind':'artist-genre'}],
       'review':None,'routing_required':True}
    t.update(changes);return t

class ExclusionTests(unittest.TestCase):
    def test_excluded_label_beats_criteria(self):
        self.assertFalse(matches_rule(track(genres=['trap','trap latino']),TRAP))
        self.assertTrue(matches_rule(track(genres=['trap'],source_labels=[]),TRAP))
        self.assertEqual(excluded_labels(track(),TRAP),{'trap latino','latin music'})

    def test_lower_origin_labels_and_case_count_but_free_tags_do_not(self):
        t=track(genres=['trap'],source_labels=[{'label':'LATIN MUSIC','kind':'album-genre'}])
        self.assertFalse(matches_rule(t,TRAP))
        t=track(genres=['trap'],source_labels=[{'label':'latin music','kind':'tag'}])
        self.assertTrue(matches_rule(t,TRAP))

    def test_model_yes_blocked_by_exclusion(self):
        t=track()
        rules=[TRAP]
        t['routing']={'key':routing_key(t,rules),'model':'m','decisions':[{'playlist':'Trap - Br','verdict':'yes','reason':''}]}
        self.assertEqual(suggest(t,['Trap - Br'],rules),[])

    def test_funk_internacional_exclusion_uses_source_vocabulary(self):
        us=track(title='Hey Ya!',genres=['funk','hip hop'],genre_origin='faixa',source_labels=[])
        self.assertEqual(excluded_labels(us,FUNK),{'funk internacional'})
        br=track(genres=['Funk'],genre_origin='ia',source_labels=[])
        self.assertTrue(matches_rule(br,FUNK))

    def test_review_uses_your_genres(self):
        t=track(review={'exclude':False,'automatic':True,'genres':['trap'],'languages':['Português'],'playlists':[]})
        self.assertTrue(matches_rule(t,TRAP))

    def test_saved_only_when_used_and_validated(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(Path(d)/'t.sqlite3')
            s.set_rules('a',[{'name':'Trap - Br','genres':['Trap'],'exclude_labels':[' trap latino ','trap latino']},{'name':'Pop','genres':['Pop'],'exclude_labels':[]}])
            rules={r['name']:r for r in s.rules('a')}
            self.assertEqual(rules['Trap - Br']['exclude_labels'],['trap latino'])
            self.assertNotIn('exclude_labels',rules['Pop'])
            with self.assertRaises(ValueError):s.set_rules('a',[{'name':'X','exclude_labels':'trap'}])
            with self.assertRaises(ValueError):s.set_rules('a',[{'name':'X','exclude_labels':['']}])

REGGAETON={'name':'Reggaeton','genres':['Reggaeton'],'languages':['Espanhol'],'artists':[]}

class SourceLabelCriteriaTests(unittest.TestCase):
    """A coarse Deezer album genre replaces the artist's genre, but the artist label still matches criteria."""
    def test_artist_label_matches_under_album_genre(self):
        t=track(title='LA GRACIOSA',genres=['Rap/Hip Hop'],genre_origin='album',
                source_labels=[{'label':'Rap/Hip Hop','kind':'album-genre'},{'label':'reggaeton','kind':'artist-genre'}])
        self.assertTrue(matches_rule(t,REGGAETON))
        self.assertEqual(suggest(t,['Reggaeton'],[REGGAETON]),['Reggaeton'])
    def test_tags_and_review_do_not_count(self):
        tag=track(genres=['Pop'],genre_origin='album',source_labels=[{'label':'reggaeton','kind':'tag'}])
        self.assertFalse(matches_rule(tag,REGGAETON))
        reviewed=track(genres=['Pop'],source_labels=[{'label':'reggaeton','kind':'artist-genre'}],
                       review={'genres':['Pop'],'languages':['Espanhol'],'exclude':False,'automatic':True,'playlists':[]})
        self.assertFalse(matches_rule(reviewed,REGGAETON))
    def test_source_funk_label_is_still_american(self):
        t=track(genres=['Soul & Funk'],genre_origin='album',languages=['Inglês'],
                source_labels=[{'label':'funk','kind':'artist-genre'}])
        self.assertFalse(matches_rule(t,{'name':'Funk','genres':['Funk'],'languages':[],'artists':[]}))

    def test_ambiguous_extra_label_adds_no_category(self):
        rock={'name':'Rock','genres':['Rock'],'languages':[],'artists':[]}
        maluma=track(genres=['Pop'],genre_origin='album',source_labels=[{'label':'pop rock','kind':'artist-genre'}])
        self.assertFalse(matches_rule(maluma,rock))
        band=track(genres=['Pop'],genre_origin='album',source_labels=[{'label':'alternative rock','kind':'artist-genre'}])
        self.assertTrue(matches_rule(band,rock))
        self.assertTrue(matches_rule(track(genres=['pop rock'],genre_origin='faixa',source_labels=[]),rock))

if __name__=='__main__':unittest.main()
