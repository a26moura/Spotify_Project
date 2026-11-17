"""Offline language detection for song lyrics, by frequent function words and scripts.

No AI and no network. The lyrics text is only read here; it is never stored.
"""
import re
import unicodedata


def _norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


# Frequent words per language, written without accents. Words that appear in more
# than one list are removed below, so only distinctive words count as evidence.
_RAW = {
    'Português': '''nao voce voces eu meu minha meus minhas estou sao com uma pra para mas tambem muito quando ele ela
        nos vou vai tem isso essa esse aqui agora sempre seu sua dela dele ate entao assim fazer quero vem
        coracao sei sou nada tudo comigo contigo gente ficar fica deixa olha saudade ja onde ninguem jeito
        voltar falar mim teu tua nossa nosso pelo pela num numa dos das ao aos e o os as um bem mesmo''',
    'Espanhol': '''el los las del muy pero eso esto estoy soy eres cuando tambien nada quiero mi mis y con una lo le
        hay ahora siempre corazon contigo conmigo noche mami yo tu te tus nadie donde estas esta quieres
        porque cuerpo vida dime puedo sin hasta mucho otra otro ella ese esa aqui asi algo nunca bien
        hace todo todos baila pa usted ustedes nosotros vamos dale ya''',
    'Inglês': '''the you and to me my is it that your what are be was with for this just know all like when we they
        she he can will not don so oh yeah baby love i in of on at up out get got want need never feel
        one now go girl there time make way do if no way say tell right night only been could would''',
    'Francês': '''je le les des et est pas qui moi toi mon ma ne une dans pour avec sur c ce cette nous vous suis
        tout plus mais j m t l qu au aux du elle il ils on bien fait comme veux etre avoir jamais toujours
        rien coeur amour encore sans parce quand oui ton ta tes mes ses leur''',
    'Italiano': '''il che non sono io ti per della questo questa sei anche ancora perche piu cosa voglio amore cuore
        niente gli lei lui noi voi siamo ho hai ha nel nella con mio mia tuo tua sempre vita adesso
        quando dove come senza tutto tutti cosi poi gia ma e la di un una''',
    'Alemão': '''ich du und der die das nicht ist mein meine dein deine wir sie es ein eine mit auf zu ja nein liebe
        herz bin bist hab habe immer noch nur wenn wie was mir dich mich dir uns euch kein keine auch
        aber oder sein so schon nie heute nacht''',
}
_SETS = {lang: set(words.split()) for lang, words in _RAW.items()}
_COUNTS = {}
for _words in _SETS.values():
    for _w in _words: _COUNTS[_w] = _COUNTS.get(_w, 0) + 1
WORDS = {lang: frozenset(w for w in words if _COUNTS[w] == 1) for lang, words in _SETS.items()}

_SCRIPTS = [
    ('Japonês', re.compile(r'[぀-ヿ]')),
    ('Coreano', re.compile(r'[가-힯ᄀ-ᇿ]')),
    ('Russo', re.compile(r'[Ѐ-ӿ]')),
    ('Árabe', re.compile(r'[؀-ۿ]')),
    ('Hindi', re.compile(r'[ऀ-ॿ]')),
    ('Chinês', re.compile(r'[一-鿿]')),
]

MIN_WORDS = 30      # Too short a text does not give a safe answer.
MIN_HITS = 6        # Minimum distinctive words for a language to count.
MIN_SHARE = 0.5     # The winner must hold at least half of the distinctive hits.
SECOND_RATIO = 0.4  # A second language counts when it has 40% of the winner's hits.


def strip_timestamps(synced):
    return re.sub(r'\[[^\]]*\]', ' ', synced or '')


def detect(text):
    """Return up to two languages, most frequent first, or [] when the evidence is weak."""
    text = text or ''
    letters = [c for c in text if c.isalpha()]
    if not letters: return []
    for lang, pattern in _SCRIPTS:
        # Kana marks Japanese even inside mostly-kanji text; Han alone counts as Chinese.
        share = len(pattern.findall(text)) / len(letters)
        if share >= (0.05 if lang == 'Japonês' else 0.3): return [lang]
    tokens = re.findall(r'[^\W\d_]+', _norm(text))
    if len(tokens) < MIN_WORDS: return []
    hits = {lang: sum(1 for t in tokens if t in words) for lang, words in WORDS.items()}
    ranked = sorted(((n, lang) for lang, n in hits.items() if n), reverse=True)
    if not ranked: return []
    top, lang = ranked[0]
    if top < MIN_HITS or top / sum(n for n, _ in ranked) < MIN_SHARE: return []
    result = [lang]
    if len(ranked) > 1 and ranked[1][0] >= max(MIN_HITS, SECOND_RATIO * top): result.append(ranked[1][1])
    return result
