"""Deezer (album genre) and LRCLIB (lyrics language) in Enricher.quick, tested offline."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from providers import Enricher, RemoteError
import lyrics_language

TRACK={'id':'a'*22,'title':'Envolver','artists':['Anitta'],'genres':[],'languages':[],'duration_ms':193000,'isrc':'BR1234567890'}
PT=('Eu não sei o que fazer sem você aqui comigo, meu coração está sempre pensando em você, '
    'quero voltar pra casa e ficar com você agora, não quero mais saber de nada, só você me faz bem, vem comigo')
ES=('Yo no sé qué hacer sin ti, mi corazón está siempre contigo, quiero que vuelvas conmigo esta noche, '
    'dime que me quieres, baila conmigo mami, dale que la vida es así y no hay nadie como tú')

class Fake(Enricher):
    """Deezer/LRCLIB answer from `web` by URL prefix."""
    def __init__(self,store,web):
        super().__init__(store);self.web=web;self.urls=[]
    def get(self,url,cache=True):
        self.urls.append(url)
        for prefix,answer in self.web.items():
            if url.startswith(prefix):
                if isinstance(answer,Exception):raise answer
                return answer
        raise AssertionError('unexpected '+url)

DEEZER_TRACK={'id':1,'artist':{'name':'Anitta'},'contributors':[{'name':'Anitta'}],'album':{'id':77,'title':'Versions of Me'}}
LYRICS={'id':5,'trackName':'Envolver','artistName':'Anitta','instrumental':False,'plainLyrics':ES,'syncedLyrics':None}

class ComplementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'t.sqlite3')
    def tearDown(self):self.tmp.cleanup()

    def web(self,**changes):
        web={'https://api.deezer.com/track/isrc:':DEEZER_TRACK,
             'https://api.deezer.com/album/77':{'title':'Versions of Me','genres':{'data':[{'name':'Pop','picture':'x'},{'name':'Latin Music'}]}},
             'https://lrclib.net/api/get':LYRICS}
        web.update(changes);return web

    def test_album_genre_and_lyrics_language(self):
        e=Fake(self.store,self.web());result=e.quick(dict(TRACK))
        self.assertEqual((result['genres'],result['genre_origin']),(['Pop'],'album'))
        self.assertEqual((result['languages'],result['language_origin']),(['Espanhol'],'letra'))
        self.assertTrue(result['quick_checked'])
        labels=[(l['label'],l['kind']) for l in result['source_labels']]
        self.assertIn(('Latin Music','album-genre'),labels)
        self.assertIn('duration=193',[u for u in e.urls if 'lrclib' in u][0])

    def test_results_are_cached_without_raw_text(self):
        e=Fake(self.store,self.web());e.quick(dict(TRACK));calls=len(e.urls)
        e.quick(dict(TRACK));self.assertEqual(len(e.urls),calls)
        with self.store.connect() as db:
            stored=' '.join(r[0] for r in db.execute('SELECT data FROM cache'))
        self.assertNotIn('corazón',stored);self.assertNotIn('picture',stored)

    def test_artist_mismatch_and_generic_genres_are_not_used(self):
        other=dict(DEEZER_TRACK,artist={'name':'Cover Band'},contributors=[])
        result=Fake(self.store,self.web(**{'https://api.deezer.com/track/isrc:':other})).quick(dict(TRACK))
        self.assertNotIn('genres',result)
        # A generic album genre only fills an empty genre; it never replaces a known one.
        generic={'title':'X','genres':{'data':[{'name':'Latin Music'}]}}
        result=Fake(self.store,self.web(**{'https://api.deezer.com/album/77':generic})).quick(dict(TRACK,isrc='BR0000000001'))
        self.assertEqual((result['genres'],result['genre_origin']),(['Latin Music'],'album'))
        result=Fake(self.store,self.web(**{'https://api.deezer.com/album/77':generic})).quick(dict(TRACK,isrc='BR0000000002',genres=['pop'],genre_origin='artista'))
        self.assertNotIn('genres',result)
        self.assertIn(('Latin Music','album-genre'),[(l['label'],l['kind']) for l in result['source_labels']])

    def test_not_found_and_instrumental(self):
        missing={'https://api.deezer.com/track/isrc:':{'error':{'code':800,'message':'no data'}},
                 'https://lrclib.net/api/get':RemoteError('LRCLIB respondeu HTTP 404.',status=404)}
        result=Fake(self.store,self.web(**missing)).quick(dict(TRACK))
        self.assertNotIn('genres',result);self.assertNotIn('languages',result);self.assertTrue(result['quick_checked'])
        instrumental=dict(LYRICS,instrumental=True,plainLyrics=None)
        result=Fake(self.store,self.web(**{'https://lrclib.net/api/get':instrumental})).quick(dict(TRACK,duration_ms=200000,isrc=None))
        self.assertEqual((result['languages'],result['language_origin']),(['Instrumental'],'letra'))

    def test_lyrics_for_other_song_ignored(self):
        wrong=dict(LYRICS,trackName='Outra Música')
        result=Fake(self.store,self.web(**{'https://lrclib.net/api/get':wrong})).quick(dict(TRACK))
        self.assertNotIn('languages',result)

    def test_temporary_failure_keeps_track_retryable_and_is_not_cached(self):
        busy={'https://api.deezer.com/track/isrc:':{'error':{'code':4,'message':'Quota limit exceeded'}},
              'https://lrclib.net/api/get':RemoteError('LRCLIB 503',status=503,transient=True)}
        e=Fake(self.store,self.web(**busy));result=e.quick(dict(TRACK))
        self.assertNotIn('quick_checked',result)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM cache').fetchone()[0],0)

    def test_track_evidence_is_not_replaced(self):
        e=Fake(self.store,self.web())
        result=e.quick(dict(TRACK,genres=['funk carioca'],genre_origin='faixa',languages=['Português'],language_origin='faixa'))
        self.assertFalse(any('lrclib' in u for u in e.urls));self.assertNotIn('genre_origin',result);self.assertNotIn('genres',result)

class DetectTests(unittest.TestCase):
    def test_languages(self):
        self.assertEqual(lyrics_language.detect(PT),['Português'])
        self.assertEqual(lyrics_language.detect(ES),['Espanhol'])
        self.assertEqual(lyrics_language.detect('I just want you to know that I need you baby, every night I feel your love and I can never let it go, oh yeah tell me what you want and I will be there for you all the time'),['Inglês'])
        self.assertEqual(lyrics_language.detect('Je ne sais pas pourquoi tu es toujours dans mon coeur, je veux être avec toi, mais tu ne comprends rien, c est la vie, on fait comme on peut, toujours encore sans toi je suis rien'),['Francês'])
    def test_mixed_short_and_scripts(self):
        mixed=('Baby I want you tonight, yo quiero estar contigo, dime que me quieres baby, I need you, dale mami que la noche es larga, '
               'I feel your love, baila conmigo, oh yeah, eres mi vida, you know I want you to stay')
        self.assertEqual(lyrics_language.detect(mixed),['Inglês','Espanhol'])
        self.assertEqual(lyrics_language.detect('amor amor amor'),[])
        self.assertEqual(lyrics_language.detect('君のことが好きだよ ずっと一緒にいたい'),['Japonês'])
        self.assertEqual(lyrics_language.detect('사랑해 너를 정말 사랑해'),['Coreano'])
        self.assertEqual(lyrics_language.detect(''),[])
    def test_distinctive_words_only(self):
        langs=list(lyrics_language.WORDS)
        for i,a in enumerate(langs):
            for b in langs[i+1:]:self.assertFalse(lyrics_language.WORDS[a]&lyrics_language.WORDS[b])
    def test_synced_lyrics(self):
        self.assertEqual(lyrics_language.strip_timestamps('[00:01.00] oi\n[00:02.50] tchau').split(),['oi','tchau'])

if __name__=='__main__':unittest.main()
