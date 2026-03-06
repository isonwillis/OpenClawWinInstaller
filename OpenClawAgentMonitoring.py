"""
OpenClawAgentMonitoring.py  –  v1.0.5
======================================
Agent Monitoring & Management Module — Lyra (Head) only.

Self-contained tkinter tab: GUI + logic in one place.
Integrated into OpenClawWinInstaller via MonitoringTab.build(notebook).

Architecture:
  MonitoringTab          — GUI owner, lifecycle, tkinter widgets
  _HealthPoller          — background daemon thread, silent polling, no log spam
  _diag_api()            — shared HTTP helper (no circular import)

Agent types (unified registry in workers.json):
  worker  — OpenClaw WorkerTaskServer  (POST /tasks, GET /result/<id>)
  ollama  — Ollama REST API            (POST /api/chat, GET /api/tags)
  openai  — OpenAI-compatible API      (POST /v1/chat/completions, GET /v1/models)
  custom  — Any HTTP endpoint          (best-effort /health check)

Protocol field controls the wire format used for Task Sender:
  openclaw — async task_id flow (OpenClaw workers)
  ollama   — synchronous POST /api/chat
  openai   — synchronous POST /v1/chat/completions

Field visibility by type:
  worker  — URL/IP + Port + Name + Role
  ollama  — URL   + Port + Name + Role + Model
  openai  — URL         + Name + Role + Model + API key
  custom  — URL   + Port + Name + Role + Model + API key

API key stored in workers.json as plaintext.
SOUL.md shows masked: first 3 + last 3 chars visible.
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk
from typing import Callable


# ── Constants ──────────────────────────────────────────────────────────────────

POLL_INTERVAL_SEC = 30

# type → (default_protocol, default_port, show_port, show_apikey, show_model)
TYPE_META: dict[str, dict] = {
    "worker": {"protocol": "openclaw", "port": 18790,
               "show_port": True,  "show_key": False, "show_model": False},
    "ollama": {"protocol": "ollama",   "port": 11434,
               "show_port": True,  "show_key": False, "show_model": True},
    "openai": {"protocol": "openai",   "port": 443,
               "show_port": False, "show_key": True,  "show_model": True},
    "custom": {"protocol": "openai",   "port": 8080,
               "show_port": True,  "show_key": True,  "show_model": True},
}

PROTOCOLS   = ["openclaw", "openai", "ollama"]
AGENT_TYPES = list(TYPE_META.keys())


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _diag_api(url: str, timeout: int = 8,
              method: str = "GET",
              data: dict | None = None,
              api_key: str = "") -> tuple[int, dict | str]:
    """
    Minimal HTTP helper — no external dependencies.
    Returns (status_code, body_as_dict_or_str).  status_code = -1 on error.
    api_key: if non-empty adds Authorization: Bearer header.
    Follows HTTP 301/302/307/308 redirects automatically (up to 5 hops),
    preserving method and headers — critical for http→https upgrades.
    """
    import urllib.parse
    url = url.replace("//localhost:", "//127.0.0.1:")

    for _ in range(5):
        try:
            body_bytes = json.dumps(data).encode("utf-8") if data else None
            headers = ({"User-Agent": "LyraMonitor/1.0.5",
                        "Accept": "application/json, text/html, */*"}
                       if method == "GET" else
                       {"Content-Type": "application/json",
                        "User-Agent": "LyraMonitor/1.0.5"})
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(
                url, data=body_bytes, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(32_000).decode("utf-8", errors="replace").strip()
                for c in [raw, raw.lstrip("\ufeff"), raw.split("\n", 1)[-1]]:
                    try:
                        return r.status, json.loads(c)
                    except Exception:
                        continue
                return r.status, raw
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 307, 308):
                loc = e.headers.get("Location", "")
                if loc:
                    if loc.startswith("/"):
                        p = urllib.parse.urlparse(url)
                        url = f"{p.scheme}://{p.netloc}{loc}"
                    else:
                        url = loc
                    continue  # follow redirect
            try:
                body = e.read(2000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, body
        except Exception as e:
            return -1, str(e)

    return -1, "Too many redirects"


def _agent_base_url(agent: dict) -> str:
    """
    Build base URL from agent dict.

    Routing logic:
      - If 'url' field contains a real URL (has '://' or looks like a domain)
        → use it as-is (external APIs like https://api.openai.com)
      - Otherwise fall back to ip:port (local workers and Ollama)
        → always includes port to avoid http://192.168.x.x (portless) bug

    Backward-compatible with old-format entries that only have 'ip' + 'port'.
    """
    url  = agent.get("url", "").strip()
    ip   = agent.get("ip",  "").strip()
    port = agent.get("port", 18790)

    # A "real" URL has a scheme OR looks like a public domain (contains a dot
    # but is NOT a bare IP address like 192.168.x.x / 10.x / 172.x / 127.x)
    def _is_real_url(s: str) -> bool:
        if "://" in s:
            return True
        # Bare IP patterns — NOT a real URL, need port appended
        import re
        if re.match(r"^(\d{1,3}\.){3}\d{1,3}$", s):
            return False
        # Has at least one dot and looks like a hostname → real URL
        return "." in s

    if url and _is_real_url(url):
        if "://" not in url:
            url = f"https://{url}"
        return url.rstrip("/")

    # IP address or bare hostname: always use ip+port
    addr = url or ip   # url field may contain a bare IP
    if not addr:
        addr = "127.0.0.1"
    return f"http://{addr}:{port}"


def _mask_key(key: str) -> str:
    """Mask API key for SOUL.md display: abcdefgh → abc***efg"""
    if not key or len(key) < 8:
        return "***"
    return f"{key[:3]}***\u2026***{key[-3:]}"


# ── Background health poller ───────────────────────────────────────────────────

class _HealthPoller(threading.Thread):
    """
    Daemon thread — silently polls every agent every interval_sec seconds.
    Delivers results on the main thread via root.after(0, callback).
    Never touches tkinter widgets directly.
    """

    def __init__(self,
                 get_agents:   Callable[[], list[dict]],
                 on_result:    Callable[[list[dict]], None],
                 root:         tk.Tk,
                 interval_sec: int = POLL_INTERVAL_SEC):
        super().__init__(daemon=True, name="LyraHealthPoller")
        self._get_agents  = get_agents
        self._on_result   = on_result
        self._root        = root
        self._interval    = interval_sec
        self._stop_evt    = threading.Event()

    def stop(self):
        self._stop_evt.set()

    def run(self):
        while not self._stop_evt.is_set():
            self._poll()
            self._stop_evt.wait(self._interval)

    def _health_url_and_key(self, agent: dict) -> tuple[str, str]:
        base    = _agent_base_url(agent)
        atype   = agent.get("type", "worker")
        api_key = agent.get("api_key", "")
        if atype == "openai":
            return f"{base}/models", api_key
        if atype == "ollama":
            return f"{base}/api/tags", ""
        return f"{base}/health", ""

    def _poll(self):
        agents = self._get_agents()
        if not agents:
            return
        results = []
        for a in agents:
            url, key = self._health_url_and_key(a)
            sc, body = _diag_api(url, timeout=4, api_key=key)
            online = (0 < sc < 400)
            info   = "OK"
            if online and isinstance(body, dict):
                atype = a.get("type", "worker")
                if atype == "worker":
                    info = f"role={body.get('role', '?')}"
                elif atype == "ollama":
                    info = f"{len(body.get('models', []))} model(s)"
                elif atype == "openai":
                    info = f"{len(body.get('data', []))} model(s)"
            elif not online:
                info = f"HTTP {sc}"
            results.append({"agent": a, "online": online, "info": info})
        self._root.after(0, lambda r=results: self._on_result(r))


# ── MonitoringTab ──────────────────────────────────────────────────────────────

class MonitoringTab:
    """
    Self-contained Monitoring Tab for OpenClaw Lyra (Head).

    Unified agent registry: OpenClaw workers AND external LLMs in one list.
    Type dropdown controls field visibility and wire protocol.

    Usage:
        from OpenClawAgentMonitoring import MonitoringTab
        self.monitoring = MonitoringTab(notebook, cfg, self.log, self.root)
        self.monitoring.build()
    """

    def __init__(self, notebook: ttk.Notebook, cfg,
                 log_fn: Callable, root: tk.Tk):
        self._nb    = notebook
        self._cfg   = cfg
        self._log   = log_fn
        self._root  = root

        self._agents: list[dict] = []
        self._poller: _HealthPoller | None = None

        # Widget refs — populated in build()
        self._reg_url_entry   = None
        self._reg_port_entry  = None
        self._reg_port_row    = None
        self._reg_name_entry  = None
        self._reg_role_var    = None
        self._reg_type_var    = None
        self._reg_proto_var   = None
        self._reg_model_entry = None
        self._reg_model_row   = None
        self._reg_key_entry   = None
        self._reg_key_row     = None
        self._reg_list        = None
        self._reg_status_lbl  = None
        self._snd_target      = None
        self._snd_task_type   = None
        self._snd_payload     = None
        self._snd_taskid_lbl  = None
        self._res_status_lbl  = None
        self._res_box         = None

        # Internal: last URL/port entry frame ref for pack ordering
        self._url_row_frame   = None

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self, head_server=None):
        """
        Create and register the Monitoring tab into the parent notebook.

        head_server: LyraHeadServer instance — if provided, registers
        on_result_callback for auto-display when worker results arrive.
        """
        frame = ttk.Frame(self._nb, padding="8")
        self._nb.add(frame, text="📡 Monitoring")
        self._build_ui(frame)
        self._root.after(300, self._load_agents_and_start_poller)
        if head_server is not None:
            self._register_head_server(head_server)

    def register_head_server(self, head_server):
        """Register (or re-register) the HeadServer for auto-display callbacks."""
        self._register_head_server(head_server)

    def _register_head_server(self, head_server):
        """Wire on_result_callback so results appear automatically."""
        def _cb(result: dict):
            # Called from server thread — schedule on main thread
            self._root.after(0, lambda r=result: self._on_result_received(r))
        head_server.on_result_callback = _cb

    def destroy(self):
        if self._poller:
            self._poller.stop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, parent: ttk.Frame):
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb    = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outer  = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(
                            int(-1 * (e.delta / 120)), "units"))
        self._build_registry_section(outer)
        self._build_task_sender_section(outer)
        self._build_result_viewer_section(outer)

    def _build_registry_section(self, parent: ttk.Frame):
        lf = ttk.LabelFrame(parent, text="🖥  Agent Registry", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        # Row 1: Type + Protocol
        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r1, text="Type:", width=10).pack(side=tk.LEFT)
        self._reg_type_var = tk.StringVar(value="worker")
        type_cb = ttk.Combobox(r1, textvariable=self._reg_type_var,
                                values=AGENT_TYPES, width=9, state="readonly")
        type_cb.pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(r1, text="Protocol:", width=9).pack(side=tk.LEFT)
        self._reg_proto_var = tk.StringVar(value="openclaw")
        ttk.Combobox(r1, textvariable=self._reg_proto_var,
                     values=PROTOCOLS, width=10,
                     state="readonly").pack(side=tk.LEFT, padx=(4, 0))
        self._reg_type_var.trace_add("write", self._on_type_changed)

        # Row 2: URL / IP
        self._url_row_frame = ttk.Frame(lf)
        self._url_row_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self._url_row_frame, text="URL / IP:", width=10).pack(side=tk.LEFT)
        self._reg_url_entry = ttk.Entry(self._url_row_frame, width=34)
        self._reg_url_entry.insert(0, "192.168.2.102")
        self._reg_url_entry.pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)

        # Row 3: Port (hidden for openai)
        self._reg_port_row = ttk.Frame(lf)
        self._reg_port_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(self._reg_port_row, text="Port:", width=10).pack(side=tk.LEFT)
        self._reg_port_entry = ttk.Entry(self._reg_port_row, width=8)
        self._reg_port_entry.insert(0, "18790")
        self._reg_port_entry.pack(side=tk.LEFT, padx=(4, 0))

        # Row 4: Name + Role
        r4 = ttk.Frame(lf)
        r4.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r4, text="Name:", width=10).pack(side=tk.LEFT)
        self._reg_name_entry = ttk.Entry(r4, width=16)
        self._reg_name_entry.insert(0, "Junior-PC")
        self._reg_name_entry.pack(side=tk.LEFT, padx=(4, 8))
        ttk.Label(r4, text="Role:", width=5).pack(side=tk.LEFT)
        self._reg_role_var = tk.StringVar(value="Junior")
        ttk.Combobox(r4, textvariable=self._reg_role_var,
                     values=["Junior", "Senior", "External"],
                     width=9, state="readonly").pack(side=tk.LEFT, padx=(4, 0))

        # Row 5: Model (hidden for worker)
        self._reg_model_row = ttk.Frame(lf)
        ttk.Label(self._reg_model_row, text="Model:", width=10).pack(side=tk.LEFT)
        self._reg_model_entry = ttk.Entry(self._reg_model_row, width=24)
        self._reg_model_entry.pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(self._reg_model_row, text="(blank = server default)",
                  font=("Arial", 8), foreground="#888").pack(side=tk.LEFT, padx=(6, 0))

        # Row 6: API Key (hidden for worker + ollama)
        self._reg_key_row = ttk.Frame(lf)
        ttk.Label(self._reg_key_row, text="API Key:", width=10).pack(side=tk.LEFT)
        self._reg_key_entry = ttk.Entry(self._reg_key_row, width=36, show="•")
        self._reg_key_entry.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(self._reg_key_row, text="(blank = no auth)",
                  font=("Arial", 8), foreground="#888").pack(side=tk.LEFT)

        # Action buttons
        r7 = ttk.Frame(lf)
        r7.pack(fill=tk.X, pady=(4, 4))
        ttk.Button(r7, text="🔍 Check",
                   command=self._check_agent).pack(side=tk.LEFT)
        self._reg_save_btn = ttk.Button(r7, text="💾 Save / Update",
                   command=self._add_agent)
        self._reg_save_btn.pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(r7, text="📋 Edit Rules",
                   command=self._open_rules_editor).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(r7, text="🗑 Remove selected",
                   command=self._remove_agent).pack(side=tk.LEFT, padx=(6, 0))

        # Agent listbox
        self._reg_list = tk.Listbox(
            lf, height=6, font=("Courier", 9), selectmode=tk.SINGLE)
        self._reg_list.pack(fill=tk.X, pady=(4, 0))
        self._reg_list.bind("<<ListboxSelect>>", self._list_select)

        # Status label
        self._reg_status_lbl = ttk.Label(
            lf, text="", font=("Arial", 9), foreground="#555555")
        self._reg_status_lbl.pack(anchor=tk.W, pady=(4, 0))

        # Apply initial field visibility
        self._apply_type_visibility("worker")

    def _build_task_sender_section(self, parent: ttk.Frame):
        lf = ttk.LabelFrame(parent, text="📤  Send Task / Prompt", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r1, text="Target:", width=10).pack(side=tk.LEFT)
        self._snd_target = ttk.Entry(r1, width=34)
        self._snd_target.insert(0, "192.168.2.102:18790")
        self._snd_target.pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)

        r2 = ttk.Frame(lf)
        r2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r2, text="Task type:", width=10).pack(side=tk.LEFT)
        self._snd_task_type = ttk.Combobox(
            r2,
            values=["web_search", "batch_exec", "summarize", "validate",
                    "chat (openai)", "chat (ollama)"],
            width=18, state="readonly")
        self._snd_task_type.current(0)
        self._snd_task_type.pack(side=tk.LEFT, padx=(4, 0))

        r3 = ttk.Frame(lf)
        r3.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r3, text="Query / msg:", width=10).pack(side=tk.LEFT)
        self._snd_payload = ttk.Entry(r3, width=40)
        self._snd_payload.insert(0, "Wetter Zürich aktuell")
        self._snd_payload.pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)

        r4 = ttk.Frame(lf)
        r4.pack(fill=tk.X)
        ttk.Button(r4, text="📤 Send",
                   command=self._send_task).pack(side=tk.LEFT)
        self._snd_taskid_lbl = ttk.Label(
            r4, text="", font=("Courier", 9), foreground="#0055aa")
        self._snd_taskid_lbl.pack(side=tk.LEFT, padx=(10, 0))

    def _build_result_viewer_section(self, parent: ttk.Frame):
        """
        Result Viewer — auto-displays results as they arrive from workers.

        Architecture: Worker POSTs result → Lyra LyraHeadServer →
        on_result_callback fires → root.after(0, _on_result_received) →
        shown here automatically. No polling needed.

        Manual 'Show All' button kept for reviewing older results.
        """
        lf = ttk.LabelFrame(parent, text="📥  Result Viewer", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        # Auto-status: shows last received result info
        self._res_status_lbl = ttk.Label(
            lf, text="Waiting for results from workers...",
            font=("Arial", 9), foreground="#888888")
        self._res_status_lbl.pack(anchor=tk.W, pady=(0, 4))

        # Manual controls for reviewing history
        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(r1, text="📋 Show All Results",
                   command=self._fetch_all_results).pack(side=tk.LEFT)
        ttk.Button(r1, text="🗑 Clear",
                   command=self._clear_result_box).pack(side=tk.LEFT, padx=(6, 0))

        self._res_box = tk.Text(
            lf, height=12, font=("Courier", 9),
            wrap=tk.WORD, state=tk.DISABLED, background="#f8f8f8")
        self._res_box.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(lf, command=self._res_box.yview)
        self._res_box.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)


    # ── Type visibility ───────────────────────────────────────────────────────

    def _on_type_changed(self, *_):
        atype = self._reg_type_var.get()
        meta  = TYPE_META.get(atype, TYPE_META["worker"])
        self._reg_proto_var.set(meta["protocol"])
        self._reg_port_entry.delete(0, tk.END)
        self._reg_port_entry.insert(0, str(meta["port"]))
        self._apply_type_visibility(atype)

    def _apply_type_visibility(self, atype: str):
        """Show/hide port, model, api_key rows based on selected type."""
        meta = TYPE_META.get(atype, TYPE_META["worker"])

        if meta["show_port"]:
            self._reg_port_row.pack(fill=tk.X, pady=(0, 4))
        else:
            self._reg_port_row.pack_forget()

        if meta["show_model"]:
            self._reg_model_row.pack(fill=tk.X, pady=(0, 4))
        else:
            self._reg_model_row.pack_forget()

        if meta["show_key"]:
            self._reg_key_row.pack(fill=tk.X, pady=(0, 4))
        else:
            self._reg_key_row.pack_forget()

    # ── Agent label ───────────────────────────────────────────────────────────

    def _agent_label(self, a: dict, status: str = "?") -> str:
        atype = a.get("type", "worker")
        url   = _agent_base_url(a)
        name  = a.get("name", "?")
        role  = a.get("role", "?")
        model = a.get("model", "")
        disp  = url.replace("https://","").replace("http://","")
        if len(disp) > 28:
            disp = disp[:25] + "..."
        model_str = f"  [{model}]" if model else ""
        # status prefix: "OK", "??" or "!!" — colored via itemconfig
        return (f"[{status:2s}] {name:12s}  {disp:28s}  "
                f"({atype}/{role}){model_str}")

    def _set_list_item(self, index: int, label: str, online: bool | None):
        """Insert/replace a listbox item and apply foreground color."""
        try:
            self._reg_list.delete(index)
            self._reg_list.insert(index, label)
            if online is True:
                self._reg_list.itemconfig(index, foreground="#1a7f1a")  # green
            elif online is False:
                self._reg_list.itemconfig(index, foreground="#cc0000")  # red
            else:
                self._reg_list.itemconfig(index, foreground="#888888")  # grey = unknown
        except Exception:
            pass

    # ── Poller integration ────────────────────────────────────────────────────

    def _load_agents_and_start_poller(self):
        agents = self._cfg.load_workers()
        self._agents = agents
        self._reg_list.delete(0, tk.END)
        for i, a in enumerate(agents):
            label = self._agent_label(a, "??")
            self._reg_list.insert(tk.END, label)
            self._reg_list.itemconfig(i, foreground="#888888")  # grey = not yet polled
        if agents:
            self._log(
                f"[Monitor] Loaded {len(agents)} agent(s) from workers.json",
                "SUCCESS")
            a0 = agents[0]
            self._snd_target.delete(0, tk.END)
            self._snd_target.insert(
                0, _agent_base_url(a0).replace("https://","").replace("http://",""))

        self._poller = _HealthPoller(
            get_agents   = lambda: list(self._agents),
            on_result    = self._on_poll_result,
            root         = self._root,
            interval_sec = POLL_INTERVAL_SEC,
        )
        self._poller.start()

    def _on_poll_result(self, results: list[dict]):
        """Update listbox items with color on the main thread — no log spam."""
        for i, res in enumerate(results):
            if i >= len(self._agents):
                break
            online = res["online"]
            status = "OK" if online else "!!"
            label  = self._agent_label(res["agent"], status)
            if online and res["info"] != "OK":
                label += f"  {res['info']}"
            self._set_list_item(i, label, online)

    # ── Registry callbacks ────────────────────────────────────────────────────

    def _collect_form(self) -> dict:
        """
        Read all form fields and return a normalised agent dict.

        Routing:
          - Bare IP (192.x, 10.x, 172.x, 127.x) → stored in 'ip' field
            so _agent_base_url always appends the port correctly.
          - Real URL (has :// or domain name) → stored in 'url' field.
        """
        import re
        atype   = self._reg_type_var.get()
        raw     = self._reg_url_entry.get().strip()
        try:
            port = int(self._reg_port_entry.get().strip())
        except ValueError:
            port = TYPE_META[atype]["port"]

        # Decide: is this a bare IP or a real URL?
        is_bare_ip = bool(re.match(r"^(\d{1,3}\.){3}\d{1,3}$", raw))
        is_real_url = ("://" in raw) or ("." in raw and not is_bare_ip)

        if is_bare_ip:
            # Store in ip field — _agent_base_url will append port
            url_val = ""
            ip_val  = raw
        elif is_real_url:
            # Store in url field — _agent_base_url uses as-is
            if "://" not in raw:
                raw = "https://" + raw
            url_val = raw
            ip_val  = ""
        else:
            # Fallback: treat as IP
            url_val = ""
            ip_val  = raw

        return {
            "type":     atype,
            "url":      url_val,
            "ip":       ip_val,
            "port":     port,
            "name":     self._reg_name_entry.get().strip() or "Agent",
            "role":     self._reg_role_var.get() or "Junior",
            "protocol": self._reg_proto_var.get(),
            "model":    self._reg_model_entry.get().strip(),
            "api_key":  self._reg_key_entry.get().strip(),
        }

    def _list_select(self, event):
        sel = self._reg_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._agents):
            return
        a = self._agents[idx]

        atype = a.get("type", "worker")
        self._reg_type_var.set(atype)  # triggers visibility update

        # URL/IP: show whichever is set
        url = a.get("url", "").strip() or a.get("ip", "").strip()
        self._reg_url_entry.delete(0, tk.END)
        self._reg_url_entry.insert(0, url)

        self._reg_port_entry.delete(0, tk.END)
        self._reg_port_entry.insert(0, str(a.get("port", TYPE_META[atype]["port"])))

        self._reg_name_entry.delete(0, tk.END)
        self._reg_name_entry.insert(0, a.get("name", ""))

        self._reg_role_var.set(a.get("role", "Junior"))
        self._reg_proto_var.set(a.get("protocol", TYPE_META[atype]["protocol"]))

        self._reg_model_entry.delete(0, tk.END)
        self._reg_model_entry.insert(0, a.get("model", ""))

        self._reg_key_entry.delete(0, tk.END)
        self._reg_key_entry.insert(0, a.get("api_key", ""))

        self._snd_target.delete(0, tk.END)
        self._snd_target.insert(
            0, _agent_base_url(a).replace("https://","").replace("http://",""))

        # Auto-switch task type based on agent protocol/type
        proto = a.get("protocol", TYPE_META[atype]["protocol"])
        if proto == "openai" or atype == "openai":
            self._snd_task_type.set("chat (openai)")
        elif proto == "ollama" or atype == "ollama":
            self._snd_task_type.set("chat (ollama)")
        else:
            self._snd_task_type.set("web_search")

        # Signal edit mode
        if hasattr(self, "_reg_save_btn"):
            self._reg_save_btn.config(text="💾 Update Agent")

    def _open_rules_editor(self):
        """
        Opens a Toplevel editor for the selected agent's delegation_rules.

        delegation_rules is a free-text field stored in workers.json that tells
        LYRA WHEN to automatically delegate to this agent:
          - Trigger conditions (e.g. "when user asks about weather")
          - Priority / preference over other agents
          - Task types this agent is best suited for
          - Constraints (e.g. "only for tasks > 500 tokens")

        The field is written to SOUL.md Agent Registry so LYRA reads it
        on every session start and applies it as a delegation policy.
        """
        sel = self._reg_list.curselection()
        if not sel:
            import tkinter.messagebox as mb
            mb.showwarning("No agent selected",
                           "Please select an agent from the list first.",
                           parent=self._root)
            return
        idx = sel[0]
        if idx >= len(self._agents):
            return
        agent = self._agents[idx]
        name  = agent.get("name", "Agent")

        # ── Toplevel window ───────────────────────────────────────────────
        win = tk.Toplevel(self._root)
        win.title(f"📋 Delegation Rules — {name}")
        win.geometry("620x480")
        win.resizable(True, True)
        win.grab_set()  # modal

        # Header
        ttk.Label(win,
                  text=f"Delegation Rules for: {name}",
                  font=("Arial", 11, "bold")).pack(anchor=tk.W, padx=12, pady=(12, 2))
        ttk.Label(win,
                  text="Define WHEN LYRA should automatically delegate tasks to this agent.\n"
                       "Written to SOUL.md — LYRA reads and applies these rules each session.",
                  font=("Arial", 9), foreground="#555555",
                  wraplength=590, justify=tk.LEFT).pack(anchor=tk.W, padx=12, pady=(0, 8))

        # Agent info strip
        info_frame = ttk.Frame(win, relief="groove", padding="6")
        info_frame.pack(fill=tk.X, padx=12, pady=(0, 8))
        atype = agent.get("type", "worker")
        model = agent.get("model", "")
        base  = _agent_base_url(agent)
        info_text = (f"Type: {atype}  |  Protocol: {agent.get('protocol','?')}  |  "
                     f"URL: {base}")
        if model:
            info_text += f"  |  Model: {model}"
        ttk.Label(info_frame, text=info_text,
                  font=("Courier", 9), foreground="#333333").pack(anchor=tk.W)

        # Placeholder hint
        placeholder = (
            "Examples:\n"
            "- Delegate all web_search tasks to this agent\n"
            "- Use for reasoning tasks (math, logic, code review)\n"
            "- Prefer this agent when query contains: weather, news, current events\n"
            "- Only use when local Ollama is unavailable\n"
            "- Priority: 1 (highest) — use before other agents of the same type\n"
            "- Max task size: any / only short queries (<200 words)\n"
            "- Language preference: German queries"
        )

        # Rules text area
        text_frame = ttk.Frame(win)
        text_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        rules_box = tk.Text(text_frame, font=("Arial", 10), wrap=tk.WORD,
                            relief="solid", borderwidth=1)
        rules_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(text_frame, command=rules_box.yview)
        rules_box.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Load existing rules or show placeholder
        existing = agent.get("delegation_rules", "")
        if existing:
            rules_box.insert("1.0", existing)
        else:
            rules_box.insert("1.0", placeholder)
            rules_box.config(foreground="#aaaaaa")

            def _clear_placeholder(event):
                if rules_box.cget("foreground") == "#aaaaaa":
                    rules_box.delete("1.0", tk.END)
                    rules_box.config(foreground="#000000")
            rules_box.bind("<FocusIn>", _clear_placeholder)

        # Buttons
        btn_frame = ttk.Frame(win)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 12))

        def _save_rules():
            rules_text = rules_box.get("1.0", tk.END).strip()
            # Don't save the placeholder text
            if rules_text == placeholder.strip():
                rules_text = ""
            self._agents[idx]["delegation_rules"] = rules_text
            self._cfg.save_workers(self._agents)
            self._save_and_update_soul()
            self._log(
                f"[Monitor] Delegation rules saved for {name} "
                f"({len(rules_text)} chars)", "SUCCESS")
            win.destroy()

        def _clear_rules():
            rules_box.delete("1.0", tk.END)
            rules_box.config(foreground="#000000")

        ttk.Button(btn_frame, text="💾 Save Rules",
                   command=_save_rules).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="🗑 Clear",
                   command=_clear_rules).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_frame, text="✖ Cancel",
                   command=win.destroy).pack(side=tk.RIGHT)

    def _check_agent(self):
        a       = self._collect_form()
        atype   = a["type"]
        base    = _agent_base_url(a)
        api_key = a.get("api_key", "")

        if atype == "openai":
            # Health check via /models — works for OpenAI (/v1/models) and
            # DeepSeek (/models) when base_url already includes /v1 if needed.
            url = f"{base}/models"
        elif atype == "ollama":
            url = f"{base}/api/tags"
        else:
            url = f"{base}/health"

        sc, body = _diag_api(url, timeout=6, api_key=api_key)
        if 0 < sc < 400:
            if isinstance(body, dict):
                if atype == "openai":
                    info = f"{len(body.get('data', []))} model(s) available"
                elif atype == "ollama":
                    info = f"{len(body.get('models', []))} model(s) loaded"
                else:
                    info = f"role={body.get('role','?')}"
            else:
                info = "OK"
            msg = f"✅ {base}  →  {info}"
            self._reg_status_lbl.config(text=msg, foreground="green")
            self._log(f"[Monitor] {msg}", "SUCCESS")
        else:
            msg = f"❌ {base}  →  HTTP {sc}  {str(body)[:60]}"
            self._reg_status_lbl.config(text=msg, foreground="red")
            self._log(f"[Monitor] {msg}", "ERROR")

    def _add_agent(self):
        entry = self._collect_form()
        base  = _agent_base_url(entry)
        for i, a in enumerate(self._agents):
            if _agent_base_url(a) == base:
                # Preserve delegation_rules — not in the form, only editable via Edit Rules
                entry["delegation_rules"] = a.get("delegation_rules", "")
                self._agents[i] = entry
                label = self._agent_label(entry, "??")
                self._set_list_item(i, label, None)
                self._log(f"[Monitor] Agent updated: {entry['name']} ({base})",
                          "SUCCESS")
                self._save_and_update_soul()
                return
        self._agents.append(entry)
        idx   = len(self._agents) - 1
        label = self._agent_label(entry, "??")
        self._reg_list.insert(tk.END, label)
        self._reg_list.itemconfig(idx, foreground="#888888")
        self._snd_target.delete(0, tk.END)
        self._snd_target.insert(
            0, base.replace("https://","").replace("http://",""))
        self._log(f"[Monitor] Agent added: {entry['name']} ({base})", "SUCCESS")
        self._save_and_update_soul()
        if hasattr(self, "_reg_save_btn"):
            self._reg_save_btn.config(text="💾 Save / Update")

    def _remove_agent(self):
        sel = self._reg_list.curselection()
        if not sel:
            self._log("[Monitor] No agent selected for removal", "INFO")
            return
        idx = sel[0]
        if idx >= len(self._agents):
            return
        removed = self._agents.pop(idx)
        self._reg_list.delete(idx)
        self._log(f"[Monitor] Agent removed: {removed.get('name','?')} "
                  f"({_agent_base_url(removed)})", "SUCCESS")
        self._save_and_update_soul()

    def _save_and_update_soul(self):
        self._cfg.save_workers(self._agents)
        self._cfg.write_soul_files(log_prefix="monitor-agent-update")
        self._log(f"[Monitor] workers.json saved + SOUL.md updated "
                  f"({len(self._agents)} agent(s))", "SUCCESS")

    # ── Task sender ───────────────────────────────────────────────────────────

    def _resolve_agent(self) -> dict | None:
        """Find agent matching the current target field."""
        target = self._snd_target.get().strip().rstrip("/")
        for a in self._agents:
            base = _agent_base_url(a).replace("https://","").replace("http://","")
            if target == base or target == _agent_base_url(a).rstrip("/"):
                return a
        return None

    def _send_task(self):
        ttype   = self._snd_task_type.get()
        message = self._snd_payload.get().strip()
        target  = self._snd_target.get().strip()
        agent   = self._resolve_agent()
        api_key = (agent or {}).get("api_key", "")
        model   = (agent or {}).get("model", "")

        url = target if "://" in target else f"http://{target}"
        url = url.rstrip("/")

        if ttype == "chat (openai)":
            self._send_openai_chat(url, message, model, api_key)
        elif ttype == "chat (ollama)":
            self._send_ollama_chat(url, message, model, api_key)
        else:
            self._send_openclaw_task(url, ttype, message)

    def _send_openclaw_task(self, url: str, ttype: str, text: str):
        if ttype == "web_search":
            payload = {"query": text}
        elif ttype == "batch_exec":
            payload = {"cmd": text}
        elif ttype == "summarize":
            payload = {"text": text}
        else:
            payload = {"content": text, "validate_type": "json"}

        self._log(f"[Monitor] OpenClaw {ttype} → {url}")
        sc, body = _diag_api(f"{url}/tasks", timeout=8, method="POST",
                              data={"type": ttype, "payload": payload})
        if sc == 200 and isinstance(body, dict) and body.get("accepted"):
            task_id = body.get("task_id", "?")
            self._snd_taskid_lbl.config(text=f"task_id: {task_id}")
            self._log(f"[Monitor] Task accepted: {task_id} — result will appear automatically",
                      "SUCCESS")
        else:
            self._snd_taskid_lbl.config(text=f"Error: HTTP {sc}")
            self._log(f"[Monitor] Send failed: HTTP {sc}  {str(body)[:80]}", "ERROR")

    def _send_openai_chat(self, url: str, message: str,
                          model: str, api_key: str):
        if not model:
            model = ("deepseek-chat" if "deepseek" in url.lower()
                     else "gpt-4o-mini")

        # Standard OpenAI-compatible endpoint.
        # For DeepSeek: set URL to https://api.deepseek.com/v1 (not /v1 appended here).
        endpoint = f"{url}/chat/completions"
        self._log(f"[Monitor] OpenAI chat → {endpoint}  model={model}")
        sc, body = _diag_api(
            endpoint, timeout=30, method="POST",
            data={"model": model,
                  "messages": [
                      {"role": "system", "content": "You are a helpful assistant."},
                      {"role": "user",   "content": message}
                  ],
                  "stream": False},
            api_key=api_key)
        if sc == 200 and isinstance(body, dict):
            try:
                reply = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                reply = json.dumps(body, indent=2, ensure_ascii=False)
            self._result_write(reply)
            self._snd_taskid_lbl.config(text="✅ Response received")
            self._log("[Monitor] OpenAI chat response received", "SUCCESS")
        else:
            self._result_write(
                f"HTTP {sc}\n" +
                (json.dumps(body, indent=2) if isinstance(body, dict) else str(body)))
            self._snd_taskid_lbl.config(text=f"Error: HTTP {sc}")
            self._log(f"[Monitor] OpenAI chat failed: HTTP {sc}", "ERROR")

    def _send_ollama_chat(self, url: str, message: str,
                          model: str, api_key: str):
        self._log(f"[Monitor] Ollama chat → {url}  model={model or 'default'}")
        sc, body = _diag_api(
            f"{url}/api/chat", timeout=60, method="POST",
            data={"model": model or "qwen2.5:7b",
                  "messages": [{"role": "user", "content": message}],
                  "stream": False},
            api_key=api_key)
        if sc == 200 and isinstance(body, dict):
            try:
                reply = body["message"]["content"]
            except (KeyError, TypeError):
                reply = json.dumps(body, indent=2, ensure_ascii=False)
            self._result_write(reply)
            self._snd_taskid_lbl.config(text="✅ Response received")
            self._log("[Monitor] Ollama chat response received", "SUCCESS")
        else:
            self._result_write(
                f"HTTP {sc}\n" +
                (json.dumps(body, indent=2) if isinstance(body, dict) else str(body)))
            self._snd_taskid_lbl.config(text=f"Error: HTTP {sc}")
            self._log(f"[Monitor] Ollama chat failed: HTTP {sc}", "ERROR")

    # ── Result viewer ─────────────────────────────────────────────────────────

    def _result_write(self, text: str):
        self._res_box.configure(state=tk.NORMAL)
        self._res_box.delete("1.0", tk.END)
        self._res_box.insert(tk.END, text)
        self._res_box.configure(state=tk.DISABLED)

    def _result_append(self, text: str):
        """Append text to result box (prepend separator if not empty)."""
        self._res_box.configure(state=tk.NORMAL)
        existing = self._res_box.get("1.0", tk.END).strip()
        if existing:
            self._res_box.insert(tk.END, "\n\n---\n\n")
        self._res_box.insert(tk.END, text)
        self._res_box.see(tk.END)
        self._res_box.configure(state=tk.DISABLED)

    def _clear_result_box(self):
        self._result_write("")
        if self._res_status_lbl:
            self._res_status_lbl.config(
                text="Cleared. Waiting for results from workers...",
                foreground="#888888")

    def _on_result_received(self, result: dict):
        """
        Called on main thread when LyraHeadServer receives a worker result.
        Auto-displays the result — no manual polling needed.
        """
        task_id = result.get("task_id", "?")
        status  = result.get("status", "?")
        worker  = result.get("worker", "?")
        icon    = "✅" if status == "success" else "⚠️"

        # Update status label
        if self._res_status_lbl:
            self._res_status_lbl.config(
                text=f"{icon} Result {task_id} from {worker} ({status})",
                foreground="#1a7f1a" if status == "success" else "#cc6600")

        # Append to result box
        text = json.dumps(result, indent=2, ensure_ascii=False)
        self._result_append(text)
        self._log(f"[Monitor] Auto-display: result {task_id} ({status}) from {worker}",
                  "SUCCESS" if status == "success" else "WARNING")

    def _local_head_url(self) -> str:
        """
        Returns the URL of Lyra's local LyraHeadServer.
        Results are always stored here — workers POST back to this URL.
        """
        return "http://127.0.0.1:18790"

    def _fetch_all_results(self):
        """GET /results from Lyra's local HeadServer — shows all stored results."""
        url = self._local_head_url()
        self._log(f"[Monitor] Fetching all results from local HeadServer ({url})")
        sc, body = _diag_api(f"{url}/results", timeout=8)
        if sc == 200 and isinstance(body, dict):
            results = body.get("results", [])
            if not results:
                self._result_write("No results stored yet in local HeadServer.")
            else:
                text = f"{len(results)} result(s) in local HeadServer:\n\n"
                for r in results:
                    text += json.dumps(r, indent=2, ensure_ascii=False)
                    text += "\n\n---\n\n"
                self._result_write(text)
            self._log(f"[Monitor] {len(results)} result(s) fetched", "SUCCESS")
        else:
            self._result_write(f"HTTP {sc}\n{str(body)}")
            self._log(f"[Monitor] All-results fetch failed: HTTP {sc}", "ERROR")
