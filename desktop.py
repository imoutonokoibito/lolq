"""LoLQ desktop entry point: background connector, picker process and tray menu."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser


def data_directory():
    return Path(os.environ.get('LOLQ_DATA_DIR') or Path(os.environ.get('LOCALAPPDATA', Path.home() / '.local' / 'share')) / 'LoLQ')


def prepare_environment():
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    os.environ['LOLQ_CONFIG_PATH'] = str(directory / 'config.json')
    os.environ['LOLQ_STATUS_PATH'] = str(directory / 'status.json')
    return directory


class Controller:
    def __init__(self, directory, no_worker=False):
        self.directory = directory
        self.no_worker = no_worker
        self.stop = threading.Event()
        self.process = None
        self.icon = None
        self.last_start = 0

    def status(self):
        import runtime
        running = self.process is not None and self.process.poll() is None
        result = dict(app='lolq', version=runtime.VERSION, enabled=runtime.enabled(),
                      worker=running, connected=False, phase=None)
        try:
            path = self.directory / 'status.json'
            data = runtime.read_json(path)
            if running and data.get('pid') == self.process.pid and time.time() - path.stat().st_mtime < 20:
                result.update(connected=data.get('connected') is True, phase=data.get('phase'))
        except (OSError, ValueError):
            pass
        return result

    def supervise(self):
        from diagnostics import logger
        while not self.stop.wait(1):
            if not self.no_worker and (self.process is None or self.process.poll() is not None) and time.monotonic() - self.last_start > 5:
                self.last_start = time.monotonic()
                command = [sys.executable]
                if not getattr(sys, 'frozen', False):
                    command.append(str(Path(__file__).resolve()))
                command.append('--worker')
                flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
                self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                                stderr=subprocess.DEVNULL, creationflags=flags)
                logger.info('Picker worker started pid=%s', self.process.pid)
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

    def toggle(self, *_):
        import runtime
        with runtime.LOCK:
            cfg = runtime.read_config()
            cfg['enabled'] = not cfg.get('enabled', True)
            runtime.atomic_json(runtime.CONFIG_PATH, cfg)

    def open_page(self, *_):
        import runtime
        webbrowser.open(runtime.WEB_URL + '#connect')

    def quit(self, *_):
        self.stop.set()

    def tray(self):
        import pystray
        from PIL import Image, ImageDraw
        picture = Image.new('RGBA', (64, 64))
        draw = ImageDraw.Draw(picture)
        draw.rounded_rectangle((2, 2, 62, 62), radius=15, fill='#007aff')
        draw.ellipse((16, 13, 47, 46), outline='white', width=6)
        draw.line((38, 38, 50, 51), fill='white', width=6)
        import runtime
        self.icon = pystray.Icon('LoLQ', picture, 'LoLQ', menu=pystray.Menu(
            pystray.MenuItem('Open LoLQ', self.open_page, default=True),
            pystray.MenuItem(lambda _: 'Pause automation' if runtime.enabled() else 'Turn on automation', self.toggle),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit LoLQ', self.quit)))
        self.icon.run_detached()


def local_request(path, token=None, method='GET'):
    import runtime
    headers = {'X-LoLQ-Client': 'web'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(f'http://127.0.0.1:{runtime.PORT}' + path, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--shutdown', action='store_true')
    parser.add_argument('--no-tray', action='store_true')
    parser.add_argument('--no-worker', action='store_true')
    parser.add_argument('--uri')
    args = parser.parse_args()
    directory = prepare_environment()
    import runtime
    if args.shutdown:
        try:
            session = local_request('/api/session')
            local_request('/api/shutdown', session['token'], 'POST')
            for _ in range(50):
                time.sleep(0.1)
                try:
                    local_request('/api/health')
                except Exception:
                    break
        except Exception:
            pass
        return
    if args.uri and args.uri.rstrip('/') != 'lolq://open':
        return
    if not runtime.CONFIG_PATH.exists():
        runtime.atomic_json(runtime.CONFIG_PATH, runtime.DEFAULT_CONFIG)
    if args.worker:
        import main as picker
        picker.connector.start()
        return
    from bridge import create_app, LoopbackServer
    from diagnostics import logger
    controller = Controller(directory, args.no_worker)
    try:
        server = LoopbackServer(create_app(controller), host='127.0.0.1', port=runtime.PORT, threads=4,
                               clear_untrusted_proxy_headers=True, max_request_body_size=256 * 1024)
    except OSError:
        try:
            if local_request('/api/health').get('app') == 'lolq' and not args.background:
                controller.open_page()
        except Exception:
            logger.error('Cannot start connector: loopback port %s is occupied', runtime.PORT)
            if sys.platform == 'win32' and not args.background:
                import ctypes
                ctypes.windll.user32.MessageBoxW(0, 'LoLQ could not start. Restart Windows and try again.', 'LoLQ', 0x10)
        return
    signal.signal(signal.SIGTERM, lambda *_: controller.stop.set())
    signal.signal(signal.SIGINT, lambda *_: controller.stop.set())
    worker = threading.Thread(target=controller.supervise, daemon=True)
    worker.start()
    threading.Thread(target=server.run, daemon=True).start()
    if sys.platform == 'win32' and not args.no_tray:
        try:
            controller.tray()
        except Exception:
            logger.exception('Tray unavailable; connector remains available from the website')
    if not args.background:
        controller.open_page()
    logger.info('Desktop connector ready on loopback port %s', runtime.PORT)
    try:
        controller.stop.wait()
    finally:
        controller.stop.set()
        worker.join(timeout=7)
        if controller.icon:
            controller.icon.stop()
        server.close()


if __name__ == '__main__':
    main()
