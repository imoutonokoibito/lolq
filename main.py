import asyncio
import time
import requests
import urllib3
import traceback
import json
import re
import random
import os
from lcu_driver import Connector
from diagnostics import logger, request_lcu

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

connector = Connector()
global am_i_assigned, am_i_picking, am_i_banning, ban_number, phase, picks, bans, in_game, have_i_prepicked
am_i_assigned = False
am_i_banning = False
am_i_picking = False
in_game = False
phase = ''
have_i_prepicked = False
have_i_dodged = False

# Ownership is diagnostic; champ-select eligibility also includes temporary unlocks.
owned_champion_ids = None
champ_select_lock = asyncio.Lock()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def migrate_config(cfg):
    """Convert old champions.{role}.order format to layouts + roles format"""
    if "layouts" in cfg:
        return cfg
    layouts = {}
    roles = {}
    nid = 1
    for role, data in cfg.get("champions", {}).items():
        ids = []
        for e in data.get("order", []):
            if isinstance(e, str):
                e = {"champion": e, "spells": [], "runes": []}
            c = e.get("champion", "")
            s = e.get("spells", [])
            r = e.get("runes", [])
            found = next((lid for lid, l in layouts.items()
                          if l["champion"] == c and l["spells"] == s and l["runes"] == r), None)
            if found:
                ids.append(found)
            else:
                lid = str(nid); nid += 1
                layouts[lid] = {"champion": c, "spells": s, "runes": r}
                ids.append(lid)
        roles[role] = ids
    fb = cfg.get("fallback", {})
    new_fb = {"mode": fb.get("mode", "random_default"), "layout_id": ""}
    if fb.get("mode") == "fallback_layout" and fb.get("fallback_layout", {}).get("champion"):
        lid = str(nid); nid += 1
        layouts[lid] = {"champion": fb["fallback_layout"].get("champion", ""),
                        "spells": fb["fallback_layout"].get("spells", []),
                        "runes": fb["fallback_layout"].get("runes", [])}
        new_fb["layout_id"] = lid
    if new_fb["mode"] == "other_roles":
        new_fb["mode"] = "random_default"
    return {"bans": cfg.get("bans", []), "layouts": layouts, "roles": roles, "fallback": new_fb}

def load_config():
    """Load config from config.json (called on every champ select for hot-reload)"""
    with open(CONFIG_PATH, "r") as f:
        cfg = json.load(f)
    if "layouts" not in cfg:
        cfg = migrate_config(cfg)
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    return cfg

# Initial load to verify config exists
try:
    _cfg = load_config()
    for role, ids in _cfg.get("roles", {}).items():
        logger.info(f"{role}: {len(ids)} picks")
    logger.info(f"Layouts: {len(_cfg.get('layouts', {}))}")
    logger.info(f"Bans: {len(_cfg.get('bans', []))}")
    logger.info(f"Fallback: {_cfg.get('fallback', {}).get('mode', 'random_default')}")
    del _cfg
except Exception as e:
    logger.info(f"Error loading config.json: {str(e)}")
    logger.info("Please ensure config.json exists with valid configuration")
    exit(1)

# Summoner spell mappings
SUMMONER_SPELLS = {
    'barrier': 21, 'cleanse': 1, 'exhaust': 3, 'flash': 4, 'ghost': 6,
    'heal': 7, 'ignite': 14, 'smite': 11, 'teleport': 12, 'clarity': 13, 'mark': 32
}

# Rune data - will be loaded from Data Dragon
runes_data = None

# Stat rune mappings - organized by slot (will be updated from Community Dragon API)
STAT_RUNES = {
    # Offense Slot (Row 1)
    'adaptive force': 5008,  # +9 Adaptive Force
    'attack speed': 5005,    # +10% Attack Speed
    'ability haste': 5007,   # +8 Ability Haste
    
    # Flex Slot (Row 2)
    'adaptive force flex': 5008,  # +9 Adaptive Force (same as offense)
    'movement speed': 5010,       # +2% Movement Speed
    'health scaling': 5001,       # +10-180 Health (based on level)
    
    # Defense Slot (Row 3)
    'health': 5011,              # +65 Health (flat)
    'tenacity': 5013,            # +10% Tenacity and Slow Resist
    'health scaling def': 5001,  # +10-180 Health (based on level)
    
    # Legacy mappings for backward compatibility
    'armor': 5002,           # +6 Armor (removed from current system)
    'magic resist': 5003,    # +8 Magic Resist (removed from current system)
    'armor mr': 5012         # +1-8 Armor and Magic Resist (removed from current system)
}

