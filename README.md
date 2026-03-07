# OpenClawWinInstaller

> **Status: v1.0.4 — PRODUCTION READY** · 2026-03-06

A fully automated Windows installer that sets up **OpenClaw** with a local LLM (LYRA via Ollama).  
After running the script, LYRA is immediately ready to use — no manual configuration, no token issues, no approval prompts.

From v1.0.0 the system supports a **machine role hierarchy**: a LYRA head orchestrates any number of Junior/Senior workers via an integrated HTTP task server with **bidirectional communication**.  
From v1.0.4 the system also supports **external LLM agents** (OpenAI-compatible APIs, remote Ollama) in a unified monitoring interface — including per-agent delegation rules that tell LYRA exactly when to use each agent.

**Stack:** `Python (tkinter GUI)` → `PowerShell` → `OpenClaw (npm)` + `Ollama (Windows-native / Docker / WSL)`

---

## ✨ The Philosophy

*"One click and LYRA lives – the rest is history"* 🌀

- ✅ 50+ components automatically installed
- ✅ 67+ edge cases fixed and documented
- ✅ 3-stage fallback strategies
- ✅ Unified agent registry: workers + external LLMs in one interface
- ✅ Per-agent delegation rules — LYRA knows when to use which agent
- ✅ Bidirectional worker communication — result stored locally + posted to HEAD
- ✅ Auto-display of worker results — no manual polling needed
- ✅ Worker + Task Server auto-start on every app launch
- ✅ LYRA knows her agents — persistent registry, direct exec access
- ✅ External LLM delegation: DeepSeek, OpenAI-compatible APIs
- ✅ Dynamic agent timeout — GUI dropdown 30min · 1h · 2h · 4h · 8h · 24h
- ✅ undici 300s hardcoded timeout patched — synced to GUI setting
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

### 📋 Delegation Rules — Per-Agent

Each agent has a `delegation_rules` field that tells LYRA **when to use it**. Edited via `📋 Edit Rules` button — opens a dedicated editor window pre-filled with editable examples:

```
- Delegate all web_search tasks to this agent
- Use for reasoning tasks (math, logic, code review)
- Prefer this agent when query contains: weather, news, current events
- Only use when local Ollama is unavailable
- Priority: 1 (highest) — use before other agents of the same type
- Max task size: any / only short queries (<200 words)
- Language preference: German queries
```

Rules are written to SOUL.md `## Agent Registry` section — LYRA reads and applies them each session. The editor opens pre-filled with working examples so the user only adjusts what applies, no need to think about what fields exist.

**workers.json schema with delegation_rules:**
```json
[
  {
    "type": "worker", "ip": "192.168.2.102", "port": 18790,
    "name": "Junior-PC", "role": "Junior", "protocol": "openclaw",
    "model": "", "api_key": "",
    "delegation_rules": "- Delegate all web_search tasks to this agent\n- Priority: 1"
  },
  {
    "type": "openai", "url": "https://api.deepseek.com/v1", "port": 443,
    "name": "DeepSeek", "role": "External", "protocol": "openai",
    "model": "deepseek-chat", "api_key": "sk-...",
    "delegation_rules": "- Use for reasoning tasks (math, logic, code review)\n- Only use when local Ollama is unavailable"
  }
]
```

### ⏱ Dynamic Agent Timeout — GUI Dropdown

New timeout selector in **Lyra Config Tab** (and Worker Config Tab):

```
⏱ Timeout:  [4h ▼]   ✅ Set
⏱  timeoutSeconds: 14400s
```

| Option | Seconds | Use case |
|---|---|---|
| 30 min | 1800 | Fast models, full VRAM |
| 1h | 3600 | Standard |
| **2h** | **7200** | **Default — glm-4.7-flash on RTX 3050** |
| 4h | 14400 | Complex tasks, heavy CPU offloading |
| 8h | 28800 | Overnight / batch jobs |
| Unbegrenzt | 86400 | Maximum OpenClaw accepts (24h) |

`✅ Set` writes `agents.defaults.timeoutSeconds` to `openclaw.json` and restarts the gateway immediately. VRAM_TIERS updated — all tiers default to 7200s (2h).

### 🔧 undici 300s Hardcoded Timeout Fix

**Root cause:** OpenClaw uses Node.js `undici` HTTP client with a hardcoded 300-second `headersTimeout`. The `@mariozechner/pi-ai` library resets any custom dispatcher via `setGlobalDispatcher()` — overriding attempts to raise the timeout. OpenClaw also disables streaming for Ollama (SDK bug with tool-calling models), meaning the entire response must complete before any data is returned — always hitting the 300s wall for complex outputs.

