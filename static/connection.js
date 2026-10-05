/* The website only speaks LoLQ's narrow local API, never the League API. */
const LoLQ = (() => {
  const localEditor = ['localhost', '127.0.0.1'].includes(location.hostname);
  const legacy = localEditor && location.port !== '17653';
  const base = localEditor ? '' : 'http://127.0.0.1:17653';
  let token = '', connected = false, busy = false, initialize, timer;
  let ready = false;

  async function api(path, options = {}) {
    const response = await fetch(base + path, {
      ...options,
      mode: 'cors', cache: 'no-store', credentials: 'omit',
      targetAddressSpace: 'loopback',
      signal: options.signal || AbortSignal.timeout(8000),
      headers: { 'X-LoLQ-Client': 'web', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers }
    });
    if (response.status === 401) { token = ''; connected = false; }
    return response;
  }

  function setup(message) {
    document.getElementById('setup').classList.remove('hidden');
    document.getElementById('setup-status').textContent = message;
    document.getElementById('app').inert = true;
    document.getElementById('loading').classList.add('hidden');
    if (ready) document.getElementById('setup-title').textContent = 'Let’s reconnect.';
  }

  function describe(status) {
    if (!status.worker) return 'Starting LoLQ…';
    if (!status.enabled) return status.connected ? 'League connected · Automation paused' : 'Automation paused · Waiting for League';
    if (!status.connected) return 'Ready · Open League to get started';
    const phases = { None: 'Ready for your next queue', Lobby: 'In lobby', Matchmaking: 'Finding a match',
      ReadyCheck: 'Accepting your match', ChampSelect: 'Taking care of champion select',
      InProgress: 'In game · Enjoy your match', EndOfGame: 'Ready for your next game',
      Reconnect: 'Reconnect to your match' };
    return phases[status.phase] || 'League connected';
  }

  async function connect() {
    if (busy || legacy) return;
    busy = true;
    try {
      if (!token) {
        const response = await api('/api/session');
        if (!response.ok) throw new Error('connection');
        const session = await response.json();
        if (session.protocol !== 1 || typeof session.token !== 'string') throw new Error('version');
        token = session.token;
      }
      const response = await api('/api/status');
      if (!response.ok) throw new Error('connection');
      const status = await response.json();
      if (status.app !== 'lolq') throw new Error('connection');
      if (!connected) {
        connected = true;
        document.getElementById('loading').classList.remove('hidden');
        if (ready && savedRevision !== saveRevision) {
          document.getElementById('loading').classList.add('hidden');
          toast('Reconnected. Retrying your changes.');
          await saveConfig();
        } else {
          await initialize();
          ready = true;
        }
      }
      document.getElementById('setup').classList.add('hidden');
      document.getElementById('app').inert = false;
      document.getElementById('connection-status').textContent = describe(status);
      if (state.config && !saving && savedRevision === saveRevision) {
        state.config.enabled = status.enabled;
        document.getElementById('automation-enabled').checked = status.enabled;
      }
      document.getElementById('connector-version').textContent = `LoLQ ${status.version}`;
      if (window.lolqRelease && window.lolqRelease.version !== status.version) {
        document.getElementById('update-link').classList.remove('hidden');
      }
    } catch (error) {
      connected = false;
      token = '';
      setup('Install LoLQ, then allow this page to connect to apps on your device when your browser asks.');
    } finally {
      busy = false;
    }
  }

  function start(init) {
    initialize = init;
    document.getElementById('connect-button').addEventListener('click', connect);
    document.getElementById('open-connector').addEventListener('click', () => {
      document.getElementById('setup-status').textContent = 'Open LoLQ in the browser prompt. This page will connect automatically.';
      setTimeout(connect, 1000);
    });
    document.getElementById('download-setup').addEventListener('click', () => {
      document.getElementById('setup-status').textContent = 'Open LoLQ-Setup.exe from your downloads. When setup finishes, this page connects automatically.';
    });
    fetch('release.json', { cache: 'no-store' }).then(r => r.json()).then(release => {
      window.lolqRelease = release;
      document.getElementById('setup-version').textContent = `Windows 10 / 11 · Version ${release.version}`;
    }).catch(() => {});
    if (legacy) {
      document.getElementById('setup').classList.add('hidden');
      document.getElementById('app').inert = false;
      document.getElementById('connection-status').textContent = 'Local editor · Keep the autopicker running';
      init();
      return;
    }
    setup('Everything you need, in one small install. Your settings and League connection stay on this PC.');
    connect();
    timer = setInterval(connect, 3000);
    window.addEventListener('pagehide', () => clearInterval(timer));
    window.addEventListener('pageshow', e => { if (e.persisted) { connect(); timer = setInterval(connect, 3000); } });
  }
  return { api, start };
})();
