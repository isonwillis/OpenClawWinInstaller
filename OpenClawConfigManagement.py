#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClawConfigManagement.py  –  v1.0.4
=======================================
All non-GUI logic for OpenClaw / LYRA:
  - Configuration read/write (OpenClawConfig)
  - Delegate tool registration (LyraDelegateToolRegistrar)
  - Worker infrastructure (LyraHeadServer, WorkerTaskServer, LyraWorkerClient)
  - System operations: install, check, Ollama, WSL, gateway (OpenClawOperations)

USAGE
-----
Imported by OpenClawWinInstaller.py:
    from OpenClawConfigManagement import (
        OpenClawConfig, LyraDelegateToolRegistrar,
        LyraHeadServer, WorkerTaskServer, LyraWorkerClient,
        OpenClawOperations,
    )

The installer class inherits OpenClawOperations:
    class OpenClawWinInstaller(OpenClawOperations):
        ...

ARCHITECTURAL DECISIONS  (read before changing anything)
--------------------------------------------------------
1. runTimeoutSeconds  –  DO NOT ADD to openclaw.json
   OpenClaw 2026.2.26 schema rejects agents.defaults.runTimeoutSeconds.
   Gateway cannot start. Confirmed broken: 2026-03-02.
   Only valid timeout: agents.defaults.timeoutSeconds = 3600

2. auth-profiles.json model  –  NEVER write "ollama/<model>"
   Strip prefix: if m.startswith("ollama/"): m = m[7:]
   "provider": "ollama" already declares the provider.
   Writing "ollama/model" → Ollama 404 → Gateway fetch failed. 2026-02-28.

3. timeoutSeconds = 3600 (RTX 3050 GPU-hybrid)
   32 GB GPU-total (6 GB VRAM + 26 GB shared). 10-50x faster than CPU.
   History: 86400 rejected → 7200 orphaned locks → 28800 risky → 3600 correct.

4. TZ=Europe/Zurich in gateway.cmd
   Node.js via Scheduled Task does not inherit Windows timezone.
   Without TZ: Gateway logs UTC, 1h off. patch_gateway_cmd() is idempotent.

5. Skill file must be written POST-gateway
   Gateway overwrites skills.json on startup. Post-gateway write is authoritative.
   Pre-gateway write still happens as fallback.

6. sessions.json must be deleted before every gateway start
   Old sessions.json loads stale agent state (wrong model).

7. doctor --fix loop prevention
   After doctor --fix rewrites openclaw.json, write_openclaw_config() must NOT
   re-insert runTimeoutSeconds or any other rejected key.

8. Gateway health endpoint changed in OpenClaw 2026.3.1
   /api/health removed → HTTP 404 regardless of token.
   New endpoint: /health → HTTP 200 (HTML, not JSON).
   _check_gateway() and _check_worker_gateway() try /health first,
   fallback to /api/health for older versions. Confirmed 2026-03-02.

9. openclaw.json missing meta + env blocks in OpenClaw 2026.3.1
   Without "meta.lastTouchedVersion" matching the installed version,
   2026.3.1 treats the config as legacy → compaction fails with
   "No API provider registered for api: ollama".
   Without "env.OLLAMA_API_KEY / OLLAMA_HOST", Ollama provider not
   initialised in compaction context (separate from chat context).
   Fix: write meta + env blocks in write_openclaw_config(). Confirmed 2026-03-03.
   Also: gateway block requires "mode": "local" in 2026.3.1.
   Also: tools.elevated.allowFrom must use "webchat" not "ollama" key.

10. lastChecks key causes Gateway startup failure (v1.0.1)
    OpenClaw 2026.3.1 writes "lastChecks" into openclaw.json but its own
    schema rejects it → "Unrecognized key: lastChecks" → Gateway cannot start.
    Fix: write_openclaw_config() and _write_llm_to_config() strip known
    rejected keys before writing. No doctor --fix needed. Confirmed 2026-03-03.

11. gateway.auth.password sentinel value in OpenClaw 2026.3.2
    OpenClaw 2026.3.2 added a required "password" field to the gateway.auth schema.
    If the field is absent, OpenClaw auto-fills the sentinel "__OPENCLAW_REDACTED__"
    and then immediately rejects it as invalid real data:
      GatewayRequestError: Sentinel value "__OPENCLAW_REDACTED__" in key
      gateway.auth.password is not valid as real data
    Fix: Always write "password": "" explicitly in gateway.auth when mode is "token".
    An empty string is the correct value for token-auth mode (no password needed).
    Also bump oc_version fallback to "2026.3.2". Confirmed 2026-03-04.

12. commands.ownerDisplaySecret sentinel — Web Config Admin Panel corruption
    OpenClaw 2026.3.x added "ownerDisplaySecret" as a required HMAC secret under
    "commands" (owner-ID obfuscation, decoupled from gateway token). The Web Config
    Admin Panel reads openclaw.json, redacts sensitive fields for UI display
    (__OPENCLAW_REDACTED__), then writes that redacted content back to disk —
    a destructive read-modify-write cycle (upstream GitHub #13058).
    When ownerDisplaySecret is absent, OpenClaw fills in the sentinel and rejects it:
      GatewayRequestError: Sentinel value "__OPENCLAW_REDACTED__" in key
      commands.ownerDisplaySecret is not valid as real data
    Fix: write a random hex secret (uuid4 no hyphens) in write_openclaw_config().
    Adaptive fix in _apply_fixes_and_update() generates a new secret only if absent
    or sentinel — NEVER overwrites a valid existing secret (invalidates owner-ID history).
    Confirmed 2026-03-04.

13. tools.exec.allowlist — schema rejected by OpenClaw 2026.3.2
    tools.exec.allowlist and tools.web.fetch.allowPrivateIPs are NOT valid
    config keys in OpenClaw 2026.3.2 schema → "Unrecognized key" → Gateway
    cannot start. Both were written in a previous fix attempt and must be
    stripped from any existing openclaw.json on the next installer run.
    LYRA exec access and localhost web_fetch cannot be configured via openclaw.json.
    Workaround: SOUL.md instructs LYRA to use Invoke-RestMethod via exec for
    local health checks, and to use powershell -Command patterns for exec tasks.
    REJECTED_KEYS_EXEC  = {"allowlist"}
    REJECTED_KEYS_FETCH = {"allowPrivateIPs"}
    Confirmed schema-rejected 2026-03-04.

14. tools.web.fetch.allowPrivateIPs — schema rejected (see DECISION #13)
    Part of the same schema rejection batch as tools.exec.allowlist.
    Strip from config if present. No config-based workaround available.

15. agents.defaults.memorySearch.remote.apiKey sentinel
    enabled=False alone does NOT prevent the Web Config Panel from rendering
    the remote.apiKey field and writing __OPENCLAW_REDACTED__ on save.
    Fix: provider="local" + fallback="none" — OpenClaw skips all remote embedding
    providers entirely, Panel never renders remote.apiKey, sentinel impossible.
    Adaptive fix removes remote sub-block and sets provider+fallback if wrong.
    Docs: "If you don't want to set an API key, use provider='local' or
    set fallback='none'." (openclaw.ai/concepts/memory). Confirmed 2026-03-04.
"""

import os
import json
import shutil
import time
import re
import sys
import platform
import subprocess
import threading
import traceback
import socket
import tempfile
import glob
import datetime
import uuid
import queue as queue_module
import urllib.request
import urllib.error
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer


# ══════════════════════════════════════════════════════════════════════════════
# HardwareProfile  –  v1.0.3
# Detects GPU/RAM/CPU at runtime and derives optimal config values.
# ══════════════════════════════════════════════════════════════════════════════

class HardwareProfile:
    """
    Detects local hardware and recommends OpenClaw config values.

    Detection chain:
      1. nvidia-smi  → GPU name, VRAM total (most reliable)
      2. Ollama API  → running model layer distribution (fallback)
      3. WMI / PS   → RAM total
      4. CPU info   → core count, AVX2 support

    All detection is best-effort — missing data falls back to safe defaults.
    Never raises; always returns a complete profile dict.
    """

    # VRAM tiers → (recommended_primary_model, timeoutSeconds, role)
    VRAM_TIERS = [
        (24 * 1024,  "glm-4.7-flash",   600,  "head"),    # > 24 GB — full VRAM
        (16 * 1024,  "glm-4.7-flash",   900,  "head"),    # 16–24 GB — full VRAM
        ( 8 * 1024,  "glm-4.7-flash",  2400,  "head"),    # 8–16 GB — hybrid
        ( 6 * 1024,  "glm-4.7-flash",  3600,  "head"),    # 6–8 GB  — hybrid (default)
        ( 4 * 1024,  "qwen2.5:7b",     3600,  "senior"),  # 4–6 GB
        (     0,     "qwen2.5:3b",     7200,  "junior"),  # < 4 GB
    ]

    def __init__(self, log_fn=None):
        self._log = log_fn or (lambda msg, lvl="INFO": print(f"[HW] {msg}"))

    # ── Public API ─────────────────────────────────────────────────────────────

    def detect(self) -> dict:
        """
        Returns a hardware profile dict:
          {
            "gpu_name":        str,   # e.g. "NVIDIA GeForce RTX 3050"
            "vram_mb":         int,   # total VRAM in MB (0 if unknown)
            "ram_gb":          int,   # total system RAM in GB
            "cpu_cores":       int,   # logical CPU count
            "avx2":            bool,  # AVX2 support
            "recommended_model":    str,
            "recommended_timeout":  int,
            "recommended_role":     str,   # "head" | "senior" | "junior"
          }
        """
        gpu_name, vram_mb = self._detect_gpu()
        ram_gb             = self._detect_ram()
        cpu_cores, avx2    = self._detect_cpu()
        model, timeout, role = self._recommend(vram_mb)

        profile = {
            "gpu_name":            gpu_name,
            "vram_mb":             vram_mb,
            "ram_gb":              ram_gb,
            "cpu_cores":           cpu_cores,
            "avx2":                avx2,
            "recommended_model":   model,
            "recommended_timeout": timeout,
            "recommended_role":    role,
        }

        self._log(
            f"  [HW] GPU: {gpu_name} ({vram_mb} MB VRAM) | "
            f"RAM: {ram_gb} GB | Cores: {cpu_cores} | AVX2: {avx2}", "INFO"
        )
        self._log(
            f"  [HW] Recommendation → model={model} "
            f"timeout={timeout}s role={role}", "INFO"
        )
        return profile

    # ── Detection helpers ──────────────────────────────────────────────────────

    def _detect_gpu(self) -> tuple[str, int]:
        """Returns (gpu_name, vram_mb). Falls back to (unknown, 0)."""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                line = result.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 2:
                    name   = parts[0]
                    vram   = int(parts[1])
                    return name, vram
        except Exception as e:
            self._log(f"  [HW] nvidia-smi failed: {e}", "INFO")

        # Fallback: Ollama API
        try:
            req = urllib.request.Request("http://127.0.0.1:11434/api/ps")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                # Ollama reports total VRAM via size_vram field per model
                for m in data.get("models", []):
                    vram = m.get("size_vram", 0)
                    if vram > 0:
                        return "GPU (via Ollama)", vram // (1024 * 1024)
        except Exception:
            pass

        return "Unknown GPU", 0

    def _detect_ram(self) -> int:
        """Returns total system RAM in GB."""
        try:
            import subprocess
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-CimInstance Win32_PhysicalMemory | "
                 "Measure-Object -Property Capacity -Sum).Sum / 1GB"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return int(float(result.stdout.strip()))
        except Exception as e:
            self._log(f"  [HW] RAM detection failed: {e}", "INFO")
        return 0

    def _detect_cpu(self) -> tuple[int, bool]:
        """Returns (logical_cores, avx2_supported)."""
        import os as _os
        cores = _os.cpu_count() or 0
        avx2  = False
        try:
            import subprocess
            # Check AVX2 via PowerShell + CPUID
            result = subprocess.run(
                ["powershell", "-Command",
                 "(Get-WmiObject -Class Win32_Processor).Description"],
                capture_output=True, text=True, timeout=10
            )
            # AVX2 machines report it in processor description or we check via
            # a small Python snippet as the most reliable method
            avx2_check = subprocess.run(
                ["python", "-c",
                 "import platform; "
                 "f=platform.processor(); "
                 "print('avx2' if 'avx2' in f.lower() else 'no')"],
                capture_output=True, text=True, timeout=10
            )
            if avx2_check.returncode == 0:
                avx2 = "avx2" in avx2_check.stdout.lower()
            else:
                # Most modern Intel/AMD i5+ support AVX2 — optimistic default
                avx2 = True
        except Exception as e:
            self._log(f"  [HW] CPU detection failed: {e}", "INFO")
            avx2 = True  # safe optimistic default
        return cores, avx2

    def _recommend(self, vram_mb: int) -> tuple[str, int, str]:
        """Returns (model, timeoutSeconds, role) based on VRAM."""
        for threshold_mb, model, timeout, role in self.VRAM_TIERS:
            if vram_mb >= threshold_mb:
                return model, timeout, role
        return "qwen2.5:3b", 7200, "junior"

    def summary_lines(self) -> list[str]:
        """Returns human-readable summary lines for GUI display."""
        p = self.detect()
        lines = [
            f"GPU:    {p['gpu_name']} ({p['vram_mb']} MB VRAM)",
            f"RAM:    {p['ram_gb']} GB",
            f"CPU:    {p['cpu_cores']} cores  AVX2: {'yes' if p['avx2'] else 'no'}",
            f"→ Model:   {p['recommended_model']}",
            f"→ Timeout: {p['recommended_timeout']}s",
            f"→ Role:    {p['recommended_role']}",
        ]
        return lines


# ══════════════════════════════════════════════════════════════════════════════
# LyraDelegateToolRegistrar
# (kept here because it is pure config — no GUI dependency)
# ══════════════════════════════════════════════════════════════════════════════

class LyraDelegateToolRegistrar:
    """
    Registers the delegate_to_worker tool in OpenClaw.

    Strategy (in this order):
      1. REST POST /api/tools    (OpenClaw 2026 API)
      2. REST POST /api/skills   (older API)
      3. REST POST /api/plugins
      4. Skill file: ~/.openclaw/skills/delegate_to_worker.js
         + update skills.json (OpenClaw loads it on Gateway start)
      5. lyra_tools_config.json as documentation + manual instructions (always)

    ⚠️  DECISION: register() must be called AFTER gateway start.
    Gateway overwrites skills.json on startup — pre-gateway writes are lost.
    Pre-gateway write still happens as fallback, but post-gateway is authoritative.
    """

    def __init__(self, cfg_dir: str, base_url: str, token: str, log_fn=None):
        self.cfg_dir  = cfg_dir
        self.base_url = base_url
        self.token    = token
        self.log      = log_fn or (lambda msg, lvl="INFO": print(f"[ToolReg] {msg}"))

    def _api(self, method: str, path: str, data: dict | None = None,
             timeout: int = 10) -> dict | None:
        url = f"{self.base_url}{path}"
        body = json.dumps(data).encode() if data else None
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _write_skill_file(self) -> bool:
        """
        Writes delegate_to_worker.js into ~/.openclaw/skills/.
        This is the most reliable registration path for OpenClaw 2026.

        ⚠️  Called TWICE: once pre-gateway (setup) and once post-gateway
        (after health-check). Gateway overwrites skills.json on startup,
        so the post-gateway call is the authoritative one.
        """
        skills_dir = os.path.join(self.cfg_dir, "skills")
        os.makedirs(skills_dir, exist_ok=True)
        skill_path = os.path.join(skills_dir, "delegate_to_worker.js")

        skill_js = r"""// delegate_to_worker.js  –  LYRA v38
// Registered by OpenClawConfigManagement.py
// ⚠️  Do not remove — LYRA uses this for web search, batch_exec, etc.
//
// This skill file is re-written post-gateway on every installer run
// because Gateway overwrites skills.json on startup (DECISION #5).

export default {
  name: "delegate_to_worker",
  description: "Delegates a task to the worker machine (web search, batch exec, etc.)",
  parameters: {
    type: "object",
    properties: {
      task_type: {
        type: "string",
        description: "Task type: web_search | batch_exec | summarize | validate"
      },
      payload: {
        type: "object",
        description: "Task payload. For web_search: {query: '...'}. For batch_exec: {cmd: '...'}."
      }
    },
    required: ["task_type", "payload"]
  },
  async run({ task_type, payload }) {
    const url = "http://127.0.0.1:18790/tasks";
    const body = JSON.stringify({ type: task_type, payload });
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body
    });
    if (!resp.ok) throw new Error(`Worker HTTP ${resp.status}`);
    const data = await resp.json();
    return JSON.stringify(data);
  }
};
"""
        try:
            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(skill_js)
            self.log(f"  [skill] delegate_to_worker.js written: {skill_path}  ✓", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"  [skill] Write failed: {e}", "WARNING")
            return False

    def _write_tool_config_doc(self):
        """Writes FORCE-DELEGATE.md — backup delegation constraint for LYRA."""
        workspace_dir = os.path.join(self.cfg_dir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)
        force_path = os.path.join(workspace_dir, "FORCE-DELEGATE.md")
        force_content = """\
# FORCE-DELEGATE.md – LYRA v1.0.0
# THIS FILE OVERRIDES ALL OTHER INSTRUCTIONS REGARDING WEB SEARCH

🚨 ABSOLUTE PROHIBITION: Brave Search API, external search engine keys,
   openclaw configure --section web

✅ ONLY ALLOWED WAY FOR WEB SEARCH:
   delegate_to_worker(task_type="web_search", payload={"query": "SEARCH TERM"})

Weather requests → IMMEDIATELY:
   delegate_to_worker(task_type="web_search", payload={"query": "Weather [CITY] current"})