pick_number = 0
ban_number = 0
assigned_position = ''

# Global lazy-loaded Data Dragon version
_ddragon_version = None

def get_ddragon_version():
    """Get Data Dragon version (lazy loaded)"""
    global _ddragon_version
    if _ddragon_version is None:
        _ddragon_version = requests.get('https://ddragon.leagueoflegends.com/api/versions.json').json()[0]
    return _ddragon_version

async def get_champions_map():
    # Get champion data from Data Dragon for English names
    ddragon_version = get_ddragon_version()
    ddragon_champions = requests.get(f'https://ddragon.leagueoflegends.com/cdn/{ddragon_version}/data/en_US/champion.json').json()
    # Swap key and value to map from name to ID instead
    champion_name_to_key = {name: int(champ['key']) for name, champ in ddragon_champions['data'].items()}
    
    champions_map = champion_name_to_key
            
    return champions_map

async def get_runes_data():
    """Load rune data from Data Dragon"""
    global runes_data
    try:
        ddragon_version = get_ddragon_version()
        runes_response = requests.get(f'https://ddragon.leagueoflegends.com/cdn/{ddragon_version}/data/en_US/runesReforged.json')
        runes_data = runes_response.json()
        return runes_data
    except Exception as e:
        logger.info(f"Failed to load runes data: {str(e)}")
        return None

async def load_stat_runes():
    """Load current stat rune data from Community Dragon API with accurate slot mappings"""
    global STAT_RUNES
    try:
        response = requests.get('https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/perks.json')
        perks_data = response.json()
        
        # Extract stat runes (IDs 5001-5013) with proper slot categorization
        stat_runes = {}
        for perk in perks_data:
            perk_id = perk.get('id')
            if perk_id and 5001 <= perk_id <= 5013:
                name = perk.get('name', '').lower()
                description = perk.get('shortDesc', '').lower()
                
                # Map based on actual current League stat rune system
                if perk_id == 5008:  # Adaptive Force (Offense + Flex)
                    stat_runes['adaptive force'] = perk_id
                    stat_runes['adaptive force flex'] = perk_id
                elif perk_id == 5005:  # Attack Speed (Offense)
                    stat_runes['attack speed'] = perk_id
                elif perk_id == 5007:  # Ability Haste (Offense)
                    stat_runes['ability haste'] = perk_id
                elif perk_id == 5010:  # Movement Speed (Flex)
                    stat_runes['movement speed'] = perk_id
                    stat_runes['move speed'] = perk_id
                elif perk_id == 5001:  # Health Scaling (Flex + Defense)
                    stat_runes['health scaling'] = perk_id
                    stat_runes['health scaling def'] = perk_id
                elif perk_id == 5011:  # Flat Health (Defense)
                    stat_runes['health'] = perk_id
                elif perk_id == 5013:  # Tenacity and Slow Resist (Defense)
                    stat_runes['tenacity'] = perk_id
                    stat_runes['tenacity and slow resist'] = perk_id
                
                # Legacy runes (may be removed in future updates)
                elif perk_id == 5002:  # Armor (legacy)
                    stat_runes['armor'] = perk_id
                elif perk_id == 5003:  # Magic Resist (legacy)
                    stat_runes['magic resist'] = perk_id
                elif perk_id == 5012:  # Armor and MR Scaling (legacy)
                    stat_runes['armor mr'] = perk_id
                    stat_runes['resist scaling'] = perk_id
        
        if stat_runes:
            STAT_RUNES.update(stat_runes)
            logger.info(f"Updated stat runes from Community Dragon API: {len(stat_runes)} stat runes loaded")
            logger.info(f"Current stat rune layout: Offense (5008/5005/5007), Flex (5008/5010/5001), Defense (5011/5013/5001)")
        
    except Exception as e:
        logger.info(f"Failed to load stat runes from Community Dragon API: {str(e)}")
        logger.info("Using fallback stat rune values")

