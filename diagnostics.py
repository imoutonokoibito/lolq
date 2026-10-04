"""Persistent local diagnostics. Never inspect the connection or its credentials."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import time


def configure_logging():
    logger = logging.getLogger('lolq')
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    formatter = logging.Formatter('%(asctime)s %(levelname)s [%(process)d] %(message)s')
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    logger.addHandler(console)
    directory = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'lolq' / 'logs'
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / 'lolq.log', maxBytes=5 * 1024 * 1024,
                                      backupCount=5, encoding='utf-8')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.info('LoLQ started; Python=%s; frozen=%s; logs=%s',
                    sys.version.split()[0], bool(getattr(sys, 'frozen', False)), handler.baseFilename)
    except OSError:
        logger.exception('Cannot open persistent logs; console logging remains active')
    return logger


logger = configure_logging()


class _LcuDriverNoise(logging.Filter):
    """lcu-driver logs empty websocket frames with a malformed format string, which makes
    Python print a '--- Logging error ---' traceback. Empty frames are keep-alives: drop them."""

    def filter(self, record):
        if str(record.msg).startswith('Error decoding the following JSON'):
            payload = record.args[0] if isinstance(record.args, tuple) and record.args else ''
            if not str(payload).strip():
                return False
            record.msg, record.args = 'lcu-driver could not decode a websocket frame: %s', (payload,)
        return True


logging.getLogger('lcu-driver').addFilter(_LcuDriverNoise())


async def request_lcu(connection, method, path, quiet_statuses=(), **kwargs):
    started = time.monotonic()
    # Only caller-supplied gameplay payloads, never headers, auth or connection URLs.
    logger.debug('LCU request %s %s params=%s data=%s', method.upper(), path,
                 kwargs.get('params'), kwargs.get('data'))
    try:
        response = await connection.request(method, path, **kwargs)
    except Exception as exc:
        logger.warning('LCU request failed %s %s elapsed_ms=%.0f exception=%s',
                       method.upper(), path, (time.monotonic() - started) * 1000, type(exc).__name__)
        raise
    elapsed = (time.monotonic() - started) * 1000
    logger.debug('LCU response %s %s status=%s elapsed_ms=%.0f',
                 method.upper(), path, response.status, elapsed)
    if not 200 <= response.status < 300:
        level = logging.DEBUG if response.status in quiet_statuses else logging.WARNING
        try:
            body = (await response.text())[:500]
        except Exception:
            body = '<unreadable>'
        logger.log(level, 'LCU error %s %s status=%s body=%s', method.upper(), path, response.status, body)
    return response
