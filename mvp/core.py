"""Rules and durable, account-scoped state. No Spotify writes in this module."""
import json
import hashlib
from contextlib import contextmanager
import re
import sqlite3
import unicodedata
from pathlib import Path

DEFAULT_PLAYLISTS = ['POP', 'Sertanejo', 'Reggaeton', 'Espanhol', 'Frances', 'Trap', 'Rock', 'Funk']
EXTRA_RULES = [{'name':n,'genres':[n],'languages':[],'artists':[]} for n in ['Eletrônica','Hip-Hop/Rap','Metal']]

def norm(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c)).strip()

def track_id(value):
    match = re.search(r'(?:track/|spotify:track:)([A-Za-z0-9]{22})(?:[/?#]|$)', value or '')
    return match.group(1) if match else None

def broad(label):
    n = norm(label)
    for terms, name in [(['reggaeton', 'regueton'], 'Reggaeton'), (['sertanej'], 'Sertanejo'),
                        (['baile funk', 'funk carioca', 'funk brasileiro', 'brazilian funk'], 'Funk'),
                        (['trap'], 'Trap')]:
        if any(x in n for x in terms): return [name]
    result = []
    if any(x in n for x in ['electronic', 'eletron', 'electro ', 'house', 'techno', 'dubstep', 'drum and bass', 'trance', 'edm']) or n == 'electro': result.append('Eletrônica')
    if any(x in n for x in ['hip hop', 'hip-hop', 'hiphop']) or n in {'rap', 'gangsta rap', 'southern rap', 'dirty south', 'hip-hop/rap'}: result.append('Hip-Hop/Rap')
    if 'metal' in n: result.append('Metal')
    if 'rock' in n or 'punk' in n: result.append('Rock')
    if 'pop' in n: result.append('Pop')
    return result or [label]

def default_rule(name):
    language = norm(name) in {'espanhol', 'frances', 'ingles', 'portugues', 'japones', 'coreano'}
    return {'name': name, 'genres': [] if language else [name],
            'languages': [name] if language else [], 'artists': []}


LABEL_KINDS = ('genre', 'album-genre', 'artist-genre')

def genre_labels(track, values, from_sources, unambiguous=False):
    """Normalized genre labels plus their broad categories. A bare "funk" from MusicBrainz/Deezer/
    Wikidata is American funk; only your review or the AI (whose list separates Funk from
    Funk Internacional) use "Funk" for Brazilian funk. With unambiguous=True a label only adds its
    broad category when there is exactly one ("pop rock" is both Rock and Pop, so it adds neither)."""
    american = from_sources and infer_origin(track, 'genre') != 'ia'
    values = ['Funk Internacional' if american and norm(x) == 'funk' else x for x in values]
    result = {norm(x) for x in values}
    for value in values:
        categories = broad(value)
        if not unambiguous or len(categories) == 1: result |= {norm(label) for label in categories}
    return result


def excluded_labels(track, rule):
    """Labels of the track listed in the playlist's "rótulos que não contam"."""
    unwanted = {norm(x) for x in rule.get('exclude_labels', [])}
    if not unwanted: return set()
    return unwanted & all_genre_labels(track)


def all_genre_labels(track):
    """Genres of the track plus the genre labels of every source (track, album and artist), even
    weaker ones. Deezer album genres are coarse ("Rap/Hip Hop", "Pop") and replace the artist's
    "reggaeton" or "trap" as the main genre, but the artist label is still evidence for criteria.
    Free MusicBrainz tags do not count. With a manual review, only your genres count."""
    review = track.get('review')
    if review:
        return genre_labels(track, review.get('genres', []), False)
    extra = [l['label'] for l in track.get('source_labels', []) or [] if l.get('kind') in LABEL_KINDS and l.get('label')]
    return genre_labels(track, track.get('genres', []), True) | genre_labels(track, extra, True, unambiguous=True)


