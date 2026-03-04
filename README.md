# OpenClawWinInstaller

> **Status: v1.0.4 — PRODUCTION READY** · 2026-03-04

A fully automated Windows installer that sets up **OpenClaw** with a local LLM (LYRA via Ollama).  
After running the script, LYRA is immediately ready to use — no manual configuration, no token issues, no approval prompts.

From v1.0.0 the system supports a **machine role hierarchy**: a LYRA head orchestrates any number of Junior/Senior workers via an integrated HTTP task server with **bidirectional communication**.

**Stack:** `Python (tkinter GUI)` → `PowerShell` → `OpenClaw (npm)` + `Ollama (Windows-native / Docker / WSL)`

---

## ✨ The Philosophy

*"One click and LYRA lives – the rest is history"* 🌀

Unlike other setups that require hours of googling, Stack Overflow deep-dives, and manual debugging, this installer handles everything:
- ✅ 50+ components automatically installed
- ✅ 67+ edge cases fixed and documented
- ✅ 3-stage fallback strategies
- ✅ Bidirectional worker communication (result stored locally + posted to HEAD)
- ✅ Worker auto-start on every app launch
- ✅ Task Server auto-start on Lyra at launch and after every Gateway restart
- ✅ LYRA knows her workers — persistent registry, direct exec access
- ✅ LYRA behavioral rules continuously tuned via live session logs
- ✅ Web search works even without a connected worker
- ✅ Gateway logs in local time (Europe/Zurich)
- ✅ GPU-hybrid inference with RTX 3050 + shared RAM
- ✅ Hardware-aware config: timeout + model from HardwareProfile
- ✅ Clean two-module architecture: GUI installer + config management separated

---

## Table of Contents

