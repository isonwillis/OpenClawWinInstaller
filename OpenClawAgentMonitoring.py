"""
OpenClawAgentMonitoring.py  –  v1.0.4
======================================
Agent Monitoring & Management Module — Lyra (Head) only.

Self-contained tkinter tab: GUI + logic in one place.
Integrated into OpenClawWinInstaller via MonitoringTab.build(notebook).

Architecture:
  MonitoringTab          — GUI owner, lifecycle, tkinter widgets
  _HealthPoller          — background thread, silent polling, no log spam
  _diag_api()            — shared HTTP helper (copied from Installer to avoid
                           circular import)

Sections:
  🖥  Worker Registry    — Add/remove workers, live ✅/❌ status, auto-refresh
  📤  Send Task          — POST /tasks to any registered worker
  📥  Result Viewer      — GET /result/<id> + GET /results
"""

from __future__ import annotations

import json
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import ttk
from typing import Callable


# ── Constants ─────────────────────────────────────────────────────────────────

POLL_INTERVAL_SEC = 30   # default background health-poll interval


# ── Standalone HTTP helper (mirrors OpenClawWinInstaller._diag_api) ───────────

def _diag_api(url: str, timeout: int = 8,
              method: str = "GET",
              data: dict | None = None) -> tuple[int, dict | str]:
    """
    Minimal HTTP helper — no external dependencies.
    Returns (status_code, body_as_dict_or_str).
    status_code = -1 on connection error.
    Replaces 'localhost' → '127.0.0.1' (Python 3.11 IPv6/Docker bug).
    """
    url = url.replace("//localhost:", "//127.0.0.1:")
    try:
        body_bytes = json.dumps(data).encode("utf-8") if data else None
        if method == "GET":
            headers = {"User-Agent": "LyraMonitor/1.0.4",
                       "Accept": "application/json, text/html, */*"}
        else:
            headers = {"Content-Type": "application/json",
                       "User-Agent": "LyraMonitor/1.0.4"}
        req = urllib.request.Request(
            url, data=body_bytes, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            raw = r.read(32_000).decode("utf-8", errors="replace").strip()
            for candidate in [raw, raw.lstrip("\ufeff"),
                              raw.split("\n", 1)[-1]]:
                try:
                    return status, json.loads(candidate)
                except Exception:
                    continue
            return status, raw
    except urllib.error.HTTPError as e:
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


# ── Background health poller ───────────────────────────────────────────────────

class _HealthPoller(threading.Thread):
    """
    Daemon thread that polls /health on all registered workers
    every `interval_sec` seconds.

    Results are delivered via callback(results: list[dict]) scheduled
    on the tkinter main thread via root.after(0, ...) — no direct widget
    access from the background thread.

    Worker result dict:
        {"worker": {...}, "online": bool, "role": str, "port": int}
    """

    def __init__(self,
                 get_workers: Callable[[], list[dict]],
                 on_result: Callable[[list[dict]], None],
                 root: tk.Tk,
                 interval_sec: int = POLL_INTERVAL_SEC):
        super().__init__(daemon=True, name="LyraHealthPoller")
        self._get_workers   = get_workers
        self._on_result     = on_result
        self._root          = root
        self._interval      = interval_sec
        self._stop_evt      = threading.Event()

    def stop(self):
        """Signal the polling loop to exit on next iteration."""
        self._stop_evt.set()

    def set_interval(self, seconds: int):
        self._interval = max(5, seconds)

    def run(self):
        """Poll once immediately, then every interval_sec seconds."""
        while not self._stop_evt.is_set():
            self._poll()
            self._stop_evt.wait(self._interval)

    def _poll(self):
        workers = self._get_workers()
        if not workers:
            return
        results = []
        for w in workers:
            url = f"http://{w['ip']}:{w['port']}/health"
            sc, body = _diag_api(url, timeout=4)
            online = (sc == 200 and isinstance(body, dict))
            results.append({
                "worker": w,
                "online": online,
                "role":   body.get("role", "?")  if online else "?",
                "port":   body.get("port", w["port"]) if online else w["port"],
            })
        # Deliver on main thread — safe tkinter access
        self._root.after(0, lambda r=results: self._on_result(r))


# ── MonitoringTab ──────────────────────────────────────────────────────────────

class MonitoringTab:
    """
    Self-contained Monitoring Tab for OpenClaw Lyra (Head).

    Usage in OpenClawWinInstaller._build_diag_tab():

        from OpenClawAgentMonitoring import MonitoringTab
        if role == "Lyra":
            self.monitoring = MonitoringTab(
                notebook = self.notebook,
                cfg      = self.cfg,
                log_fn   = self.log,
                root     = self.root,
            )
            self.monitoring.build()

    The tab registers itself into `notebook` as "📡 Monitoring".
    Call destroy() on app exit to stop the background poller.
    """

    def __init__(self,
                 notebook: ttk.Notebook,
                 cfg,               # OpenClawConfig instance
                 log_fn: Callable,  # log(msg, level="INFO")
                 root: tk.Tk):
        self._nb      = notebook
        self._cfg     = cfg
        self._log     = log_fn
        self._root    = root

        # Internal state
        self._workers: list[dict] = []   # {"ip", "port", "name", "role"}
        self._poller: _HealthPoller | None = None

        # Widget refs (populated in build())
        self._mon_ip_entry    = None
        self._mon_port_entry  = None
        self._mon_name_entry  = None
        self._mon_role_var    = None
        self._mon_worker_list = None
        self._mon_status_lbl  = None
        self._mon_target      = None
        self._mon_task_type   = None
        self._mon_payload     = None
        self._mon_taskid_lbl  = None
        self._mon_result_id   = None
        self._mon_result_box  = None

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self):
        """Create and register the Monitoring tab into the parent notebook."""
        frame = ttk.Frame(self._nb, padding="8")
        self._nb.add(frame, text="📡 Monitoring")
        self._build_ui(frame)
        # Load workers after UI is ready, start poller
        self._root.after(300, self._load_workers_and_start_poller)

    def destroy(self):
        """Stop background poller on app exit."""
        if self._poller:
            self._poller.stop()

    def get_first_worker_ip_port(self) -> str | None:
        """Return 'ip:port' of first registered worker, or None."""
        if self._workers:
            w = self._workers[0]
            return f"{w['ip']}:{w['port']}"
        return None

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, parent: ttk.Frame):
        """Build the three-section layout inside parent frame."""
        # Scrollable canvas wrapper
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
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_registry_section(outer)
        self._build_task_sender_section(outer)
        self._build_result_viewer_section(outer)

    def _build_registry_section(self, parent: ttk.Frame):
        """
        Section 1: Worker Registry.
        Shows all registered workers with live ✅/❌ status.
        Status is updated silently by _HealthPoller — no log entries.
        """
        lf = ttk.LabelFrame(parent, text="🖥  Worker Registry", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        # IP + Port row
        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r1, text="Worker IP:", width=11).pack(side=tk.LEFT)
        self._mon_ip_entry = ttk.Entry(r1, width=16)
        self._mon_ip_entry.insert(0, "192.168.2.102")
        self._mon_ip_entry.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(r1, text="Port:", width=4).pack(side=tk.LEFT)
        self._mon_port_entry = ttk.Entry(r1, width=6)
        self._mon_port_entry.insert(0, "18790")
        self._mon_port_entry.pack(side=tk.LEFT, padx=(4, 0))

        # Name + Role row
        r2 = ttk.Frame(lf)
        r2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r2, text="Name:", width=11).pack(side=tk.LEFT)
        self._mon_name_entry = ttk.Entry(r2, width=16)
        self._mon_name_entry.insert(0, "Junior-PC")
        self._mon_name_entry.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(r2, text="Role:", width=4).pack(side=tk.LEFT)
        self._mon_role_var = tk.StringVar(value="Junior")
        ttk.Combobox(r2, textvariable=self._mon_role_var,
                     values=["Junior", "Senior"],
                     width=8, state="readonly").pack(side=tk.LEFT, padx=(4, 0))

        # Action buttons
        r3 = ttk.Frame(lf)
        r3.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(r3, text="🔍 Check",
                   command=self._check_worker).pack(side=tk.LEFT)
        ttk.Button(r3, text="➕ Add & Save",
                   command=self._add_worker).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(r3, text="🗑 Remove selected",
                   command=self._remove_worker).pack(side=tk.LEFT, padx=(6, 0))

        # Worker listbox — status icons updated silently by poller
        self._mon_worker_list = tk.Listbox(
            lf, height=5, font=("Courier", 9), selectmode=tk.SINGLE)
        self._mon_worker_list.pack(fill=tk.X, pady=(4, 0))
        self._mon_worker_list.bind("<<ListboxSelect>>", self._list_select)

        # Inline status label (shows last check result for current entry fields)
        self._mon_status_lbl = ttk.Label(
            lf, text="", font=("Arial", 9), foreground="#555555")
        self._mon_status_lbl.pack(anchor=tk.W, pady=(4, 0))

    def _build_task_sender_section(self, parent: ttk.Frame):
        """Section 2: Task Sender — POST /tasks to a worker."""
        lf = ttk.LabelFrame(parent, text="📤  Send Task to Worker", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r1, text="Target IP:port", width=14).pack(side=tk.LEFT)
        self._mon_target = ttk.Entry(r1, width=22)
        self._mon_target.insert(0, "192.168.2.102:18790")
        self._mon_target.pack(side=tk.LEFT, padx=(4, 0))

        r2 = ttk.Frame(lf)
        r2.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r2, text="Task type:", width=14).pack(side=tk.LEFT)
        self._mon_task_type = ttk.Combobox(
            r2, values=["web_search", "batch_exec", "summarize", "validate"],
            width=16, state="readonly")
        self._mon_task_type.current(0)
        self._mon_task_type.pack(side=tk.LEFT, padx=(4, 0))

        r3 = ttk.Frame(lf)
        r3.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r3, text="Query / cmd:", width=14).pack(side=tk.LEFT)
        self._mon_payload = ttk.Entry(r3, width=40)
        self._mon_payload.insert(0, "Wetter Zürich aktuell")
        self._mon_payload.pack(side=tk.LEFT, padx=(4, 0), fill=tk.X, expand=True)

        r4 = ttk.Frame(lf)
        r4.pack(fill=tk.X)
        ttk.Button(r4, text="📤 Send Task",
                   command=self._send_task).pack(side=tk.LEFT)
        self._mon_taskid_lbl = ttk.Label(
            r4, text="", font=("Courier", 9), foreground="#0055aa")
        self._mon_taskid_lbl.pack(side=tk.LEFT, padx=(10, 0))

    def _build_result_viewer_section(self, parent: ttk.Frame):
        """Section 3: Result Viewer — GET /result/<id> or GET /results."""
        lf = ttk.LabelFrame(parent, text="📥  Result Viewer", padding="8")
        lf.pack(fill=tk.X, pady=(0, 8))

        r1 = ttk.Frame(lf)
        r1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r1, text="Task ID:", width=10).pack(side=tk.LEFT)
        self._mon_result_id = ttk.Entry(r1, width=16)
        self._mon_result_id.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(r1, text="📥 Fetch Result",
                   command=self._fetch_result).pack(side=tk.LEFT)
        ttk.Button(r1, text="📋 All Results",
                   command=self._fetch_all_results).pack(side=tk.LEFT, padx=(6, 0))

        self._mon_result_box = tk.Text(
            lf, height=10, font=("Courier", 9),
            wrap=tk.WORD, state=tk.DISABLED, background="#f8f8f8")
        self._mon_result_box.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        sb = ttk.Scrollbar(lf, command=self._mon_result_box.yview)
        self._mon_result_box.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Poller integration ────────────────────────────────────────────────────

    def _load_workers_and_start_poller(self):
        """Load workers.json, populate listbox, start background poller."""
        workers = self._cfg.load_workers()
        self._workers = workers
        self._mon_worker_list.delete(0, tk.END)
        for w in workers:
            self._mon_worker_list.insert(tk.END, self._worker_label(w, "⬜"))
        if workers:
            self._log(
                f"[Monitor] Loaded {len(workers)} worker(s) from workers.json",
                "SUCCESS")
            w0 = workers[0]
            self._mon_target.delete(0, tk.END)
            self._mon_target.insert(0, f"{w0['ip']}:{w0['port']}")

        # Start background poller — silent, no log entries per poll
        self._poller = _HealthPoller(
            get_workers = lambda: list(self._workers),
            on_result   = self._on_poll_result,
            root        = self._root,
            interval_sec= POLL_INTERVAL_SEC,
        )
        self._poller.start()

    def _on_poll_result(self, results: list[dict]):
        """
        Called on the main thread by _HealthPoller with fresh health data.
        Updates listbox icons silently — no log entries.
        """
        for i, res in enumerate(results):
            if i >= len(self._workers):
                break
            icon  = "✅" if res["online"] else "❌"
            label = self._worker_label(res["worker"], icon)
            try:
                self._mon_worker_list.delete(i)
                self._mon_worker_list.insert(i, label)
            except Exception:
                pass

    # ── Worker registry callbacks ─────────────────────────────────────────────

    def _worker_url(self, ip_port: str | None = None) -> str:
        """Build http://ip:port base URL from string or entry fields."""
        if ip_port:
            return ("http://" + ip_port if "://" not in ip_port
                    else ip_port).rstrip("/")
        ip   = self._mon_ip_entry.get().strip()
        port = self._mon_port_entry.get().strip() or "18790"
        return f"http://{ip}:{port}"

    def _worker_label(self, w: dict, status: str = "⬜") -> str:
        """Format worker dict into a fixed-width listbox string."""
        return (f"{status} {w.get('name', '?'):12s}  "
                f"{w.get('ip', '?')}:{w.get('port', 18790)}  "
                f"({w.get('role', '?')})")

    def _save_and_update_soul(self):
        """Persist workers.json and regenerate SOUL.md Worker Registry section."""
        self._cfg.save_workers(self._workers)
        self._cfg.write_soul_files(log_prefix="monitor-worker-update")
        self._log(
            f"[Monitor] workers.json saved + SOUL.md updated "
            f"({len(self._workers)} worker(s))", "SUCCESS")

    def _list_select(self, event):
        """Listbox click → prefill IP/port/name/role fields + target field."""
        sel = self._mon_worker_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._workers):
            return
        w = self._workers[idx]
        self._mon_ip_entry.delete(0, tk.END)
        self._mon_ip_entry.insert(0, w.get("ip", ""))
        self._mon_port_entry.delete(0, tk.END)
        self._mon_port_entry.insert(0, str(w.get("port", 18790)))
        self._mon_name_entry.delete(0, tk.END)
        self._mon_name_entry.insert(0, w.get("name", ""))
        self._mon_role_var.set(w.get("role", "Junior"))
        self._mon_target.delete(0, tk.END)
        self._mon_target.insert(0, f"{w['ip']}:{w['port']}")

    def _check_worker(self):
        """Check /health of the worker currently in the IP/port fields."""
        url    = self._worker_url()
        sc, body = _diag_api(f"{url}/health", timeout=5)
        if sc == 200 and isinstance(body, dict):
            role = body.get("role", "?")
            port = body.get("port", "?")
            msg  = f"✅ {url}  →  role={role}  port={port}"
            self._mon_status_lbl.config(text=msg, foreground="green")
            self._log(f"[Monitor] {msg}", "SUCCESS")
        else:
            msg = f"❌ {url}  →  HTTP {sc}  {str(body)[:60]}"
            self._mon_status_lbl.config(text=msg, foreground="red")
            self._log(f"[Monitor] {msg}", "ERROR")

    def _add_worker(self):
        """Add or update worker in registry → persist + update SOUL.md."""
        ip   = self._mon_ip_entry.get().strip()
        port = int(self._mon_port_entry.get().strip() or "18790")
        name = self._mon_name_entry.get().strip() or f"Worker-{ip}"
        role = self._mon_role_var.get() or "Junior"

        # Update existing entry if same IP:port
        for i, w in enumerate(self._workers):
            if w["ip"] == ip and w["port"] == port:
                self._workers[i] = {"ip": ip, "port": port,
                                    "name": name, "role": role}
                self._mon_worker_list.delete(i)
                self._mon_worker_list.insert(
                    i, self._worker_label(self._workers[i]))
                self._log(
                    f"[Monitor] Worker updated: {name} ({ip}:{port})", "SUCCESS")
                self._save_and_update_soul()
                return

        # New entry
        entry = {"ip": ip, "port": port, "name": name, "role": role}
        self._workers.append(entry)
        self._mon_worker_list.insert(tk.END, self._worker_label(entry))
        self._mon_target.delete(0, tk.END)
        self._mon_target.insert(0, f"{ip}:{port}")
        self._log(f"[Monitor] Worker added: {name} ({ip}:{port})", "SUCCESS")
        self._save_and_update_soul()

    def _remove_worker(self):
        """Remove selected worker from registry → persist + update SOUL.md."""
        sel = self._mon_worker_list.curselection()
        if not sel:
            self._log("[Monitor] No worker selected for removal", "INFO")
            return
        idx = sel[0]
        if idx >= len(self._workers):
            return
        removed = self._workers.pop(idx)
        self._mon_worker_list.delete(idx)
        self._log(
            f"[Monitor] Worker removed: {removed.get('name','?')} "
            f"({removed.get('ip','?')}:{removed.get('port','?')})", "SUCCESS")
        self._save_and_update_soul()

    # ── Task sender callbacks ─────────────────────────────────────────────────

    def _send_task(self):
        """Send a task to the selected worker via POST /tasks."""
        target       = self._mon_target.get().strip()
        url          = self._worker_url(target)
        ttype        = self._mon_task_type.get()
        payload_text = self._mon_payload.get().strip()

        if ttype == "web_search":
            payload = {"query": payload_text}
        elif ttype == "batch_exec":
            payload = {"cmd": payload_text}
        elif ttype == "summarize":
            payload = {"text": payload_text}
        else:
            payload = {"content": payload_text, "validate_type": "json"}

        self._log(
            f"[Monitor] Sending {ttype} → {url}  payload={payload_text[:50]}")
        sc, body = _diag_api(
            f"{url}/tasks", timeout=8, method="POST",
            data={"type": ttype, "payload": payload})

        if sc == 200 and isinstance(body, dict) and body.get("accepted"):
            task_id = body.get("task_id", "?")
            self._mon_taskid_lbl.config(text=f"task_id: {task_id}")
            self._mon_result_id.delete(0, tk.END)
            self._mon_result_id.insert(0, task_id)
            self._log(f"[Monitor] Task accepted: {task_id}", "SUCCESS")
        else:
            self._mon_taskid_lbl.config(text=f"Error: HTTP {sc}")
            self._log(
                f"[Monitor] Send failed: HTTP {sc}  {str(body)[:80]}", "ERROR")

    # ── Result viewer callbacks ───────────────────────────────────────────────

    def _result_write(self, text: str):
        """Write text into the result box (replaces existing content)."""
        self._mon_result_box.configure(state=tk.NORMAL)
        self._mon_result_box.delete("1.0", tk.END)
        self._mon_result_box.insert(tk.END, text)
        self._mon_result_box.configure(state=tk.DISABLED)

    def _fetch_result(self):
        """Fetch result for a specific task_id from the worker via GET /result/<id>."""
        target  = self._mon_target.get().strip()
        url     = self._worker_url(target)
        task_id = self._mon_result_id.get().strip()
        if not task_id:
            self._result_write("Enter a task_id first.")
            return
        self._log(f"[Monitor] Fetching result/{task_id} from {url}")
        sc, body = _diag_api(f"{url}/result/{task_id}", timeout=8)
        if sc == 200:
            self._result_write(
                json.dumps(body, indent=2, ensure_ascii=False))
            self._log(f"[Monitor] Result received for {task_id}", "SUCCESS")
        elif sc == 404:
            self._result_write(
                f"Result not yet available for task_id: {task_id}\n"
                f"(Worker may still be processing — retry in a few seconds)")
            self._log(f"[Monitor] Result not yet ready: {task_id}", "INFO")
        else:
            self._result_write(
                f"HTTP {sc}\n{json.dumps(body, indent=2)}")
            self._log(f"[Monitor] Fetch error: HTTP {sc}", "ERROR")

    def _fetch_all_results(self):
        """Fetch all stored results from the worker via GET /results (max 100)."""
        target = self._mon_target.get().strip()
        url    = self._worker_url(target)
        self._log(f"[Monitor] Fetching all results from {url}")
        sc, body = _diag_api(f"{url}/results", timeout=8)
        if sc == 200 and isinstance(body, dict):
            results = body.get("results", [])
            if not results:
                self._result_write("No results stored yet.")
            else:
                text = f"{len(results)} result(s):\n\n"
                for r in results:
                    text += json.dumps(r, indent=2, ensure_ascii=False)
                    text += "\n\n---\n\n"
                self._result_write(text)
            self._log(f"[Monitor] {len(results)} result(s) fetched", "SUCCESS")
        else:
            self._result_write(f"HTTP {sc}\n{str(body)}")
            self._log(
                f"[Monitor] All-results fetch failed: HTTP {sc}", "ERROR")
