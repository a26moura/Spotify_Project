"""Rules and durable, account-scoped state. No Spotify writes in this module."""
import json
from contextlib import contextmanager
import re
import sqlite3
import unicodedata
from pathlib import Path

DEFAULT_PLAYLISTS = ['POP', 'Sertanejo', 'Reggaeton', 'Espanhol', 'Frances', 'Trap', 'Rock', 'Funk']

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
    if 'rock' in n or 'punk' in n: result.append('Rock')
    if 'pop' in n: result.append('Pop')
    return result or [label]

def suggest(track, names):
    review = track.get('review')
    if review is not None:
        return [] if review['exclude'] else [n for n in review['playlists'] if n in names]
    lookup = {norm(n): n for n in names}
    return list(dict.fromkeys(lookup[norm(x)] for x in track.get('genres', []) + track.get('languages', []) if norm(x) in lookup))

def record(raw):
    ident = raw.get('id') or track_id(raw.get('url', ''))
    if not ident or not re.fullmatch(r'[A-Za-z0-9]{22}', ident): return None
    artists = [a['name'] if isinstance(a, dict) else a for a in raw.get('artists', [])]
    return {'id': ident, 'title': raw.get('name') or raw.get('title', ''), 'artists': artists,
            'uri': 'spotify:track:' + ident, 'url': 'https://open.spotify.com/track/' + ident,
            'isrc': raw.get('external_ids', {}).get('isrc'), 'genres': [], 'languages': [],
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
              CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, data TEXT NOT NULL, expires REAL NOT NULL);''')

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
            db.execute('INSERT OR IGNORE INTO accounts VALUES (?,?)', (account, json.dumps(DEFAULT_PLAYLISTS)))
            return json.loads(db.execute('SELECT names FROM accounts WHERE id=?', (account,)).fetchone()[0])

    def set_names(self, account, names):
        if not isinstance(names, list) or not 1 <= len(names) <= 30 or any(not isinstance(n,str) or not n.strip() or len(n)>80 for n in names):
            raise ValueError('Escolha entre 1 e 30 nomes de playlists, com até 80 caracteres.')
        names = [n.strip() for n in names]
        if len({norm(n) for n in names}) != len(names): raise ValueError('Os nomes não podem se repetir.')
        removed = set(self.names(account)) - set(names)
        if any(removed.intersection((t.get('review') or {}).get('playlists', [])) for t in self.tracks(account)):
            raise ValueError('Há revisões usando uma playlist removida. Ajuste essas músicas primeiro.')
        with self.connect() as db:
            db.execute('UPDATE accounts SET names=? WHERE id=?', (json.dumps(names), account))

    def tracks(self, account, active=False):
        with self.connect() as db:
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM tracks WHERE account=? ORDER BY rowid', (account,))]
        return [r for r in rows if r['active']] if active else rows

    def put(self, account, item):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO tracks VALUES (?,?,?)', (account, item['id'], json.dumps(item)))

    def import_tracks(self, account, items):
        old = {t['id']: t for t in self.tracks(account)}
        found = {}
        for item in items:
            t = record(item)
            if not t: continue
            if t['id'] in old:
                previous = old[t['id']]
                for key in ['review', 'genres', 'languages', 'sources', 'lookup', 'lookup_note']:
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
        t['review']['playlists'] = list(dict.fromkeys(destinations))
        self.put(account,t)

    def targets(self, account):
        with self.connect() as db: return dict(db.execute('SELECT name,playlist FROM targets WHERE account=?',(account,)))

    def target(self, account, name, ident):
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO targets VALUES (?,?,?)',(account,name,ident))

    def seed(self, account, directory, full=False, apply_review=True):
        directory = Path(directory)
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

def desired_sets(tracks, names):
    result = {n: set() for n in names}
    for t in tracks:
        if not t['active'] or not t.get('playable',True): continue
        for name in suggest(t,names): result[name].add(t['uri'])
    return result
