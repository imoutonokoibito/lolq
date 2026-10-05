// LoLQ Config Editor - Layouts-first architecture

const ROLES = ['top', 'jungle', 'mid', 'bot', 'utility'];
const ROLE_LABELS = { top: 'Top', jungle: 'Jungle', mid: 'Mid', bot: 'Bot', utility: 'Support' };
const ROLE_SHORT = ROLE_LABELS;

// Hardcoded fallback for spell key mapping (used if DDragon summoner.json fails)
const SPELL_KEYS_FALLBACK = {
  flash: 'SummonerFlash', ignite: 'SummonerDot', smite: 'SummonerSmite',
  teleport: 'SummonerTeleport', heal: 'SummonerHeal', exhaust: 'SummonerExhaust',
  barrier: 'SummonerBarrier', cleanse: 'SummonerBoost', ghost: 'SummonerHaste',
  clarity: 'SummonerMana', mark: 'SummonerSnowball'
};

const CDRAGON_BASE = 'https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default';

const STAT_SHARDS = [
  [{ id: 5008, name: 'Adaptive Force', cfg: 'adaptive force', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsadaptiveforceicon.png` },
   { id: 5005, name: 'Attack Speed', cfg: 'attack speed', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsattackspeedicon.png` },
   { id: 5007, name: 'Ability Haste', cfg: 'ability haste', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodscdrscalingicon.png` }],
  [{ id: 5008, name: 'Adaptive Force', cfg: 'adaptive force', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsadaptiveforceicon.png` },
   { id: 5010, name: 'Movement Speed', cfg: 'movement speed', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodsmovementspeedicon.png` },
   { id: 5001, name: 'Health Scaling', cfg: 'health scaling', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthplusicon.png` }],
  [{ id: 5011, name: 'Health', cfg: 'health', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthscalingicon.png` },
   { id: 5013, name: 'Tenacity', cfg: 'tenacity', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodstenacityicon.png` },
   { id: 5001, name: 'Health Scaling', cfg: 'health scaling', icon: `${CDRAGON_BASE}/v1/perk-images/statmods/statmodshealthplusicon.png` }]
];

// State
const state = {
  config: null, // { bans, layouts, roles, fallback }
  champions: {},
  championList: [],
  spellKeys: {}, // name -> DDragon key (e.g. "flash" -> "SummonerFlash")
  spellList: [],  // available spell names
  runes: [],
  ddVersion: ''
};

// Rune picker state
let runePicker = {
  primaryTreeId: null, secondaryTreeId: null,
  primaryRunes: [null, null, null, null],
  secondarySlots: {},
  statShards: [null, null, null],
  callback: null
};

// ===================== HELPERS =====================

function champIcon(name) {
  const c = state.champions[name];
  return c ? `https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/img/champion/${c.id}.png` : '';
}

function spellIcon(name) {
  const n = name?.toLowerCase();
  const key = state.spellKeys[n] || SPELL_KEYS_FALLBACK[n];
  return key ? `https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/img/spell/${key}.png` : '';
}

function runeIcon(path) {
  return `https://ddragon.leagueoflegends.com/cdn/img/${path}`;
}

function norm(s) {
  return (s || '').replace(/[^a-z0-9]/gi, '').toLowerCase();
}

function runeToConfig(name) {
  return name.toLowerCase().replace(/[^a-z ]/g, '').replace(/\s+/g, ' ').trim();
}

function findRuneInData(name) {
  const n = norm(name);
  if (!n) return null;
  for (const tree of state.runes) {
    for (const slot of tree.slots) {
      for (const rune of slot.runes) {
        if (norm(rune.name) === n) return { ...rune, treeId: tree.id };
      }
    }
  }
  for (const tree of state.runes) {
    for (const slot of tree.slots) {
      for (const rune of slot.runes) {
        if (norm(rune.name).includes(n) || n.includes(norm(rune.name)))
          return { ...rune, treeId: tree.id };
      }
    }
  }
  return null;
}

function nextLayoutId() {
  const ids = Object.keys(state.config.layouts).map(Number).filter(n => !isNaN(n));
  return String((ids.length ? Math.max(...ids) : 0) + 1);
}

function esc(s) {
  return (s || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.remove('hidden');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 2000);
}

// ===================== DATA LOADING =====================