def normalize_string(s):
    """Remove spaces, separators, and convert to lowercase for fuzzy matching"""
    return re.sub(r"[^a-zA-Z0-9]", "", s.lower())

def find_rune_by_name(rune_name):
    """Find rune ID by fuzzy matching the name"""
    if not runes_data:
        return None
    
    normalized_search = normalize_string(rune_name)
    
    # Search through all rune trees
    for tree in runes_data:
        # Check all slots in the tree
        for slot in tree['slots']:
            for rune in slot['runes']:
                if normalized_search in normalize_string(rune['name']):
                    return {'id': rune['id'], 'tree_id': tree['id'], 'name': rune['name']}
    
    # Check stat runes
    for stat_name, stat_id in STAT_RUNES.items():
        if normalized_search in normalize_string(stat_name):
            return {'id': stat_id, 'tree_id': None, 'name': stat_name}
    
    return None

def build_rune_page(rune_names):
    """Build a rune page from list of rune names using fuzzy matching"""
    if not rune_names or len(rune_names) == 0:
        return None
    
    selected_runes = []
    primary_tree = None
    secondary_tree = None
    
    # Process each rune name
    for i, rune_name in enumerate(rune_names):
        rune_info = find_rune_by_name(rune_name)
        if not rune_info:
            logger.info(f"Could not find rune: {rune_name}")
            continue
            
        selected_runes.append(rune_info['id'])
        
        # Determine primary and secondary trees based on first 6 runes
        if i < 4 and rune_info['tree_id'] and not primary_tree:
            primary_tree = rune_info['tree_id']
        elif i >= 4 and i < 6 and rune_info['tree_id'] and not secondary_tree:
            secondary_tree = rune_info['tree_id']
    
    if not primary_tree:
        logger.info("Could not determine primary rune tree")
        return None
    
    # Build the rune page data structure
    rune_page = {
        'name': 'AutoPick Runes',
        'primaryStyleId': primary_tree,
        'subStyleId': secondary_tree or 8000,  # Default to Precision if no secondary
        'selectedPerkIds': selected_runes,
        'current': True
    }
    
    return rune_page

DEFAULT_SPELLS = {
    'TOP': ['flash', 'teleport'],
    'JUNGLE': ['flash', 'smite'],
    'MIDDLE': ['flash', 'ignite'],
    'BOTTOM': ['flash', 'heal'],
    'UTILITY': ['flash', 'exhaust']
}

def get_role_champions(assigned_position, config):
    """Get champion list for assigned role with configurable fallback.

    Config uses layouts+roles format:
      layouts: {id: {champion, spells, runes}}
      roles: {role: [layout_ids]}
      fallback: {mode, layout_id}
    """
    role_mapping = {
        'TOP': 'top',
        'JUNGLE': 'jungle',
        'MIDDLE': 'mid',
        'BOTTOM': 'bot',
        'UTILITY': 'utility'
    }

    role_key = role_mapping.get(assigned_position, 'mid')
    layouts = config.get("layouts", {})
    roles = config.get("roles", {})
    fallback = config.get("fallback", {"mode": "random_default", "layout_id": ""})

    # Get layout IDs for this role
    role_ids = roles.get(role_key, [])
    if role_ids:
        # Resolve layout IDs to actual layout dicts
        result = []
        for lid in role_ids:
            layout = layouts.get(lid)
            if layout:
                result.append(layout)
        if result:
            return result

    # No layouts for this role - use fallback
    fallback_mode = fallback.get('mode', 'random_default')

    if fallback_mode == 'dodge':
        return []

    if fallback_mode == 'fallback_layout':
        fb_lid = fallback.get('layout_id', '')
        if fb_lid and fb_lid in layouts:
            return [layouts[fb_lid]]

    # Default: random champion + default runes
    return [{'champion': '__RANDOM__', 'spells': [], 'runes': []}]

