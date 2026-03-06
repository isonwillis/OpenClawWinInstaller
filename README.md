# OpenClawWinInstaller

> **Status: v1.0.4 — PRODUCTION READY** · 2026-03-06

A fully automated Windows installer that sets up **OpenClaw** with a local LLM (LYRA via Ollama).  
After running the script, LYRA is immediately ready to use — no manual configuration, no token issues, no approval prompts.

From v1.0.0 the system supports a **machine role hierarchy**: a LYRA head orchestrates any number of Junior/Senior workers via an integrated HTTP task server with **bidirectional communication**.  
From v1.0.4 the system also supports **external LLM agents** (OpenAI-compatible APIs, remote Ollama) in a unified monitoring interface.

**Stack:** `Python (tkinter GUI)` → `PowerShell` → `OpenClaw (npm)` + `Ollama (Windows-native / Docker / WSL)`

---

## ✨ The Philosophy

*"One click and LYRA lives – the rest is history"* 🌀

- ✅ 50+ components automatically installed
- ✅ 67+ edge cases fixed and documented
- ✅ 3-stage fallback strategies
- ✅ Unified agent registry: workers + external LLMs in one interface
- ✅ Bidirectional worker communication — result stored locally + posted to HEAD
- ✅ Auto-display of worker results — no manual polling needed
- ✅ Worker + Task Server auto-start on every app launch
- ✅ LYRA knows her agents — persistent registry, direct exec access
- ✅ External LLM delegation: DeepSeek, OpenAI-compatible APIs
- ✅ Hardware-aware config: timeout + model from HardwareProfile
- ✅ Clean three-module architecture: Installer · Config · Monitoring

---

## Table of Contents