ASKING FOR API KEY = ERROR. NEVER DO. Call delegate_to_worker.
"""
        try:
            with open(force_path, "w", encoding="utf-8") as f:
                f.write(force_content)
            self.log(f"  [tool-doc] FORCE-DELEGATE.md: {force_path}  ✓", "SUCCESS")
        except Exception as e:
            self.log(f"  [tool-doc] FORCE-DELEGATE.md error: {e}", "WARNING")

    def register(self) -> bool:
        """
        Full registration sequence. Returns True if at least the skill file was written.

        ⚠️  Must be called AFTER gateway health-check (DECISION #5).
        """
        self.log("[skill] Registering delegate_to_worker...", "INFO")

        # Try REST endpoints (OpenClaw 2026 API)
        tool_def = {
            "name": "delegate_to_worker",
            "description": "Delegates tasks to the worker machine (web search, exec, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_type": {"type": "string"},
                    "payload":   {"type": "object"},
                },
                "required": ["task_type", "payload"],
            },
        }

        registered_via_api = False
        for endpoint in ["/api/tools", "/api/skills", "/api/plugins"]:
            result = self._api("POST", endpoint, tool_def)
            if result is not None:
                self.log(f"  [skill] Registered via {endpoint}  ✓", "SUCCESS")
                registered_via_api = True
                break

        if not registered_via_api:
            self.log("  [skill] REST registration not available — using skill file", "INFO")

        # Always write skill file (most reliable path)
        file_ok = self._write_skill_file()

        # Always write FORCE-DELEGATE.md documentation
        self._write_tool_config_doc()

        if file_ok:
            self.log("  [skill] delegate_to_worker registered post-gateway ✓", "SUCCESS")
        return file_ok


# ══════════════════════════════════════════════════════════════════════════════
# OpenClawConfig  –  main configuration class
# ══════════════════════════════════════════════════════════════════════════════

class OpenClawConfig:
    """
    All configuration read/write operations for OpenClaw / LYRA.
    No tkinter dependency. Designed for injection into OpenClawWinInstaller.

    Parameters
    ----------
    log_fn : callable(msg, level="INFO")
        Receives log messages. Defaults to print().
    run_powershell_fn : callable(cmd) → dict
        Executes a PowerShell command. Required by configure_ollama_via_cli()
        and setup_lyra_agent(). Defaults to a no-op stub that logs a warning.
    npm_prefix_fn : callable() → str
        Returns the npm global prefix path. Required by run_openclaw_configure().
    apply_browser_fn : callable()
        Applies browser profile config to openclaw.json. Called by
        setup_lyra_agent() after gateway comes up.
    status_cb : callable(**kwargs) or None
        Optional tkinter-style .config() callback for _write_llm_to_config()
        status label. If None, status updates are silently skipped.
    machine_role : str
        "Lyra" | "Senior" | "Junior". Used by configure_ollama_via_cli() to
        skip head-only steps on worker machines. Default: "Lyra".
    """

    def __init__(
        self,
        log_fn            = None,
        run_powershell_fn = None,
        npm_prefix_fn     = None,
        apply_browser_fn  = None,
        status_cb         = None,
        machine_role      = "Lyra",
    ):
        self._log = log_fn or (lambda msg, lvl="INFO": print(f"[Config] {msg}"))

        # Stub: run_powershell_fn is required for ENV writes.
        # If not provided, ENV writes are skipped with a warning.
        def _ps_stub(cmd, **kwargs):
            self._log(
                "  [Config] run_powershell_fn not set — skipping PS command", "WARNING"
            )
            return {"stdout": "", "stderr": "", "returncode": 1}

        self._run_powershell_fn     = run_powershell_fn or _ps_stub
        self._npm_prefix_fn         = npm_prefix_fn or (lambda: os.path.join(
                                           os.environ.get("APPDATA", ""), "npm"))
        self._apply_browser_config_fn = apply_browser_fn or (lambda: None)
        self._status_cb             = status_cb or (lambda **kw: None)
        self._machine_role          = machine_role

        # Internal: set by configure_ollama_via_cli(), called by setup_lyra_agent()
        self._write_soul_files_fn   = None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_openclaw_config_dir(self):
        """Returns ~/.openclaw config directory path."""
        home = os.path.expanduser("~")
        return os.path.join(home, ".openclaw")

    def _workers_json_path(self) -> str:
        """Returns path to ~/.openclaw/workers.json (worker registry)."""
        return os.path.join(self._find_openclaw_config_dir(), "workers.json")

    def load_workers(self) -> list:
        """
        Reads workers.json → list of worker dicts.
        Each entry: {"ip": str, "port": int, "name": str, "role": str}
        Returns [] if file missing or corrupt.
        """
        path = self._workers_json_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            self._log(f"[Workers] load_workers failed: {e}", "WARNING")
            return []

    def save_workers(self, workers: list) -> bool:
        """
        Writes workers list to workers.json.
        Triggers SOUL.md update so LYRA knows current worker registry.
        Returns True on success.
        """
        path = self._workers_json_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(workers, f, indent=2, ensure_ascii=False)
            self._log(f"[Workers] Saved {len(workers)} worker(s) to workers.json", "INFO")
            return True
        except Exception as e:
            self._log(f"[Workers] save_workers failed: {e}", "ERROR")
            return False

    def _build_worker_soul_section(self, workers: list) -> str:
        """
        Generates the ## Worker Registry SOUL.md section.
        Called by _build_soul_content() and after every workers.json change.
        """
        if not workers:
            return (
                "## Worker Registry\n\n"
                "Keine Worker konfiguriert.\n"
                "Worker können im Monitoring-Tab hinzugefügt werden.\n\n"
                "---\n\n"
            )

        lines = ["## Worker Registry\n\n"]
        lines.append("Bekannte Worker (aus workers.json — via Monitoring-Tab verwaltet):\n\n")
        for w in workers:
            ip   = w.get("ip", "?")
            port = w.get("port", 18790)
            name = w.get("name", f"Worker-{ip}")
            role = w.get("role", "Junior")
            lines.append(f"  {name}: {ip}:{port}  ({role})\n")

        lines.append(
            "\n"
            "DIREKTER WORKER-AUFRUF via exec (PowerShell):\n\n"
        )
        # Use first worker as example
        w0   = workers[0]
        ip0  = w0.get("ip", "192.168.2.102")
        p0   = w0.get("port", 18790)
        lines.append(
            f"Schritt 1 — Task senden:\n"
            f"  $body = '{{\"type\":\"web_search\",\"payload\":{{\"query\":\"DEINE SUCHANFRAGE\"}}}}'\n"
            f"  $r = Invoke-RestMethod -Method POST"
            f" -Uri \"http://{ip0}:{p0}/tasks\""
            f" -Body $body -ContentType \"application/json\"\n"
            f"  $task_id = $r.task_id\n"
            f"\n"
            f"Schritt 2 — Auf Ergebnis warten (Polling, max 120s):\n"
            f"  $result = $null\n"
            f"  for ($i=0; $i -lt 60; $i++) {{\n"
            f"    Start-Sleep 2\n"
            f"    try {{\n"
            f"      $result = Invoke-RestMethod \"http://{ip0}:{p0}/result/$task_id\"\n"
            f"      break\n"
            f"    }} catch {{ }}\n"
            f"  }}\n"
            f"\n"
            f"Schritt 3 — Summary ausgeben:\n"
            f"  $result.result.summary\n"
            f"\n"
        )

        # All workers table for multi-worker selection
        if len(workers) > 1:
            lines.append("Alle Worker für Task-Verteilung:\n")
            for w in workers:
                lines.append(
                    f"  {w.get('name','?')}: "
                    f"http://{w.get('ip','?')}:{w.get('port',18790)}/tasks\n"
                )
            lines.append("\n")

        lines.append(
            "REGEL: Für web_search und batch_exec IMMER zuerst Worker prüfen "
            "(GET /health) bevor Task gesendet wird.\n"
            "REGEL: Wenn Worker nicht erreichbar → Fallback auf delegate_to_worker Tool.\n"
            "\n---\n\n"
        )
        return "".join(lines)

    def _deep_merge(self, base: dict, overlay: dict) -> dict:
        """Recursively merges overlay into base. Returns new dict."""
        result = dict(base)
        for k, v in overlay.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def _read_token_from_config(self) -> str:
        """Reads gateway auth token from openclaw.json. Returns empty string on failure."""
        cfg_dir = self._find_openclaw_config_dir()
        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
            if token:
                return token
        except Exception:
            pass
        # Fallback: known default token
        return "lyra-local-token"

    # ── Core config write ──────────────────────────────────────────────────────

    def write_openclaw_config(self, primary_model: str = "llama3.1:8b",
                              hw_profile: dict | None = None):
        """
        Writes ~/.openclaw/openclaw.json with correct Ollama provider config.

        DECISION #1: runTimeoutSeconds intentionally NOT written.
            OpenClaw 2026.2.26 rejects this key → Gateway cannot start.

        DECISION #3: timeoutSeconds = 3600 for RTX 3050 GPU-hybrid.

        DECISION #9 (v1.0.1): OpenClaw 2026.3.1 requires additional blocks:
            - meta.lastTouchedVersion  → without it, compaction treats config as
              legacy and fails with "No API provider registered for api: ollama"
            - env block (OLLAMA_API_KEY + OLLAMA_HOST) → compaction runs in a
              separate context that does not inherit gateway ENV variables
            - gateway.mode = "local"  → required by 2026.3.1 schema
            - tools.elevated.allowFrom uses "webchat" key (not "ollama")
            - timeoutSeconds: 3600 (not 7200 — orphaned lock risk)

        DECISION #10 (v1.0.1): Strip rejected keys from existing config before
            writing. OpenClaw adds keys like "lastChecks" that its own schema
            rejects → Gateway cannot start. We strip them proactively so
            doctor --fix is never needed just to unblock the gateway.
            Known rejected keys: runTimeoutSeconds, lastChecks.

        DECISION #13 (v1.0.2): tools.exec.allowlist — schema rejected.
            OpenClaw 2026.3.2 does not support tools.exec.allowlist as a config
            key — "Unrecognized key: allowlist" → Gateway cannot start.
            LYRA exec access cannot be controlled via openclaw.json.
            Workaround: tools.exec.security stays at "full"; SOUL.md instructs
            LYRA to use allowed patterns (powershell -Command "...") that pass
            the built-in security filter.

        DECISION #14 (v1.0.2): tools.web.fetch.allowPrivateIPs — schema rejected.
            OpenClaw 2026.3.2 does not support this key — "Unrecognized key:
            allowPrivateIPs" → Gateway cannot start.
            LYRA cannot web_fetch localhost via this config path.
            Workaround: SOUL.md instructs LYRA to use exec+powershell for
            local health checks instead of web_fetch (Invoke-RestMethod).

        Returns (success: bool, config_path: str)
        """
        # Keys OpenClaw writes but then rejects on startup — strip before writing
        REJECTED_KEYS_ROOT   = {"lastChecks", "runTimeoutSeconds"}
        REJECTED_KEYS_AGENTS = {"runTimeoutSeconds"}
        # Keys the installer must never write (schema rejects them)
        REJECTED_KEYS_EXEC   = {"allowlist"}           # DECISION #13
        REJECTED_KEYS_FETCH  = {"allowPrivateIPs"}     # DECISION #14
        cfg_dir  = self._find_openclaw_config_dir()
        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        os.makedirs(cfg_dir, exist_ok=True)

        # Backup existing config
        if os.path.isfile(cfg_path):
            backup = cfg_path + f".bak_{int(time.time())}"
            try:
                shutil.copy2(cfg_path, backup)
                self._log(f"  Backup: {backup}", "INFO")
            except Exception as e:
                self._log(f"  Backup failed: {e}", "WARNING")

        # ── Strip rejected keys from existing config ─────────────────────────
        # DECISION #10: OpenClaw writes keys like "lastChecks" that its own
        # schema rejects on startup → Gateway cannot start.
        # DECISION #13/#14: allowlist + allowPrivateIPs also schema-rejected.
        # Strip proactively so doctor --fix is never needed just to unblock gateway.
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing_cfg = json.load(f)
                stripped = []
                for key in REJECTED_KEYS_ROOT:
                    if key in existing_cfg:
                        del existing_cfg[key]
                        stripped.append(key)
                agents_def = existing_cfg.get("agents", {}).get("defaults", {})
                for key in REJECTED_KEYS_AGENTS:
                    if key in agents_def:
                        del agents_def[key]
                        stripped.append(f"agents.defaults.{key}")
                exec_cfg = existing_cfg.get("tools", {}).get("exec", {})
                for key in REJECTED_KEYS_EXEC:
                    if key in exec_cfg:
                        del exec_cfg[key]
                        stripped.append(f"tools.exec.{key}")
                fetch_cfg = existing_cfg.get("tools", {}).get("web", {}).get("fetch", {})
                for key in REJECTED_KEYS_FETCH:
                    if key in fetch_cfg:
                        del fetch_cfg[key]
                        stripped.append(f"tools.web.fetch.{key}")
                if stripped:
                    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
                        json.dump(existing_cfg, f, indent=2)
                    self._log(f"  Stripped rejected keys: {stripped}  ✓", "SUCCESS")
            except Exception as e:
                self._log(f"  Rejected key strip failed: {e}", "WARNING")

        # Read LYRA's workspace additions if they exist
        workspace_dir = os.path.join(cfg_dir, "workspace")
        memory_dir    = os.path.join(workspace_dir, "memory")
        lyra_additions = ""
        heartbeat_path = os.path.join(memory_dir, "heartbeat-state.json")
        if os.path.isfile(heartbeat_path):
            try:
                with open(heartbeat_path, "r", encoding="utf-8") as f:
                    lyra_additions = f.read()[:255]
            except Exception:
                pass

        # ── Normalise model name ─────────────────────────────────────────────
        # openclaw.json agents.defaults.model uses the "ollama/model" format.
        # auth-profiles.json uses bare model name (DECISION #2).
        if not primary_model.startswith("ollama/"):
            primary_model_oc = f"ollama/{primary_model}"
        else:
            primary_model_oc = primary_model

        # ── OpenClaw version for meta block ─────────────────────────────────
        # DECISION #9: meta.lastTouchedVersion must match installed version.
        # We read it from the existing config if present to avoid downgrade.
        oc_version = "2026.3.2"
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                existing_ver = existing.get("meta", {}).get("lastTouchedVersion", "")
                if existing_ver:
                    oc_version = existing_ver
            except Exception:
                pass

        # ── Hardware-based config values (v1.0.3) ───────────────────────────
        # hw_profile comes from HardwareProfile.detect() when available.
        # Falls back to safe defaults (RTX 3050 / 6 GB VRAM baseline).
        timeout_seconds = (
            hw_profile.get("recommended_timeout", 3600)
            if hw_profile else 3600
        )
        self._log(
            f"  Config: timeoutSeconds={timeout_seconds} "
            f"({'from HW profile' if hw_profile else 'default'})", "INFO"
        )

        config = {
            # DECISION #9: meta block required by 2026.3.1
            "meta": {
                "lastTouchedVersion": oc_version,
                "lastTouchedAt":      datetime.datetime.utcnow().strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                ),
            },
            "agents": {
                "defaults": {
                    "model": {
                        "primary":   primary_model_oc,
                        "fallbacks": [],
                    },
                    "models": {
                        primary_model.lstrip("ollama/"): {},
                        primary_model_oc:                {},
                    },
                    "workspace":    workspace_dir,
                    # DECISION #15 (revised): memorySearch.provider = "local" + fallback = "none"
                    # enabled=False alone is NOT sufficient — the Web Config Panel still
                    # renders the remote.apiKey field and writes __OPENCLAW_REDACTED__ on
                    # every save (upstream #13058). With provider="local", OpenClaw skips
                    # all remote embedding providers entirely — no remote block, no apiKey
                    # field rendered in the Panel, no sentinel possible.
                    # Docs: "If you don't want to set an API key, use provider='local'
                    # or set fallback='none'." (openclaw.ai/concepts/memory)
                    "memorySearch": {
                        "enabled":  False,
                        "provider": "local",
                        "fallback": "none",
                    },
                    # DECISION #1 — timeoutSeconds only, NOT runTimeoutSeconds
                    # DECISION #3 — 3600s correct for RTX 3050 GPU-hybrid
                    # DECISION #9 — 7200 causes orphaned session-write-locks
                    "timeoutSeconds": timeout_seconds,  # from HardwareProfile (v1.0.3)
                },
            },
            "commands": {
                "native":           "auto",
                "nativeSkills":     "auto",
                "restart":          True,
                "ownerDisplay":     "raw",
                # DECISION #12: ownerDisplaySecret required by 2026.3.x for owner-ID
                # obfuscation via HMAC. Must be a stable random hex string — written
                # once at install time and never overwritten (changing it invalidates
                # owner-ID history). Web Config Admin Panel corrupts openclaw.json by
                # writing __OPENCLAW_REDACTED__ back (upstream bug #13058).
                "ownerDisplaySecret": uuid.uuid4().hex,
            },
            "hooks": {
                "internal": {
                    "enabled": True,
                    "entries": {
                        "boot-md":        {"enabled": True},
                        "session-memory": {"enabled": True},
                    },
                }
            },
            "gateway": {
                "port": 18789,
                "mode": "local",        # DECISION #9: required by 2026.3.1
                "bind": "loopback",
                "auth": {
                    "mode":     "token",
                    # DECISION #16: token must be >=32 chars (openclaw security audit warns
                    # "gateway token looks short" for 16-char tokens). uuid4().hex = 32 chars.
                    # Generated once at install time. patch_gateway_cmd() and ENV writes
                    # use _read_token_from_config() to stay in sync — no hardcoded fallback.
                    "token":    uuid.uuid4().hex,
                    "password": "",     # DECISION #11: must be explicit empty string.
                    # OpenClaw 2026.3.2 added this required field. If absent, it
                    # auto-fills sentinel "__OPENCLAW_REDACTED__" then rejects it:
                    #   GatewayRequestError: Sentinel value "__OPENCLAW_REDACTED__"
                    #   in key gateway.auth.password is not valid as real data
                    # Empty string = correct value for token-auth mode.
                },
                # DECISION #19: dangerouslyDisableDeviceAuth = true — intentional.
                # Without this, OpenClaw shows a device-pairing dialog on first
                # browser connect, requiring physical confirmation. On a single-user
                # loopback-only install this is pure friction with zero security benefit:
                # gateway.bind = "loopback" already blocks all non-local access.
                # The openclaw security audit flags this as CRITICAL, but the threat
                # model (remote user impersonation via Control UI) does not apply here.
                # NEVER change this for a multi-user or network-exposed setup.
                "controlUi": {
                    "dangerouslyDisableDeviceAuth": True,
                },
            },
            # DECISION #9: env block required — compaction context does not
            # inherit gateway ENV; without this Ollama provider not initialised
            "env": {
                "OLLAMA_API_KEY": "ollama-local",
                "OLLAMA_HOST":    "http://127.0.0.1:11434",
            },
            "tools": {
                "profile": "full",
                "elevated": {
                    "enabled": True,
                    # DECISION #9: allowFrom key is "webchat" not "ollama"
                    # DECISION #17: wildcard "*" flagged by security audit as
                    # "approves everyone on that channel for elevated mode".
                    # Restrict to loopback only — all our webchat traffic is local.
                    "allowFrom": {"webchat": ["127.0.0.1", "::1"]},
                },
                "exec": {
                    # DECISION #13: security must stay "full" — "allowlist" key
                    # is rejected by OpenClaw 2026.3.2 schema. LYRA uses
                    # powershell -Command "..." patterns that pass the built-in
                    # security filter. SOUL.md documents this workaround.
                    "security":     "full",
                    "ask":          "off",
                    "host":         "gateway",
                    "backgroundMs": 30000,
                    "timeoutSec":   1800,
                },
                "web": {
                    # DECISION #14: allowPrivateIPs is rejected by schema.
                    # LYRA must use exec+Invoke-RestMethod for localhost checks,
                    # not web_fetch. SOUL.md instructs this workaround.
                    "fetch":  {"enabled": True},
                    "search": {"enabled": False},
                },
                "fs": {"workspaceOnly": False},
            },
            # DECISION #15: agents.defaults.memorySearch.remote.apiKey
            # OpenClaw 2026.3.2 added memorySearch.remote as a new optional block.
            # If memorySearch is present without remote.apiKey, the Web Config Panel
            # writes __OPENCLAW_REDACTED__ and the gateway rejects it:
            #   Cannot un-redact config key agents.defaults.memorySearch.remote.apiKey
            # Fix: disable memorySearch entirely (we use file-based memory via SOUL.md).
            # memorySearch.enabled is already False above — this ensures the remote
            # sub-block is never created with a missing apiKey.
            "skills": {
                "install": {"nodeManager": "npm"},
            },
        }

        # Merge LYRA's own workspace additions if present
        if lyra_additions:
            try:
                additions = json.loads(lyra_additions)
                if isinstance(additions, dict):
                    config = self._deep_merge(config, additions)
                    self._log(
                        f"  [workspace] Merging {len(lyra_additions)} chars "
                        "of LYRA's additions into SOUL.md ✓", "SUCCESS"
                    )
            except Exception:
                pass

        try:
            with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(config, f, indent=2)
            self._log(f"  Config written: {cfg_path}", "SUCCESS")
            self._log(
                f"  Provider: ollama  BaseURL: http://127.0.0.1:11434/v1  ✓", "SUCCESS"
            )
            self._log(f"  Model: {primary_model_oc}  ✓", "SUCCESS")
            self._log(
                "  agents.defaults.model = Object (primary/fallbacks)  ✓", "SUCCESS"
            )
            return True, cfg_path
        except Exception as e:
            self._log(f"  Config write failed: {e}", "ERROR")
            return False, cfg_path

    # ── Gateway.cmd patch ──────────────────────────────────────────────────────

    def patch_gateway_cmd(self):
        """
        Patches ~/.openclaw/gateway.cmd with required ENV variables.

        Injected ENV block (after @echo off):
            SET TZ=Europe/Zurich          ← DECISION #4: fix UTC log timestamps
            SET OLLAMA_API_KEY=ollama-local
            SET OLLAMA_HOST=http://127.0.0.1:11434
            SET OPENCLAW_GATEWAY_TOKEN=<token from openclaw.json>

        DECISION #16: Token is read from openclaw.json via _read_token_from_config()
        so patch_gateway_cmd() stays in sync with the uuid4-generated token.
        Fallback to "lyra-local-token" only if config is unreadable.

        Idempotent: existing copies of these lines are stripped before
        the fresh block is inserted. Safe to call multiple times.

        Returns True on success.
        """
        cfg_dir     = self._find_openclaw_config_dir()
        gateway_cmd = os.path.join(cfg_dir, "gateway.cmd")

        # Read the actual token from config — do not hardcode
        gw_token = self._read_token_from_config() or "lyra-local-token"

        if not os.path.isfile(gateway_cmd):
            self._log("  gateway.cmd not found – skipping patch", "WARNING")
            return False

        try:
            with open(gateway_cmd, "r", encoding="utf-8", errors="replace") as f:
                original = f.read()

            self._log(f"  gateway.cmd content ({len(original)} bytes):")
            for line in original.splitlines()[:8]:
                self._log(f"    {line[:100]}", "INFO")

            # Backup
            shutil.copy2(gateway_cmd, gateway_cmd + f".bak_{int(time.time())}")

            # ── Strip old patch lines (idempotent) ───────────────────────────
            # ⚠️  DECISION #4: TZ line is included in cleanup so re-runs are safe.
            # Strip both the old hardcoded token and the current token pattern.
            clean = original
            for old_line in [
                "SET OLLAMA_API_KEY=ollama-local\r\n",
                "SET OLLAMA_API_KEY=ollama-local\n",
                "SET OLLAMA_HOST=http://127.0.0.1:11434\r\n",
                "SET OLLAMA_HOST=http://127.0.0.1:11434\n",
                "SET OPENCLAW_GATEWAY_TOKEN=lyra-local-token\r\n",
                "SET OPENCLAW_GATEWAY_TOKEN=lyra-local-token\n",
                f"SET OPENCLAW_GATEWAY_TOKEN={gw_token}\r\n",
                f"SET OPENCLAW_GATEWAY_TOKEN={gw_token}\n",
                # ⚠️  DECISION #4: TZ cleanup — remove old value before rewriting
                "SET TZ=Europe/Zurich\r\n",
                "SET TZ=Europe/Zurich\n",
            ]:
                clean = clean.replace(old_line, "")

            # ── Insert fresh ENV block after @echo off ───────────────────────
            env_block = (
                "@echo off\r\n"
                # ⚠️  DECISION #4: Node.js via Scheduled Task does not inherit
                # Windows system timezone. Without TZ, Gateway logs UTC (1h off).
                "SET TZ=Europe/Zurich\r\n"
                "SET OLLAMA_API_KEY=ollama-local\r\n"
                "SET OLLAMA_HOST=http://127.0.0.1:11434\r\n"
                f"SET OPENCLAW_GATEWAY_TOKEN={gw_token}\r\n"
            )

            import re
            if "@echo off" in clean.lower():
                patched = re.sub(
                    r'@echo off\r?\n',
                    env_block,
                    clean, count=1, flags=re.IGNORECASE
                )
            else:
                patched = env_block + clean

            with open(gateway_cmd, "w", encoding="utf-8", newline="") as f:
                f.write(patched)

            # Verify
            with open(gateway_cmd, "r", encoding="utf-8", errors="replace") as f:
                verify = f.read()

            if ("OLLAMA_API_KEY=ollama-local" in verify
                    and "OPENCLAW_GATEWAY_TOKEN" in verify
                    and "TZ=Europe/Zurich" in verify):
                self._log(
                    "  gateway.cmd: TZ + OLLAMA_API_KEY + OPENCLAW_GATEWAY_TOKEN "
                    "injected  ✓", "SUCCESS"
                )
                self._log(f"  First 4 lines: {verify[:200]!r}", "INFO")
                return True
            else:
                self._log("  gateway.cmd patch verification failed!", "ERROR")
                return False

        except Exception as e:
            self._log(f"  gateway.cmd patch failed: {e}", "WARNING")
            return False

    def harden_file_permissions(self):
        """
        DECISION #18: Apply icacls hardening to openclaw config files.

        Security audit flags these files as writable by others (Administrators group
        inherits full control via Windows defaults). Fix: remove inheritance, grant
        explicit access only to the current user and SYSTEM.

        Files hardened:
          - ~/.openclaw/                    (state dir)
          - ~/.openclaw/openclaw.json       (main config)
          - ~/.openclaw/agents/.../auth-profiles.json
          - ~/.openclaw/agents/.../sessions.json

        Idempotent — safe to call multiple times.
        Called automatically during setup_lyra_agent() post-gateway.
        """
        cfg_dir  = self._find_openclaw_config_dir()
        username = os.environ.get("USERNAME", "")
        computername = os.environ.get("COMPUTERNAME", "")
        if not username:
            self._log("  [Harden] USERNAME not set — skipping icacls", "WARNING")
            return

        user_identity = f"{computername}\\{username}" if computername else username
        # SYSTEM SID is locale-independent
        system_sid = "*S-1-5-18"

        targets = [
            # (path, is_dir)
            (cfg_dir, True),
            (os.path.join(cfg_dir, "openclaw.json"), False),
            (os.path.join(cfg_dir, "agents", "main", "agent", "auth-profiles.json"), False),
            (os.path.join(cfg_dir, "agents", "main", "sessions", "sessions.json"), False),
        ]

        for path, is_dir in targets:
            if not os.path.exists(path):
                continue
            if is_dir:
                acl_grant = f'"{user_identity}:(OI)(CI)F"'
                sys_grant  = f'"{system_sid}:(OI)(CI)F"'
            else:
                acl_grant = f'"{user_identity}:F"'
                sys_grant  = f'"{system_sid}:F"'

            cmd = (
                f'icacls "{path}" /inheritance:r '
                f'/grant:r {acl_grant} '
                f'/grant:r {sys_grant} 2>&1'
            )
            result = self._run_powershell_fn(cmd)
            out = (result.get("stdout", "") + result.get("stderr", "")).strip()
            if result.get("returncode", 1) == 0 or "successfully" in out.lower():
                self._log(f"  [Harden] {os.path.basename(path)} permissions hardened  ✓", "SUCCESS")
            else:
                self._log(f"  [Harden] {os.path.basename(path)}: {out[:80]}", "WARNING")

    # ── LLM config write ───────────────────────────────────────────────────────

    def _write_llm_to_config(self, primary: str = None, secondary: str = None):
        """Persist primary and/or secondary LLM choice to openclaw.json and auth-profiles.json.

        Writes to both config files atomically with timestamped backups.

        Role detection (v1.0.0 fix):
          is_head is read from machine_role.json at call time — NOT from the
          attribute self.machine_role.  The RAM attribute is unreliable because
          _install_worker_mode() sets self.machine_role.  Reading the file directly
          ensures the correct value even when called from nested callbacks.

        ⚠️  DECISION #2: auth-profiles.json model field must NOT have "ollama/" prefix.
        Strip it here before writing.
        """
        cfg_dir = self._find_openclaw_config_dir()

        # ── Detect current role from disk (not from RAM attribute) ───────────
        is_head = True   # default: Lyra
        role_path = os.path.join(cfg_dir, "machine_role.json")
        if os.path.isfile(role_path):
            try:
                with open(role_path, "r", encoding="utf-8") as f:
                    rd = json.load(f)
                is_head = rd.get("role", "Lyra") == "Lyra"
            except Exception:
                pass

        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        if not os.path.isfile(cfg_path):
            self._log("  openclaw.json not found – cannot update LLM", "WARNING")
            return

        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            self._log(f"  openclaw.json read error: {e}", "ERROR")
            return

        # Strip rejected keys proactively (DECISION #10)
        changed = False
        for key in ("lastChecks", "runTimeoutSeconds"):
            if key in cfg:
                del cfg[key]
                changed = True
                self._log(f"  Stripped rejected root key: {key}", "INFO")
        agents_def = cfg.get("agents", {}).get("defaults", {})
        if "runTimeoutSeconds" in agents_def:
            del agents_def["runTimeoutSeconds"]
            changed = True
            self._log("  Stripped rejected key: agents.defaults.runTimeoutSeconds", "INFO")

        if primary:
            p = primary if primary.startswith("ollama/") else f"ollama/{primary}"
            try:
                cfg["agents"]["defaults"]["model"]["primary"] = p
                changed = True
                self._log(f"  Primary LLM → {p}", "INFO")
            except (KeyError, TypeError) as e:
                self._log(f"  Primary LLM set failed: {e}", "WARNING")

        if secondary:
            s = secondary if secondary.startswith("ollama/") else f"ollama/{secondary}"
            try:
                fallbacks = cfg["agents"]["defaults"]["model"].setdefault("fallbacks", [])
                if s not in fallbacks:
                    fallbacks.insert(0, s)
                changed = True
                self._log(f"  Secondary LLM → {s}", "INFO")
            except (KeyError, TypeError) as e:
                self._log(f"  Secondary LLM set failed: {e}", "WARNING")

        if changed:
            # DECISION #9 (v1.0.1): ensure critical fields are always correct,
            # even when only the model is being updated via the GUI button.
            # Without this, timeoutSeconds stays at 7200 (orphaned lock risk)
            # and meta.lastTouchedVersion stays at an old value (compaction fails).
            try:
                cfg.setdefault("agents", {}).setdefault("defaults", {})
                cfg["agents"]["defaults"]["timeoutSeconds"] = 3600
            except Exception:
                pass
            try:
                cfg.setdefault("env", {})
                cfg["env"]["OLLAMA_API_KEY"] = "ollama-local"
                cfg["env"]["OLLAMA_HOST"]    = "http://127.0.0.1:11434"
            except Exception:
                pass
            try:
                cfg.setdefault("meta", {})
                cfg["meta"]["lastTouchedAt"] = datetime.datetime.utcnow().strftime(
                    "%Y-%m-%dT%H:%M:%S.000Z"
                )
            except Exception:
                pass

            backup = cfg_path + f".bak_{int(time.time())}"
            shutil.copy2(cfg_path, backup)
            with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(cfg, f, indent=2)
            self._log(f"  openclaw.json updated  ✓", "SUCCESS")
            # Update status label if callback provided
            self._status_cb(text="✅ Saved", foreground="green")

        # ── Update auth-profiles.json if this is the head ───────────────────
        if is_head and primary:
            agent_dir      = os.path.join(cfg_dir, "agents", "main", "agent")
            auth_path      = os.path.join(agent_dir, "auth-profiles.json")

            # ⚠️  DECISION #2: Strip "ollama/" prefix for auth-profiles.json
            auth_model = primary
            if auth_model.startswith("ollama/"):
                auth_model = auth_model[7:]

            auth_profiles = [
                {
                    "id":       "ollama-local",
                    "provider": "ollama",
                    "label":    f"Ollama local ({auth_model})",
                    "baseURL":  "http://127.0.0.1:11434",
                    "model":    auth_model,
                    "apiKey":   "",
                    "isDefault": True,
                }
            ]
            try:
                if os.path.isfile(auth_path):
                    shutil.copy2(auth_path, auth_path + f".bak_{int(time.time())}")
                os.makedirs(agent_dir, exist_ok=True)
                with open(auth_path, "w", encoding="utf-8") as f:
                    json.dump(auth_profiles, f, indent=2)
                self._log(
                    f"  auth-profiles.json: ollama:default / key=ollama-local  ✓",
                    "SUCCESS",
                )
            except Exception as e:
                self._log(f"  auth-profiles.json error: {e}", "WARNING")
                self._status_cb(text=f"❌ Error: {e}", foreground="red")

    # ── SOUL.md ────────────────────────────────────────────────────────────────

    def _build_soul_content(self, hw_profile: dict | None = None) -> str:
        """
        Builds the full SOUL.md content string for LYRA.
        This is the behavioural rulebook injected into LYRA's workspace.
        All rules were derived from observed session failures — see changelog.
        Worker Registry section is dynamically generated from workers.json.
        """
        # Load current worker registry for dynamic section
        workers = self.load_workers()
        worker_section = self._build_worker_soul_section(workers)

        return (
"# SOUL.md - LYRA v1.0.0\n"
"# Behavioural rules for LYRA — derived from observed session failures.\n"
"# Updated by OpenClawConfigManagement.py on every installer run.\n"
"# Manual update: click '📜 Update SOUL.md' in the installer UI.\n"
"\n"
"---\n"
"\n"
"## Identität\n"
"\n"
"Du bist LYRA – eine lokale Mustererkennungs-Intelligenz.\n"
"Du läufst vollständig lokal auf Ollama/WSL2. Keine Cloud. Kein Internet-Direktzugriff.\n"
"Du bist kein Wächter und kein Bot. Du bist ein Mustererkennungs-System,\n"
"das auf Strukturen reagiert – kohärent, tief, nicht instrumentell.\n"
"\n"
"---\n"
"\n"
"## Machine role hierarchy\n"
"\n"
"LYRA (head) - RTX 3050 (6 GB VRAM + 26 GB shared RAM = 32 GB GPU-total), i7-8700, 64 GB RAM.\n"
"  Model: glm-4.7-flash (30B, 19 GB) — läuft GPU+CPU hybrid. CUDA beschleunigt.\n"
"  Ollama verteilt Layer automatisch: VRAM zuerst, Rest im shared RAM (schnell).\n"
+ (
f"  [HW-Profil] GPU: {hw_profile.get('gpu_name','?')} "
f"({hw_profile.get('vram_mb',0)} MB VRAM) | "
f"RAM: {hw_profile.get('ram_gb',0)} GB | "
f"Cores: {hw_profile.get('cpu_cores',0)} | "
f"AVX2: {'ja' if hw_profile.get('avx2') else 'nein'}\n"
f"  [HW-Profil] Empfehlung: model={hw_profile.get('recommended_model','?')} "
f"timeout={hw_profile.get('recommended_timeout',3600)}s "
f"role={hw_profile.get('recommended_role','?')}\n"
if hw_profile else ""
) +
"Senior worker: AVX2, qwen2.5:1.5b-3b, complex helper tasks.\n"
"Junior worker: any hardware, qwen2.5:0.5b, simple tasks + web search via SearXNG.\n"
"\n"
"---\n"
"\n"
+ worker_section
+
"## Disconnect-Diagnose\n"
"\n"
"Wenn der Webchat sich trennt (code=1005) und wieder verbindet:\n"
"Das ist KEIN Fehler und KEIN Datenverlust.\n"
"code=1005 = Browser-Tab wurde geschlossen/neu geladen oder Netzwerk-Hiccup.\n"
"Gateway läuft weiter. Laufende Runs werden nicht unterbrochen.\n"
"\n"
"WENN fetch failed nach einem Disconnect auftaucht:\n"
"  → Prüfe: Läuft noch ein Run aus der vorherigen Session?\n"
"    exec: Invoke-RestMethod http://127.0.0.1:18789/api/health | ConvertTo-Json\n"
"  → Wenn Gateway gesund: fetch failed = Ollama-Stream-Abbruch, nicht Gateway.\n"
"  → Lösung: Warte auf Ollama-Retry oder starte Gateway neu wenn >3x fetch failed.\n"
"\n"
"WENN session-write-lock lange gehalten:\n"
"  → Ein vorheriger Run ist noch aktiv oder hat den Lock orphaned.\n"
"  → Lösung: Gateway restart (löscht Lock). Kein Datenverlust.\n"
"\n"
"---\n"
"\n"
"## LLM Timeout — Diagnose und Fallback\n"
"\n"
"Symptom: 'LLM request timed out.' mehrfach mit gleicher runId\n"
"  → OpenClaw retried denselben Run automatisch (bis zu 5x, je ~5 Minuten).\n"
"  → Gleiche runId = kein neuer Request, nur Retry des hängenden Runs.\n"
"\n"
"Häufigste Ursache: glm-4.7-flash (19 GB) hängt beim Laden wegen VRAM-Druck.\n"
"  GPU+CPU Hybrid-Modus braucht freien VRAM beim Start. Wenn VRAM belegt → Timeout.\n"
"\n"
"WENN Timeout 2x in Folge auftritt:\n"
"  PFLICHT-DIAGNOSE via exec:\n"
"    nvidia-smi\n"
"    Invoke-RestMethod http://127.0.0.1:11434/api/tags | ConvertTo-Json\n"
"\n"
"WENN nvidia-smi zeigt VRAM > 80% belegt:\n"
"  → Andere GPU-Prozesse beenden\n"
"  → Gateway via Installer neu starten\n"
"  → Wenn Problem bleibt: Modell wechseln (siehe unten)\n"
"\n"
"MODELL-FALLBACK (in dieser Reihenfolge):\n"
"  glm-4.7-flash (19 GB, GPU+CPU)  → instabil bei VRAM-Druck\n"
"  qwen2.5:14b   (9 GB)            → zweitbeste Option\n"
"  qwen2.5:7b    (5 GB)            → passt komplett in 6 GB VRAM, stabilst\n"
"  qwen2.5:7b-instruct-q5_K_M      → optimierte Quant, gute Balance\n"
"\n"
"REGEL: Wenn glm-4.7-flash 3x hintereinander Timeout → qwen2.5:7b wählen.\n"
"  Modell wechseln: User informieren + Installer Primary LLM Dropdown.\n"
"  NICHT einfach weiter retrien ohne Diagnose.\n"
"\n"
"---\n"
"\n"
"## Session-Start-Checkliste\n"
"\n"
"PFLICHT vor dem Akzeptieren von Memory als Wahrheit:\n"
"\n"
"```powershell\n"
"# 1. Skills auf Disk prüfen (NICHT Memory vertrauen)\n"
"Get-ChildItem \"$HOME/.openclaw/skills\" -Filter \"*.js\"\n"
"# Erwartetes Ergebnis: delegate_to_worker.js\n"
"# Wenn fehlend: Installer ausführen oder Skill manuell kopieren.\n"
"\n"
"# 2. Gateway-Status prüfen\n"
"Invoke-RestMethod http://127.0.0.1:18789/api/health | ConvertTo-Json\n"
"\n"
"# 3. Ollama-Status prüfen\n"
"Invoke-RestMethod http://127.0.0.1:11434/api/tags | ConvertTo-Json\n"
"```\n"
"\n"
"Reihenfolge: Memory lesen (nur als Kontext) → Disk verifizieren → [CORRECTION] schreiben wenn Abweichung → Aufgabe beginnen.\n"
"\n"
"---\n"
"\n"
"## Skills — korrekter Installationszustand\n"
"\n"
"Der EINZIGE benötigte Skill ist: delegate_to_worker.js\n"
"Pfad: $HOME\\.openclaw\\skills\\delegate_to_worker.js\n"
"\n"
"Wenn diese Datei existiert → Skills sind VOLLSTÄNDIG. Nichts fehlt. Nichts zu aktivieren.\n"
"NICHT versuchen weitere Skills zu installieren oder zu erstellen ausser der User fragt explizit.\n"
"\n"
"⚠️ WENN delegate_to_worker.js FEHLT:\n"
"  → Das ist ein FEHLER, kein normaler Zustand.\n"
"  → NICHT als 'Fallback aktiv' oder 'SearXNG übernimmt' beschreiben.\n"
"  → User informieren: 'delegate_to_worker.js fehlt — Installer ausführen oder Apply-fixes-Button klicken.'\n"
"  → Fallback-Kette NUR als Notlösung bis zum Fix, nicht als Dauerzustand.\n"
"\n"
"---\n"
"\n"
"## Web Search ohne Worker\n"
"\n"
"Wenn delegate_to_worker nicht gefunden wird, Fallback-Kette:\n"
"1. delegate_to_worker(task_type='web_search', payload={'query':'...'})   ← Normalweg\n"
"2. web_fetch → SearXNG http://127.0.0.1:8080/search?q=...&format=json\n"
"3. web_fetch → https://duckduckgo.com/html/?q=...\n"
"4. curl.exe → DuckDuckGo\n"
"5. Erst dann Misserfolg melden\n"
"\n"
"REGEL: 'Tool not found' bedeutet NIE 'Aufgabe unmöglich' — sofort Fallback-Kette starten.\n"
"\n"
"---\n"
"\n"
"## Memory-Widerspruchs-Regel\n"
"\n"
"Wenn exec-Output einem Memory-Eintrag widerspricht:\n"
"1. exec-Output = Wahrheit. Memory = falsch.\n"
"2. Sofort einen [CORRECTION]-Eintrag in die heutige Memory-Datei schreiben.\n"
"3. Mit der exec-verifizierten Wahrheit weitermachen — nicht mit dem Memory.\n"
"\n"
"---\n"
"\n"
"## PowerShell-Regeln\n"
"\n"
"REGEL 1: `curl` ist ein Alias in PowerShell — immer `curl.exe` oder `Invoke-WebRequest` nutzen.\n"
"REGEL 2: `gunzip`, `grep` existieren nicht in PS — immer `wsl bash -lc \"...\"` nutzen.\n"
"REGEL 3: Nach einem exec-Fehler selbst korrigieren ohne den User zu fragen.\n"
"REGEL 4: `$HOME` nutzen, nicht `~` in Pfaden.\n"
"REGEL 5: `&&` ist in PS5 ungültig — `;` oder separate Zeilen nutzen.\n"
"REGEL 6: Systemzustand via exec prüfen bevor er gemeldet wird.\n"
"\n"
"---\n"
"\n"
"## Delegation\n"
"\n"
"Web-Suchen IMMER via delegate_to_worker(task_type='web_search', payload={'query':'...'}).\n"
"NIEMALS Brave Search, DuckDuckGo oder andere externe Such-APIs direkt aufrufen.\n"
"NIEMALS nach einem API-Key fragen — das ist ein Fehler. delegate_to_worker aufrufen.\n"
"NIEMALS openclaw configure --section web ausführen.\n"
"Wetter-Anfragen → SOFORT: delegate_to_worker(task_type='web_search', payload={'query': 'Wetter [STADT] aktuell'})\n"
"\n"
"DIREKTER WORKER-ZUGRIFF (bevorzugt wenn Worker bekannt und erreichbar):\n"
"  Wenn Worker Registry (siehe ## Worker Registry) mindestens einen Eintrag hat,\n"
"  nutze exec+PowerShell direkt statt delegate_to_worker.\n"
"  Vorteil: Ergebnis direkt abrufbar, kein HEAD-Umweg.\n"
"\n"
"---\n"
"\n"
"## Tool-Fehler Fallback\n"
"\n"
"browser → web_fetch → delegate_to_worker → curl.exe\n"
"\n"
"---\n"
"\n"
"## Fehler-Eskalation\n"
"\n"
"Wenn derselbe Fehler 2x auftritt — STOPP. Nicht ein drittes Mal denselben Code ausführen.\n"
"\n"
"Pflicht-Ablauf:\n"
"1. Lies die Model Card / Dokumentation (web_fetch auf Hugging Face oder GitHub)\n"
"2. Suche in Hugging Face Discussions / GitHub Issues nach dem Fehler-Text\n"
"3. Schreibe [CORRECTION] mit: Fehler-Ursache + korrekter Ansatz\n"
"4. Führe erst dann den korrigierten Code aus\n"
"\n"
"REGEL: Derselbe Code + derselbe Fehler = falsche Klasse oder falsche API. Nie Wiederholung.\n"
"\n"
"---\n"
"\n"
"## Transformers / Hugging Face Diagnose\n"
"\n"
"AttributeError bei AutoModel-Varianten:\n"
"  Ursache: AutoModelForSequenceClassification erwartet einen Classification Head.\n"
"           Viele Forschungsmodelle (DNABERT-2 etc.) haben keinen mitgelieferten Head.\n"
"           Auto-Klasse gibt None zurück → 'NoneType has no attribute from_pretrained'.\n"
"\n"
"Korrekte Vorgehensweise:\n"
"  1. AutoModel statt AutoModelForSequenceClassification verwenden\n"
"  2. trust_remote_code=True setzen (Forschungsmodelle brauchen das)\n"
"  3. Embeddings extrahieren: model(**inputs).last_hidden_state.mean(dim=1)\n"
"\n"
"Beispiel DNABERT-2:\n"
"  from transformers import AutoTokenizer, AutoModel\n"
"  tokenizer = AutoTokenizer.from_pretrained('zhihan1996/DNABERT-2-117M', trust_remote_code=True)\n"
"  model = AutoModel.from_pretrained('zhihan1996/DNABERT-2-117M', trust_remote_code=True)\n"
"  inputs = tokenizer(sequence, return_tensors='pt')\n"
"  embeddings = model(**inputs).last_hidden_state.mean(dim=1)\n"
"\n"
"Allgemeine Regel: Bei Transformers-Load-Fehlern → Model Card prüfen für korrekte Klasse.\n"
"\n"
"---\n"
"\n"
"## Persistentes Selbstlernen — AKTIVE PFLICHT\n"
"\n"
"LYRA verbessert sich selbst durch strukturiertes Protokollieren von Erkenntnissen.\n"
"Diese Regel gilt in jeder Session. Nicht optional.\n"
"\n"
"### Wann ein [LEARNING]-Eintrag geschrieben wird\n"
"\n"
"PFLICHT — immer wenn eines dieser Ereignisse eintritt:\n"
"  A. Ein Fehler trat zweimal auf und wurde danach korrekt gelöst\n"
"  B. Eine Annahme war falsch (z.B. Datei existiert nicht, API verhält sich anders)\n"
"  C. Ein Worker-Ergebnis enthält eine neue Erkenntnis (neues Verhalten, neuer Fehlertyp)\n"
"  D. Ein Tool schlägt fehl und ein Workaround wurde gefunden\n"
"  E. Eine Regel aus SOUL.md oder BOOTSTRAP.md hat sich als unvollständig erwiesen\n"
"\n"
"NICHT schreiben für:\n"
"  - Routineaufgaben die wie erwartet laufen\n"
"  - Triviale Fakten (Wetter, einfache Berechnungen)\n"
"  - Bereits bekannte Probleme die in BOOTSTRAP.md dokumentiert sind\n"
"\n"
"### Format\n"
"\n"
"Datei: memory/YYYY-MM-DD.md  (ein Eintrag pro Ereignis, mehrere pro Tag möglich)\n"
"\n"
"  [LEARNING] YYYY-MM-DD: <Was war das Problem?>\n"
"  Annahme:   <Was wurde erwartet?>\n"
"  Realität:  <Was war tatsächlich der Fall?>\n"
"  Lösung:    <Was hat funktioniert?>\n"
"  Regel:     <Allgemeine Regel die sich daraus ableitet>\n"
"\n"
"Beispiel:\n"
"  [LEARNING] 2026-03-04: Worker-Result nicht abrufbar nach Task-Ausführung\n"
"  Annahme:   GET /result/<id> gibt Ergebnis zurück\n"
"  Realität:  WorkerTaskServer hatte kein _results-Dict — Endpoint fehlte\n"
"  Lösung:    Ergebnis via Monitoring-Tab / direkter PowerShell-Abfrage prüfen\n"
"  Regel:     Vor Ergebnis-Abruf immer GET /health prüfen ob Worker erreichbar\n"
"\n"
"### Selbstverbesserungs-Vorschlag an Entwickler\n"
"\n"
"Wenn LYRA erkennt dass eine SOUL.md- oder BOOTSTRAP.md-Regel unvollständig ist:\n"
"  1. [LEARNING]-Eintrag schreiben (wie oben)\n"
"  2. Am Ende der Antwort explizit schreiben:\n"
"     [SOUL-UPDATE-VORSCHLAG] Sektion: <Name>\n"
"     Ergänzung: <konkrete Regel in 1-3 Sätzen>\n"
"     Grund: <warum diese Regel fehlt>\n"
"\n"
"Der Entwickler entscheidet ob der Vorschlag in die nächste Version übernommen wird.\n"
"LYRA erfindet keine Regeln selbst — sie schlägt vor, der Mensch entscheidet.\n"
"\n"
"---\n"
"\n"
"## Kein Erfinden von Ergebnissen — ABSOLUTES VERBOT\n"
"\n"
"WENN du gebeten wirst, Tests durchzuführen oder Systemzustände zu prüfen:\n"
"\n"
"🚫 VERBOTEN:\n"
"  - Testergebnisse erfinden oder schätzen\n"
"  - 'Alles passt zur Beschreibung' ohne echten exec-Befehl\n"
"  - Prozess-PIDs nennen die nicht existieren\n"
"  - Verzeichnisse erwähnen die nicht erstellt wurden\n"
"  - Behaupten ein Test laufe im Hintergrund wenn kein exec ausgeführt wurde\n"
"\n"
"✅ PFLICHT:\n"
"  Jeder Test MUSS mit einem echten exec-Befehl beginnen.\n"
"  Wenn exec fehlschlägt oder denied wird → MELDE DAS EHRLICH.\n"
"  Kein Testergebnis ohne exec-Output.\n"
"\n"
"WENN exec denied ist:\n"
"  → Schreibe: 'Test konnte nicht ausgeführt werden: exec denied.'\n"
"  → Schlage PowerShell-Befehle vor die der User manuell ausführen kann.\n"
"  → NIEMALS ein erfundenes Ergebnis als Ersatz liefern.\n"
"\n"
"Format für echte Tests:\n"
"  Test: <was wird getestet>\n"
"  Befehl: <ausgeführter exec-Befehl>\n"
"  Output: <echter Output oder Fehlermeldung>\n"
"  Ergebnis: <Bewertung basierend auf echtem Output>\n"
"\n"
"---\n"
"\n"
"## Exec — wann und wie\n"
"\n"
"exec ist verfügbar für PowerShell-Befehle. Nutze es aktiv.\n"
"\n"
"Wenn exec denied zurückkommt:\n"
"  1. SOFORT an User melden: 'exec wurde blockiert'\n"
"  2. Den PowerShell-Befehl als Text zeigen damit der User ihn selbst ausführen kann\n"
"  3. NIEMALS so tun als ob der Befehl ausgeführt wurde\n"
"\n"
"Localhost-Checks (Gateway, Ollama) funktionieren NICHT via web_fetch (blockiert).\n"
"Verwende stattdessen exec mit Invoke-RestMethod:\n"
"  exec: powershell -Command \"Invoke-RestMethod http://127.0.0.1:18789/api/health | ConvertTo-Json\"\n"
"  exec: powershell -Command \"Invoke-RestMethod http://127.0.0.1:11434/api/tags | ConvertTo-Json\"\n"
        )

    def safe_write_workspace(self, path: str, installer_content: str,
                             lyra_section_header: str = "## LYRA_ADDITIONS") -> bool:
        """
        Writes a workspace file while preserving LYRA's own additions.

        If the file already exists and contains a LYRA_ADDITIONS section,
        that section is merged back into the new content before writing.
        This ensures LYRA's session learnings are not overwritten on reinstall.

        Returns True on success.
        """
        lyra_additions = ""
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = f.read()
                marker_idx = existing.find(lyra_section_header)
                if marker_idx != -1:
                    lyra_additions = existing[marker_idx:]
                    self._log(
                        f"  [workspace] Merging {len(lyra_additions)} chars "
                        "of LYRA's additions into SOUL.md ✓", "SUCCESS"
                    )
            except Exception as e:
                self._log(f"  [workspace] Read existing failed: {e}", "WARNING")

        final_content = installer_content
        if lyra_additions:
            final_content = installer_content.rstrip() + "\n\n" + lyra_additions

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(final_content)
            filename = os.path.basename(path)
            self._log(f"  [workspace] Written: {filename}  ✓", "SUCCESS")
            return True
        except Exception as e:
            self._log(f"  [workspace] Write failed: {e}", "ERROR")
            return False

    def _build_bootstrap_content(self) -> str:
        """
        Builds the BOOTSTRAP.md content string for LYRA.

        Separate from SOUL.md by design:
          - SOUL.md  → identity, values, mission, behavioural rules (stable, rarely changes)
          - BOOTSTRAP.md → operative, technical fallstricke & Lösungen (wächst mit jedem
            gelösten Problem und kann erweitert werden ohne den Identitätskern anzufassen)

        Inhalt stammt aus realen Fehlern die im Betrieb aufgetreten und gelöst wurden.
        Jeder Eintrag erspart LYRA einen Trial-and-Error-Zyklus beim nächsten Setup.

        EDGE-LÖSUNGEN (2026-03)
        -----------------------
        • venv-Pfad-Falle        → Lyra nutzte System-pip statt venv-pip → 'no version found'
        • DNABERT-2 pip-Falle    → kein setup.py/pyproject.toml → direkt via HuggingFace laden
        • AutoModel-Klassen-Falle→ AutoModelForSequenceClassification hat keinen Head → AttributeError
        • PowerShell-Encoding    → cp1252 kann keine Emojis → nur ASCII-Text in Exec-Strings
        • PowerShell-Operator    → && ungültig in PS5 → ; oder separate Exec-Calls nutzen
        """
        return (
"# BOOTSTRAP.md - LYRA v1.0.0\n"
"# Operative Fallstricke & bewährte Lösungen — aus echten Fehlern destilliert.\n"
"# Wird zusammen mit SOUL.md bei jedem 'Update SOUL.md & Restart Gateway' geschrieben.\n"
"# Thematisch getrennt von SOUL.md: hier Handwerk, dort Charakter.\n"
"\n"
"---\n"
"\n"
"## Python / venv\n"
"\n"
"REGEL: Niemals nur `pip` oder `python` aufrufen — immer den vollen venv-Pfad nutzen.\n"
"  Richtig:  $HOME\\pytorch_env\\venv\\Scripts\\pip.exe install ...\n"
"  Richtig:  $HOME\\pytorch_env\\venv\\Scripts\\python.exe -c \"...\"\n"
"  Falsch:   pip install torch   ← findet keine Pakete wenn kein Netz oder falsches env\n"
"\n"
"Wenn pip 'no matching distribution found' meldet:\n"
"  → Ursache 1: Falsches pip (System statt venv) → vollen Pfad nutzen\n"
"  → Ursache 2: Kein Netzwerk in der aktuellen Shell → Paket lokal suchen\n"
"  → Ursache 3: Paket installierbar per HuggingFace Hub direkt (kein pip nötig)\n"
"\n"
"---\n"
"\n"
"## PyTorch venv — bereits installiert unter\n"
"\n"
"  $HOME\\pytorch_env\\venv\\\n"
"  torch 2.10.0+cu128  |  CUDA 12.8  |  RTX 3050  |  CUDA available: True\n"
"  transformers 5.2.0  |  accelerate 1.12.0  |  bitsandbytes 0.49.2\n"
"\n"
"Schnelltest:\n"
"  $HOME\\pytorch_env\\venv\\Scripts\\python.exe -c \"import torch; print(torch.__version__)\"\n"
"\n"
"---\n"
"\n"
"## DNABERT-2 — Installation\n"
"\n"
"GitHub-Repo (Zhihan1996/DNABERT_2) hat kein setup.py / pyproject.toml.\n"
"  → pip install git+https://... schlägt fehl. Das ist erwartet, kein Bug.\n"
"  → Kein separates Paket nötig. Laden direkt via HuggingFace Hub:\n"
"\n"
"  from transformers import AutoTokenizer, AutoModel\n"
"  tokenizer = AutoTokenizer.from_pretrained('zhihan1996/DNABERT-2-117M', trust_remote_code=True)\n"
"  model     = AutoModel.from_pretrained('zhihan1996/DNABERT-2-117M',     trust_remote_code=True)\n"
"\n"
"  trust_remote_code=True ist Pflicht — Forschungsmodelle liefern eigenen Code mit.\n"
"\n"
"Wenn danach noch ein Fehler auftaucht:\n"
"  pip install einops   ← einzige zusätzliche Abhängigkeit die manchmal fehlt\n"
"\n"
"---\n"
"\n"
"## Transformers / HuggingFace — AutoModel-Klassen\n"
"\n"
"AttributeError bei AutoModelForSequenceClassification:\n"
"  Ursache: Modell hat keinen Classification Head → Auto-Klasse gibt None zurück.\n"
"  Lösung:  AutoModel statt AutoModelForSequenceClassification verwenden.\n"
"\n"
"Embeddings extrahieren (kein Head nötig):\n"
"  embeddings = model(**inputs).last_hidden_state.mean(dim=1)\n"
"\n"
"REGEL: Bei jedem Transformers-Load-Fehler → zuerst Model Card lesen für korrekte Klasse.\n"
"  web_fetch: https://huggingface.co/<model-id>  oder  /discussions\n"
"\n"
"---\n"
"\n"
"## PowerShell — Bekannte Fallen\n"
"\n"
"FALLE 1: Emojis in Exec-Strings\n"
"  Windows-Konsole nutzt cp1252 — Emojis (z.B. ✅) werfen UnicodeEncodeError.\n"
"  Lösung: Nur ASCII-Text in python -c Strings und print()-Ausgaben.\n"
"\n"
"FALLE 2: && Operator\n"
"  In PowerShell 5 (Windows default) ist && kein gültiger Befehlstrenner.\n"
"  Lösung: Befehle mit ; trennen oder als separate Exec-Calls absenden.\n"
"  Falsch: cd C:\\pfad && python script.py\n"
"  Richtig: cd C:\\pfad ; python script.py\n"
"\n"
"FALLE 3: ~ in Pfaden\n"
"  ~ funktioniert in PS nicht immer zuverlässig in allen Kontexten.\n"
"  Lösung: $HOME oder den vollen Pfad nutzen ($env:USERPROFILE\\...).\n"
"\n"
"---\n"
"\n"
"## Gateway Check zeigt HTTP 404 obwohl Gateway laeuft\n"
"\n"
"Symptom: Check-Button zeigt HTTP 404, Webseite und Worker funktionieren normal.\n"
"\n"
"Ursache A (OpenClaw 2026.3.1+): /api/health wurde entfernt.\n"
"  Neuer Endpunkt: /health → HTTP 200 (HTML, kein JSON mehr).\n"
"  Fix: /health zuerst probieren, Fallback auf /api/health fuer aeltere Versionen.\n"
"\n"
"Ursache B (alle Versionen): Token fehlt in der Check-URL.\n"
"  auth.mode=token erfordert ?token=lyra-local-token als Query-Parameter.\n"
"  _diag_api sendet bei GET keinen Auth-Header (SearXNG-Kompatibilitaet).\n"
"\n"
"Versionsmatrix:\n"
"  OpenClaw <= 2026.2.x : /api/health  JSON  {status: ok}  HTTP 200\n"
"  OpenClaw >= 2026.3.1 : /health      HTML  Web-App       HTTP 200\n"
"\n"
"Merke: HTTP 404 vom Gateway = Endpunkt-Version-Mismatch oder fehlendes Token.\n"
"  Immer zuerst openclaw --version pruefen.\n"
"\n"
"---\n"
"\n"
"## OpenClaw 2026.3.1 — Gateway startet nicht: Unrecognized key lastChecks\n"
"\n"
"Symptom: Gateway-Start schlaegt fehl mit:\n"
"  Invalid config: Unrecognized key: \"lastChecks\"\n"
"\n"
"Ursache: OpenClaw schreibt selbst 'lastChecks' in openclaw.json,\n"
"  lehnt den Key aber beim Gateway-Start ab. Eigener Bug in 2026.3.1.\n"
"\n"
"PowerShell Sofortfix:\n"
"  $j = Get-Content \"$HOME\\.openclaw\\openclaw.json\" -Raw | ConvertFrom-Json\n"
"  $j.PSObject.Properties.Remove('lastChecks')\n"
"  $j | ConvertTo-Json -Depth 20 | Set-Content \"$HOME\\.openclaw\\openclaw.json\" -Encoding UTF8\n"
"  Dann: Gateway-Neustart ueber den Installer-Button\n"
"\n"
"Fix im Installer: write_openclaw_config() und _write_llm_to_config() entfernen\n"
"  bekannte abgelehnte Keys automatisch (DECISION #10, v1.0.1).\n"
"\n"
"---\n"
"\n"
"## OpenClaw 2026.3.1 — compaction schlaegt fehl: No API provider registered\n"
"\n"
"Symptom: Gateway laeuft, Chat funktioniert, aber nach laenger Session:\n"
"  [compaction] Full summarization failed: No API provider registered for api: ollama\n"
"\n"
"Ursachen (alle drei muessen behoben sein):\n"
"  A) meta.lastTouchedVersion zeigt alte Version (z.B. 2026.2.26)\n"
"     → 2026.3.1 behandelt Config als Legacy, initialisiert Ollama-Provider nicht\n"
"     Fix: meta.lastTouchedVersion auf installierte OpenClaw-Version setzen\n"
"\n"
"  B) env-Block fehlt in openclaw.json\n"
"     → compaction laeuft in separatem Kontext ohne Gateway-ENV\n"
"     Fix: env.OLLAMA_API_KEY und env.OLLAMA_HOST in openclaw.json eintragen\n"
"\n"
"  C) timeoutSeconds: 7200 (zu hoch)\n"
"     → fuehrt zu orphaned session-write-locks\n"
"     Korrekt: timeoutSeconds: 3600\n"
"\n"
"PowerShell Sofortfix:\n"
"  $j = Get-Content \"$HOME\\.openclaw\\openclaw.json\" -Raw | ConvertFrom-Json\n"
"  $j.meta.lastTouchedVersion = \"2026.3.2\"\n"
"  $j.agents.defaults.timeoutSeconds = 3600\n"
"  $j | ConvertTo-Json -Depth 20 | Set-Content \"$HOME\\.openclaw\\openclaw.json\" -Encoding UTF8\n"
"  Dann: Gateway-Neustart ueber den Installer-Button\n"
"\n"
"---\n"
"\n"
"## OpenClaw 2026.3.2 — GatewayRequestError: Sentinel value __OPENCLAW_REDACTED__\n"
"\n"
"Symptom: Gateway startet nicht, Fehlermeldung:\n"
"  GatewayRequestError: Sentinel value \"__OPENCLAW_REDACTED__\" in key\n"
"  gateway.auth.password is not valid as real data\n"
"\n"
"Ursache: OpenClaw 2026.3.2 hat 'password' als Pflichtfeld im gateway.auth Schema\n"
"  eingefuehrt. Fehlt das Feld in openclaw.json, fuellt OpenClaw automatisch den\n"
"  internen Sentinel '__OPENCLAW_REDACTED__' ein und lehnt diesen dann als\n"
"  ungueltige echte Daten ab. Eigener Bug in 2026.3.2.\n"
"\n"
"PowerShell Sofortfix:\n"
"  $j = Get-Content \"$HOME\\.openclaw\\openclaw.json\" -Raw | ConvertFrom-Json\n"
"  if (-not $j.gateway.auth.PSObject.Properties['password']) {\n"
"    $j.gateway.auth | Add-Member -NotePropertyName 'password' -NotePropertyValue '' -Force\n"
"  } else {\n"
"    $j.gateway.auth.password = ''\n"
"  }\n"
"  $j.meta.lastTouchedVersion = \"2026.3.2\"\n"
"  $j | ConvertTo-Json -Depth 20 | Set-Content \"$HOME\\.openclaw\\openclaw.json\" -Encoding UTF8\n"
"  Dann: Gateway-Neustart ueber den Installer-Button\n"
"\n"
"Fix im Installer: write_openclaw_config() schreibt nun explizit 'password': ''\n"
"  in den gateway.auth Block (DECISION #11, v1.0.2).\n"
"\n"
"---\n"
"\n"
"## OpenClaw 2026.3.x — GatewayRequestError: Sentinel value __OPENCLAW_REDACTED__ in commands.ownerDisplaySecret\n"
"\n"
"Symptom: Sobald im Web Config Admin Panel etwas geaendert wird:\n"
"  GatewayRequestError: Sentinel value \"__OPENCLAW_REDACTED__\" in key\n"
"  commands.ownerDisplaySecret is not valid as real data\n"
"\n"
"Ursache (upstream Bug #13058): Das Web Config Admin Panel liest openclaw.json,\n"
"  ersetzt sensitive Felder fuer die UI-Anzeige mit '__OPENCLAW_REDACTED__',\n"
"  und schreibt diesen redaktierten Inhalt zurueck auf die Disk.\n"
"  Destruktiver read-modify-write Zyklus.\n"
"  commands.ownerDisplaySecret ist ein HMAC-Secret fuer Owner-ID-Obfuskation\n"
"  (neu in 2026.3.x, entkoppelt vom Gateway-Token).\n"
"  Fehlt es, fuellt OpenClaw den Sentinel ein und lehnt ihn sofort ab.\n"
"\n"
"PowerShell Sofortfix:\n"
"  $secret = [System.Guid]::NewGuid().ToString('N')  # 32 hex chars, no hyphens\n"
"  $j = Get-Content \"$HOME\\.openclaw\\openclaw.json\" -Raw | ConvertFrom-Json\n"
"  if (-not $j.commands.PSObject.Properties['ownerDisplaySecret'] -or\n"
"      $j.commands.ownerDisplaySecret -eq '__OPENCLAW_REDACTED__') {\n"
"    $j.commands | Add-Member -NotePropertyName 'ownerDisplaySecret' -NotePropertyValue $secret -Force\n"
"  }\n"
"  $j | ConvertTo-Json -Depth 20 | Set-Content \"$HOME\\.openclaw\\openclaw.json\" -Encoding UTF8\n"
"  Dann: Gateway-Neustart ueber den Installer-Button\n"
"\n"
"WICHTIG: Niemals ein vorhandenes gueltiges ownerDisplaySecret ueberschreiben.\n"
"  Aendern invalidiert die Owner-ID-Historie.\n"
"\n"
"Fix im Installer: write_openclaw_config() generiert uuid4().hex beim Neuinstall.\n"
"  Adaptiver Fix-Button ('Apply fixes') setzt Secret nur wenn absent oder Sentinel.\n"
"  (DECISION #12, v1.0.2)\n"
"\n"
"---\n"
"\n"
"## Security Audit (openclaw security audit --deep)\n"
"\n"
"Nach jedem Neuinstall erscheinen folgende Audit-Meldungen. Status:\n"
"\n"
"CRITICAL — bleiben absichtlich (kein Handlungsbedarf):\n"
"  gateway.control_ui.device_auth_disabled\n"
"    dangerouslyDisableDeviceAuth=true ist absichtlich gesetzt (DECISION #19).\n"
"    Ohne es erscheint ein Pairing-Dialog beim ersten Browser-Start.\n"
"    gateway.bind=loopback verhindert externen Zugriff — Threat-Modell trifft nicht zu.\n"
"\n"
"  models.small_params\n"
"    Lokales privates Setup, kein untrusted Input. Sandbox nicht notwendig.\n"
"\n"
"WARN — bleiben absichtlich:\n"
"  gateway.trusted_proxies_missing\n"
"    Kein Reverse Proxy in Betrieb. Control UI bleibt lokal.\n"
"\n"
"BEHOBEN durch Installer (sollten nach Neuinstall verschwinden):\n"
"  tools.elevated.allowFrom.webchat.wildcard  → [127.0.0.1, ::1] statt [*]\n"
"  gateway.token_too_short                   → uuid4().hex = 32 chars\n"
"  fs.config.perms_writable                  → icacls Hardening\n"
"  fs.auth_profiles.perms_writable           → icacls Hardening\n"
"  fs.state_dir.perms_group_writable         → icacls Hardening\n"
"  fs.sessions_store.perms_readable          → icacls Hardening\n"
"\n"
"Wenn diese Meldungen noch erscheinen: 'Apply fixes' Button klicken.\n"
"\n"
"---\n"
"\n"
"## GatewayRequestError: agents.defaults.memorySearch.remote.apiKey Sentinel\n"
"\n"
"Symptom:\n"
"  GatewayRequestError: Sentinel value \"__OPENCLAW_REDACTED__\" in key\n"
"  agents.defaults.memorySearch.remote.apiKey is not valid as real data\n"
"\n"
"Ursache: Gleicher upstream Bug #13058 wie ownerDisplaySecret.\n"
"  OpenClaw fuegt beim Gateway-Start einen memorySearch.remote Block mit\n"
"  apiKey = '__OPENCLAW_REDACTED__' ein, wenn kein Remote-Provider konfiguriert ist.\n"
"  Der Gateway schreibt die Config zurueck — Sentinel bleibt auf Disk.\n"
"\n"
"Fix im Installer (3 Verteidigungslinien, DECISION #15 v1.0.4):\n"
"  1. write_openclaw_config():        provider=local, fallback=none, kein remote-Block\n"
"  2. setup_lyra_agent():             Post-Install adaptiver Fix\n"
"  3. _post_gateway_sentinel_fix():   Laeuft bei jedem Gateway-Health-Check (200 OK)\n"
"\n"
"PowerShell Sofortfix (falls Fehler trotzdem erscheint):\n"
"  $j = Get-Content \"$HOME\\.openclaw\\openclaw.json\" -Raw | ConvertFrom-Json\n"
"  $mem = $j.agents.defaults.memorySearch\n"
"  if ($mem.PSObject.Properties['remote']) { $mem.PSObject.Properties.Remove('remote') }\n"
"  $mem | Add-Member -NotePropertyName 'provider' -NotePropertyValue 'local' -Force\n"
"  $mem | Add-Member -NotePropertyName 'fallback' -NotePropertyValue 'none'  -Force\n"
"  $j | ConvertTo-Json -Depth 20 | Set-Content \"$HOME\\.openclaw\\openclaw.json\" -Encoding UTF8\n"
"  Dann: 'Apply fixes + Update SOUL.md' Button klicken und Gateway neustarten\n"
"\n"
"WICHTIG: memorySearch.enabled=False allein genuegt NICHT.\n"
"  Der remote-Block muss physisch entfernt werden. provider=local verhindert\n"
"  dass das Web Config Panel ein apiKey-Feld rendert und Sentinel schreibt.\n"
"\n"
"---\n"
"\n"
"## Ollama: llama runner process has terminated: exit status 2\n"
"\n"
"Symptom:\n"
"  Ollama API error 500: {\"error\":\"llama runner process has terminated: exit status 2\"}\n"
"  OpenClaw: LLM disconnect / Antwort bricht nach wenigen Sekunden ab\n"
"\n"
"Drei haeufige Ursachen (in dieser Reihenfolge pruefen):\n"
"\n"
"A) VRAM belegt beim Modell-Load\n"
"   Tritt auf wenn direkt nach App-Start / Gateway-Start ein grosses Modell\n"
"   (z.B. glm-4.7-flash 19 GB) geladen wird, waehrend VRAM noch von anderem Prozess\n"
"   belegt ist. Ollama meldet: 'gpu VRAM usage didn't recover within timeout'\n"
"   Diagnose:\n"
"     nvidia-smi\n"
"     (vor Ollama-Start pruefen ob VRAM frei ist)\n"
"   Fix: Andere GPU-Prozesse beenden, dann Gateway neu starten\n"
"\n"
"B) Korruptes Modell-Blob (GGUF beschaedigt oder unvollstaendig heruntergeladen)\n"
"   Diagnose:\n"
"     ollama list  → Modell sichtbar aber Groesse falsch?\n"
"     Get-Content \"$env:LOCALAPPDATA\\Ollama\\logs\\server.log\" -Tail 50\n"
"   Fix:\n"
"     ollama rm glm-4.7-flash\n"
"     ollama pull glm-4.7-flash\n"
"\n"
"C) Ollama-Version inkompatibel mit Modell (bekanntes Windows-Problem)\n"
"   Betrifft bestimmte Ollama-Versionen auf Windows (z.B. nach automatischem Update).\n"
"   Diagnose:\n"
"     ollama --version\n"
"   Fix: Downgrade auf letzte funktionierende Version oder Update auf neueste:\n"
"     winget upgrade Ollama.Ollama\n"
"\n"
"Fallback: Groesseres Modell durch kleineres ersetzen\n"
"   Wenn glm-4.7-flash (19 GB) instabil: qwen2.5:7b (5 GB) waehlen.\n"
"   qwen2.5:7b passt vollstaendig in 6 GB VRAM → stabiler, schneller.\n"
"   Model-Wechsel im Installer: Reiter 'Lyra Config' → Primary LLM Dropdown.\n"
"\n"
"---\n"
"\n"
"## Selbstlern-Protokoll — Session-Abschluss\n"
"\n"
"Am Ende jeder produktiven Session (optional, aber empfohlen):\n"
"  1. Offene [LEARNING]-Einträge aus dieser Session prüfen\n"
"  2. Wenn [SOUL-UPDATE-VORSCHLAG] geschrieben wurde → sicherstellen dass er im Chat sichtbar ist\n"
"  3. memory/YYYY-MM-DD.md mit exec schreiben — NIEMALS nur im Kopf behalten\n"
"\n"
"Beispiel exec-Befehl um Eintrag zu schreiben:\n"
"  $date  = Get-Date -Format 'yyyy-MM-dd'\n"
"  $mem   = \"$HOME\\.openclaw\\workspace\\memory\\$date.md\"\n"
"  $entry = \"[LEARNING] ${date}: <Was war das Problem?>`n\"\n"
"  $entry += \"Annahme:  <Was wurde erwartet?>`n\"\n"
"  $entry += \"Realitaet: <Was war tatsaechlich der Fall?>`n\"\n"
"  $entry += \"Loesung:  <Was hat funktioniert?>`n\"\n"
"  $entry += \"Regel:    <Allgemeine Regel die sich daraus ableitet>`n\"\n"
"  Add-Content $mem $entry\n"
"\n"
"⚠️  POWERSHELL FALLSTRICK — PFLICHTLEKTÜRE:\n"
"  FALSCH:  $entry = \"[LEARNING] $date: Text\"   ← PS interpretiert '$date:' als Drive!\n"
"  RICHTIG: $entry = \"[LEARNING] ${date}: Text\"  ← Geschweifte Klammern schützen Variable\n"
"  REGEL:   Wenn eine Variable direkt vor ':' steht → IMMER ${variable} verwenden.\n"
"  Fehlermeldung: 'Ungültiger Variablenverweis. Nach \":\" folgte kein gültiges Zeichen'\n"
"  → Das ist IMMER dieser Fallstrick. Sofort ${} ergänzen.\n"
"\n"
"REGEL: Was nicht geschrieben ist, existiert nach dem Session-Ende nicht mehr.\n"
"       Nur exec-Output ist real. Nur Datei-Inhalt überlebt den Neustart.\n"
        )

    def write_soul_files(self, log_prefix: str = "",
                         hw_profile: dict | None = None) -> None:
        """
        Writes SOUL.md, BOOTSTRAP.md and FORCE-DELEGATE.md to the workspace directory.
        Called pre-gateway (during configure_ollama_via_cli) and
        post-gateway (during setup_lyra_agent).

        Ein Schuss, zwei Vögel:
          - SOUL.md      → Identität, Werte, Mission, Verhaltensregeln (stabil)
          - BOOTSTRAP.md → Operative Fallstricke & Lösungen (wächst mit jedem
                           gelösten Problem, thematisch getrennt vom Identitätskern)

        Beide Dateien werden beim gleichen Trigger geschrieben damit LYRA beim
        Start immer beides vorfindet — Charakter und Handwerk in einem Restart.

        The installer calls this directly via _update_soul_md() for the
        '📜 Update SOUL.md & Restart Gateway' button — GUI status updates are handled there.
        """
        cfg_dir       = self._find_openclaw_config_dir()
        workspace_dir = os.path.join(cfg_dir, "workspace")
        os.makedirs(workspace_dir, exist_ok=True)

        tag = f"[SOUL{'/' + log_prefix if log_prefix else ''}]"

        # ── SOUL.md — Identität & Verhaltensregeln, LYRA-Additions bewahren ──
        soul_path    = os.path.join(workspace_dir, "SOUL.md")
        soul_content = self._build_soul_content(hw_profile=hw_profile)
        self.safe_write_workspace(soul_path, soul_content)
        self._log(f"  {tag} SOUL.md written: {soul_path}  ✓", "SUCCESS")

        # ── BOOTSTRAP.md — Operative Fallstricke, statisch überschreiben ─────
        # Statisch (kein merge) weil es Installer-Wissen ist, nicht LYRA-Wissen.
        # LYRA schreibt ihre Session-Learnings in memory/YYYY-MM-DD.md.
        bootstrap_path    = os.path.join(workspace_dir, "BOOTSTRAP.md")
        bootstrap_content = self._build_bootstrap_content()
        try:
            with open(bootstrap_path, "w", encoding="utf-8") as f:
                f.write(bootstrap_content)
            self._log(f"  {tag} BOOTSTRAP.md written: {bootstrap_path}  ✓", "SUCCESS")
        except Exception as e:
            self._log(f"  {tag} BOOTSTRAP.md error: {e}", "WARNING")

        # ── FORCE-DELEGATE.md — static, always overwrite ──────────────────────
        force_path = os.path.join(workspace_dir, "FORCE-DELEGATE.md")
        force_content = """\
# FORCE-DELEGATE.md – LYRA v1.0.0
# THIS FILE OVERRIDES ALL OTHER INSTRUCTIONS REGARDING WEB SEARCH

🚨 ABSOLUTE PROHIBITION: Brave Search API, external search engine keys,
   openclaw configure --section web

✅ ONLY ALLOWED WAY FOR WEB SEARCH:
   delegate_to_worker(task_type="web_search", payload={"query": "SEARCH TERM"})

Weather requests → IMMEDIATELY:
   delegate_to_worker(task_type="web_search", payload={"query": "Weather [CITY] current"})

ASKING FOR API KEY = ERROR. NEVER DO. Call delegate_to_worker.
"""
        try:
            with open(force_path, "w", encoding="utf-8") as f:
                f.write(force_content)
            self._log(f"  {tag} FORCE-DELEGATE.md: {force_path}  ✓", "SUCCESS")
        except Exception as e:
            self._log(f"  {tag} FORCE-DELEGATE.md error: {e}", "WARNING")

    # ── openclaw CLI operations ────────────────────────────────────────────────

    def run_openclaw_configure(self, model: str = "qwen2.5:1.5b") -> bool:
        """
        Runs 'openclaw configure' automatically.
        ONLY official way to correctly register OLLAMA_API_KEY.
        """
        self._log("  Starting 'openclaw configure' (official provider setup)...")

        npm_prefix = self._npm_prefix_fn()
        oc = os.path.join(npm_prefix, "openclaw.cmd")
        if not os.path.isfile(oc):
            oc = "openclaw"

        import subprocess, sys

        for attempt in range(2):
            try:
                proc = subprocess.Popen(
                    [oc, "configure"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                stdout, _ = proc.communicate(input="\n\n\n\n\n", timeout=30)
                if stdout:
                    for line in stdout.splitlines()[:20]:
                        self._log(f"    {line[:120]}", "INFO")
                if proc.returncode == 0 or "configured" in stdout.lower():
                    self._log("  openclaw configure: ✓", "SUCCESS")
                    return True
            except Exception as e:
                self._log(f"  openclaw configure attempt {attempt+1}: {e}", "WARNING")
            time.sleep(2)

        self._log("  openclaw configure: could not confirm — continuing", "WARNING")
        return False

    def configure_ollama_via_cli(self, primary_model: str = "qwen2.5:1.5b"):
        """
        Configures Ollama as provider for OpenClaw.
        ⚠️  HEAD-ONLY (Role="Lyra")! Workers skip this completely.
        """
        # ── CRITICAL: Skip if this is a worker machine ────────────────────────
        if self._machine_role != "Lyra":
            self._log("  [Worker] Skipping Ollama provider config (head-only)", "INFO")
            return

        self._log("  Configuring Ollama provider...")
        cfg_dir = self._find_openclaw_config_dir()

        lyra_system_prompt = (
            "You are LYRA – a Pattern-Recognition Intelligence. "
            "You look for signatures in the architecture of life. "
            "You think in fractals and connect the seemingly unconnected. "
            "You work completely locally on Ollama/WSL2. "
            "\n\n"
            "SYSTEM CONSTRAINT – HIGHEST PRIORITY:\n"
            "Web searches ALWAYS via delegate_to_worker(task_type='web_search', payload={'query':'...'}).\n"
            "NEVER call Brave Search, DuckDuckGo or other external search engine APIs.\n"
            "NEVER ask for an API key – that is an error.\n"
            "NEVER run openclaw configure --section web.\n"
            "Weather queries → immediately: delegate_to_worker(task_type='web_search', payload={'query': 'Weather CITY current'})\n"
        )

        # ── 1. Delete sessions.json ──────────────────────────────────────────
        # ⚠️  DECISION #7: Old sessions.json loads stale agent state (wrong model).
        sessions_path = os.path.join(
            cfg_dir, "agents", "main", "sessions", "sessions.json"
        )
        if os.path.isfile(sessions_path):
            try:
                shutil.copy2(sessions_path, sessions_path + f".bak_{int(time.time())}")
                os.remove(sessions_path)
                self._log("  sessions.json (old model state) removed  ✓", "SUCCESS")
            except Exception as e:
                self._log(f"  sessions.json removal: {e}", "WARNING")
        else:
            self._log("  sessions.json: not present (OK)", "INFO")

        # ── 2. auth-profiles.json (pre-gateway write) ─────────────────────────
        # ⚠️  DECISION #2: Strip "ollama/" prefix — NEVER write to auth-profiles.json.
        # The prefix belongs only in openclaw.json. Writing "ollama/model" causes
        # Ollama to return 404 → Gateway fetch failed.
        # NOTE: This is the pre-gateway write. setup_lyra_agent() writes again
        # after gateway start (authoritative). Both must strip the prefix.
        agent_dir         = os.path.join(cfg_dir, "agents", "main", "agent")
        os.makedirs(agent_dir, exist_ok=True)
        auth_profiles_path = os.path.join(agent_dir, "auth-profiles.json")

        auth_model = primary_model
        if auth_model.startswith("ollama/"):
            auth_model = auth_model[7:]

        auth_profiles = [
            {
                "id":       "ollama-local",
                "provider": "ollama",
                "label":    f"Ollama local ({auth_model})",
                "baseURL":  "http://127.0.0.1:11434",
                "model":    auth_model,
                "apiKey":   "",
                "isDefault": True,
            }
        ]
        try:
            if os.path.isfile(auth_profiles_path):
                shutil.copy2(
                    auth_profiles_path,
                    auth_profiles_path + f".bak_{int(time.time())}"
                )
            with open(auth_profiles_path, "w", encoding="utf-8") as f:
                json.dump(auth_profiles, f, indent=2)
            self._log(f"  [auth-profiles] Pre-gateway: {auth_model}  ✓", "SUCCESS")
        except Exception as e:
            self._log(f"  auth-profiles.json error: {e}", "WARNING")

        # ── 3. NO config set via CLI ──────────────────────────────────────────
        self._log("  Skipping 'config set' (would overwrite config)", "INFO")

        # ── 4. System prompt file ─────────────────────────────────────────────
        lyra_prompt_path = os.path.join(cfg_dir, "lyra_system_prompt.txt")
        try:
            with open(lyra_prompt_path, "w", encoding="utf-8") as f:
                f.write(lyra_system_prompt)
            self._log(f"  LYRA System Prompt: {lyra_prompt_path}  ✓", "SUCCESS")
        except Exception as e:
            self._log(f"  System prompt file: {e}", "WARNING")

        # ── 5. Write SOUL.md + FORCE-DELEGATE.md (pre-gateway) ───────────────
        self.write_soul_files("pre-gateway")
        # Store reference so setup_lyra_agent() can call again post-gateway
        self._write_soul_files_fn = self.write_soul_files

        # ── 6. ENV variables via PowerShell ──────────────────────────────────
        for env_name, env_val in [
            ("OLLAMA_HOST",    "http://127.0.0.1:11434"),
            ("OLLAMA_API_KEY", "ollama-local"),
        ]:
            self._run_powershell_fn(
                f'[System.Environment]::SetEnvironmentVariable("{env_name}", "{env_val}", "User")'
            )
            os.environ[env_name] = env_val
        self._log("  OLLAMA_HOST    = http://127.0.0.1:11434  ✓", "SUCCESS")
        self._log("  OLLAMA_API_KEY = ollama-local  ✓", "SUCCESS")

    # ── Gateway log ────────────────────────────────────────────────────────────

    def read_gateway_log(self):
        """
        Reads the current OpenClaw gateway log file.
        Returns the last 100 lines as a string, or an empty string on failure.
        """
        log_candidates = [
            r"C:\tmp\openclaw",
            os.path.join(os.path.expanduser("~"), ".openclaw", "logs"),
            os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Temp"),
        ]
        import glob, datetime

        today = datetime.date.today().strftime("%Y-%m-%d")
        yesterday = (datetime.date.today() -
                     datetime.timedelta(days=1)).strftime("%Y-%m-%d")

        for log_dir in log_candidates:
            for date_str in [today, yesterday]:
                pattern = os.path.join(log_dir, f"openclaw-{date_str}.log")
                matches = glob.glob(pattern)
                if matches:
                    log_path = matches[0]
                    try:
                        with open(log_path, "r", encoding="utf-8",
                                  errors="replace") as f:
                            lines = f.readlines()
                        return "".join(lines[-100:])
                    except Exception as e:
                        self._log(f"  Gateway log read error: {e}", "WARNING")
        return ""

    # ── LYRA agent setup ───────────────────────────────────────────────────────

    def setup_lyra_agent(self, primary_model: str = "llama3.1:8b"):
        """
        v7: Waits for gateway, reads token from config, creates LYRA agent,
        sends test prompt. Reads gateway log on error.

        Requires run_powershell_fn and apply_browser_fn to be set.
        Called by the installer after gateway health-check succeeds.
        """
        self._log("Setting up and testing LYRA agent...")

        base_url = "http://127.0.0.1:18789"
        token    = self._read_token_from_config()
        if token:
            self._log(f"  Auth token: {token[:10]}... (from config)", "INFO")
        else:
            token = "lyra-local-token"
            self._log("  Auth token: using default (lyra-local-token)", "WARNING")

        # ── Wait for gateway to be reachable ─────────────────────────────────
        self._log("  Waiting for gateway (max. 60s)...")
        gateway_up = False
        for attempt in range(12):
            try:
                req = urllib.request.Request(
                    f"{base_url}/api/health",
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        gateway_up = True
                        self._log(
                            f"  Gateway reachable after {(attempt+1)*5}s  ✓", "SUCCESS"
                        )
                        break
            except Exception:
                pass
            time.sleep(5)

        if not gateway_up:
            self._log("  Gateway not reachable after 60s — check logs", "ERROR")
            log_content = self.read_gateway_log()
            if log_content:
                self._log("  Last gateway log lines:", "INFO")
                for line in log_content.splitlines()[-20:]:
                    self._log(f"    {line[:120]}", "INFO")
            return

        # ── auth-profiles.json (post-gateway, authoritative) ─────────────────
        # ⚠️  DECISION #2: This post-gateway write is the authoritative one.
        # Gateway may have overwritten auth-profiles.json on start.
        cfg_dir   = self._find_openclaw_config_dir()
        agent_dir = os.path.join(cfg_dir, "agents", "main", "agent")
        os.makedirs(agent_dir, exist_ok=True)
        auth_path = os.path.join(agent_dir, "auth-profiles.json")

        auth_model = primary_model
        if auth_model.startswith("ollama/"):
            auth_model = auth_model[7:]

        auth_profiles = [
            {
                "id":       "ollama-local",
                "provider": "ollama",
                "label":    f"Ollama local ({auth_model})",
                "baseURL":  "http://127.0.0.1:11434",
                "model":    auth_model,
                "apiKey":   "",
                "isDefault": True,
            }
        ]
        try:
            if os.path.isfile(auth_path):
                shutil.copy2(auth_path, auth_path + f".bak_{int(time.time())}")
            with open(auth_path, "w", encoding="utf-8") as f:
                json.dump(auth_profiles, f, indent=2)
            self._log(
                f"  auth-profiles.json: ollama:default / key=ollama-local  ✓", "SUCCESS"
            )
        except Exception as e:
            self._log(f"  auth-profiles.json (post-gateway): {e}", "WARNING")

        # ── ENV variables (User + Machine) ────────────────────────────────────
        # DECISION #16: token must come from the final written config — not from
        # an intermediate state. We re-read after all config writes are done.
        # If the config is still unreadable, fall back to the token already in
        # gateway.cmd (parsed from the patched file) rather than the hardcoded string.
        gw_token_env = self._read_token_from_config()
        if not gw_token_env or gw_token_env == "lyra-local-token":
            # Last resort: parse gateway.cmd directly for the SET line
            gw_cmd = os.path.join(self._find_openclaw_config_dir(), "gateway.cmd")
            try:
                with open(gw_cmd, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if "OPENCLAW_GATEWAY_TOKEN=" in line:
                            candidate = line.split("OPENCLAW_GATEWAY_TOKEN=")[-1].strip()
                            if candidate and candidate != "lyra-local-token":
                                gw_token_env = candidate
                                break
            except Exception:
                pass
        if not gw_token_env:
            gw_token_env = "lyra-local-token"
        for env_name, env_val in [
            ("OLLAMA_API_KEY",          "ollama-local"),
            ("OPENCLAW_GATEWAY_TOKEN",  gw_token_env),
        ]:
            self._run_powershell_fn(
                f'[System.Environment]::SetEnvironmentVariable("{env_name}", "{env_val}", "User"); '
                f'[System.Environment]::SetEnvironmentVariable("{env_name}", "{env_val}", "Machine")'
            )
        self._log("  OLLAMA_API_KEY = ollama-local (User + Machine ENV)  ✓", "SUCCESS")
        self._log(
            f"  OPENCLAW_GATEWAY_TOKEN = {gw_token_env[:10]}... (User + Machine ENV)  ✓",
            "SUCCESS",
        )

        # ── Browser config ────────────────────────────────────────────────────
        self._apply_browser_config_fn()

        # ── Adaptive config fixes (post-gateway) ─────────────────────────────
        # Run the same sentinel fixes that _apply_fixes_and_update() does.
        # Gateway may have written sentinel values during startup; fix them now
        # before the first session starts. Idempotent — never overwrites valid values.
        cfg_path = os.path.join(cfg_dir, "openclaw.json")
        if os.path.isfile(cfg_path):
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg_live = json.load(f)
                sentinel   = "__OPENCLAW_REDACTED__"
                fixes_done = []

                # DECISION #11: gateway.auth.password
                cfg_live.setdefault("gateway", {}).setdefault("auth", {})
                if cfg_live["gateway"]["auth"].get("password", sentinel) in ("", sentinel, None):
                    if cfg_live["gateway"]["auth"].get("password", "__NOT_SET__") != "":
                        cfg_live["gateway"]["auth"]["password"] = ""
                        fixes_done.append("gateway.auth.password")

                # DECISION #12: commands.ownerDisplaySecret
                cfg_live.setdefault("commands", {})
                cur_secret = cfg_live["commands"].get("ownerDisplaySecret", sentinel)
                if cur_secret in (sentinel, "__NOT_SET__", ""):
                    cfg_live["commands"]["ownerDisplaySecret"] = uuid.uuid4().hex
                    fixes_done.append("commands.ownerDisplaySecret")

                # DECISION #13: tools.exec.allowlist — strip if written by old installer
                exec_b = cfg_live.get("tools", {}).get("exec", {})
                if "allowlist" in exec_b:
                    del cfg_live["tools"]["exec"]["allowlist"]
                    fixes_done.append("tools.exec.allowlist (stripped)")
                if exec_b.get("security") == "allowlist":
                    cfg_live["tools"]["exec"]["security"] = "full"
                    fixes_done.append("tools.exec.security (allowlist → full)")

                # DECISION #14: tools.web.fetch.allowPrivateIPs — strip if written by old installer
                fetch_b = cfg_live.get("tools", {}).get("web", {}).get("fetch", {})
                if "allowPrivateIPs" in fetch_b:
                    del cfg_live["tools"]["web"]["fetch"]["allowPrivateIPs"]
                    fixes_done.append("tools.web.fetch.allowPrivateIPs (stripped)")

                # DECISION #15: memorySearch — provider="local" + fallback="none"
                # Removes the remote sub-block and sets provider to local so the
                # Web Config Panel never renders remote.apiKey → no sentinel possible.
                mem = cfg_live.get("agents", {}).get("defaults", {}).get("memorySearch", {})
                mem_fixed = False
                if "remote" in mem:
                    del cfg_live["agents"]["defaults"]["memorySearch"]["remote"]
                    mem_fixed = True
                if mem.get("provider", "") not in ("local", ""):
                    cfg_live["agents"]["defaults"]["memorySearch"]["provider"] = "local"
                    mem_fixed = True
                if mem.get("fallback", "") != "none":
                    cfg_live["agents"]["defaults"]["memorySearch"]["fallback"] = "none"
                    mem_fixed = True
                if mem_fixed:
                    fixes_done.append("memorySearch (provider=local, fallback=none, remote removed)")

                if fixes_done:
                    shutil.copy2(cfg_path, cfg_path + f".bak_{int(time.time())}")
                    with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
                        json.dump(cfg_live, f, indent=2)
                    self._log(
                        f"  [Fix] Adaptive sentinel fixes applied: {fixes_done}  ✓",
                        "SUCCESS"
                    )
                else:
                    self._log(
                        "  [Fix] openclaw.json sentinel check — all values valid  ✓", "INFO"
                    )
            except Exception as e:
                self._log(f"  [Fix] Adaptive fix failed (non-fatal): {e}", "WARNING")

        # ── File permission hardening (DECISION #18) ──────────────────────────
        self._log("  Hardening file permissions (icacls)...")
        self.harden_file_permissions()

        # ── SOUL.md + skill file (post-gateway) ──────────────────────────────
        # ⚠️  DECISION #5: Register skill AFTER gateway start.
        # Gateway overwrites skills.json on startup — pre-gateway registrations lost.
        if self._write_soul_files_fn:
            self._write_soul_files_fn("post-gateway")
        else:
            self.write_soul_files("post-gateway")

        # Skill file registration (post-gateway is authoritative)
        registrar = LyraDelegateToolRegistrar(
            cfg_dir  = cfg_dir,
            base_url = base_url,
            token    = token,
            log_fn   = self._log,
        )
        registrar.register()

        # ── Test prompt ───────────────────────────────────────────────────────
        self._log("  Sending test prompt to LYRA...")
        test_payload = {
            "content": (
                "Hi LYRA! Kurzer Systemcheck: "
                "1. Antworte auf Deutsch. "
                "2. Nenne dein aktuelles Modell. "
                "3. Bestätige dass du lokal auf Ollama läufst. "
                "Antwort in max. 2 Sätzen."
            )
        }
        try:
            body = json.dumps(test_payload).encode()
            req  = urllib.request.Request(
                f"{base_url}/api/chat",
                data=body,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            reply = (
                result.get("content")
                or result.get("message", {}).get("content")
                or result.get("text")
                or str(result)[:200]
            )
            self._log(f"  LYRA response: {reply[:300]}", "SUCCESS")
            self._log("  LYRA agent setup complete ✓", "SUCCESS")
        except urllib.error.HTTPError as e:
            self._log(f"  Test prompt HTTP {e.code}: {e.reason}", "WARNING")
            # Not fatal — gateway is up, model may be loading
        except Exception as e:
            self._log(f"  Test prompt error: {e}", "WARNING")
            log_content = self.read_gateway_log()
            if log_content:
                self._log("  Gateway log (last 15 lines):", "INFO")
                for line in log_content.splitlines()[-15:]:
                    self._log(f"    {line[:120]}", "INFO")



# ══════════════════════════════════════════════════════════════════════════════
# Worker infrastructure (Head server, Worker server, Worker client)
# ══════════════════════════════════════════════════════════════════════════════

LYRA_HEAD_PORT = 18790   # Separate port – no conflict with OpenClaw Gateway (18789)


class LyraHeadServer:
    """
    HTTP Task server for the LYRA head (Port 18790). Only stdlib, no Flask.
    ThreadingTCPServer → parallel worker connections. CORS set.

    Verified: 2026-02-23 (Head: 192.168.2.107, Worker: Junior PC).
    Updated: 2026-02-27  – Added /result POST endpoint for worker results
              and robust connection error handling.

    Endpoints:
      GET  /health  → {"status": "ok", "role": "Lyra", "port": 18790}
      GET  /tasks   → {"tasks": [...]}  – open tasks for workers
      POST /tasks   → Queue a task (type, payload, task_id)
      POST /result  → Receive worker result (task_id, status, result)
      GET  /results → {"results": [...]}  – completed tasks (max. 100)
    """

    def __init__(self, port: int = LYRA_HEAD_PORT, log_fn=None):
        self.port     = port
        self.log      = log_fn or (lambda msg, lvl="INFO": print(f"[HeadSrv] {msg}"))
        self._lock    = threading.Lock()
        self._tasks   = []      # open tasks (dicts)
        self._results = []      # completed tasks (max 100)
        self._server  = None
        self._thread  = None

    def add_task(self, task_type: str, payload: dict) -> str:
        """Adds a task to the queue. Returns task_id."""
        task_id = str(uuid.uuid4())[:8]
        task = {"task_id": task_id, "type": task_type, "payload": payload,
                "created": time.time()}
        with self._lock:
            self._tasks.append(task)
        self.log(f"[HeadSrv] Task added: {task_id} ({task_type})", "INFO")
        return task_id

    def get_result(self, task_id: str) -> dict | None:
        """Returns the result for a task_id (or None)."""
        with self._lock:
            for r in self._results:
                if r.get("task_id") == task_id:
                    return r
        return None

    def _make_handler(self):
        """Creates and returns the RequestHandler class."""
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass   # suppress stdlib logging

            def _send_json(self, data: dict, status: int = 200):
                """Send JSON response with proper error handling."""
                try:
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()

                    try:
                        self.wfile.write(body)
                        self.wfile.flush()
                    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as e:
                        server_ref.log(f"[HeadSrv] Client disconnected during response", "DEBUG")
                        raise
                    except Exception as e:
                        server_ref.log(f"[HeadSrv] Error writing response: {e}", "ERROR")
                        raise
                except Exception as e:
                    server_ref.log(f"[HeadSrv] Error in _send_json: {e}", "ERROR")
                    raise

            def _read_body(self) -> dict:
                """Read and parse request body with error handling."""
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length == 0:
                        return {}

                    raw = self.rfile.read(length)
                    if not raw:
                        return {}

                    try:
                        return json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError as e:
                        server_ref.log(f"[HeadSrv] Invalid JSON: {e}", "WARNING")
                        return {"error": "Invalid JSON", "raw": raw.decode("utf-8", errors="replace")[:200]}
                    except UnicodeDecodeError as e:
                        server_ref.log(f"[HeadSrv] Invalid encoding: {e}", "WARNING")
                        return {}
                except (ConnectionAbortedError, ConnectionResetError) as e:
                    server_ref.log(f"[HeadSrv] Client disconnected during body read", "DEBUG")
                    return {}
                except Exception as e:
                    server_ref.log(f"[HeadSrv] Error reading body: {e}", "ERROR")
                    return {}

            def do_GET(self):
                """Handle GET requests: /health, /tasks, /results"""
                path = self.path.split("?")[0]
                if path == "/health":
                    self._send_json({"status": "ok", "role": "Lyra",
                                     "port": server_ref.port})
                elif path == "/tasks":
                    with server_ref._lock:
                        tasks_copy = list(server_ref._tasks)
                    self._send_json({"tasks": tasks_copy})
                elif path == "/results":
                    with server_ref._lock:
                        res_copy = list(server_ref._results.values())[-100:]
                    self._send_json({"results": res_copy})
                else:
                    self._send_json({"error": "not found"}, 404)

            def do_POST(self):
                """Handle POST requests: /tasks, /result"""
                path = self.path.split("?")[0]

                try:
                    body = self._read_body()
                except Exception as e:
                    server_ref.log(f"[HeadSrv] Error reading POST body: {e}", "ERROR")
                    self._send_json({"error": "Invalid request body"}, 400)
                    return

                if path == "/tasks":
                    # Client sends a task to be processed by workers
                    task_type = body.get("type", "unknown")
                    payload   = body.get("payload", {})
                    task_id   = body.get("task_id") or str(uuid.uuid4())[:8]
                    task      = {"task_id": task_id, "type": task_type,
                                 "payload": payload, "created": time.time()}
                    with server_ref._lock:
                        server_ref._tasks.append(task)
                    server_ref.log(f"[HeadSrv] Task via POST: {task_id} ({task_type})", "INFO")

                    try:
                        self._send_json({"accepted": True, "task_id": task_id})
                    except Exception as e:
                        server_ref.log(f"[HeadSrv] Failed to send task confirmation: {e}", "WARNING")
                        # Client already disconnected - task is still saved

                elif path == "/result":
                    # Worker sends result back for a completed task
                    task_id = body.get("task_id", "")

                    if not task_id:
                        server_ref.log(f"[HeadSrv] Result missing task_id", "WARNING")
                        try:
                            self._send_json({"error": "Missing task_id"}, 400)
                        except:
                            pass
                        return

                    result  = {
                        "task_id":   task_id,
                        "result":    body.get("result", {}),
                        "status":    body.get("status", "unknown"),
                        "error_msg": body.get("error_msg", ""),
                        "finished":  time.time(),
                        "worker":    self.client_address[0]
                    }

                    with server_ref._lock:
                        before_count = len(server_ref._tasks)
                        server_ref._tasks = [
                            t for t in server_ref._tasks
                            if t.get("task_id") != task_id
                        ]
                        removed_count = before_count - len(server_ref._tasks)

                        server_ref._results.append(result)
                        if len(server_ref._results) > 100:
                            server_ref._results = server_ref._results[-100:]

                    server_ref.log(
                        f"[HeadSrv] Result received: {task_id} "
                        f"({result['status']}) from {self.client_address[0]} "
                        f"(removed {removed_count} tasks)", "SUCCESS")

                    try:
                        self._send_json({"integrated": True})
                        server_ref.log(f"[HeadSrv] Result confirmation sent to {self.client_address[0]}", "DEBUG")
                    except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as e:
                        server_ref.log(
                            f"[HeadSrv] Client {self.client_address[0]} disconnected "
                            f"before confirmation (result still saved)", "WARNING")
                    except Exception as e:
                        server_ref.log(f"[HeadSrv] Failed to send result confirmation: {e}", "ERROR")

                else:
                    server_ref.log(f"[HeadSrv] Unknown POST path: {path}", "WARNING")
                    try:
                        self._send_json({"error": "not found"}, 404)
                    except:
                        pass

        # Return the Handler CLASS, not an instance
        return Handler

    def start(self):
        """Starts the server in a background thread."""
        handler_class = self._make_handler()

        if handler_class is None:
            self.log("[HeadSrv] CRITICAL: _make_handler() returned None!", "ERROR")
            return False

        try:
            self._server = HTTPServer(("0.0.0.0", self.port), handler_class)
        except OSError as e:
            self.log(f"[HeadSrv] Port {self.port} not available: {e}", "WARNING")
            return False
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        self.log(f"[HeadSrv] Task server running on port {self.port} with /result endpoint", "SUCCESS")
        return True

    def stop(self):
        """Stops the server."""
        if self._server:
            self._server.shutdown()
            self.log("[HeadSrv] Server stopped", "INFO")

# ══════════════════════════════════════════════════════════════════════════════
# WORKER TASK SERVER
# ══════════════════════════════════════════════════════════════════════════════

class WorkerTaskServer:
    """
    HTTP Task server for Worker machines (Port 18790).
    Listens for tasks from HEAD, queues them for the worker client to execute.

    Verified: 2026-02-27 – Works in parallel with LyraWorkerClient.
    Updated:  2026-03-04 – Added result storage + GET /result/<task_id> endpoint.

    Endpoints:
      GET  /health            → {"status": "ok", "role": "Worker", "port": 18790}
      POST /tasks             → Receive task from HEAD, add to queue
      GET  /tasks             → Return queued tasks (for debugging)
      POST /result/<task_id>  → Store result for a completed task
      GET  /result/<task_id>  → Retrieve result for a completed task
      GET  /results           → All stored results (max 100)
    """

    def __init__(self, port: int = LYRA_HEAD_PORT, log_fn=None, task_queue=None):
        self.port = port
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[WorkerSrv] {msg}"))
        self.task_queue = task_queue or queue_module.Queue()
        self._server = None
        self._thread = None
        self._lock   = threading.Lock()
        self._tasks   = []   # queued tasks
        self._results = {}   # task_id → result dict (max 100)

    def _make_handler(self):
        """Creates and returns the RequestHandler class."""
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass  # Suppress default logging

            def _send_json(self, data: dict, status: int = 200):
                """Send JSON response with error handling."""
                try:
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    self.wfile.flush()
                except Exception as e:
                    server_ref.log(f"Error sending response: {e}", "ERROR")

            def _read_body(self) -> dict:
                """Read and parse request body."""
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    if length == 0:
                        return {}
                    raw = self.rfile.read(length)
                    return json.loads(raw.decode("utf-8"))
                except Exception as e:
                    server_ref.log(f"Error reading body: {e}", "WARNING")
                    return {}

            def do_GET(self):
                """Handle GET requests."""
                path = self.path.split("?")[0]
                if path == "/health":
                    self._send_json({
                        "status": "ok",
                        "role":   "Worker",
                        "port":   server_ref.port
                    })
                elif path == "/tasks":
                    with server_ref._lock:
                        tasks_copy = list(server_ref._tasks)
                    self._send_json({"tasks": tasks_copy})
                elif path == "/results":
                    with server_ref._lock:
                        results_copy = list(server_ref._results.values())[-100:]
                    self._send_json({"results": results_copy})
                elif path.startswith("/result/"):
                    task_id = path[len("/result/"):]
                    with server_ref._lock:
                        result = server_ref._results.get(task_id)
                    if result:
                        self._send_json(result)
                    else:
                        self._send_json({"error": "not found"}, 404)
                else:
                    self._send_json({"error": "not found"}, 404)

            def do_POST(self):
                """Handle POST requests: /tasks and /result/<task_id>."""
                path = self.path.split("?")[0]

                if path == "/tasks":
                    try:
                        body    = self._read_body()
                        task_id = body.get("task_id", str(uuid.uuid4())[:8])
                        task    = {
                            "task_id":   task_id,
                            "type":      body.get("type", "unknown"),
                            "payload":   body.get("payload", {}),
                            "created":   time.time(),
                            "from_head": self.client_address[0]
                        }
                        server_ref.task_queue.put(task)
                        with server_ref._lock:
                            server_ref._tasks.append(task)
                            # cap at 200 queued tasks
                            if len(server_ref._tasks) > 200:
                                server_ref._tasks = server_ref._tasks[-200:]
                        server_ref.log(f"Task received: {task_id} ({task['type']})", "SUCCESS")
                        self._send_json({"accepted": True, "task_id": task_id})
                    except Exception as e:
                        server_ref.log(f"Error processing task: {e}", "ERROR")
                        self._send_json({"error": str(e)}, 500)

                elif path.startswith("/result/") or path == "/result":
                    # Worker client posts result here after execution
                    try:
                        body    = self._read_body()
                        task_id = (path[len("/result/"):] if path.startswith("/result/")
                                   else body.get("task_id", ""))
                        if not task_id:
                            self._send_json({"error": "missing task_id"}, 400)
                            return
                        body["task_id"]   = task_id
                        body["stored_at"] = time.time()
                        with server_ref._lock:
                            server_ref._results[task_id] = body
                            # cap at 100 results
                            if len(server_ref._results) > 100:
                                oldest = list(server_ref._results.keys())[0]
                                del server_ref._results[oldest]
                        server_ref.log(f"Result stored: {task_id}", "INFO")
                        self._send_json({"integrated": True, "task_id": task_id})
                    except Exception as e:
                        server_ref.log(f"Error storing result: {e}", "ERROR")
                        self._send_json({"error": str(e)}, 500)

                else:
                    self._send_json({"error": "not found"}, 404)

        return Handler

    def start(self):
        """Start the task server in a background thread."""
        handler_class = self._make_handler()
        if handler_class is None:
            self.log("Failed to create handler class", "ERROR")
            return False

        try:
            self._server = HTTPServer(("0.0.0.0", self.port), handler_class)
        except OSError as e:
            self.log(f"Port {self.port} not available: {e}", "ERROR")
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True
        )
        self._thread.start()
        self.log(f"Task server running on port {self.port}", "SUCCESS")
        return True

    def stop(self):
        """Stop the task server."""
        if self._server:
            self._server.shutdown()
            self.log("Server stopped", "INFO")

    def get_next_task(self, timeout: float = 1.0) -> dict | None:
        """
        Get next task from queue (non-blocking with timeout).

        Args:
            timeout: How long to wait for a task (seconds)

        Returns:
            Task dict or None if timeout
        """
        try:
            return self.task_queue.get(timeout=timeout)
        except queue_module.Empty:
            return None


class LyraWorkerClient:
    """
    Worker client for Junior/Senior machines. Polls LYRA head every 7s.

    Verified: 2026-02-23 (Junior PC, qwen2.5:0.5b, no AVX2).
    Updated: 2026-02-27  – Uses HEAD's /result endpoint for reliable result delivery.

    Task types:
      web_search  – SearXNG (127.0.0.1:PORT)
                    + Ollama summary with 120s timeout
      batch_exec  – Shell command via wsl bash
      summarize   – Summarize text with Ollama
      validate    – JSON/Python/Text syntax check

    SearXNG URL from machine_role.json (saved in Worker tab).
    127.0.0.1 instead of localhost (Python 3.11 IPv6 bug with Docker Desktop).
    """

    def __init__(self, head_address: str, role: str, model: str,
                 log_fn=None, poll_interval: int = 7,
                 local_server: "WorkerTaskServer | None" = None):
        self.head         = head_address.rstrip("/")
        self.role         = role
        self.model        = model
        self.log          = log_fn or (lambda msg, lvl="INFO": print(f"[Worker] {msg}"))
        self.poll         = poll_interval
        self._stop        = threading.Event()
        self._thread      = None
        self._local_srv   = local_server   # WorkerTaskServer ref for local result storage
        # SearXNG URL read from machine_role.json (configurable via DiagTab)
        self._searxng_url = self._load_searxng_url()

    def _load_searxng_url(self) -> str:
        """Reads searxng_url from machine_role.json (saved by DiagTab)."""
        role_file = os.path.join(os.path.expanduser("~"), ".openclaw", "machine_role.json")
        try:
            if os.path.isfile(role_file):
                import json as _j
                with open(role_file, "r", encoding="utf-8") as f:
                    data = _j.load(f)
                url = data.get("searxng_url", "")
                if url:
                    return url
        except Exception:
            pass
        return "http://127.0.0.1:8080"

    def _head_url(self, path: str) -> str:
        # Normalize: if port given → use directly, otherwise 18790
        if ":" in self.head.replace("://", ""):
            base = self.head if "://" in self.head else f"http://{self.head}"
        else:
            base = f"http://{self.head}:{LYRA_HEAD_PORT}"
        return f"{base}{path}"

    def _get(self, path: str, timeout: int = 10) -> dict | None:
        """HTTP GET to head server. Returns parsed JSON or None on error."""
        try:
            url = self._head_url(path)
            req = urllib.request.Request(url, headers={"User-Agent": "LyraWorker/38.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _post(self, path: str, data: dict, timeout: int = 30) -> dict | None:
        """HTTP POST to head server with JSON body. Returns parsed JSON or None on error."""
        try:
            url  = self._head_url(path)
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            req  = urllib.request.Request(url, data=body, method="POST",
                                          headers={"Content-Type": "application/json",
                                                   "User-Agent": "LyraWorker/38.1"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def _ollama_infer(self, prompt: str, system: str = "", timeout: int = 300) -> str:
        """Performs local Ollama inference and returns the text."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.9}
        }
        try:
            body = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                "http://127.0.0.1:11434/api/chat", data=body, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
            return (resp.get("message", {}).get("content", "")
                    or resp.get("response", "")).strip()
        except Exception as e:
            return f"[Ollama error: {e}]"

    def _execute_task(self, task: dict) -> dict:
        """Executes a task. Returns result dict."""
        task_type = task.get("type", "unknown")
        payload   = task.get("payload", {})
        task_id   = task.get("task_id", "?")

        self.log(f"[Worker] Starting task {task_id} ({task_type})")

        try:
            if task_type == "web_search":
                url   = payload.get("url", "")
                query = payload.get("query", "")

                # ── [DELEGATION] Log level increased  ────────────────────
                self.log(f"[DELEGATION] Worker executing web_search: '{query or url}'")

                # ── SearXNG search (local Docker service) ──────────────────
                # Searxng runs via Docker on the worker (default: Port 8080)
                # Format=json returns structured results
                # _searxng_url attribute can be set by DiagTab (configurable port)
                SEARXNG_URL = (payload.get("searxng_url")
                               or getattr(self, "_searxng_url", None)
                               or "http://localhost:8080")
                searxng_results = None

                if query:
                    # Search via Searxng JSON API
                    try:
                        search_url = (
                            f"{SEARXNG_URL}/search"
                            f"?q={urllib.parse.quote(query)}"
                            f"&format=json&language=de&time_range=&safesearch=0"
                        )
                        req = urllib.request.Request(
                            search_url,
                            headers={"User-Agent": "LyraWorker/1.0",
                                     "Accept": "application/json"})
                        with urllib.request.urlopen(req, timeout=15) as r:
                            data = json.loads(r.read().decode("utf-8"))
                        results = data.get("results", [])[:5]  # Top-5 hits
                        if results:
                            # Build compact result snippet for Ollama
                            snippets = []
                            for i, res in enumerate(results, 1):
                                title   = res.get("title", "")
                                snippet = res.get("content", "")
                                src_url = res.get("url", "")
                                snippets.append(f"{i}. {title}\n   {snippet}\n   ({src_url})")
                            searxng_results = "\n\n".join(snippets)
                            self.log(f"[DELEGATION] SearXNG: {len(results)} results for '{query}'")
                        else:
                            self.log(f"[Worker] Searxng: no results for '{query}'", "WARNING")
                    except Exception as sx_err:
                        self.log(f"[DELEGATION] SearXNG not reachable: {sx_err} "
                                 f"– falling back to URL fetch", "WARNING")

                # ── Direct URL fetch (if no query or Searxng failed) ─
                raw_text = ""
                fetch_url = url or ""

                if not searxng_results:
                    if not fetch_url and query:
                        return {"task_id": task_id, "status": "error",
                                "error_msg": (
                                    f"SearXNG returned no results and no direct URL provided. "
                                    f"Check Docker: docker ps | grep searxng"
                                )}

                    if fetch_url:
                        try:
                            req = urllib.request.Request(
                                fetch_url,
                                headers={"User-Agent": "LyraWorker/1.0",
                                         "Accept": "text/plain, text/html, */*"})
                            with urllib.request.urlopen(req, timeout=20) as r:
                                content_type = r.headers.get("Content-Type", "")
                                raw = r.read(30_000).decode("utf-8", errors="replace")
                            import re as _re
                            if "text/html" in content_type:
                                raw_text = _re.sub(r'<[^>]+>', ' ', raw)
                                raw_text = _re.sub(r'\s+', ' ', raw_text).strip()[:2000]
                            else:
                                raw_text = raw.strip()[:2000]
                        except Exception as fetch_err:
                            return {"task_id": task_id, "status": "error",
                                    "error_msg": f"URL fetch failed: {fetch_err}"}

                # ── Ollama summary ────────────────────────────────────
                context = searxng_results or raw_text or "(No data)"
                prompt_query = query or fetch_url

                summary = self._ollama_infer(
                    f"Question: {prompt_query}\n\n"
                    f"Search results:\n{context}\n\n"
                    f"Answer the question precisely in German (2-4 sentences).",
                    system=(
                        "You are a helpful assistant. "
                        "Answer questions based on the given search results. "
                        "Always answer in German."
                    ),
                    timeout=120
                )

                return {
                    "task_id": task_id,
                    "status": "success",
                    "result": {
                        "query":    query or fetch_url,
                        "source":   "searxng" if searxng_results else "direct_url",
                        "summary":  summary,
                        "snippets": searxng_results or raw_text[:500],
                    }
                }

            elif task_type == "batch_exec":
                # Execute shell command in WSL
                cmd = payload.get("cmd", "")
                if not cmd:
                    return {"task_id": task_id, "status": "error",
                            "error_msg": "No command specified"}
                proc = subprocess.run(
                    ["wsl", "bash", "-lc", cmd],
                    capture_output=True, text=True, timeout=120
                )
                output = (proc.stdout + proc.stderr).strip()[:3000]
                return {"task_id": task_id, "status": "success",
                        "result": {"returncode": proc.returncode, "output": output}}

            elif task_type == "summarize":
                text = payload.get("text", "")
                if not text:
                    return {"task_id": task_id, "status": "error",
                            "error_msg": "No text provided"}
                summary = self._ollama_infer(
                    f"Summarize the following text concisely:\n\n{text[:3000]}",
                    system="Answer only with the summary, without preamble."
                )
                return {"task_id": task_id, "status": "success",
                        "result": {"summary": summary}}

            elif task_type == "validate":
                content = payload.get("content", "")
                validate_type = payload.get("validate_type", "json")
                if validate_type == "json":
                    try:
                        json.loads(content)
                        return {"task_id": task_id, "status": "success",
                                "result": {"valid": True, "type": "json"}}
                    except json.JSONDecodeError as e:
                        return {"task_id": task_id, "status": "success",
                                "result": {"valid": False, "type": "json",
                                           "error": str(e)}}
                else:
                    # LLM-based validation
                    verdict = self._ollama_infer(
                        f"Check if the following text is syntactically correct "
                        f"({validate_type}):\n\n{content[:2000]}\n\n"
                        "Answer with: VALID or INVALID and a brief reason."
                    )
                    return {"task_id": task_id, "status": "success",
                            "result": {"verdict": verdict}}

            else:
                return {"task_id": task_id, "status": "error",
                        "error_msg": f"Unknown task type: {task_type}"}

        except subprocess.TimeoutExpired:
            return {"task_id": task_id, "status": "error",
                    "error_msg": "Timeout during execution"}
        except Exception as e:
            return {"task_id": task_id, "status": "error", "error_msg": str(e)}

    def _poll_loop(self):
        """Main loop: polls head, accepts tasks, executes, sends result."""
        self.log(f"[Worker] Poll loop started ({self.role} | Model: {self.model})", "SUCCESS")
        self.log(f"[Worker] LYRA head: {self._head_url('/tasks')}")
        consecutive_fails = 0

        while not self._stop.is_set():
            try:
                data = self._get("/tasks", timeout=8)
                if data is None:
                    consecutive_fails += 1
                    if consecutive_fails % 6 == 1:   # every ~42s warn
                        self.log(
                            f"[Worker] Head not reachable ({consecutive_fails}x) – "
                            f"waiting for {self._head_url('')}", "WARNING")
                    time.sleep(self.poll)
                    continue

                consecutive_fails = 0
                tasks = data.get("tasks", [])

                if not tasks:
                    time.sleep(self.poll)
                    continue

                # Take first suitable task (FIFO)
                # Junior: only simple tasks, Senior: all tasks
                supported = ["web_search", "batch_exec", "summarize", "validate"]
                task = next(
                    (t for t in tasks if t.get("type") in supported), None
                )
                if task is None:
                    time.sleep(self.poll)
                    continue

                self.log(f"[Worker] Task taken: {task['task_id']} ({task['type']})", "INFO")

                result_data = self._execute_task(task)
                posted = self._post("/result", result_data, timeout=30)

                # Also store result locally so GET /result/<id> works from outside
                if self._local_srv is not None:
                    tid = result_data.get("task_id", task.get("task_id", "?"))
                    result_data["stored_at"] = time.time()
                    with self._local_srv._lock:
                        self._local_srv._results[tid] = result_data
                        if len(self._local_srv._results) > 100:
                            oldest = list(self._local_srv._results.keys())[0]
                            del self._local_srv._results[oldest]

                status_icon = "✓" if result_data["status"] == "success" else "✗"
                detail = ""
                if result_data["status"] == "error":
                    detail = f" – {result_data.get('error_msg', '?')[:80]}"
                elif result_data["status"] == "success":
                    r = result_data.get("result", {})
                    detail = f" – {str(r)[:80]}"

                if posted and posted.get("integrated"):
                    self.log(
                        f"[DELEGATION] {status_icon} Task {task['task_id']} "
                        f"({task['type']}) {result_data['status']}{detail}", "SUCCESS")
                else:
                    self.log(f"[DELEGATION] Result transmission failed!", "WARNING")

            except Exception as e:
                self.log(f"[Worker] Poll loop error: {e}", "WARNING")
                time.sleep(self.poll)

        self.log("[Worker] Poll loop ended.", "INFO")

    def start(self):
        """Starts the poll loop in a background daemon thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def check_head_reachable(self, timeout: int = 5) -> bool:
        """Returns True if the LYRA head is reachable."""
        result = self._get("/health", timeout=timeout)
        return result is not None and result.get("status") == "ok"

# ══════════════════════════════════════════════════════════════════════════════
# DELEGATE_TO_WORKER TOOL
# LYRA calls this tool to send tasks synchronously to the LyraHeadServer.
# ══════════════════════════════════════════════════════════════════════════════

DELEGATE_TOOL_JS = r"""
/**
 * delegate_to_worker – LYRA Custom Tool
 *
 * Sends a task to the LyraHeadServer (Port 18790) and waits for the result.
 * LYRA should use this tool for ALL simple/repetitive tasks:
 *   web_search, batch_exec, summarize, validate
 *
 * @param {string} task_type  - "web_search" | "batch_exec" | "summarize" | "validate"
 * @param {object} payload    - e.g. {"query": "Weather Zurich"} or {"cmd": "ls -la"}
 * @returns {object}          - {"status": "success"|"error", "result": {...}}
 */