async def set_recommended_runes(connection, champion_id, position):
    """Try to set recommended runes from the LCU for a champion"""
    try:
        pages_response = await request_lcu(connection, 'get', '/lol-perks/v1/recommended-pages')
        if hasattr(pages_response, 'json'):
            pages = await pages_response.json()
        else:
            pages = pages_response

        if not isinstance(pages, list) or not pages:
            return

        # Find page matching champion and position
        best_page = None
        for page in pages:
            if page.get('championId') == champion_id:
                if page.get('position', '').upper() == position:
                    best_page = page
                    break
                elif not best_page:
                    best_page = page

        if not best_page and pages:
            best_page = pages[0]

        if best_page:
            rune_page = {
                'name': 'AutoPick Runes',
                'primaryStyleId': best_page.get('primaryPerkStyleId', best_page.get('primaryStyleId')),
                'subStyleId': best_page.get('secondaryPerkStyleId', best_page.get('subStyleId')),
                'selectedPerkIds': best_page.get('perkIds', best_page.get('selectedPerkIds', [])),
                'current': True
            }

            current_pages = await request_lcu(connection, 'get', '/lol-perks/v1/pages')
            if hasattr(current_pages, 'json'):
                current_pages = await current_pages.json()

            for page in current_pages:
                if page.get('name') == 'AutoPick Runes' and page.get('isDeletable', True):
                    await request_lcu(connection, 'delete', f'/lol-perks/v1/pages/{page["id"]}')
                    break

            await request_lcu(connection, 'post', '/lol-perks/v1/pages', data=rune_page)
            logger.info(f"Set recommended runes for champion {champion_id}")
    except Exception as e:
        logger.info(f"Could not set recommended runes: {str(e)}")

async def get_owned_champion_ids(connection):
    """Use inventory ownership flags when the shortcut endpoint is unavailable."""
    try:
        champs = await get_lcu_json(connection, '/lol-champions/v1/owned-champions-minimal')
        if isinstance(champs, list):
            return {c['id'] for c in champs if c.get('id')}
        logger.info('Owned-champions shortcut unavailable; trying summoner inventory')
        summoner = await get_lcu_json(connection, '/lol-summoner/v1/current-summoner')
        if isinstance(summoner, dict) and summoner.get('summonerId'):
            champs = await get_lcu_json(connection,
                f"/lol-champions/v1/inventories/{summoner['summonerId']}/champions-minimal")
            if isinstance(champs, list):
                return {c['id'] for c in champs
                        if c.get('id') and c.get('ownership', {}).get('owned')}
    except Exception as e:
        logger.info(f"Failed to fetch owned champions: {str(e)}")
    return None


async def get_lcu_json(connection, path):
    try:
        response = await request_lcu(connection, 'get', path)
        if not 200 <= response.status < 300:
            return None
        return await response.json()
    except Exception:
        logger.debug('Could not read LCU JSON for %s', path, exc_info=True)
        return None