- [What's New in v1.0.4](#whats-new-in-v104)
- [What's New in v1.0.3](#whats-new-in-v103)
- [What's New in v1.0.0](#whats-new-in-v100)
- [Three-Module Architecture](#three-module-architecture)
- [Machines](#machines)
- [What Works](#what-works)
- [Machine Role Hierarchy](#machine-role-hierarchy)
- [LyraHeadServer API](#lyraheadserver-api-head-port-18790)
- [WorkerTaskServer API](#workertaskserver-api-worker-port-18790)
- [SOUL.md — LYRA Behavior Rules](#soulmd--lyra-behavior-rules)
- [Critical Knowledge — Bugs Already Resolved](#critical-knowledge--bugs-already-resolved)
- [Current Models](#current-models)
- [File Paths & Ports](#file-paths--ports)
- [Running the Installer](#running-the-installer)

---

## What's New in v1.0.4

### 📡 Unified Agent Registry (Monitoring Tab — complete rewrite)

The Monitoring Tab has been completely rewritten. The old Worker-only registry is now a **unified agent list** supporting four agent types:

| Type | Protocol | Endpoints |
|---|---|---|
| `worker` | openclaw (async) | POST /tasks · GET /result/\<id\> |
| `ollama` | ollama (sync) | POST /api/chat · GET /api/tags |
| `openai` | openai (sync) | POST /v1/chat/completions · GET /v1/models |
| `custom` | openai or ollama | best-effort /health |

**Field visibility** is dynamic — irrelevant fields hidden by type:

| Type | Visible Fields |
|---|---|
| `worker` | URL/IP · Port · Name · Role |
| `ollama` | URL · Port · Name · Role · Model |
| `openai` | URL · Name · Role · Model · API Key _(Port hidden)_ |
| `custom` | All fields |

**Inline edit** — click any agent → all fields prefill → modify → `💾 Update Agent`. No re-entry required.

**Auto-switch task type** — clicking an agent switches the Task Sender dropdown automatically: `openai` → `chat (openai)`, `ollama` → `chat (ollama)`, `worker` → `web_search`.

### 📊 Color-Coded Health Status

Background poller (30s daemon thread, no log spam). Status via `itemconfig(foreground=...)` — emoji render black on Windows, colored text does not:

| Indicator | Color | Meaning |
|---|---|---|
| `[??]` | Grey | Not yet polled |
| `[OK]` | Green | Online |
| `[!!]` | Red | Unreachable |

Health check endpoint per type: `worker` → GET /health · `ollama` → GET /api/tags · `openai` → GET /models

### 📥 Result Viewer — Auto-Display

Results from OpenClaw workers appear **automatically** without any manual fetch:

1. Worker POSTs result → `LyraHeadServer`
2. `on_result_callback` fires → `root.after(0, _on_result_received)` — safe main-thread delivery
3. Result appears in viewer instantly

For OpenAI/Ollama chat: response shown synchronously inline — no task_id, no polling.

### 🔧 LyraHeadServer — Critical Fixes

| Fix | Detail |
|---|---|
| `GET /result/<task_id>` | **Was missing entirely.** New endpoint — lookup by task_id in `_results` list |
| `GET /results` | **Bug:** `_results` is a list, not a dict. Removed erroneous `.values()` call |
| `on_result_callback` | New hook — fires when worker POSTs result. Used by MonitoringTab for auto-display |

### 🌐 External LLM Support

Any OpenAI-compatible API works. **DeepSeek** setup:

| Field | Value |
|---|---|
| URL | `https://api.deepseek.com/v1` |
| Type | `openai` |
| Model | `deepseek-chat` or `deepseek-reasoner` |
| API Key | from platform.deepseek.com |

> The `/v1` suffix is key: code appends `/chat/completions` → identical path to OpenAI. No provider-specific branching.

### 🔄 HTTP Redirect Handling

`_diag_api()` now follows 301/302/307/308 redirects automatically (up to 5 hops), preserving method and `Authorization` header.

### 🔒 Persistent Sentinel Fix (Third Defense Layer)

`_post_gateway_sentinel_fix()` runs 500ms after every gateway health-check. Three-layer defense against upstream bug [#13058](https://github.com/openclaw/openclaw/issues/13058):

1. `write_openclaw_config()` — correct from the start
2. `setup_lyra_agent()` — adaptive post-install fix
3. `_post_gateway_sentinel_fix()` — fires after **every** gateway start ← NEW

### 🗂 workers.json — Extended Schema

```json
[
  {
    "type": "worker", "ip": "192.168.2.102", "port": 18790,
    "name": "Junior-PC", "role": "Junior", "protocol": "openclaw",
    "model": "", "api_key": ""
  },
  {
    "type": "openai", "url": "https://api.deepseek.com/v1", "port": 443,
    "name": "DeepSeek", "role": "External", "protocol": "openai",
    "model": "deepseek-chat", "api_key": "sk-..."
  }
]
```

SOUL.md `## Agent Registry` section dynamically generated from `workers.json`. API keys masked (`abc***…***xyz`).

### 📖 SOUL.md — New Sections (v1.0.4)

| Section | Content |
|---|---|
| LLM Timeout Fallback | 3x timeout → switch to `qwen2.5:7b` · VRAM diagnosis |
| Ollama exit status 2 | 3 causes: VRAM pressure · corrupt blob · version bug |
| memorySearch sentinel | Three defense layers documented |
| PowerShell `${var}:` | `$date:` = drive reference → always use `${date}:` |
| Agent Registry | All agent types, masked API keys, PS commands for LYRA |

---

## What's New in v1.0.3

### OpenClaw 2026.3.2 Sentinel Bug Fixes (DECISION #11 + #12)

Two required fields in OpenClaw 2026.3.x caused `GatewayRequestError` after every install and every Web Config Admin Panel interaction (upstream bug [#13058](https://github.com/openclaw/openclaw/issues/13058)):

**`gateway.auth.password`** — Empty string is the correct value for token-auth mode.

**`commands.ownerDisplaySecret`** — HMAC secret corrupted by Web Config Admin Panel on every config save.

Both fixes applied at three levels: `write_openclaw_config()` · `setup_lyra_agent()` · `🛠 Apply fixes` button.

### Universal Fix Button

`📜 Update SOUL.md` replaced by `🛠 Apply fixes + Update SOUL.md`. Runs all adaptive config fixes in one pass.

---

## What's New in v1.0.0

### Three-Module Architecture

The original 9005-line monolith split into three focused files:

- **`OpenClawWinInstaller.py`** — GUI + installation flow (Steps 1–16, all tkinter)
- **`OpenClawConfigManagement.py`** — all logic: config, servers, worker client, operations
- **`OpenClawAgentMonitoring.py`** — self-contained Monitoring Tab (no Installer dependency)

### SOUL.md: Two New Behavioral Sections

**Fehler-Eskalation** — same error twice → stop → read docs → `[CORRECTION]` → fix.  
**Transformers diagnose** — `AutoModel` + `trust_remote_code=True` for research models.

---

## Three-Module Architecture

```
OpenClawWinInstaller.py        3 454 lines   GUI + installation flow
OpenClawConfigManagement.py    5 759 lines   All logic, servers, config
OpenClawAgentMonitoring.py       957 lines   Monitoring Tab (self-contained)
─────────────────────────────────────────
Total                         10 170 lines
```

---

## Machines

| Machine | CPU | RAM | GPU | Role |
|---|---|---|---|---|
| **Lyra** (192.168.2.107) | i7-8700, AVX2 ✓ | 64 GB | RTX 3050 · 6 GB + 26 GB shared | **HEAD** |
| **Junior** (192.168.2.102) | i5-2500, no AVX2 | ~32 GB | — | **Worker** |
| **DeepSeek API** | api.deepseek.com/v1 | — | — | **External LLM** |

---

## What Works

### Agent Registry
- ✅ Unified registry: OpenClaw workers + external LLMs in one list
- ✅ workers.json persistent — survives restarts
- ✅ Inline edit — click agent → fields prefill → modify → save
- ✅ Auto-switch task type on agent select
- ✅ Color-coded health status (green/red/grey via itemconfig)
- ✅ Silent background polling every 30s
- ✅ External LLM: DeepSeek, OpenAI-compatible APIs

### Worker Communication
- ✅ Task server auto-starts on **Lyra** at launch + after every Gateway restart
- ✅ Task server auto-starts 1.5s after launch on **Worker**
- ✅ Bidirectional: result stored locally + POSTed to HEAD
- ✅ `GET /result/<task_id>` on HeadServer — fixed v1.0.4
- ✅ `GET /results` on HeadServer — fixed v1.0.4
- ✅ Auto-display: result appears without manual fetch
- ✅ SOUL.md Agent Registry — LYRA knows all agents + exact PS commands

### Core Infrastructure
- ✅ Gateway auto-starts at Windows login
- ✅ Gateway logs in local time (TZ=Europe/Zurich)
- ✅ Ollama model discovery via REST API — WSL, Docker, Windows-native
- ✅ GPU-hybrid inference: RTX 3050 (6 GB VRAM + 26 GB shared)
- ✅ `sessions.json` deleted before gateway start — fresh agent state

### LYRA Behavior
- ✅ SOUL.md written on every install + `🛠 Apply fixes + Update SOUL.md`
- ✅ FORCE-DELEGATE.md prevents Brave Search API requests
- ✅ Session-start checklist: disk verified before memory accepted as truth
- ✅ Error escalation: same error twice → read docs → `[CORRECTION]`
- ✅ Persistent self-learning: `[LEARNING]` entries to `memory/YYYY-MM-DD.md`

---

## Machine Role Hierarchy

```
LYRA (head) ──────────────────────────────────────────────────
  i7-8700 · 64 GB RAM · RTX 3050 (32 GB GPU-total)
  Model: glm-4.7-flash (30B, 19 GB) — GPU+CPU hybrid
  Runs: OpenClaw Gateway (18789) + LyraHeadServer (18790)
  
  ↓ delegates via HTTP POST /tasks
  
Junior Worker ─────────────────────────────────────────────────
  i5-2500 · no AVX2 · qwen2.5:0.5b
  Handles: web search via SearXNG, simple tasks
  
  ↑ result POSTed back to HEAD /result

External LLM ──────────────────────────────────────────────────
  OpenAI-compatible API (DeepSeek, OpenAI, LM Studio, ...)
  Accessed via Monitoring Tab → chat (openai) / chat (ollama)
  Synchronous — no task_id, response inline
```

---

## LyraHeadServer API (HEAD, Port 18790)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok", "role": "Lyra", "port": 18790}` |
| GET | `/tasks` | Open tasks waiting for a worker |
| POST | `/tasks` | Queue a task `{type, payload, task_id}` |
| POST | `/result` | Worker submits result `{task_id, status, result}` |
| GET | `/result/<task_id>` | Retrieve single result — **fixed v1.0.4** |
| GET | `/results` | Completed tasks max 100 — **fixed v1.0.4** |

---

## WorkerTaskServer API (Worker, Port 18790)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok", "role": "Worker", "port": 18790}` |
| POST | `/tasks` | Receive task from HEAD |
| POST | `/result/<task_id>` | Store result locally |
| GET | `/result/<task_id>` | Retrieve stored result |
| GET | `/results` | All results on this worker (max 100) |

---

## SOUL.md — LYRA Behavior Rules

| Rule | What it prevents | Added |
|---|---|---|
| Delegation (web search) | Direct Brave Search / API key requests | Initial |
| Tool failure fallback | `browser → web_fetch → delegate_to_worker → curl.exe` | Initial |
| PowerShell rules | `curl` alias, `&&`, `~` path, `grep` | Initial |
| Session-start checklist | Memory claimed without disk verification | Initial |
| Memory contradiction | exec output > memory → write `[CORRECTION]` | Initial |
| Web search without worker | SearXNG → DuckDuckGo → curl.exe fallback | Initial |
| Fehler-Eskalation | Same error twice → read docs → `[CORRECTION]` | v1.0.0 |
| Transformers diagnose | `AutoModel` + `trust_remote_code=True` | v1.0.0 |
| LLM Timeout Fallback | 3x timeout → `qwen2.5:7b` · nvidia-smi diagnosis | v1.0.4 |
| Ollama exit status 2 | VRAM · corrupt blob · version bug | v1.0.4 |
| memorySearch sentinel | Three defense layers | v1.0.4 |
| PowerShell `${var}:` | `$date:` = drive reference | v1.0.4 |
| Agent Registry | All types, masked keys, PS commands | v1.0.4 |
| Persistent self-learning | `[LEARNING]` + `[SOUL-UPDATE-VORSCHLAG]` | v1.0.4 |

---

## Critical Knowledge — Bugs Already Resolved

### ❌ `_results.values()` in LyraHeadServer — NEVER REINTRODUCE
`_results` is a `list`. Calling `.values()` raises `AttributeError` on `GET /results`. Also `GET /result/<task_id>` was missing entirely.  
**Fix:** `list(_results)[-100:]`. New `/result/<task_id>` endpoint with `next()` lookup.

### ❌ Result fetched from Worker instead of HeadServer — NEVER REINTRODUCE
Worker POSTs result to `LyraHeadServer` immediately after completion — result is no longer on worker.  
**Fix:** All result fetching from `localhost:18790`. `on_result_callback` for auto-display.

### ❌ IP address loses port when stored as `url` field — NEVER REINTRODUCE
`_collect_form` stored bare IPs in the `url` field → `_agent_base_url` returned `http://192.168.x.x` without port.  
**Fix:** IPs → `ip` field. Real URLs → `url` field. `_agent_base_url` uses `ip:port` for IPs.

### ❌ DeepSeek base_url without `/v1` — NEVER REINTRODUCE
Use `https://api.deepseek.com/v1` as base_url. Code appends `/chat/completions` → identical to OpenAI. No provider detection needed.

### ❌ `memorySearch` sentinel returns after every Gateway start — NEVER REINTRODUCE
Gateway re-injects sentinel on every start (upstream bug [#13058](https://github.com/openclaw/openclaw/issues/13058)).  
**Fix:** `_post_gateway_sentinel_fix()` runs 500ms after every health-check.

### ❌ `runTimeoutSeconds` in openclaw.json — NEVER REINTRODUCE
Schema rejected → Gateway cannot start. Only `agents.defaults.timeoutSeconds` is valid.

### ❌ Gateway logs UTC instead of local time — NEVER REINTRODUCE
**Fix:** `SET TZ=Europe/Zurich` in `gateway.cmd`.

### ❌ `timeoutSeconds` wrong value — NEVER REINTRODUCE
`86400` rejected · `7200` too short · `28800` too long · **`3600`** ← correct for RTX 3050

### ❌ `ollama/` prefix in auth-profiles.json — NEVER REINTRODUCE
`openclaw.json` uses `ollama/model`. `auth-profiles.json` uses bare model name only.

### ❌ `delegate_to_worker` lost after Gateway restart — NEVER REINTRODUCE
Gateway overwrites `skills.json` on startup. **Fix:** `_write_skill_file()` called post-Gateway.

### ❌ `&&` in PowerShell 5 — NEVER REINTRODUCE
**Fix:** Use `;` or separate lines.

### ❌ `$date:` PowerShell drive reference — NEVER REINTRODUCE
`"[LEARNING] $date: text"` — PS interprets `$date:` as a drive reference.  
**Fix:** Always `${date}:` when a variable directly precedes a colon.

---

## Current Models

| Machine | Model | Size | Notes |
|---|---|---|---|
| Lyra (head) | glm-4.7-flash | 30B / 19 GB | Primary · GPU+CPU hybrid · 3600s timeout |
| Lyra (head) | qwen2.5:14b | 9 GB | Primary alt |
| Lyra (head) | qwen2.5:7b | 5 GB | Fits in VRAM alone — fastest fallback |
| Lyra (head) | deepseek-r1:8b | 5 GB | Reasoning tasks |
| Junior worker | qwen2.5:0.5b | 0.5B | No AVX2 · web search via SearXNG |
| External | deepseek-chat | API | DeepSeek V3.2 · 128K · non-thinking |
| External | deepseek-reasoner | API | DeepSeek R1 · 128K · thinking mode |

> **GPU:** RTX 3050 · 6 GB VRAM + 26 GB shared = 32 GB GPU-total. qwen2.5:7b fits entirely in VRAM → fastest. glm-4.7-flash uses GPU+CPU hybrid.

---

## File Paths & Ports

```
~\.openclaw\openclaw.json                           Main config
~\.openclaw\gateway.cmd                             Gateway starter (TZ + tokens)
~\.openclaw\machine_role.json                       Role + head IP + SearXNG URL
~\.openclaw\workers.json                            Unified agent registry (all types)
~\.openclaw\workspace\SOUL.md                       LYRA behavior rules + Agent Registry
~\.openclaw\workspace\BOOTSTRAP.md                  Diagnostic knowledge base
~\.openclaw\workspace\FORCE-DELEGATE.md             Delegation constraints
~\.openclaw\workspace\memory\YYYY-MM-DD.md          LYRA self-learning entries
~\.openclaw\skills\delegate_to_worker.js            Only required skill
~\.openclaw\agents\main\agent\auth-profiles.json    Ollama provider (no ollama/ prefix!)
~\.openclaw\agents\main\sessions\sessions.json      Delete before gateway start
```

| Port | Service |
|---|---|
| `18789` | OpenClaw gateway (WebSocket + HTTP dashboard) |
| `18790` | LyraHeadServer (HEAD) + WorkerTaskServer (Worker) |
| `11434` | Ollama API |
| `8080` | SearXNG (Docker) — web_fetch fallback |
| `443` | External LLM APIs (DeepSeek, OpenAI) |

---

## Running the Installer

```bash
python OpenClawWinInstaller.py
```

All three files in the same directory:
```
OpenClawWinInstaller.py
OpenClawConfigManagement.py
OpenClawAgentMonitoring.py
```

Dashboard (LYRA head):
```
http://127.0.0.1:18789/?token=lyra-local-token
```

> ⚠️ **Always include `?token=...`** — without it the WebSocket returns code=4008.

---

## PowerShell Quick Reference

```powershell
# Download — CORRECT
Invoke-WebRequest -Uri "https://example.com/file" -OutFile "$HOME\file.txt"
curl.exe -s "https://example.com/file" -o "$HOME\file.txt"

# Download — WRONG (curl is an alias in PS)
curl -s "https://example.com/file" -o file.txt       # ← FAILS

# Chain — CORRECT (PS5)
Set-Location "$HOME\.openclaw"; openclaw status

# Chain — WRONG (PS5 does not support &&)
cd "$HOME\.openclaw" && openclaw status               # ← FAILS

# Variable before colon — CORRECT
$entry = "[LEARNING] ${date}: text"

# Variable before colon — WRONG (drive reference)
$entry = "[LEARNING] $date: text"                     # ← FAILS
```

---

## License

Private, non-commercial hobby project.

## Acknowledgements

- [OpenClaw](https://github.com/openclaw) — open-source AI agent framework
- [Ollama](https://ollama.com) — local LLM runtime
- [SearXNG](https://searxng.github.io/searxng/) — privacy-respecting search engine

---

*"One click and LYRA lives – the rest is history"* 🌀