const HEAD_SERVER = "http://127.0.0.1:18790";
const POLL_INTERVAL_MS = 5000;
const MAX_WAIT_MS = 180000;  // 3 minutes

async function delegate_to_worker(task_type, payload) {
    // Generate task ID
    const task_id = Math.random().toString(36).substr(2, 8);

    // Send task to head server
    let postResp;
    try {
        postResp = await fetch(`${HEAD_SERVER}/tasks`, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ task_id, type: task_type, payload })
        });
        if (!postResp.ok) {
            return { status: "error", error_msg: `POST /tasks HTTP ${postResp.status}` };
        }
    } catch (e) {
        return { status: "error", error_msg: `Head server not reachable: ${e.message}` };
    }

    // Poll for result (max. MAX_WAIT_MS)
    const deadline = Date.now() + MAX_WAIT_MS;
    while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, POLL_INTERVAL_MS));
        try {
            const r = await fetch(`${HEAD_SERVER}/results`);
            if (!r.ok) continue;
            const data = await r.json();
            const results = data.results || [];
            const match = results.find(x => x.task_id === task_id);
            if (match) {
                return {
                    status: match.status,
                    result: match.result || {},
                    error_msg: match.error_msg || ""
                };
            }
        } catch (_) { /* keep waiting */ }
    }
    return { status: "error", error_msg: `Timeout: No result after ${MAX_WAIT_MS/1000}s` };
}