async function loadDDragon() {
  const vers = await fetch('https://ddragon.leagueoflegends.com/api/versions.json').then(r => r.json());
  state.ddVersion = vers[0];

  // Fetch champions, runes, and spells in parallel (spells can fail gracefully)
  const [cData, rData, sData] = await Promise.all([
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/champion.json`).then(r => r.json()),
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/runesReforged.json`).then(r => r.json()),
    fetch(`https://ddragon.leagueoflegends.com/cdn/${state.ddVersion}/data/en_US/summoner.json`).then(r => r.json()).catch(() => null)
  ]);

  // Champions
  state.champions = {};
  state.championList = [];
  for (const [id, c] of Object.entries(cData.data)) {
    state.champions[c.name] = { id, key: c.key, name: c.name };
    state.championList.push(c.name);
  }
  state.championList.sort();
  state.runes = rData;

  // Summoner spells - build name->key map from API, skip arena/URF/placeholder spells
  state.spellKeys = {};
  state.spellList = [];
  if (sData?.data) {
    const skip = /Cherry|Poro|URF|Placeholder/i;
    for (const [id, s] of Object.entries(sData.data)) {
      if (skip.test(id)) continue;
      const name = s.name.toLowerCase();
      if (!state.spellKeys[name]) {
        state.spellKeys[name] = id;
        state.spellList.push(name);
      }
    }
  }
  // Fallback if API returned nothing useful
  if (state.spellList.length === 0) {
    state.spellKeys = { ...SPELL_KEYS_FALLBACK };
    state.spellList = Object.keys(SPELL_KEYS_FALLBACK);
  }
}

async function loadConfig() {
  const response = await LoLQ.api('/api/config');
  if (!response.ok) throw new Error('Could not load your configuration');
  state.config = await response.json();
  if (!state.config.layouts) state.config.layouts = {};
  if (!state.config.roles) {
    state.config.roles = {};
    ROLES.forEach(r => state.config.roles[r] = []);
  }
  ROLES.forEach(r => { if (!state.config.roles[r]) state.config.roles[r] = []; });
  if (!state.config.bans) state.config.bans = [];
  if (!state.config.fallback) state.config.fallback = { mode: 'random_default', layout_id: '' };
  const before = JSON.stringify(state.config.fallback);
  normalizeFallback();
  // Persist the repair so the bot uses what the editor shows
  if (JSON.stringify(state.config.fallback) !== before) autoSave();
}

// "Use layout" must always point at an existing layout; with none left, fall back to random.
function normalizeFallback() {
  const fb = state.config.fallback;
  if (fb.mode !== 'fallback_layout') {
    fb.layout_id = '';
    return;
  }
  if (!state.config.layouts[fb.layout_id]) {
    const first = Object.keys(state.config.layouts)[0];
    if (first) {
      fb.layout_id = first;
    } else {
      fb.mode = 'random_default';
      fb.layout_id = '';
    }
  }
}

let saveRevision = 0;
let savedRevision = 0;
let saving = false;
let _autoSaveTimer = null;

function saveStatus(message, kind = '') {
  const el = document.getElementById('save-status');
  el.textContent = message;
  el.className = `save-status ${kind}`;
  document.getElementById('retry-save').classList.toggle('hidden', kind !== 'err');
}