async def verified_pick(connection, action, champion_id, completed):
    """True = confirmed, False = rejected, None = uncertain/turn ended; stop picking."""
    session = await get_lcu_json(connection, '/lol-champ-select/v1/session')
    if not isinstance(session, dict):
        return None
    fresh = next((a for group in session.get('actions', []) for a in group
                  if a['id'] == action['id'] and a['actorCellId'] == action['actorCellId']
                  and a['type'] == 'pick'), None)
    if fresh is None or fresh.get('completed') or (completed and not fresh.get('isInProgress')):
        logger.info('Skipping pick: action %s is gone, completed, or no longer active', action['id'])
        return None
    logger.info('Attempting %s action=%s champion=%s',
                'lock-in' if completed else 'hover', action['id'], champion_id)
    try:
        response = await request_lcu(connection, 'patch',
            f"/lol-champ-select/v1/session/actions/{action['id']}",
            data={'championId': champion_id, 'completed': completed})
        if not 200 <= response.status < 300:
            logger.info(f"LCU rejected champion {champion_id} (HTTP {response.status}): {await response.text()}")
            return False
    except Exception as e:
        # A lost response does not prove the write failed. Read back before deciding.
        logger.info(f"Pick request interrupted; checking client state: {e}")

    current = None
    for attempt in range(4):
        if attempt:
            await asyncio.sleep(0.2)
        session = await get_lcu_json(connection, '/lol-champ-select/v1/session')
        if not isinstance(session, dict):
            current = None
            continue
        current = next((a for group in session.get('actions', []) for a in group
                        if a['id'] == action['id'] and a['actorCellId'] == action['actorCellId']
                        and a['type'] == 'pick'), None)
        logger.debug('Pick verification attempt=%s action=%s expected_champion=%s lock=%s state=%s',
                     attempt + 1, action['id'], champion_id, completed, current)
        if current is None:
            return None
        if current.get('championId') == champion_id and (not completed or current.get('completed')):
            return True
        if current.get('completed') or (completed and not current.get('isInProgress')):
            return None
    if current is None:
        logger.info('Cannot verify pick; waiting for a fresh champion-select update')
        return None
    logger.info(f"Client did not confirm champion {champion_id}; trying next candidate")
    return False

@connector.ready
async def connect(connection):
    global champions_map, runes_data, owned_champion_ids, have_i_prepicked
    have_i_prepicked = False
    logger.info('League client connected; loading champion and rune data')
    champions_map = await get_champions_map()
    runes_data = await get_runes_data()
    await load_stat_runes()
    owned_champion_ids = await get_owned_champion_ids(connection)
    logger.info(f"Owned champions: {len(owned_champion_ids) if owned_champion_ids is not None else 'unknown; will verify picks in champion select'}")

@connector.ws.register('/lol-matchmaking/v1/ready-check', event_types=('UPDATE',))
async def ready_check_changed(connection, event):
    global have_i_prepicked
    if event.data['state'] == 'InProgress' and event.data['playerResponse'] == 'None':
        await request_lcu(connection, 'post', '/lol-matchmaking/v1/ready-check/accept', data={})
        # Reset prepick status when accepting a new queue
        have_i_prepicked = False
        logger.info("Queue accepted, reset prepick status")


@connector.ws.register('/lol-champ-select/v1/session', event_types=('CREATE', 'UPDATE', 'DELETE'))
async def champ_select_changed(connection, event):
    global have_i_prepicked, have_i_dodged
    # Websocket callbacks can overlap; queued events must never act on stale actions.
    async with champ_select_lock:
        logger.debug('Champion-select event=%s', event.type)
        if event.type.upper() == 'DELETE':
            have_i_prepicked = have_i_dodged = False
            return
        if event.type.upper() == 'CREATE':
            have_i_prepicked = have_i_dodged = False
        session = await get_lcu_json(connection, '/lol-champ-select/v1/session')
        if isinstance(session, dict):
            try:
                await handle_champ_select(connection, session)
            except Exception:
                logger.exception('Champion-select handler failed; waiting for next update')


def pick_candidates(position, config, pickable, unavailable):
    entries = list(get_role_champions(position, config))
    fallback = config.get('fallback', {})
    layout = config.get('layouts', {}).get(fallback.get('layout_id'))
    if fallback.get('mode') == 'dodge':
        pass
    elif fallback.get('mode') == 'fallback_layout' and layout:
        entries.append(layout)
    else:
        entries.append({'champion': '__RANDOM__', 'spells': [], 'runes': []})
    seen = set()
    for entry in entries:
        data = parse_pick_entry(entry).copy()
        is_random = data['champion'] == '__RANDOM__'
        if is_random:
            names = [name for name, cid in champions_map.items()
                     if cid not in unavailable and cid not in seen
                     and (pickable is None or cid in pickable)]
            random.shuffle(names)
            names = names[:5]
        else:
            names = [data['champion']]
        for name in names:
            cid = champions_map.get(name)
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if cid in unavailable or (pickable is not None and cid not in pickable):
                logger.info(f'{name} is not pickable, trying next candidate')
                continue
            candidate = dict(data, champion=name)
            if is_random:
                candidate.update(spells=DEFAULT_SPELLS.get(position, ['flash', 'ignite']), runes=[])
            yield cid, candidate, is_random


