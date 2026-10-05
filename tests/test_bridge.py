import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import runtime
from bridge import create_app


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'config.json'
        self.patch = patch.object(runtime, 'CONFIG_PATH', self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        runtime.atomic_json(self.path, runtime.DEFAULT_CONFIG)
        self.stop = threading.Event()
        controller = type('Controller', (), {'stop': self.stop, 'status': lambda _: {'app': 'lolq'}})()
        self.client = create_app(controller).test_client()
        self.origin = 'https://imoutosuki.com'
        self.base = f'http://127.0.0.1:{runtime.PORT}'
        self.headers = {'X-LoLQ-Client': 'web', 'Origin': self.origin}
        r = self.request('/api/session')
        self.assertEqual(r.status_code, 200)
        self.headers['Authorization'] = 'Bearer ' + r.json['token']

    def request(self, path, method='GET', headers=None, **kwargs):
        return self.client.open(path, method=method, base_url=self.base,
                                headers=self.headers if headers is None else headers, **kwargs)

    def test_configuration_round_trip_and_paused_default(self):
        config = self.request('/api/config').json
        self.assertFalse(config['enabled'])
        config['bans'] = ["Cho'Gath", "Nunu & Willump"]
        self.assertEqual(self.request('/api/config', 'POST', json=config).status_code, 200)
        self.assertEqual(json.loads(self.path.read_text())['bans'], ["Cho'Gath", "Nunu & Willump"])

    def test_foreign_origins_cannot_bootstrap_read_or_write(self):
        for origin in ['https://evil.test', 'null', 'https://imoutosuki.com.evil.test', 'http://imoutosuki.com']:
            for endpoint in ['/api/session', '/api/health', '/api/config']:
                response = self.request(endpoint, headers={**self.headers, 'Origin': origin})
                self.assertEqual(response.status_code, 403)
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
            self.assertEqual(self.request('/api/config', 'POST', headers={**self.headers, 'Origin': origin}, json=runtime.DEFAULT_CONFIG).status_code, 403)

    def test_dns_rebinding_and_simple_csrf_are_rejected(self):
        response = self.client.get('/api/session', base_url='http://evil.test:17653', headers=self.headers)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.request('/api/session', headers={}).status_code, 403)
        self.assertEqual(self.request('/api/config', 'POST', headers={'Origin': self.origin}, data='x').status_code, 403)

    def test_preflight_is_narrow_and_session_required(self):
        response = self.request('/api/config', 'OPTIONS', headers={'Origin': self.origin,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,x-lolq-client'})
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['Access-Control-Allow-Origin'], self.origin)
        self.assertEqual(response.headers['Access-Control-Allow-Private-Network'], 'true')
        self.assertEqual(self.request('/api/config', headers={'X-LoLQ-Client': 'web', 'Origin': self.origin}).status_code, 401)

    def test_invalid_config_never_overwrites_previous(self):
        before = self.path.read_bytes()
        for config in [None, [], {}, {**runtime.DEFAULT_CONFIG, 'enabled': 'yes'},
                       {**runtime.DEFAULT_CONFIG, 'bans': ['<script>']},
                       {**runtime.DEFAULT_CONFIG, 'roles': {'mid': ['missing']}},
                       {**runtime.DEFAULT_CONFIG, 'layouts': {'1': {'champion': 'Ahri', 'spells': [], 'runes': [], 'injected': 1}}}]:
            response = self.request('/api/config', 'POST', json=config)
            self.assertIn(response.status_code, (400, 415))
            self.assertEqual(self.path.read_bytes(), before)

    def test_large_body_and_unrelated_lcu_routes_rejected(self):
        response = self.request('/api/config', 'POST', data='x' * (257 * 1024), content_type='application/json')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.request('/lol-login/v1/session').status_code, 404)

    def test_atomic_writes_remain_readable_and_settings_persist(self):
        errors = []
        def write():
            for i in range(30):
                runtime.atomic_json(self.path, {**runtime.DEFAULT_CONFIG, 'bans': ['Ahri'] * (i % 3)})
        thread = threading.Thread(target=write)
        thread.start()
        while thread.is_alive():
            try:
                self.assertIn('layouts', runtime.read_config())
            except Exception as exc:
                errors.append(exc)
        thread.join()
        self.assertEqual(errors, [])

    def test_shutdown_requires_session(self):
        response = self.request('/api/shutdown', 'POST', headers={'X-LoLQ-Client': 'web'})
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.stop.is_set())
        self.assertEqual(self.request('/api/shutdown', 'POST').status_code, 200)
        self.assertTrue(self.stop.is_set())

class PauseTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_prevents_ready_check_and_champion_select_requests(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        import main
        connection = SimpleNamespace(request=AsyncMock())
        with patch.object(runtime, 'enabled', return_value=False):
            await main.ready_check_changed(connection, SimpleNamespace(data={'state': 'InProgress', 'playerResponse': 'None'}))
            await main.champ_select_changed(connection, SimpleNamespace(type='Update'))
        connection.request.assert_not_awaited()
