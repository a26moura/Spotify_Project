"""Prévia final e gravação no Spotify das escolhas do jogo.

Regras: nada é gravado sem uma prévia que você confirmou; a prévia guarda o conteúdo de cada
playlist no momento em que foi feita e a gravação recusa a playlist se ela mudou desde então;
nenhuma gravação é repetida automaticamente (após uma falha, prepare nova prévia).
"""
import hashlib
import html

import game
from providers import RemoteError

CHUNK = 100  # limite do Spotify por requisição para adicionar ou remover itens


def marker(account, key):
    """Temporary description of a playlist the app creates, so a create whose response was lost is
    found again instead of duplicated. Replaced by your description right after the create."""
    return 'Spotify Project ' + hashlib.sha256((account + '\0' + key).encode()).hexdigest()[:20]


def _uri(track_id): return 'spotify:track:' + track_id


def _ids(uris): return {u.rsplit(':', 1)[1] for u in uris if u.startswith('spotify:track:')}


def prepare(store, account, api):
    """Read your playlists live and compute, per playlist, what enters, what leaves and what changes
    in name and description. Nothing is written."""
    owned = {p['id']: p for p in api.playlists()}
    by_marker = {p.get('description'): p for p in owned.values() if (p.get('description') or '').startswith('Spotify Project ')}
    cards, alias, members = game.deck(store, account)
    tracks = {t['id']: t for t in cards}
    done = game.decisions(store, account)
    def describe(ids, present=()):
        # 'uris': what is written; a removal takes out every version of the song in the playlist.
        rows = []
        for i in sorted(ids, key=lambda i: (tracks[i]['title'].casefold(), i)):
            uris = [_uri(m) for m in members.get(i, [i]) if _uri(m) in present] if present else [_uri(i)]
            rows.append({'id': i, 'title': tracks[i]['title'], 'artists': tracks[i]['artists'], 'uris': uris})
        return rows
    items = []
    for p in game.profiles(store, account):
        if p.get('missing'): continue
        key = p['key']
        add = {t for t, d in done.items() if key in d['add'] and t in tracks}
        remove = {t for t, d in done.items() if key in d['remove'] and t in tracks}
        ident, recovered = p.get('spotify_id'), False
        if not ident and marker(account, key) in by_marker:
            ident, recovered = by_marker[marker(account, key)]['id'], True
        if ident and ident not in owned:
            raise ValueError(f'A playlist "{p["name"]}" não está mais na sua conta. Sincronize de novo antes de gravar.')
        live_uris = api.contents(ident) if ident else set()
        live = {alias.get(i, i) for i in _ids(live_uris)}
        add, remove = add - live, remove & live
        spotify = owned.get(ident) or {}
        live_name = html.unescape(spotify.get('name') or '')
        live_description = html.unescape(spotify.get('description') or '')
        item = {'key': key, 'id': ident, 'name': p['name'], 'add': describe(add), 'remove': describe(remove, live_uris),
                'before': len(live), 'after': len(live | add) - len(remove), 'live': sorted(live_uris), 'rename': None, 'describe': None}
        if not ident:
            item['action'] = 'create' if add else 'skip'
            item['describe'] = {'from': '', 'to': p['description']} if p['description'] else None
        else:
            if recovered or p['name'] != p.get('spotify_name'):
                if p['name'] != live_name: item['rename'] = {'from': live_name, 'to': p['name']}
            if recovered and live_description == marker(account, key):
                item['describe'] = {'from': '', 'to': p['description']}  # replaces the temporary marker
            elif p['description'] != p.get('spotify_description') and p['description'] != live_description:
                item['describe'] = {'from': live_description, 'to': p['description']}
            item['action'] = 'update' if (add or remove or item['rename'] or item['describe']) else 'same'
        items.append(item)
    order = {'create': 0, 'update': 1, 'skip': 2, 'same': 3}
    items.sort(key=lambda i: order[i['action']])
    totals = {'playlists': sum(1 for i in items if i['action'] in ('create', 'update')),
              'create': sum(1 for i in items if i['action'] == 'create'),
              'add': sum(len(i['add']) for i in items if i['action'] in ('create', 'update')),
              'remove': sum(len(i['remove']) for i in items if i['action'] == 'update')}
    return {'items': items, 'totals': totals}


def execute(store, account, api, plan):
    """Write the confirmed preview, one playlist at a time. Stops at the first failure."""
    results = []
    for item in plan['items']:
        if item['action'] not in ('create', 'update'): continue
        name = item['rename']['to'] if item['rename'] else item['name']
        try:
            ident = item['id']
            owned = {p['id']: p for p in api.playlists()}
            if item['action'] == 'create':
                # A create whose answer was lost shows up with the marker: use it instead of creating another.
                found = [p for p in owned.values() if p.get('description') == marker(account, item['key'])]
                if len(found) > 1: raise RemoteError('Há mais de uma playlist criada pelo app com este identificador. Confira no Spotify.')
                ident = found[0]['id'] if found else api.call('/me/playlists', 'POST', {'name': name, 'public': False, 'description': marker(account, item['key'])})['id']
                present = api.contents(ident) if found else set()
            else:
                if ident not in owned: raise RemoteError('A playlist não pertence mais à conta conectada.')
                present = api.contents(ident)
                if present != set(item['live']):
                    raise ValueError('A playlist mudou no Spotify desde a prévia. Nada foi gravado nela; prepare uma nova prévia.')
            profile = next(p for p in game.profiles(store, account) if p['key'] == item['key'])
            body = {}
            if item['rename']: body['name'] = name
            if item['describe'] is not None or item['action'] == 'create': body['description'] = profile['description']
            warning = None
            if body:
                try: api.call('/playlists/' + ident, 'PUT', body)
                except RemoteError:
                    # Clearing the temporary description of a new playlist must not block its songs.
                    if body != {'description': ''}: raise
                    warning = 'Não consegui apagar a descrição temporária; edite-a no Spotify se quiser.'
            add = [u for t in item['add'] for u in t['uris'] if u not in present]
            for start in range(0, len(add), CHUNK):
                api.call('/playlists/' + ident + '/items', 'POST', {'uris': add[start:start + CHUNK]})
            remove = [u for t in item['remove'] for u in t['uris'] if u in present]
            for start in range(0, len(remove), CHUNK):
                api.call('/playlists/' + ident + '/items', 'DELETE', {'items': [{'uri': u} for u in remove[start:start + CHUNK]]})
            game.apply_published(store, account, item['key'], ident, name, profile['description'],
                                 [t['id'] for t in item['add']], [u.rsplit(':', 1)[1] for t in item['remove'] for u in t['uris']])
            results.append({'name': name, 'status': 'Criada' if item['action'] == 'create' else 'Atualizada',
                            'added': len(add), 'removed': len(remove), 'url': 'https://open.spotify.com/playlist/' + ident,
                            **({'warning': warning} if warning else {})})
        except (RemoteError, ValueError) as error:
            results.append({'name': name, 'status': 'Falha', 'error': str(error)})
            break
    return results