# Dodge endpoints, newest first. The legacy LCDS quitV2 invoke is kept last for older clients;
# modern clients reject it (community reports: Snooze-Manager PR #21, lcu-driver issue #23).
DODGE_PATHS = [
    '/lol-lobby-team-builder/champ-select/v1/session/quit',
    '/lol-gameflow/v1/session/dodge',
    '/lol-login/v1/session/invoke?destination=lcdsServiceProxy&method=call'
    '&args=["","teambuilder-draft","quitV2",""]',
]


async def dodge(connection):
    """Leave champion select. True once any dodge endpoint accepts the request."""
    for path in DODGE_PATHS:
        try:
            response = await request_lcu(connection, 'post', path)
        except Exception as e:
            logger.info(f'Dodge request {path} failed: {e}')
            continue
        if 200 <= response.status < 300:
            logger.info(f'Dodged champion select via {path.split("?")[0]}')
            return True
        logger.info(f'Dodge request {path.split("?")[0]} rejected (HTTP {response.status})')
    logger.info('All dodge requests were rejected; staying in champion select')
    return False


async def handle_champ_select(connection, session):
    global have_i_prepicked, have_i_dodged
    try:
        config = load_config()
    except Exception as e:
        logger.info(f'Config reload failed: {e}')
        return
    cell = session['localPlayerCellId']
    player = next((p for p in session['myTeam'] if p['cellId'] == cell), None)
    if player is None:
        return
    position = (player.get('assignedPosition') or '').upper()
    lobby_phase = session['timer']['phase']
    actions = [a for group in session['actions'] for a in group]
    logger.debug('Champion-select phase=%s cell=%s position=%s actions=%s',
                 lobby_phase, cell, position, actions)
    active = next((a for a in actions if a['actorCellId'] == cell
                   and a['isInProgress'] and not a['completed']), None)
    if active and active['type'] == 'ban' and lobby_phase == 'BAN_PICK':
        for name in config.get('bans', []):
            cid = champions_map.get(name)
            if not cid:
                continue
            response = await request_lcu(connection, 'patch',
                f"/lol-champ-select/v1/session/actions/{active['id']}",
                data={'championId': cid, 'completed': True})
            if 200 <= response.status < 300:
                logger.info(f'Successfully banned {name}')
                break

    locking = bool(active and active['type'] == 'pick' and lobby_phase == 'BAN_PICK')
    planning = lobby_phase == 'PLANNING' and not have_i_prepicked
    if not locking and not planning:
        return
    action = active if locking else next((a for a in actions
        if a['actorCellId'] == cell and a['type'] == 'pick' and not a['completed']), None)
    if action is None:
        return
    ids = await get_lcu_json(connection, '/lol-champ-select/v1/pickable-champion-ids')
    pickable = set(ids) if isinstance(ids, list) else None
    logger.debug('Pick eligibility ids=%s configured_layouts=%s fallback=%s',
                 sorted(pickable) if pickable is not None else 'unknown',
                 get_role_champions(position, config), config.get('fallback'))
    # Ownership alone excludes free rotation and other temporary/queue unlocks.
    # When eligibility is unavailable, verify each attempted pick against session state.
    unavailable = {a['championId'] for a in actions if a['completed']
                   and a['type'] in ('ban', 'pick') and a['championId']}
    for cid, data, is_random in pick_candidates(position, config, pickable, unavailable):
        result = await verified_pick(connection, action, cid, locking)
        if result is None:
            return
        if not result:
            continue
        if planning:
            have_i_prepicked = True
        verb = 'Successfully picked' if locking else 'Pre-picked'
        logger.info(f"{verb} {data['champion']} for {position} (confirmed by client)")
        if data['spells']:
            await set_summoner_spells(connection, data['spells'])
        if data['runes']:
            await set_runes(connection, data['runes'])
        elif is_random and locking:
            await set_recommended_runes(connection, cid, position)
        return
    logger.info(f'No confirmed pick for {position}; configured candidates exhausted')
    # Only dodge on our actual pick turn: during planning, bans and trades can still change.
    if locking and config.get('fallback', {}).get('mode') == 'dodge' and not have_i_dodged:
        have_i_dodged = await dodge(connection)


