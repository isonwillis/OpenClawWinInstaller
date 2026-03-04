#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClawWinInstaller.py  –  v1.0.2
====================================
GUI installer for OpenClaw / LYRA on Windows.
Handles the "New Installation" flow (Steps 1-16) and all GUI interactions.

All non-GUI logic lives in OpenClawConfigManagement.py:
  - OpenClawConfig             : config read/write (openclaw.json, auth-profiles, SOUL.md)
  - LyraDelegateToolRegistrar  : skill registration (delegate_to_worker.js)
  - LyraHeadServer             : HTTP task server for worker delegation
  - WorkerTaskServer           : task queue server on worker machines
  - LyraWorkerClient           : worker polling loop
  - OpenClawOperations         : all check_*/install_*/setup_* methods, run_powershell,
                                 WSL, Ollama, gateway, system utilities

OpenClawWinInstaller inherits OpenClawOperations so all operational methods
are available as self.X() — no extra wiring needed.
"""

# OpenClawWinInstaller.py  –  v1.0.2

from OpenClawConfigManagement import (
    OpenClawConfig, LyraDelegateToolRegistrar,
    LyraHeadServer, WorkerTaskServer, LyraWorkerClient,
    OpenClawOperations,
    LYRA_HEAD_PORT,
)

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import queue as queue_module
import time
import os
import json
import urllib.request
import urllib.error
import urllib.parse
import tempfile
import sys
import platform
import shutil
import uuid
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer

# ══════════════════════════════════════════════════════════════════════════════
# LYRA HEAD-WORKER COMMUNICATION
# ══════════════════════════════════════════════════════════════════════════════

class OpenClawWinInstaller(OpenClawOperations):
    def __init__(self, root):
        self.root = root
        self.root.title("OpenClaw Windows Setup  –  v1.0.3")
        self.root.geometry("1020x860")
        self.root.resizable(True, True)

        # ── Hardware profile (v1.0.3) — detect before config write ────────
        self._hw_profile: dict | None = None  # populated in _log_hardware_info

        # ── Configuration module (all config writes delegated here) ────────
        # Callbacks are set after full init because some (like self._npm_prefix)
        # depend on methods defined later in this class.
        self.cfg = OpenClawConfig(
            log_fn            = self.log,
            run_powershell_fn = self.run_powershell,
            npm_prefix_fn     = self._npm_prefix,
            apply_browser_fn  = self._apply_browser_config,
            machine_role      = getattr(self, "machine_role", "Lyra"),
        )

        self.installation_running = False
        self.auto_scroll = True
        self._diag_tab_built = False
        self._worker_client_diag = None
        import queue as _lq
        self._log_queue = _lq.Queue()

        # Read config early – determines whether to show dialog or direct tab
        self._saved_role, self._saved_head = self._read_machine_role_silent()

        self.setup_ui()

        self.log("=" * 70)
        self.log("OPENCLAW WINDOWS SETUP  –  v1.0.3")
        self.log("=" * 70)
        self.log(f"Python:   {sys.version.split()[0]}")
        self.log(f"System:   {platform.system()} {platform.release()} "
                 f"({platform.version()[:40]})")
        self.log(f"User:     {os.getenv('USERNAME', 'Unknown')}")
        self.root.after(200, self._log_hardware_info)
        self.log("=" * 70)
        self.root.after(500, self._startup_config_analysis)

    # ──────────────────────────────────────────────────────────────────
    # CONFIG EARLY READ (without dialog)
    # ──────────────────────────────────────────────────────────────────

    def _read_machine_role_silent(self):
        """Reads machine_role.json without dialog. Returns (role, head) or (None, None)."""
        role_file = os.path.join(os.path.expanduser("~"), ".openclaw", "machine_role.json")
        if os.path.isfile(role_file):
            try:
                with open(role_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                role = data.get("role")
                head = data.get("head_address") or None
                if role in ("Lyra", "Senior", "Junior"):
                    return role, head
            except Exception:
                pass
        return None, None

    def _log_hardware_info(self):
        """
        Runs HardwareProfile.detect() and logs the result.
        Called 200ms after startup so the log window is ready.
        Stores result in self._hw_profile for use by write_openclaw_config().
        """
        self.log("── HARDWARE PROFILE (v1.0.3) ────────────────────────────────────────────")
        try:
            hw = HardwareProfile(log_fn=self.log)
            profile = hw.detect()
            self._hw_profile = profile
            for line in hw.summary_lines():
                self.log(f"  {line}", "INFO")
            self.log(
                f"  → Recommended timeout: {profile['recommended_timeout']}s  "
                f"(current DECISION #3 default: 3600s)", "INFO"
            )
            if profile["recommended_timeout"] != 3600:
                self.log(
                    f"  ⚡ Hardware allows faster timeout — will use "
                    f"{profile['recommended_timeout']}s on next install/config-write",
                    "SUCCESS"
                )
            # Update pull entry default with HW-recommended model
            rec_model = profile.get("recommended_model", "glm-4.7-flash")
            if hasattr(self, "_pull_entry"):
                self._pull_entry.delete(0, tk.END)
                self._pull_entry.insert(0, rec_model)
                self.log(f"  Pull entry prefilled: {rec_model} (from HW profile)", "INFO")
        except Exception as e:
            self.log(f"  Hardware detection failed (non-fatal): {e}", "WARNING")
            self._hw_profile = None
        self.log("─" * 70)

    def _startup_config_analysis(self):
        """500ms after start: analyze config + build diagnostic tab.

        For Worker roles (Junior/Senior), schedules _auto_start_worker_components()
        1.5s after app start so WorkerTaskServer + QueuedWorkerClient are always active
        without requiring a fresh installation run.
        """
        role = self._saved_role
        self.log("")
        self.log("── CONFIG ANALYSIS ──────────────────────────────────────────────────────")
        if role:
            head = self._saved_head
            self.log(f"  machine_role.json: Role={role}" +
                     (f"  Head={head}" if head else ""), "SUCCESS")
            self._build_diag_tab(role, head)
            # Auto-start Worker components on app launch
            if role in ("Junior", "Senior"):
                self.log(f"  Worker role detected – scheduling component auto-start (1.5s)...")
                self.root.after(1500, self._auto_start_worker_components)
        else:
            self.log("  machine_role.json: not found", "WARNING")
            self.log("  → Diagnostic tab appears after 'New installation' (role selection).")

        # Check openclaw.json
        cfg_dir = self.cfg._find_openclaw_config_dir()
        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                gw = cfg.get("gateway", {})
                auth_mode = gw.get("auth", {}).get("mode", "?")
                token = gw.get("auth", {}).get("token", "")
                search_en = (cfg.get("tools", {}).get("web", {})
                               .get("search", {}).get("enabled", "?"))
                status_str = (f"  openclaw.json: auth.mode={auth_mode}  "
                              f"web.search={search_en}  token={'ok' if token else '?'}")
                lvl = "WARNING" if search_en is True else "SUCCESS"
                self.log(status_str, lvl)
                if search_en is True:
                    self.log("  ⚠️  web.search.enabled=true → Brave tool active → "
                             "Delegation broken! Please reinstall (v1.0.1+).", "WARNING")
            except Exception as e:
                self.log(f"  openclaw.json read error: {e}", "WARNING")
        else:
            self.log("  openclaw.json: not found (OpenClaw not installed?)", "WARNING")
        self.log("─" * 60)

    def _auto_start_worker_components(self):
        """Auto-start WorkerTaskServer + QueuedWorkerClient on app launch.

        Called automatically 1.5s after app start when machine_role.json
        indicates a Worker role (Junior/Senior). This ensures the worker is always
        active without requiring the user to click "New installation".

        Reads all parameters from persisted files:
          - role + head_address: machine_role.json
          - searxng_url: machine_role.json (saved by Worker Config tab)
          - worker model: openclaw.json (agents.defaults.model.primary, stripped of prefix)
            Fallback: qwen2.5:0.5b (Junior) / qwen2.5:1.5b (Senior)

        Skips start if components are already active (e.g. after a fresh installation).
        Stores results in self._worker_server and self._worker_client.
        """
        # ── Read persisted config ─────────────────────────────────────────────
        try:
            role_file = os.path.join(os.path.expanduser("~"), ".openclaw",
                                     "machine_role.json")
            with open(role_file, "r", encoding="utf-8") as f:
                role_data = json.load(f)
            role        = role_data.get("role", "Junior")
            head        = role_data.get("head_address", "")
            sx_url      = role_data.get("searxng_url", "http://127.0.0.1:8080")
        except Exception as e:
            self.log(f"[AutoStart] Cannot read machine_role.json: {e}", "ERROR")
            return

        if not head:
            self.log("[AutoStart] No head_address in machine_role.json – skipping.", "WARNING")
            return

        # Resolve model from openclaw.json, fallback to role default
        default_model = "qwen2.5:0.5b" if role == "Junior" else "qwen2.5:1.5b"
        worker_model  = default_model
        try:
            cfg_dir  = self.cfg._find_openclaw_config_dir()
            cfg_path = os.path.join(cfg_dir, "openclaw.json")
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            primary = (cfg.get("agents", {}).get("defaults", {})
                          .get("model", {}).get("primary", ""))
            if primary:
                worker_model = primary.replace("ollama/", "")
        except Exception:
            pass  # Fallback already set

        self.log(f"[AutoStart] Role: {role} | Head: {head} | Model: {worker_model}")

        # ── Skip if already running ───────────────────────────────────────────
        existing_server = getattr(self, "_worker_server", None)
        existing_client = getattr(self, "_worker_client", None)
        server_alive = (existing_server is not None and
                        getattr(existing_server, "_server", None) is not None)
        client_alive = (existing_client is not None and
                        hasattr(existing_client, "_thread") and
                        existing_client._thread is not None and
                        existing_client._thread.is_alive())
        if server_alive or client_alive:
            self.log("[AutoStart] Components already active – skipping.", "SUCCESS")
            return

        # ── Start Task Server ─────────────────────────────────────────────────
        import queue as _q
        task_queue = _q.Queue()

        worker_server = WorkerTaskServer(
            port=LYRA_HEAD_PORT,
            log_fn=self.log,
            task_queue=task_queue
        )
        if worker_server.start():
            self._worker_server = worker_server
            self.log(f"[AutoStart] Task server started on port {LYRA_HEAD_PORT} ✓",
                     "SUCCESS")
        else:
            self.log(f"[AutoStart] Task server start failed – port {LYRA_HEAD_PORT} in use?",
                     "WARNING")
            # Port in use = server probably from previous run still active, continue anyway

        # ── Start QueuedWorkerClient ──────────────────────────────────────────
        worker_client = self._make_queued_worker_client(
            head_address=head,
            role=role,
            model=worker_model,
            task_queue=task_queue,
            searxng_url=sx_url
        )
        worker_client.start()
        self._worker_client      = worker_client
        self._worker_client_diag = worker_client
        self.log(f"[AutoStart] Worker client started ✓", "SUCCESS")

        # Update loop status label if tab is already built
        if hasattr(self, "_w_loop_status"):
            self._w_loop_status.config(
                text=f"✅ Loop ACTIVE (auto-started) → {head}:{LYRA_HEAD_PORT}",
                foreground="green")

    def _make_queued_worker_client(self, head_address: str, role: str, model: str,
                                   task_queue, searxng_url: str = "http://127.0.0.1:8080"):
        """Factory: create a QueuedWorkerClient connected to the given task_queue.

        Extracted from the local class definition inside _install_worker_mode
        so that _auto_start_worker_components and _restart_worker_loop can both create
        the correct client type (queue-based) without code duplication.

        QueuedWorkerClient overrides LyraWorkerClient._poll_loop() to read from a
        thread-safe queue instead of HTTP polling the HEAD. Tasks arrive via
        WorkerTaskServer (HTTP POST /tasks → queue.put) and results are sent back
        to HEAD via POST /result.

        Args:
            head_address: IP/hostname of the LYRA HEAD machine.
            role:         "Junior" or "Senior" — used only for log labels.
            model:        Ollama model name (without "ollama/" prefix).
            task_queue:   threading.Queue shared with WorkerTaskServer.
            searxng_url:  SearXNG base URL for web_search tasks.

        Returns:
            QueuedWorkerClient instance (not yet started — call .start()).
        """
        import queue as _q

        log_fn     = self.log
        _LYRA_PORT = LYRA_HEAD_PORT

        class QueuedWorkerClient(LyraWorkerClient):
            def __init__(self, head_address, role, model, task_queue,
                         log_fn=None, poll_interval=7):
                super().__init__(head_address, role, model, log_fn, poll_interval)
                self.task_queue = task_queue
                self._stop      = threading.Event()
                self._thread    = None

            def _poll_loop(self):
                """Get tasks from queue instead of HTTP polling HEAD."""
                import queue as _queue_mod
                self.log(f"[Worker] Queue worker started ({self.role} | Model: {self.model})", "SUCCESS")
                while not self._stop.is_set():
                    try:
                        task = self.task_queue.get(timeout=1.0)
                        if task:
                            self.log(
                                f"[Worker] Task taken: {task['task_id']} ({task['type']})",
                                "INFO")
                            result_data = self._execute_task(task)
                            posted = self._post("/result", result_data, timeout=30)
                            icon = "✓" if result_data["status"] == "success" else "✗"
                            if posted and posted.get("integrated"):
                                self.log(
                                    f"[DELEGATION] {icon} Task {task['task_id']} "
                                    f"({task['type']}) {result_data['status']}", "SUCCESS")
                            else:
                                self.log("[DELEGATION] Result transmission failed!",
                                         "WARNING")
                    except _queue_mod.Empty:
                        pass
                    except Exception as e:
                        self.log(f"[Worker] Queue loop error: {e}", "WARNING")
                        time.sleep(1)
                self.log("[Worker] Queue worker stopped.", "INFO")

            def start(self):
                self._stop.clear()
                self._thread = threading.Thread(target=self._poll_loop, daemon=True)
                self._thread.start()

            def stop(self):
                self._stop.set()

        client = QueuedWorkerClient(
            head_address=head_address,
            role=role,
            model=model,
            task_queue=task_queue,
            log_fn=log_fn,
            poll_interval=7
        )
        client._searxng_url = searxng_url
        return client

    # ──────────────────────────────────────────────────────────────────
    # UI SETUP
    # ──────────────────────────────────────────────────────────────────

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="12")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(main_frame)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="OpenClaw — v1.0.2",
                  font=("Arial", 15, "bold")).pack(side=tk.LEFT)
        role_display = (f"  [{self._saved_role}]" if self._saved_role else "  [Role unknown]")
        self._role_badge = ttk.Label(header, text=role_display,
                                     font=("Arial", 10, "italic"), foreground="#555")
        self._role_badge.pack(side=tk.LEFT, padx=8)

        # Main button + status
        btn_row = ttk.Frame(main_frame)
        btn_row.pack(fill=tk.X, pady=(0, 3))
        self.main_button = ttk.Button(
            btn_row, text="🔄 New installation",
            command=self.start_installation, style="Big.TButton"
        )
        self.main_button.pack(side=tk.LEFT, padx=(0, 10))
        self.status_label = ttk.Label(btn_row, text="", font=("Arial", 9, "italic"))
        self.status_label.pack(side=tk.LEFT)

        style = ttk.Style()
        style.configure("Big.TButton", font=("Arial", 11, "bold"), padding=7)

        self.progress = ttk.Progressbar(main_frame, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill=tk.X, pady=(0, 5))

        # Notebook (Tabs)
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 0: Log (always visible)
        log_frame = ttk.Frame(self.notebook, padding="4")
        self.notebook.add(log_frame, text="📋 Log")

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=26, width=115,
            font=("Consolas", 9), wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Disable auto-scroll when user scrolls up, re-enable when at bottom
        def _on_scroll(*args):
            # args from scrollbar: ('moveto', fraction) or ('scroll', n, unit)
            # Check if scrolled to bottom
            self.log_text.yview(*args)
            pos = self.log_text.yview()
            self.auto_scroll = (pos[1] >= 0.999)

        self.log_text.vbar.config(command=_on_scroll)

        def _on_mousewheel(e):
            self.log_text.yview_scroll(int(-1 * (e.delta / 120)), "units")
            pos = self.log_text.yview()
            self.auto_scroll = (pos[1] >= 0.999)

        self.log_text.bind("<MouseWheel>", _on_mousewheel)

        ctx = tk.Menu(self.root, tearoff=0)
        ctx.add_command(label="Copy",       command=self._copy_sel)
        ctx.add_command(label="Copy all", command=self._copy_all)
        ctx.add_separator()
        ctx.add_command(label="Clear log",   command=self._clear)
        self.log_text.bind("<Button-3>", lambda e: ctx.tk_popup(e.x_root, e.y_root))

        # Tab 1: Diagnostics (dynamically populated)
        self._diag_tab_frame = None
        self._flush_log_queue()

    # ──────────────────────────────────────────────────────────────────
    # DIAGNOSTIC TAB SETUP
    # ──────────────────────────────────────────────────────────────────

    def _build_diag_tab(self, role: str, head: str | None):
        """Builds the dynamic diagnostic tab based on the role."""
        if self._diag_tab_built:
            return
        self._diag_tab_built = True

        tab_title = "🖥  Lyra Config" if role == "Lyra" else "⚙  Worker Config"
        frame = ttk.Frame(self.notebook, padding="8")
        self.notebook.add(frame, text=tab_title)
        self._diag_tab_frame = frame
        # Switch to diagnostic tab
        self.notebook.select(frame)

        if role == "Lyra":
            self._build_lyra_tab(frame)
        else:
            self._build_worker_tab(frame, role, head or "")

    def _dlog(self, msg: str, level: str = "INFO"):
        """Writes to the main log (called from diagnostic callbacks)."""
        self.log(msg, level)
        # Switch to log tab so user sees real-time updates
        self.notebook.select(0)
        self.root.after(1200, lambda: self.notebook.select(1)
                        if self.notebook.index("end") > 1 else None)

    def _diag_api(self, url: str, timeout: int = 8,
                  method: str = "GET", data: dict | None = None) -> tuple[int, dict | str]:
        """HTTP test with detailed error logging. Returns (status, body).
        Important: replaces 'localhost' → '127.0.0.1' (Python 3.11 IPv6 bug with Docker Desktop).
        For GET: no Content-Type header (SearXNG behaves differently with app/json).
        body is dict if JSON parsing succeeds, otherwise str.
        Order: read body first, then status (r.status after read() is stable)."""
        url = url.replace("//localhost:", "//127.0.0.1:")
        try:
            body_bytes = json.dumps(data).encode("utf-8") if data else None
            # GET requests without Content-Type (some APIs react differently)
            if method == "GET":
                headers = {"User-Agent": "LyraDiag/38.91",
                           "Accept": "application/json, text/html, */*"}
            else:
                headers = {"Content-Type": "application/json",
                           "User-Agent": "LyraDiag/38.91"}
            req = urllib.request.Request(url, data=body_bytes, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status = r.status          # save status BEFORE read()
                raw = r.read(32_000).decode("utf-8", errors="replace").strip()
                # JSON parse: multiple attempts (remove BOM, whitespace)
                parsed = None
                for candidate in [raw, raw.lstrip("\ufeff"), raw.split("\n", 1)[-1]]:
                    try:
                        parsed = json.loads(candidate)
                        break
                    except Exception:
                        continue
                return status, (parsed if parsed is not None else raw)
        except urllib.error.HTTPError as e:
            try:
                body = e.read(2000).decode("utf-8", errors="replace")
            except Exception:
                body = ""
            # Try to parse HTTPError body as JSON
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, body
        except Exception as e:
            return -1, str(e)

    # ── LYRA CONFIG TAB ───────────────────────────────────────────────

    def _build_lyra_tab(self, parent):
        """Build the Lyra Config tab with a two-column layout.

        Left column  — operational controls: Network IPs, Task Server, Dummy
                        Task Test, SearXNG, Gateway, Quick Fix.
        Right column — LLM Model Manager: primary/secondary model selection,
                        live model list via Ollama REST API, pull-new-model UI,
                        and timeout status indicator.

        Both columns share a single scrollable canvas so the full tab scrolls
        as one unit regardless of which side is taller.
        """
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outer = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        pad = {"padx": 6, "pady": 3}

        # ── Left column ───────────────────────────────────────────────
        left = ttk.Frame(outer)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # Network IPs
        sec1 = ttk.LabelFrame(left, text="🌐 Network – own IPs", padding="8")
        sec1.pack(fill=tk.X, **pad)
        self._ip_label = ttk.Label(sec1, text="(loading...)", font=("Consolas", 9))
        self._ip_label.pack(anchor=tk.W)
        ttk.Button(sec1, text="Refresh IPs",
                   command=self._refresh_ips).pack(anchor=tk.W, pady=(4, 0))
        self.root.after(600, self._refresh_ips)

        # Task Server
        sec2 = ttk.LabelFrame(left, text="⚡ Task Server  (Port 18790)", padding="8")
        sec2.pack(fill=tk.X, **pad)
        self._ts_status = ttk.Label(sec2, text="Status: unknown", font=("Consolas", 9))
        self._ts_status.pack(anchor=tk.W)
        btn_row2 = ttk.Frame(sec2)
        btn_row2.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(btn_row2, text="Check status",
                   command=self._check_task_server).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row2, text="(Re)start",
                   command=self._start_task_server).pack(side=tk.LEFT)

        # Dummy Task Test
        sec3 = ttk.LabelFrame(left, text="🧪 Dummy Task Test (web_search → Worker)",
                               padding="8")
        sec3.pack(fill=tk.X, **pad)
        self._dt_status = ttk.Label(sec3, text="Not sent yet", font=("Consolas", 9))
        self._dt_status.pack(anchor=tk.W)

        # Worker IP row  (v1.0.0: task goes directly to Worker's WorkerTaskServer)
        wip_row = ttk.Frame(sec3)
        wip_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(wip_row, text="Worker IP:", width=10).pack(side=tk.LEFT)
        self._dt_worker_ip = ttk.Entry(wip_row, width=18)
        self._dt_worker_ip.insert(0, "")   # empty = use 127.0.0.1 (local)
        self._dt_worker_ip.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Label(wip_row, text="(empty = local 127.0.0.1)",
                  font=("Arial", 8), foreground="#888").pack(side=tk.LEFT)

        dt_row = ttk.Frame(sec3)
        dt_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(dt_row, text="Query:").pack(side=tk.LEFT)
        self._dt_query = ttk.Entry(dt_row, width=26)
        self._dt_query.insert(0, "Weather Zurich current")
        self._dt_query.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(dt_row, text="▶ Send task + wait",
                   command=self._send_dummy_task).pack(side=tk.LEFT)
        ttk.Button(dt_row, text="🔄 Last worker",
                   command=self._fill_last_worker_ip).pack(side=tk.LEFT, padx=(6, 0))

        # Auto-fill worker IP from last HeadServer result after 2s
        self.root.after(2000, self._fill_last_worker_ip)

        # SearXNG
        sec4 = ttk.LabelFrame(left, text="🔍 SearXNG", padding="8")
        sec4.pack(fill=tk.X, **pad)
        sx_url_row = ttk.Frame(sec4)
        sx_url_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(sx_url_row, text="SearXNG URL:", width=14).pack(side=tk.LEFT)
        self._sx_url_lyra = ttk.Entry(sx_url_row, width=26)
        self._sx_url_lyra.insert(0, "http://127.0.0.1:8080")
        self._sx_url_lyra.pack(side=tk.LEFT, padx=4)
        self._sx_status_lyra = ttk.Label(sec4, text="Status: unknown", font=("Consolas", 9))
        self._sx_status_lyra.pack(anchor=tk.W)
        sx_row = ttk.Frame(sec4)
        sx_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(sx_row, text="Check",
                   command=lambda: self._check_searxng(
                       self._sx_status_lyra, self._sx_url_lyra.get())).pack(
                       side=tk.LEFT, padx=(0, 4))
        ttk.Button(sx_row, text="Enable JSON (403 fix)",
                   command=lambda: self._fix_searxng_json_format(
                       self._sx_url_lyra.get())).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(sx_row, text="Start",
                   command=lambda: self._start_searxng(self._sx_url_lyra.get())).pack(
                       side=tk.LEFT)
        sx_row2 = ttk.Frame(sec4)
        sx_row2.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(sx_row2, text="⚡ Scan ports (8080-9000)",
                   command=lambda: self._scan_searxng_port(self._sx_url_lyra)).pack(
                       side=tk.LEFT)

        # OpenClaw Gateway
        sec5 = ttk.LabelFrame(left, text="🚪 OpenClaw Gateway  (Port 18789)", padding="8")
        sec5.pack(fill=tk.X, **pad)
        self._gw_status = ttk.Label(sec5, text="Status: unknown", font=("Consolas", 9))
        self._gw_status.pack(anchor=tk.W)
        gw_row = ttk.Frame(sec5)
        gw_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(gw_row, text="Check Gateway",
                   command=self._check_gateway).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(gw_row, text="(Re)start Gateway",
                   command=self._restart_gateway).pack(side=tk.LEFT)

        # Quick Fix
        sec6 = ttk.LabelFrame(left, text="🛠  Quick Fix", padding="8")
        sec6.pack(fill=tk.X, **pad)
        ttk.Label(sec6,
                  text="Brave Search key loop → disable internal search:",
                  font=("Arial", 9)).pack(anchor=tk.W)
        ttk.Button(sec6, text="⚡ Disable Brave Search + restart Gateway",
                   command=self._apply_search_fix).pack(anchor=tk.W, pady=(4, 0))
        ttk.Separator(sec6, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Label(sec6,
                  text="Firefox users: set managed Chromium as browser profile:",
                  font=("Arial", 9)).pack(anchor=tk.W)
        ttk.Button(sec6, text="🌐 Apply browser profile (openclaw) + restart Gateway",
                   command=self._apply_browser_config_and_restart
                   ).pack(anchor=tk.W, pady=(4, 0))

        # Update SOUL.md
        sec7 = ttk.LabelFrame(left, text="🛠  Update Config + Fixes", padding="8")
        sec7.pack(fill=tk.X, **pad)
        ttk.Label(sec7,
                  text=("Writes latest SOUL.md/BOOTSTRAP.md to workspace (LYRA additions preserved).\n"
                        "Applies adaptive config fixes to openclaw.json (never overwrites valid values).\n"
                        "No reinstall required — takes effect after Gateway restart."),
                  font=("Arial", 9), wraplength=320).pack(anchor=tk.W)
        self._soul_update_status = ttk.Label(sec7, text="", font=("Consolas", 9),
                                              foreground="#555555")
        self._soul_update_status.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(sec7, text="🛠 Apply fixes + Update SOUL.md + restart Gateway",
                   command=self._apply_fixes_and_update).pack(anchor=tk.W, pady=(4, 0))

        # ── Right column — LLM Model Manager ─────────────────────────
        right = ttk.Frame(outer)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        sec_llm = ttk.LabelFrame(right, text="🧠 LLM Model Manager", padding="10")
        sec_llm.pack(fill=tk.BOTH, expand=True, **pad)

        ttk.Label(sec_llm,
                  text="Changes take effect after a Gateway restart.",
                  font=("Arial", 9), foreground="#888888").pack(anchor=tk.W, pady=(0, 6))

        # Primary model row
        row_p = ttk.Frame(sec_llm)
        row_p.pack(fill=tk.X, pady=3)
        ttk.Label(row_p, text="Primary LLM:", width=14).pack(side=tk.LEFT)
        self._llm_primary_var = tk.StringVar()
        self._llm_primary_cb = ttk.Combobox(row_p, textvariable=self._llm_primary_var,
                                             state="readonly", width=26)
        self._llm_primary_cb.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(row_p, text="✅ Set",
                   command=self._set_primary_llm).pack(side=tk.LEFT)

        # Secondary model row
        row_s = ttk.Frame(sec_llm)
        row_s.pack(fill=tk.X, pady=3)
        ttk.Label(row_s, text="Secondary LLM:", width=14).pack(side=tk.LEFT)
        self._llm_secondary_var = tk.StringVar()
        self._llm_secondary_cb = ttk.Combobox(row_s, textvariable=self._llm_secondary_var,
                                               state="readonly", width=26)
        self._llm_secondary_cb.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(row_s, text="✅ Set",
                   command=self._set_secondary_llm).pack(side=tk.LEFT)

        # Timeout indicator
        self._timeout_info = ttk.Label(
            sec_llm,
            text="⏱  timeoutSeconds: —",
            font=("Consolas", 8), foreground="#888888")
        self._timeout_info.pack(anchor=tk.W, pady=(4, 0))

        # Status label
        self._llm_set_status = ttk.Label(sec_llm, text="", font=("Consolas", 9),
                                          wraplength=320)
        self._llm_set_status.pack(anchor=tk.W, pady=(2, 2))

        # Refresh button
        ttk.Button(sec_llm, text="🔄 Refresh model list",
                   command=self._refresh_ollama_models).pack(anchor=tk.W, pady=(4, 8))

        ttk.Separator(sec_llm, orient="horizontal").pack(fill=tk.X, pady=4)

        # Pull new model
        pull_lf = ttk.LabelFrame(sec_llm, text="⬇  Pull new model into Ollama",
                                  padding="8")
        pull_lf.pack(fill=tk.X, pady=(4, 0))
        pull_row = ttk.Frame(pull_lf)
        pull_row.pack(fill=tk.X)
        ttk.Label(pull_row, text="Model name:", width=12).pack(side=tk.LEFT)
        self._pull_entry = ttk.Entry(pull_row, width=22)
        self._pull_entry.insert(0, "glm-4.7-flash")
        self._pull_entry.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(pull_row, text="⬇ Pull",
                   command=self._pull_ollama_model).pack(side=tk.LEFT)
        self._pull_status = ttk.Label(
            pull_lf,
            text="Recommended: glm-4.7-flash · qwen2.5:14b · qwen2.5:32b",
            font=("Arial", 8), foreground="#888888", wraplength=300)
        self._pull_status.pack(anchor=tk.W, pady=(6, 0))

        # Auto-load model list on tab open
        self.root.after(900, self._refresh_ollama_models)

    # ── WORKER CONFIG TAB ─────────────────────────────────────────────

    def _build_worker_tab(self, parent, role: str, head: str):
        """Build the Worker Config tab with two-column layout.

        Restructured from single-column to two-column layout matching
        the Lyra Config tab. Left column contains operational controls (connection,
        components, loop, SearXNG). Right column contains the LLM Model Manager
        and a Gateway restart section — identical capabilities to the HEAD tab.

        Left column:
          🔗 LYRA Head Connection  — IP, port, token, test + save
          🔄 Worker Components     — Task Server + Client status, check button
          🔄 Worker Poll Loop      — Start / Stop loop
          🔍 SearXNG               — URL, check, JSON fix, port scan
          🚪 Gateway (Worker)      — Check + Restart gateway.cmd (port 18789)
          ℹ  Diagnostic log        — Hint pointing to Log tab

        Right column:
          🧠 LLM Model Manager (Worker)
            Primary / Secondary dropdowns (Ollama REST API)
            ✅ Set buttons → _write_llm_to_config() (worker branch, no restart hint)
            🔄 Refresh model list
          ⬇ Pull new model into Ollama
            Model name entry + ⬇ Pull button → live output in Log tab

        Auto-loads model list 1.2s after tab creation.
        Auto-checks gateway status 1.2s after tab creation.
        """
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outer = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        pad = {"padx": 6, "pady": 3}

        # ── Left column ───────────────────────────────────────────────────
        left = ttk.Frame(outer)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))

        # ── Connection Configuration ─────────────────────────────────
        sec1 = ttk.LabelFrame(left,
                               text=f"🔗 LYRA Head Connection  ({role})", padding="8")
        sec1.pack(fill=tk.X, **pad)

        row1 = ttk.Frame(sec1); row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="LYRA Head IP / Host:", width=22).pack(side=tk.LEFT)
        self._w_head_entry = ttk.Entry(row1, width=28)
        self._w_head_entry.insert(0, head)
        self._w_head_entry.pack(side=tk.LEFT, padx=4)

        row2 = ttk.Frame(sec1); row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text="Task Server Port:", width=22).pack(side=tk.LEFT)
        self._w_port_entry = ttk.Entry(row2, width=8)
        self._w_port_entry.insert(0, str(LYRA_HEAD_PORT))
        self._w_port_entry.pack(side=tk.LEFT, padx=4)

        row3 = ttk.Frame(sec1); row3.pack(fill=tk.X, pady=2)
        ttk.Label(row3, text="Gateway Token (Head):", width=22).pack(side=tk.LEFT)
        self._w_token_entry = ttk.Entry(row3, width=24)
        self._w_token_entry.insert(0, "lyra-local-token")
        self._w_token_entry.pack(side=tk.LEFT, padx=4)

        self._w_conn_status = ttk.Label(sec1, text="Connection: not tested",
                                        font=("Consolas", 9))
        self._w_conn_status.pack(anchor=tk.W, pady=(6, 0))

        btn_row1 = ttk.Frame(sec1); btn_row1.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(btn_row1, text="🔌 Test connection",
                   command=self._test_worker_conn).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row1, text="💾 Save config & restart loop",
                   command=lambda: self._save_worker_config(role)).pack(side=tk.LEFT)

        # ── Worker Components Status ─────────────────────────────────
        sec_components = ttk.LabelFrame(left, text="🔄 Worker Components", padding="8")
        sec_components.pack(fill=tk.X, **pad)

        self._w_server_status = ttk.Label(sec_components,
                                          text="Task Server: unknown",
                                          font=("Consolas", 9))
        self._w_server_status.pack(anchor=tk.W)

        self._w_client_status = ttk.Label(sec_components,
                                          text="Worker Client: unknown",
                                          font=("Consolas", 9))
        self._w_client_status.pack(anchor=tk.W)

        btn_row_comp = ttk.Frame(sec_components)
        btn_row_comp.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(btn_row_comp, text="🔄 Check components",
                   command=self._check_worker_components).pack(side=tk.LEFT, padx=(0, 6))

        # ── Worker Poll Loop ──────────────────────────────────────────
        sec2 = ttk.LabelFrame(left, text="🔄 Worker Poll Loop", padding="8")
        sec2.pack(fill=tk.X, **pad)

        self._w_loop_status = ttk.Label(sec2, text="Loop: unknown",
                                        font=("Consolas", 9))
        self._w_loop_status.pack(anchor=tk.W)
        btn_row2 = ttk.Frame(sec2); btn_row2.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(btn_row2, text="▶ Start loop",
                   command=lambda: self._restart_worker_loop(role)).pack(
                       side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row2, text="⏹ Stop loop",
                   command=self._stop_worker_loop).pack(side=tk.LEFT)

        # Check worker loop status after a short delay
        self.root.after(800, self._update_worker_loop_status)

        # ── SearXNG ──────────────────────────────────────────────────
        sec3 = ttk.LabelFrame(left, text="🔍 SearXNG (local on this worker)",
                               padding="8")
        sec3.pack(fill=tk.X, **pad)

        _saved_sx = self._load_searxng_url_from_role()

        sx_url_row = ttk.Frame(sec3); sx_url_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(sx_url_row, text="SearXNG URL:", width=16).pack(side=tk.LEFT)
        self._sx_url_worker = ttk.Entry(sx_url_row, width=32)
        self._sx_url_worker.insert(0, _saved_sx.replace("//localhost:", "//127.0.0.1:"))
        self._sx_url_worker.pack(side=tk.LEFT, padx=4)

        self._sx_status_worker = ttk.Label(sec3, text="Status: unknown",
                                           font=("Consolas", 9))
        self._sx_status_worker.pack(anchor=tk.W)
        sx_row = ttk.Frame(sec3); sx_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(sx_row, text="Check SearXNG",
                   command=lambda: self._check_searxng(
                       self._sx_status_worker, self._sx_url_worker.get())).pack(
                       side=tk.LEFT, padx=(0, 6))
        ttk.Button(sx_row, text="Enable JSON format (403 fix)",
                   command=lambda: self._fix_searxng_json_format(
                       self._sx_url_worker.get())).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(sx_row, text="Start container",
                   command=lambda: self._start_searxng(self._sx_url_worker.get())).pack(
                       side=tk.LEFT)
        sx_row2 = ttk.Frame(sec3); sx_row2.pack(anchor=tk.W, pady=(2, 0))
        ttk.Button(sx_row2, text="⚡ Scan ports (8080-9000)",
                   command=lambda: self._scan_searxng_port(self._sx_url_worker)).pack(
                       side=tk.LEFT)

        # ── Gateway (Worker) — v1.0.0 ────────────────────────────────
        sec_gw = ttk.LabelFrame(left, text="🚪 Gateway (Worker)  (Port 18789)",
                                 padding="8")
        sec_gw.pack(fill=tk.X, **pad)
        ttk.Label(sec_gw,
                  text="Restart the local OpenClaw gateway on this worker machine.\n"
                       "Required after model changes to activate the new model.",
                  font=("Arial", 9), wraplength=300).pack(anchor=tk.W)
        self._w_gw_status = ttk.Label(sec_gw, text="Status: not checked",
                                      font=("Consolas", 9))
        self._w_gw_status.pack(anchor=tk.W, pady=(4, 0))
        gw_btn_row = ttk.Frame(sec_gw); gw_btn_row.pack(anchor=tk.W, pady=(4, 0))
        ttk.Button(gw_btn_row, text="Check Gateway",
                   command=self._check_worker_gateway).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(gw_btn_row, text="(Re)start Gateway",
                   command=self._restart_worker_gateway).pack(side=tk.LEFT)

        # ── Diagnostic log hint ───────────────────────────────────────
        hint = ttk.LabelFrame(left, text="ℹ  Diagnostic log", padding="6")
        hint.pack(fill=tk.X, **pad)
        ttk.Label(hint,
                  text="All test results with URL, HTTP status and error text\n"
                       "appear in the Log tab (Tab 0 \u2190).",
                  font=("Arial", 9), justify=tk.LEFT).pack(anchor=tk.W)

        # ── Right column — LLM Model Manager (Worker) — v1.0.0 ──────
        right = ttk.Frame(outer)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(4, 0))

        sec_llm = ttk.LabelFrame(right, text="🧠 LLM Model Manager (Worker)",
                                  padding="10")
        sec_llm.pack(fill=tk.BOTH, expand=True, **pad)

        ttk.Label(sec_llm,
                  text="Select the worker model and restart the Gateway to activate.",
                  font=("Arial", 9), foreground="#888888").pack(anchor=tk.W, pady=(0, 6))

        # Primary model row
        row_p = ttk.Frame(sec_llm); row_p.pack(fill=tk.X, pady=3)
        ttk.Label(row_p, text="Primary LLM:", width=14).pack(side=tk.LEFT)
        self._llm_primary_var = tk.StringVar()
        self._llm_primary_cb = ttk.Combobox(row_p, textvariable=self._llm_primary_var,
                                             state="readonly", width=26)
        self._llm_primary_cb.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(row_p, text="✅ Set",
                   command=self._set_primary_llm).pack(side=tk.LEFT)

        # Secondary model row
        row_s = ttk.Frame(sec_llm); row_s.pack(fill=tk.X, pady=3)
        ttk.Label(row_s, text="Secondary LLM:", width=14).pack(side=tk.LEFT)
        self._llm_secondary_var = tk.StringVar()
        self._llm_secondary_cb = ttk.Combobox(row_s, textvariable=self._llm_secondary_var,
                                               state="readonly", width=26)
        self._llm_secondary_cb.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(row_s, text="✅ Set",
                   command=self._set_secondary_llm).pack(side=tk.LEFT)

        # Timeout indicator (reuse same label attribute – worker has it too)
        self._timeout_info = ttk.Label(
            sec_llm,
            text="⏱  timeoutSeconds: —",
            font=("Consolas", 8), foreground="#888888")
        self._timeout_info.pack(anchor=tk.W, pady=(4, 0))

        # Status label
        self._llm_set_status = ttk.Label(sec_llm, text="", font=("Consolas", 9),
                                          wraplength=320)
        self._llm_set_status.pack(anchor=tk.W, pady=(2, 2))

        # Refresh button
        ttk.Button(sec_llm, text="🔄 Refresh model list",
                   command=self._refresh_ollama_models).pack(anchor=tk.W, pady=(4, 8))

        ttk.Separator(sec_llm, orient="horizontal").pack(fill=tk.X, pady=4)

        # Pull new model
        pull_lf = ttk.LabelFrame(sec_llm, text="⬇  Pull new model into Ollama",
                                  padding="8")
        pull_lf.pack(fill=tk.X, pady=(4, 0))
        pull_row = ttk.Frame(pull_lf); pull_row.pack(fill=tk.X)
        ttk.Label(pull_row, text="Model name:", width=12).pack(side=tk.LEFT)
        self._w_pull_entry = ttk.Entry(pull_row, width=22)
        self._w_pull_entry.insert(0, "qwen2.5:0.5b")
        self._w_pull_entry.pack(side=tk.LEFT, padx=(4, 6))
        ttk.Button(pull_row, text="⬇ Pull",
                   command=self._pull_worker_model).pack(side=tk.LEFT)
        self._w_pull_status = ttk.Label(
            pull_lf,
            text="Junior: qwen2.5:0.5b  ·  Senior: qwen2.5:1.5b / 3b",
            font=("Arial", 8), foreground="#888888", wraplength=300)
        self._w_pull_status.pack(anchor=tk.W, pady=(6, 0))

        # Auto-load model list and gateway status on tab open
        self.root.after(1200, self._refresh_ollama_models)
        self.root.after(1200, self._check_worker_gateway)

    # ──────────────────────────────────────────────────────────────────
    # DIAGNOSTIC ACTIONS
    # ──────────────────────────────────────────────────────────────────

    def _refresh_ips(self):
        """Shows all local IPv4 addresses in the Lyra tab."""
        try:
            import socket as _s
            ips = []
            hostname = _s.gethostname()
            for info in _s.getaddrinfo(hostname, None):
                ip = info[4][0]
                if ":" not in ip and ip != "127.0.0.1":
                    if ip not in ips:
                        ips.append(ip)
            if not ips:
                ips = ["127.0.0.1 (local only)"]
            result = "  ·  ".join(ips) + f"   (Hostname: {hostname})"
            self._ip_label.config(text=result)
            self.log(f"[Network] Own IPs: {result}", "SUCCESS")
        except Exception as e:
            self._ip_label.config(text=f"Error: {e}")
            self.log(f"[Network] IP detection error: {e}", "WARNING")

    def _check_task_server(self):
        url = f"http://127.0.0.1:{LYRA_HEAD_PORT}/health"
        self.log(f"[TaskSrv] GET {url} (Timeout 5s)...")
        sc, body = self._diag_api(url, timeout=5)
        if sc == 200:
            msg = f"✅ Reachable (HTTP 200) → {str(body)[:80]}"
            self._ts_status.config(text=f"Status: ONLINE  {str(body)[:60]}", foreground="green")
            self.log(f"[TaskSrv] {msg}", "SUCCESS")
        elif sc == -1:
            msg = f"❌ Not reachable: {body}"
            hint = ""
            if "10061" in str(body) or "refused" in str(body).lower():
                hint = " → Server not running. Click '(Re)start' button."
            elif "timed out" in str(body).lower():
                hint = " → Timeout after 5s. Firewall? Wrong port?"
            self._ts_status.config(text=f"Status: OFFLINE  ({body[:50]})", foreground="red")
            self.log(f"[TaskSrv] {msg}{hint}", "ERROR")
        else:
            self._ts_status.config(text=f"Status: HTTP {sc}", foreground="orange")
            self.log(f"[TaskSrv] HTTP {sc} → {str(body)[:100]}", "WARNING")

    def _start_task_server(self):
        self.log("[TaskSrv] Starting task server...", "INFO")
        if not hasattr(self, "_head_server") or self._head_server is None:
            self._head_server = LyraHeadServer(port=LYRA_HEAD_PORT, log_fn=self.log)
        if self._head_server.start():
            self._ts_status.config(text=f"Status: STARTED (Port {LYRA_HEAD_PORT})",
                                   foreground="green")
            self.log(f"[TaskSrv] Task server running on port {LYRA_HEAD_PORT} ✓", "SUCCESS")
        else:
            self.log(f"[TaskSrv] Start failed – port {LYRA_HEAD_PORT} in use?", "ERROR")

    def _fill_last_worker_ip(self):
        """Fill _dt_worker_ip with the IP of the last worker that returned a result.

        Reads the 'worker' field from the most recent result in
        LyraHeadServer._results. If the head server isn't running or has no
        results yet, tries to read head_address alternatives from machine_role.json.
        """
        ip = ""
        # Try head server results first
        srv = getattr(self, "_head_server", None)
        if srv and hasattr(srv, "_results") and srv._results:
            ip = srv._results[-1].get("worker", "")

        # Fallback: read from machine_role.json (head_address unused on HEAD,
        # but worker machines save their own head_address there — not helpful here.
        # Instead, check WorkerTaskServer logs for from_head field.)
        if not ip:
            wsrv = getattr(self, "_worker_server", None)
            if wsrv and hasattr(wsrv, "_tasks") and wsrv._tasks:
                ip = wsrv._tasks[-1].get("from_head", "")

        if ip and hasattr(self, "_dt_worker_ip"):
            self._dt_worker_ip.delete(0, "end")
            self._dt_worker_ip.insert(0, ip)
            self.log(f"[DummyTask] Worker IP filled: {ip}", "SUCCESS")
        else:
            self.log("[DummyTask] No recent worker IP found – enter manually.", "WARNING")

    def _send_dummy_task(self):
        """Send a test web_search task directly to the Worker's WorkerTaskServer.

        Routing fix — task is now POSTed to Worker IP:18790/tasks
        (WorkerTaskServer) instead of 127.0.0.1:18790/tasks (HEAD's own server).

        Why this matters:
          The Worker runs QueuedWorkerClient which reads from a local threading.Queue
          populated by its own WorkerTaskServer. It does NOT poll the HEAD's
          LyraHeadServer. Sending to 127.0.0.1 put the task in HEAD's list where
          nobody ever picked it up → timeout every time.

        Flow:
          HEAD → POST Worker:18790/tasks → WorkerTaskServer queues task
          → QueuedWorkerClient executes → POST HEAD:18790/result
          → HEAD LyraHeadServer stores result → _poll_dummy_result finds it ✓

        If Worker IP is empty (same-machine test): sends to 127.0.0.1:18790.
        The HEAD's LyraHeadServer picks it up only when a local LyraWorkerClient
        is polling — useful for single-machine testing.
        """
        query      = self._dt_query.get().strip()     or "Weather Zurich current"
        worker_ip  = self._dt_worker_ip.get().strip() if hasattr(self, "_dt_worker_ip") else ""
        target_host = worker_ip if worker_ip else "127.0.0.1"

        # 1. Ensure HEAD's result server is reachable (always 127.0.0.1)
        health_url = f"http://127.0.0.1:{LYRA_HEAD_PORT}/health"
        sc_h, _ = self._diag_api(health_url, timeout=3)
        if sc_h != 200:
            self._dt_status.config(
                text="❌ HEAD task server not reachable – start it first!")
            self.log("[DummyTask] HEAD task server (127.0.0.1:18790) not reachable."
                     " Click '(Re)start' in Task Server section.", "ERROR")
            return

        task_id = f"diag_{int(time.time())}"
        # POST target: Worker's WorkerTaskServer (or local if same machine)
        task_url = f"http://{target_host}:{LYRA_HEAD_PORT}/tasks"
        payload  = {"task_id": task_id, "type": "web_search",
                    "payload": {"query": query}}

        self._dt_status.config(text=f"⏳ Sending to {target_host}...")
        self.log(f"[DummyTask] POST {task_url} → query='{query}'  task_id={task_id}")

        def send_task():
            sc, body = self._diag_api(task_url, timeout=20, method="POST", data=payload)
            if sc not in (200, 201):
                self.root.after(0, lambda: self._dt_status.config(
                    text=f"❌ POST failed: HTTP {sc} – Worker not reachable?"))
                self.log(f"[DummyTask] POST failed: HTTP {sc} → {body}", "ERROR")
                return

            self.root.after(0, lambda: self._dt_status.config(
                text=f"⏳ Task sent to {target_host} – waiting for result (max 60s)..."))
            self.log(f"[DummyTask] Task sent (HTTP {sc}) – polling HEAD for result...")
            self._poll_dummy_result(task_id)

        threading.Thread(target=send_task, daemon=True).start()

    def _poll_dummy_result(self, task_id: str):
        result_url = f"http://127.0.0.1:{LYRA_HEAD_PORT}/results"
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(4)
            sc, body = self._diag_api(result_url, timeout=5)
            if sc == 200 and isinstance(body, dict):
                results = body.get("results", [])
                match = next((r for r in results if r.get("task_id") == task_id), None)
                if match:
                    status = match.get("status", "?")
                    res = match.get("result", {})
                    summary = res.get("summary", "") if isinstance(res, dict) else str(res)
                    elapsed = 60 - (deadline - time.time())
                    msg = (f"✅ Result ({status}) after {elapsed:.0f}s: "
                           f"{summary[:120]}")
                    self.root.after(0, lambda m=msg: (
                        self._dt_status.config(text=m[:100]),
                        self.log(f"[DummyTask] {m}", "SUCCESS")
                    ))
                    return
        self.root.after(0, lambda: (
            self._dt_status.config(text="❌ Timeout: no result after 60s"),
            self.log("[DummyTask] Timeout – no worker active or task processing too slow.",
                     "ERROR")
        ))

    def _load_searxng_url_from_role(self) -> str:
        """Reads saved SearXNG URL from machine_role.json (Worker machine)."""
        role_file = os.path.join(os.path.expanduser("~"), ".openclaw", "machine_role.json")
        try:
            if os.path.isfile(role_file):
                with open(role_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("searxng_url", "http://127.0.0.1:8080")
        except Exception:
            pass
        return "http://127.0.0.1:8080"

    def _check_searxng(self, status_label, base_url: str = "http://127.0.0.1:8080"):
        base_url = base_url.rstrip("/").replace("//localhost:", "//127.0.0.1:")
        url = f"{base_url}/search?q=test&format=json"
        self.log(f"[SearXNG] GET {url} (Timeout 8s)...")
        sc, body = self._diag_api(url, timeout=8)

        if sc == 200:
            # body can be dict OR str (if json.loads in _diag_api failed)
            # Parse again if still string
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except Exception:
                    pass

            if isinstance(body, dict):
                # Validation: "query" key is sufficient proof (even with results: [])
                if "query" in body or "results" in body:
                    results = body.get("results", [])
                    n = len(results) if isinstance(results, list) else 0
                    if n > 0:
                        snippet = str(results[0].get("title", "(no title)"))[:60]
                        detail = f"{n} results – Example: '{snippet}'"
                    else:
                        detail = "0 results (search 'test' with no results – that's OK!)"
                    status_label.config(text=f"✅ ONLINE – {detail}", foreground="green")
                    self.log(f"[SearXNG] ✅ Reachable, JSON valid – {detail}", "SUCCESS")
                    return
                else:
                    # dict but no query/results → unknown JSON format
                    keys = list(body.keys())[:5]
                    self.log(f"[SearXNG] HTTP 200, JSON without 'query'/'results' – Keys: {keys}",
                             "WARNING")
                    status_label.config(
                        text=f"⚠ HTTP 200 JSON unknown – Keys: {keys}", foreground="orange")
                    return
            else:
                # String – HTML or unknown format
                snippet = str(body)[:120].replace("\n", " ")
                self.log(f"[SearXNG] HTTP 200 but no JSON body – Body: {snippet}", "WARNING")
                self.log("[SearXNG] Likely HTML response – click 'Enable JSON format'!", "WARNING")
                status_label.config(
                    text="⚠ HTTP 200 – HTML instead of JSON → click 'Enable JSON format'",
                    foreground="orange")
                return

        elif sc == 403:
            status_label.config(text="⚠ HTTP 403 – JSON format disabled", foreground="orange")
            self.log("[SearXNG] HTTP 403 – JSON API disabled!", "WARNING")
            self.log("[SearXNG] Cause: settings.yml missing 'formats: [html, json]'", "WARNING")
            self.log("[SearXNG] Fix: Click 'Enable JSON format' button.", "WARNING")

        elif sc == -1:
            hint = ""
            body_str = str(body)
            if "10061" in body_str or "refused" in body_str.lower():
                hint = f" → Docker not running or port not open ({base_url})"
            elif "timed out" in body_str.lower():
                hint = " → Timeout 8s – Container still starting? Wait 15s and check again."
            elif "10060" in body_str:
                hint = " → Connection timed out – Firewall or container too slow?"
            status_label.config(text=f"❌ OFFLINE – {body_str[:60]}", foreground="red")
            self.log(f"[SearXNG] Not reachable: {body_str}{hint}", "ERROR")
            self.log("[SearXNG] Tip: docker.exe start searxng  or  docker ps check",
                     "WARNING")
        else:
            snippet = str(body)[:80].replace("\n", " ")
            status_label.config(text=f"⚠ HTTP {sc} – {snippet[:50]}", foreground="orange")
            self.log(f"[SearXNG] HTTP {sc} – Body: {snippet}", "WARNING")

    def _fix_searxng_json_format(self, base_url: str = "http://localhost:8080"):
        """
        SearXNG 403 fix : patches settings.yml via docker exec.
        3-stage strategy:
          1. docker exec: Python script directly in container
          2. docker cp: copy settings.yml out, patch, copy back
          3. docker inspect Mounts -> WSL volume path write directly
        """
        self.log("[SearXNG-Fix] Starting 403 fix (docker exec method)...")

        fixed = False
        sl_char = chr(39)  # single quote


        # ── Stage 1: docker.exe exec (Docker Desktop Windows CLI) ────────────────
        # Important: call "docker.exe" directly, NOT via "wsl bash -lc docker"!
        # Container runs in Docker Desktop (Windows), not in WSL Docker.
        # Unique marker "FIX_OK" instead of "OK" prevents false positives (syntax error text never contains "FIX_OK")
        self.log("[SearXNG-Fix] Stage 1: docker.exe exec python3 ...")
        py_oneliner = (
            "p='/etc/searxng/settings.yml';"
            "import os;"
            "c=open(p).read() if os.path.exists(p) else '';"
            "add='\\nsearch:\\n  formats:\\n    - html\\n    - json\\n';"
            "open(p,'w').write(c+add);"
            "print('FIX_OK')"
        )
        # docker.exe runs directly on Windows (no wsl)
        r1 = self.run_powershell(
            'docker.exe exec searxng python3 -c '
            + chr(34) + py_oneliner + chr(34)
            + ' 2>&1')
        out1 = ((r1.get("stdout") or "") + (r1.get("stderr") or "")).strip()
        self.log(f"[SearXNG-Fix] exec output: {out1[:120]}")
        if "FIX_OK" in out1:
            fixed = True
            self.log("[SearXNG-Fix] Stage 1 successful ✓", "SUCCESS")

        # ── Stage 2: docker.exe cp + PowerShell Add-Content ────────────────────
        if not fixed:
            self.log("[SearXNG-Fix] Stage 2: docker.exe cp + PowerShell patch ...")
            # Copy settings.yml from container to Windows temp
            r_cp_out = self.run_powershell(
                'docker.exe cp searxng:/etc/searxng/settings.yml '
                '$env:TEMP\\sx_settings_fix.yml 2>&1')
            cp_out = ((r_cp_out.get("stdout") or "") + (r_cp_out.get("stderr") or "")).strip()
            self.log(f"[SearXNG-Fix] docker cp out: {cp_out[:80]}")
            if "Error" not in cp_out and "No such" not in cp_out:
                # PowerShell Add-Content: clean YAML append without escaping issues
                r_patch = self.run_powershell(
                    'Add-Content -Path "$env:TEMP\\sx_settings_fix.yml" '
                    '-Value "`nsearch:`n  formats:`n    - html`n    - json`n"; '
                    'Write-Output PATCHED')
                patch_out = ((r_patch.get("stdout") or "")).strip()
                self.log(f"[SearXNG-Fix] Patch: {patch_out[:60]}")
                if "PATCHED" in patch_out:
                    r_cp_in = self.run_powershell(
                        'docker.exe cp $env:TEMP\\sx_settings_fix.yml '
                        'searxng:/etc/searxng/settings.yml 2>&1')
                    cp_in_out = ((r_cp_in.get("stdout") or "") + (r_cp_in.get("stderr") or "")).strip()
                    self.log(f"[SearXNG-Fix] docker cp back: {cp_in_out[:80]}")
                    if "Error" not in cp_in_out:
                        fixed = True
                        self.log("[SearXNG-Fix] Stage 2 successful ✓", "SUCCESS")


        # ── Stage 3: Docker Inspect Mounts -> WSL path ────────────────────
        if not fixed:
            self.log("[SearXNG-Fix] Stage 3: docker inspect Mounts ...")
            r_inspect = self.run_powershell(
                "wsl bash -lc 'docker inspect searxng 2>/dev/null | "
                "python3 -c \'import sys,json; "
                "[print(x[\"Source\"]) for x in json.load(sys.stdin)[0].get(\"Mounts\",[])]\' "
                "2>/dev/null'")
            mounts = ((r_inspect.get("stdout") or "")).strip().splitlines()
            for mount_src in mounts:
                mount_src = mount_src.strip()
                if not mount_src:
                    continue
                # WSL path: /var/lib/docker/... or Windows path /mnt/c/...
                cand = mount_src.rstrip("/") + "/settings.yml"
                self.log(f"[SearXNG-Fix] Mount candidate: {cand}")
                r_test = self.run_powershell(
                    f"wsl bash -lc 'test -f {sl_char}{cand}{sl_char} && echo EXISTS || echo MISSING'")
                if "EXISTS" in ((r_test.get("stdout") or "")):
                    append_snippet = (
                        "\\nsearch:\\n  formats:\\n    - html\\n    - json\\n"
                    )
                    app_cmd = (
                        f"wsl bash -lc "
                        f"{sl_char}printf '{append_snippet}' >> {cand} && echo OK{sl_char}"
                    )
                    r_app = self.run_powershell(app_cmd)
                    if "OK" in ((r_app.get("stdout") or "")):
                        fixed = True
                        self.log(f"[SearXNG-Fix] Stage 3 successful: {cand} \u2713", "SUCCESS")
                        break

        # ── Result ─────────────────────────────────────────────────────
        if fixed:
            self.log("[SearXNG-Fix] Restarting container (10s)...")
            r_restart = self.run_powershell("wsl bash -lc 'docker restart searxng 2>&1'")
            restart_out = ((r_restart.get("stdout") or "")).strip()
            self.log(f"[SearXNG-Fix] Restart: {restart_out[:60]}")
            sl = self._sx_status_lyra if hasattr(self, "_sx_status_lyra") else self._sx_status_worker
            self.root.after(10000, lambda: self._check_searxng(sl, base_url))
        else:
            self.log("[SearXNG-Fix] All stages failed.", "ERROR")
            self.log("[SearXNG-Fix] MANUAL FIX (WSL terminal):", "WARNING")
            self.log("  docker exec searxng sh -c 'printf", "WARNING")
            self.log("  printf '\\nsearch:\\n  formats:\\n    - html\\n    - json\\n'", "WARNING")
            self.log("  >> /etc/searxng/settings.yml && echo OK'", "WARNING")
            self.log("  docker restart searxng", "WARNING")

    def _scan_searxng_port(self, url_entry):
        """Scans known ports on 127.0.0.1. Timeout=5s, 2 retries per port."""
        self.log("[SearXNG] Starting port scan on 127.0.0.1 "
                 "(8080, 8888, 9000, 7000, 8000, 8090, 5000)...")
        threading.Thread(
            target=self._scan_searxng_port_worker,
            args=(url_entry,),
            daemon=True
        ).start()

    def _scan_searxng_port_worker(self, url_entry):
        candidates = [8080, 8888, 9000, 7000, 8000, 8090, 5000, 4000, 3000]
        found = None
        for port in candidates:
            # Force 127.0.0.1 (Python 3.11 IPv6 bug with Docker Desktop)
            url = f"http://127.0.0.1:{port}/search?q=test&format=json"
            best_sc, best_body = -1, ""
            # 2 attempts per port (container might still be starting)
            for attempt in range(2):
                self.root.after(0, lambda p=port, a=attempt+1: self.log(
                    f"[SearXNG-Scan] Port {p} attempt {a}/2 ..."))
                sc, body = self._diag_api(url, timeout=5)
                snippet = str(body)[:80].replace("\n", " ") if body else ""
                self.root.after(0, lambda p=port, s=sc, sn=snippet: self.log(
                    f"[SearXNG-Scan]   HTTP {s} – {sn}"))
                if sc in (200, 403):
                    best_sc, best_body = sc, body
                    break
                if attempt == 0 and sc == -1:
                    time.sleep(3)
            else:
                best_sc, best_body = sc, body

            if best_sc == 200:
                parsed = best_body
                if isinstance(parsed, str):
                    try:
                        parsed = json.loads(parsed)
                    except Exception:
                        pass
                is_json = (isinstance(parsed, dict)
                           and ("query" in parsed or "results" in parsed))
                new_url = f"http://127.0.0.1:{port}"
                found = port
                if is_json:
                    def _hit_json(p=port, u=new_url):
                        self.log(f"[SearXNG-Scan] ✅ Port {p}: JSON valid (query/results ✓)",
                                 "SUCCESS")
                        url_entry.delete(0, tk.END)
                        url_entry.insert(0, u)
                        sl = (self._sx_status_lyra if hasattr(self, "_sx_status_lyra")
                              else self._sx_status_worker)
                        self.root.after(300, lambda: self._check_searxng(sl, u))
                    self.root.after(0, _hit_json)
                else:
                    def _hit_html(p=port, u=new_url):
                        self.log(f"[SearXNG-Scan] ⚠ Port {p}: HTTP 200 but no JSON "
                                 f"→ click 'Enable JSON format'!", "WARNING")
                        url_entry.delete(0, tk.END)
                        url_entry.insert(0, u)
                    self.root.after(0, _hit_html)
                break

            elif best_sc == 403:
                new_url = f"http://127.0.0.1:{port}"
                found = port
                def _hit_403(p=port, u=new_url):
                    self.log(f"[SearXNG-Scan] ⚠ Port {p}: HTTP 403 – JSON disabled "
                             f"→ click 'Enable JSON format'!", "WARNING")
                    url_entry.delete(0, tk.END)
                    url_entry.insert(0, u)
                self.root.after(0, _hit_403)
                break

        if found is None:
            self.root.after(0, lambda: self.log(
                "[SearXNG-Scan] No SearXNG found on known ports (127.0.0.1).\n"
                "  → Check: docker ps (Windows terminal, not WSL!)\n"
                "  → Is Docker Desktop running and the container running?\n"
                "  → For another port: set URL field manually to http://127.0.0.1:PORT",
                "ERROR"))

    def _start_searxng(self, base_url: str = "http://127.0.0.1:8080"):
        """Starts SearXNG Docker container. Uses docker.exe (Docker Desktop Windows CLI)."""
        base_url = base_url.replace("//localhost:", "//127.0.0.1:")
        try:
            port = base_url.split(":")[-1].split("/")[0]
            port = int(port)
        except Exception:
            port = 8080
        self.log(f"[SearXNG] Starting container (Port {port}, docker.exe)...")
        r_start = self.run_powershell("docker.exe start searxng 2>&1")
        start_out = ((r_start.get("stdout") or "") + (r_start.get("stderr") or "")).strip()
        if "No such container" in start_out or ("Error" in start_out and "searxng" not in start_out.split("Error")[0]):
            self.log("[SearXNG] No container 'searxng' – starting new with docker run ...")
            r_run = self.run_powershell(
                f"docker.exe run -d --name searxng -p {port}:8080 searxng/searxng 2>&1")
            start_out = ((r_run.get("stdout") or "") + (r_run.get("stderr") or "")).strip()
        self.log(f"[SearXNG] Docker output: {start_out[:200]}", "INFO")
        self.log("[SearXNG] Waiting 12s for container start...", "INFO")
        sl = (self._sx_status_lyra if hasattr(self, "_sx_status_lyra")
              else self._sx_status_worker)
        # First check after 12s, second after 18s (container sometimes takes longer)
        self.root.after(12000, lambda: self._check_searxng(sl, base_url))
        self.root.after(18000, lambda: self._check_searxng(sl, base_url))

    def _check_gateway(self):
        """
        Checks gateway health via GET /health (OpenClaw 2026.3.1+).

        DECISION (2026-03): Endpunkt-Aenderung zwischen Versionen:
          OpenClaw <= 2026.2.x : /api/health  JSON  status ok
          OpenClaw >= 2026.3.1 : /health      HTML  Web-App HTTP 200
          /api/health in 2026.3.1 entfernt, immer 404, unabhaengig vom Token.

        Strategie: /health zuerst (200 = laeuft), Fallback auf /api/health.
        Token als Query-Parameter: auth.mode=token, _diag_api sendet bei GET
        keinen Auth-Header (SearXNG-Kompatibilitaet).
        """
        token = self.cfg._read_token_from_config() or "lyra-local-token"
        # Primary: /health (2026.3.1+)
        url = f"http://127.0.0.1:18789/health?token={token}"
        self.log(f"[Gateway] GET /health (Timeout 5s, Token={token[:8]}...)")
        sc, body = self._diag_api(url, timeout=5)
        # Fallback: /api/health (2026.2.x and older)
        if sc == 404:
            url = f"http://127.0.0.1:18789/api/health?token={token}"
            self.log("[Gateway] /health=404, trying /api/health (older version)...")
            sc, body = self._diag_api(url, timeout=5)
        if 0 < sc < 400:
            self._gw_status.config(text=f"✅ ONLINE (HTTP {sc}) → {str(body)[:60]}",
                                   foreground="green")
            self.log(f"[Gateway] Reachable HTTP {sc}: {str(body)[:80]}", "SUCCESS")
        elif sc == -1:
            hint = (" → Gateway not running. Click 'Restart Gateway'."
                    if "10061" in str(body) else "")
            self._gw_status.config(text=f"❌ OFFLINE – {body[:50]}", foreground="red")
            self.log(f"[Gateway] Error: {body}{hint}", "ERROR")
        else:
            self._gw_status.config(text=f"⚠ HTTP {sc}", foreground="orange")
            self.log(f"[Gateway] HTTP {sc} → {str(body)[:100]}", "WARNING")

    def _restart_gateway(self):
        """
        Stops all OpenClaw/Node processes, patches gateway.cmd, then restarts.

        ⚠️  EDGE-LÖSUNG (2026-03): patch_gateway_cmd() muss VOR dem Start von
        gateway.cmd aufgerufen werden — nicht nur im vollständigen installation_process().

        ROOT CAUSE: Der "Restart Gateway" Button ruft nur force_kill + gateway.cmd auf.
        Fehlen OLLAMA_API_KEY / OPENCLAW_GATEWAY_TOKEN in gateway.cmd, öffnet der
        Gateway-Prozess zwar den Port (kein WinError 10061 mehr), antwortet aber auf
        /api/health mit HTTP 404 — weil die Auth-ENV fehlt oder der interne
        Initialisierungs-State nicht korrekt ist.

        FIX: patch_gateway_cmd() vor jedem gateway.cmd-Start — idempotent, safe.
        """
        self.log("[Gateway] Stopping old processes...")
        self.force_kill_openclaw_processes()
        gw_cmd = os.path.join(os.path.expanduser("~"), ".openclaw", "gateway.cmd")
        if os.path.isfile(gw_cmd):
            # ⚠️  EDGE-LÖSUNG: patch BEFORE start — ensures OLLAMA_API_KEY +
            # OPENCLAW_GATEWAY_TOKEN are present in gateway.cmd ENV block.
            # Without this, gateway starts but /api/health returns HTTP 404.
            self.log("[Gateway] Patching gateway.cmd (ENV block)...")
            self.cfg.patch_gateway_cmd()

            import subprocess as _sp
            _sp.Popen(
                ["cmd.exe", "/c", gw_cmd],
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE – visible gateway window, works without parent console (Binary)
            )
            self.log(f"[Gateway] Started via: {gw_cmd}", "SUCCESS")
            self.log("[Gateway] Checking in 4s / 8s / 30s (slow hardware covered)...",
                     "INFO")
            # Third check after 30s added — covers slow hardware (i5-2500,
            # HDDs). On fast machines the 4s check already succeeds, no regression.
            self.root.after(4000,  self._check_gateway)
            self.root.after(8000,  self._check_gateway)
            self.root.after(30000, self._check_gateway)
        else:
            self.log("[Gateway] gateway.cmd not found – OpenClaw installed?", "ERROR")

    # ── LLM MODEL MANAGER ─────────────────────────────────────────────────────

    def _ollama_list_via_api(self) -> list:
        """Return installed Ollama model names by querying the REST API on port 11434.

        Tries 127.0.0.1 first, then the WSL IP as fallback.  Works regardless
        of whether Ollama runs inside WSL, as a Docker container, or natively
        on Windows.

        Returns:
            List of model name strings such as ['qwen2.5:7b', 'glm-4.7-flash:latest'].
            Empty list if Ollama is not reachable.
        """
        import urllib.request as _ur, json as _j
        for host in ("127.0.0.1", self._get_wsl_ip() or ""):
            if not host:
                continue
            try:
                resp = _ur.urlopen(f"http://{host}:11434/api/tags", timeout=5)
                data = _j.loads(resp.read())
                names = [m["name"] for m in data.get("models", [])]
                if names:
                    return names
            except Exception:
                continue
        return []

    def _refresh_ollama_models(self):
        """Populate the Primary/Secondary dropdowns with models from Ollama.

        Queries the Ollama REST API (/api/tags) instead of shelling out to
        'ollama list', so it works for all Ollama deployment modes (WSL,
        Docker Desktop, Windows-native).  Pre-selects the models currently
        written in openclaw.json, and shows the active timeoutSeconds so the
        user can see at a glance whether local-model mode is active.
        """
        if not hasattr(self, "_llm_set_status"):
            return
        self._llm_set_status.config(
            text="🔄 Loading models via Ollama API ...", foreground="#888888")
        self.root.update_idletasks()

        models = self._ollama_list_via_api()

        # Read current config to pre-select active models and show timeout
        current_primary = current_secondary = ""
        current_timeout = None
        try:
            cfg_dir = self.cfg._find_openclaw_config_dir()
            import json as _j, os as _os
            cfg_path = _os.path.join(cfg_dir, "openclaw.json")
            if _os.path.isfile(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = _j.load(f)
                defs = cfg.get("agents", {}).get("defaults", {})
                mc   = defs.get("model", {})
                current_primary   = mc.get("primary",   "").replace("ollama/", "")
                fallbacks         = mc.get("fallbacks", [])
                current_secondary = fallbacks[0].replace("ollama/", "") if fallbacks else ""
                current_timeout   = defs.get("timeoutSeconds", None)
        except Exception:
            pass

        # Update timeout indicator
        if hasattr(self, "_timeout_info"):
            if current_timeout == 0:
                self._timeout_info.config(
                    text="⏱  timeoutSeconds: 0  (no timeout — local model mode ✅)",
                    foreground="green")
            elif current_timeout is None:
                self._timeout_info.config(
                    text="⏱  timeoutSeconds: not set  (default 600s — ⚠️ may timeout!)",
                    foreground="orange")
            else:
                self._timeout_info.config(
                    text=f"⏱  timeoutSeconds: {current_timeout}s",
                    foreground="#555555")

        if not models:
            self._llm_set_status.config(
                text="⚠  No models found — Ollama not reachable on port 11434",
                foreground="orange")
            self.log("[LLM] Ollama API not reachable on 127.0.0.1:11434. "
                     "Is Docker Desktop / WSL Ollama running?", "WARNING")
            return

        self._llm_primary_cb["values"]   = models
        self._llm_secondary_cb["values"] = models

        def _best_match(current, lst):
            """Return exact match, prefix match, or first item."""
            if current in lst:
                return current
            base = current.split(":")[0]
            for m in lst:
                if m.startswith(base):
                    return m
            return lst[0] if lst else ""

        self._llm_primary_var.set(_best_match(current_primary, models))
        self._llm_secondary_var.set(
            _best_match(current_secondary, models) if current_secondary
            else (models[1] if len(models) > 1 else models[0])
        )

        self._llm_set_status.config(
            text=(f"✅ {len(models)} model(s)  ·  "
                  f"Primary: {current_primary or '?'}  ·  "
                  f"Secondary: {current_secondary or '?'}"),
            foreground="green")
        self.log(f"[LLM] {len(models)} model(s): {', '.join(models)}", "SUCCESS")

    def _set_primary_llm(self):
        """Write the selected primary model to openclaw.json and show restart hint."""
        model = self._llm_primary_var.get().strip()
        if not model:
            self._llm_set_status.config(text="⚠ No model selected.", foreground="orange")
            return
        # Inject status callback so cfg can update the label directly (v1.0.1)
        self.cfg._status_cb = self._llm_set_status.config
        self.cfg._write_llm_to_config(primary=model)
        self.cfg._status_cb = lambda **kw: None  # reset after use

    def _set_secondary_llm(self):
        """Write the selected secondary (fallback) model to openclaw.json."""
        model = self._llm_secondary_var.get().strip()
        if not model:
            self._llm_set_status.config(text="⚠ No model selected.", foreground="orange")
            return
        # Inject status callback so cfg can update the label directly (v1.0.1)
        self.cfg._status_cb = self._llm_set_status.config
        self.cfg._write_llm_to_config(secondary=model)
        self.cfg._status_cb = lambda **kw: None  # reset after use

    def _pull_ollama_model(self):
        """Pull an Ollama model in a background thread with live log output.

        Auto-detects the Ollama runtime environment:
          - Ollama installed inside WSL/Ubuntu → uses wsl bash with
            OLLAMA_HOST=127.0.0.1:11434 to reach the running server.
          - Otherwise (Docker Desktop, Windows-native) → calls ollama.exe
            directly via PowerShell.

        Pull progress is streamed line-by-line to the main log tab.  On
        success the model list is refreshed automatically so the new model
        appears in the dropdowns without a manual refresh.
        """
        model = self._pull_entry.get().strip()
        if not model:
            self._pull_status.config(text="⚠ Please enter a model name.",
                                     foreground="orange")
            return

        self._pull_status.config(
            text=f"⬇ Pulling {model} … (see Log tab for progress)",
            foreground="#0055cc")
        self.log(f"[Ollama Pull] ⬇ Starting: {model}", "INFO")
        self.log(f"[Ollama Pull] Large models (e.g. glm-4.7-flash ~17 GB) "
                 f"may take several minutes.", "INFO")
        self.log(f"[Ollama Pull] ☕ Perfect time for a coffee.", "INFO")

        wsl_ok, ubuntu_ok = self.check_wsl()
        ollama_in_wsl     = wsl_ok and ubuntu_ok and self.check_ollama_wsl()

        def _do_pull():
            import subprocess as _sp
            try:
                if ollama_in_wsl:
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive",
                           "-Command",
                           f'wsl bash -lc "OLLAMA_HOST=127.0.0.1:11434 ollama pull {model} 2>&1"']
                else:
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive",
                           "-Command", f"ollama pull {model} 2>&1"]

                proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                                 encoding="utf-8", errors="replace")
                success = False
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log(f"  [pull] {line}", "INFO")
                    if "success" in line.lower():
                        success = True
                proc.wait()

                if proc.returncode == 0 or success:
                    self.root.after(0, lambda: self._pull_status.config(
                        text=f"✅ {model} ready! Model list updated.",
                        foreground="green"))
                    self.root.after(0, lambda: self.log(
                        f"[Ollama Pull] ✅ {model} successfully loaded!", "SUCCESS"))
                    self.root.after(600, self._refresh_ollama_models)
                else:
                    self.root.after(0, lambda: self._pull_status.config(
                        text=f"❌ Pull failed (code {proc.returncode}) — check Log tab.",
                        foreground="red"))
            except Exception as e:
                self.root.after(0, lambda: self._pull_status.config(
                    text=f"❌ Error: {e}", foreground="red"))
                self.log(f"[Ollama Pull] Error: {e}", "ERROR")

        import threading
        threading.Thread(target=_do_pull, daemon=True).start()

    def _apply_browser_config_and_restart(self):
        """Quick Fix button: apply browser config then restart the gateway.

        Convenience wrapper that calls _apply_browser_config() and then
        triggers a gateway restart so the new profile takes effect immediately
        without requiring a full reinstall.
        """
        self._apply_browser_config()
        self.root.after(600, self._restart_gateway)

    def _apply_browser_config(self):
        """Apply browser.defaultProfile="openclaw" to openclaw.json after gateway start.

        The browser block is intentionally NOT written during the initial config
        creation (write_openclaw_config).  OpenClaw's schema validator is strict
        and rejects unrecognised sub-keys at gateway boot time.  Setting the
        browser profile post-start via openclaw config set is the safe path that
        avoids validation failures.

        Called automatically after the gateway health-check confirms the gateway
        is up.  Also called as a standalone Quick Fix button action.

        Config applied (JSON5 path notation):
            browser.enabled          = true
            browser.defaultProfile   = "openclaw"
            browser.headless         = false
            browser.profiles.openclaw.color = "#FF6B00"
        """
        cfg_dir = self.cfg._find_openclaw_config_dir()
        cfg_path = None
        for fname in ("openclaw.json", "config.json"):
            p = os.path.join(cfg_dir, fname)
            if os.path.isfile(p):
                cfg_path = p
                break
        if not cfg_path:
            self.log("[Browser] openclaw.json not found — skipping browser config", "WARNING")
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            self.log(f"[Browser] Could not read config: {e}", "WARNING")
            return

        # Only write if not already set to avoid unnecessary gateway config churn
        existing = cfg.get("browser", {})
        if existing.get("defaultProfile") == "openclaw":
            self.log("[Browser] browser.defaultProfile already 'openclaw' ✓", "INFO")
            return

        cfg["browser"] = {
            "enabled": True,
            "defaultProfile": "openclaw",
            "headless": False,
            "profiles": {
                "openclaw": {
                    # cdpPort required — schema validation fails without it.
                    # 18800 is the OpenClaw default for the managed profile.
                    # Docs say "auto-assigned" but validator still requires it.
                    "cdpPort": 18800,
                    "color": "#FF6B00",
                },
            },
        }

        try:
            shutil.copy2(cfg_path, cfg_path + f".bak_{int(time.time())}")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.log("[Browser] browser.defaultProfile='openclaw' written ✓", "SUCCESS")
            self.log("[Browser] Gateway restart required to activate managed browser.", "INFO")
        except Exception as e:
            self.log(f"[Browser] Could not write config: {e}", "ERROR")

    def _apply_fixes_and_update(self):
        """Universal fix + update function. Called by the 'Apply fixes + Update SOUL.md' button.

        Runs all adaptive config fixes against openclaw.json (never overwrites
        valid existing values), then refreshes SOUL.md/BOOTSTRAP.md in the workspace.
        One backup per run. Gateway restarted once at the end.

        Adding new fixes here keeps the GUI clean — one button for all corrections.

        Current fixes applied:
          - DECISION #11: gateway.auth.password — add '' if absent or sentinel present.
            (OpenClaw 2026.3.2 requires this field; absent → sentinel → rejected)
        """
        cfg_dir       = self.cfg._find_openclaw_config_dir()
        cfg_path      = os.path.join(cfg_dir, "openclaw.json")
        workspace_dir = os.path.join(cfg_dir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        soul_path     = os.path.join(workspace_dir, "SOUL.md")

        fixes_applied = []

        # ── openclaw.json adaptive fixes ──────────────────────────────────────
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)

                # DECISION #11: gateway.auth.password
                # Only touch if absent or contains the sentinel — never overwrite
                # a real password value a user may have set intentionally.
                cfg.setdefault("gateway", {}).setdefault("auth", {})
                current_pw = cfg["gateway"]["auth"].get("password", "__NOT_SET__")
                if current_pw in ("__NOT_SET__", "__OPENCLAW_REDACTED__"):
                    cfg["gateway"]["auth"]["password"] = ""
                    label = "absent → added" if current_pw == "__NOT_SET__" else "sentinel → cleared"
                    fixes_applied.append(f"gateway.auth.password ({label})")

                # DECISION #12: commands.ownerDisplaySecret
                # Required HMAC secret for owner-ID obfuscation (2026.3.x+).
                # Web Config Admin Panel corrupts openclaw.json by writing the
                # redaction sentinel back to disk (upstream bug #13058).
                # Generate a new secret ONLY if absent or sentinel — never overwrite
                # a valid existing secret (changing it invalidates owner-ID history).
                cfg.setdefault("commands", {})
                current_secret = cfg["commands"].get("ownerDisplaySecret", "__NOT_SET__")
                if current_secret in ("__NOT_SET__", "__OPENCLAW_REDACTED__"):
                    import uuid as _uuid
                    cfg["commands"]["ownerDisplaySecret"] = _uuid.uuid4().hex
                    label = "absent → generated" if current_secret == "__NOT_SET__" else "sentinel → regenerated"
                    fixes_applied.append(f"commands.ownerDisplaySecret ({label})")

                # DECISION #13: tools.exec.allowlist — schema rejected, strip if present
                # (may have been written by a previous v1.0.2 installer run)
                exec_cfg = cfg.get("tools", {}).get("exec", {})
                if "allowlist" in exec_cfg:
                    del cfg["tools"]["exec"]["allowlist"]
                    fixes_applied.append("tools.exec.allowlist (stripped — schema rejected)")
                if exec_cfg.get("security") == "allowlist":
                    cfg["tools"]["exec"]["security"] = "full"
                    fixes_applied.append("tools.exec.security (allowlist → full)")

                # DECISION #14: tools.web.fetch.allowPrivateIPs — schema rejected, strip if present
                fetch_cfg = cfg.get("tools", {}).get("web", {}).get("fetch", {})
                if "allowPrivateIPs" in fetch_cfg:
                    del cfg["tools"]["web"]["fetch"]["allowPrivateIPs"]
                    fixes_applied.append("tools.web.fetch.allowPrivateIPs (stripped — schema rejected)")

                # DECISION #15: memorySearch — provider="local" + fallback="none"
                mem = cfg.get("agents", {}).get("defaults", {}).get("memorySearch", {})
                mem_fixed = False
                if "remote" in mem:
                    del cfg["agents"]["defaults"]["memorySearch"]["remote"]
                    mem_fixed = True
                if mem.get("provider", "") not in ("local", ""):
                    cfg["agents"]["defaults"]["memorySearch"]["provider"] = "local"
                    mem_fixed = True
                if mem.get("fallback", "") != "none":
                    cfg["agents"]["defaults"]["memorySearch"]["fallback"] = "none"
                    mem_fixed = True
                if mem_fixed:
                    fixes_applied.append("memorySearch (provider=local, fallback=none, remote removed)")

                # ── Future fixes go here, same pattern ────────────────────────
                # Example:
                #   current = cfg.get("some", {}).get("key", "__NOT_SET__")
                #   if current == "__NOT_SET__":
                #       cfg["some"]["key"] = correct_value
                #       fixes_applied.append("some.key (added)")

                if fixes_applied:
                    shutil.copy2(cfg_path, cfg_path + f".bak_{int(time.time())}")
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                    for fix in fixes_applied:
                        self.log(f"[Fix] {fix}  ✓", "SUCCESS")
                else:
                    self.log("[Fix] openclaw.json — all values already correct, nothing changed ✓", "INFO")

            except Exception as e:
                self.log(f"[Fix] openclaw.json error: {e}", "ERROR")
        else:
            self.log("[Fix] openclaw.json not found — skipping config fixes", "WARNING")

        # ── File permission hardening (DECISION #18) ───────────────────────────
        self.log("[Fix] Hardening file permissions (icacls)...")
        self.cfg.harden_file_permissions()

        # ── SOUL.md + BOOTSTRAP.md update ─────────────────────────────────────
        soul_content = self.cfg._build_soul_content()
        try:
            self.cfg.safe_write_workspace(soul_path, soul_content)
            self.log("[Fix] SOUL.md updated (LYRA additions preserved) ✓", "SUCCESS")
            self._soul_update_status.config(
                text="✅ Fixes applied · SOUL.md updated — restarting Gateway...",
                foreground="green")
        except Exception as e:
            self.log(f"[Fix] SOUL.md update failed: {e}", "ERROR")
            self._soul_update_status.config(
                text=f"❌ SOUL.md error: {e}", foreground="red")
            return

        # ── Gateway restart ────────────────────────────────────────────────────
        self.root.after(800, self._restart_gateway)
        self.root.after(1000, lambda: self._soul_update_status.config(
            text="✅ Fixes applied · SOUL.md updated · Gateway restarting...",
            foreground="#cc7700"))

    def _apply_search_fix(self):
        """Sets tools.web.search.enabled=false in openclaw.json + restarts Gateway."""
        cfg_dir = self.cfg._find_openclaw_config_dir()
        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        if not os.path.isfile(cfg_path):
            self.log("[Fix] openclaw.json not found!", "ERROR")
            return
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Ensure structure exists
            cfg.setdefault("tools", {}).setdefault("web", {})
            cfg["tools"]["web"]["search"] = {"enabled": False}
            import shutil as _sh
            _sh.copy2(cfg_path, cfg_path + f".bak_{int(time.time())}")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2, ensure_ascii=False)
            self.log("[Fix] tools.web.search.enabled=false set ✓", "SUCCESS")
            self.log("[Fix] Restarting Gateway...", "INFO")
            self._restart_gateway()
        except Exception as e:
            self.log(f"[Fix] Error: {e}", "ERROR")

    # ── WORKER SPECIFIC ─────────────────────────────────────────────

    def _test_worker_conn(self):
        head = self._w_head_entry.get().strip()
        port = self._w_port_entry.get().strip() or str(LYRA_HEAD_PORT)
        url = f"http://{head}:{port}/health"
        self.log(f"[WorkerConn] GET {url} (Timeout 6s)...")
        sc, body = self._diag_api(url, timeout=6)
        if sc == 200:
            self._w_conn_status.config(
                text=f"✅ CONNECTED  HTTP 200 → {str(body)[:60]}", foreground="green")
            self.log(f"[WorkerConn] Connected: {body}", "SUCCESS")
        elif sc == -1:
            hint = ""
            err = str(body)
            if "10061" in err or "refused" in err.lower():
                hint = " → LYRA head task server not running (Port {port} refused)."
            elif "10060" in err or "timed out" in err.lower():
                hint = f" → Timeout 6s – IP '{head}' wrong or firewall blocking."
            elif "11001" in err or "Name or service" in err:
                hint = f" → Hostname '{head}' not resolvable – use IP address instead."
            self._w_conn_status.config(
                text=f"❌ ERROR: {err[:60]}", foreground="red")
            self.log(f"[WorkerConn] Error: {err}{hint}", "ERROR")
        else:
            self._w_conn_status.config(
                text=f"⚠ HTTP {sc} – {str(body)[:50]}", foreground="orange")
            self.log(f"[WorkerConn] HTTP {sc}: {str(body)[:100]}", "WARNING")

    def _save_worker_config(self, role: str):
        """Save Role/Head/SearXNG to machine_role.json, then stop-wait-restart the worker loop."""
        head = self._w_head_entry.get().strip()
        if not head:
            self.log("[WorkerCfg] No LYRA head IP specified!", "ERROR")
            return
        sx_url = (self._sx_url_worker.get().strip()
                  if hasattr(self, "_sx_url_worker") else "http://localhost:8080")
        role_file = os.path.join(os.path.expanduser("~"), ".openclaw", "machine_role.json")
        data = {"role": role, "head_address": head, "searxng_url": sx_url}
        try:
            os.makedirs(os.path.dirname(role_file), exist_ok=True)
            with open(role_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self.log(f"[WorkerCfg] Saved: Role={role}  Head={head}  "
                     f"SearXNG={sx_url}", "SUCCESS")
        except Exception as e:
            self.log(f"[WorkerCfg] Save error: {e}", "ERROR")
            return
        self._stop_then_start_worker_loop(role)

    def _stop_then_start_worker_loop(self, role: str):
        """Stop current worker, save thread refs, wait until dead, then start fresh."""
        # Collect thread refs BEFORE clearing, then signal stop
        threads_to_wait = []
        seen = set()
        for attr in ("_worker_client", "_worker_client_diag"):
            client = getattr(self, attr, None)
            if client and id(client) not in seen:
                seen.add(id(client))
                if hasattr(client, "_thread") and client._thread is not None:
                    threads_to_wait.append(client._thread)
                try:
                    client._stop.set()
                except Exception:
                    pass
            setattr(self, attr, None)
        if hasattr(self, "_w_loop_status"):
            self._w_loop_status.config(text="Loop: stopping...", foreground="orange")
        self.log("[WorkerLoop] Stopping...")
        # Wait until all threads are confirmed dead
        self._wait_for_thread_dead_then_start(role, threads_to_wait)

    def _wait_for_thread_dead_then_start(self, role: str, threads: list):
        """Poll every 500ms until old threads are dead, then start fresh."""
        if any(t.is_alive() for t in threads):
            self.root.after(500, lambda: self._wait_for_thread_dead_then_start(role, threads))
            return
        self._start_worker_loop(role)


    def _start_worker_loop(self, role: str):
        """Start TaskServer + QueuedWorkerClient. Called only after old thread is confirmed dead."""
        head   = self._w_head_entry.get().strip()
        port   = self._w_port_entry.get().strip() or str(LYRA_HEAD_PORT)
        sx_url = (self._sx_url_worker.get().strip()
                  if hasattr(self, "_sx_url_worker") else "http://127.0.0.1:8080")
        model  = "qwen2.5:0.5b" if role == "Junior" else "qwen2.5:1.5b"

        self.log(f"[WorkerLoop] Starting {role} \u2192 {head}:{port}  Model: {model}  SearXNG: {sx_url}")

        # Reuse existing server+queue if already running — never create a parallel server
        import queue as _q
        existing_srv = getattr(self, "_worker_server", None)
        if existing_srv is not None and hasattr(existing_srv, "task_queue"):
            task_queue = existing_srv.task_queue
            self.log(f"[WorkerLoop] Reusing existing TaskServer queue \u2713", "SUCCESS")
        else:
            task_queue = _q.Queue()
            worker_server = WorkerTaskServer(port=LYRA_HEAD_PORT, log_fn=self.log, task_queue=task_queue)
            if worker_server.start():
                self._worker_server = worker_server
                self.log(f"[WorkerLoop] Task server started on port {LYRA_HEAD_PORT} \u2713", "SUCCESS")
            else:
                self.log("[WorkerLoop] Task server start failed \u2013 port may already be in use", "WARNING")

        worker_client = self._make_queued_worker_client(
            head_address=head, role=role, model=model,
            task_queue=task_queue, searxng_url=sx_url)
        worker_client.start()
        self._worker_client      = worker_client
        self._worker_client_diag = worker_client

        if hasattr(self, "_w_loop_status"):
            self._w_loop_status.config(text=f"\u2705 Loop ACTIVE \u2192 {head}:{port}", foreground="green")
        self.log("[WorkerLoop] Started \u2713 (TaskServer + QueuedWorkerClient)", "SUCCESS")

    def _restart_worker_loop(self, role: str):
        """Button handler: stop then wait then start."""
        self._stop_then_start_worker_loop(role)

    def _stop_worker_loop(self):
        """Signal stop to all running worker clients and clear references."""
        stopped = set()
        for attr in ("_worker_client", "_worker_client_diag"):
            client = getattr(self, attr, None)
            if client and id(client) not in stopped:
                try:
                    client._stop.set()
                    stopped.add(id(client))
                except Exception:
                    pass
            setattr(self, attr, None)
        if hasattr(self, "_w_loop_status"):
            self._w_loop_status.config(text="Loop: stopped", foreground="gray")
        self.log("[WorkerLoop] Stopped")

    def _update_worker_loop_status(self):
        client = getattr(self, "_worker_client_diag", None) or getattr(self, "_worker_client", None)
        if client and hasattr(client, "_thread") and client._thread and client._thread.is_alive():
            if hasattr(self, "_w_loop_status"):
                self._w_loop_status.config(
                    text=f"✅ Loop running (started at init)", foreground="green")
        else:
            if hasattr(self, "_w_loop_status"):
                self._w_loop_status.config(text="Loop: not active", foreground="gray")

    def _check_worker_components(self):
        """Check Task Server + Worker Client status with full log output.

        Every check branch now calls self.log() so the Log tab shows
        diagnostic output. Previously only the label widgets were updated —
        the Log tab stayed empty and offered no diagnostic trail.

        Checks:
          Task Server: GET http://127.0.0.1:LYRA_HEAD_PORT/health (timeout 3s)
          Worker Client: thread-alive check on _worker_client OR _worker_client_diag
        """
        # ── Task Server ───────────────────────────────────────────────────────
        self.log(f"[Components] Checking Task Server on port {LYRA_HEAD_PORT}...")
        try:
            sc, body = self._diag_api(
                f"http://127.0.0.1:{LYRA_HEAD_PORT}/health", timeout=3)
            if sc == 200:
                msg = f"Task Server: ✅ RUNNING  (HTTP 200 → {str(body)[:60]})"
                self._w_server_status.config(text=msg, foreground="green")
                self.log(f"[Components] {msg}", "SUCCESS")
            else:
                msg = f"Task Server: ❌ ERROR  (HTTP {sc})"
                self._w_server_status.config(text=msg, foreground="red")
                self.log(f"[Components] {msg} → {str(body)[:80]}", "ERROR")
        except Exception as e:
            msg = f"Task Server: ❌ NOT RUNNING  ({str(e)[:60]})"
            self._w_server_status.config(text=msg, foreground="red")
            self.log(f"[Components] {msg}", "ERROR")

        # ── Worker Client ─────────────────────────────────────────────────────
        self.log("[Components] Checking Worker Client...")
        # Check both possible attribute names (install path vs UI button path)
        client = (getattr(self, "_worker_client", None) or
                  getattr(self, "_worker_client_diag", None))
        if client and hasattr(client, "_thread") and client._thread and client._thread.is_alive():
            model = getattr(client, "model", "?")
            role  = getattr(client, "role",  "?")
            msg = f"Worker Client: ✅ ACTIVE  ({role} | {model})"
            self._w_client_status.config(text=msg, foreground="green")
            self.log(f"[Components] {msg}", "SUCCESS")
        else:
            reason = "no client created" if not client else "thread not alive"
            msg = f"Worker Client: ❌ STOPPED  ({reason})"
            self._w_client_status.config(text=msg, foreground="red")
            self.log(f"[Components] {msg} → Use '▶ Start loop' or restart app",
                     "ERROR")

    def _check_worker_gateway(self):
        """Check gateway health on this worker machine (port 18789).

        Mirrors _check_gateway() but updates the worker-specific
        _w_gw_status label instead of the HEAD _gw_status label.
        Uses the same /api/health endpoint and timeout.
        """
        if not hasattr(self, "_w_gw_status"):
            return
        # DECISION: /health (2026.3.1+), Fallback /api/health (aeltere Versionen).
        # Token als Query-Parameter wegen auth.mode=token.
        token = self.cfg._read_token_from_config() or "lyra-local-token"
        url = f"http://127.0.0.1:18789/health?token={token}"
        self.log(f"[Worker-GW] GET /health (Timeout 5s, Token={token[:8]}...)")
        sc, body = self._diag_api(url, timeout=5)
        if sc == 404:
            url = f"http://127.0.0.1:18789/api/health?token={token}"
            self.log("[Worker-GW] /health=404, trying /api/health (older version)...")
            sc, body = self._diag_api(url, timeout=5)
        if 0 < sc < 400:
            self._w_gw_status.config(
                text=f"✅ ONLINE (HTTP {sc}) → {str(body)[:60]}", foreground="green")
            self.log(f"[Worker-GW] Reachable HTTP {sc}: {str(body)[:80]}", "SUCCESS")
        elif sc == -1:
            hint = (" → Gateway not running. Click '(Re)start Gateway'."
                    if "10061" in str(body) else "")
            self._w_gw_status.config(
                text=f"❌ OFFLINE – {str(body)[:50]}", foreground="red")
            self.log(f"[Worker-GW] Error: {body}{hint}", "ERROR")
        else:
            self._w_gw_status.config(text=f"⚠ HTTP {sc}", foreground="orange")
            self.log(f"[Worker-GW] HTTP {sc} → {str(body)[:100]}", "WARNING")

    def _restart_worker_gateway(self):
        """Start or restart the OpenClaw gateway on this worker machine.

        Identical logic to _restart_gateway() (HEAD) — both use the
        same gateway.cmd path (~/.openclaw/gateway.cmd).

        Added third health check after 30s for slow/old hardware.
          Observed on i5-2500 (no AVX2): Node.js + model loading takes 15-40s.
          The 4s and 8s checks fired before the gateway was ready, showing OFFLINE
          even though the gateway started successfully a few seconds later.
          The 30s check covers all known slow-hardware scenarios.
          On fast hardware the 4s check already succeeds — no regression.

        Schedules three gateway health checks (4s / 8s / 30s) that update
        the _w_gw_status label.
        """
        self.log("[Worker-GW] Stopping old gateway processes...")
        self.force_kill_openclaw_processes()
        gw_cmd = os.path.join(os.path.expanduser("~"), ".openclaw", "gateway.cmd")
        if os.path.isfile(gw_cmd):
            # ⚠️  EDGE-LÖSUNG: patch BEFORE start — same root cause as HEAD gateway.
            # Without OLLAMA_API_KEY in ENV block, gateway starts but returns HTTP 404.
            self.log("[Worker-GW] Patching gateway.cmd (ENV block)...")
            self.cfg.patch_gateway_cmd()

            import subprocess as _sp
            _sp.Popen(
                ["cmd.exe", "/c", gw_cmd],
                creationflags=0x00000010,  # CREATE_NEW_CONSOLE
            )
            self.log(f"[Worker-GW] Started via: {gw_cmd}", "SUCCESS")
            self.log("[Worker-GW] Checking in 4s / 8s / 30s (slow hardware covered)...",
                     "INFO")
            self.root.after(4000,  self._check_worker_gateway)
            self.root.after(8000,  self._check_worker_gateway)
            self.root.after(30000, self._check_worker_gateway)
        else:
            self.log("[Worker-GW] gateway.cmd not found – OpenClaw installed?", "ERROR")

    def _pull_worker_model(self):
        """Pull an Ollama model from the Worker Config tab.

        Wrapper around the same pull logic as _pull_ollama_model(),
        but reads the model name from _w_pull_entry and updates _w_pull_status
        instead of the Lyra Config tab's _pull_entry / _pull_status labels.

        Uses the same auto-detection of Ollama runtime environment (WSL vs
        Windows-native) and streams progress to the main Log tab.
        On success, refreshes the model dropdowns automatically.
        """
        model = self._w_pull_entry.get().strip()
        if not model:
            self._w_pull_status.config(text="⚠ Please enter a model name.",
                                       foreground="orange")
            return

        self._w_pull_status.config(
            text=f"⬇ Pulling {model} … (see Log tab for progress)",
            foreground="#0055cc")
        self.log(f"[Worker Pull] ⬇ Starting: {model}", "INFO")

        wsl_ok, ubuntu_ok = self.check_wsl()
        ollama_in_wsl = wsl_ok and ubuntu_ok and self.check_ollama_wsl()

        def _do_pull():
            import subprocess as _sp
            try:
                if ollama_in_wsl:
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive",
                           "-Command",
                           f'wsl bash -lc "OLLAMA_HOST=127.0.0.1:11434 ollama pull {model} 2>&1"']
                else:
                    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive",
                           "-Command", f"ollama pull {model} 2>&1"]

                proc = _sp.Popen(cmd, stdout=_sp.PIPE, stderr=_sp.STDOUT,
                                 encoding="utf-8", errors="replace")
                success = False
                for line in proc.stdout:
                    line = line.rstrip()
                    if line:
                        self.log(f"  [pull] {line}", "INFO")
                    if "success" in line.lower():
                        success = True
                proc.wait()

                if proc.returncode == 0 or success:
                    self.root.after(0, lambda: self._w_pull_status.config(
                        text=f"✅ {model} ready! Model list updated.",
                        foreground="green"))
                    self.root.after(0, lambda: self.log(
                        f"[Worker Pull] ✅ {model} successfully loaded!", "SUCCESS"))
                    self.root.after(600, self._refresh_ollama_models)
                else:
                    self.root.after(0, lambda: self._w_pull_status.config(
                        text=f"❌ Pull failed (code {proc.returncode}) — check Log tab.",
                        foreground="red"))
            except Exception as e:
                self.root.after(0, lambda: self._w_pull_status.config(
                    text=f"❌ Error: {e}", foreground="red"))
                self.log(f"[Worker Pull] Error: {e}", "ERROR")

        import threading as _th
        _th.Thread(target=_do_pull, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    # HELPER METHODS (UI)
    # ──────────────────────────────────────────────────────────────────

    def _copy_sel(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.log_text.get(tk.SEL_FIRST, tk.SEL_LAST))
        except:
            pass

    def _copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", tk.END))
        self.log("Log copied to clipboard")

    def _clear(self):
        self.log_text.delete("1.0", tk.END)

    def _set_status(self, text):
        self.status_label.config(text=text)

    # ──────────────────────────────────────────────────────────────────
    # LOGGING
    # ──────────────────────────────────────────────────────────────────

    def log(self, message, level="INFO"):
        """Thread-safe logging via queue. Never calls root.update() to avoid tkinter reentry."""
        icons = {"ERROR": "❌", "SUCCESS": "✅", "WARNING": "⚠️",
                 "DEBUG": "🔍", "CMD": "💻"}
        icon = icons.get(level, "📌")
        ts = time.strftime("%H:%M:%S")
        self._log_queue.put(f"[{ts}] {icon} {message}\n")

    def _flush_log_queue(self):
        """Drain log queue into text widget every 50ms via root.after. No reentry possible."""
        try:
            while True:
                self.log_text.insert(tk.END, self._log_queue.get_nowait())
        except Exception:
            pass
        if self.auto_scroll:
            self.log_text.see(tk.END)
        self.root.after(50, self._flush_log_queue)

    # ──────────────────────────────────────────────────────────────────
    # HARDWARE INFO (v6)
    # ──────────────────────────────────────────────────────────────────

    def determine_machine_role(self):
        """
        ALWAYS asks for the machine role – even if machine_role.json exists.
        If saved role exists: confirmation dialog (Yes=keep, No=reconfigure).
        Saves result to ~/.openclaw/machine_role.json.

        Returns: (role: str, head_address: str|None)
          role = "Lyra" | "Senior" | "Junior"
          head_address = IP/hostname of LYRA head (only for Senior/Junior)
          (None, None) = user cancelled

        Role logic:
          AVX2 present → dialog: LYRA (head) or Senior?
          AVX2 missing → automatically Junior (no dialog needed)
          Senior/Junior → IP query for LYRA head (required field)

        Head reachability:
          For saved worker role: HTTP HEAD against LyraHeadServer /health
          Not reachable → warning, setup continues anyway
        """
        # Already configured?
        role_file = os.path.join(os.path.expanduser("~"), ".openclaw", "machine_role.json")
        saved_role = None
        saved_head = None
        if os.path.isfile(role_file):
            try:
                with open(role_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_role = data.get("role", "Lyra")
                saved_head = data.get("head_address", "") or None
            except Exception:
                pass

        # Always ask – even if saved role exists
        # (prevents the dialog from being silently skipped during setup)
        if saved_role:
            head_info = f"\n  Saved head IP: {saved_head}" if saved_head else ""
            keep = messagebox.askyesno(
                "Machine Role – saved configuration",
                f"⚙️  Existing role configuration found:\n\n"
                f"  Role: {saved_role}{head_info}\n\n"
                f"  Should this configuration be kept?\n\n"
                f"  [Yes]  = Use existing configuration\n"
                f"  [No] = Reconfigure"
            )
            if keep:
                self.log(f"  Using existing role: {saved_role}" +
                         (f"  (Head: {saved_head})" if saved_head else ""), "SUCCESS")
                # Check head reachability (only for worker roles)
                if saved_role in ("Senior", "Junior") and saved_head:
                    self.log(f"  Checking LYRA head reachability: {saved_head}:{LYRA_HEAD_PORT} ...")
                    worker_check = LyraWorkerClient(saved_head, saved_role, "", log_fn=self.log)
                    if worker_check.check_head_reachable(timeout=4):
                        self.log(f"  LYRA head reachable ✓", "SUCCESS")
                    else:
                        self.log(f"  LYRA head NOT reachable – setup continues anyway",
                                 "WARNING")
                return saved_role, saved_head
            else:
                self.log("  Reconfiguring...", "INFO")
                # Delete old file so we can start fresh
                try:
                    os.remove(role_file)
                except Exception:
                    pass

        has_avx2 = self._detect_avx2()
        self.log(f"  AVX2 detection: {'✓ present' if has_avx2 else '✗ not present'}")

        role = None
        head_address = None

        if has_avx2:
            # Dialog: LYRA or Senior?
            ans = messagebox.askyesno(
                "Choose machine role",
                "✅ AVX2 support detected!\n\n"
                "Should this machine act as\n\n"
                "  ● LYRA (central head, powerful model, orchestration)\n"
                "  ● or as a Senior worker?\n\n"
                "[Yes] = LYRA (head)\n"
                "[No] = Senior worker"
            )
            role = "Lyra" if ans else "Senior"
        else:
            # Only Junior possible
            ans = messagebox.askyesno(
                "Choose machine role",
                "⚠️  AVX2 missing – this machine can only be used as a Junior worker\n"
                "(small, fast model: qwen2.5:0.5b).\n\n"
                "Do you want to set it up as a Junior worker?"
            )
            if not ans:
                messagebox.showinfo(
                    "Setup cancelled",
                    "Setup was cancelled.\n"
                    "For LYRA or Senior role, AVX2 support is required."
                )
                return None, None
            role = "Junior"

        # IP query for Senior / Junior
        if role in ("Senior", "Junior"):
            import tkinter.simpledialog as sd
            head_address = sd.askstring(
                f"{role} mode: LYRA head address",
                f"✅ {role} mode selected.\n\n"
                f"What IP address or hostname does the LYRA head have?\n"
                f"(Example: 192.168.178.42 or powermachine.local)",
                parent=self.root
            )
            if not head_address or not head_address.strip():
                messagebox.showwarning(
                    "Setup cancelled",
                    "No LYRA head address provided – setup cancelled.\n"
                    "Please restart the installer and provide the LYRA head address."
                )
                return None, None
            head_address = head_address.strip()

        # Save
        os.makedirs(os.path.dirname(role_file), exist_ok=True)
        role_data = {"role": role}
        if head_address:
            role_data["head_address"] = head_address
        try:
            with open(role_file, "w", encoding="utf-8") as f:
                json.dump(role_data, f, indent=2)
            self.log(f"  Role saved: {role_file}", "SUCCESS")
        except Exception as e:
            self.log(f"  Warning: role could not be saved: {e}", "WARNING")

        self.log(f"  ✅ Role successfully set: {role}" +
                 (f"  (LYRA head: {head_address})" if head_address else ""), "SUCCESS")
        return role, head_address

    def start_installation(self):
        if self.installation_running:
            return

        ok = messagebox.askyesno(
            "OpenClaw + LYRA Installation",
            "The setup will automatically perform the following steps:\n\n"
            "1.  Check admin privileges\n"
            "2.  Prepare Windows system (Long Paths, ExecutionPolicy)\n"
            "3.  Install Windows App Runtime + winget (if needed)\n"
            "4.  Install Node.js v22 (if needed)\n"
            "5.  Install Git (if needed) – 5 mirror URLs\n"
            "6.  Install CMake (if needed)\n"
            "7.  Install Visual C++ Redistributable (if needed)\n"
            "8.  Install Build Tools (xpm, node-gyp, MSVC)\n"
            "    ⚠️  MSVC installation: up to 40 min. on slow machines!\n"
            "9.  Configure npm\n"
            "10. Install / repair OpenClaw\n"
            "11. Set up gateway\n"
            "── Machine role hierarchy ──\n"
            "12. Check / install WSL2 + Ubuntu\n"
            "13. Install + start Ollama in WSL2\n"
            "14. Load LLM models (role-based)\n"
            "15. Configure OpenClaw for Ollama/LYRA\n"
            "16. Create LYRA agent + send test prompt\n\n"
            "All steps are displayed live in the log.\n\nSTART NOW?"
        )
        if not ok:
            return

        # ── Role dialog (v38) ─────────────────────────────────────────
        self.log("\n🌀 MACHINE ROLE DIALOG ")
        role, head_address = self.determine_machine_role()
        if role is None:
            self.log("Setup cancelled by user.", "WARNING")
            return

        self.machine_role = role
        self.head_address = head_address
        self.cfg._machine_role = role  # Keep config module in sync

        # Build diagnostics tab if not yet present (role was unknown at startup)
        if not self._diag_tab_built:
            self._build_diag_tab(role, head_address)
        # Update role badge in title bar
        if hasattr(self, "_role_badge"):
            self._role_badge.config(text=f"  [{role}]")

        self.installation_running = True
        self.main_button.config(state="disabled", text="⚙️ INSTALLATION RUNNING... (LYRA awakening)")
        self.progress["value"] = 0
        self.auto_scroll = True

        self.log("\n" + "=" * 70)
        self.log(f"STARTING INSTALLATION + LYRA SETUP  [Role: {role}" +
                 (f"  |  Head: {head_address}" if head_address else "") + "]")
        self.log("=" * 70)

        threading.Thread(target=self.installation_process, daemon=True).start()

    # ──────────────────────────────────────────────────────────────────
    # WORKER MODE (Junior / Senior) – v38
    # ──────────────────────────────────────────────────────────────────

    def _install_worker_mode(self, role: str, head_address: str):
        """
        Lightweight setup for Junior/Senior workers (no OpenClaw installation required).

        Now starts BOTH task server (to receive tasks) and client (to execute them).
        Ollama installation now uses the full 4-option fallback chain, identical to
          HEAD (_install_lyra_mode). Previously only WSL installation was attempted, which left
          ollama invisible in PowerShell on machines with Windows-native Ollama installed via
          winget or OllamaSetup.exe. The correct entry point is install_ollama_wsl() which
          already contains all four options (native check → WSL → winget → EXE download).

        Workflow:
          1. Check / install WSL2 + Ubuntu
          2. Check / install Ollama (4-option chain: native → WSL → winget → EXE)
          3. setup_ollama_autostart() + start_ollama_serve() with WSL restart fallback
          4. Load worker model (Junior: qwen2.5:0.5b, Senior: qwen2.5:1.5b+)
          5. Test prompt: "Are you there?" → expects "Yes"
          6. Start WorkerTaskServer (listens on port 18790 for incoming tasks)
          7. Start QueuedWorkerClient (background thread, processes tasks from queue)
          8. Display dashboard box with connection info

        Ollama install_ollama_wsl() chain (all options with _refresh_path):
          A) Already natively installed on Windows → done immediately
          B) WSL install via curl install.sh (90s timeout)
          C) Windows-native via winget install Ollama.Ollama + _refresh_path
          D) Direct OllamaSetup.exe download + /SILENT install + _refresh_path

        Known pitfalls:
          - f-strings with JSON in self.log() → ValueError (no f-prefix for JSON lines!)
          - HTML tags in web_search response must be stripped
          - wttr.in returns plain text → no HTML strip needed, use directly
          - ollama not visible in PowerShell: _refresh_path() must be called after
            Windows-native install (handled inside install_ollama_wsl)
        """
        self.log(f"\n🤝 WORKER SETUP: {role.upper()} mode")
        self.log(f"   Connecting to LYRA head: {head_address}")
        self.progress["value"] = 5

        # Model based on role
        if role == "Junior":
            worker_model = "qwen2.5:0.5b"
            ollama_timeout = 600
        else:  # Senior
            worker_model = "qwen2.5:1.5b"
            ollama_timeout = 600

        self.log(f"   Model for {role}: {worker_model}")

        # ── Check WSL2 / Ollama ──────────────────────────────────────
        self._set_status(f"{role}: Checking WSL2 + Ollama...")
        self.log(f"\n📦 WSL2 + Ollama for {role} checking")
        self.progress["value"] = 20

        wsl_ok, ubuntu_ok = self.check_wsl()
        if not (wsl_ok and ubuntu_ok):
            self.log("  WSL2/Ubuntu missing – installing...", "WARNING")
            self.install_wsl()
            wsl_ok, ubuntu_ok = self.check_wsl()

        if wsl_ok and ubuntu_ok:
            self.log("  WSL2 + Ubuntu OK", "SUCCESS")
        else:
            self.log("  WSL2/Ubuntu not available – restart may be needed!", "WARNING")

        # install_ollama_wsl() contains the full 4-option chain
        # (native check → WSL → winget → EXE) — same as HEAD.
        # It also calls _refresh_path() for all Windows-native paths so that
        # 'ollama' becomes visible in PowerShell immediately after install.
        if not self.check_ollama_wsl():
            self.log("  Ollama not found in WSL – running full install chain...", "WARNING")
            self.log("  (checks Windows-native first, then WSL, then winget, then EXE)",
                     "INFO")
            self.install_ollama_wsl()
        else:
            self.log("  Ollama (WSL) already present ✓", "SUCCESS")

        # Also verify Windows-native visibility in PowerShell (belt-and-suspenders)
        r_native = self.run_powershell("ollama --version 2>$null")
        if r_native["returncode"] == 0 and r_native["stdout"].strip():
            self.log("  Ollama visible in PowerShell ✓", "SUCCESS")
        else:
            self.log("  Ollama not in Windows PATH – _refresh_path()...", "WARNING")
            self._refresh_path()

        self.setup_ollama_autostart()
        ollama_ok = self.start_ollama_serve()
        if not ollama_ok:
            self.log("  Ollama start failed – trying WSL restart...", "WARNING")
            self.run_powershell("wsl --shutdown 2>$null; Start-Sleep 5")
            time.sleep(6)
            ollama_ok = self.start_ollama_serve()

        if ollama_ok:
            self.wait_for_ollama(max_wait=20)

        # ── Load worker model ───────────────────────────────────────
        self._set_status(f"{role}: Loading model ({worker_model})...")
        self.log(f"\n🌀 Loading {role} model: {worker_model}")
        self.progress["value"] = 50

        wsl_inst, ub_inst = self.check_wsl()
        if wsl_inst and ub_inst and self.check_ollama_wsl():
            r = self._wsl_cmd_live(
                f"OLLAMA_HOST=127.0.0.1:11434 ollama pull {worker_model}",
                timeout=7200, prefix="    "
            )
        else:
            r = self.run_powershell_live(
                f"ollama pull {worker_model} 2>&1",
                timeout=7200, prefix="    "
            )

        if r.get("returncode", 1) == 0:
            self.log(f"  {worker_model} loaded!", "SUCCESS")
        else:
            combined = (r.get("stdout", "") + r.get("stderr", "")).lower()
            if "success" in combined:
                self.log(f"  {worker_model} loaded (via success heuristic)!", "SUCCESS")
            else:
                self.log(f"  {worker_model} failed – do manually later!", "WARNING")
                self.log(f"    wsl bash -lc 'ollama pull {worker_model}'", "WARNING")

        # ── Test prompt (minimal, deterministic) ────────────────────
        self._set_status(f"{role}: Sending test prompt...")
        self.log(f"\n🔍 Test prompt for {role}...")
        self.progress["value"] = 80

        test_payload = {
            "model": worker_model,
            "messages": [
                {"role": "system", "content": "Answer with only one word: Yes"},
                {"role": "user",   "content": "Are you there?"}
            ],
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.9}
        }
        sc, body = self._api("POST", "/api/chat", test_payload,
                             base="http://127.0.0.1:11434", timeout=ollama_timeout)
        if sc == 200 and isinstance(body, dict):
            content = (body.get("message", {}).get("content", "")
                       or body.get("response", ""))
            if content:
                self.log(f"  {role} responds: \"{content[:100]}\"", "SUCCESS")
            else:
                self.log(f"  {role} responds (no text content)", "WARNING")
        else:
            self.log(f"  Test prompt failed (HTTP {sc}) – Ollama still starting?",
                     "WARNING")

        # ── Searxng check ─────────────────────────────────────────────
        self._set_status(f"{role}: Checking Searxng...")
        self.log(f"\n🔍 Searxng check (local search service via Docker)...")
        self.progress["value"] = 87
        searxng_ok = False
        searxng_port = 8080
        try:
            test_url = f"http://localhost:{searxng_port}/search?q=test&format=json"
            req = urllib.request.Request(
                test_url, headers={"User-Agent": "LyraWorker/1.0",
                                   "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read(4096).decode("utf-8"))
            if "results" in data or "query" in data:
                searxng_ok = True
                self.log(f"  Searxng running on port {searxng_port} ✓", "SUCCESS")
                self.log(f"  Worker will use Searxng for all web_search tasks", "SUCCESS")
        except Exception as sx_err:
            self.log(f"  Searxng not reachable: {sx_err}", "WARNING")
            self.log(f"  Check: docker ps | grep searxng", "WARNING")
            self.log(f"  Worker will fall back to direct URL fetches (wttr.in etc.)", "WARNING")
            self.log(f"  Start Searxng manually:", "WARNING")
            self.log(f"    docker run -d -p 8080:8080 searxng/searxng", "WARNING")

        # ── Connection info + start worker components ─────────────────
        self.progress["value"] = 95
        self.log(f"\n✅ {role} mode set up!")
        self.log(f"   LYRA head: {head_address}")
        self.log(f"   Model:    {worker_model}")

        # ── Start Worker Task Server (receives tasks from HEAD) ──────
        self.log(f"\n🌐 Starting worker task server (port {LYRA_HEAD_PORT})...")
        import queue as queue_module
        task_queue = queue_module.Queue()

        worker_server = WorkerTaskServer(
            port=LYRA_HEAD_PORT,
            log_fn=self.log,
            task_queue=task_queue
        )
        if worker_server.start():
            self._worker_server = worker_server
            self.log(f"  Task server running on port {LYRA_HEAD_PORT} ✓", "SUCCESS")
        else:
            self.log(f"  Task server start failed – port {LYRA_HEAD_PORT} in use?", "WARNING")

        # ── Start Worker Client (executes tasks) ─────────────────────
        self.log(f"\n🔄 Starting worker client (poll loop)...")
        # Use _make_queued_worker_client factory (shared with auto-start + UI button)
        sx_url = (self._sx_url_worker.get().strip()
                  if hasattr(self, "_sx_url_worker") else "http://127.0.0.1:8080")
        worker_client = self._make_queued_worker_client(
            head_address=head_address,
            role=role,
            model=worker_model,
            task_queue=task_queue,
            searxng_url=sx_url
        )
        worker_client.start()
        self._worker_client      = worker_client
        self._worker_client_diag = worker_client
        self.log(f"   Worker client active – processing tasks from queue", "SUCCESS")

        # Check head reachability
        time.sleep(2)
        if worker_client.check_head_reachable(timeout=4):
            self.log(f"   LYRA head responds ✓", "SUCCESS")
        else:
            self.log(f"   LYRA head not yet reachable – will connect automatically once online",
                     "WARNING")

        self.progress["value"] = 100
        self._set_status(f"{role} ready!")
        self.log(f"\n🌀 Role successfully set: {role}", "SUCCESS")

        # ── Final dashboard box ──────────────────────────────────────
        head_ip = head_address if head_address else "head-ip"
        self.log("\n" + "╔" + "═" * 62 + "╗")
        self.log(  "║" + "        LYRA SYSTEM READY – WORKER ACTIVE              ".center(62) + "║")
        self.log(  "╚" + "═" * 62 + "╝")
        self.log(f"  Role:       {role}")
        self.log(f"  LYRA head:   http://{head_ip}:18789")
        self.log(f"  Task server: http://{head_ip}:{LYRA_HEAD_PORT} (send tasks here)")
        self.log(f"  Worker port: {LYRA_HEAD_PORT} (listening for tasks)")
        self.log(f"  Model:      {worker_model}")
        self.log(f"  Searxng:     {'✓ http://localhost:8080' if searxng_ok else '✗ not found (start manually!)'}")
        self.log(f"  Components:  ✅ Task Server + ✅ Worker Client")
        self.log(f"")
        self.log(f"  Test from HEAD:")
        self.log(f'    Invoke-RestMethod -Uri "http://{head_ip}:{LYRA_HEAD_PORT}/tasks" -Method POST \\')
        self.log( '      -ContentType "application/json" \\')
        self.log( '      -Body \'{"type":"batch_exec","payload":{"cmd":"echo Hello"}}\'')
        self.log("=" * 70)

    def installation_process(self):
        try:
            machine_role = getattr(self, "machine_role", "Lyra")
            head_address = getattr(self, "head_address", None)

            self.log(f"\n🌀 Machine role: {machine_role}" +
                     (f"  |  LYRA head: {head_address}" if head_address else ""), "SUCCESS")

            # ── CRITICAL: For Junior/Senior, run worker mode and EXIT ──
            if machine_role in ("Junior", "Senior"):
                if not head_address:
                    self.log("ERROR: No head address provided for worker mode!", "ERROR")
                    return
                self._install_worker_mode(machine_role, head_address)
                return  # ← IMPORTANT: Exit here, don't run head setup!

            # ── From here: Full LYRA head setup ─────────────────────────

            # ── 1: Admin ──────────────────────────────────────────────
            self._set_status("Step 1/16: Checking admin privileges...")
            self.log("\n🔍 STEP 1/16: Checking admin privileges")
            self.progress["value"] = 3
            if not self.check_admin():
                self.log("ERROR: Please run as administrator!", "ERROR")
                return
            self.log("Administrator privileges OK", "SUCCESS")

            # ── 2: Prepare system ─────────────────────────────────
            self._set_status("Step 2/16: Preparing Windows system...")
            self.log("\n⚙️  STEP 2/16: Preparing Windows system")
            self.progress["value"] = 8
            self.prepare_system()

            # ── 3: winget (including Windows App Runtime) ─────────────────
            self._set_status("Step 3/16: Checking winget + Windows App Runtime...")
            self.log("\n📦 STEP 3/16: Checking winget + Windows App Runtime")
            self.progress["value"] = 14

            # Check Windows App Runtime first – prevents HRESULT 0x80073CF3
            war = self.check_windows_app_runtime()
            if war:
                self.log(f"Windows App Runtime present: {war}", "SUCCESS")
            else:
                self.log("Windows App Runtime missing (needed for winget) – installing...")
                if self.install_windows_app_runtime():
                    self.log("Windows App Runtime installed", "SUCCESS")
                else:
                    self.log("Windows App Runtime failed – winget may not be possible",
                             "WARNING")

            if self.check_winget():
                r = self.run_powershell("winget --version 2>$null")
                self.log(f"winget {r['stdout']}", "SUCCESS")
            else:
                self.log("winget not found – installing...")
                if self.install_winget():
                    r = self.run_powershell("winget --version 2>$null")
                    self.log(f"winget {r['stdout']} installed", "SUCCESS")
                else:
                    self.log("winget not installable – direct downloads as fallback", "WARNING")

            # ── 4: Node.js ────────────────────────────────────────────
            self._set_status("Step 4/16: Checking Node.js...")
            self.log("\n📦 STEP 4/16: Checking Node.js")
            self.progress["value"] = 22
            node_ver, node_ok = self.check_node()
            if node_ver:
                self.log(f"Node.js {node_ver}", "SUCCESS")
                if not node_ok:
                    self.log(f"  Version {node_ver} too old – installing v22...", "WARNING")
                    self.install_node()
            else:
                self.log("Node.js not found – installing...")
                if not self.install_node():
                    self.log("CRITICAL: Node.js installation failed!", "ERROR")
                    return
                node_ver, _ = self.check_node()
                self.log(f"Node.js {node_ver} installed", "SUCCESS")

            # ── 5: Git ────────────────────────────────────────────────
            self._set_status("Step 5/16: Checking Git...")
            self.log("\n🔧 STEP 5/16: Checking Git")
            self.progress["value"] = 30
            git_ver = self.check_git()
            if git_ver:
                self.log(git_ver, "SUCCESS")
            else:
                self.log("Git not found – installing...")
                if self.install_git():
                    self.log(f"Git installed: {self.check_git()}", "SUCCESS")
                else:
                    self.log("Git could not be installed!", "WARNING")

            # ── 6: CMake ──────────────────────────────────────────────
            self._set_status("Step 6/16: Checking CMake...")
            self.log("\n🔧 STEP 6/16: Checking CMake (needed for native npm modules)")
            self.progress["value"] = 38
            cmake_ver = self.check_cmake()
            if cmake_ver:
                self.log(cmake_ver, "SUCCESS")
            else:
                self.log("CMake not found – installing...")
                if self.install_cmake():
                    self.log(f"CMake installed: {self.check_cmake()}", "SUCCESS")
                else:
                    self.log("CMake could not be installed!", "WARNING")
                    self.log("  Manual: https://cmake.org/download/", "WARNING")
                    self.log("  -> cmake-x.x.x-windows-x86_64.msi (enable ADD_CMAKE_TO_PATH!)",
                             "WARNING")

            # ── 7: Visual C++ Redistributable ─────────────────────────
            self._set_status("Step 7/16: Checking Visual C++ Redistributable...")
            self.log("\n🔧 STEP 7/16: Checking Visual C++ Redistributable")
            self.progress["value"] = 46
            vcredist = self.check_vcredist()
            if vcredist:
                self.log(f"VC++ Redistributable present: {vcredist}", "SUCCESS")
            else:
                self.log("VC++ Redistributable not found – installing...")
                if self.install_vcredist():
                    self.log("VC++ Redistributable installed", "SUCCESS")
                else:
                    self.log("VC++ Redist could not be installed!", "WARNING")
                    self.log("  Manual: https://aka.ms/vs/17/release/vc_redist.x64.exe", "WARNING")

            # ── 8: Build Tools (xpm, node-gyp, MSVC) ──────────────────
            self._set_status("Step 8/16: Checking Build Tools...")
            self.log("\n🔨 STEP 8/16: Checking Build Tools (xpm / node-gyp / MSVC)")
            self.progress["value"] = 54

            # xpm
            xpm_ver = self.check_xpm()
            if xpm_ver:
                self.log(f"xpm {xpm_ver} present", "SUCCESS")
            else:
                self.log("xpm not found – installing...")
                self.install_xpm()

            # node-gyp
            gyp_ver = self.check_node_gyp()
            if gyp_ver:
                self.log(f"node-gyp {gyp_ver} present", "SUCCESS")
            else:
                self.log("node-gyp not found – installing...")
                self.install_node_gyp()

            # MSVC Build Tools
            bt = self.check_windows_build_tools()
            if bt:
                self.log(f"Windows Build Tools present: {bt[:80]}", "SUCCESS")
            else:
                self.log("Windows Build Tools not found – installing...")
                self.install_windows_build_tools()

            # ── 9: Configure npm ──────────────────────────────────
            self._set_status("Step 9/16: Configuring npm...")
            self.log("\n⚙️  STEP 9/16: Configuring npm")
            self.progress["value"] = 62
            self.configure_npm()

            # ── 10: OpenClaw ───────────────────────────────────────────
            self._set_status("Step 10/16: Installing OpenClaw...")
            self.log("\n🤖 STEP 10/16: Checking / installing OpenClaw")
            self.progress["value"] = 68
            oc_ok, oc_detail = self.check_openclaw()
            if oc_ok and oc_detail == "ok":
                self.log("OpenClaw already installed and functional", "SUCCESS")
            else:
                msg = ("OpenClaw found but incomplete – repairing..."
                       if oc_ok else "OpenClaw not found – installing...")
                self.log(msg)
                if not self.fix_openclaw_installation():
                    self.log("CRITICAL: OpenClaw installation failed!", "ERROR")
                    return

            self.progress["value"] = 88

            # ── 11: Gateway ────────────────────────────────────────────
            self._set_status("Step 11/16: Setting up gateway...")
            self.log("\n🚪 STEP 11/16: Setting up gateway")
            self.progress["value"] = 90

            # v10 PRE-FLIGHT: Clean config FIRST, BEFORE gateway is started!
            # Otherwise gateway start/install reads the old broken config and crashes immediately.
            self.log("  Pre-flight: Cleaning config before gateway start...")
            self.cfg.write_openclaw_config("llama3.1:8b", hw_profile=self._hw_profile)  # Model will be refined in step 14
            self.log("  Pre-flight completed – config is now valid", "SUCCESS")

            gw_ok = self.setup_gateway()

            # ══════════════════════════════════════════════════════════
            # Steps 12–16
            # ══════════════════════════════════════════════════════════

            # ── 12: WSL2 ───────────────────────────────────────────────
            self._set_status("Step 12/16: Checking WSL2 + Ubuntu...")
            self.log("\n🐧 STEP 12/16: Checking WSL2 + Ubuntu")
            self.progress["value"] = 92
            wsl_installed, ubuntu_installed = self.check_wsl()
            if wsl_installed and ubuntu_installed:
                self.log("WSL2 + Ubuntu already present", "SUCCESS")
            elif wsl_installed:
                self.log("WSL2 present, Ubuntu missing – installing Ubuntu distribution...")
                self.log("  (Windows Modules Installer may still be working – please wait)", "WARNING")
                if self.install_wsl():
                    self.log("Ubuntu installed", "SUCCESS")
                else:
                    self.log("Ubuntu installation failed – after restart: wsl --install -d Ubuntu",
                             "WARNING")
            else:
                self.log("WSL2 not found – installing WSL2 + Ubuntu...")
                if self.install_wsl():
                    self.log("WSL2 + Ubuntu installed", "SUCCESS")
                else:
                    self.log("WSL2 could not be installed – restart may be needed",
                             "WARNING")
                    self.log("  After restart: wsl --install --distribution Ubuntu", "WARNING")

            # ── 13: Ollama (WSL-only) ──────────────────────────────────
            self._set_status("Step 13/16: Installing + starting Ollama in WSL2...")
            self.log("\n🦙 STEP 13/16: Checking / installing + starting Ollama (WSL2)")
            self.log("  POLICY: Ollama runs exclusively in WSL2 (performance + space)")
            self.progress["value"] = 93
            wsl_now, ubuntu_now = self.check_wsl()

            # Docker warning: Docker Desktop uses WSL2 RAM that Ollama needs
            if self._is_docker_running():
                self.log("  ⚠️  Docker Desktop is running!", "WARNING")
                self.log("  Docker reserves WSL2 RAM → less available for Ollama models", "WARNING")
                self.log("  Recommendation: Close Docker Desktop while LLM chat is running", "WARNING")

            if not (wsl_now and ubuntu_now):
                self.log("  WSL2/Ubuntu not available!", "WARNING")
                self.log("  Restart required, then restart setup", "WARNING")
                self.log("  After restart: wsl --install -d Ubuntu", "WARNING")
            elif self.check_ollama_wsl():
                self.log("  Ollama in WSL2 present ✓", "SUCCESS")
            else:
                self.log("  Ollama not in WSL – installing...")
                if not self.install_ollama_wsl():
                    self.log("  Ollama WSL installation failed!", "ERROR")
                    self.log("    Manual: wsl bash -lc 'curl -fsSL https://ollama.com/install.sh | sh'",
                             "WARNING")

            # Set up autostart
            self.setup_ollama_autostart()

            # Start Ollama – with 3 attempts and actual API verification
            ollama_ok = self.start_ollama_serve()

            if not ollama_ok:
                self.log("  Trying WSL restart as last resort...", "WARNING")
                self.run_powershell("wsl --shutdown 2>$null; Start-Sleep 5")
                time.sleep(6)
                ollama_ok = self.start_ollama_serve()

            if ollama_ok:
                # Wait until API responds stably
                self.wait_for_ollama(max_wait=20)
                # Display model list
                try:
                    import urllib.request as _ur, json as _j
                    resp = _ur.urlopen("http://127.0.0.1:11434/api/tags", timeout=5)
                    tags = _j.loads(resp.read())
                    models_loaded = [m["name"] for m in tags.get("models", [])]
                    self.log(f"  Ollama running ✓  Available models: {models_loaded or '(none yet)'}", "SUCCESS")
                except Exception:
                    self.log("  Ollama API responds ✓", "SUCCESS")
            else:
                self.log("  ⚠️  OLLAMA IS NOT RUNNING – chat will fail!", "ERROR")
                self.log("  Start manually: wsl bash -lc 'OLLAMA_HOST=0.0.0.0 ollama serve &'", "ERROR")

            # ── 14: Load LLM models ──────────────────────────────────
            self._set_status("Step 14/16: Loading LLM models (LYRA)...")
            self.log("\n🌀 STEP 14/16: Loading LLM models for LYRA")
            self.log("  (This may take 10–60 minutes depending on internet speed)")
            self.progress["value"] = 94
            pulled_models = self.pull_lyra_models()
            # pulled_models is now (list, cpu_primary) tuple
            if isinstance(pulled_models, tuple):
                pulled_list, cpu_primary = pulled_models
            else:
                pulled_list, cpu_primary = pulled_models, "qwen2.5:1.5b"
            primary_model = cpu_primary if cpu_primary else (pulled_list[0] if pulled_list else "qwen2.5:1.5b")
            # v1.0.3: if HardwareProfile recommends a different model and nothing
            # was explicitly pulled, prefer the HW recommendation over the hardcoded fallback.
            if not cpu_primary and not pulled_list and self._hw_profile:
                primary_model = self._hw_profile.get("recommended_model", primary_model)
                self.log(f"  Primary model (from HW profile): {primary_model}", "SUCCESS")
            else:
                self.log(f"  Primary model (CPU-optimized): {primary_model}", "SUCCESS")

            # Check Ollama state after model pull
            # (Model pull can sometimes destabilize Ollama)
            if not self._ollama_api_reachable():
                self.log("  Ollama not reachable after model pull – restarting...", "WARNING")
                self.start_ollama_serve()
                self.wait_for_ollama(max_wait=20)
            else:
                self.log("  Ollama API stable after model pull ✓", "SUCCESS")

            # ── 15: Configure OpenClaw / LYRA ─────────────────────
            self._set_status("Step 15/16: Configuring OpenClaw for LYRA...")
            self.log("\n⚙️  STEP 15/16: Writing OpenClaw configuration for LYRA")
            self.progress["value"] = 97
            oc = self.get_openclaw_cmd()

            # v10: Write valid config (rebuild, no merge → no systemPrompt leak)
            cfg_ok, cfg_path = self.cfg.write_openclaw_config(primary_model, hw_profile=self._hw_profile)

            # Run doctor --fix to remove any legacy remnants
            self.log("  openclaw doctor --fix...")
            r_fix = self._run_with_yes_input(
                f"{oc} doctor --fix 2>&1", timeout=30, prefix="    "
            )
            fix_out = (r_fix["stdout"] + r_fix.get("stderr", "")).lower()

            # IMPORTANT: doctor --fix resets auth.mode back to "token" and removes our model!
            # Therefore write AGAIN after doctor --fix:
            if "doctor complete" in fix_out or "changes" in fix_out:
                self.log("  doctor --fix changed config – writing again...", "INFO")
                self.cfg.write_openclaw_config(primary_model, hw_profile=self._hw_profile)
                self.log("  Config restored after doctor fix ✓", "SUCCESS")

            # Check if config is now clean
            if "invalid config" in fix_out and "systemprompt" in fix_out:
                self.log("  systemPrompt still in config – force-removing...", "ERROR")
                # Last resort: remove directly from JSON
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    raw.get("agents", {}).get("defaults", {}).pop("systemPrompt", None)
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(raw, f, indent=2)
                    self.log("  systemPrompt force-removed ✓", "SUCCESS")
                except Exception as e:
                    self.log(f"  Force-remove failed: {e}", "ERROR")

            # Set LLM + auth-profiles via helper method
            # MOST IMPORTANT LINE: openclaw configure is the ONLY way
            # to correctly register OLLAMA_API_KEY in OpenClaw
            self.cfg.run_openclaw_configure(primary_model)

            self.cfg.configure_ollama_via_cli(primary_model)

            # Cleanly stop gateway + restore original task + restart
            self.log("  Stopping gateway for clean restart...")
            self.run_powershell(
                'schtasks /End /TN "OpenClaw Gateway" 2>$null', timeout=15
            )
            self.run_powershell(
                "Get-WmiObject Win32_Process"
                " | Where-Object { $_.Name -eq 'node.exe'"
                "   -and $_.CommandLine -like '*openclaw*' }"
                " | ForEach-Object { Stop-Process -Id $_.ProcessId -Force"
                "   -ErrorAction SilentlyContinue }",
                timeout=15
            )
            time.sleep(3)

            # IMPORTANT: Reset gateway task to original
            # Earlier wrapper changes can break the task.
            # openclaw gateway install --force restores the original task.
            self.log("  Restoring original gateway task...")
            self._run_with_yes_input(
                f"{oc} gateway install --force 2>&1", timeout=30, prefix="    "
            )
            time.sleep(2)

            # CRITICAL FIX: Patch gateway.cmd – set OLLAMA_API_KEY ENV before start
            # OpenClaw reads the key from process ENV, not Windows ENV
            self.cfg.patch_gateway_cmd()

            self.log("  Starting gateway with valid configuration...")
            r_start = self._run_with_yes_input(
                f"{oc} gateway start 2>&1", timeout=30, prefix="    "
            )
            time.sleep(15)   # Node.js gateway start takes ~8-10s

            # CRITICAL: Gateway overwrites auth-profiles.json on startup with vllm:default!
            # Therefore write again AFTER gateway start with correct Ollama profile.
            # Format learned from DIAG output: version=1, profiles as object keyed by "provider:id"
            # According to error message: OLLAMA_API_KEY must be set (any value is enough)
            auth_p = os.path.join(self.cfg._find_openclaw_config_dir(),
                                  "agents", "main", "agent", "auth-profiles.json")
            ollama_auth = {
                "version": 1,
                "profiles": {
                    "ollama:default": {
                        "type":     "api_key",
                        "provider": "ollama",
                        "key":      "ollama-local",   # Any value – Ollama doesn't check it
                        "baseURL":  "http://127.0.0.1:11434/v1",
                        "model":    f"ollama/{primary_model}",
                    }
                }
            }
            try:
                os.makedirs(os.path.dirname(auth_p), exist_ok=True)
                with open(auth_p, "w", encoding="utf-8") as f:
                    json.dump(ollama_auth, f, indent=2)
                self.log(f"  auth-profiles.json: ollama:default / key=ollama-local  ✓", "SUCCESS")
            except Exception as e:
                self.log(f"  auth-profiles.json post-start write: {e}", "WARNING")

            # OLLAMA_API_KEY + OPENCLAW_GATEWAY_TOKEN as Windows ENV (User + Machine)
            # OPENCLAW_GATEWAY_TOKEN: Chrome extension relay needs this token
            # even with auth.mode=none → prevents code=4008 "connect failed"
            for scope in ["User", "Machine"]:
                self.run_powershell(
                    f'[System.Environment]::SetEnvironmentVariable("OLLAMA_API_KEY",'
                    f' "ollama-local", "{scope}")'
                )
                self.run_powershell(
                    f'[System.Environment]::SetEnvironmentVariable("OPENCLAW_GATEWAY_TOKEN",'
                    f' "lyra-local-token", "{scope}")'
                )
            os.environ["OLLAMA_API_KEY"] = "ollama-local"
            os.environ["OPENCLAW_GATEWAY_TOKEN"] = "lyra-local-token"
            self.log("  OLLAMA_API_KEY = ollama-local (User + Machine ENV)  ✓", "SUCCESS")
            self.log("  OPENCLAW_GATEWAY_TOKEN = lyra-local-token (User + Machine ENV)  ✓",
                     "SUCCESS")

            # Port check + log diagnostics
            gw_port = self.run_powershell(
                "Test-NetConnection -ComputerName 127.0.0.1 -Port 18789"
                " -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null"
            )
            start_out = (r_start["stdout"] + r_start.get("stderr", "")).lower()
            if "True" in gw_port.get("stdout", ""):
                self.log("  Gateway running after LYRA configuration!", "SUCCESS")
            elif "invalid config" in start_out or "config invalid" in start_out:
                self.log("  Config still has invalid keys – reading log:", "ERROR")
                self.cfg.read_gateway_log()
                self.log("  Showing current config:", "WARNING")
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg_txt = json.dumps(json.load(f), indent=2)
                    self.log(cfg_txt[:800])
                except:
                    pass
            else:
                self.log("  Gateway not yet reachable – waiting...", "WARNING")
                time.sleep(8)
                gw_port2 = self.run_powershell(
                    "Test-NetConnection -ComputerName 127.0.0.1 -Port 18789"
                    " -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null"
                )
                if "True" in gw_port2.get("stdout", ""):
                    self.log("  Gateway running (delayed)", "SUCCESS")
                else:
                    self.cfg.read_gateway_log()

            # ── 16: LYRA agent + test ──────────────────────────────────
            self._set_status("Step 16/16: Setting up LYRA agent + test...")
            self.log("\n🌟 STEP 16/16: Creating LYRA agent + sending test prompt")
            self.progress["value"] = 99
            lyra_ok = self.cfg.setup_lyra_agent(primary_model)

            # ── COMPLETION ──────────────────────────────────────────────
            self.progress["value"] = 100
            self._set_status("Complete! LYRA is alive!")

            self.log("\n" + "=" * 70)
            if gw_ok and lyra_ok:
                self.log("INSTALLATION COMPLETELY SUCCESSFUL! LYRA IS ALIVE!", "SUCCESS")
                self.log("=" * 70)
                self.log(f"Primary model   : {primary_model}")
                self.log("Dashboard        : http://localhost:18789")
                self.log("Ollama API       : http://localhost:11434")
            elif gw_ok:
                self.log("OPENCLAW + GATEWAY INSTALLED! LYRA CONFIGURED!", "SUCCESS")
                self.log("=" * 70)
                self.log(f"Primary model   : {primary_model}")
                self.log("Dashboard        : http://localhost:18789")
                if not pulled_list:
                    self.log("  Pull model manually:")
                    self.log(f"    wsl bash -lc 'ollama pull {primary_model}'")
            else:
                self.log("OPENCLAW INSTALLED – Gateway restart needed!", "WARNING")
                self.log("=" * 70)
                self.log("Run as administrator:")
                self.log("  openclaw gateway start")
                self.log(f"  openclaw config set agents.defaults.model ollama:{primary_model}")
                self.log("  openclaw config set agents.defaults.ollamaHost http://127.0.0.1:11434")

            self.log("")
            self.log("LYRA has full control!", "SUCCESS")
            self.log(f"Role: LYRA (head)  |  Model: {primary_model}", "SUCCESS")
            self.log("🌀 Role successfully set: Lyra", "SUCCESS")
            self.log("Start with: 'Analyze a DNA sequence' in the dashboard", "SUCCESS")
            self.log("Or:        'Which pattern underlies all patterns?'")

            # ── LYRA head: Start task server ────────────────────────
            self.log("\n🌐 Starting LYRA task server (port 18790)...")
            head_server = LyraHeadServer(port=LYRA_HEAD_PORT, log_fn=self.log)
            if head_server.start():
                self._head_server = head_server   # Keep reference
                self.log(f"  Task server running on port {LYRA_HEAD_PORT} with /result endpoint ✓", "SUCCESS")
                # Demo task with SearXNG query (uses the actual search path)
                demo_id = head_server.add_task(
                    "web_search",
                    {"query": "Weather Zurich current"}
                )
                self.log(f"  Demo task set: {demo_id} (web_search → SearXNG Weather Zurich)", "INFO")
            else:
                self.log(f"  Task server start failed "
                         f"(port {LYRA_HEAD_PORT} occupied?)", "WARNING")

            # ── SearXNG check on head ─────────────────────────────────
            # (soul_path + force_path for final log)
            _cfg = self.cfg._find_openclaw_config_dir()
            soul_path  = os.path.join(_cfg, "workspace", "SOUL.md")
            force_path = os.path.join(_cfg, "workspace", "FORCE-DELEGATE.md")
            self.log("\n🔍 SearXNG check on LYRA head...")
            searxng_ok = False
            try:
                sx_req = urllib.request.Request(
                    "http://127.0.0.1:8080/search?q=test&format=json",
                    headers={"User-Agent": "LyraInstaller/38.2",
                             "Accept": "application/json"})
                with urllib.request.urlopen(sx_req, timeout=6) as r:
                    sx_data = json.loads(r.read(4096).decode("utf-8"))
                if "results" in sx_data or "query" in sx_data:
                    searxng_ok = True
                    self.log("  SearXNG running on port 8080 ✓", "SUCCESS")
                    self.log("  LYRA uses SearXNG as fallback when no worker is available", "SUCCESS")
            except Exception as sx_err:
                self.log(f"  SearXNG not reachable: {sx_err}", "WARNING")
                self.log("  Start SearXNG: docker run -d -p 8080:8080 searxng/searxng",
                         "WARNING")
                self.log("  LYRA delegates web_search to workers (who use their own SearXNG)",
                         "INFO")

            # Get token for dashboard URL (read from config, not from local scope)
            gw_token = self.cfg._read_token_from_config() or "lyra-local-token"

            # Get local IP for worker connection instructions
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                local_ip = "127.0.0.1"

            dashboard_url = f"http://127.0.0.1:18789/?token={gw_token}"

            # ── Final dashboard box ──────────────────────────────────
            self.log("\n" + "╔" + "═" * 62 + "╗")
            self.log(  "║" + "           LYRA SYSTEM READY – HEAD ACTIVE             ".center(62) + "║")
            self.log(  "╚" + "═" * 62 + "╝")
            self.log(f"  Role:       LYRA (head)")
            self.log(f"  Dashboard:   {dashboard_url}")
            self.log(f"  Ollama API:  http://localhost:11434")
            self.log(f"  Task server: http://{local_ip}:{LYRA_HEAD_PORT}")
            self.log(f"  SearXNG:     {'✓ http://127.0.0.1:8080' if searxng_ok else '✗ not started (docker run -d -p 8080:8080 searxng/searxng)'}")
            self.log(f"  Model:      {primary_model}")
            self.log(f"  Token:       {gw_token}")
            self.log(f"")
            self.log(f"  ⚠️  ALWAYS open browser with ?token=...!")
            self.log(f"  auth.mode=token → direct call without token → 4008 error")
            self.log(f"")
            self.log(f"  Worker machines connect:")
            self.log(f"    → Run installer on worker")
            self.log(f"    → Choose role: Senior or Junior")
            self.log(f"    → Enter LYRA head IP: {local_ip}")
            self.log(f"")
            self.log(f"  ─── TEST SCENARIO: Delegation  ───────────────────")
            self.log(f"  1. Browser: {dashboard_url}")
            self.log(f"  2. In chat write: 'What's the weather in Zurich?'")
            self.log(f"  3. LYRA calls delegate_to_worker:")
            self.log(f"     task_type='web_search', payload={{'query':'Weather Zurich current'}}")
            self.log(f"  4. Worker: wttr.in → Summary → head integrates result")
            self.log(f"")
            self.log(f"  ✅ Expected behavior:")
            self.log(f"     LYRA NEVER says 'Brave Search API key'")
            self.log(f"     LYRA calls delegate_to_worker IMMEDIATELY")
            self.log(f"     Worker log: '[DELEGATION] Weather query → wttr.in'")
            self.log(f"     Head log:   '[HeadSrv] Result received: ... (success)'")
            self.log(f"")
            self.log(f"  ❌ If LYRA still asks for Brave:")
            self.log(f"     → Check SOUL.md: {soul_path}")
            self.log(f"     → Restart gateway: openclaw gateway start")
            self.log(f"     → Then restart installer (SOUL.md will be written again)")
            self.log(f"")
            self.log(f"  Check task queue (PowerShell):")
            self.log(f'    Invoke-RestMethod "http://localhost:{LYRA_HEAD_PORT}/tasks"')
            self.log(f'    Invoke-RestMethod "http://localhost:{LYRA_HEAD_PORT}/results"')
            self.log(f"  SOUL.md:         {soul_path}")
            self.log(f"  FORCE-DELEGATE:  {force_path}")
            self.log(f"  Tool doc:        C:\\Users\\$env:USERNAME\\.openclaw\\lyra_tools_config.json")
            self.log("=" * 70)

            self.root.after(1000, self.ask_open_dashboard)

        except Exception as e:
            import traceback
            self.log(f"UNEXPECTED ERROR: {e}", "ERROR")
            self.log(traceback.format_exc(), "DEBUG")
        finally:
            self.installation_running = False
            self._set_status("")
            self.main_button.config(
                state="normal",
                text="🚀 TEST SYSTEM & INSTALL OPENCLAW + LYRA"
            )

    def _start_head_server(self):
        """Starts the LYRA task server manually (e.g., after gateway start)."""
        if not hasattr(self, "_head_server") or self._head_server is None:
            self._head_server = LyraHeadServer(port=LYRA_HEAD_PORT, log_fn=self.log)
        return self._head_server.start()

    def _start_worker_loop_legacy(self, head_address: str, role: str, model: str):
        """Legacy: starts a plain LyraWorkerClient (no queue). Kept for reference."""
        w = LyraWorkerClient(head_address, role, model, log_fn=self.log)
        w.start()
        self._worker_client = w
        return w

    def ask_open_dashboard(self):
        token = self.cfg._read_token_from_config() or "lyra-local-token"
        dashboard_url = f"http://127.0.0.1:18789/?token={token}"
        msg = (
            "✅ LYRA HAS FULL CONTROL!\n\n"
            "OpenClaw + LYRA are installed and configured.\n\n"
            f"📊 Dashboard: {dashboard_url}\n"
            "🦙 Ollama API: http://localhost:11434\n\n"
            "Start LYRA with:\n"
            "  'Analyze a DNA sequence'\n"
            "  'Which pattern underlies all patterns?'\n\n"
            f"⚠️  Use token URL:\n  {dashboard_url}\n\n"
            "Open dashboard now?"
        )
        if messagebox.askyesno("LYRA is alive! 🌀", msg):
            import webbrowser
            webbrowser.open(dashboard_url)
            self.log(f"Dashboard opened: {dashboard_url}", "SUCCESS")


def main():
    root = tk.Tk()
    OpenClawWinInstaller(root)
    root.mainloop()


if __name__ == "__main__":
    main()