- [What's New in v1.0.4](#whats-new-in-v104)
- [What's New in v1.0.3](#whats-new-in-v103)
- [What's New in v1.0.0](#whats-new-in-v100)
- [Machines](#machines)
- [What Works](#what-works)
- [Machine Role Hierarchy](#machine-role-hierarchy)
- [LyraHeadServer API (HEAD)](#lyraheadserver-api-head-port-18790)
- [WorkerTaskServer API (Worker)](#workertaskserver-api-worker-port-18790)
- [SOUL.md — LYRA Behavior Rules](#soulmd--lyra-behavior-rules)
- [Critical Knowledge — Bugs Already Resolved](#critical-knowledge--bugs-already-resolved)
- [Current Models](#current-models)
- [File Paths & Ports](#file-paths)
- [Running the Installer](#running-the-installer)
- [Testing Worker Communication](#testing-worker-communication)

---

## What's New in v1.0.4

### 📡 Monitoring Tab (Lyra only)

New **📡 Monitoring** tab in the Lyra GUI — agent monitoring and management without touching the log or config tab.

**Worker Registry:**
- Add workers with Name, IP, Port, Role (Junior/Senior)
- `🔍 Check` — instant health check against `/health`
- `➕ Add & Save` — persists to `workers.json`, regenerates SOUL.md immediately
- `🗑 Remove selected` — removes and persists
- Listbox click prefills all fields for editing
- On startup: loads `workers.json` automatically, prefills Target field with first worker

**Task Sender:**
- Target IP:port, task type dropdown (`web_search`, `batch_exec`, `summarize`, `validate`)
- Sends directly to `WorkerTaskServer` on the worker machine
- task_id auto-prefilled into Result Viewer after send

**Result Viewer:**
- `📥 Fetch Result` — GET `/result/<task_id>` from worker
- `📋 All Results` — GET `/results` (last 100)
- All output in formatted JSON text box

**Auto-poll:**
- Configurable interval (default 30s), Start/Stop toggle
- Updates listbox with ✅/❌ per worker

### 🗂 Worker Registry — `workers.json`

Persistent worker registry at `~/.openclaw/workers.json`:
```json
[{"ip": "192.168.2.102", "port": 18790, "name": "Junior-PC", "role": "Junior"}]
```
Every `Add & Save` and `Remove` writes `workers.json` and immediately regenerates SOUL.md so LYRA sees current workers in the same session.

### 🧠 SOUL.md — Dynamic Worker Registry Section

`## Worker Registry` section dynamically generated from `workers.json` on every SOUL.md write. LYRA gets the exact PowerShell commands to reach each worker directly:

```powershell
# Schritt 1 — Task senden
$body = '{"type":"web_search","payload":{"query":"DEINE SUCHANFRAGE"}}'
$r = Invoke-RestMethod -Method POST -Uri "http://192.168.2.102:18790/tasks" -Body $body -ContentType "application/json"
$task_id = $r.task_id

# Schritt 2 — Polling max 120s
$result = $null
for ($i=0; $i -lt 60; $i++) {
    Start-Sleep 2
    try { $result = Invoke-RestMethod "http://192.168.2.102:18790/result/$task_id"; break } catch { }
}

# Schritt 3 — Summary
$result.result.summary
```

### 🔧 WorkerTaskServer — Full Result Roundtrip

`WorkerTaskServer` now stores results locally — enabling direct result retrieval from outside:

| Method | Endpoint | Description |
|---|---|---|
| POST | `/result/<task_id>` | Store result for a completed task |
| GET | `/result/<task_id>` | Retrieve result — `{"status": "success", "result": {...}}` |
| GET | `/results` | All stored results (max 100) |

`LyraWorkerClient` and `QueuedWorkerClient` write results to `WorkerTaskServer._results` locally **before** attempting to POST to HEAD — result is always retrievable via `GET /result/<id>` even if HEAD is unreachable.

### ⚡ Task Server Auto-Start on Lyra

`LyraHeadServer` (task server) now starts automatically on Lyra — no manual click required:
- **App launch** (1s after start) — if `machine_role.json` shows Lyra role
- **Every Gateway restart** (2s after gateway.cmd started) — idempotent, silent if already running
- Manual `▶ (Re)start Task Server` button remains as fallback

### 🖥 Hardware-Aware Configuration (completed)

`HardwareProfile.detect()` now fully drives config values (previously only logged):
- `timeoutSeconds` in `openclaw.json` comes from `recommended_timeout`
- Pull entry in GUI prefilled with `recommended_model` after hardware detection
- `primary_model` in Step 14 falls back to `recommended_model` if no model pulled

### 🔒 Security Hardening (DECISION #16–19, v1.0.3 carry-forward documented)

| Decision | What | Why |
|---|---|---|
| #16 | `gateway.token` → `uuid4().hex` (32 chars) | Passes `token_too_short` audit |
| #17 | `elevated.allowFrom.webchat` → `["127.0.0.1", "::1"]` | No wildcard on loopback |
| #18 | `icacls` hardening on config files | Owner+SYSTEM only |
| #19 | `dangerouslyDisableDeviceAuth=true` — intentional | Loopback-only, no pairing friction |

---

## What's New in v1.0.3

### OpenClaw 2026.3.2 Sentinel Bug Fixes (DECISION #11 + #12)

Two new required fields in OpenClaw 2026.3.x caused `GatewayRequestError` after every install and every Web Config Admin Panel interaction. Root cause: OpenClaw auto-fills missing fields with the internal sentinel `__OPENCLAW_REDACTED__`, then immediately rejects it as invalid real data (upstream bug [#13058](https://github.com/openclaw/openclaw/issues/13058)).

**`gateway.auth.password`** — new required field in 2026.3.2. Empty string is the correct value for token-auth mode.

**`commands.ownerDisplaySecret`** — new HMAC secret for owner-ID obfuscation (2026.3.x). The Web Config Admin Panel triggers this: it reads `openclaw.json`, redacts sensitive fields for display, then writes the redacted content back to disk — destroying the secret on every config save.

Both fixes are applied at three levels:
1. `write_openclaw_config()` — written correctly from the start on fresh install
2. `setup_lyra_agent()` — adaptive check runs automatically post-gateway during installation
3. `🛠 Apply fixes + Update SOUL.md` button — for running installations without reinstall

### Universal Fix Button replaces "Update SOUL.md"

The `📜 Update SOUL.md` button has been replaced by `🛠 Apply fixes + Update SOUL.md`. It now runs all adaptive config fixes in a single pass before refreshing SOUL.md/BOOTSTRAP.md — one Gateway restart for everything. Future fixes are added here, not as new buttons.

---

## What's New in v1.0.0

### Architecture: Two-Module Split

The original 9005-line monolith has been split into two focused files:

**`OpenClawWinInstaller.py`** — GUI + New Installation flow only  
- Steps 1–16 of the installation process
- All tkinter widgets, tabs, and dialogs
- Machine role dialog
- `OpenClawWinInstaller` inherits `OpenClawOperations` — no duplication

**`OpenClawConfigManagement.py`** — all non-GUI logic  
- `OpenClawConfig` — config read/write (`openclaw.json`, `auth-profiles.json`, `SOUL.md`, `gateway.cmd`)
- `LyraDelegateToolRegistrar` — skill registration (`delegate_to_worker.js`)
- `LyraHeadServer` — HTTP task server for worker delegation (Port 18790)
- `WorkerTaskServer` — task queue server on worker machines
- `LyraWorkerClient` — worker polling loop
- `OpenClawOperations` — all `check_*`, `install_*`, `setup_*`, `run_powershell`, WSL, Ollama, gateway utilities

Version history ballast removed. All critical knowledge preserved as `⚠️ DECISION:` comments directly at the relevant code locations.

### SOUL.md: Two New Behavioral Sections

**Fehler-Eskalation** — After the same error occurs twice, LYRA must stop, read the model card / documentation, search Hugging Face Discussions, write a `[CORRECTION]` entry, and only then execute corrected code. The same code must never run a third time unchanged.

**Transformers / Hugging Face Diagnose** — Root cause documented for `AutoModelForSequenceClassification → NoneType` errors: use `AutoModel` + `trust_remote_code=True` + extract embeddings via `last_hidden_state.mean(dim=1)`. DNABERT-2 example included.

---

## Machines

| Machine | CPU | RAM | GPU | Role | Status |
|---|---|---|---|---|---|
| **Lyra machine** (192.168.2.107) | i7-8700, AVX2 ✓ | 64 GB | RTX 3050 · 6 GB VRAM + 26 GB shared | **LYRA (head)** | ✅ Production · glm-4.7-flash hybrid |
| **Junior worker machine** (192.168.2.102) | i5-2500, no AVX2 | ~32 GB | — | **Junior** | ✅ Auto-starts · qwen2.5:0.5b |

---

## What Works

### Core Infrastructure
- ✅ Gateway auto-starts at Windows login (scheduled task)
- ✅ Gateway logs in local time (TZ=Europe/Zurich set in gateway.cmd)
- ✅ Ollama model discovery via REST API — WSL, Docker Desktop, Windows-native
- ✅ LYRA responds; primary/secondary LLM selectable live
- ✅ GPU-hybrid inference: RTX 3050 (6 GB VRAM + 26 GB shared = 32 GB GPU-total)
- ✅ Browser opens with token URL — no login prompt
- ✅ `sessions.json` deleted before gateway start → fresh agent state, no stale model

### Configuration
- ✅ `openclaw.json` written correctly — no rejected schema keys
- ✅ `auth-profiles.json` — `ollama/` prefix stripped (bare model name only)
- ✅ `gateway.cmd` patched: TZ + OLLAMA_API_KEY + OPENCLAW_GATEWAY_TOKEN
- ✅ `timeoutSeconds: 3600` — correct for RTX 3050 GPU-hybrid
- ✅ `runTimeoutSeconds` intentionally absent — schema rejects it, Gateway cannot start
- ✅ `gateway.auth.password: ""` — explicit empty string prevents sentinel injection (2026.3.2+)
- ✅ `commands.ownerDisplaySecret` — random hex secret generated at install, never overwritten

### LYRA Behavior
- ✅ SOUL.md written to workspace on every install + "🛠 Apply fixes + Update SOUL.md" button
- ✅ FORCE-DELEGATE.md prevents Brave Search API requests
- ✅ Web search fallback chain works without a connected worker
- ✅ Session-start checklist: disk verified before memory accepted as truth
- ✅ Memory contradiction rule: exec output > memory → `[CORRECTION]` written
- ✅ Error escalation: same error twice → read docs → correct → then execute

### Worker Communication
- ✅ Task server auto-starts on **Lyra** at app launch + after every Gateway restart (v1.0.4)
- ✅ Task server auto-starts 1.5s after app launch on **Worker** (no manual start needed)
- ✅ Dummy task routes directly to Worker-IP:18790/tasks
- ✅ Bidirectional: result stored locally in `WorkerTaskServer._results` (v1.0.4) + POST to HEAD
- ✅ `GET /result/<task_id>` on Worker — LYRA can fetch results directly (v1.0.4)
- ✅ `workers.json` persistent registry — survives restarts (v1.0.4)
- ✅ SOUL.md Worker Registry section — LYRA knows IPs + exact PowerShell commands (v1.0.4)
- ✅ `delegate_to_worker.js` re-registered post-Gateway (Gateway overwrites skills.json on startup)

### Not set / intentionally absent
- ❌ `agents.defaults.runTimeoutSeconds` — schema rejection, Gateway cannot start
- ❌ `browser` block in initial `write_openclaw_config()` — set post-start via `openclaw config set`

---

## Machine Role Hierarchy

```
LYRA (head) ──────────────────────────────────────────────────
  i7-8700 · 64 GB RAM · RTX 3050 (32 GB GPU-total)
  Model: glm-4.7-flash (30B, 19 GB) — GPU+CPU hybrid
  Runs: OpenClaw Gateway (18789) + LyraHeadServer (18790)
  
  ↓ delegates via HTTP POST /tasks
  
Senior Worker ─────────────────────────────────────────────────
  Any machine with AVX2
  Model: qwen2.5:1.5b–3b
  Handles: complex helper tasks
  
Junior Worker ─────────────────────────────────────────────────
  Any hardware (no AVX2 required)
  Model: qwen2.5:0.5b
  Handles: web search via SearXNG, simple tasks
  
  ↑ result POSTed back to HEAD /result
```

---

## LyraHeadServer API (HEAD, Port 18790)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok", "role": "Lyra", "port": 18790}` |
| GET | `/tasks` | Open tasks waiting for a worker |
| POST | `/tasks` | Queue a task `{type, payload, task_id}` |
| POST | `/result` | Worker submits result `{task_id, status, result}` |
| GET | `/results` | Completed tasks (max. 100) |

---

## WorkerTaskServer API (Worker, Port 18790)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok", "role": "worker"}` |
| POST | `/tasks` | Receive task from HEAD |
| GET | `/results` | Tasks processed by this worker |

---

## SOUL.md — LYRA Behavior Rules

Rules are written to `~/.openclaw/workspace/SOUL.md` on every install.  
Update without reinstall: click **"🛠 Apply fixes + Update SOUL.md"** in the **🖥 Lyra Config** tab.

| Rule | What it prevents | Added |
|---|---|---|
| Delegation (web search) | Direct Brave Search / API key requests | Initial |
| Tool failure fallback | `browser → web_fetch → delegate_to_worker → curl.exe` | Initial |
| PowerShell rules | `curl` alias, `&&`, `~` path, `grep` missing in PS | Initial |
| Verify before claiming | Checking exec output before reporting state | Initial |
| Skills state | Only `delegate_to_worker.js` needed — nothing else missing | Initial |
| Memory contradiction | exec output > memory — write `[CORRECTION]` on conflict | Initial |
| Session-start checklist | Verify skills on disk before accepting memory as truth | Initial |
| Disconnect diagnosis | code=1005 explained, orphaned lock diagnosis, recovery | Initial |
| Web search without worker | SearXNG → DuckDuckGo → curl.exe fallback chain | Initial |
| Persistent self-learning | Write `[LEARNING]` entries to `memory/YYYY-MM-DD.md` | Initial |
| Fehler-Eskalation | Same error twice → read docs → `[CORRECTION]` → fix | v1.0.0 |
| Transformers diagnose | `AutoModel` + `trust_remote_code=True` for research models | v1.0.0 |

---

## Critical Knowledge — Bugs Already Resolved

### ❌ `runTimeoutSeconds` in openclaw.json — NEVER REINTRODUCE
**Problem:** OpenClaw 2026.2.26 schema rejects `agents.defaults.runTimeoutSeconds` → every openclaw command fails → Gateway cannot start.  
**Symptom:** `Invalid config: Unrecognized key: "runTimeoutSeconds"` on every command.  
**Fix:** Key removed from `write_openclaw_config()` entirely. Only valid timeout: `agents.defaults.timeoutSeconds`.

**If you have `runTimeoutSeconds` in your `openclaw.json`:**
```powershell
$j = Get-Content "$HOME\.openclaw\openclaw.json" -Raw | ConvertFrom-Json
$j.agents.defaults.PSObject.Properties.Remove('runTimeoutSeconds')
$j | ConvertTo-Json -Depth 20 | Set-Content "$HOME\.openclaw\openclaw.json" -Encoding UTF8
# Then: Gateway restart
```

### ❌ Gateway logs UTC instead of local time — NEVER REINTRODUCE
**Problem:** Node.js via Scheduled Task does not inherit Windows system timezone → UTC timestamps → 1h offset → timeout debugging misleading.  
**Fix:** `SET TZ=Europe/Zurich` in `gateway.cmd` after `@echo off`. `patch_gateway_cmd()` is idempotent.

### ❌ `timeoutSeconds` wrong value — NEVER REINTRODUCE
**History:**
- `86400` → Gateway rejected
- `7200` → too short for CPU-only, caused orphaned session-write-locks
- `28800` → too long for GPU-hybrid, 8h lock if stuck
- **`3600`** ← correct for RTX 3050 GPU-hybrid (current)

### ❌ `ollama/` prefix in auth-profiles.json — NEVER REINTRODUCE
**Problem:** Writing `"model": "ollama/glm-4.7-flash:latest"` in `auth-profiles.json` → Ollama 404 on every chat request.  
**Rule:** `openclaw.json` uses `ollama/model`. `auth-profiles.json` uses bare `model` only.  
**Fix:** Strip prefix in all three write locations: `configure_ollama_via_cli()`, `setup_lyra_agent()`, `_write_llm_to_config()`.

### ❌ `delegate_to_worker` lost after Gateway restart — NEVER REINTRODUCE
**Problem:** Gateway overwrites `skills.json` on startup → skill gone → "Tool not found".  
**Fix:** `_write_skill_file()` called post-Gateway after health-check confirms gateway is up.

### ❌ Memory accepted as truth without disk check — NEVER REINTRODUCE
**Problem:** LYRA read contaminated memory (4 Skills listed), never verified disk. Continued with wrong state.  
**Fix:** Session-start checklist — `Get-ChildItem "$HOME/.openclaw/skills" -Filter "*.js"` before any memory-based claim.

### ❌ Dummy task routed to wrong server — NEVER REINTRODUCE
**Problem:** `_send_dummy_task()` POSTed to HEAD's own server — Worker never received task.  
**Fix:** POST directly to `Worker-IP:18790/tasks`.

### ❌ Worker not running after app restart — NEVER REINTRODUCE
**Problem:** Worker components only started during installation, not on subsequent launches.  
**Fix:** `_auto_start_worker_components()` called 1.5s after app start.

### ❌ `&&` in PowerShell 5 — NEVER REINTRODUCE
**Problem:** PowerShell 5.x does not support `&&` operator.  
**Fix:** Use `;` or separate lines.

### ❌ Same Transformers error repeated without diagnosis — NEVER REINTRODUCE
**Problem:** `AutoModelForSequenceClassification` returns `NoneType` for models without a classification head. Running the same code three times does not fix it.  
**Fix:** Use `AutoModel` + `trust_remote_code=True`. Extract embeddings via `last_hidden_state.mean(dim=1)`. After the second identical error: read model card, search Hugging Face Discussions, write `[CORRECTION]`.

### ❌ `gateway.auth.password` missing — NEVER REINTRODUCE
**Problem:** OpenClaw 2026.3.2 added `password` as a required field in `gateway.auth`. If absent, it auto-fills `__OPENCLAW_REDACTED__` then rejects it: `GatewayRequestError: Sentinel value "__OPENCLAW_REDACTED__" in key gateway.auth.password is not valid as real data`.  
**Fix:** Always write `"password": ""` explicitly in `gateway.auth`. Correct value for token-auth mode. (DECISION #11)

### ❌ `commands.ownerDisplaySecret` missing — NEVER REINTRODUCE
**Problem:** OpenClaw 2026.3.x added `ownerDisplaySecret` (HMAC secret for owner-ID obfuscation) as a required field under `commands`. The Web Config Admin Panel corrupts `openclaw.json` by writing the redaction sentinel `__OPENCLAW_REDACTED__` back to disk on every config save (upstream bug #13058). Gateway then rejects it immediately.  
**Fix:** Generate a stable `uuid4().hex` at install time. Adaptive fix (`🛠 Apply fixes`) regenerates it only if absent or sentinel — never overwrites a valid existing secret. (DECISION #12)

---

## Current Models

| Machine | Model | Size | Purpose | Notes |
|---|---|---|---|---|
| Lyra (head) | glm-4.7-flash | 30B / 19 GB | **Primary** | GPU+CPU hybrid · 3600s timeout |
| Lyra (head) | voytas26/openclaw-oss-20b-deterministic | 21B / 14 GB | Alt / Test | Slower than glm |
| Lyra (head) | qwen2.5:14b | 15B / 9 GB | Primary alt | Fits in VRAM+shared easily |
| Lyra (head) | qwen2.5:7b | 8B / 5 GB | Fast fallback | Fits in 6 GB VRAM alone |
| Lyra (head) | deepseek-r1:8b | 8B / 5 GB | Reasoning tasks | |
| Junior worker | qwen2.5:0.5b | 0.5B | Only option (no AVX2) | Web search via SearXNG |
| Senior worker | qwen2.5:1.5b | 1.5B | Primary | AVX2 required |

> **GPU note:** RTX 3050 has 6 GB dedicated VRAM + 26 GB Windows shared RAM = 32 GB GPU-total.  
> Ollama automatically distributes model layers: VRAM first (fastest), overflow to shared RAM (GPU-assisted).  
> qwen2.5:7b (5 GB) fits entirely in VRAM → fastest responses. glm-4.7-flash (19 GB) uses GPU+CPU hybrid.

---

## File Paths

```
~\.openclaw\openclaw.json                           Main config (timeoutSeconds: from HardwareProfile!)
~\.openclaw\gateway.cmd                             Gateway starter (TZ + API keys patched)
~\.openclaw\machine_role.json                       Role + head IP + SearXNG URL
~\.openclaw\workers.json                            Worker registry (Monitoring Tab) — v1.0.4
~\.openclaw\workspace\SOUL.md                       LYRA behavior rules (incl. Worker Registry)
~\.openclaw\workspace\FORCE-DELEGATE.md             Backup delegation constraint
~\.openclaw\workspace\memory\YYYY-MM-DD.md          LYRA's persistent self-learning
~\.openclaw\workspace\memory\heartbeat-state.json   Heartbeat tracking state
~\.openclaw\skills\delegate_to_worker.js            JS tool (only skill needed)
~\.openclaw\agents\main\agent\auth-profiles.json    Ollama provider (no ollama/ prefix!)
~\.openclaw\agents\main\sessions\sessions.json      Delete before gateway start
```

### Ports

| Port | Service |
|---|---|
| `18789` | OpenClaw gateway (WebSocket + HTTP dashboard) |
| `18790` | LyraHeadServer (HEAD) + WorkerTaskServer (Worker) |
| `11434` | Ollama API |
| `8080`  | SearXNG (Docker container) — used as web_fetch fallback |

---

## Running the Installer

```bash
python OpenClawWinInstaller.py
```

Both files must be in the same directory:
```
OpenClawWinInstaller.py
OpenClawConfigManagement.py
```

### Open dashboard (LYRA head)

```
http://127.0.0.1:18789/?token=lyra-local-token
```

> ⚠️ **Always include `?token=...`** — without it the WebSocket returns code=4008.

---

## Testing Worker Communication

### 1. Check component status (on Worker)
In **⚙ Worker Config** → **🔄 Check components** — both Task Server and Worker Client should show ✅.

### 2. Send Dummy Task from HEAD
In **🖥 Lyra Config** → **🧪 Dummy Task Test**:
1. Enter **Worker IP** (e.g. `192.168.2.102`) or click **🔄 Last worker**
2. Enter a query
3. Click **▶ Send task + wait**

### 3. Send task via PowerShell
```powershell
$body = @{
    type    = "batch_exec"
    payload = @{ cmd = "hostname; Get-Date" }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://192.168.2.102:18790/tasks" -Method Post `
    -Body $body -ContentType "application/json"
```

### 4. Check results (HEAD)
```powershell
Invoke-RestMethod http://127.0.0.1:18790/results | ConvertTo-Json -Depth 10
```

---

## PowerShell Quick Reference

```powershell
# Download — CORRECT
Invoke-WebRequest -Uri "https://example.com/file" -OutFile "$HOME\file.txt"
curl.exe -s "https://example.com/file" -o "$HOME\file.txt"

# Download — WRONG (curl is an alias with different syntax in PS)
curl -s "https://example.com/file" -o file.txt   # ← FAILS

# Chain commands — CORRECT (PS5)
Set-Location "$HOME\.openclaw"; openclaw status

# Chain commands — WRONG (PS5 does not support &&)
cd "$HOME\.openclaw" && openclaw status           # ← FAILS

# Linux tools — use WSL
wsl bash -lc "grep 'pattern' /mnt/c/path/file.txt"

# Verify Gateway timezone
Get-TimeZone
# After fix: gateway logs should match system clock
```

---

## License

This project is a **private, non-commercial hobby project**.

## Acknowledgements

Built on:
- [OpenClaw](https://github.com/openclaw) — open-source AI agent framework
- [Ollama](https://ollama.com) — local LLM runtime
- [SearXNG](https://searxng.github.io/searxng/) — privacy-respecting search engine

---

*"One click and LYRA lives – the rest is history"* 🌀