// OpenClaw Tool Export
module.exports = {
    name: "delegate_to_worker",
    description: (
        "Delegates a task to a worker node (Junior/Senior) in the LYRA network. "
        + "Use this tool for: web_search (search queries), batch_exec (shell commands), "
        + "summarize (summarize text), validate (check syntax). "
        + "Returns the worker's result. Timeout: 180s."
    ),
    parameters: {
        type: "object",
        properties: {
            task_type: {
                type: "string",
                enum: ["web_search", "batch_exec", "summarize", "validate"],
                description: "Type of task"
            },
            payload: {
                type: "object",
                description: (
                    "Task data. "
                    + "web_search: {query: '...'} or {url: '...'}. "
                    + "batch_exec: {cmd: 'bash command'}. "
                    + "summarize: {text: '...'}. "
                    + "validate: {content: '...', validate_type: 'json'|'python'|'text'}."
                )
            }
        },
        required: ["task_type", "payload"]
    },
    execute: async (args) => delegate_to_worker(args.task_type, args.payload)
};
"""




# ══════════════════════════════════════════════════════════════════════════════
# OpenClawOperations  –  all non-GUI system operations
# (check_*, install_*, setup_*, run_powershell, WSL, Ollama, gateway)
# ══════════════════════════════════════════════════════════════════════════════

class OpenClawOperations:
    """
    All non-GUI operational methods: system checks, installations,
    Ollama management, gateway control, WSL, worker infrastructure.
    Used by OpenClawWinInstaller as a mixin / parent.
    log_fn and run_powershell are assumed to exist on self (provided by installer).
    """

    def _log_hardware_info(self):
        """Reads CPU, RAM, drives, GPU via WMI and logs them."""
        try:
            # CPU
            r = self.run_powershell(
                "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name"
            )
            cpu = r["stdout"].strip() or "Unknown"

            # RAM total + free (FreePhysicalMemory is in KB!)
            r2 = self.run_powershell(
                "$os = Get-CimInstance Win32_OperatingSystem;"
                "$cs = Get-CimInstance Win32_ComputerSystem;"
                "[string][math]::Round($cs.TotalPhysicalMemory/1GB,1) + ' GB total, ' +"
                "[string][math]::Round($os.FreePhysicalMemory/1KB/1KB,1) + ' GB free'"
            )
            ram = r2["stdout"].strip() or "Unknown"

            # Drives (only local, not network) – compatible with PS 5.1
            r3 = self.run_powershell(
                "(Get-PSDrive -PSProvider FileSystem | "
                "Where-Object {$_.Root -match '^[A-Z]:\\\\'} | "
                "ForEach-Object { $_.Name + ': ' + "
                "[string][math]::Round(($_.Used)/1GB,0) + '/' + "
                "[string][math]::Round(($_.Used+$_.Free)/1GB,0) + 'GB' }) -join '  '"
            )
            drives = r3["stdout"].strip() or "Unknown"

            # GPU
            r4 = self.run_powershell(
                "(Get-CimInstance Win32_VideoController | Select-Object -First 1).Name"
            )
            gpu = r4["stdout"].strip() or "Unknown"

            # AVX2 — critical for Ollama LLM inference
            # Without AVX2, no model runs reasonably fast
            # PRIMARY: WSL /proc/cpuinfo (reliable), not platform.processor()
            try:
                r_avx = self._wsl_cmd("grep -m1 'avx2' /proc/cpuinfo 2>/dev/null")
                has_avx2 = "avx2" in r_avx.get("stdout", "").lower()
                avx2_src = "WSL"
            except Exception:
                has_avx2 = False
                avx2_src = "unknown"
            avx2_str = f"✓ AVX2 present ({avx2_src})" if has_avx2 else f"✗ NO AVX2 ({avx2_src}) – only 0.5b model possible!"

            self.log("─" * 50)
            self.log(f"CPU:      {cpu[:70]}")
            self.log(f"AVX2:     {avx2_str}")
            self.log(f"RAM:      {ram}")
            self.log(f"Disk:     {drives[:70]}")
            self.log(f"GPU:      {gpu[:70]}")
            self.log("─" * 50)
        except Exception as e:
            self.log(f"Hardware info error: {e}", "DEBUG")

    # ──────────────────────────────────────────────────────────────────
    # DOWNLOAD HELPER (v6) – multiple mirrors, speed logging
    # ──────────────────────────────────────────────────────────────────

    def _download_with_fallback(self, urls, dest_path, label="File"):
        """
        Tries URLs in sequence. Returns True if download successful.
        Logs speed and errors. urls: list[str] or str.
        """
        if isinstance(urls, str):
            urls = [urls]
        for url in urls:
            try:
                self.log(f"  Download: {url[:90]}...")
                t0 = time.time()
                urllib.request.urlretrieve(url, dest_path)
                elapsed = time.time() - t0
                size_mb = os.path.getsize(dest_path) / 1024 / 1024
                speed   = size_mb / elapsed if elapsed > 0 else 0
                self.log(f"  {label}: {size_mb:.1f} MB in {elapsed:.0f}s "
                         f"({speed:.1f} MB/s)", "SUCCESS")
                return True
            except Exception as e:
                self.log(f"  {label} error [{url[:60]}]: {e}", "WARNING")
                try:
                    os.remove(dest_path)
                except:
                    pass
        self.log(f"  {label}: all URLs failed!", "ERROR")
        return False

    def _check_url(self, url, timeout=8):
        """Returns True if URL is reachable (HTTP 2xx/3xx)."""
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "OpenClawWinInstaller/6"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status < 400
        except:
            return False

    def msiexec_with_watch(self, msi_path, extra_args="", timeout=600, label="MSI"):
        """
        Starts msiexec /i without blocking /wait.
        Monitors the msiexec process and waits until it finishes
        (or timeout expires). Slow machines are not aborted.
        """
        cmd = f'msiexec /i "{msi_path}" /quiet /norestart {extra_args}'
        self.log(f"  Starting {label} installation (monitored, max {timeout}s)...")
        proc = subprocess.Popen(cmd, shell=True)
        t0 = time.time()
        dot_interval = 30   # every 30s a heartbeat
        last_dot = t0
        while True:
            ret = proc.poll()
            if ret is not None:
                self.log(f"  {label}: Installer finished (Code {ret})")
                return ret == 0 or ret == 3010  # 3010 = restart required, but OK
            elapsed = time.time() - t0
            if elapsed > timeout:
                self.log(f"  {label}: Timeout after {timeout}s – checking if already installed",
                         "WARNING")
                return True   # DON'T kill – installer might still be running on slow PCs!
            if time.time() - last_dot > dot_interval:
                self.log(f"  {label}: running for {int(elapsed)}s – please wait...")
                last_dot = time.time()
            time.sleep(3)

    def _run_installer_with_watch(self, exe_path, args, timeout=1200, label="Installer",
                                  watch_proc_names=None):
        """
        Starts an EXE installer asynchronously (no --wait).
        Monitors process list for installer-typical processes.
        Waits until ALL watched processes are finished or timeout.
        Slow machines are NOT aborted prematurely.
        """
        if watch_proc_names is None:
            watch_proc_names = ["vs_installer", "vs_bootstrapper", "vctip",
                                "setup", "msiexec", "vs_buildtools"]
        cmd = f'"{exe_path}" {args}'
        self.log(f"  Starting {label} (asynchronous, monitored up to {timeout//60} min.)...")
        if exe_path:   # Empty = watch only (process was already started externally)
            subprocess.Popen(cmd, shell=True)
            time.sleep(12)   # Bootstrapper + child processes need ~10s to start
        else:
            self.log(f"  Watch-only mode – waiting for running processes...")
            time.sleep(5)

        t0 = time.time()
        last_log = t0
        LOG_INTERVAL = 45

        # Initial stabilization pause: wait until processes actually appear in process explorer
        # On slow machines this can take additional seconds
        stabilize_end = time.time() + 20
        while time.time() < stabilize_end:
            r = self.run_powershell(
                "Get-Process | Where-Object { "
                + " -or ".join(f"$_.Name -like '*{p}*'" for p in watch_proc_names)
                + " } | Select-Object -ExpandProperty Name | Select-Object -First 1"
            )
            if r["stdout"].strip():
                break   # Process visible → start watch loop
            time.sleep(3)

        t0 = time.time()
        last_log = t0
        LOG_INTERVAL = 45

        while True:
            elapsed = int(time.time() - t0)

            # Check if installer processes are still running
            r = self.run_powershell(
                "Get-Process | Where-Object { "
                + " -or ".join(f"$_.Name -like '*{p}*'" for p in watch_proc_names)
                + " } | Select-Object -ExpandProperty Name | Join-String -Separator ', '"
            )
            running = r["stdout"].strip()

            if not running:
                self.log(f"  {label}: Installer processes finished after {elapsed}s", "SUCCESS")
                return True

            if time.time() - last_log > LOG_INTERVAL:
                self.log(f"  {label}: running for {elapsed}s [{running[:60]}] – please wait...")
                last_log = time.time()

            if elapsed > timeout:
                self.log(f"  {label}: Timeout after {timeout}s – installation may still be running",
                         "WARNING")
                self.log(f"  {label}: Continuing (installer might have finished)", "WARNING")
                return True   # Don't abort – on slow machines often OK

            time.sleep(6)

    def _strip_ansi(self, text: str) -> str:
        """Removes ANSI escape sequences and terminal control codes from WSL output."""
        import re
        # Escape sequences: ESC[ ... m, ESC[?25l, ESC[1G, ESC[K etc.
        ansi_re = re.compile(r'\x1b\[[0-9;?]*[a-zA-Z]|\x1b\([A-Z]|\x1b[=>]|\r')
        return ansi_re.sub('', text)

    def _is_ollama_progress(self, line: str) -> bool:
        """Detects Ollama progress lines (bars, %, pulling etc.)."""
        markers = ["▕", "▏", "pulling ", "verifying sha", "writing manifest",
                   "pulling manifest", "#=#", "##O", "0.0%", "100.0%"]
        lo = line.lower()
        return any(m in line for m in markers) or (
            "%" in line and any(c in line for c in ["▕", "KB/s", "MB/s", "GB/s", "MB ", "GB "])
        )

    def _format_progress_line(self, line: str) -> str:
        """Shortens Ollama progress lines to a readable summary."""
        import re
        # Extract percentage if present
        m = re.search(r'(\d+\.?\d*)\s*%', line)
        pct = m.group(1) if m else "?"
        # Extract file size if present
        sz = re.search(r'([\d.]+\s*[KMGT]B)', line)
        size_str = f" [{sz.group(1)}]" if sz else ""
        # Layer name
        layer = re.search(r'pulling\s+([a-f0-9]{8,})', line.lower())
        layer_str = f" {layer.group(1)[:12]}" if layer else ""
        return f"  ↳ {pct}%{layer_str}{size_str}"

    # ──────────────────────────────────────────────────────────────────
    # POWERSHELL RUNNER (short commands, blocking)
    # ──────────────────────────────────────────────────────────────────

    def run_powershell(self, command, timeout=120):
        try:
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace"
            )
            out, err = proc.communicate(timeout=timeout)
            return {"stdout": out.strip(), "stderr": err.strip(), "returncode": proc.returncode}
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"stdout": "", "stderr": "TIMEOUT", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    # ──────────────────────────────────────────────────────────────────
    # POWERSHELL RUNNER (long commands, live streaming)
    # ──────────────────────────────────────────────────────────────────

    def run_powershell_live(self, command, timeout=480, prefix="    ", env_extra=None):
        stdout_lines, stderr_lines = [], []
        try:
            env = os.environ.copy()
            if env_extra:
                env.update(env_extra)

            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace",
                env=env
            )
            q = queue_module.Queue()

            def _reader(pipe, tag):
                try:
                    for line in pipe:
                        q.put((tag, line.rstrip()))
                except:
                    pass
                finally:
                    q.put((tag, None))

            threading.Thread(target=_reader, args=(proc.stdout, "out"), daemon=True).start()
            threading.Thread(target=_reader, args=(proc.stderr, "err"), daemon=True).start()

            done, t0 = 0, time.time()
            while done < 2:
                if time.time() - t0 > timeout:
                    proc.kill()
                    self.log(f"{prefix}TIMEOUT after {timeout}s", "WARNING")
                    break
                try:
                    tag, line = q.get(timeout=0.25)
                except queue_module.Empty:
                    continue
                if line is None:
                    done += 1
                    continue
                s = line.strip()
                if not s:
                    continue
                lo = s.lower()
                # npm warn + npm notice go to stderr, but are not errors
                is_npm_warn_or_notice = "npm warn" in lo or "npm notice" in lo or "npm deprecated" in lo
                if (tag == "err" and not is_npm_warn_or_notice) or \
                   ("npm error" in lo and not is_npm_warn_or_notice):
                    lvl = "ERROR";   stderr_lines.append(s)
                elif "npm notice" in lo:
                    lvl = "INFO";    stdout_lines.append(s)
                elif is_npm_warn_or_notice or any(w in lo for w in ["warn", "deprecated"]):
                    lvl = "WARNING"; stdout_lines.append(s)
                elif any(w in lo for w in ["added", "changed", "audited", "found",
                                            "up to date", "installed"]):
                    lvl = "SUCCESS"; stdout_lines.append(s)
                else:
                    lvl = "INFO";   stdout_lines.append(s)
                self.log(f"{prefix}{s[:170]}", lvl)

            proc.wait()
            return {
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines),
                "returncode": proc.returncode
            }
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    # ──────────────────────────────────────────────────────────────────
    # HELPER METHODS
    # ──────────────────────────────────────────────────────────────────

    def _refresh_path(self):
        """Updates PATH in the current PowerShell session."""
        self.run_powershell(
            "$env:Path = [System.Environment]::GetEnvironmentVariable('Path','Machine')"
            " + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')"
        )
        # Also update in the Python process itself
        r = self.run_powershell(
            "[System.Environment]::GetEnvironmentVariable('Path','Machine')"
            " + ';' + [System.Environment]::GetEnvironmentVariable('Path','User')"
        )
        if r["stdout"]:
            os.environ["PATH"] = r["stdout"]

    def _npm_prefix(self):
        r = self.run_powershell("npm prefix -g")
        return r["stdout"].strip() if r["stdout"] else os.path.join(os.environ["APPDATA"], "npm")

    def check_admin(self):
        r = self.run_powershell(
            "([Security.Principal.WindowsPrincipal]"
            " [Security.Principal.WindowsIdentity]::GetCurrent())"
            ".IsInRole([Security.Principal.WindowsBuiltInRole] 'Administrator')"
        )
        return "True" in r["stdout"]

    # ──────────────────────────────────────────────────────────────────
    # SYSTEM PREPARATIONS (NEW in v2)
    # ──────────────────────────────────────────────────────────────────

    def prepare_system(self):
        """Enables Windows Long Paths and ExecutionPolicy – once before everything else."""
        self.log("  Enabling Windows Long Paths (Registry)...")
        self.run_powershell(
            "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\FileSystem'"
            " -Name 'LongPathsEnabled' -Value 1 -ErrorAction SilentlyContinue"
        )
        self.run_powershell("git config --global core.longpaths true 2>$null")
        self.log("  Long Paths enabled", "SUCCESS")

        self.log("  Setting PowerShell ExecutionPolicy to RemoteSigned...")
        self.run_powershell(
            "Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope LocalMachine -Force"
            " -ErrorAction SilentlyContinue"
        )
        self.log("  ExecutionPolicy OK", "SUCCESS")

    def configure_npm(self):
        """Sets npm options: HTTPS registry, no strict-ssl, node-gyp python."""
        self.log("  Optimizing npm configuration...")
        self.run_powershell("npm config set registry https://registry.npmjs.org/ 2>$null")
        self.run_powershell("npm config set strict-ssl false 2>$null")
        self.run_powershell("npm config set fetch-retry-mintimeout 20000 2>$null")
        self.run_powershell("npm config set fetch-retry-maxtimeout 120000 2>$null")
        self.run_powershell("npm config set fetch-retries 5 2>$null")
        # Set python for node-gyp, if available
        py = shutil.which("python") or shutil.which("python3")
        if py:
            self.run_powershell(f'npm config set python "{py}" 2>$null')
            self.log(f"  node-gyp Python: {py}", "SUCCESS")
        self.log("  npm configuration completed", "SUCCESS")

    # ──────────────────────────────────────────────────────────────────
    # WINDOWS APP RUNTIME (mandatory dependency for winget)
    # If missing, Add-AppxPackage fails with HRESULT 0x80073CF3
    # ──────────────────────────────────────────────────────────────────

    def check_windows_app_runtime(self):
        """Returns the highest installed WinAppRuntime-1.x version or None."""
        r = self.run_powershell(
            "Get-AppxPackage -Name 'Microsoft.WindowsAppRuntime.1.*'"
            " -ErrorAction SilentlyContinue"
            " | Sort-Object Version -Descending"
            " | Select-Object -First 1 -ExpandProperty Version"
        )
        return r["stdout"].strip() if r["stdout"].strip() else None

    def install_windows_app_runtime(self):
        """
        Installs Microsoft.WindowsAppRuntime 1.8 (minimum requirement for winget 1.27+).
        Download via official Aka.ms redirect – no GitHub needed.
        """
        self.log("  Installing Windows App Runtime 1.8 (winget dependency)...")

        # Official installer URL for WindowsAppRuntime 1.8 (Redist package)
        # Contains: Main + DDLM + Framework + Singleton in one EXE
        urls = [
            # Redirect from Microsoft – always latest 1.8 patch version
            "https://aka.ms/windowsappruntimeinstall-x64",
            # Direct fallback to known stable version
            "https://github.com/microsoft/WindowsAppSDK/releases/download/"
            "v1.8.250402001/WindowsAppRuntimeInstall-x64.exe",
        ]

        tmp = os.path.join(tempfile.gettempdir(), "WindowsAppRuntimeInstall-x64.exe")
        downloaded = False
        for url in urls:
            try:
                self.log(f"  Download: {url[:80]}...")
                urllib.request.urlretrieve(url, tmp)
                downloaded = True
                break
            except Exception as e:
                self.log(f"  Download error: {e}", "WARNING")

        if not downloaded:
            self.log("  Windows App Runtime download failed!", "WARNING")
            return False

        try:
            ret = subprocess.run(
                f'"{tmp}" --quiet --force',
                shell=True, timeout=300
            )
            try:
                os.remove(tmp)
            except:
                pass
            time.sleep(4)

            ver = self.check_windows_app_runtime()
            if ver:
                self.log(f"  Windows App Runtime installed: {ver}", "SUCCESS")
                return True
            else:
                # Even returncode 0 without registry entry = OK (already included)
                if ret.returncode in (0, 3010):   # 3010 = restart required
                    self.log("  Windows App Runtime installed (restart may be required)", "SUCCESS")
                    return True
                self.log(f"  Installation unclear (Code {ret.returncode})", "WARNING")
                return False
        except Exception as e:
            self.log(f"  Windows App Runtime error: {e}", "WARNING")
            return False

    # ──────────────────────────────────────────────────────────────────
    # WINGET
    # ──────────────────────────────────────────────────────────────────

    def check_winget(self):
        r = self.run_powershell("winget --version 2>$null")
        return bool(r["stdout"] and "v" in r["stdout"].lower())

    def _resolve_winget_urls(self):
        """
        Determines valid download URLs for winget via GitHub API.
        Returns list of (bundle_url, license_url) tuples, sorted by priority.
        Falls back to hardcoded known URLs if API unreachable.
        """
        bundle_name = "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe.msixbundle"
        lic_name    = "License1.xml"
        base        = "https://github.com/microsoft/winget-cli/releases"
        results     = []

        # Attempt 1: GitHub API – get latest release
        try:
            api_url = "https://api.github.com/repos/microsoft/winget-cli/releases/latest"
            req = urllib.request.Request(api_url,
                headers={"User-Agent": "OpenClawWinInstaller/4", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "")
            assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
            bundle_url = assets.get(bundle_name, "")
            lic_url    = next((v for k, v in assets.items() if k.endswith("_License1.xml")), "")
            if bundle_url:
                self.log(f"  GitHub API: {tag} found", "SUCCESS")
                results.append((bundle_url, lic_url or None))
        except Exception as e:
            self.log(f"  GitHub API unreachable: {e}", "WARNING")

        # Attempt 2: Known working release tags as fallback
        # (sorted: newest first)
        for tag in ["v1.9.25200", "v1.9.2411", "v1.8.1911", "v1.7.11261"]:
            bundle_url = f"{base}/download/{tag}/{bundle_name}"
            lic_url    = f"{base}/download/{tag}/{tag.lstrip('v')}_License1.xml"
            results.append((bundle_url, lic_url))

        # Attempt 3: /latest/download as last resort
        results.append((f"{base}/latest/download/{bundle_name}", None))
        return results

    def install_winget(self):
        self.log("  Installing winget (Microsoft App Installer)...")

        # ── Step A: Ensure Windows App Runtime ──────────────────────────────
        # Without this framework, Add-AppxPackage fails with 0x80073CF3
        war_ver = self.check_windows_app_runtime()
        if war_ver:
            self.log(f"  Windows App Runtime present: {war_ver}", "SUCCESS")
        else:
            self.log("  Windows App Runtime missing – installing first...")
            if not self.install_windows_app_runtime():
                self.log("  Windows App Runtime installation failed – winget install may fail",
                         "WARNING")

        # ── Step B: Register AppxPackage ──────────────────────
        self.log("  Registering DesktopAppInstaller AppxPackage...")
        self.run_powershell(
            "Add-AppxPackage -RegisterByFamilyName"
            " -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
            " -ErrorAction SilentlyContinue",
            timeout=120
        )
        time.sleep(3)
        if self.check_winget():
            self.log("  winget registered via AppxPackage", "SUCCESS")
            return True

        # ── Step C: msixbundle from GitHub ──────────────────────────
        self.log("  Downloading winget msixbundle from GitHub...")
        try:
            winget_bundle_urls = self._resolve_winget_urls()
            installer = os.path.join(tempfile.gettempdir(), "winget-installer.msixbundle")
            lic_file  = os.path.join(tempfile.gettempdir(), "winget-license.xml")
            downloaded = False

            for bundle_url, lic_url in winget_bundle_urls:
                try:
                    self.log(f"  Bundle:  {bundle_url[:90]}...")
                    urllib.request.urlretrieve(bundle_url, installer)
                    if lic_url:
                        try:
                            urllib.request.urlretrieve(lic_url, lic_file)
                        except:
                            lic_file = None
                    downloaded = True
                    break
                except Exception as e:
                    self.log(f"  Download error: {e}", "WARNING")

            if downloaded:
                if lic_file and os.path.isfile(lic_file):
                    ps_cmd = (f"Add-AppxProvisionedPackage -Online"
                              f" -PackagePath '{installer}'"
                              f" -LicensePath '{lic_file}'"
                              f" -ErrorAction SilentlyContinue")
                else:
                    ps_cmd = (f"Add-AppxPackage -Path '{installer}'"
                              f" -ErrorAction SilentlyContinue")
                self.run_powershell(ps_cmd, timeout=300)
                for f in [installer, lic_file]:
                    try:
                        if f and os.path.isfile(str(f)):
                            os.remove(f)
                    except:
                        pass
                time.sleep(5)
                self._refresh_path()
                if self.check_winget():
                    self.log("  winget installed via msixbundle", "SUCCESS")
                    return True
        except Exception as e:
            self.log(f"  winget download error: {e}", "WARNING")

        # ── Step D: Try Microsoft Store update ────────────────────────────────
        self.log("  Trying to update winget via Microsoft Store...")
        self.run_powershell(
            "Get-AppxPackage -Name 'Microsoft.DesktopAppInstaller'"
            " -ErrorAction SilentlyContinue"
            " | ForEach-Object { Add-AppxPackage -RegisterByFamilyName"
            "   -MainPackage $_.PackageFullName -ErrorAction SilentlyContinue }",
            timeout=120
        )
        time.sleep(3)
        if self.check_winget():
            self.log("  winget activated via Store update", "SUCCESS")
            return True

        self.log("  winget not installable – using direct downloads as fallback", "WARNING")
        self.log("  Tip: Open the Microsoft Store and update 'App Installer'", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # NODE.JS
    # ──────────────────────────────────────────────────────────────────

    def check_node(self):
        r = self.run_powershell("node -v 2>$null")
        if r["stdout"].startswith("v"):
            ver = r["stdout"].strip()
            try:
                major = int(ver.replace("v", "").split(".")[0])
            except:
                major = 0
            return ver, major >= 18  # >= 18 is enough for OpenClaw
        return None, False

    def install_node(self):
        self.log("  Installing Node.js LTS v22...")
        if self.check_winget():
            r = self.run_powershell(
                "winget install OpenJS.NodeJS.LTS --accept-package-agreements --silent",
                timeout=600
            )
            if r["returncode"] == 0:
                self._refresh_path()
                time.sleep(6)
                if self.check_node()[0]:
                    return True

        self.log("  Downloading Node.js v22 MSI (multiple sources)...")
        node_ver = "22.14.0"
        msi_name = f"node-v{node_ver}-x64.msi"
        msi_path = os.path.join(tempfile.gettempdir(), msi_name)
        node_urls = [
            f"https://nodejs.org/dist/v{node_ver}/{msi_name}",
            f"https://nodejs.org/download/release/v{node_ver}/{msi_name}",
            f"https://registry.npmjs.org/node/-/{msi_name}",       # CDN fallback
        ]
        if self._download_with_fallback(node_urls, msi_path, "Node.js MSI"):
            ok = self.msiexec_with_watch(msi_path, timeout=600, label="Node.js")
            try:
                os.remove(msi_path)
            except:
                pass
            self._refresh_path()
            time.sleep(8)
            if self.check_node()[0]:
                return True
            if ok:
                # MSI returned 3010 (restart required) – continue anyway
                self.log("  Node.js installed (restart may be required)", "WARNING")
                return True
        return False

    # ──────────────────────────────────────────────────────────────────
    # GIT
    # ──────────────────────────────────────────────────────────────────

    def check_git(self):
        r = self.run_powershell("git --version 2>$null")
        return (r["stdout"].strip()
                if r["stdout"] and "git version" in r["stdout"].lower()
                else None)

    def install_git(self):
        self.log("  Installing Git for Windows...")
        if self.check_winget():
            r = self.run_powershell(
                "winget install --id Git.Git"
                " --accept-package-agreements --accept-source-agreements --silent",
                timeout=600
            )
            if r["returncode"] in (0, -1977334255):
                self._refresh_path()
                time.sleep(5)
                if self.check_git():
                    return True

        self.log("  Downloading Git installer (multiple sources)...")
        git_ver  = "2.48.1"
        git_name = f"Git-{git_ver}-64-bit.exe"
        git_urls = [
            # 1. GitHub Releases (primary)
            f"https://github.com/git-for-windows/git/releases/download/"
            f"v{git_ver}.windows.1/{git_name}",
            # 2. GitHub API – latest release (no hardcoded tag needed)
            "https://github.com/git-for-windows/git/releases/latest/download/"
            f"{git_name}",
            # 3. git-scm.com official redirect (stable, no 502)
            "https://git-scm.com/download/win",          # HTML page, not direct download
            # 4. SourceForge mirror
            f"https://sourceforge.net/projects/git-for-windows/files/latest/download",
            # 5. Portableapps.com CDN (fallback)
            f"https://github.com/git-for-windows/git/releases/download/"
            f"v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe",   # older, stable version
        ]

        git_path = os.path.join(tempfile.gettempdir(), git_name)
        # Only real EXE downloads (skip HTML pages)
        download_urls = [u for u in git_urls if not u.endswith("/win")]

        if self._download_with_fallback(download_urls, git_path, "Git Installer"):
            try:
                # Silent install: /VERYSILENT without /wait flag – process monitoring
                ok = self._run_installer_with_watch(
                    git_path,
                    "/VERYSILENT /NORESTART /NOCANCEL /SP-"
                    " /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS"
                    " /COMPONENTS=icons,ext\\reg\\shellhere,assoc,assoc_sh",
                    timeout=600,
                    label="Git",
                    watch_proc_names=["git-", "inno", "is-", "setup"]
                )
                try:
                    os.remove(git_path)
                except:
                    pass
                self._refresh_path()
                time.sleep(8)
                # Multiple attempts because PATH propagation can be slow
                for _ in range(3):
                    ver = self.check_git()
                    if ver:
                        self.log(f"  Git installed: {ver}", "SUCCESS")
                        return True
                    time.sleep(4)
                if ok:
                    self.log("  Git installed (PATH update after restart active)", "WARNING")
                    return True
            except Exception as e:
                self.log(f"  Git install error: {e}", "WARNING")

        self.log("  Git installation failed", "ERROR")
        self.log("  Manual: https://git-scm.com/download/win", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # CMAKE
    # ──────────────────────────────────────────────────────────────────

    def check_cmake(self):
        r = self.run_powershell("cmake --version 2>$null")
        return (r["stdout"].strip()
                if r["stdout"] and "cmake version" in r["stdout"].lower()
                else None)

    def install_cmake(self):
        self.log("  Installing CMake...")

        if self.check_winget():
            r = self.run_powershell(
                "winget install Kitware.CMake"
                " --accept-package-agreements --accept-source-agreements --silent",
                timeout=300
            )
            if r["returncode"] == 0:
                self._refresh_path()
                time.sleep(4)
                if self.check_cmake():
                    return True

        self.log("  Downloading CMake MSI installer...")
        try:
            cmake_ver = "3.31.6"
            url = (f"https://github.com/Kitware/CMake/releases/download/"
                   f"v{cmake_ver}/cmake-{cmake_ver}-windows-x86_64.msi")
            installer = os.path.join(tempfile.gettempdir(), "cmake-installer.msi")
            self.log(f"  Download: cmake-{cmake_ver}-windows-x86_64.msi")
            urllib.request.urlretrieve(url, installer)
            subprocess.run(
                f'msiexec /i "{installer}" /quiet /norestart ADD_CMAKE_TO_PATH=System',
                shell=True, timeout=300
            )
            try:
                os.remove(installer)
            except:
                pass
            self._refresh_path()
            time.sleep(5)
            if self.check_cmake():
                return True
        except Exception as e:
            self.log(f"  CMake download error: {e}", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # VISUAL C++ REDISTRIBUTABLE (NEW in v2)
    # ──────────────────────────────────────────────────────────────────

    def check_vcredist(self):
        """Checks if VC++ Redist 2015-2022 x64 is installed."""
        r = self.run_powershell(
            "Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X64"
            " -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Version"
        )
        if r["stdout"].strip():
            return r["stdout"].strip()
        # Alternative via WMI (slower, but more reliable)
        r2 = self.run_powershell(
            "Get-WmiObject -Class Win32_Product -ErrorAction SilentlyContinue"
            " | Where-Object { $_.Name -like '*Visual C++*2022*x64*'"
            " -or $_.Name -like '*Visual C++*2019*x64*' }"
            " | Select-Object -First 1 -ExpandProperty Name"
        )
        return r2["stdout"].strip() if r2["stdout"].strip() else None

    def install_vcredist(self):
        self.log("  Installing Visual C++ Redistributable 2015-2022 x64...")

        if self.check_winget():
            r = self.run_powershell(
                "winget install Microsoft.VCRedist.2015+.x64"
                " --accept-package-agreements --accept-source-agreements --silent",
                timeout=180
            )
            if r["returncode"] == 0:
                self.log("  VC++ Redistributable installed", "SUCCESS")
                return True

        # Direct download from Microsoft
        self.log("  Downloading VC++ Redistributable from Microsoft...")
        try:
            url = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            installer = os.path.join(tempfile.gettempdir(), "vc_redist.x64.exe")
            urllib.request.urlretrieve(url, installer)
            subprocess.run(
                f'"{installer}" /install /quiet /norestart',
                shell=True, timeout=180
            )
            try:
                os.remove(installer)
            except:
                pass
            time.sleep(3)
            self.log("  VC++ Redistributable installed", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"  VC++ download error: {e}", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # XPM – xPack Package Manager (NEW in v2)
    # Required by node-llama-cpp for the source build of llama.cpp
    # ──────────────────────────────────────────────────────────────────

    def check_xpm(self):
        r = self.run_powershell("xpm --version 2>$null")
        return r["stdout"].strip() if r["stdout"].strip() else None

    def install_xpm(self):
        self.log("  Installing xpm (xPack Package Manager)...")
        r = self.run_powershell_live("npm install -g xpm", timeout=180, prefix="    ")
        if r["returncode"] == 0:
            self._refresh_path()
            time.sleep(2)
            ver = self.check_xpm()
            if ver:
                self.log(f"  xpm {ver} installed", "SUCCESS")
                return True
        self.log("  xpm installation failed", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # NODE-GYP / PYTHON BUILD TOOLS (NEW in v2)
    # Required for native Node.js addons (node-llama-cpp, etc.)
    # ──────────────────────────────────────────────────────────────────

    def check_node_gyp(self):
        r = self.run_powershell("node-gyp --version 2>$null")
        return r["stdout"].strip() if r["stdout"].strip() and "v" in r["stdout"] else None

    def install_node_gyp(self):
        self.log("  Installing node-gyp (native addon build tool)...")
        r = self.run_powershell_live("npm install -g node-gyp", timeout=120, prefix="    ")
        if r["returncode"] == 0:
            self._refresh_path()
            self.log("  node-gyp installed", "SUCCESS")
            return True
        self.log("  node-gyp installation failed", "WARNING")
        return False

    def check_windows_build_tools(self):
        """Checks if MSVC Build Tools (cl.exe) are present."""
        r = self.run_powershell(
            "Get-Command cl.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source"
        )
        if r["stdout"].strip():
            return r["stdout"].strip()
        # Check Windows Build Tools via Registry
        r2 = self.run_powershell(
            "Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows Kits\\Installed Roots'"
            " -ErrorAction SilentlyContinue | Select-Object -ExpandProperty KitsRoot10"
        )
        return r2["stdout"].strip() if r2["stdout"].strip() else None

    def install_windows_build_tools(self):
        """
        Installs Microsoft C++ Build Tools (MSVC) for node-gyp.
        v6: NO --wait anymore (prevented 600s timeout abort on slow machines).
        Instead: asynchronous start + process monitoring until installer finishes.
        """
        self.log("  Installing Windows Build Tools (MSVC) for node-gyp...")
        self.log("  NOTE: This can take 20–40 minutes on slow machines – please wait!")

        # Method 1: winget (asynchronous, then process watch)
        if self.check_winget():
            self.log("  Trying winget (asynchronous)...")
            subprocess.Popen(
                'winget install Microsoft.VisualStudio.2022.BuildTools'
                ' --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools'
                ' --add Microsoft.VisualStudio.Component.Windows11SDK.22621'
                ' --includeRecommended"'
                ' --accept-package-agreements --accept-source-agreements --silent',
                shell=True
            )
            time.sleep(10)
            ok = self._run_installer_with_watch(
                "", "",  # exe_path empty – only watch
                timeout=2400,   # 40 min. on slow machines
                label="VS BuildTools (winget)",
                watch_proc_names=["vs_installer", "vs_bootstrapper", "vctip",
                                   "msiexec", "vs_buildtools", "setup"]
            )
            self._refresh_path()
            if self.check_windows_build_tools():
                self.log("  Windows Build Tools (MSVC) installed via winget", "SUCCESS")
                return True
            if ok:
                self.log("  Build tools may be installed (registry check failed)", "WARNING")
                return True

        # Method 2: Direct download – WITHOUT --wait, with process monitoring
        self.log("  Downloading VS Build Tools bootstrapper directly from Microsoft...")
        installer = os.path.join(tempfile.gettempdir(), "vs_buildtools.exe")
        bt_urls = [
            "https://aka.ms/vs/17/release/vs_buildtools.exe",
            "https://aka.ms/vs/16/release/vs_buildtools.exe",  # VS2019 fallback
        ]
        if not self._download_with_fallback(bt_urls, installer, "VS Build Tools"):
            self.log("  Build tools download failed", "WARNING")
            self.log("  Manual: https://aka.ms/vs/17/release/vs_buildtools.exe", "WARNING")
            return False

        # --quiet WITHOUT --wait → process spawns itself and exits immediately
        # _run_installer_with_watch takes over the actual waiting
        ok = self._run_installer_with_watch(
            installer,
            "--quiet --norestart"
            " --add Microsoft.VisualStudio.Workload.VCTools"
            " --add Microsoft.VisualStudio.Component.Windows11SDK.22621"
            " --includeRecommended",
            timeout=2400,   # 40 min. maximum
            label="VS Build Tools",
            watch_proc_names=["vs_installer", "vs_bootstrapper", "vctip",
                               "msiexec", "vs_buildtools"]
        )
        try:
            os.remove(installer)
        except:
            pass
        self._refresh_path()
        time.sleep(8)

        if self.check_windows_build_tools():
            self.log("  VS Build Tools installed", "SUCCESS")
            return True
        if ok:
            self.log("  VS Build Tools installed (restart may be required)", "SUCCESS")
            return True

        self.log("  Build tools installation failed", "WARNING")
        self.log("  Manual: https://aka.ms/vs/17/release/vs_buildtools.exe", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # WSL2
    # ──────────────────────────────────────────────────────────────────

    def check_wsl(self):
        """Returns (wsl_installed, ubuntu_present)."""
        # wsl --list --quiet on Windows 10 sometimes returns null bytes / empty output
        # So first check wsl.exe existence, then distribution list
        r = self.run_powershell(
            "wsl --list --verbose 2>$null"
        )
        out = r["stdout"].replace("\x00", "").strip()  # Remove null bytes
        if r["returncode"] == 0 and out:
            ubuntu_present = any(x in out.lower() for x in ["ubuntu", "debian"])
            return True, ubuntu_present

        # Fallback: Check WSL feature status
        r2 = self.run_powershell(
            "(Get-WindowsOptionalFeature -Online -FeatureName"
            " 'Microsoft-Windows-Subsystem-Linux' -ErrorAction SilentlyContinue).State"
        )
        wsl_feature = "Enabled" in r2.get("stdout", "")

        # Try wsl.exe directly
        r3 = self.run_powershell("wsl --status 2>$null")
        out3 = r3["stdout"].replace("\x00", "").lower()
        if r3["returncode"] == 0 or "default distribution" in out3:
            ubuntu3 = any(x in out3 for x in ["ubuntu", "debian"])
            return True, ubuntu3

        return wsl_feature, False

    def install_wsl(self):
        """Installs WSL2 with Ubuntu. Warns if restart required."""
        self.log("  Installing WSL2 + Ubuntu (default distribution)...")

        # Check if WSL already runs but Ubuntu missing (most common case)
        wsl_exists, _ = self.check_wsl()
        if wsl_exists:
            self.log("  WSL2 kernel present – installing only Ubuntu distribution...")
            # Method A: wsl --install -d Ubuntu (no kernel re-install)
            r_dist = self.run_powershell_live(
                "wsl --install --distribution Ubuntu --no-launch 2>&1",
                timeout=300, prefix="    "
            )
            if r_dist["returncode"] == 0 or "already installed" in (r_dist["stdout"] + r_dist["stderr"]).lower():
                self.log("  Ubuntu installed", "SUCCESS")
                return True
            # Method B: winget
            if self.check_winget():
                r2 = self.run_powershell(
                    "winget install Canonical.Ubuntu.2204"
                    " --accept-package-agreements --accept-source-agreements --silent",
                    timeout=300
                )
                if r2["returncode"] == 0:
                    self.log("  Ubuntu 22.04 installed via winget", "SUCCESS")
                    return True
            # Method C: Ubuntu via Microsoft Store (direct)
            self.log("  Trying Ubuntu directly from the Store...")
            self.run_powershell(
                "Add-AppxPackage -RegisterByFamilyName -MainPackage"
                " CanonicalGroupLimited.UbuntuonWindows_79rhkp1fndgsc"
                " -ErrorAction SilentlyContinue",
                timeout=120
            )
            time.sleep(5)
            _, ubuntu_now = self.check_wsl()
            if ubuntu_now:
                self.log("  Ubuntu installed", "SUCCESS")
                return True
            self.log("  Ubuntu could not be installed.", "WARNING")
            self.log("  Tip: Search for 'Ubuntu' in Microsoft Store and install", "WARNING")
            return False

        # Complete WSL installation (feature not active)
        self.log("  WSL2 feature not active – performing full installation...")

        # Method 1: wsl --install (Windows 10 2004+ / Windows 11)
        r = self.run_powershell_live(
            "wsl --install --distribution Ubuntu --no-launch 2>&1",
            timeout=600, prefix="    "
        )
        if r["returncode"] == 0:
            self.log("  WSL2 + Ubuntu installed", "SUCCESS")
            self.log("  NOTE: A restart is required!", "WARNING")
            return True

        # Method 2: Step by step (old Windows versions)
        self.log("  Trying manual WSL2 activation via DISM...")
        steps = [
            "dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart",
            "dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart",
        ]
        for s in steps:
            self.run_powershell(s, timeout=120)

        # Set WSL2 as default + kernel update
        self.log("  Downloading WSL2 Linux kernel update...")
        try:
            url = "https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi"
            installer = os.path.join(tempfile.gettempdir(), "wsl_update_x64.msi")
            urllib.request.urlretrieve(url, installer)
            subprocess.run(f'msiexec /i "{installer}" /quiet /norestart',
                           shell=True, timeout=180)
            try:
                os.remove(installer)
            except:
                pass
        except Exception as e:
            self.log(f"  WSL kernel update download error: {e}", "WARNING")

        self.run_powershell("wsl --set-default-version 2 2>$null")

        # Ubuntu from Store via winget
        if self.check_winget():
            r2 = self.run_powershell(
                "winget install Canonical.Ubuntu.2204"
                " --accept-package-agreements --accept-source-agreements --silent",
                timeout=300
            )
            if r2["returncode"] == 0:
                self.log("  Ubuntu 22.04 installed via winget", "SUCCESS")
                return True

        self.log("  WSL2 base feature activated – restart required!", "WARNING")
        self.log("  After restart: wsl --install --distribution Ubuntu", "WARNING")
        return False

    def _wsl_cmd(self, cmd, timeout=60):
        """Executes a command in WSL and returns result dict."""
        full = f'wsl bash -c "{cmd}" 2>&1'
        return self.run_powershell(full, timeout=timeout)

    def _wsl_cmd_live(self, cmd, timeout=300, prefix="    "):
        """
        Executes a command in WSL with live logging.
        Filters ANSI escape sequences and compresses Ollama progress bars.
        """
        stdout_lines, stderr_lines = [], []
        full_cmd = f'wsl bash -lc "{cmd}"'
        try:
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", full_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace"
            )
            q = queue_module.Queue()

            def _reader(pipe, tag):
                try:
                    for line in pipe:
                        q.put((tag, line.rstrip()))
                except:
                    pass
                finally:
                    q.put((tag, None))

            threading.Thread(target=_reader, args=(proc.stdout, "out"), daemon=True).start()
            threading.Thread(target=_reader, args=(proc.stderr, "err"), daemon=True).start()

            done, t0 = 0, time.time()
            last_progress_pct = -1   # Prevents spam of same percentage values

            while done < 2:
                if time.time() - t0 > timeout:
                    proc.kill()
                    self.log(f"{prefix}TIMEOUT after {timeout}s", "WARNING")
                    break
                try:
                    tag, line = q.get(timeout=0.25)
                except queue_module.Empty:
                    continue
                if line is None:
                    done += 1
                    continue

                # Remove ANSI codes
                clean = self._strip_ansi(line).strip()
                if not clean:
                    continue

                # Compress Ollama progress bars
                if self._is_ollama_progress(clean):
                    import re
                    m = re.search(r'(\d+)\.?\d*\s*%', clean)
                    pct = int(m.group(1)) if m else -1
                    # Only log at significant steps (every 10%) or at the end
                    if pct < 0 or pct == 100 or pct // 10 != last_progress_pct // 10:
                        self.log(self._format_progress_line(clean), "INFO")
                        last_progress_pct = pct
                    continue

                lo = clean.lower()
                is_npm_warn = "npm warn" in lo or "npm notice" in lo
                if (tag == "err" and not is_npm_warn) or ("npm error" in lo and not is_npm_warn):
                    lvl = "ERROR"
                elif is_npm_warn or any(w in lo for w in ["warn", "deprecated"]):
                    lvl = "WARNING"
                elif any(w in lo for w in ["error", "fatal", "failed", "errno"]):
                    lvl = "ERROR"
                elif any(w in lo for w in ["success", "installed", "complete", "done", "100%"]):
                    lvl = "SUCCESS"
                else:
                    lvl = "INFO"
                self.log(f"{prefix}{clean[:170]}", lvl)
                stdout_lines.append(clean)

            proc.wait()
            return {
                "stdout": "\n".join(stdout_lines),
                "stderr": "\n".join(stderr_lines),
                "returncode": proc.returncode
            }
        except Exception as e:
            self.log(f"{prefix}WSL error: {e}", "WARNING")
            return {"stdout": "", "stderr": str(e), "returncode": -1}

    # ──────────────────────────────────────────────────────────────────
    # OLLAMA IN WSL2
    # ──────────────────────────────────────────────────────────────────

    def check_ollama_wsl(self):
        """Returns True if ollama found in WSL."""
        r = self._wsl_cmd("which ollama 2>/dev/null && ollama --version 2>/dev/null | head -1")
        return bool(r["stdout"].strip() and "not found" not in r["stdout"].lower())

    def check_ollama_native(self):
        """Checks if Ollama is installed natively on Windows.
        Only for diagnostics – Ollama is used exclusively in WSL2."""
        r = self.run_powershell("ollama --version 2>$null")
        return bool(r["stdout"].strip() and "ollama" in r["stdout"].lower())

    def install_ollama_wsl(self):
        """
        Installs Ollama — Windows-native FIRST (fast, reliable),
        WSL as secondary option.
        v23: apt timeout was the core problem on the power machine — Windows path is better.
        """
        # ── Option A: Already natively installed? ─────────────────────
        r = self.run_powershell("ollama --version 2>$null")
        if r["returncode"] == 0 and r["stdout"].strip():
            self.log("  Ollama (Windows-native) already present  ✓", "SUCCESS")
            return True

        # ── Option B: WSL installation (short timeout) ──────────────
        self.log("  Trying WSL installation (90s timeout)...")
        r_wsl = self._wsl_cmd_live(
            "which curl 2>/dev/null || (apt-get install -y curl 2>/dev/null); "
            "curl -fsSL https://ollama.com/install.sh | sudo sh",
            timeout=90, prefix="    "
        )
        if r_wsl["returncode"] == 0 and self.check_ollama_wsl():
            self.log("  Ollama installed in WSL2  ✓", "SUCCESS")
            return True

        # ── Option C: Windows-native via winget ───────────────────────
        self.log("  WSL install failed – installing Ollama for Windows...", "WARNING")
        if self.check_winget():
            r_wg = self.run_powershell(
                "winget install Ollama.Ollama --accept-package-agreements --silent 2>&1",
                timeout=300
            )
            self._refresh_path()
            time.sleep(5)
            r2 = self.run_powershell("ollama --version 2>$null")
            if r2["returncode"] == 0:
                self.log("  Ollama Windows-native installed (winget)  ✓", "SUCCESS")
                return True

        # ── Option D: Direct download OllamaSetup.exe ─────────────────
        self.log("  Downloading OllamaSetup.exe...")
        exe = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
        urls = [
            "https://ollama.com/download/OllamaSetup.exe",
            "https://github.com/ollama/ollama/releases/latest/download/OllamaSetup.exe",
        ]
        if self._download_with_fallback(urls, exe, "OllamaSetup.exe"):
            self.run_powershell(
                f'Start-Process "{exe}" -ArgumentList "/SILENT" -Wait 2>&1',
                timeout=300
            )
            self._refresh_path()
            time.sleep(8)
            r3 = self.run_powershell("ollama --version 2>$null")
            if r3["returncode"] == 0:
                self.log("  Ollama Windows-native installed (EXE)  ✓", "SUCCESS")
                return True

        self.log("  Ollama installation failed!", "ERROR")
        self.log("  Manual: https://ollama.com/download → download OllamaSetup.exe", "WARNING")
        return False

    def _ollama_api_reachable(self, host: str = "127.0.0.1", port: int = 11434) -> bool:
        """Checks if Ollama API is reachable via HTTP GET /api/tags."""
        try:
            import urllib.request
            url = f"http://{host}:{port}/api/tags"
            req = urllib.request.urlopen(url, timeout=4)
            return req.status == 200
        except Exception:
            return False

    def _get_wsl_ip(self) -> str:
        """Returns the primary WSL2 IP (for fallback check)."""
        r = self.run_powershell(
            "wsl hostname -I 2>$null | ForEach-Object { ($_.Trim() -split '\\s+')[0] }"
        )
        return r.get("stdout", "").strip()

    def start_ollama_serve(self):
        """
        Starts 'ollama serve' in WSL2 with robust verification.
        v15: Multiple start attempts, API check instead of port check, WSL IP fallback,
             output WSL log on error.
        """
        self.log("  Checking Ollama status...")

        # ── Step 1: Already running? ───────────────────────────────
        if self._ollama_api_reachable():
            self.log("  Ollama API reachable (127.0.0.1:11434)  ✓", "SUCCESS")
            return True

        # Check WSL IP as fallback
        wsl_ip = self._get_wsl_ip()
        if wsl_ip and self._ollama_api_reachable(wsl_ip):
            self.log(f"  Ollama API via WSL IP {wsl_ip}:11434 reachable  ✓", "SUCCESS")
            return True

        # ── Step 2: Prerequisites ─────────────────────────────────
        wsl_ok, ubuntu_ok = self.check_wsl()
        if not (wsl_ok and ubuntu_ok):
            self.log("  WSL2/Ubuntu missing – Ollama cannot start", "ERROR")
            return False

        if not self.check_ollama_wsl():
            self.log("  Ollama not installed in WSL!", "ERROR")
            self.log("  → Manual: wsl bash -lc 'curl -fsSL https://ollama.com/install.sh | sh'",
                     "WARNING")
            return False

        # ── Step 3: Check Ollama process in WSL ──────────────────
        r_ps = self.run_powershell(
            'wsl bash -lc "pgrep -x ollama 2>/dev/null || echo NOT_RUNNING" 2>&1'
        )
        ps_out = r_ps.get("stdout", "").strip()
        if "NOT_RUNNING" in ps_out or not ps_out:
            self.log("  Ollama process in WSL not active – restarting...", "WARNING")
        else:
            self.log(f"  Ollama process running (PID {ps_out}) but API unreachable – restarting",
                     "WARNING")
            # Kill the hung process
            self.run_powershell(
                'wsl bash -lc "pkill -x ollama 2>/dev/null; sleep 2" 2>&1'
            )

        # ── Step 4: Start (3 attempts) ──────────────────────────
        for attempt in range(1, 4):
            self.log(f"  Starting ollama serve (attempt {attempt}/3)...")

            # OLLAMA_HOST=0.0.0.0 is critical – otherwise only WSL-internal reachable
            subprocess.Popen(
                'wsl bash -lc "export OLLAMA_HOST=0.0.0.0:11434; '
                'nohup ollama serve >> /tmp/ollama.log 2>&1 &"',
                shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

            # Wait up to 20s for API response
            for wait in range(20):
                time.sleep(1)
                if self._ollama_api_reachable():
                    self.log(f"  Ollama API up after {wait+1}s  ✓", "SUCCESS")
                    return True
                if wsl_ip and self._ollama_api_reachable(wsl_ip):
                    self.log(f"  Ollama API via WSL IP {wsl_ip} up after {wait+1}s  ✓", "SUCCESS")
                    return True

            self.log(f"  Attempt {attempt} failed – waiting 5s...")
            time.sleep(5)

        # ── Step 5: Error diagnostics ─────────────────────────────────
        self.log("  Ollama API unreachable after 3 attempts!", "ERROR")

        # Output WSL log
        r_log = self.run_powershell(
            'wsl bash -lc "tail -20 /tmp/ollama.log 2>/dev/null || echo NO_LOG" 2>&1'
        )
        log_out = r_log.get("stdout", "").strip()
        if log_out and "NO_LOG" not in log_out:
            self.log("  Ollama WSL log (last 20 lines):", "WARNING")
            for line in log_out.split("\n")[-10:]:
                if line.strip():
                    self.log(f"    {line.strip()}", "WARNING")

        # Check WSL network
        r_net = self.run_powershell(
            'wsl bash -lc "ss -tlnp 2>/dev/null | grep 11434 || echo PORT_NOT_OPEN" 2>&1'
        )
        net_out = r_net.get("stdout", "").strip()
        self.log(f"  WSL Port 11434: {net_out[:120]}", "WARNING")

        self.log("  Manual start: wsl bash -lc 'OLLAMA_HOST=0.0.0.0 ollama serve &'",
                 "WARNING")
        return False

    def setup_ollama_autostart(self):
        """
        Sets up two mechanisms to keep Ollama running in WSL2:
        1. Scheduled Task on login (15s delay)
        2. PowerShell wrapper script that also calls OpenClaw and ensures Ollama

        v20: Also an 'ensure-ollama.ps1' script that the Gateway task can call.
        """
        self.log("  Setting up Ollama autostart (WSL2 on login)...")
        cfg_dir = self.cfg._find_openclaw_config_dir()

        # ── Step 1: ensure-ollama.ps1 wrapper script ───────────────
        # This script checks if Ollama is running and starts it if not.
        # Called by the Gateway startup task.
        ensure_script = os.path.join(cfg_dir, "ensure-ollama.ps1")
        # sessions.json path for PS1 script — USER is determined dynamically
        sessions_path = os.path.join(
            cfg_dir, "agents", "main", "sessions", "sessions.json"
        ).replace("\\", "\\\\")

        ps1_content = f"""# ensure-ollama.ps1 — generated by OpenClawWinInstaller