def matches_rule(track, rule):
    # OR within each field, AND between fields. Empty rules never match everything.
    # An excluded label always wins over the inclusion criteria.
    if excluded_labels(track, rule): return False
    metadata = track.get('review') or track
    criteria = []
    for key in ('genres', 'languages', 'artists'):
        wanted = {norm(x) for x in rule.get(key, [])}
        if not wanted:
            continue
        values = track.get(key, []) if key == 'artists' else metadata.get(key, [])
        actual = all_genre_labels(track) if key == 'genres' else {norm(x) for x in values}
        criteria.append(bool(wanted & actual))
    return bool(criteria) and all(criteria)


# Ranks are compared within one field. Genre: faixa > album > artista > ia. Language: faixa > letra > ia.
ORIGIN_RANK = {'faixa': 4, 'album': 3, 'letra': 3, 'artista': 2, 'ia': 1}

def infer_origin(track, field):
    """Where a track's genres/languages came from: faixa, album, letra, artista, ia or None (empty)."""
    key = 'genres' if field == 'genre' else 'languages'
    if not track.get(key): return None
    if track.get(field + '_origin') in ORIGIN_RANK: return track[field + '_origin']
    if str(track.get('classification_source') or '').startswith('Ollama'): return 'ia'
    if field == 'genre' and track.get('artist_genres'): return 'artista'
    return 'faixa'


def needs_artist_labels(track):
    """True when the artist's genres were not yet collected as extra labels (since 19/11/2026)."""
    return not track.get('artist_labels') and not track.get('review')


def needs_complements(track):
    """True when Deezer/LRCLIB were not yet tried and could still improve genre or language."""
    if track.get('complements_checked') or track.get('review'): return False
    return (ORIGIN_RANK.get(infer_origin(track, 'genre'), 0) < ORIGIN_RANK['album'] or
            ORIGIN_RANK.get(infer_origin(track, 'language'), 0) < ORIGIN_RANK['letra'])


# Bump when the routing prompt or evidence rules change, so old model decisions are redone.
ROUTING_VERSION = 2

