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
    }
    .item {
      padding: 9px 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcff;
      cursor: pointer;
    }
    .item.selected { border-color: var(--blue); background: #eff6ff; }
    .title { font-weight: 650; }
    .meta { margin-top: 2px; color: var(--muted); font-size: 12px; }
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
      <h2>Menus in menus.json</h2>
      <div class="menu-list" id="menus"></div>
    </section>
    <section>
      <h2>Execution Queue</h2>
      <div class="queue-list" id="queue"></div>
      <div class="actions">
        <button id="clear-queue">Clear Queue</button>
      </div>
    </section>
    <section>
      <h2>Selected Menu</h2>
      <div id="selected-meta" class="meta">No menu selected</div>
      <div class="actions">
        <button class="primary" id="enqueue">Queue Selected</button>
        <button class="danger" id="delete">Delete Selected</button>
        <button id="reload">Reload menus.json</button>
      </div>
    </section>
    <section>
      <h2>Return Strategy</h2>
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
    </section>
  </main>
  <script>
    let state = null;
    let selectedMenuId = null;
    let formDirty = false;

    const $ = (id) => document.getElementById(id);

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
          <div class="title">${m.menuName}</div>
          <div class="meta">${m.id} | ${m.drill_count} drills</div>
        </div>
      `).join('') || '<div class="meta">No menus in menus.json</div>';

      document.querySelectorAll('[data-menu-id]').forEach(el => {
        el.onclick = () => {
          selectedMenuId = el.dataset.menuId;
          formDirty = false;
          render();
        };
      });

      $('queue').innerHTML = state.queue.length ? state.queue.map((q, i) => `
        <div class="item">
          <div class="title">${i + 1}. ${q.menuName || q.id}</div>
          <div class="meta">${q.id}</div>
        </div>
      `).join('') : '<div class="meta">Queue is empty</div>';

      if (!menu) {
        $('selected-meta').textContent = 'No menu selected';
        $('scope').innerHTML = '';
        $('profile').innerHTML = '';
        $('target').innerHTML = '';
        return;
      }

      $('selected-meta').textContent = `${menu.menuName} | ${menu.id} | ${menu.drill_count} drills`;
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

    async function refresh(preserveDraft=false) {
      state = await api('/api/state');
      render(preserveDraft);
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
    $('enqueue').onclick = () => selectedMenuId && command('enqueue', {menu_id: selectedMenuId});
    $('delete').onclick = () => selectedMenuId && command('delete', {menu_id: selectedMenuId});
    $('clear-queue').onclick = () => command('clear_queue');
    $('save-policy').onclick = () => selectedMenuId && command('set_policy', {
      menu_id: selectedMenuId,
      scope: $('scope').value,
      profile: $('profile').value,
      target_label: $('target').value
    });

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

        self.httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.url
