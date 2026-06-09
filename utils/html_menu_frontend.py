"""Browser-based menu frontend served by the simulator."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


HTML_PAGE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Badminton Menu Frontend</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --panel: #ffffff;
      --text: #142033;
      --muted: #637083;
      --line: #d8dee9;
      --blue: #2563eb;
      --green: #15803d;
      --red: #dc2626;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 22px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { margin: 0; font-size: 20px; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 16px;
      padding: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      min-height: 120px;
    }
    section:has(details:not([open])) {
      min-height: 0;
      padding-top: 10px;
      padding-bottom: 10px;
    }
    h2 { margin: 0 0 12px; font-size: 16px; }
    label {
      display: block;
      margin: 10px 0 5px;
      font-size: 12px;
      color: var(--muted);
      font-weight: 650;
    }
    select, button {
      height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font-size: 14px;
    }
    select {
      width: 100%;
      padding: 0 10px;
      background: #fff;
      color: var(--text);
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }
    button {
      padding: 0 12px;
      cursor: pointer;
      background: #e8eef8;
      color: var(--text);
      font-weight: 650;
    }
    button.primary { background: var(--blue); color: white; border-color: var(--blue); }
    button.good { background: var(--green); color: white; border-color: var(--green); }
    button.danger { background: var(--red); color: white; border-color: var(--red); }
    .menu-list, .queue-list {
      display: grid;
      gap: 8px;
      margin-top: 8px;
      max-height: calc(3 * 52px + 2 * 8px);
      overflow-y: auto;
      padding-right: 2px;
    }
    .item {
      height: 52px;
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcff;
      cursor: pointer;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 8px;
    }
    .item.selected { border-color: var(--blue); background: #eff6ff; }
    .item-main {
      min-width: 0;
    }
    .item-actions {
      display: flex;
      gap: 6px;
    }
    button.icon {
      width: 32px;
      height: 32px;
      padding: 0;
      line-height: 1;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    .title {
      font-weight: 650;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .meta {
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
      min-height: 18px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
    }
    .control-block {
      border-top: 1px solid var(--line);
      padding-top: 12px;
      margin-top: 12px;
    }
    .control-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 10px;
    }
    .control-row label {
      margin: 0;
    }
    input[type="checkbox"] {
      width: 18px;
      height: 18px;
      accent-color: var(--blue);
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--blue);
    }
    input[type="color"] {
      width: 44px;
      height: 34px;
      padding: 2px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
    }
    .range-row {
      display: grid;
      grid-template-columns: 1fr 44px;
      align-items: center;
      gap: 10px;
    }
    .value {
      color: var(--muted);
      font-size: 12px;
      text-align: right;
      font-variant-numeric: tabular-nums;
    }
    .shot-log {
      margin-top: 8px;
      max-height: 240px;
      overflow-y: auto;
      padding-right: 2px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcff;
      padding: 9px 10px;
      color: var(--muted);
      font-family: Consolas, "Courier New", monospace;
      font-size: 12px;
      line-height: 1.45;
      white-space: pre-wrap;
    }
    details > summary {
      cursor: pointer;
      font-size: 16px;
      font-weight: 650;
      list-style-position: inside;
    }
    details > summary h2 {
      display: inline;
      margin: 0;
    }
    details[open] > summary {
      margin-bottom: 12px;
    }
    @media (max-width: 900px) {
      main { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Badminton Menu Frontend</h1>
    <div class="status" id="status">Loading...</div>
  </header>
  <main>
    <section>
      <details data-block="menus">
        <summary><h2>Menus in menus.json</h2></summary>
        <div class="menu-list" id="menus"></div>
        <div class="actions">
          <button id="reload">Reload menus.json</button>
        </div>
      </details>
    </section>
    <section>
      <details data-block="queue">
        <summary><h2>Execution Queue</h2></summary>
        <div class="queue-list" id="queue"></div>
        <div class="actions">
          <button id="clear-queue">Clear Queue</button>
        </div>
      </details>
    </section>
    <section>
      <details data-block="shotLog">
        <summary><h2>Shot Log</h2></summary>
        <div class="shot-log" id="shot-log"></div>
      </details>
    </section>
    <section>
      <details data-block="returnStrategy">
        <summary><h2>Return Strategy</h2></summary>
        <div class="grid">
          <div>
            <label for="scope">Scope</label>
            <select id="scope"></select>
          </div>
          <div>
            <label for="profile">Shot Type</label>
            <select id="profile"></select>
          </div>
        </div>
        <label for="target">Target</label>
        <select id="target"></select>
        <div class="actions">
          <button class="primary" id="save-policy">Save Return Strategy</button>
        </div>
      </details>
    </section>
    <section>
      <details data-block="simulatorControls">
        <summary><h2>Simulator Controls</h2></summary>
        <div class="grid">
          <div>
            <label for="view-mode">View Mode</label>
            <select id="view-mode"></select>
          </div>
          <div>
            <label>Dynamic Returns</label>
            <button id="returns-toggle">Off</button>
          </div>
        </div>

        <div class="control-block">
          <h2>Serve Trajectory</h2>
          <div class="control-row">
            <label for="serve-traj-visible">Visible</label>
            <input id="serve-traj-visible" type="checkbox" />
          </div>
          <label for="serve-traj-size">Size</label>
          <div class="range-row">
            <input id="serve-traj-size" type="range" min="0.02" max="0.30" step="0.01" />
            <div class="value" id="serve-traj-size-value"></div>
          </div>
          <label for="serve-traj-density">Density</label>
          <div class="range-row">
            <input id="serve-traj-density" type="range" min="1" max="5" step="1" />
            <div class="value" id="serve-traj-density-value"></div>
          </div>
          <div class="control-row">
            <label for="serve-traj-color">Color</label>
            <input id="serve-traj-color" type="color" />
          </div>
        </div>

        <div class="control-block">
          <h2>Return Trajectory</h2>
          <div class="control-row">
            <label for="return-traj-visible">Visible</label>
            <input id="return-traj-visible" type="checkbox" />
          </div>
          <label for="return-traj-size">Size</label>
          <div class="range-row">
            <input id="return-traj-size" type="range" min="0.02" max="0.30" step="0.01" />
            <div class="value" id="return-traj-size-value"></div>
          </div>
          <label for="return-traj-density">Density</label>
          <div class="range-row">
            <input id="return-traj-density" type="range" min="1" max="5" step="1" />
            <div class="value" id="return-traj-density-value"></div>
          </div>
          <div class="control-row">
            <label for="return-traj-color">Color</label>
            <input id="return-traj-color" type="color" />
          </div>
        </div>
      </details>
    </section>
  </main>
  <script>
    let state = null;
    let selectedMenuId = null;
    let formDirty = false;
    const BLOCK_DEFAULT_OPEN = {
      menus: true,
      queue: true,
      shotLog: false,
      returnStrategy: false,
      simulatorControls: false
    };

    const $ = (id) => document.getElementById(id);

    function applyBlockDefaults() {
      document.querySelectorAll('[data-block]').forEach(el => {
        el.open = BLOCK_DEFAULT_OPEN[el.dataset.block] !== false;
      });
    }

    async function api(path, body) {
      const options = body ? {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      } : {};
      const res = await fetch(path, options);
      if (!res.ok) throw new Error(await res.text());
      return await res.json();
    }

    function selectedMenu() {
      if (!state || !state.menus.length) return null;
      return state.menus.find(m => m.id === selectedMenuId) || state.menus[0];
    }

    function currentPolicy(menu, scope) {
      const sim = menu?.simulator || {};
      let policy = sim.default_return_policy;
      if (scope !== 'default') {
        const override = (sim.drill_overrides || {})[scope];
        if (override && override.return_policy) policy = override.return_policy;
      }
      return policy || {profile: 'clear', target: null};
    }

    function targetKeyFor(profile, target) {
      if (!target) return '';
      const options = state.targets[profile] || {};
      for (const [label, value] of Object.entries(options)) {
        if (Math.abs(value.x - Number(target.x)) < 0.02 && Math.abs(value.y - Number(target.y)) < 0.02) {
          return label;
        }
      }
      return '';
    }

    function render(preserveDraft=false) {
      if (!state) return;
      if (!selectedMenuId && state.menus.length) selectedMenuId = state.menus[0].id;
      if (!state.menus.some(m => m.id === selectedMenuId)) selectedMenuId = state.menus[0]?.id || null;
      const menu = selectedMenu();
      const draftScope = $('scope').value || 'default';
      const draftProfile = $('profile').value || 'clear';
      const draftTarget = $('target').value || '';
      const useDraft = preserveDraft && formDirty && menu;

      $('status').textContent = state.status || `Loaded ${state.menus.length} menus`;
      $('menus').innerHTML = state.menus.map((m) => `
        <div class="item ${m.id === selectedMenuId ? 'selected' : ''}" data-menu-id="${m.id}">
          <div class="item-main">
            <div class="title">${m.menuName}</div>
            <div class="meta">${m.id} | ${m.drill_count} drills</div>
          </div>
          <div class="item-actions">
            <button class="icon primary" data-enqueue-menu-id="${m.id}" title="Add to queue">+</button>
            <button class="icon danger" data-delete-menu-id="${m.id}" title="Delete from menus.json">&#128465;</button>
          </div>
        </div>
      `).join('') || '<div class="meta">No menus in menus.json</div>';

      document.querySelectorAll('[data-menu-id]').forEach(el => {
        el.onclick = () => {
          selectedMenuId = el.dataset.menuId;
          formDirty = false;
          render();
        };
      });
      document.querySelectorAll('[data-enqueue-menu-id]').forEach(el => {
        el.onclick = (event) => {
          event.stopPropagation();
          command('enqueue', {menu_id: el.dataset.enqueueMenuId});
        };
      });
      document.querySelectorAll('[data-delete-menu-id]').forEach(el => {
        el.onclick = (event) => {
          event.stopPropagation();
          command('delete', {menu_id: el.dataset.deleteMenuId});
        };
      });

      $('queue').innerHTML = state.queue.length ? state.queue.map((q, i) => `
        <div class="item">
          <div class="item-main">
            <div class="title">${i + 1}. ${q.menuName || q.id}</div>
            <div class="meta">${q.id}</div>
          </div>
          <div class="item-actions">
            <button class="icon danger" data-remove-queue-index="${i}" title="Remove from queue">&#128465;</button>
          </div>
        </div>
      `).join('') : '<div class="meta">Queue is empty</div>';
      document.querySelectorAll('[data-remove-queue-index]').forEach(el => {
        el.onclick = () => command('remove_queue_item', {queue_index: Number(el.dataset.removeQueueIndex)});
      });

      $('shot-log').textContent = (state.shot_log || []).length
        ? state.shot_log.map(entry => `${entry.title}: ${entry.detail}`).join('\n')
        : 'Shot log is empty';

      if (!menu) {
        $('scope').innerHTML = '';
        $('profile').innerHTML = '';
        $('target').innerHTML = '';
        return;
      }

      const scope = useDraft ? draftScope : ($('scope').value || 'default');
      const normalizedScope = scope === 'default' || Number(scope) < menu.drill_count ? scope : 'default';
      $('scope').innerHTML = [
        `<option value="default">Default policy</option>`,
        ...Array.from({length: menu.drill_count}, (_, i) => `<option value="${i}">Drill ${i + 1}</option>`)
      ].join('');
      $('scope').value = normalizedScope;

      const policy = currentPolicy(menu, normalizedScope);
      $('profile').innerHTML = Object.keys(state.targets).map(p => `<option value="${p}">${p}</option>`).join('');
      const profileValue = useDraft ? draftProfile : (policy.profile && state.targets[policy.profile] ? policy.profile : 'clear');
      $('profile').value = state.targets[profileValue] ? profileValue : 'clear';

      renderTargets(useDraft ? null : policy.target);
      if (useDraft && draftTarget && Array.from($('target').options).some(o => o.value === draftTarget)) {
        $('target').value = draftTarget;
      }
    }

    function renderTargets(existingTarget=null) {
      const profile = $('profile').value || 'clear';
      const options = state.targets[profile] || {};
      $('target').innerHTML = Object.keys(options).map(label => `<option value="${label}">${label}</option>`).join('');
      const match = targetKeyFor(profile, existingTarget);
      if (match) $('target').value = match;
    }

    function renderSimulatorControls() {
      const controls = state.simulator_controls || {};
      const serve = controls.serve_trajectory || {};
      const ret = controls.return_trajectory || {};

      $('view-mode').innerHTML = (controls.view_modes || []).map(mode => (
        `<option value="${mode.value}" ${mode.enabled ? '' : 'disabled'}>${mode.label}</option>`
      )).join('');
      $('view-mode').value = String(controls.view_mode ?? 0);

      $('returns-toggle').textContent = controls.dynamic_returns ? 'On' : 'Off';
      $('returns-toggle').className = controls.dynamic_returns ? 'good' : '';

      $('serve-traj-visible').checked = serve.visible !== false;
      $('serve-traj-size').value = Number(serve.size ?? 0.10).toFixed(2);
      $('serve-traj-size-value').textContent = Number(serve.size ?? 0.10).toFixed(2);
      $('serve-traj-density').value = String(serve.density ?? 4);
      $('serve-traj-density-value').textContent = String(serve.density ?? 4);
      $('serve-traj-color').value = serve.color || '#facc15';

      $('return-traj-visible').checked = ret.visible !== false;
      $('return-traj-size').value = Number(ret.size ?? 0.10).toFixed(2);
      $('return-traj-size-value').textContent = Number(ret.size ?? 0.10).toFixed(2);
      $('return-traj-density').value = String(ret.density ?? 3);
      $('return-traj-density-value').textContent = String(ret.density ?? 3);
      $('return-traj-color').value = ret.color || '#f97316';
    }

    async function refresh(preserveDraft=false) {
      state = await api('/api/state');
      render(preserveDraft);
      renderSimulatorControls();
    }

    async function command(action, payload={}) {
      await api('/api/command', {action, ...payload});
      await new Promise(resolve => setTimeout(resolve, 120));
      if (action === 'set_policy') formDirty = false;
      await refresh(action !== 'set_policy');
    }

    $('scope').onchange = () => {
      formDirty = false;
      render();
    };
    $('profile').onchange = () => {
      formDirty = true;
      renderTargets();
    };
    $('target').onchange = () => {
      formDirty = true;
    };
    $('reload').onclick = () => {
      formDirty = false;
      refresh();
    };
    $('clear-queue').onclick = () => command('clear_queue');
    $('save-policy').onclick = () => selectedMenuId && command('set_policy', {
      menu_id: selectedMenuId,
      scope: $('scope').value,
      profile: $('profile').value,
      target_label: $('target').value
    });
    $('view-mode').onchange = () => command('set_view_mode', {view_mode: Number($('view-mode').value)});
    $('returns-toggle').onclick = () => command('toggle_returns');

    function sendTrajectoryConfig(target) {
      $(`${target}-traj-size-value`).textContent = Number($(`${target}-traj-size`).value).toFixed(2);
      $(`${target}-traj-density-value`).textContent = $(`${target}-traj-density`).value;
      command('set_trajectory_config', {
        target,
        visible: $(`${target}-traj-visible`).checked,
        size: Number($(`${target}-traj-size`).value),
        density: Number($(`${target}-traj-density`).value),
        color: $(`${target}-traj-color`).value
      });
    }

    ['serve', 'return'].forEach(target => {
      $(`${target}-traj-visible`).onchange = () => sendTrajectoryConfig(target);
      $(`${target}-traj-size`).oninput = () => {
        $(`${target}-traj-size-value`).textContent = Number($(`${target}-traj-size`).value).toFixed(2);
      };
      $(`${target}-traj-size`).onchange = () => sendTrajectoryConfig(target);
      $(`${target}-traj-density`).oninput = () => {
        $(`${target}-traj-density-value`).textContent = $(`${target}-traj-density`).value;
      };
      $(`${target}-traj-density`).onchange = () => sendTrajectoryConfig(target);
      $(`${target}-traj-color`).onchange = () => sendTrajectoryConfig(target);
    });

    applyBlockDefaults();
    refresh();
    setInterval(() => refresh(true), 1500);
  </script>
</body>
</html>
"""


class HtmlMenuFrontendServer:
    def __init__(self, get_state, command_queue, host="127.0.0.1", port=8765):
        self.get_state = get_state
        self.command_queue = command_queue
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}/"
        self.httpd = None
        self.thread = None

    def start(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, body, content_type="application/json; charset=utf-8"):
                raw = body if isinstance(body, bytes) else body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                path = urlparse(self.path).path
                if path == "/":
                    self._send(200, HTML_PAGE, "text/html; charset=utf-8")
                    return
                if path == "/api/state":
                    self._send(200, json.dumps(server.get_state(), ensure_ascii=False))
                    return
                self._send(404, json.dumps({"error": "not found"}))

            def do_POST(self):
                path = urlparse(self.path).path
                if path != "/api/command":
                    self._send(404, json.dumps({"error": "not found"}))
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                    server.command_queue.put(payload)
                    self._send(202, json.dumps({"status": "queued"}))
                except Exception as exc:
                    self._send(400, json.dumps({"error": str(exc)}))

            def log_message(self, _format, *args):
                return

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler) # 放在另一個thread，避免干擾模擬器正在讀取menus.json的主線程
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.url
