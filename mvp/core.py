"""Dados de cada conta (músicas, cópia das playlists) e origem das informações. Nada aqui grava no Spotify."""
import json
from contextlib import contextmanager
import re
import sqlite3
import unicodedata
from pathlib import Path

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

# Information collected about a track; a new import keeps it.
KEEP_ON_IMPORT = ['review', 'genres', 'languages', 'sources', 'source_labels', 'genre_origin', 'language_origin',
                  'artist_genres', 'classification_source', 'quick_checked', 'deezer_id', 'bpm', 'lookup', 'lookup_note']


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            # Old databases may still have the accounts/targets/rules tables of the first version; unused now.
            db.executescript('''CREATE TABLE IF NOT EXISTS tracks(account TEXT, id TEXT, data TEXT NOT NULL, PRIMARY KEY(account,id));
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
                for key in KEEP_ON_IMPORT:
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
