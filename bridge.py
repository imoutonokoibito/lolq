"""Loopback-only API for the hosted LoLQ editor. Never exposes LCU credentials."""
import secrets
import socket
import sys
from waitress.server import TcpWSGIServer
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
import runtime


class LoopbackServer(TcpWSGIServer):
    def set_reuse_addr(self):
        # SO_REUSEADDR permits competing listeners on Windows. The connector
        # must own its port exclusively, including across Windows sessions.
        if sys.platform == 'win32':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            super().set_reuse_addr()


ORIGINS = {'https://imoutosuki.com', 'https://glorreichersieg.com',
           f'http://127.0.0.1:{runtime.PORT}', f'http://localhost:{runtime.PORT}'}


def create_app(controller):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 256 * 1024
    token = secrets.token_urlsafe(32)

    @app.before_request
    def guard():
        if request.host not in {f'127.0.0.1:{runtime.PORT}', f'localhost:{runtime.PORT}'}:
            return jsonify(error='Invalid host'), 403
        origin = request.headers.get('Origin')
        if origin is not None and origin not in ORIGINS:
            return jsonify(error='Origin not allowed'), 403
        if request.method == 'OPTIONS':
            if not origin or request.headers.get('Access-Control-Request-Method') not in {'GET', 'POST'}:
                return jsonify(error='Invalid preflight'), 403
            return '', 204
        if not request.path.startswith('/api/'):
            return None
        if request.headers.get('X-LoLQ-Client') != 'web':
            return jsonify(error='Use the LoLQ page'), 403
        if request.path not in {'/api/health', '/api/session'}:
            supplied = request.headers.get('Authorization', '').removeprefix('Bearer ')
            if not secrets.compare_digest(supplied, token):
                return jsonify(error='Reconnect to LoLQ'), 401

    @app.after_request
    def headers(response):
        origin = request.headers.get('Origin')
        if origin in ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-LoLQ-Client'
            response.headers['Access-Control-Allow-Private-Network'] = 'true'
            response.headers['Access-Control-Max-Age'] = '600'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; connect-src 'self' https:; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        return response

    @app.get('/api/health')
    def health():
        return jsonify(app='lolq', version=runtime.VERSION, protocol=1)

    @app.get('/api/session')
    def session():
        return jsonify(token=token, version=runtime.VERSION, protocol=1)

    @app.get('/api/status')
    def status():
        return jsonify(controller.status())

    @app.get('/api/config')
    def get_config():
        with runtime.LOCK:
            return jsonify(runtime.read_config())

    @app.post('/api/config')
    def save_config():
        if not request.is_json:
            return jsonify(error='JSON required'), 415
        try:
            value = runtime.validate_config(request.get_json())
            with runtime.LOCK:
                runtime.atomic_json(runtime.CONFIG_PATH, value)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(ok=True)

    @app.post('/api/shutdown')
    def shutdown():
        controller.stop.set()
        return jsonify(ok=True)

    @app.get('/')
    def index():
        return send_from_directory(Path(__file__).parent / 'static', 'index.html')

    @app.get('/<path:filename>')
    def assets(filename):
        if filename not in {'app.js', 'connection.js', 'style.css', 'release.json'}:
            return '', 404
        return send_from_directory(Path(__file__).parent / 'static', filename)

    return app
