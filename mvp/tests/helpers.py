"""Shared test helpers (not a test module): a real local server on a random port with a temporary
database; the background collector is a stub, so no test reaches the network."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Store

ID1 = 'a' * 22
ID2 = 'b' * 22


def raw(ident=ID1): return {'id': ident, 'name': 'Song', 'artists': [{'name': 'Artist'}]}


class StubCollector:
    def __init__(self): self.started = []
    def start(self, account): self.started.append(account); return True
    def status(self, account): return {'running': False, 'message': '', 'remaining': 0}


class HTTPTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.port = self.http.server_port
        self.collector = StubCollector()
        self.patches = [patch.object(server, 'STORE', Store(Path(self.tmp.name) / 'test.sqlite3')), patch.object(server, 'SESSIONS', {}),
                        patch.object(server, 'PORT', self.port), patch.object(server, 'ORIGIN', f'http://127.0.0.1:{self.port}'),
                        patch.object(server, 'COLLECTOR', self.collector)]
        for p in self.patches: p.start()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True); self.thread.start()
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/game') as r:
            self.cookie = r.headers['Set-Cookie'].split(';')[0]; self.state = json.load(r)
        self.session = next(iter(server.SESSIONS.values()))

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{self.port}/api/' + path, headers={'Cookie': self.cookie})) as r:
            return json.load(r)

    def post(self, path, data, csrf=True, origin=True):
        headers = {'Content-Type': 'application/json', 'Cookie': self.cookie}
        if csrf: headers['X-CSRF-Token'] = self.state['csrf']
        if origin: headers['Origin'] = f'http://127.0.0.1:{self.port}'
        request = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/' + path, data=json.dumps(data).encode(), headers=headers)
        try:
            with urllib.request.urlopen(request) as r: return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            with e: return e.code, json.load(e)