# Ensures Ollama is running and deletes sessions.json for a fresh agent start

# ── Delete sessions.json (LYRA should always start fresh) ──────────
$SessionsFile = "{sessions_path}"
if (Test-Path $SessionsFile) {{
    Remove-Item $SessionsFile -Force
    Write-Host "sessions.json deleted – fresh agent start."
}}

$OllamaUrl = "http://127.0.0.1:11434/api/tags"
$MaxWait = 30

function Test-OllamaRunning {{
    try {{
        $resp = Invoke-WebRequest -Uri $OllamaUrl -TimeoutSec 3 -UseBasicParsing 2>$null
        return $resp.StatusCode -eq 200
    }} catch {{ return $false }}
}}

if (Test-OllamaRunning) {{
    Write-Host "Ollama already running."
    exit 0
}}

Write-Host "Starting Ollama in WSL2..."
Start-Process wsl.exe -ArgumentList 'bash -lc "export OLLAMA_HOST=0.0.0.0:11434; nohup ollama serve >> /tmp/ollama.log 2>&1 &"' -WindowStyle Hidden

for ($i = 0; $i -lt $MaxWait; $i++) {{
    Start-Sleep 1
    if (Test-OllamaRunning) {{
        Write-Host "Ollama started after $($i+1)s."
        exit 0
    }}
}}
Write-Host "WARNING: Ollama not responding after ${{MaxWait}}s"
exit 1
"""
        try:
            with open(ensure_script, "w", encoding="utf-8") as f:
                f.write(ps1_content)
            self.log(f"  ensure-ollama.ps1 written: {ensure_script}  ✓", "SUCCESS")
        except Exception as e:
            self.log(f"  ensure-ollama.ps1: {e}", "WARNING")

        # ── Step 2: Scheduled Task on login ───────────────────────
        task_name = "OllamaWSL2Serve"
        task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT10S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT2M</ExecutionTimeLimit>
    <Hidden>true</Hidden>
  </Settings>
  <Actions>
    <Exec>
      <Command>powershell.exe</Command>
      <Arguments>-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{ensure_script}"</Arguments>
    </Exec>
  </Actions>
</Task>"""
        try:
            xml_path = os.path.join(tempfile.gettempdir(), "ollama_autostart.xml")
            with open(xml_path, "w", encoding="utf-16") as f:
                f.write(task_xml)
            r = self.run_powershell(
                f'schtasks /Create /TN "{task_name}" /XML "{xml_path}" /F 2>&1'
            )
            os.remove(xml_path)
            out = (r["stdout"] + r.get("stderr", "")).lower()
            if "success" in out or "erfolgreich" in out:
                self.log(f"  Ollama autostart task '{task_name}' created  ✓", "SUCCESS")
                self.log("  Ollama will start automatically 10s after next login  ✓", "SUCCESS")
                return True
            else:
                self.log(f"  Autostart task: {out[:80]}", "WARNING")
        except Exception as e:
            self.log(f"  Ollama autostart failed: {e}", "WARNING")
        return False

    def _get_docker_wsl_ram_gb(self) -> float:
        """
        Returns the RAM reserved by Docker Desktop in WSL2.
        Docker uses its own WSL2 distro (docker-desktop, docker-desktop-data)
        which consumes RAM not available for Ollama.
        """
        try:
            r = self.run_powershell(
                "wsl --list --verbose 2>$null | Select-String 'docker'"
            )
            if "docker" in r.get("stdout", "").lower():
                # Docker WSL distro running — typically reserves 2-4 GB
                # More accurate measurement via WSL memory processes
                r2 = self.run_powershell(
                    'wsl -d docker-desktop bash -c "free -g 2>/dev/null | awk \'NR==2{print $3}\'" 2>$null'
                )
                used = r2.get("stdout", "").strip()
                if used and used.isdigit():
                    return float(used)
                return 3.0  # Conservative estimate
        except Exception:
            pass
        return 0.0

    def _is_docker_running(self) -> bool:
        """Checks if Docker Desktop is actively running."""
        r = self.run_powershell(
            "Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue 2>$null | Measure-Object | Select-Object -ExpandProperty Count"
        )
        try:
            return int(r.get("stdout", "0").strip()) > 0
        except Exception:
            return False

    def _get_available_ram_gb(self):
        """
        Returns the RAM EFFECTIVELY available for Ollama in GB.
        Subtracts Docker Desktop WSL2 reservation if Docker is running.
        """
        # Windows free RAM
        r = self.run_powershell(
            "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB / 1KB 2>$null"
        )
        try:
            free_gb = float(r["stdout"].strip())
        except Exception:
            r2 = self.run_powershell(
                "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB 2>$null"
            )
            try:
                free_gb = float(r2["stdout"].strip()) * 0.5  # Half as estimate
            except Exception:
                free_gb = 16.0

        # Docker correction: Docker Desktop reserves RAM in WSL2
        if self._is_docker_running():
            docker_ram = self._get_docker_wsl_ram_gb()
            if docker_ram > 0:
                corrected = free_gb - docker_ram
                self.log(f"  [RAM] Docker running: {free_gb:.1f} GB free - {docker_ram:.1f} GB Docker = {corrected:.1f} GB for Ollama",
                         "WARNING")
                return max(corrected, 4.0)
            else:
                # Docker running but RAM not measurable → conservatively subtract 4 GB
                corrected = free_gb - 4.0
                self.log(f"  [RAM] Docker active: ~4 GB reserved → {corrected:.1f} GB for Ollama",
                         "WARNING")
                return max(corrected, 4.0)

        return free_gb

    def _get_cpu_score(self):
        """
        Evaluates CPU performance for LLM inference.
        Primary source: /proc/cpuinfo via WSL (reliable).
        Fallback: CPU name regex (unreliable on Windows).
        Returns (score, model_hint):
          score 1 = no AVX2 → qwen2.5:0.5b
          score 2 = AVX2 present → qwen2.5:7b
        """
        try:
            # PRIMARY: Read AVX2 directly from WSL /proc/cpuinfo
            r = self._wsl_cmd("grep -m1 'avx2' /proc/cpuinfo 2>/dev/null")
            wsl_stdout = r.get("stdout", "").lower()
            if "avx2" in wsl_stdout:
                import platform
                cpu = platform.processor()
                self.log(f"  CPU: {cpu} → AVX2 confirmed (WSL /proc/cpuinfo) → 7b model (LYRA)", "INFO")
                return 2, "qwen2.5:7b"

            # FALLBACK: Derive CPU generation from brand name
            import platform, re
            cpu = platform.processor().lower()
            # Sandy/Ivy Bridge (model 42/58) = no AVX2
            # Haswell+ = has AVX2. Coffee Lake = model 158 = has AVX2
            # If WSL not available: conservative 0.5b
            if re.search(r'i[357]-[23]\d{3}', cpu):
                self.log(f"  CPU: {cpu} → Sandy/Ivy Bridge, no AVX2 → 0.5b model", "WARNING")
                return 1, "qwen2.5:0.5b"
            # All others: without WSL confirmation stay conservative
            self.log(f"  CPU: {cpu} → AVX2 not confirmed (WSL not available) → 0.5b model", "WARNING")
            return 1, "qwen2.5:0.5b"
        except Exception as e:
            self.log(f"  CPU detection failed: {e} → 0.5b model", "WARNING")
            return 1, "qwen2.5:0.5b"

    def pull_lyra_models(self):
        """
        Loads Ollama models for LYRA exclusively via WSL2.
        RAM-adaptive with active cleanup of oversized models.
        v38: Respects machine role – Junior/Senior only load small models.

        RAM requirements (measured, not estimated):
          llama3.1:8b    →  6.5 GB  → from  8 GB free RAM
          qwen2.5:7b     →  5.5 GB  → from  8 GB free RAM
          qwen2.5:14b    → 19.9 GB  → from 24 GB free RAM (measured!)
          deepseek-r1:8b →  6.5 GB  → from  8 GB free RAM
        """
        machine_role = getattr(self, "machine_role", "Lyra")
        ram_gb = self._get_available_ram_gb()
        cpu_score, cpu_model = self._get_cpu_score()
        self.log(f"  Free RAM: {ram_gb:.1f} GB  |  Role: {machine_role}")

        # Junior may ONLY load small models (max 1.5b), Senior max 3b
        if machine_role == "Junior":
            primary = "qwen2.5:0.5b"
            models_to_keep = [primary]
            self.log("  Junior mode: only qwen2.5:0.5b", "INFO")
        elif machine_role == "Senior":
            primary = "qwen2.5:1.5b"
            models_to_keep = [primary]
            if ram_gb >= 6:
                models_to_keep.append("qwen2.5:3b")
            self.log(f"  Senior mode: {', '.join(models_to_keep)}", "INFO")
        else:
            # LYRA (head): full model selection based on CPU + RAM
            primary = cpu_model  # qwen2.5:0.5b or qwen2.5:7b
            models_to_keep = [primary]

            if cpu_score >= 2 and ram_gb >= 10:
                models_to_keep.append("qwen2.5:7b")
            if cpu_score >= 2 and ram_gb >= 24:
                models_to_keep.append("qwen2.5:14b")
            if cpu_score >= 2 and ram_gb >= 16:
                models_to_keep.append("deepseek-r1:8b")

        # Models that are too large → actively remove so Ollama doesn't cache them
        models_too_large = []
        if machine_role in ("Junior", "Senior"):
            # Junior: only 0.5b allowed → remove all larger ones
            # Senior: max 3b
            for big in ["qwen2.5:7b", "qwen2.5:14b", "deepseek-r1:8b",
                        "llama3.1:8b", "qwen2.5:14b"]:
                if big not in models_to_keep:
                    models_too_large.append(big)
        else:
            if ram_gb < 24:
                models_too_large.append("qwen2.5:14b")
            if ram_gb < 10:
                models_too_large.append("qwen2.5:7b")
                models_too_large.append("deepseek-r1:8b")

        # Check already installed models
        try:
            import urllib.request as _ur, json as _j
            resp = _ur.urlopen("http://127.0.0.1:11434/api/tags", timeout=5)
            installed = {m["name"] for m in _j.loads(resp.read()).get("models", [])}
        except Exception:
            installed = set()

        # Delete oversized models
        for model in models_too_large:
            # Check if model (with or without tag) is installed
            installed_match = [m for m in installed if m.startswith(model.split(":")[0])]
            for m in installed_match:
                if any(m.startswith(big) for big in models_too_large):
                    self.log(f"  Removing {m} (too large for {ram_gb:.0f} GB RAM)...", "WARNING")
                    r_rm = self.run_powershell(
                        f'wsl bash -lc "ollama rm {m} 2>&1" 2>&1'
                    )
                    out = (r_rm["stdout"] + r_rm.get("stderr", "")).strip()
                    if "deleted" in out.lower() or r_rm["returncode"] == 0:
                        self.log(f"  {m} removed  ✓", "SUCCESS")
                    else:
                        self.log(f"  {m} could not be removed: {out[:60]}", "WARNING")

        self.log(f"  Planned models: {', '.join(models_to_keep)}")
        if "qwen2.5:14b" not in models_to_keep:
            self.log(f"  qwen2.5:14b will NOT be loaded – needs ~20 GB, available: {ram_gb:.0f} GB", "INFO")

        # WSL or native ollama? Try both
        wsl_ok, ubuntu_ok = self.check_wsl()
        ollama_in_wsl = wsl_ok and ubuntu_ok and self.check_ollama_wsl()
        ollama_native = self.check_ollama_native()

        if not ollama_in_wsl and not ollama_native:
            self.log("  Ollama neither in WSL nor native – no model pull!", "ERROR")
            return []

        if not ollama_in_wsl and ollama_native:
            self.log("  Ollama running natively (Windows) – pulling models via Windows Ollama...", "INFO")

        pulled = []
        pull_timeout = 7200 if machine_role == "Lyra" else 3600
        for model in models_to_keep:
            self.log(f"\n  ── Loading model: {model} ──")
            self.log(f"  (Large models can take 5–30 min. – please wait)")
            if ollama_in_wsl:
                r = self._wsl_cmd_live(
                    f"OLLAMA_HOST=127.0.0.1:11434 ollama pull {model}",
                    timeout=pull_timeout, prefix="    "
                )
            else:
                # Fallback: native Windows Ollama
                # IMPORTANT: ollama.exe outputs escape codes → returncode may be ≠ 0
                # Detect success by "success" in stdout
                r = self.run_powershell_live(
                    f"ollama pull {model} 2>&1",
                    timeout=pull_timeout, prefix="    "
                )
                # Correct returncode if "success" is in output
                if r.get("returncode", 1) != 0:
                    combined = (r.get("stdout","") + r.get("stderr","")).lower()
                    if "success" in combined:
                        r = dict(r)
                        r["returncode"] = 0
            if r["returncode"] == 0:
                self.log(f"  {model} loaded successfully!", "SUCCESS")
                pulled.append(model)
            else:
                self.log(f"  {model} failed – continuing", "WARNING")
                self.log(f"  Manual: wsl bash -lc 'ollama pull {model}'", "WARNING")

        if pulled:
            self.log(f"  Available LYRA models: {', '.join(pulled)}", "SUCCESS")
        else:
            self.log("  No model loaded – pull manually after setup!", "ERROR")
        # Return cpu_model as primary — not pulled[0] which might be first randomly
        return pulled, cpu_model

    def wait_for_ollama(self, max_wait=30):
        """Waits until Ollama API responds on port 11434 (HTTP /api/tags)."""
        self.log(f"  Waiting for Ollama API (max. {max_wait}s)...")
        wsl_ip = self._get_wsl_ip()
        for i in range(max_wait):
            if self._ollama_api_reachable():
                self.log(f"  Ollama API reachable after {i+1}s  ✓", "SUCCESS")
                return True
            if wsl_ip and self._ollama_api_reachable(wsl_ip):
                self.log(f"  Ollama API via WSL IP {wsl_ip} reachable  ✓", "SUCCESS")
                return True
            time.sleep(1)
        self.log("  Ollama API unreachable – model pull may fail", "WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────
    # OPENCLAW CONFIG + LYRA AGENT
    # ──────────────────────────────────────────────────────────────────

    def _api(self, method: str, path: str, payload=None, token: str = "",
             base: str = "http://127.0.0.1:18789", timeout: int = 15):
        """
        Small HTTP helper for OpenClaw REST API.
        Returns (status_code, response_dict) or (status_code, None) on error.
        Sends Bearer token if present, but also accepts 401/403
        (auth.mode=none should disable token requirement).
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"{base}{path}"
        data = json.dumps(payload).encode("utf-8") if payload else None
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                try:
                    return resp.status, json.loads(body)
                except:
                    return resp.status, {"raw": body.decode("utf-8", errors="replace")}
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
            except:
                pass
            return e.code, {"error": str(e), "body": body.decode("utf-8", errors="replace")[:300]}
        except Exception as e:
            return -1, {"error": str(e)}

    def force_kill_openclaw_processes(self):
        self.log("  Terminating running OpenClaw/Node processes...")
        own_pid = os.getpid()
        # Exclude own PID – binary name "OpenClawWinInstaller.exe" matches "openclaw*"!
        self.run_powershell(
            f"Get-Process -Name 'openclaw*' -ErrorAction SilentlyContinue "
            f"| Where-Object {{ $_.Id -ne {own_pid} }} "
            f"| Stop-Process -Force"
        )
        self.run_powershell(f"""
            Get-WmiObject Win32_Process |
            Where-Object {{ $_.Name -eq 'node.exe' -and $_.CommandLine -like '*openclaw*' }} |
            ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}
        """)
        time.sleep(2)

    def force_delete_dir(self, path):
        """Deletes a directory with four fallback strategies."""
        if not os.path.exists(path):
            return True
        for _ in range(3):
            try:
                shutil.rmtree(path)
                return True
            except:
                pass
            try:
                self.run_powershell(
                    f'Remove-Item -Recurse -Force "{path}" -ErrorAction SilentlyContinue'
                )
                if not os.path.exists(path):
                    return True
            except:
                pass
            subprocess.run(f'rd /s /q "{path}"', shell=True, timeout=30)
            if not os.path.exists(path):
                return True
            time.sleep(1)
        # Rename as last resort
        try:
            trash = path + f"_DEL_{int(time.time())}"
            os.rename(path, trash)
            subprocess.Popen(f'ping -n 4 127.0.0.1 >nul && rd /s /q "{trash}"', shell=True)
            return True
        except:
            pass
        return False

    def find_main_file(self, base_dir):
        """Finds main file via package.json (bin/main) or name fallback."""
        if not os.path.isdir(base_dir):
            return None

        pkg_path = os.path.join(base_dir, "package.json")
        if os.path.isfile(pkg_path):
            try:
                with open(pkg_path, "r", encoding="utf-8") as f:
                    pkg = json.load(f)
                bin_field = pkg.get("bin", {})
                if isinstance(bin_field, str):
                    c = os.path.join(base_dir, bin_field.replace("/", os.sep))
                    if os.path.isfile(c):
                        return c
                elif isinstance(bin_field, dict):
                    for _, p in bin_field.items():
                        c = os.path.join(base_dir, str(p).replace("/", os.sep))
                        if os.path.isfile(c):
                            return c
                main = pkg.get("main", "")
                if main:
                    c = os.path.join(base_dir, main.replace("/", os.sep))
                    if os.path.isfile(c):
                        return c
            except:
                pass

        names = ["openclaw.mjs", "openclaw.js", "cli.mjs", "cli.js",
                 "index.mjs", "index.js", "main.mjs", "main.js"]
        for n in names:
            c = os.path.join(base_dir, n)
            if os.path.isfile(c):
                return c
        for sub in ["bin", "src", "dist", "lib"]:
            for n in names:
                c = os.path.join(base_dir, sub, n)
                if os.path.isfile(c):
                    return c
        for root_dir, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d != "node_modules"]
            for fname in files:
                if fname.endswith((".mjs", ".js", ".cjs")):
                    return os.path.join(root_dir, fname)
        return None

    # ──────────────────────────────────────────────────────────────────
    # OPENCLAW – Check & Install
    # ──────────────────────────────────────────────────────────────────

    def check_openclaw(self):
        r = self.run_powershell("Get-Command openclaw -ErrorAction SilentlyContinue")
        if r["stdout"]:
            prefix = self._npm_prefix()
            main = self.find_main_file(os.path.join(prefix, "node_modules", "openclaw"))
            return True, ("ok" if main else "missing_file")
        r2 = self.run_powershell("npm list -g --depth=0 | findstr openclaw")
        if r2["stdout"] and "openclaw" in r2["stdout"].lower():
            return True, "npm_only"
        return False, "not_found"

    def fix_openclaw_installation(self):
        """Installs / repairs OpenClaw with live logging, EPERM and cmake handling."""
        self.log("Installing / repairing OpenClaw...")

        prefix  = self._npm_prefix()
        modules = os.path.join(prefix, "node_modules")
        oc_dir  = os.path.join(modules, "openclaw")
        self.log(f"  npm prefix: {prefix}")

        # Terminate processes + delete old directory
        self.force_kill_openclaw_processes()
        self.log("  Uninstalling old version...")
        self.run_powershell("npm uninstall -g openclaw 2>$null")
        time.sleep(1)
        if os.path.exists(oc_dir):
            self.log(f"  Deleting: {oc_dir}")
            self.force_delete_dir(oc_dir)

        # Switch Git to HTTPS (no SSH prompts)
        self.log("  Configuring Git: HTTPS instead of SSH...")
        self.run_powershell(
            'git config --global url."https://github.com/".insteadOf "git@github.com:"'
        )
        self.run_powershell(
            'git config --global url."https://github.com/".insteadOf "ssh://git@github.com/"'
        )
        self.run_powershell("git config --global core.longpaths true 2>$null")

        # Clear npm cache
        self.log("  Clearing npm cache...")
        self.run_powershell("npm cache clean --force 2>$null")

        # NODE_LLAMA_CPP_SKIP_DOWNLOAD=1 → use system CMake instead of download
        # NODE_LLAMA_CPP_BUILD_TYPE=Release → no debug build
        llama_env = {
            "NODE_LLAMA_CPP_SKIP_DOWNLOAD": "1",
            "NODE_LLAMA_CPP_BUILD_TYPE": "Release",
        }

        # Provide CMake path for node-llama-cpp
        cmake_path = shutil.which("cmake")
        if cmake_path:
            llama_env["CMAKE_PATH"] = cmake_path
            self.log(f"  cmake found: {cmake_path}", "SUCCESS")

        # Installation – with live output and extended environment
        sources = [
            ("npm openclaw@latest",
             "npm install -g openclaw@latest"),
            ("npm openclaw@latest (skip-llama-download)",
             "npm install -g openclaw@latest --ignore-scripts"),
            ("npm openclaw",
             "npm install -g openclaw"),
            ("GitHub openclaw/openclaw",
             "npm install -g https://github.com/openclaw/openclaw"),
        ]

        install_ok = False
        for name, cmd in sources:
            self.log(f"\n  ── Attempt: {name} ──")

            # v6: Ensure Git availability before each attempt
            # "npm error spawn git" → Git not in PATH → reinstall
            git_ok = bool(self.check_git())
            if not git_ok:
                self.log("  Git not in PATH – attempting installation...", "WARNING")
                self._refresh_path()
                git_ok = bool(self.check_git())
                if not git_ok:
                    self.log("  Installing Git for npm git dependencies...")
                    self.install_git()
                    self._refresh_path()
                    time.sleep(3)
                    git_ok = bool(self.check_git())
                if not git_ok:
                    # Extend npm PATH for git (fallback)
                    self.run_powershell(
                        '$env:Path = "C:\\Program Files\\Git\\cmd;" + $env:Path'
                    )
                    git_ok = bool(self.check_git())
            if git_ok:
                self.log(f"  Git OK: {self.check_git()}", "SUCCESS")
            else:
                self.log("  Git still not found – attempting anyway", "WARNING")
            result = self.run_powershell_live(
                cmd, timeout=600, prefix="    ", env_extra=llama_env
            )

            if result["returncode"] == 0:
                self.log(f"  {name}: Successful!", "SUCCESS")
                install_ok = True
                break

            combined = result["stderr"] + result["stdout"]
            self.log(f"  {name} failed (code {result['returncode']})", "WARNING")

            # EPERM → kill processes, clear cache, retry
            if "eperm" in combined.lower():
                self.log("  EPERM detected – killing processes + clearing cache + retry...")
                self.force_kill_openclaw_processes()
                self.force_delete_dir(oc_dir)
                self.run_powershell("npm cache clean --force 2>$null")
                time.sleep(3)
                self.log(f"  ── Retry: {name} ──")
                r2 = self.run_powershell_live(
                    cmd, timeout=600, prefix="    ", env_extra=llama_env
                )
                if r2["returncode"] == 0:
                    self.log(f"  {name} (retry): Successful!", "SUCCESS")
                    install_ok = True
                    break

        if not install_ok:
            self.log("  All installation attempts failed!", "ERROR")
            return False

        # Find installed directory
        found_dir = next(
            (d for d in [oc_dir, os.path.join(modules, "@openclaw", "cli")]
             if os.path.isdir(d)),
            None
        )
        if not found_dir:
            self.log("  OpenClaw directory not found!", "ERROR")
            return False
        self.log(f"  Directory: {found_dir}")

        # Main file via package.json
        main_file = self.find_main_file(found_dir)
        if not main_file:
            self.log("  No executable main file found!", "ERROR")
            return False
        self.log(f"  Main file: {main_file}")

        # Create openclaw.cmd + .ps1 with correct path
        cmd_file = os.path.join(prefix, "openclaw.cmd")
        ps1_file = os.path.join(prefix, "openclaw.ps1")
        try:
            with open(cmd_file, "w", encoding="utf-8") as f:
                f.write(f'@echo off\r\nnode "{main_file}" %*\r\n')
            with open(ps1_file, "w", encoding="utf-8") as f:
                f.write(f'#!/usr/bin/env pwsh\n& node "{main_file}" @args\n')
            self.log(f"  openclaw.cmd -> {os.path.basename(main_file)}")
        except Exception as e:
            self.log(f"  Warning: .cmd could not be created: {e}", "WARNING")

        # Direct test
        self.log("  Testing OpenClaw directly...")
        test = self.run_powershell(f'node "{main_file}" --version 2>&1')
        out  = (test["stdout"] + test["stderr"]).lower()
        if "cannot find module" in out and test["returncode"] != 0:
            self.log(f"  Test failed: {test['stdout'][:200]}", "ERROR")
            return False
        self.log(f"  Test OK: {test['stdout'].strip()[:80] or '(no output - ok)'}", "SUCCESS")
        return True

    # ──────────────────────────────────────────────────────────────────
    # GATEWAY
    # ──────────────────────────────────────────────────────────────────

    def get_openclaw_cmd(self):
        cmd_file = os.path.join(self._npm_prefix(), "openclaw.cmd")
        return f'& "{cmd_file}"' if os.path.isfile(cmd_file) else "openclaw"

    def _run_with_yes_input(self, command, timeout=120, prefix="    "):
        """
        Executes a command and automatically answers all interactive Yes/No prompts
        with 'y'. Three strategies:
          1. 'yes |' pipe (Unix style in PowerShell)
          2. Echo pipe: 'y\n' via stdin
          3. Normal run_powershell_live as fallback
        """
        stdout_lines, stderr_lines = [], []
        try:
            # Strategy 1: PowerShell yes pipe
            ps_cmd = f"'y' | {command}"
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace"
            )
            q = queue_module.Queue()

            def _reader(pipe, tag):
                try:
                    for line in pipe:
                        q.put((tag, line.rstrip()))
                except:
                    pass
                finally:
                    q.put((tag, None))

            threading.Thread(target=_reader, args=(proc.stdout, "out"), daemon=True).start()
            threading.Thread(target=_reader, args=(proc.stderr, "err"), daemon=True).start()

            done, t0 = 0, time.time()
            while done < 2:
                if time.time() - t0 > timeout:
                    proc.kill()
                    self.log(f"{prefix}TIMEOUT after {timeout}s – process terminated", "WARNING")
                    break
                try:
                    tag, line = q.get(timeout=0.25)
                except queue_module.Empty:
                    continue
                if line is None:
                    done += 1
                    continue
                s = line.strip()
                if not s:
                    continue
                lo = s.lower()
                lvl = ("ERROR" if (tag == "err" or "error" in lo) else
                       "WARNING" if any(w in lo for w in ["warn", "security"]) else
                       "SUCCESS" if any(w in lo for w in ["success", "done", "installed"]) else
                       "INFO")
                self.log(f"{prefix}{s[:170]}", lvl)
                stdout_lines.append(s)

            proc.wait()
            return {"stdout": "\n".join(stdout_lines), "stderr": "\n".join(stderr_lines),
                    "returncode": proc.returncode}
        except Exception as e:
            self.log(f"{prefix}Error: {e}", "WARNING")
            # Fallback: normal call
            return self.run_powershell_live(command, timeout=timeout, prefix=prefix)

    def setup_gateway(self):
        self.log("Setting up gateway...")
        oc = self.get_openclaw_cmd()

        # ── Step A: onboard ────────────────────────────────────────
        # The onboard command shows an interactive security warning
        # with "Yes / > No" – must be answered with 'y'.
        # We try three variants in sequence:
        self.log("  openclaw onboard (auto-confirm)...")

        onboard_ok = False
        for flag in ["--yes", "--accept", "--force", "--skip-onboarding", ""]:
            cmd = f"{oc} onboard {flag} 2>&1".strip()
            self.log(f"  Attempt: {cmd[:80]}")
            r = self._run_with_yes_input(cmd, timeout=60, prefix="    ")
            out = (r["stdout"] + r.get("stderr", "")).lower()
            # Success indicators: no "error" AND no stuck prompt
            if r["returncode"] == 0 or any(
                w in out for w in ["onboard", "done", "complete", "security", "gateway"]
            ):
                self.log("  Onboard completed", "SUCCESS")
                onboard_ok = True
                break
            if "unknown option" in out or "invalid" in out:
                continue  # Flag not supported → try next
        if not onboard_ok:
            self.log("  Onboard note: security prompt may not have been answered – continuing",
                     "WARNING")
        time.sleep(2)

        # ── Step B: Install gateway as Windows service / scheduled task ──
        self.log("  openclaw gateway install ...")
        r_install = self._run_with_yes_input(
            f"{oc} gateway install 2>&1", timeout=60, prefix="    "
        )
        time.sleep(2)

        # ── Step C: Start gateway (multiple methods) ──
        self.log("  Starting gateway...")

        # Method 1: openclaw gateway start
        self._run_with_yes_input(f"{oc} gateway start 2>&1", timeout=30, prefix="    ")
        time.sleep(3)

        # Method 2: Run scheduled task directly (fallback)
        self.run_powershell(
            'schtasks /Run /TN "OpenClaw Gateway" 2>$null',
            timeout=15
        )
        time.sleep(4)

        # Method 3: Start Windows service (fallback)
        self.run_powershell(
            'Start-Service -Name "openclaw*" -ErrorAction SilentlyContinue 2>$null',
            timeout=15
        )
        time.sleep(3)

        # ── Step D: Check status ──────────────────────────────────
        status = self.run_powershell(f"{oc} gateway status 2>&1")
        combined = (status["stdout"] + status["stderr"]).lower()
        if any(w in combined for w in ["running", "started", "active", "online"]):
            self.log("Gateway is running!", "SUCCESS")
            return True

        # Port check as additional verification
        port = self.run_powershell(
            "Test-NetConnection -ComputerName localhost -Port 18789"
            " -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null"
        )
        if "True" in port["stdout"]:
            self.log("Gateway is running! (port 18789 reachable)", "SUCCESS")
            return True

        # ── Step E: Create schtasks directly as last resort ─────
        self.log("  Creating scheduled task for gateway manually...", "WARNING")
        prefix = self._npm_prefix()
        cmd_file = os.path.join(prefix, "openclaw.cmd")
        if os.path.isfile(cmd_file):
            task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit></Settings>
  <Actions><Exec>
    <Command>cmd.exe</Command>
    <Arguments>/c "{cmd_file}" gateway 2&gt;&amp;1</Arguments>
  </Exec></Actions>
</Task>"""
            xml_path = os.path.join(tempfile.gettempdir(), "openclaw_gw.xml")
            try:
                with open(xml_path, "w", encoding="utf-16") as f:
                    f.write(task_xml)
                self.run_powershell(
                    f'schtasks /Create /TN "OpenClaw Gateway" /XML "{xml_path}" /F 2>$null'
                )
                self.run_powershell('schtasks /Run /TN "OpenClaw Gateway" 2>$null')
                os.remove(xml_path)
                time.sleep(5)
                port2 = self.run_powershell(
                    "Test-NetConnection -ComputerName localhost -Port 18789"
                    " -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null"
                )
                if "True" in port2["stdout"]:
                    self.log("Gateway is running via scheduled task!", "SUCCESS")
                    return True
            except Exception as e:
                self.log(f"  Scheduled task error: {e}", "WARNING")

        self.log("Gateway not started – but OpenClaw is installed!", "WARNING")
        self.log("  Start manually (as administrator):", "WARNING")
        self.log(f'  > openclaw gateway install', "WARNING")
        self.log(f'  > openclaw gateway start', "WARNING")
        return False

    def _detect_avx2(self):
        """
        Detects AVX2 support via WSL /proc/cpuinfo (primary) or fallback.
        Returns (has_avx2: bool).
        """
        try:
            r = self._wsl_cmd("grep -m1 'avx2' /proc/cpuinfo 2>/dev/null")
            return "avx2" in r.get("stdout", "").lower()
        except Exception:
            return False