async function saveConfig() {
  if (saving) return;
  saving = true;
  saveStatus('Saving…');
  try {
    // Serialize writes, then save again if editing continued during the request.
    do {
      const revision = saveRevision;
      const response = await LoLQ.api('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(state.config)
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const result = await response.json();
      if (!result.ok) throw new Error('Save not acknowledged');
      savedRevision = revision;
    } while (savedRevision !== saveRevision);
    saveStatus('All changes saved', 'ok');
  } catch (e) {
    saveStatus('Changes not saved', 'err');
  } finally {
    saving = false;
  }
}

function autoSave() {
  saveRevision++;
  saveStatus('Saving…');
  clearTimeout(_autoSaveTimer);
  _autoSaveTimer = setTimeout(saveConfig, 150);
}

window.addEventListener('beforeunload', e => {
  if (savedRevision !== saveRevision) { e.preventDefault(); e.returnValue = ''; }
});

// ===================== RENDERING =====================

function render() {
  renderBans();
  renderPool();
  renderRoles();
  renderFallback();
}

function renderBans() {
  const el = document.getElementById('bans-section');
  const bans = state.config.bans;
  el.innerHTML = `
    <div class="section-header"><div><h2 id="bans-title">Your bans</h2><p>LoLQ tries these in order, from left to right.</p></div></div>
    <div id="bans-list" class="bans-list">
      ${bans.map((b, i) => `
        <div class="ban-item" data-index="${i}">
          <img src="${champIcon(b)}" alt="${esc(b)}" onerror="this.style.display='none'">
          <span>${b}</span>
          <button class="order-button" aria-label="Move ${esc(b)} earlier" onclick="moveBan(${i},-1)" ${i === 0 ? 'disabled' : ''}>‹</button>
          <button class="order-button" aria-label="Move ${esc(b)} later" onclick="moveBan(${i},1)" ${i === bans.length - 1 ? 'disabled' : ''}>›</button>
          <button class="btn-x" aria-label="Remove ban ${esc(b)}" onclick="removeBan(${i})">&times;</button>
        </div>
      `).join('')}
    </div>
    <button class="btn-add" onclick="addBan()">＋ Add ban</button>
  `;
  if (window.Sortable) new Sortable(document.getElementById('bans-list'), {
    filter: 'button',
    preventOnFilter: false,
    animation: 150,
    draggable: '.ban-item',
    onEnd: e => {
      const item = state.config.bans.splice(e.oldIndex, 1)[0];
      state.config.bans.splice(e.newIndex, 0, item);
      renderBans();
      autoSave();
    }
  });
}

function renderPool() {
  const grid = document.getElementById('pool-grid');
  const layoutIds = Object.keys(state.config.layouts);
  if (layoutIds.length === 0) {
    grid.innerHTML = '<div class="empty-state"><h3>Start with a favorite.</h3><p>Choose your first champion with “Add champion” above.</p></div>';
    return;
  }
  grid.innerHTML = layoutIds.map(lid => {
    const layout = state.config.layouts[lid];
    const name = layout.champion || '???';
    const spells = layout.spells || [];
    const runes = layout.runes || [];

    let keystoneHtml = '';
    if (runes.length > 0) {
      const ks = findRuneInData(runes[0]);
      if (ks && ks.icon) {
        keystoneHtml = `<img src="${runeIcon(ks.icon)}" class="keystone-icon" title="${runes[0]}">`;
      }
    }

    const spellHtml = spells.map(s => `<img src="${spellIcon(s)}" class="spell-icon" title="${s}">`).join('');

    const roleBtns = ROLES.map(r => {
      const active = (state.config.roles[r] || []).includes(lid);
      return `<button class="pool-role-btn ${active ? 'active' : ''}" aria-pressed="${active}" onclick="toggleLayoutRole('${lid}','${r}')" title="${ROLE_LABELS[r]}">${ROLE_SHORT[r]}</button>`;
    }).join('');

    return `
      <div class="pool-card" data-layout-id="${lid}">
        <div class="pool-card-top">
          <button class="pool-card-icon" aria-label="Change ${esc(name)} champion" onclick="changeLayoutChampion('${lid}')">
            <img src="${champIcon(name)}" alt="" onerror="this.style.opacity=0.3">
          </button>
          <div class="pool-card-info">
            <button class="pool-card-name" onclick="changeLayoutChampion('${lid}')">${name}</button>
            <p class="pool-card-subtitle">${ROLES.filter(r => state.config.roles[r].includes(lid)).map(r => ROLE_LABELS[r]).join(' · ') || 'Choose a role below'}</p>
          </div>
          <button class="btn-x btn-danger" aria-label="Remove ${esc(name)} layout" onclick="removeLayout('${lid}')">×</button>
        </div>
        <div class="pool-card-details">
          <button class="loadout-button" aria-label="Edit ${esc(name)} spells" onclick="editLayoutSpells('${lid}')">${spellHtml}<span>${spells.length ? 'Spells' : 'Default spells'}</span></button>
          <button class="loadout-button" aria-label="Edit ${esc(name)} runes" onclick="editLayoutRunes('${lid}')">${keystoneHtml}<span>${runes.length ? 'Runes' : 'Recommended'}</span></button>
        </div>
        <div class="pool-card-bottom" role="group" aria-label="Roles for ${esc(name)}">${roleBtns}</div>
      </div>
    `;
  }).join('');
}

function renderRoles() {
  const grid = document.getElementById('roles-grid');
  grid.innerHTML = ROLES.map(role => {
    const ids = state.config.roles[role] || [];
    const items = ids.map((lid, i) => {
      const layout = state.config.layouts[lid];
      if (!layout) return '';
      const name = layout.champion || '???';

      return `
        <div class="role-item" data-lid="${lid}">
          <span class="role-item-num">${i + 1}</span>
          <div class="role-item-icon"><img src="${champIcon(name)}" alt="${esc(name)}" onerror="this.style.opacity=0.3"></div>
          <span class="role-item-name">${name}</span>
          <div class="role-item-controls">
            <button class="order-button" aria-label="Move ${esc(name)} up in ${ROLE_LABELS[role]}" onclick="moveInRole('${role}',${i},-1)" ${i === 0 ? 'disabled' : ''}>↑</button>
            <button class="order-button" aria-label="Move ${esc(name)} down in ${ROLE_LABELS[role]}" onclick="moveInRole('${role}',${i},1)" ${i === ids.length - 1 ? 'disabled' : ''}>↓</button>
            <button class="role-item-remove" aria-label="Remove ${esc(name)} from ${ROLE_LABELS[role]}" onclick="removeFromRole('${role}','${lid}')">×</button>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="role-column">
        <div class="role-column-header">${ROLE_LABELS[role]}<span class="role-count">${ids.length}</span></div>
        <div class="role-column-items" id="role-items-${role}">${items || '<p class="role-empty">Uses fallback</p>'}</div>
      </div>
    `;
  }).join('');

  // Setup SortableJS on each column
  ROLES.forEach(role => {
    const el = document.getElementById(`role-items-${role}`);
    if (el && window.Sortable) {
      new Sortable(el, {
        filter: 'button',
        preventOnFilter: false,
        animation: 150,
        draggable: '.role-item',
        group: { name: 'roles', pull: false, put: false },
        onEnd: e => {
          const ids = state.config.roles[role];
          const item = ids.splice(e.oldIndex, 1)[0];
          ids.splice(e.newIndex, 0, item);
          renderRoles();
          autoSave();
        }
      });
    }
  });
}

function renderFallback() {
  const el = document.getElementById('fallback-section');
  const fb = state.config.fallback;
  const layoutIds = Object.keys(state.config.layouts);
  const noLayouts = layoutIds.length === 0;

  const layoutOptions = layoutIds.map(lid => {
    const l = state.config.layouts[lid];
    const selected = fb.layout_id === lid ? 'selected' : '';
    return `<option value="${lid}" ${selected}>${l.champion || '???'}</option>`;
  }).join('');

  el.innerHTML = `
    <div class="section-header"><div><h2 id="fallback-title">When picks run out</h2><p>Used when your role has no available configured pick.</p></div></div>
    <div class="fallback-options">
      <label class="fallback-radio ${fb.mode === 'random_default' ? 'active' : ''}">
        <input type="radio" name="fb" value="random_default" onchange="setFallbackMode(this.value)" ${fb.mode === 'random_default' ? 'checked' : ''}>
        Random champion, default runes
      </label>
      <div class="fallback-radio ${fb.mode === 'fallback_layout' ? 'active' : ''} ${noLayouts ? 'disabled' : ''}">
        <label class="fallback-choice">
          <input type="radio" name="fb" value="fallback_layout" onchange="setFallbackMode(this.value)" ${fb.mode === 'fallback_layout' ? 'checked' : ''} ${noLayouts ? 'disabled' : ''}>
          Use a layout
        </label>
        ${noLayouts
          ? '<span class="text-muted">Add a champion first</span>'
          : `<select aria-label="Fallback layout" onchange="setFallbackLayout(this.value)">${layoutOptions}</select>`}
      </div>
      <label class="fallback-radio ${fb.mode === 'dodge' ? 'active' : ''}">
        <input type="radio" name="fb" value="dodge" onchange="setFallbackMode(this.value)" ${fb.mode === 'dodge' ? 'checked' : ''}>
        Dodge champion select
      </label>
    </div>
  `;
}

// ===================== HANDLERS =====================

function moveBan(index, direction) {
  const next = index + direction;
  const bans = state.config.bans;
  if (next < 0 || next >= bans.length) return;
  [bans[index], bans[next]] = [bans[next], bans[index]];
  renderBans();
  autoSave();
  document.querySelectorAll('.ban-item')[next]?.querySelector('.order-button:not(:disabled)')?.focus();
}

function moveInRole(role, index, direction) {
  const ids = state.config.roles[role];
  const next = index + direction;
  if (next < 0 || next >= ids.length) return;
  [ids[index], ids[next]] = [ids[next], ids[index]];
  renderRoles();
  autoSave();
  document.querySelectorAll(`#role-items-${role} .role-item`)[next]?.querySelector('.order-button:not(:disabled)')?.focus();
}

function removeBan(i) {
  state.config.bans.splice(i, 1);
  renderBans();
  autoSave();
}

function addBan() {
  openChampionPicker(name => {
    if (!state.config.bans.includes(name)) {
      state.config.bans.push(name);
      renderBans();
      autoSave();
    }
  });
}

function addLayout() {
  openChampionPicker(name => {
    const lid = nextLayoutId();
    state.config.layouts[lid] = { champion: name, spells: [], runes: [] };
    renderPool();
    renderFallback();
    autoSave();
  });
}

function removeLayout(lid) {
  delete state.config.layouts[lid];
  // Remove from all roles
  ROLES.forEach(r => {
    state.config.roles[r] = (state.config.roles[r] || []).filter(id => id !== lid);
  });
  // Re-point the fallback if it referenced this layout
  normalizeFallback();
  renderPool();
  renderRoles();
  renderFallback();
  autoSave();
}

function changeLayoutChampion(lid) {
  openChampionPicker(name => {
    state.config.layouts[lid].champion = name;
    renderPool();
    renderRoles();
    renderFallback();
    autoSave();
  });
}

function editLayoutSpells(lid) {
  const layout = state.config.layouts[lid];
  openSpellPicker(layout.spells || [], spells => {
    layout.spells = spells;
    renderPool();
    renderRoles();
    autoSave();
  });
}

function editLayoutRunes(lid) {
  const layout = state.config.layouts[lid];
  openRunePicker(layout.runes || [], runes => {
    layout.runes = runes;
    renderPool();
    renderRoles();
    autoSave();
  });
}

function toggleLayoutRole(lid, role) {
  const ids = state.config.roles[role];
  const idx = ids.indexOf(lid);
  if (idx >= 0) {
    ids.splice(idx, 1);
  } else {
    ids.push(lid);
  }
  renderPool();
  renderRoles();
  autoSave();
  document.querySelector(`[data-layout-id="${lid}"] [onclick="toggleLayoutRole('${lid}','${role}')"]`)?.focus();
}

function removeFromRole(role, lid) {
  const ids = state.config.roles[role];
  const idx = ids.indexOf(lid);
  if (idx >= 0) {
    ids.splice(idx, 1);
    renderPool();
    renderRoles();
    autoSave();
  }
}

function setFallbackMode(mode) {
  state.config.fallback.mode = mode;
  normalizeFallback();
  renderFallback();
  document.querySelector('input[name="fb"]:checked')?.focus();
  autoSave();
}

function setFallbackLayout(lid) {
  state.config.fallback.mode = 'fallback_layout';
  state.config.fallback.layout_id = lid;
  renderFallback();
  document.querySelector('[aria-label="Fallback layout"]')?.focus();
  autoSave();
}

// ===================== MODALS =====================

let modalOpener = null;
function openModal(html) {
  const overlay = document.getElementById('modal-overlay');
  const wasOpen = !overlay.classList.contains('hidden');
  const activeAction = wasOpen ? document.activeElement?.getAttribute('onclick') : null;
  if (!wasOpen) modalOpener = document.activeElement;
  document.getElementById('modal-content').innerHTML = html;
  document.querySelector('#modal-content h3')?.setAttribute('id', 'modal-title');
  overlay.classList.remove('hidden');
  document.getElementById('app').inert = true;
  document.body.style.overflow = 'hidden';
  const matched = activeAction && [...overlay.querySelectorAll('[onclick]')].find(el => el.getAttribute('onclick') === activeAction);
  (matched || overlay.querySelector('input') || overlay.querySelector('.modal-close')).focus();
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  closeModalForce();
}

function closeModalForce() {
  const overlay = document.getElementById('modal-overlay');
  if (overlay.classList.contains('hidden')) return;
  overlay.classList.add('hidden');
  document.getElementById('app').inert = false;
  document.body.style.overflow = '';
  const opener = modalOpener;
  const action = opener?.getAttribute('onclick');
  queueMicrotask(() => {
    const target = opener?.isConnected ? opener : [...document.querySelectorAll('#app [onclick]')].find(el => el.getAttribute('onclick') === action);
    target?.focus();
  });
}

// --- Champion Picker ---
function openChampionPicker(callback) {
  window._champCb = callback;
  openModal(`
    <div class="modal-header"><h3>Choose a champion</h3></div>
    <input type="text" id="champ-search" class="search-input" aria-label="Search champions" placeholder="Search champions…" oninput="filterChampions()">
    <div id="champ-grid" class="champ-grid">
      ${state.championList.map(name => `
        <button type="button" class="champ-option" onclick="pickChampion('${esc(name)}')">
          <img src="${champIcon(name)}" alt="${esc(name)}" loading="lazy">
          <span>${name}</span>
        </button>
      `).join('')}
    </div>
    <p id="champ-empty" class="text-muted hidden">No champions found. Try another name.</p>
  `);
}

function filterChampions() {
  const q = norm(document.getElementById('champ-search').value);
  document.querySelectorAll('.champ-option').forEach(el => {
    const name = norm(el.querySelector('span').textContent);
    el.style.display = name.includes(q) ? '' : 'none';
  });
  document.getElementById('champ-empty').classList.toggle('hidden', [...document.querySelectorAll('.champ-option')].some(el => el.style.display !== 'none'));
}

function pickChampion(name) {
  closeModalForce();
  window._champCb?.(name);
}

// --- Spell Picker ---
let _spellOrder = []; // ordered [spell1, spell2] for D, F

function openSpellPicker(current, callback) {
  window._spellCb = callback;
  _spellOrder = (current || []).map(s => s.toLowerCase()).slice(0, 2);
  renderSpellPicker();
}

function renderSpellPicker() {
  const slot = (i, label) => {
    const s = _spellOrder[i];
    if (s) {
      return `<div class="spell-slot">
        <span class="spell-slot-key">${label}</span>
        <div class="spell-slot-icon"><img src="${spellIcon(s)}" alt="${s}"></div>
        <span class="spell-slot-name">${s[0].toUpperCase() + s.slice(1)}</span>
      </div>`;
    }
    return `<div class="spell-slot">
      <span class="spell-slot-key">${label}</span>
      <div class="spell-slot-icon empty"></div>
      <span class="spell-slot-name text-muted">-</span>
    </div>`;
  };

  openModal(`
    <div class="modal-header">
      <h3>Summoner spells</h3>
      <p class="text-muted">Click spells in order: first click = D, second = F</p>
    </div>
    <div class="spell-order-preview">
      ${slot(0, 'D')}
      <span class="spell-order-arrow"></span>
      ${slot(1, 'F')}
    </div>
    <div id="spell-grid" class="spell-grid">
      ${state.spellList.map(s => {
        const idx = _spellOrder.indexOf(s);
        const cls = idx >= 0 ? 'selected' : '';
        return `
        <button type="button" class="spell-option ${cls}" aria-pressed="${idx >= 0}" onclick="toggleSpell('${s}')" data-spell="${s}">
          <img src="${spellIcon(s)}" alt="${s}">
          <span>${s[0].toUpperCase() + s.slice(1)}</span>
        </button>`;
      }).join('')}
    </div>
    <div class="modal-footer">
      <button class="btn-secondary" onclick="clearSpells()">Clear</button>
      <button class="btn-secondary" onclick="closeModalForce()">Cancel</button>
      <button class="btn-primary" onclick="applySpells()">Apply</button>
    </div>
  `);
}

function toggleSpell(spell) {
  const idx = _spellOrder.indexOf(spell);
  if (idx >= 0) {
    _spellOrder.splice(idx, 1);
  } else if (_spellOrder.length < 2) {
    _spellOrder.push(spell);
  } else {
    // Replace second slot
    _spellOrder[1] = spell;
  }
  renderSpellPicker();
}

function clearSpells() {
  _spellOrder = [];
  renderSpellPicker();
}

function applySpells() {
  closeModalForce();
  window._spellCb?.([..._spellOrder]);
}

// --- Rune Picker ---
function openRunePicker(currentRunes, callback) {
  runePicker = {
    primaryTreeId: null, secondaryTreeId: null,
    primaryRunes: [null, null, null, null],
    secondarySlots: {},
    statShards: [null, null, null],
    callback
  };

  if (currentRunes && currentRunes.length > 0) {
    for (let i = 0; i < Math.min(4, currentRunes.length); i++) {
      const found = findRuneInData(currentRunes[i]);
      if (found && found.treeId) {
        if (!runePicker.primaryTreeId) runePicker.primaryTreeId = found.treeId;
        runePicker.primaryRunes[i] = found.id;
      }
    }
    for (let i = 4; i < Math.min(6, currentRunes.length); i++) {
      const found = findRuneInData(currentRunes[i]);
      if (found && found.treeId) {
        if (!runePicker.secondaryTreeId) runePicker.secondaryTreeId = found.treeId;
        const tree = state.runes.find(t => t.id === found.treeId);
        if (tree) {
          for (let si = 1; si < tree.slots.length; si++) {
            if (tree.slots[si].runes.some(r => r.id === found.id)) {
              runePicker.secondarySlots[si] = found.id;
              break;
            }
          }
        }
      }
    }
    for (let i = 6; i < Math.min(9, currentRunes.length); i++) {
      const row = i - 6;
      const n = norm(currentRunes[i]);
      // Exact match only: substring matching broke here because "health" is
      // a substring of "healthscaling", so it matched before ever reaching
      // the real "health scaling" entry later in the row.
      const shard = STAT_SHARDS[row].find(s => norm(s.cfg) === n);
      if (shard) runePicker.statShards[row] = shard.id;
    }
  }

  renderRunePickerModal();
}

function renderRunePickerModal() {
  const primaryTree = state.runes.find(t => t.id === runePicker.primaryTreeId);
  const secondaryTree = state.runes.find(t => t.id === runePicker.secondaryTreeId);

  openModal(`
    <div class="modal-header"><h3>Choose your runes</h3><p class="text-muted">Choose a primary tree, then a secondary tree. Clear to use recommended runes.</p></div>
    <div class="rune-picker">
      <div class="rune-trees-select">
        ${state.runes.map(tree => {
          let cls = 'tree-icon';
          if (tree.id === runePicker.primaryTreeId) cls += ' primary-selected';
          else if (tree.id === runePicker.secondaryTreeId) cls += ' secondary-selected';
          return `<button type="button" class="${cls}" aria-label="${tree.name}${tree.id === runePicker.primaryTreeId ? ' (primary)' : tree.id === runePicker.secondaryTreeId ? ' (secondary)' : ''}" aria-pressed="${tree.id === runePicker.primaryTreeId || tree.id === runePicker.secondaryTreeId}" onclick="selectTree(${tree.id})" title="${tree.name}">
            <img src="${runeIcon(tree.icon)}" alt="${tree.name}">
            <span>${tree.name}</span>
          </button>`;
        }).join('')}
      </div>

      <div class="rune-columns">
        <div class="rune-column primary-column">
          <h4>${primaryTree ? primaryTree.name : 'Primary'}</h4>
          ${primaryTree ? primaryTree.slots.map((slot, si) => `
            <div class="rune-slot">
              ${slot.runes.map(rune => `
                <button type="button" class="rune-option ${si === 0 ? 'keystone' : ''} ${runePicker.primaryRunes[si] === rune.id ? 'selected' : ''}"
                     aria-pressed="${runePicker.primaryRunes[si] === rune.id}" onclick="selectPrimaryRune(${si},${rune.id})" aria-label="${rune.name}" title="${rune.name}">
                  <img src="${runeIcon(rune.icon)}" alt="${rune.name}">
                </button>
              `).join('')}
            </div>
          `).join('') : '<p class="text-muted" style="text-align:center;padding:20px">Click a tree above</p>'}
        </div>

        <div class="rune-column secondary-column">
          <h4>${secondaryTree ? secondaryTree.name : 'Secondary'}</h4>
          ${secondaryTree ? secondaryTree.slots.slice(1).map((slot, si) => {
            const idx = si + 1;
            return `<div class="rune-slot">
              ${slot.runes.map(rune => `
                <button type="button" class="rune-option ${runePicker.secondarySlots[idx] === rune.id ? 'selected' : ''}"
                     aria-pressed="${runePicker.secondarySlots[idx] === rune.id}" onclick="selectSecondaryRune(${idx},${rune.id})" aria-label="${rune.name}" title="${rune.name}">
                  <img src="${runeIcon(rune.icon)}" alt="${rune.name}">
                </button>
              `).join('')}
            </div>`;
          }).join('') : '<p class="text-muted" style="text-align:center;padding:20px">Click a different tree</p>'}
        </div>
      </div>

      <div class="stat-shards">
        <h4>Stat Shards</h4>
        ${STAT_SHARDS.map((row, ri) => `
          <div class="shard-row">
            ${row.map(shard => `
              <button type="button" class="shard-option ${runePicker.statShards[ri] === shard.id ? 'selected' : ''}"
                   onclick="selectStatShard(${ri},${shard.id})" aria-label="${shard.name}" aria-pressed="${runePicker.statShards[ri] === shard.id}" title="${shard.name}"><img src="${shard.icon}" class="shard-icon" alt="" onerror="this.style.display='none'"></button>
            `).join('')}
          </div>
        `).join('')}
      </div>
    </div>

    <div class="modal-footer">
      <button class="btn-secondary" onclick="clearRunes()">Clear</button>
      <button class="btn-secondary" onclick="closeModalForce()">Cancel</button>
      <button class="btn-primary" onclick="applyRunes()">Apply</button>
    </div>
  `);
}

function selectTree(treeId) {
  if (runePicker.primaryTreeId === treeId) {
    runePicker.primaryTreeId = null;
    runePicker.primaryRunes = [null, null, null, null];
    if (runePicker.secondaryTreeId) {
      runePicker.primaryTreeId = runePicker.secondaryTreeId;
      runePicker.secondaryTreeId = null;
      runePicker.secondarySlots = {};
    }
  } else if (runePicker.secondaryTreeId === treeId) {
    runePicker.secondaryTreeId = null;
    runePicker.secondarySlots = {};
  } else if (!runePicker.primaryTreeId) {
    runePicker.primaryTreeId = treeId;
    runePicker.primaryRunes = [null, null, null, null];
  } else if (!runePicker.secondaryTreeId) {
    runePicker.secondaryTreeId = treeId;
    runePicker.secondarySlots = {};
  } else {
    runePicker.secondaryTreeId = treeId;
    runePicker.secondarySlots = {};
  }
  renderRunePickerModal();
}

function selectPrimaryRune(slot, runeId) {
  runePicker.primaryRunes[slot] = runePicker.primaryRunes[slot] === runeId ? null : runeId;
  renderRunePickerModal();
}

function selectSecondaryRune(slot, runeId) {
  const slots = Object.keys(runePicker.secondarySlots).map(Number);
  if (slots.includes(slot)) {
    if (runePicker.secondarySlots[slot] === runeId) {
      delete runePicker.secondarySlots[slot];
    } else {
      runePicker.secondarySlots[slot] = runeId;
    }
  } else if (slots.length < 2) {
    runePicker.secondarySlots[slot] = runeId;
  } else {
    delete runePicker.secondarySlots[slots[0]];
    runePicker.secondarySlots[slot] = runeId;
  }
  renderRunePickerModal();
}

function selectStatShard(row, id) {
  runePicker.statShards[row] = runePicker.statShards[row] === id ? null : id;
  renderRunePickerModal();
}

function applyRunes() {
  const runes = [];
  const primaryTree = state.runes.find(t => t.id === runePicker.primaryTreeId);
  const secondaryTree = state.runes.find(t => t.id === runePicker.secondaryTreeId);

  if (primaryTree) {
    for (let i = 0; i < 4; i++) {
      const id = runePicker.primaryRunes[i];
      if (id) {
        const rune = primaryTree.slots[i].runes.find(r => r.id === id);
        if (rune) runes.push(runeToConfig(rune.name));
      }
    }
  }
  if (secondaryTree) {
    const sortedSlots = Object.keys(runePicker.secondarySlots).map(Number).sort();
    for (const si of sortedSlots) {
      const id = runePicker.secondarySlots[si];
      const rune = secondaryTree.slots[si].runes.find(r => r.id === id);
      if (rune) runes.push(runeToConfig(rune.name));
    }
  }
  for (let i = 0; i < 3; i++) {
    const id = runePicker.statShards[i];
    if (id) {
      const shard = STAT_SHARDS[i].find(s => s.id === id);
      if (shard) runes.push(shard.cfg);
    }
  }

  closeModalForce();
  runePicker.callback?.(runes);
}

function clearRunes() {
  closeModalForce();
  runePicker.callback?.([]);
}

// ===================== KEYBOARD =====================
document.addEventListener('keydown', e => {
  const overlay = document.getElementById('modal-overlay');
  if (overlay.classList.contains('hidden')) return;
  if (e.key === 'Escape') closeModalForce();
  if (e.key === 'Tab') {
    const focusable = [...overlay.querySelectorAll('button:not(:disabled), input, select, [tabindex="0"]')].filter(el => el.getClientRects().length);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
  }
});

function toggleAutomation(value) {
  state.config.enabled = value;
  autoSave();
}

// ===================== INIT =====================
async function init() {
  try {
    await Promise.all([loadDDragon(), loadConfig()]);
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
    document.getElementById('automation-enabled').checked = state.config.enabled !== false;
    render();
  } catch (e) {
    document.getElementById('loading').innerHTML =
      `<p>Couldn’t load your champions. Check your internet connection and try again.</p>
       <button onclick="location.reload()" class="btn-primary" style="margin-top:12px">Retry</button>`;
  }
}

LoLQ.start(init);
