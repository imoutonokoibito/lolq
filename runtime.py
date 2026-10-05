"""Shared desktop paths and atomic configuration storage."""
import json
import os
from pathlib import Path
import tempfile
import threading
import time

VERSION = '1.0.0'
PORT = 17653
WEB_URL = 'https://imoutosuki.com/lolq/'
CONFIG_PATH = Path(os.environ.get('LOLQ_CONFIG_PATH', Path(__file__).with_name('config.json')))
LOCK = threading.RLock()
DEFAULT_CONFIG = {'enabled': False, 'bans': [], 'layouts': {},
                  'roles': {r: [] for r in ('top', 'jungle', 'mid', 'bot', 'utility')},
                  'fallback': {'mode': 'random_default', 'layout_id': ''}}


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.01)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    # Windows can briefly deny a new open while ReplaceFile/rename completes.
    for attempt in range(20):
        try:
            with Path(path).open(encoding='utf-8') as file:
                return json.load(file)
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.01)


def read_config():
    return read_json(CONFIG_PATH)


def enabled():
    try:
        return read_config().get('enabled', True) is True
    except (OSError, ValueError):
        return False


def validate_config(value):
    if not isinstance(value, dict):
        raise ValueError('Expected a configuration object')
    if set(value) - {'enabled', 'bans', 'layouts', 'roles', 'fallback'}:
        raise ValueError('Unknown configuration field')
    if not isinstance(value.get('enabled', False), bool):
        raise ValueError('Invalid enabled value')
    def names(items, maximum):
        return isinstance(items, list) and len(items) <= maximum and all(
            isinstance(x, str) and 0 < len(x) <= 100 and not any(c in x for c in '<>"\\\r\n') for x in items)
    if not names(value.get('bans'), 30):
        raise ValueError('Invalid bans')
    layouts = value.get('layouts')
    if not isinstance(layouts, dict) or len(layouts) > 150:
        raise ValueError('Invalid layouts')
    for key, layout in layouts.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdigit() or len(key) > 12:
            raise ValueError('Invalid layout identifier')
        if not isinstance(layout, dict) or set(layout) != {'champion', 'spells', 'runes'}:
            raise ValueError('Invalid layout')
        if not names([layout['champion']], 1) or not names(layout['spells'], 2) or not names(layout['runes'], 12):
            raise ValueError('Invalid champion, spells or runes')
    roles = value.get('roles')
    if not isinstance(roles, dict) or set(roles) != set(DEFAULT_CONFIG['roles']):
        raise ValueError('Invalid roles')
    for ids in roles.values():
        if not isinstance(ids, list) or len(ids) > 150 or any(not isinstance(x, str) or x not in layouts for x in ids):
            raise ValueError('Invalid pick order')
    fallback = value.get('fallback')
    if not isinstance(fallback, dict) or set(fallback) != {'mode', 'layout_id'}:
        raise ValueError('Invalid fallback')
    if fallback['mode'] not in ('random_default', 'fallback_layout', 'dodge') or not isinstance(fallback['layout_id'], str):
        raise ValueError('Invalid fallback mode')
    if fallback['mode'] == 'fallback_layout' and fallback['layout_id'] not in layouts:
        raise ValueError('Choose a fallback champion')
    return value
