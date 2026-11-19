"""Estado do jogo: perfis das playlists e escolhas de cada música. Nada aqui grava no Spotify.

Perfil de playlist: as suas playlists do Spotify (chave = id do Spotify) e as novas criadas no app
(chave "new:..."), com nome, descrição, idioma e gênero/clima opcionais e se está ativa no jogo.

Escolha de uma música: guardada como diferença em relação ao conteúdo atual no Spotify
({'add': [chaves], 'remove': [chaves]}). Assim uma nova sincronização não apaga o que você
decidiu e o que você não tocou continua como está no Spotify.
"""
import html
import json
import secrets
import time

from core import norm

MAX_ACTIVE = 8
NAME_MAX = 100
DESCRIPTION_MAX = 300
TAG_MAX = 50


def ensure(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS profiles(account TEXT, key TEXT, data TEXT NOT NULL, PRIMARY KEY(account,key));
          CREATE TABLE IF NOT EXISTS decisions(account TEXT, track TEXT, data TEXT NOT NULL, PRIMARY KEY(account,track));
          CREATE TABLE IF NOT EXISTS history(seq INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, track TEXT NOT NULL, before TEXT);''')


# ---------- perfis das playlists ----------

def profiles(store, account):
    ensure(store)
    with store.connect() as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM profiles WHERE account=?', (account,))]
    return sorted(rows, key=lambda p: (p.get('position', 0), norm(p['name'])))


def _save(db, account, profile):
    db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?,?)', (account, profile['key'], json.dumps(profile)))


def sync_profiles(store, account, playlists):
    """Bring profiles in line with your own Spotify playlists. Your edits are kept; a name or
    description you did not edit follows the Spotify. A playlist gone from the Spotify is marked
    missing and leaves the game (its choices stay, but are not written)."""
    current = {p['key']: p for p in profiles(store, account)}
    by_spotify = {p['spotify_id']: p for p in current.values() if p.get('spotify_id')}
    seen = set()
    position = max([p.get('position', 0) for p in current.values()] or [0])
    with store.connect() as db:
        for playlist in playlists:
            key = playlist['id']; seen.add(key)
            name = html.unescape(playlist.get('name') or 'Playlist')[:NAME_MAX]
            description = html.unescape(playlist.get('description') or '')[:DESCRIPTION_MAX]
            p = by_spotify.get(key)
            if p is None:
                position += 1
                p = {'key': key, 'spotify_id': key, 'name': name, 'description': description,
                     'language': '', 'genre': '', 'active': False, 'position': position}
            else:
                if p['name'] == p.get('spotify_name'): p['name'] = name
                if p['description'] == p.get('spotify_description'): p['description'] = description
            p.update(spotify_name=name, spotify_description=description, missing=False,
                     snapshot_id=playlist.get('snapshot_id'))
            _save(db, account, p)
        for key, p in current.items():
            if p.get('spotify_id') and p['spotify_id'] not in seen and not p.get('missing'):
                p.update(missing=True, active=False)
                _save(db, account, p)


def _clean(fields, profile):
    result = {}
    for key, limit in (('name', NAME_MAX), ('description', DESCRIPTION_MAX), ('language', TAG_MAX), ('genre', TAG_MAX)):
        if key not in fields: continue
        value = fields[key]
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(f'Campo "{key}" inválido (máximo {limit} caracteres).')
        result[key] = value.strip()
    if 'name' in result and not result['name']: raise ValueError('A playlist precisa de um nome.')
    if 'active' in fields:
        if not isinstance(fields['active'], bool): raise ValueError('Valor de "ativa" inválido.')
        if fields['active'] and profile.get('missing'): raise ValueError('Esta playlist não existe mais no Spotify.')
        result['active'] = fields['active']
    return result


def _check(all_profiles):
    names = [norm(p['name']) for p in all_profiles if not p.get('missing')]
    if len(set(names)) != len(names): raise ValueError('Já existe uma playlist com esse nome.')
    if sum(1 for p in all_profiles if p.get('active')) > MAX_ACTIVE:
        raise ValueError(f'Escolha no máximo {MAX_ACTIVE} playlists ativas no jogo.')


def update_profile(store, account, key, fields):
    rows = {p['key']: p for p in profiles(store, account)}
    if key not in rows: raise ValueError('Playlist não encontrada.')
    rows[key].update(_clean(fields, rows[key]))
    _check(rows.values())
    with store.connect() as db: _save(db, account, rows[key])
    return rows[key]


def create_profile(store, account, fields):
    rows = profiles(store, account)
    p = {'key': 'new:' + secrets.token_hex(8), 'spotify_id': None, 'name': '', 'description': '',
         'language': '', 'genre': '', 'active': len([r for r in rows if r.get('active')]) < MAX_ACTIVE,
         'position': max([r.get('position', 0) for r in rows] or [0]) + 1, 'missing': False}
    p.update(_clean(fields, p))
    if not p['name']: raise ValueError('A playlist precisa de um nome.')
    _check(rows + [p])
    with store.connect() as db: _save(db, account, p)
    return p


def delete_profile(store, account, key):
    """Only playlists created in the app (not yet on the Spotify) can be deleted. Choices that
    added music to it are dropped too."""
    row = next((p for p in profiles(store, account) if p['key'] == key), None)
    if not row or row.get('spotify_id'): raise ValueError('Só playlists novas, ainda não gravadas, podem ser apagadas.')
    with store.connect() as db:
        db.execute('DELETE FROM profiles WHERE account=? AND key=?', (account, key))
        for track, data in db.execute('SELECT track,data FROM decisions WHERE account=?', (account,)).fetchall():
            d = json.loads(data)
            if key in d['add'] or key in d['remove']:
                d['add'] = [k for k in d['add'] if k != key]; d['remove'] = [k for k in d['remove'] if k != key]
                db.execute('UPDATE decisions SET data=? WHERE account=? AND track=?', (json.dumps(d), account, track))


# ---------- escolhas das músicas ----------

def membership(store, account):
    """Track ids currently in each playlist profile (by profile key), from the last sync."""
    lists = {pl['id']: {t['id'] for t in pl.get('tracks', []) if t.get('id')} for pl in store.spotify_library(account).get('playlists', [])}
    return {p['key']: lists.get(p['spotify_id'], set()) for p in profiles(store, account) if p.get('spotify_id')}


def apply_published(store, account, key, spotify_id, name, description, added, removed):
    """After a successful write: the local copy follows the Spotify and the applied choices are
    cleared (the tracks stay decided)."""
    rows = {p['key']: p for p in profiles(store, account)}
    p = rows[key]
    p.update(spotify_id=spotify_id, name=name, description=description, spotify_name=name, spotify_description=description, missing=False)
    library = store.spotify_library(account)
    entry = next((pl for pl in library.get('playlists', []) if pl['id'] == spotify_id), None)
    if entry is None:
        entry = {'id': spotify_id, 'name': name, 'description': description, 'owned': True, 'tracks': [], 'unavailable': False}
        library.setdefault('playlists', []).append(entry)
    gone = set(removed)
    entry['tracks'] = [t for t in entry['tracks'] if t.get('id') not in gone]
    have = {t.get('id') for t in entry['tracks']}
    entry['tracks'] += [{'id': t, 'uri': 'spotify:track:' + t} for t in added if t not in have]
    entry.update(name=name, description=description)
    store.save_spotify_library(account, library)
    with store.connect() as db:
        _save(db, account, p)
        for track, data in db.execute('SELECT track,data FROM decisions WHERE account=?', (account,)).fetchall():
            d = json.loads(data)
            if key in d['add'] or key in d['remove']:
                d['add'] = [k for k in d['add'] if k != key]; d['remove'] = [k for k in d['remove'] if k != key]
                db.execute('UPDATE decisions SET data=? WHERE account=? AND track=?', (json.dumps(d), account, track))


def decisions(store, account):
    ensure(store)
    with store.connect() as db:
        return {track: json.loads(data) for track, data in db.execute('SELECT track,data FROM decisions WHERE account=?', (account,))}


def marks(track, decision, current, keys):
    """Playlists (among keys) where the track will be after the game."""
    decision = decision or {'add': [], 'remove': []}
    return [k for k in keys if (track in current.get(k, set()) or k in decision['add']) and k not in decision['remove']]


def _write(db, account, track, before, after):
    db.execute('INSERT INTO history(account,track,before) VALUES (?,?,?)', (account, track, json.dumps(before) if before else None))
    if after is None: db.execute('DELETE FROM decisions WHERE account=? AND track=?', (account, track))
    else: db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?)', (account, track, json.dumps(after)))


def _track(store, account, track):
    if not any(t['id'] == track and t['active'] for t in store.tracks(account)):
        raise ValueError('Música não encontrada nesta conta.')


def decide(store, account, track, chosen):
    """Save where the track goes among the active playlists. Playlists outside the game keep
    whatever was decided before."""
    _track(store, account, track)
    active = [p['key'] for p in profiles(store, account) if p.get('active')]
    if not isinstance(chosen, list) or any(k not in active for k in chosen):
        raise ValueError('Escolha só playlists ativas no jogo.')
    current = membership(store, account)
    before = decisions(store, account).get(track)
    kept = before or {'add': [], 'remove': []}
    after = {'add': [k for k in kept['add'] if k not in active] + [k for k in active if k in chosen and track not in current.get(k, set())],
             'remove': [k for k in kept['remove'] if k not in active] + [k for k in active if k not in chosen and track in current.get(k, set())],
             'skipped': False, 'at': time.time()}
    with store.connect() as db: _write(db, account, track, before, after)
    return after


def skip(store, account, track):
    _track(store, account, track)
    before = decisions(store, account).get(track)
    after = dict(before or {'add': [], 'remove': []}, skipped=True, at=time.time())
    with store.connect() as db: _write(db, account, track, before, after)
    return after


def undo(store, account):
    """Undo the last move. Returns (track id, the choice that was undone) so the card can show
    that choice again for you to adjust, or (None, None)."""
    ensure(store)
    with store.connect() as db:
        row = db.execute('SELECT seq,track,before FROM history WHERE account=? ORDER BY seq DESC LIMIT 1', (account,)).fetchone()
        if not row: return None, None
        seq, track, before = row
        undone = db.execute('SELECT data FROM decisions WHERE account=? AND track=?', (account, track)).fetchone()
        if before is None: db.execute('DELETE FROM decisions WHERE account=? AND track=?', (account, track))
        else: db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?)', (account, track, before))
        db.execute('DELETE FROM history WHERE seq=?', (seq,))
    return track, json.loads(undone[0]) if undone else None


def queue(store, account):
    """Ids of the tracks still to sort, in play order: first those already with genre or language,
    grouped by language, genre and artist (similar cards in a row); then those still without data;
    skipped tracks go last."""
    done = decisions(store, account)
    pending = [t for t in store.tracks(account, active=True) if t.get('playable', True)
               and (t['id'] not in done or done[t['id']].get('skipped'))]
    def key(t):
        meta = t.get('review') or t
        language = norm((meta.get('languages') or [''])[0])
        genre = norm((meta.get('genres') or [''])[0])
        return (bool(done.get(t['id'], {}).get('skipped')), not (language or genre),
                language or '~', genre or '~', norm((t.get('artists') or [''])[0]), norm(t.get('title', '')))
    return [t['id'] for t in sorted(pending, key=key)]


def progress(store, account):
    tracks = [t for t in store.tracks(account, active=True) if t.get('playable', True)]
    done = decisions(store, account)
    decided = sum(1 for t in tracks if t['id'] in done and not done[t['id']].get('skipped'))
    return {'total': len(tracks), 'decided': decided,
            'skipped': sum(1 for t in tracks if done.get(t['id'], {}).get('skipped'))}


def overview(store, account):
    """Profiles with how many tracks each one has now and will have after the game, plus the
    genres and languages seen in the library (suggestions for the profile fields)."""
    current = membership(store, account)
    done = decisions(store, account)
    tracks = store.tracks(account, active=True)
    active_ids = {t['id'] for t in tracks}
    rows = []
    for p in profiles(store, account):
        key = p['key']
        now = current.get(key, set()) & active_ids
        after = {t for t in active_ids if key in marks(t, done.get(t), current, [key])} if not p.get('missing') else now
        rows.append(dict(p, count=len(now), count_after=len(after)))
    genres, languages = {}, {}
    for t in tracks:
        meta = t.get('review') or t
        for g in meta.get('genres') or []: genres[g] = genres.get(g, 0) + 1
        for l in meta.get('languages') or []: languages[l] = languages.get(l, 0) + 1
    top = lambda counts, n: [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], norm(kv[0])))[:n]]
    return {'profiles': rows, 'max_active': MAX_ACTIVE, 'genres': top(genres, 40), 'languages': top(languages, 20),
            'progress': progress(store, account)}


# ---------- cartão do jogo ----------

def suggested(track, profile):
    """True when the playlist's language or genre/mood matches the track. Only a highlight for you;
    it never decides anything. "Misto" and empty fields never match."""
    from core import all_genre_labels
    meta = track.get('review') or track
    language = norm(profile.get('language') or '')
    if language and language != 'misto' and language in {norm(x) for x in meta.get('languages') or []}: return True
    genre = norm(profile.get('genre') or '')
    if genre:
        labels = all_genre_labels(track)
        if any(genre == l or (len(genre) >= 3 and genre in l) for l in labels): return True
    return False


def card(store, account, track_id=None, preset=None):
    """The card to show: the given track, or the first one in the queue. None when nothing is left."""
    rows = {t['id']: t for t in store.tracks(account, active=True)}
    if track_id is None:
        order = queue(store, account)
        track_id = order[0] if order else None
        remaining = len(order)
    else:
        remaining = len(queue(store, account))
    if track_id not in rows: return {'track': None, 'progress': progress(store, account), 'remaining': remaining}
    t = rows[track_id]
    active = [p for p in profiles(store, account) if p.get('active')]
    current = membership(store, account)
    decision = decisions(store, account).get(track_id)
    keys = [p['key'] for p in active]
    meta = t.get('review') or t
    from core import infer_origin
    info = {k: t.get(k) for k in ('id', 'title', 'artists', 'album', 'year', 'cover', 'explicit', 'duration_ms', 'bpm', 'liked', 'added_at', 'url')}
    info.update(genres=meta.get('genres') or [], languages=meta.get('languages') or [],
                genre_origin='manual' if t.get('review') else infer_origin(t, 'genre'),
                language_origin='manual' if t.get('review') else infer_origin(t, 'language'),
                pending=not t.get('quick_checked') and not t.get('review'),
                labels=list(dict.fromkeys(l['label'] for l in t.get('source_labels') or [] if l.get('kind') in ('genre', 'album-genre', 'artist-genre')))[:8])
    shown = preset if preset and not preset.get('skipped') else decision
    return {'track': info, 'marks': marks(track_id, shown, current, keys),
            'in_spotify': [k for k in keys if track_id in current.get(k, set())],
            'suggested': [p['key'] for p in active if suggested(t, p)],
            'decided': bool(decision) and not decision.get('skipped'),
            'progress': progress(store, account), 'remaining': remaining}