def parse_pick_entry(pick_entry):
    """Parse a pick entry that can be either a string or dict with champion, spells, and runes"""
    if isinstance(pick_entry, str):
        return {'champion': pick_entry, 'spells': [], 'runes': []}
    elif isinstance(pick_entry, dict):
        champion = pick_entry.get('champion', '')
        spells = pick_entry.get('spells', [])
        runes = pick_entry.get('runes', [])
        # Normalize spell names to lowercase
        normalized_spells = [spell.lower() for spell in spells] if spells else []
        return {'champion': champion, 'spells': normalized_spells, 'runes': runes}
    else:
        return {'champion': '', 'spells': [], 'runes': []}

async def set_summoner_spells(connection, spells):
    """Set summoner spells using the my-selection endpoint"""
    if not spells or len(spells) == 0:
        return
    
    try:
        spell_ids = []
        for spell in spells:
            spell_id = SUMMONER_SPELLS.get(spell.lower())
            if spell_id:
                spell_ids.append(spell_id)
            else:
                logger.info(f"Unknown summoner spell: {spell}")
        
        if len(spell_ids) == 1:
            # Only one spell specified, set it as spell1, keep spell2 unchanged
            data = {"spell1Id": spell_ids[0]}
        elif len(spell_ids) >= 2:
            # Two spells specified
            data = {"spell1Id": spell_ids[0], "spell2Id": spell_ids[1]}
        else:
            return
        
        await request_lcu(connection, 'patch', '/lol-champ-select/v1/session/my-selection', data=data)
        spell_names = [spell for spell in spells if spell.lower() in SUMMONER_SPELLS]
        logger.info(f"Set summoner spells: {', '.join(spell_names)}")
        
    except Exception as e:
        logger.info(f"Failed to set summoner spells {spells}: {str(e)}")
        logger.info(f"Full error: {traceback.format_exc()}")

async def set_runes(connection, rune_names):
    """Set runes by creating/replacing a rune page"""
    if not rune_names or len(rune_names) == 0:
        return
    
    try:
        # Build rune page from names
        rune_page_data = build_rune_page(rune_names)
        if not rune_page_data:
            logger.info("Failed to build rune page")
            return
        
        # Get current rune pages to find one to replace
        pages_response = await request_lcu(connection, 'get', '/lol-perks/v1/pages')
        if hasattr(pages_response, 'json'):
            current_pages = await pages_response.json()
        else:
            current_pages = pages_response
        
        # Delete the oldest editable page if we have too many, or find an AutoPick page to replace
        page_to_replace = None
        for page in current_pages:
            if not page.get('isDeletable', True):
                continue
            if page.get('name') == 'AutoPick Runes':
                page_to_replace = page
                break
        
        # If no AutoPick page found, replace oldest editable page
        if not page_to_replace:
            editable_pages = [p for p in current_pages if p.get('isDeletable', True)]
            if editable_pages:
                page_to_replace = editable_pages[0]  # Replace first editable page
        
        # Delete the page to replace
        if page_to_replace:
            await request_lcu(connection, 'delete', f'/lol-perks/v1/pages/{page_to_replace["id"]}')
        
        # Create new rune page
        await request_lcu(connection, 'post', '/lol-perks/v1/pages', data=rune_page_data)
        logger.info(f"Set runes: {rune_page_data['name']}")
        
    except Exception as e:
        logger.info(f"Failed to set runes: {str(e)}")
        logger.info(f"Full error: {traceback.format_exc()}")

@connector.close
async def disconnect(_):
    logger.info('The client has been closed!')


if __name__ == '__main__':
    connector.start()