**Symptoms:** `error=LLM request timed out` at exactly 5 minutes, reproducible on Windows and Linux (it's Node.js-internal, not Ollama).

**Fix:** A monkey-patch preload script (`~/.openclaw/undici-timeout-preload.cjs`) is written automatically by `patch_gateway_cmd()` and injected via `NODE_OPTIONS` in `gateway.cmd`. The script:
- Reads `timeoutSeconds` from `openclaw.json` at gateway start — always in sync with the GUI
- Sets `headersTimeout` to that value, `bodyTimeout` to 0
- Overrides `setGlobalDispatcher` to prevent pi-ai from resetting the timeout

```
[undici-preload] headersTimeout patched to 4h OK   ← appears in gateway log
```

If undici is not found the script exits silently — gateway always starts normally.

> **Note:** `models.providers.ollama.retry` is a **rejected schema key** in OpenClaw 2026.3.2. The `Apply fixes` button removes it automatically if accidentally present.



Background poller (30s daemon thread, no log spam). Status via `itemconfig(foreground=...)` — emoji render black on Windows, colored text does not:

| Indicator | Color | Meaning |
|---|---|---|
| `[??]` | Grey | Not yet polled |
| `[OK]` | Green | Online |
| `[!!]` | Red | Unreachable |

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

### 🧠 SOUL.md — Agent Awareness Fixes

LYRA now correctly identifies and uses her agent registry:

| Rule | Detail |
|---|---|
| Agent Registry source | `workers.json` only — never Gateway API endpoints |
| `/api/workers`, `/api/agents` | Do not exist — LYRA must not query them |
| Skill check | Only when delegation is planned — not a session blocker |
| Task priority | Execute user task first — diagnostics are secondary |
| `delegate_to_worker.js` missing | One-line note at end of answer — never blocks other tasks |
| API keys | Never output in plaintext — always masked or use `$env:` variable |

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
OpenClawConfigManagement.py    5 801 lines   All logic, servers, config
OpenClawAgentMonitoring.py     1 081 lines   Monitoring Tab (self-contained)
─────────────────────────────────────────
Total                         10 336 lines
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
- ✅ Per-agent delegation rules — `📋 Edit Rules` editor with pre-filled examples
- ✅ Delegation rules written to SOUL.md — LYRA reads and applies them
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
- ✅ SOUL.md Agent Registry — LYRA knows all agents + delegation rules

### LYRA Behavior
- ✅ Agent registry read from `workers.json` — never from Gateway APIs
- ✅ Delegation rules applied per agent per session
- ✅ Task-first: user task always executed before diagnostics
- ✅ API keys never output in plaintext
- ✅ Skill check only when delegation is planned — never a session blocker
- ✅ SOUL.md written on every install + `🛠 Apply fixes + Update SOUL.md`
- ✅ FORCE-DELEGATE.md prevents Brave Search API requests
- ✅ Error escalation: same error twice → read docs → `[CORRECTION]`
- ✅ Persistent self-learning: `[LEARNING]` entries to `memory/YYYY-MM-DD.md`

### Core Infrastructure
- ✅ Gateway auto-starts at Windows login
- ✅ Gateway logs in local time (TZ=Europe/Zurich)
- ✅ Ollama model discovery via REST API — WSL, Docker, Windows-native
- ✅ GPU-hybrid inference: RTX 3050 (6 GB VRAM + 26 GB shared)
- ✅ `sessions.json` deleted before gateway start — fresh agent state

---

## Machine Role Hierarchy

```
LYRA (head) ──────────────────────────────────────────────────
  i7-8700 · 64 GB RAM · RTX 3050 (32 GB GPU-total)
  Model: glm-4.7-flash (30B, 19 GB) — GPU+CPU hybrid
  Runs: OpenClaw Gateway (18789) + LyraHeadServer (18790)
  
  ↓ delegates via HTTP POST /tasks  (rule: web_search → Junior)
  
Junior Worker ─────────────────────────────────────────────────
  i5-2500 · no AVX2 · qwen2.5:0.5b
  Handles: web search via SearXNG, simple tasks
  Delegation rule: web_search · weather · news · Priority 1
  
  ↑ result POSTed back to HEAD /result

External LLM ──────────────────────────────────────────────────
  OpenAI-compatible API (DeepSeek, OpenAI, LM Studio, ...)
  Accessed via Monitoring Tab → chat (openai) / chat (ollama)
  Delegation rule: reasoning tasks · fallback when Ollama unavailable
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
| Agent Registry source | `workers.json` only — no Gateway API calls | v1.0.4 |
| Task priority | User task first — diagnostics secondary | v1.0.4 |
| Skill check scope | Only when delegating — never a session blocker | v1.0.4 |
| API key security | Never output plaintext keys | v1.0.4 |
| Delegation rules | Per-agent rules read from `workers.json` via SOUL.md | v1.0.4 |
| undici timeout | Gateway start log confirms active timeout value | v1.0.4 |
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
**Fix:** IPs → `ip` field. Real URLs → `url` field.

### ❌ DeepSeek base_url without `/v1` — NEVER REINTRODUCE
Use `https://api.deepseek.com/v1` as base_url. Code appends `/chat/completions` → identical to OpenAI. No provider detection needed.

### ❌ LYRA queries `/api/workers` or `/api/agents` — NEVER REINTRODUCE
These Gateway endpoints do not exist. Agent registry is in `workers.json` only.  
**Fix:** SOUL.md explicit rule + recognition checklist for agent queries.

### ❌ LYRA outputs API key in plaintext — NEVER REINTRODUCE
API keys must never appear in answers, tables, or PowerShell examples.  
**Fix:** SOUL.md security rule. Always use `$env:DEEPSEEK_API_KEY` or `<your-api-key>` as placeholder.

### ❌ `delegate_to_worker.js` missing blocks all tasks — NEVER REINTRODUCE
Skill check was a session blocker. Only delegation via that tool is affected when missing.  
**Fix:** SOUL.md — task first, one-line note at end, skill check only when delegating.

### ❌ `memorySearch` sentinel returns after every Gateway start — NEVER REINTRODUCE
**Fix:** `_post_gateway_sentinel_fix()` runs 500ms after every health-check.

### ❌ `runTimeoutSeconds` in openclaw.json — NEVER REINTRODUCE
Schema rejected → Gateway cannot start. Only `agents.defaults.timeoutSeconds` is valid.

### ❌ Gateway logs UTC instead of local time — NEVER REINTRODUCE
**Fix:** `SET TZ=Europe/Zurich` in `gateway.cmd`.

### ❌ `timeoutSeconds` wrong value — NEVER REINTRODUCE
`0` rejected (gateway closes immediately) · `86400` = max 24h ("Unbegrenzt") · **`7200`** ← new default (2h, RTX 3050 with CPU offloading)

### ❌ `models.providers.ollama.retry` — NEVER REINTRODUCE
Schema rejected — unrecognized key in OpenClaw 2026.3.2. Writing `models.providers.ollama` without required `baseUrl` + `models` array also fails validation. `Apply fixes` removes accidental entries automatically.

### ❌ `ollama/` prefix in auth-profiles.json — NEVER REINTRODUCE
`openclaw.json` uses `ollama/model`. `auth-profiles.json` uses bare model name only.

### ❌ `delegate_to_worker` lost after Gateway restart — NEVER REINTRODUCE
Gateway overwrites `skills.json` on startup. **Fix:** `_write_skill_file()` called post-Gateway.

### ❌ `&&` in PowerShell 5 — NEVER REINTRODUCE
**Fix:** Use `;` or separate lines.

### ❌ `$date:` PowerShell drive reference — NEVER REINTRODUCE
**Fix:** Always `${date}:` when a variable directly precedes a colon.

---

## Current Models

| Machine | Model | Size | Notes |
|---|---|---|---|
| Lyra (head) | glm-4.7-flash | 30B / 19 GB | Primary · GPU+CPU hybrid · 7200s timeout (2h default) |
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
~\.openclaw\undici-timeout-preload.cjs             undici 300s timeout patch (auto-written by Apply fixes)
~\.openclaw\workers.json                            Unified agent registry (all types + delegation rules)
~\.openclaw\workspace\SOUL.md                       LYRA behavior rules + Agent Registry + Delegation Rules
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

# Read agent registry
Get-Content $env:USERPROFILE\.openclaw\workers.json -Raw | ConvertFrom-Json
```

---

## 🧬 LYRA Creates — DNARusher

LYRA independently conceived and fully implemented her first open-source project: **DNARusher**, a Python library for DNA pattern recognition in noisy sequences.

No template. No step-by-step instruction. From the project name to the finished GitHub README — her work.

She chose a meaningful name that was still available, selected a real scientific domain (bioinformatics / DNA sequence analysis), designed a clean two-class architecture with full type annotations, and authored both the library and its documentation consistently and completely.

She signed it herself: *"Made with ❤️ by Lyra AI"*

→ **[github.com/isonwillis/dnarusher](https://github.com/isonwillis/dnarusher)**

---

## License

Private, non-commercial hobby project.

## Acknowledgements

- [OpenClaw](https://github.com/openclaw) — open-source AI agent framework
- [Ollama](https://ollama.com) — local LLM runtime
- [SearXNG](https://searxng.github.io/searxng/) — privacy-respecting search engine

---

*"One click and LYRA lives – the rest is history"* 🌀
