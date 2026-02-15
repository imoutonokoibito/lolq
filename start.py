"""
LoLQ - Start everything with one command.

Usage:
  python start.py          - Start both config editor + autopicker
  python start.py --editor - Config editor only
  python start.py --picker - Autopicker only
"""
import subprocess, sys, os, time, webbrowser, signal, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 5005
procs = []

def cleanup(*_):
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def wait_for_server(port, timeout=10):
    """Poll until the server responds."""
    for _ in range(timeout * 10):
        try:
            urllib.request.urlopen(f'http://localhost:{port}/api/config', timeout=1)
            return True
        except Exception:
            time.sleep(0.1)
    return False

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else '--all'

    if mode in ('--all', '--editor'):
        print(f"Starting config editor on http://localhost:{PORT}")
        p = subprocess.Popen(
            [sys.executable, os.path.join(DIR, 'server.py')],
            cwd=DIR
        )
        procs.append(p)
        if wait_for_server(PORT):
            print("Config editor ready")
            webbrowser.open(f'http://localhost:{PORT}')
        else:
            print("Warning: server may not have started correctly")

    if mode in ('--all', '--picker'):
        print("Starting autopicker (waiting for League client...)")
        p = subprocess.Popen(
            [sys.executable, os.path.join(DIR, 'main.py')],
            cwd=DIR
        )
        procs.append(p)

    if not procs:
        print("Usage: python start.py [--editor|--picker|--all]")
        return

    print("\nLoLQ running. Ctrl+C to stop.")
    try:
        while any(p.poll() is None for p in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    cleanup()

if __name__ == '__main__':
    main()
