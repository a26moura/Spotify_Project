"""Coleta em segundo plano para o jogo: Deezer e LRCLIB (Enricher.quick), uma música por vez,
na ordem da fila do jogo. Só lê serviços públicos; nunca grava no Spotify."""
import threading
import time

import game

RETRY_PAUSE = 60   # seconds to wait before trying again the tracks whose source failed temporarily
MAX_PASSES = 3


def pending(store, account):
    order = {ident: i for i, ident in enumerate(game.queue(store, account))}
    rows = [t for t in store.tracks(account, active=True) if not t.get('quick_checked') and not t.get('review')]
    return sorted(rows, key=lambda t: order.get(t['id'], len(order)))


class Collector:
    def __init__(self, store, enricher, lock, pause=RETRY_PAUSE):
        self.store, self.enricher, self.lock, self.pause = store, enricher, lock, pause
        self.state, self.threads = {}, {}

    def status(self, account):
        with self.lock:
            left = len(pending(self.store, account))
        info = dict(self.state.get(account) or {'running': False, 'message': ''})
        return dict(info, remaining=left)

    def step(self, account, track):
        """Look up one track (network, outside the lock) and merge the result into the latest copy."""
        result = self.enricher.quick(track)
        with self.lock:
            current = next((t for t in self.store.tracks(account) if t['id'] == track['id']), None)
            if not current or current.get('review'): return result
            current.update(result)
            self.store.put(account, current)
        return result

    def run(self, account):
        state = self.state[account]
        try:
            for attempt in range(MAX_PASSES):
                with self.lock:
                    rows = pending(self.store, account)
                if not rows: break
                failed = 0
                for i, track in enumerate(rows):
                    state['message'] = f'Buscando informações: {track["title"]} ({i + 1} de {len(rows)})'
                    if not self.step(account, track).get('quick_checked'): failed += 1
                if not failed: break
                if attempt < MAX_PASSES - 1:
                    state['message'] = f'{failed} músicas sem resposta de uma fonte. Nova tentativa em {self.pause} s.'
                    time.sleep(self.pause)
            left = len(pending(self.store, account))
            state['message'] = 'Informações coletadas.' if not left else f'{left} músicas ficaram sem resposta de alguma fonte; tente de novo mais tarde.'
        except Exception as error:  # a failure must never stop the game; the track stays pending
            state['message'] = 'Coleta interrompida: ' + str(error)
        finally:
            state['running'] = False

    def start(self, account):
        if (self.state.get(account) or {}).get('running'): return False
        self.state[account] = {'running': True, 'message': 'Coleta iniciada.', 'started': time.time()}
        thread = threading.Thread(target=self.run, args=(account,), daemon=True)
        self.threads[account] = thread
        thread.start()
        return True