def routing_key(track, rules):
    data={k:track.get(k,[]) for k in ('title','artists','genres','languages','source_labels')}
    return hashlib.sha256(json.dumps([ROUTING_VERSION,data,rules],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def has_evidence(track):
    """The model may only route tracks that already have a genre or language from some source."""
    return bool(track.get('genres') or track.get('languages'))


def needs_routing(track, rules, model):
    if track.get('review') or not has_evidence(track): return False
    routing = track.get('routing') or {}
    return routing.get('key') != routing_key(track, rules) or routing.get('model') != model or bool(routing.get('redo'))


def reset_routing(track, name):
    """Forget the model's decision for one playlist, locally. Manual reviews are never touched.
    Returns True when the track changed; it is re-evaluated for that playlist on the next distribution."""
    routing = track.get('routing')
    if track.get('review') or not routing or not any(d['playlist']==name for d in routing.get('decisions',[])): return False
    routing['decisions'] = [d for d in routing['decisions'] if d['playlist']!=name]
    routing['redo'] = sorted(set(routing.get('redo',[]))|{name})
    return True


def merge_routing(track, rules, previous, partial):
    """Combine a partial re-evaluation (only the playlists in redo) with the decisions kept from before."""
    redo = set(previous.get('redo',[]))
    kept = [d for d in previous.get('decisions',[]) if d['playlist'] not in redo]
    return {'key':routing_key(track,rules),'model':partial['model'],'decisions':kept+partial['decisions']}


def model_may_say_yes(track, rule):
    """A 'yes' from the model counts only when the track has data for the playlist's explicit criteria:
    a genre criterion needs a genre, a language criterion needs a language. Names are never evidence."""
    if not has_evidence(track) or excluded_labels(track, rule): return False
    if rule.get('genres') and not track.get('genres'): return False
    if rule.get('languages') and not track.get('languages'): return False
    return True

def suggest(track, names, rules=None):
    review = track.get('review')
    if review is not None:
        if review['exclude']:
            return []
        if not review.get('automatic', False):
            return [n for n in review['playlists'] if n in names]
    rules = rules if rules is not None else [default_rule(n) for n in names]
    matched = [r['name'] for r in rules if r['name'] in names and matches_rule(track, r)]
    if review is None and track.get('routing_required'):
        # Your explicit criteria always count; the model can add playlists, gated by evidence.
        routing=track.get('routing') or {}
        if routing.get('key')!=routing_key(track,rules):return matched
        by_name={r['name']:r for r in rules}
        yes={d['playlist'] for d in routing.get('decisions',[]) if d['verdict']=='yes' and d['playlist'] in by_name and model_may_say_yes(track,by_name[d['playlist']])}
        return [n for n in names if n in yes or n in matched]
    return matched

def cover_url(album):
    """Smallest album image that is at least 300 px wide (good for the card), else the largest one."""
    images = [i for i in (album or {}).get('images') or [] if isinstance(i, dict) and i.get('url')]
    if not images: return None
    wide = [i for i in images if (i.get('width') or 0) >= 300]
    pick = min(wide, key=lambda i: i['width']) if wide else max(images, key=lambda i: i.get('width') or 0)
    return pick['url']

def record(raw, liked=True):
    ident = raw.get('id') or track_id(raw.get('url', ''))
    if not ident or not re.fullmatch(r'[A-Za-z0-9]{22}', ident): return None
    artists = [a['name'] if isinstance(a, dict) else a for a in raw.get('artists', [])]
    album = raw.get('album') if isinstance(raw.get('album'), dict) else {}
    year = (album.get('release_date') or '')[:4]
    return {'id': ident, 'title': raw.get('name') or raw.get('title', ''), 'artists': artists,
            'uri': 'spotify:track:' + ident, 'url': 'https://open.spotify.com/track/' + ident,
            'isrc': (raw.get('external_ids') or {}).get('isrc'), 'genres': [], 'languages': [],
            'duration_ms': raw.get('duration_ms'),
            'album': album.get('name') or '', 'year': int(year) if year.isdigit() else None,
            'cover': cover_url(album), 'explicit': bool(raw.get('explicit')),
            'liked': liked, 'added_at': raw.get('added_at') if liked else None,
            'sources': [], 'lookup': 'pending', 'review': None, 'active': True,
            'playable': raw.get('is_playable', True) and not raw.get('is_local', False)}

class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, names TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS tracks(account TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(account,id));
              CREATE TABLE IF NOT EXISTS targets(account TEXT,name TEXT,playlist TEXT NOT NULL,PRIMARY KEY(account,name));
              CREATE TABLE IF NOT EXISTS rules(account TEXT PRIMARY KEY, data TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS spotify_library(account TEXT PRIMARY KEY, data TEXT NOT NULL);''')

    def spotify_library(self, account):
        with self.connect() as db:
            row=db.execute('SELECT data FROM spotify_library WHERE account=?',(account,)).fetchone()
        return json.loads(row[0]) if row else {'playlists':[], 'synced_at':None}

    def save_spotify_library(self, account, snapshot):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO spotify_library VALUES (?,?)',(account,json.dumps(snapshot)))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def names(self, account):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO accounts VALUES (?,?)', (account, '[]'))
            return json.loads(db.execute('SELECT names FROM accounts WHERE id=?', (account,)).fetchone()[0])

    def set_names(self, account, names):
        if not isinstance(names, list) or not 0 <= len(names) <= 30 or any(not isinstance(n,str) or not n.strip() or len(n)>80 for n in names):
            raise ValueError('Escolha até 30 nomes de playlists, com até 80 caracteres.')
        names = [n.strip() for n in names]
        if len({norm(n) for n in names}) != len(names): raise ValueError('Os nomes não podem se repetir.')
        removed = set(self.names(account)) - set(names)
        if any(removed.intersection((t.get('review') or {}).get('playlists', [])) for t in self.tracks(account)):
            raise ValueError('Há revisões usando uma playlist removida. Ajuste essas músicas primeiro.')
        with self.connect() as db:
            db.execute('UPDATE accounts SET names=? WHERE id=?', (json.dumps(names), account))

    def rules(self, account):
        names = self.names(account)
        with self.connect() as db:
            row = db.execute('SELECT data FROM rules WHERE account=?', (account,)).fetchone()
        saved = {r['name']: r for r in json.loads(row[0])} if row else {}
        return [saved.get(n, default_rule(n)) for n in names]

    def set_rules(self, account, rules):
        if not isinstance(rules, list) or not 0 <= len(rules) <= 30:
            raise ValueError('Defina até 30 playlists.')
        old_names = self.names(account)
        clean, renames, originals = [], {}, set()
        for rule in rules:
            if not isinstance(rule, dict): raise ValueError('Regra inválida.')
            name = rule.get('name')
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError('Cada playlist precisa de um nome de até 80 caracteres.')
            item = {'name': name.strip()}
            description=rule.get('description','')
            if not isinstance(description,str) or len(description)>1000:raise ValueError('Descrição da playlist inválida (máximo 1000 caracteres).')
            if description.strip():item['description']=description.strip()
            for key in ('genres', 'languages', 'artists'):
                values = rule.get(key, [])
                if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in values):
                    raise ValueError('Critérios inválidos: use até 30 valores por campo.')
                item[key] = list(dict.fromkeys(v.strip() for v in values))
            exclude = rule.get('exclude_labels', [])
            if not isinstance(exclude, list) or len(exclude) > 30 or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in exclude):
                raise ValueError('Rótulos que não contam inválidos: use até 30 valores.')
            # Stored only when used, so existing rules keep the same routing key.
            if exclude: item['exclude_labels'] = list(dict.fromkeys(v.strip() for v in exclude))
            original = rule.get('previous_name', item['name'] if item['name'] in old_names else None)
            if original is not None:
                if not isinstance(original, str) or original not in old_names or original in originals:
                    raise ValueError('Origem da playlist inválida ou repetida.')
                originals.add(original)
                renames[original] = item['name']
            clean.append(item)
        names = [r['name'] for r in clean]
        if len({norm(n) for n in names}) != len(names): raise ValueError('Os nomes não podem se repetir.')
        tracks = self.tracks(account)
        removed = set(old_names) - originals
        if any(removed.intersection((t.get('review') or {}).get('playlists', [])) for t in tracks):
            raise ValueError('Há escolhas manuais nesta playlist. Retire esses destinos antes de removê-la.')
        targets = self.targets(account)
        with self.connect() as db:
            db.execute('UPDATE accounts SET names=? WHERE id=?', (json.dumps(names), account))
            db.execute('INSERT OR REPLACE INTO rules VALUES (?,?)', (account, json.dumps(clean)))
            db.execute('DELETE FROM targets WHERE account=?', (account,))
            for old, ident in targets.items():
                if old in renames:
                    db.execute('INSERT INTO targets VALUES (?,?,?)', (account, renames[old], ident))
            for t in tracks:
                if t.get('review'):
                    t['review']['playlists'] = [renames[n] for n in t['review']['playlists'] if n in renames]
                    db.execute('UPDATE tracks SET data=? WHERE account=? AND id=?', (json.dumps(t), account, t['id']))

    def tracks(self, account, active=False):
        with self.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM tracks WHERE account=? ORDER BY rowid', (account,))]
        return [r for r in rows if r['active']] if active else rows

    def put(self, account, item):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO tracks VALUES (?,?,?)', (account, item['id'], json.dumps(item)))

    def import_tracks(self, account, items, playlist_items=()):
        """Liked tracks plus tracks that are only in your own playlists (liked=False).
        Tracks in neither become inactive; their data is kept for a later import."""
        old = {t['id']: t for t in self.tracks(account)}
        found = {}
        liked_ids = {record(i)['id'] for i in items if record(i)}
        extra = [i for i in playlist_items if (r := record(i)) and r['id'] not in liked_ids]
        for item, liked in [(i, True) for i in items] + [(i, False) for i in extra]:
            t = record(item, liked)
            if not t or t['id'] in found: continue
            if t['id'] in old:
                previous = old[t['id']]
                for key in ['review', 'genres', 'languages', 'sources', 'lookup', 'lookup_note', 'artist_genres', 'classification_source', 'classification_level', 'source_labels', 'labels_collected', 'routing_required', 'routing', 'genre_origin', 'language_origin', 'artist_checked', 'ai_checked', 'complements_checked', 'artist_labels']:
                    if key in previous: t[key] = previous[key]
            found[t['id']] = t
        # A full successful import is committed atomically. An API failure never empties the library.
        with self.connect() as db:
            for ident, t in old.items():
                if ident not in found:
                    t['active'] = False
                    db.execute('UPDATE tracks SET data=? WHERE account=? AND id=?', (json.dumps(t),account,ident))
            for t in found.values():
                db.execute('INSERT OR REPLACE INTO tracks VALUES (?,?,?)', (account,t['id'],json.dumps(t)))
        return len(found)

    def review(self, account, ident, data):
        rows = {t['id']: t for t in self.tracks(account)}
        if ident not in rows: raise ValueError('Música não encontrada nesta conta.')
        names = self.names(account)
        destinations = data.get('playlists')
        if not isinstance(destinations,list) or any(n not in names for n in destinations): raise ValueError('Playlist inválida.')
        if not isinstance(data.get('exclude'),bool): raise ValueError('Exclusão inválida.')
        for key in ['genres','languages']:
            if not isinstance(data.get(key),list) or len(data[key])>20 or any(not isinstance(x,str) or len(x)>100 for x in data[key]): raise ValueError('Gênero ou idioma inválido.')
        t = rows[ident]
        t['review'] = {k: data[k] for k in ['playlists','exclude','genres','languages']}
        if not isinstance(data.get('automatic', False), bool): raise ValueError('Modo de organização inválido.')
        t['review']['automatic'] = data.get('automatic', False)
        t['review']['playlists'] = list(dict.fromkeys(destinations))
        self.put(account,t)

    def targets(self, account):
        with self.connect() as db: return dict(db.execute('SELECT name,playlist FROM targets WHERE account=?',(account,)))

    def target(self, account, name, ident):
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO targets VALUES (?,?,?)',(account,name,ident))

    def seed(self, account, directory, full=False, apply_review=True):
        directory = Path(directory)
        if not all((directory / name).is_file() for name in ['revisao-consolidada.json', 'playlists-definidas.json', 'fontes-amostra.json']):
            self.names(account)
            return 0
        if full and not (directory / 'musicas-curtidas.json').is_file():
            raise ValueError('A exportação pessoal não está disponível nesta instalação. Conecte o Spotify para importar suas curtidas.')
        reviews = json.loads((directory/'revisao-consolidada.json').read_text(encoding='utf-8-sig'))['tracks']
        assignments = json.loads((directory/'playlists-definidas.json').read_text(encoding='utf-8-sig'))['sample_assignments']
        proposals = {track_id(t['spotify_url']):t for t in assignments}
        sources = {track_id(t['spotify_url']):t for t in json.loads((directory/'fontes-amostra.json').read_text(encoding='utf-8-sig'))['tracks']}
        self.names(account)
        if account.startswith('demo:'):
            raw = json.loads((directory/'musicas-curtidas.json').read_text(encoding='utf-8-sig'))['tracks'] if full else [dict(t,url=t['spotify_url']) for t in reviews]
            self.import_tracks(account,raw)
        current = {t['id']:t for t in self.tracks(account)}
        count = 0
        for r in reviews:
            ident = track_id(r['spotify_url'])
            if ident not in current or current[ident]['review'] is not None: continue
            t = current[ident]
            src = sources[ident]
            t.update(genres=r['suggested_genres'], languages=r['documented_languages'], lookup='done', sources=[{'url': e['url'], 'label': e['source'], 'level': e['level']} for e in src.get('evidence',[])])
            if apply_review:
                t['review'] = {'genres':r['user_genres'], 'languages':r['user_languages'], 'exclude':r['exclude_from_project_playlists'], 'playlists':proposals[ident]['proposed_playlists']}
                count += 1
            self.put(account,t)
        return count

def desired_sets(tracks, names, rules=None):
    result = {n: set() for n in names}
    for t in tracks:
        if not t['active'] or not t.get('playable',True): continue
        for name in suggest(t,names,rules): result[name].add(t['uri'])
    return result
