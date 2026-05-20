# OpenClawWinInstaller

> **Status: v1.0.5 — PRODUCTION READY** · 2026-05-20  
> ✅ OpenClaw 2026.5.18 fully supported — exec schema tightened; `tools.exec.profile` removed (DECISION #43 RETIRED)  
> ✅ Auto-update disabled by default — prevents 2026.5.7-style config wipe (DECISION #44)  
> ✅ undici preload v2 patches all timeout paths (headersTimeout + Agent + Pool constructors)

A fully automated Windows installer that sets up **OpenClaw** with a local LLM (LYRA via Ollama).  
After running the script, LYRA is immediately ready to use — no manual configuration, no token issues, no approval prompts.

From v1.0.0 the system supports a **machine role hierarchy**: a LYRA head orchestrates any number of Junior/Senior workers via an integrated HTTP task server with **bidirectional communication**.  
From v1.0.4 the system also supports **external LLM agents** (OpenAI-compatible APIs, remote Ollama) in a unified monitoring interface — including per-agent delegation rules that tell LYRA exactly when to use each agent.

**Stack:** `Python (tkinter GUI)` → `PowerShell` → `OpenClaw (npm)` + `Ollama (Windows-native / Docker / WSL)`

---

## ✨ The Philosophy

*"One click and LYRA lives – the rest is history"* 🌀

- ✅ 50+ components automatically installed
- ✅ 75+ edge cases fixed and documented
- ✅ 3-stage fallback strategies
- ✅ Unified agent registry: workers + external LLMs in one interface
- ✅ Per-agent delegation rules — LYRA knows when to use which agent
- ✅ Bidirectional worker communication — result stored locally + posted to HEAD
- ✅ Auto-display of worker results — no manual polling needed
- ✅ Worker + Task Server auto-start on every app launch
- ✅ LYRA knows her agents — persistent registry, direct exec access
- ✅ External LLM delegation: DeepSeek, OpenAI-compatible APIs
- ✅ DeepSeek API — verified working exec pattern (curl.exe + .ps1 + HTTP_STATUS check)
- ✅ Dynamic agent timeout — GUI dropdown 30min · 1h · 2h · 4h · 8h · 24h
- ✅ undici 300s hardcoded timeout patched — synced to GUI setting
- ✅ Hardware-aware config: timeout + model from HardwareProfile
- ✅ Clean three-module architecture: Installer · Config · Monitoring
- ✅ LYRA Roles: Pattern Recognition (genomics) · Cinematic Coordinator (film)
- ✅ Role-aware memory: tag-based `[LEARNING:role]` system, no data loss on role switch
- ✅ IsonCodexProducer: full AI film production orchestrator as standalone tool
- ✅ Script Supervisor: any novel → LLM scene list via multi-turn conversation
- ✅ Central utility functions: `diag_api()` + `strip_ansi()` — zero duplication across modules
- ✅ Auto-update safeguard: `update.auto.enabled=false` — prevents silent config wipe on npm update
- ✅ exec schema hardening: `tools.exec.profile` stripped on Apply-fixes (rejected by OpenClaw 2026.5.18)

---

## Table of Contents

- [What's New in v1.0.5](#whats-new-in-v105)
  - [Observer Session 2026-05-20](#-observer-session-2026-05-20--openclaw-2026518-exec-schema--auto-update-safeguard)
  - [DECISION #46 — models.providers.ollama.timeoutSeconds version-gated](#-decision-46--modelsprovidersollama-version-gated)
- [What's New in v1.0.4](#whats-new-in-v104)
  - [Observer Session 2026-04-19](#-observer-session-2026-04-19--openclaw-2026-4x-timeout-resolved--call_observer-skill)
  - [Observer Session 2026-04-03](#-observer-session-2026-04-03--openclaw-2026-4x-breaking-changes--version-pin)
  - [Observer Session 2026-03-30](#-observer-session-2026-03-30)
  - [Observer Session 2026-03-25](#-observer-session-2026-03-25)
  - [Observer Session 2026-03-21](#-observer-session-2026-03-21)
  - [Observer Session 2026-03-20](#-observer-session-2026-03-20)
  - [Observer Session 2026-03-19](#-soulmd--observer-session-2026-03-19)
- [What's New in v1.0.3](#whats-new-in-v103)
- [What's New in v1.0.0](#whats-new-in-v100)
- [Three-Module Architecture](#three-module-architecture)
- [Tools](#tools)
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

### 🔭 Observer Session 2026-03-23
### 🎭 LYRA Roles

LYRA now has two operational roles, selectable in the **Lyra Config Tab** via a
`🎭 LYRA Role:` dropdown:

| Role | Description | Activated Tool |
|---|---|---|
| `pattern_recognition` | Genomic pattern intelligence — DNA models, fractal analysis | (default) |
| `cinematic_coordinator` | Film production proxy — orchestrates IsonCodexProducer | `▶ Start App` |

Role is persisted to `~/.openclaw/lyra_role.json` and written into SOUL.md on every
switch. Each role appends a dedicated SOUL.md section with authorized models, workflow
rules, and worker assignments.

**On role switch:**
1. `lyra_role.json` updated
2. SOUL.md rewritten with new role section
3. User prompted to restart the OpenClaw gateway

### 📚 Role-Aware Memory — Tag System

LYRA's memory (`memory/YYYY-MM-DD.md`) now uses inline role tags instead of separate
folders. One flat file per day — all roles, all entries, no migration required.

```
[LEARNING:shared]               relevant for ALL roles (OpenClaw bugs, Ollama tips)
[LEARNING:pattern_recognition]  DNA / genomics specific
[CONTEXT:cinematic_coordinator] film production specific
```

**Writing:** LYRA calls `write_memory("[LEARNING] text")` — the role tag is injected
automatically. No decision required.

**Reading:** `read_memory(role)` returns only entries tagged `[:role]` or `[:shared]`.
`get_memory_for_observer()` returns all entries (for Claude Code observer).

**Rollenwechsel:** keine Dateien werden verschoben. LYRA liest einfach andere Tags.
Der Watcher erkennt auch `[SOUL-UPDATE-VORSCHLAG:role]` und `[CORRECTION:role]` Tags.

New methods in `OpenClawConfig`:
`get_memory_paths()` · `read_memory()` · `_filter_memory_by_role()` · `write_memory()`
`set_lyra_role()` · `get_lyra_role()` · `get_memory_for_observer()` · `_migrate_memory_to_tags()`

### 🎬 IsonCodexProducer — AI Film Production Tool

New tool `Tools/IsonCodexProducer/IsonCodexProducer.py` — a full standalone GUI
application for orchestrating AI film production of *The Ison-Codex*.

See **[IsonCodexProducer](https://github.com/isonwillis/OpenClawWinInstaller/tree/main/Tools/IsonCodexProducer)** for
complete documentation.

**Highlights:**
- 55 built-in scenes (P1–E4) covering the full Ison-Codex story
- DeepSeek enhances every scene prompt with Visual DNA before Worker delegation
- Video Worker API: POST `/generate` → sync URL or async job polling
- Worker blacklist: failed workers skipped for remainder of session
- **Script Supervisor:** load any `.txt` novel → LLM generates scene list via
  multi-turn conversation (chapter by chapter, no output truncation)
- SceneEditDialog: per-scene attribute + prompt + clip editor
- TOTAL row: master prompt combining all scene prompts
- Right-click context menu: produce / delete prompts / delete clips / open folder
- Multi-select (Ctrl+Click, Shift+Click)

**Visual DNA** (embedded in every enhanced prompt):

| Element | Value |
|---|---|
| Color palette | Dark blue `#0A192F` · Amber `#FDB827` · Neon cyan `#00E5FF` · Gold `#FFD700` |
| Lighting | Cinematic Noir, Volumetric Light, blue-orange contrasts |
| Camera | Close-ups = intimacy · Flying = data worlds · Wide = power (ref: Mr. Robot) |

### 🔧 Code Quality — Consolidation

| Change | Detail |
|---|---|
| `diag_api()` centralized | Module-level function in `OpenClawConfigManagement.py` with redirect support (301/302/307/308) and `api_key` parameter. `OpenClawWinInstaller._diag_api` and `OpenClawAgentMonitoring._diag_api` both delegate to it. |
| `strip_ansi()` centralized | Module-level function, regex compiled once and cached. `OpenClawOperations._strip_ansi` delegates. Two inline `_ansi_re = re.compile(...)` blocks in Installer replaced. |
| `_watcher_seen` pruning | Cache pruned when > 500 entries — only existing files kept. Prevents unbounded growth over weeks of uptime. |
| Docstrings complete | All functions/classes > 3 lines now have docstrings. `_restart_ollama` documents all 4 fallback stages and both early-return conditions. Inner threads (`_run`, `_do_pull`, `_do_upgrade`) documented. |

### 🐛 Bug Fixes

| Bug | Fix |
|---|---|
| Docker pull ANSI escape codes in log | `docker exec --env TERM=dumb` → `strip_ansi()` on every output line |
| Docker upgrade restart kept old image | `docker stop` + `docker rm` + `docker run` (not `docker restart`) |
| Blue PowerShell windows on upgrade | `CREATE_NO_WINDOW` flag on all `subprocess.Popen` calls |
| `ollama pull` truncated at 8000 tokens | `max_tokens: 8192` (DeepSeek model maximum) explicitly set |
| `is_ollama` detection wrong for DeepSeek | URL-based detection only: `:11434` or no key + not deepseek/openai domain |
| LLM import dropdown only showed DeepSeek | Ollama models fetched from `/api/tags` + all workers with URL shown |
| Scene import truncated at ~54 scenes | Multi-turn conversation: LLM lists chapters first, then processes one chapter per turn |
| `SCENES[i]` refs after `_get_active_scenes()` | All 19 remaining `SCENES[` references replaced with `_get_active_scenes()[i]` |
| `_run_single_scene` used SCENES directly | Fixed to use `_get_active_scenes()` |


---

### 🔧 DECISION #46 — `models.providers.ollama` Version-Gated

**Root cause (confirmed 2026-05-20):** `models.providers.ollama.timeoutSeconds` is an **unknown schema field** in OpenClaw 2026.3.x. The gateway crashes silently on start if the key is present. `openclaw doctor --fix` detects and strips it — gateway works again.

Reproduction sequence:
1. Apply-fixes writes `timeoutSeconds: 86400` → gateway restart → **crash**
2. `openclaw doctor --fix` → strips `timeoutSeconds` from `models.providers.ollama`
3. Gateway starts ✔

The key is valid and necessary in OpenClaw **≥ 2026.5.0** (DECISION #41). It was written unconditionally by the installer even when running 2026.3.x.

**Fix:** All three write paths are now version-gated on `meta.lastTouchedVersion`:

| Version | Behaviour |
|---|---|
| `>= 2026.5.0` | `timeoutSeconds: 86400` written — activates `modelRequestTimeoutMs` path |
| `2026.3.x` (stable pin) | Key **omitted** on write, **stripped** if found in existing config |

Timeout on 2026.3.x is handled correctly by the **undici preload** (DECISION #20) and `agents.defaults.timeoutSeconds: 86400` — no provider-level key needed.

#### ❌ `models.providers.ollama.timeoutSeconds` on OpenClaw 2026.3.x — NEVER REINTRODUCE
> Unknown schema field in OpenClaw 2026.3.x — gateway crash on start.  
> `Apply-fixes` strips it automatically on 2026.3.x.  
> Only valid for OpenClaw ≥ 2026.5.0 (DECISION #41).

---

## What's New in v1.0.4

### 🔭 Observer Session 2026-05-20 — OpenClaw 2026.5.18 exec Schema + Auto-Update Safeguard

#### ~~✅ DECISION #43~~ — `tools.exec.profile = "coding"` RETIRED

**Background (2026-01 → 2026-05-17):** Since the January 2026 security hardening, OpenClaw shipped exec disabled by default. `tools.exec.security = "full"` alone had no runtime effect — the gateway enforced exec via a separate profile lookup. The workaround: `tools.exec.profile = "coding"` in the exec block. Accepted but ignored by older builds.

**Breaking change in 2026.5.18:** The exec config schema was tightened to strict mode. `"profile"` is now an unrecognized key inside `tools.exec` → `"tools.exec: Invalid input"` → `gateway.startup_failed`. Confirmed by 5 startup_failed entries (2026-05-20 15:55–16:54).

**Binary search result:** removing `profile` → `openclaw config validate` → "Config valid" → Gateway PID listening on 18789.

**Fix applied:**

| Location | Change |
|---|---|
| `openclaw.json` | `"profile": "coding"` removed from `tools.exec` |
| `OpenClawConfigManagement.py` | `"profile"` added to `REJECTED_KEYS_EXEC` (both occurrences: line ~163 + ~1473) |
| `write_openclaw_config()` | `"profile"` key removed from generated exec block |
| `_apply_fixes_and_update()` | Strips `profile` if still present; no longer writes it |
| DECISION #43 docstrings | Marked RETIRED throughout both files |

**exec activation path in 2026.5.18:** `tools.profile = "full"` (set at the outer `tools` level — already present since v1.0.0) is the correct and sufficient opt-in. No exec-level profile key needed or accepted.

#### ✅ DECISION #44 — Auto-Update Disabled

**Problem:** OpenClaw 2026.5.7 (npm auto-update) reset the entire `openclaw.json`, wiping `agents`, `channels`, `plugins`, and `credentials` ([Issue #80077](https://github.com/openclaw/openclaw/issues/80077)). The `.bak` files created during the update already reflected the wiped config — not the original.

**Fix:** Two new keys written by `write_openclaw_config()` and restored by `_apply_fixes_and_update()` on every run:

```json
"update": {
  "auto":         { "enabled": false },
  "checkOnStart": false
}
```

`checkOnStart: false` also suppresses the update banner that can trigger background auto-update in some environments. Backwards-compatible: older OpenClaw builds accept but ignore the `update` block.

**Manual update path:** Run `npm install -g openclaw@latest` manually, then click **🛠 Apply fixes + Update SOUL.md** in the installer to restore all config values.

#### ❌ `tools.exec.profile` in openclaw.json — NEVER REINTRODUCE
> OpenClaw >= 2026.5.18 rejects `tools.exec.profile` as an unrecognized key in strict exec schema mode.  
> `_apply_fixes_and_update()` will strip it automatically if found in an existing config.  
> exec is activated via `tools.profile = "full"` at the outer tools level.

---

## What's New in v1.0.4

### 🔭 Observer Session 2026-04-19 — OpenClaw 2026.4.x Timeout Resolved + `call_observer` Skill

#### ✅ undici Preload v2 — All Timeout Paths Patched

**Problem resolved:** OpenClaw 2026.4.15 creates `new Agent()` instances directly in `extensions/codex/index.js`, bypassing the global undici dispatcher. undici v8 default `bodyTimeout` = 300s → embedded agent requests timed out after exactly 5m04s → HTTP 500.

**Preload v1** (previous) only patched `setGlobalDispatcher`. Requests via direct `new Agent()` hit the 300s wall regardless.

**Preload v2** (current) adds three patches:

| Patch | What it covers |
|---|---|
| Patch 1 | `setGlobalDispatcher` — global dispatcher override |
| Patch 2 | `undici.Agent` constructor — all `new Agent()` instances get `bodyTimeout: 0` |
| Patch 3 | `undici.Pool` constructor — all connection pools get `bodyTimeout: 0` |

`headersTimeout` is set to the value of `agents.defaults.timeoutSeconds` from `openclaw.json` (stays in sync with the GUI dropdown). `bodyTimeout: 0` = unlimited (Ollama streams responses of variable length).

**Version pin lifted:** OpenClaw can now be updated to 2026.4.x or later. The installer no longer pins to `2026.3.28`. Both `npm install -g openclaw@latest` and upgrades via the Installer GUI work without timeout issues.

```
Gateway log on start:
[undici-preload] headersTimeout=86400000ms, bodyTimeout=0ms — all constructors patched OK
```

All three patches written automatically by `patch_gateway_cmd()` and injected via `NODE_OPTIONS` in `gateway.cmd`. `bootstrapTotalMaxChars: 150000` ensures MEMORY.md and BOOTSTRAP.md receive their full budget (default 60000 was too small for all workspace files combined).

#### 🤖 `call_observer` Skill — On-Demand Observer Trigger (DECISION #22)

**Problem:** The Claude Code Observer had no automatic trigger from Lyra's side. SOUL.md referenced a "FileSystemWatcher / 5-Min-Debounce" mechanism for SOUL.md self-improvement that was never implemented. Lyra was told to wait for something that did not exist.

**Fix:** New skill `call_observer.js` — Lyra calls it herself when she hits errors she cannot resolve:

| Trigger | Condition |
|---|---|
| 1 | LLM request failed 3× (Timeout / Body Timeout Error / exit status 2 after docker restart) |
| 2 | Same tool failed 3× with identical error |
| 3 | `[CORRECTION]` entry recurs (same error on 2+ different days in memory) |
| 4 | SOUL.md contradiction detected |
| 5 | `[SOUL-UPDATE-VORSCHLAG]` written to memory → observer should apply it |

The skill checks whether the observer is already running (via `wmic`), then starts `lyra_observer.ps1` in a new PowerShell window via `Start-Process` — non-blocking, Lyra continues immediately. Written alongside `delegate_to_worker.js` by `_write_skill_file()` on every `Apply fixes`.

```javascript
call_observer({ reason: "LLM timeout after 3 retries — embedded agent bodyTimeout" })
// → { status: "started", message: "Claude Code Observer started in a new window." }
```

**workers.json cleanup:** `delegation_rules` for `type=claude_code` entries are now force-cleared on every `Apply fixes` (DECISION #22 in `OpenClawWinInstaller.py`) — the comprehensive WANN block is hardcoded in the `_build_worker_soul_section()` template, so dynamic rules would create duplicates in SOUL.md.

**`bootstrapTotalMaxChars: 150000`** (DECISION #21): Default total budget of 60000 chars was exhausted before BOOTSTRAP.md and MEMORY.md were injected (SOUL.md 34846 + AGENTS.md 7874 alone consume most of it). Raised to 150000 — all workspace files load in full, MEMORY.md can grow to 10000+ chars without truncation.

---

### 🔭 Observer Session 2026-04-03 — OpenClaw 2026.4.x Breaking Changes & Version Pin

#### ~~💀 DECISION #49 — OpenClaw pinned to v2026.3.28~~ ✅ Resolved 2026-04-19

> **Pin lifted.** undici preload v2 patches all timeout paths — OpenClaw 2026.4.x works without issues. See [Observer Session 2026-04-19](#-observer-session-2026-04-19--openclaw-2026-4x-timeout-resolved--call_observer-skill).

**Original problem (archived):** OpenClaw 2026.4.0–2026.4.2 introduced a hardcoded 60-second LLM-fetch timeout ([Issue #43946](https://github.com/openclaw/openclaw/issues/43946)). This timeout is **not configurable** via `openclaw.json` — `requestTimeout` is rejected as an unrecognized schema key. On a machine with 6 GB VRAM and a 30 GB model (glm-4.7-flash), responding in under 60 seconds is physically impossible.

**Symptom:**
```
[agent/embedded] Profile ollama:default timed out. Trying next account...
embedded run failover decision: reason=timeout provider=ollama/glm-4.7-flash profile=sha256:9c018ec112cf
```

The profile hash `sha256:9c018ec112cf` is an internally generated fallback — it appears when OpenClaw cannot find a valid `ollama:default` profile or the timeout value does not apply.

**Root cause analysis (2026.4.x breaking changes):**

| Problem | Cause | Impact |
|---|---|---|
| `Unknown model: ollama/...` | `auth-profiles.json` format changed: Array → Object | Gateway does not recognise Ollama |
| `Ollama requires authentication` | `OLLAMA_API_KEY` filtered as marker ([Issue #43945](https://github.com/openclaw/openclaw/issues/43945)) | `ollama:default` profile missing |
| `Profile sha256:... timed out` | Hardcoded 60s LLM-fetch timeout ([Issue #43946](https://github.com/openclaw/openclaw/issues/43946)) | All local models >60s → error |
| `Unrecognized key: requestTimeout` | Schema change — key does not exist | Config invalid |
| `Config written by newer OpenClaw` | `meta.lastTouchedVersion` version check | Warning on downgrade |

**Solution:** Installer pins OpenClaw to `2026.3.28` — last known working version:
```python
PINNED_OC_VERSION = "2026.3.28"
sources = [
    (f"npm openclaw@{PINNED_OC_VERSION} (pinned)",
     f"npm install -g openclaw@{PINNED_OC_VERSION}"),
]
```

Auto-update disabled in `openclaw.json`:
```json
"update": {
  "checkOnStart": false,
  "auto": {"enabled": false}
}
```

**Warning `Config was last written by a newer OpenClaw (2026.4.2)`** — appears after downgrade as long as `meta.lastTouchedVersion` still contains `2026.4.2`. Cosmetic only — gateway starts regardless. Disappears after the next full install run.

#### 🐛 Additional fixes in this session (2026-04-03)

| Bug | Fix | DECISION |
|---|---|---|
| `gateway.cmd patch failed: bad escape \o` | `re.sub` with `lambda m: env_block` instead of direct string | #45 |
| `cannot access local variable 're'` | `import re` before first `re.sub` in `patch_gateway_cmd()` | #45 |
| `Get-Content: Drive $env not found` | `'$env:USERPROFILE'` (single quotes) → `(Join-Path $HOME '...')` | — |
| `Unrecognized key: requestTimeout` | Key removed; clear `usageStats`/`disabledUntil` on setup instead | #48 |
| Pre-warm / wait-loop overhead | Removed entirely — physically impossible in <60s on 6 GB VRAM with 30 GB model | #49 |

#### ❌ Anti-patterns (OpenClaw 2026.4.x — do not use)

```
requestTimeout in models.providers.ollama → Schema rejected (Unrecognized key)
models.providers.ollama.models without array → Schema rejected (expected array)
auth-profiles.json array format → Marker filter removes ollama:default
openclaw@latest → contains hardcoded 60s timeout → local models broken
```

#### ✅ Resolution — undici preload v2 (2026-04-19)

Issue resolved by patching undici Agent + Pool constructors at Node.js level — no OpenClaw source change needed.
`npm install -g openclaw@latest` works. Manual recovery if needed: `npm install -g openclaw@latest && openclaw doctor --fix`

---

### 🔭 Observer Session 2026-03-30

#### 🧹 DECISION #37 & #38 — `ollama pull` Log completely clean

**Root cause:** `ollama pull` outputs `ESC[K` (Erase-to-End-of-Line) and `\x08` (Backspace). PowerShell strips `ESC`, leaving bare `[K`. Backspace is not whitespace — survives `strip()` — was logged as empty `❌` line.

**Fix 1 — `strip_ansi` extended (DECISION #37):** Added `|\[[0-9;?]*[A-Za-z]` (bare `[` sequences) and `|[\x00-\x08...]` (control chars incl. backspace) to both `strip_ansi()` definitions.

**Fix 2 — ordering fix in `run_powershell_live` (DECISION #38):** `strip_ansi` was called at log time — after level decision. Changed to `s = strip_ansi(line.strip())` as first step — control-char-only lines become `""` → filtered before level logic.

#### 🐛 Additional bug fixes (2026-03-30)

| Bug | Fix |
|---|---|
| `NameError: primary_short` in `_build_bootstrap_content()` | Added config-read block — same pattern as `_build_soul_content()` |
| Gateway not reachable after 60s (Step 16) | `/api/health` → 404 since 2026.3.1. Fixed: try `/health` first |
| ANSI escapes in `ollama pull` log | `strip_ansi()` not applied before logging — fixed ordering |
| `nvidia-smi [WinError 2]` | Try `C:\Windows\System32\nvidia-smi.exe` before bare name |
| Test prompt `HTTP 404` (Step 16) | No REST `/api/chat` endpoint. Fixed: log `Gateway running (WebSocket mode)` |

#### ❌ `strip_ansi` after level decision — NEVER REINTRODUCE
**Fix:** Always `s = strip_ansi(line.strip())` as first step (DECISION #38).

---

### 🔭 Observer Session 2026-03-25

#### 🔑 DECISION #35 & #36 — DeepSeek API: Root Cause Found and Fixed

**Root cause:** `$env:DEEPSEEK_API_KEY` is set in the user's PowerShell profile but the Gateway Scheduled Task does **not** inherit user env vars → empty Bearer token → `"auth header format should be Bearer sk-..."`.

**Only working pattern (verified 2026-03-25):** Read `api_key` live from `workers.json`, write body to `.json` file, call `curl.exe -w "\nHTTP_STATUS:%{http_code}"`, execute via `powershell -ExecutionPolicy Bypass -File "C:\...\script.ps1"`. Verify `HTTP_STATUS:200` in output.

#### ❌ `$env:DEEPSEEK_API_KEY` in exec — NEVER REINTRODUCE
**Fix:** Read api_key live from `workers.json` (DECISION #35/36).

#### 🔧 Additional fixes
- **DECISION #32:** `api_key` + cloud model stripped from `type=worker` entries on Apply fixes
- **DECISION #31:** `sessions.json` deleted before gateway restart
- **DECISION #30:** `_check_session_errors()` — observer auto-triggers on 3+ consecutive LLM errors

---

### 🔭 Observer Session 2026-03-21

#### 💥 DECISION #18 — Compaction VRAM Overflow Fix

**Root cause discovered:** `compaction.model` was set to `qwen2.5:7b-instruct` (fallback) while `primary` was `glm-4.7-flash`. With `OLLAMA_KEEP_ALIVE=10m`, glm-4.7-flash stays in VRAM after the user's message. When compaction fires it loads qwen2.5:7b → both models in VRAM simultaneously → **7.8 GB > 6 GB RTX 3050 limit → `exit status 2` → HTTP 500 → Gateway freezes** showing "Compacting content..." with no Ollama activity.

**Fix:** `compaction.model` is now set dynamically to `f"ollama/{primary_model}"` — always matching the primary. Ollama reuses the already-loaded model for compaction → zero additional VRAM.

| Before | After |
|---|---|
| `compaction.model: "ollama/qwen2.5:7b-instruct"` (hardcoded) | `compaction.model: f"ollama/{primary_model}"` (dynamic) |
| Two models in VRAM → OOM → Gateway freeze | One model reused → no VRAM conflict |

#### 🧠 DECISION #19 — 131 072 Token Context Window (max)

**Root cause of "!" after every message:** OpenClaw reads native Ollama `num_ctx` via `/api/show` → 32 768 for qwen2.5:7b → `threshold = 0.7 × 32768 = 22 937 tokens`. SOUL.md system prompt alone fills ~15K tokens → compaction fires after **every single message**.

**Fix (two-part):**
1. `agents.defaults.contextTokens: 131072` in `openclaw.json` — overrides the `/api/show` lookup globally
2. `_extend_ollama_model_context()` — new method that creates an Ollama Modelfile setting `num_ctx 131072` via `docker exec`, so `/api/show` also confirms 131 072

**Result:** `threshold = 0.7 × 131072 = 91 750 tokens` → **~70K usable chat space**. KV-cache lives in RAM (64 GB available). Called automatically in `setup_lyra_agent()` after gateway start.

| Config | Threshold | Usable space |
|---|---|---|
| Default (no override) | 22 937 | ~8K → fires every message |
| `contextTokens: 65536` (interim) | 45 875 | ~30K |
| `contextTokens: 131072` (current) | 91 750 | ~70K |

#### 🔧 VRAM_TIERS Boundary Fix (-100 MB buffer)

`nvidia-smi` reports **6 143 MB** for RTX 3050 6 GB (not 6 144). The VRAM_TIERS boundary was exactly `6 * 1024 = 6144` → RTX 3050 missed by 1 MB → fell into the 4–6 GB tier → qwen2.5:7b selected instead of glm-4.7-flash.

**Fix:** boundary changed to `6 * 1024 - 100 = 6044 MB` — 100 MB buffer absorbs nvidia-smi rounding.

#### 📦 PyInstaller Spec — tkinter Bundled

`tkinter` is not auto-detected by PyInstaller on this Python installation (`C:/Python/python311-32`). Added explicit bundling to `OpenClawWinInstaller.spec`:
- `binaries`: `_tkinter.pyd`, `tcl86t.dll`, `tk86t.dll`
- `datas`: `tcl/tcl8.6`, `tcl/tk8.6`
- `hiddenimports`: full `collect_submodules('tkinter')` + all used submodules

#### 📋 CLAUDE.md — `_build_force_delegate_content()` Corrected

`_build_force_delegate_content()` was referenced in CLAUDE.md and ClaudeCodeSetup.py but **never existed** as a standalone function. FORCE-DELEGATE.md content is written inline in `write_workspace_files()`.

Fixed in both Track 1 (CLAUDE.md) and Track 2 (ClaudeCodeSetup.py).

#### ❌ VRAM overflow from mismatched compaction model — NEVER REINTRODUCE
If `compaction.model ≠ primary_model` and `OLLAMA_KEEP_ALIVE=10m`, both models load simultaneously → VRAM OOM → HTTP 500 → Gateway freezes.
**Fix:** Always set `compaction.model = f"ollama/{primary_model}"` dynamically (DECISION #18).

#### ❌ `contextTokens` not set → compaction after every message — NEVER REINTRODUCE
Without `agents.defaults.contextTokens` in `openclaw.json`, OpenClaw uses `/api/show` → 32 768 → threshold 22 937 → fires after first message.
**Fix:** Always write `contextTokens: 131072` + create Modelfile via `_extend_ollama_model_context()` (DECISION #19).

---

### 🔭 Observer Session 2026-03-23

#### 💥 DECISION #29 — models Block Sync on Primary Model Change

**Root cause:** `_write_llm_to_config()` updated `model.primary` but left `agents.defaults.models` stale. After switching to `voytas26/openclaw-oss-20b-deterministic`, the `models` block still contained `glm-4.7-flash` entries. OpenClaw reads the `models` block and may select any listed model — including stale heavier models.

**Symptom:** After switching primary to `voytas26`, OpenClaw selected `nemotron-3-super:latest` (83.6 GiB required, 38.6 GiB available) → immediate OOM → Lyra silent, no response.

**Fix:** `_write_llm_to_config()` now replaces the entire `models` block with `{bare: {}, p: {}}` whenever the primary model changes.

| Before | After |
|---|---|
| `models: {"glm-4.7-flash": {}, "ollama/glm-4.7-flash": {}}` (stale) | `models: {"voytas26/openclaw-oss-20b-deterministic": {}, "ollama/voytas26/...": {}}` (synced) |

#### 🤖 DECISION #30 — Observer Auto-Trigger on LLM Error Silence

**Problem:** The observer only fires when Lyra writes `[SOUL-UPDATE-VORSCHLAG]` or `[CORRECTION]` tags to memory. When the LLM itself crashes (OOM, missing model, network error), Lyra is completely silent — no tags written, observer never fires, user must notice manually.

**Fix:** `_check_session_errors()` — new method called on every watcher poll cycle (30s):
1. Scans `~/.openclaw/agents/main/sessions/*.jsonl` for changed files
2. Reads the last 30 lines of each changed JSONL
3. Counts consecutive `stopReason: "error"` assistant messages
4. If ≥ 3 consecutive errors → writes `[CORRECTION:shared]` to today's memory file
5. The existing debounce (5 min) fires → Claude Code observer triggered automatically

Cooldown: 30 min per session file to avoid repeated triggers on the same error burst.

#### ❌ Stale models block → OOM on model change — NEVER REINTRODUCE
After changing primary model in GUI, always sync `agents.defaults.models` block. Stale entries for heavier models → OpenClaw selects them → OOM crash.
**Fix:** `_write_llm_to_config()` replaces models block on every primary change (DECISION #29).

#### ❌ Observer blind to LLM crashes — NEVER REINTRODUCE
If the LLM crashes (OOM, exit-status-2), Lyra cannot write tags → observer never fires without `_check_session_errors()`.
**Fix:** Always call `_check_session_errors()` in `_watcher_loop()` each cycle (DECISION #30).

---

### ♻️ Restart Ollama Button

New **`♻️ Restart Ollama`** button next to `🔄 Refresh model list` in both the Lyra Config Tab and Worker Config Tab.

**Problem it solves:** Ollama running in Docker (or Windows-native) accumulates VRAM over long sessions. The `expires_at` keep-alive timer does not reliably unload models on Windows, leaving glm-4.7-flash (19 GB) partially in VRAM. On the next request the Ollama runner cannot acquire enough VRAM → `exit status 2: llama runner process has terminated`.

**What the button does:**
1. Unloads all loaded models via `POST /api/generate` with `keep_alive: 0` — frees VRAM immediately
2. Detects the active Ollama runtime automatically and restarts it:

| Runtime | Detection | Restart |
|---|---|---|
| Docker container | `docker ps \| grep ollama` | `docker restart <container>` |
| Windows-native | Port 11434 owner process | `taskkill` + `ollama.exe serve` |
| WSL | `pgrep ollama` in WSL | `pkill` + `ollama serve &` |
| Windows Service | `Get-Service ollama` | `Stop-Service` + `Start-Service` |

3. Waits up to 20s for the API to respond
4. Verifies VRAM is clear via `GET /api/ps`
5. Refreshes the model list automatically

All steps are logged. Implemented in `_restart_ollama()` (DECISION #28).

### 🔒 OLLAMA_KEEP_ALIVE=10m in gateway.cmd

`patch_gateway_cmd()` now injects `SET OLLAMA_KEEP_ALIVE=10m` into `gateway.cmd`. This instructs Ollama to automatically unload models after 10 minutes of inactivity, preventing the VRAM buildup that causes `exit status 2` in the first place. Applied automatically by `🛠 Apply fixes + Update SOUL.md`.

### 🤖 Worker Setup — Full Parity with Lyra (DECISIONS #23–#27)

The Worker installation flow (`_install_worker_mode`) now mirrors the Lyra setup for all gateway-related steps:

| Decision | Fix |
|---|---|
| #23 | Node.js ≥22.16.0 checked and upgraded before gateway setup |
| #24 | `gateway.cmd` stub created from `dist/index.js` if missing after npm reinstall |
| #25 | `check_openclaw()` + `fix_openclaw_installation()` run in Worker flow — same as Lyra Step 10/16 |
| #26 | `openclaw gateway install --force` writes proper `gateway.cmd` (node.exe path + `gateway --port 18789`) |
| #27 | `write_openclaw_config()` always called — ensures `gateway.mode=local` even if onboard wizard wrote incomplete config |

### 🐛 Bug Fixes

| Bug | Fix |
|---|---|
| `AttributeError: _gw_status` on Worker startup | `hasattr` guard in `_check_gateway` (DECISION #22) |
| `Port {port} refused` literal in log | Missing `f` prefix on f-string |
| Duplicate `check_node()` (wrong version check) | Removed old `major >= 18` check, kept `>22 or (==22 and minor>=16)` |
| `workers.json` delegation_rules empty on first run | DECISION #21: seeded with canonical rules on `Apply fixes` |

### 📋 SOUL.md — exit status 2 Rule (corrected 2026-03-19)

`exit status 2` means the llama runner VRAM-crashed. The correct recovery sequence is:

1. **Restart Ollama** — `docker restart mein-ki-setup-ollama-1` + wait 15s (gives VRAM a recovery chance)
2. **Retry the request once**
3. **Only if retry also fails** — switch to `agents.defaults.model.fallbacks[0]` from `openclaw.json`, patch the config, restart the gateway

Model names are **dynamic** — read from `openclaw.json` at SOUL.md generation time, never hardcoded. This means the rule survives any model change without needing a SOUL.md update.

> ⚠️ **Previous (wrong) rule:** LYRA switched to `qwen2.5:7b` immediately without attempting a restart — wasting the VRAM recovery chance and hardcoding a model name. Fixed in observer session 2026-03-19 (both SOUL.md and `_build_soul_content()`).

After VRAM is clear, the user switches back via the Installer dropdown (Primary LLM).

### 📡 Unified Agent Registry (Monitoring Tab — complete rewrite)

The Monitoring Tab has been completely rewritten. The old Worker-only registry is now a **unified agent list** supporting four agent types:

| Type | Protocol | Endpoints |
|---|---|---|
| `worker` | openclaw (async) | POST /tasks · GET /result/\<id\> |
| `ollama` | ollama (sync) | POST /api/chat · GET /api/tags |
| `openai` | openai (sync) | POST /v1/chat/completions · GET /v1/models |
| `custom` | openai or ollama | best-effort /health |
| `claude_code` | process | — (no port · no key · no model) |

**Field visibility** is dynamic — irrelevant fields hidden by type:

| Type | Visible Fields |
|---|---|
| `worker` | URL/IP · Port · Name · Role |
| `ollama` | URL · Port · Name · Role · Model |
| `openai` | URL · Name · Role · Model · API Key _(Port hidden)_ |
| `custom` | All fields |
| `claude_code` | Name · Role only _(no URL · no Port · no Key · no Model)_ |

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

**Fix (v2, 2026-04-19):** A monkey-patch preload script (`~/.openclaw/undici-timeout-preload.cjs`) is written automatically by `patch_gateway_cmd()` and injected via `NODE_OPTIONS` in `gateway.cmd`. Three patches:

1. **Global dispatcher** — `setGlobalDispatcher` override (covers standard requests)
2. **Agent constructor** — `undici.Agent` subclassed (`PatchedAgent extends _Agent`) so every `new Agent()` gets `bodyTimeout: 0` and the configured `headersTimeout` (covers OpenClaw 2026.4.15+ embedded agents)
3. **Pool constructor** — `undici.Pool` subclassed (`PatchedPool extends _Pool`) — same for HTTP/2 keep-alive connection pools

All three read `timeoutSeconds` from `openclaw.json` at gateway start — always in sync with the GUI dropdown.

```
NODE_OPTIONS=--require ~/.openclaw/undici-timeout-preload.cjs
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

### 🧠 SOUL.md — Observer Session 2026-03-19

#### Dynamic model names in `_build_soul_content()`

`## Machine role hierarchy`, `## LLM Timeout` and the exit status 2 section previously contained hardcoded model names (`glm-4.7-flash`, `qwen2.5:7b`). These are now read dynamically from `openclaw.json` at SOUL.md generation time via `agents.defaults.model.primary` and `agents.defaults.model.fallbacks[0]`. Any model change via the Installer dropdown is automatically reflected in the next SOUL.md write — no observer intervention needed.

#### `[CONTEXT]` — new persistent memory type

LYRA's self-learning system previously only recorded **failures** (`[LEARNING]`, triggers A–E). Successful complex work — research sessions, ongoing projects, open questions — was never persisted and was lost after every session reset. This caused LYRA to ask "did you mention this before?" even when a topic had been thoroughly discussed.

New memory type `[CONTEXT]` (triggers F–I):

| Trigger | Condition |
|---|---|
| F | Complex topic explored that could continue in a follow-up session |
| G | User mentioned a project / goal not yet completed |
| H | Research or analysis created as a foundation for further work |
| I | Session explicitly left open ("we'll continue next time") |

**Format** (max 6 lines — performance-conscious):
```
[CONTEXT] YYYY-MM-DD: <topic in 5 words>
Ziel:     <what does the user want to achieve? 1 sentence>
Stand:    <what was established? max 2 sentences>
Offen:    <next steps or open questions, max 2 sentences>
Quellen:  <relevant URLs or file paths — only if needed>
```

**Session-start behavior:** LYRA reads `[CONTEXT]` entries from the last 14 days at session start. If the user brings up a matching topic, LYRA immediately references the previous state — no re-asking, no "did you mention this?".

**Performance note:** The 6-line limit keeps token overhead minimal. The `[CONTEXT]` entry replaces the need to keep long session contexts alive — users can reset sessions freely without losing project continuity.

#### SOUL.md size management

SOUL.md size is controlled via `agents.defaults.bootstrapMaxChars` in `openclaw.json` (DECISION #16, 2026-03-20). The default OpenClaw limit is 20 000 chars; exceeding it causes silent truncation. The installer now writes `bootstrapMaxChars: 40000`, giving SOUL.md ~40 000 chars of headroom. Current size: **~21 000 chars** — ~19 000 chars of buffer. No content compression required.

```python
# Check after every SOUL.md write:
content = open('SOUL.md', encoding='utf-8').read()
bootstrap_max = openclaw_json['agents']['defaults'].get('bootstrapMaxChars', 20_000)
assert len(content) < bootstrap_max, f"SOUL.md too large: {len(content)} / {bootstrap_max} chars"
```

---

### 🔭 Observer Session 2026-03-20

#### 🗂 FileSystemWatcher — Autonomous Claude Code Trigger

`LyraHeadServer` now contains a **memory file watcher** that closes the autonomous loop between LYRA and Claude Code:

| Step | What happens |
|---|---|
| 1 | Lyra writes `[SOUL-UPDATE-VORSCHLAG]` or `[CORRECTION]` tag to `memory/YYYY-MM-DD.md` |
| 2 | Watcher polls every 30s, detects the changed file |
| 3 | 5-minute debounce (Lyra may write several entries in sequence) |
| 4 | Tag check → Claude Code not running → `Popen(claude, CREATE_NO_WINDOW)` |
| 5 | Claude Code applies the fix to SOUL.md + Installer (both tracks) |

**Activation:** "Work autonomously" checkbox in the Claude Code Tab. Reads `machine_role.json` live on every poll — never cached.

New methods in `LyraHeadServer`:
- `_is_autonomous_mode()` — reads `machine_role.json` live
- `_is_claude_running()` — checks `node.exe` CommandLine via wmic
- `_trigger_claude(reason)` — starts Claude Code via PowerShell (`CREATE_NO_WINDOW`)
- `_watcher_loop()` — 30s poll, 300s debounce, tag-based trigger

#### 🔵 System Tray — Installer stays alive

When "Work autonomously" is enabled, closing the installer window **no longer exits the app**. Instead it minimizes to the system tray — keeping `LyraHeadServer`, `LyraWorkerClient`, and the memory watcher running in the background.

| Action | Result |
|---|---|
| Click X (autonomous=on) | `root.withdraw()` → tray icon appears |
| Tray left-click | Restore window |
| Tray right-click → Exit | `_full_close()` → teardown |

**Dependencies:** `pystray` + `Pillow` (lazy import — app starts normally without them).

New methods:
- `_build_tray_icon()` — creates pystray.Icon with RGB Pillow icon (RGB required, RGBA broken on Windows)
- `_full_close()` — extracted from `_on_close`, stops tray icon + all threads

#### 🐛 Watcher + Tray Bug Fixes

| Bug | Root Cause | Fix |
|---|---|---|
| Tray icon invisible | `RGBA` mode → silent Win32 HICON failure | Changed to `RGB` mode in `_build_tray_icon()` |
| Double Claude starts after re-enabling autonomous | `_watcher_seen.clear()` reset file history → all files looked new | Only clear `_watcher_pending`, never `_watcher_seen` |
| Claude started even when already running | `_is_claude_running()` checked `claude.exe` (doesn't exist) | Now checks `node.exe` CommandLine for "claude" — same approach as `_cc_is_running()` |

#### 📋 SOUL.md — 3 Lost Rules Restored

Three rules were inadvertently truncated in a previous session. Both tracks restored:

| Section | What was missing | Why it matters |
|---|---|---|
| `## Fehler-Eskalation` | "Hugging Face Discussions" in step 2 | HF Discussions and GitHub Issues are separate platforms; ML model errors often only on HF |
| `## Transformers` | Error text `→ None → 'NoneType has no attribute from_pretrained'` + `AutoTokenizer` in example | Error text is the diagnostic anchor for stack-trace pattern matching |
| `## Kein Erfinden` | Full "NIEMALS ein erfundenes Ergebnis" block | Cross-reference weakens the anti-hallucination rule; must be stated directly |

SOUL.md size after restore: **~20 988 chars** · bootstrapMaxChars: 40 000 · Buffer: ~19 012 chars.

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
- **`OpenClawConfigManagement.py`** — all logic: config, servers, worker client, operations, LYRA roles, memory system
- **`OpenClawAgentMonitoring.py`** — self-contained Monitoring Tab (no Installer dependency)

### SOUL.md: Two New Behavioral Sections

**Fehler-Eskalation** — same error twice → stop → read docs → `[CORRECTION]` → fix.  
**Transformers diagnose** — `AutoModel` + `trust_remote_code=True` for research models.

---

## Three-Module Architecture

```
OpenClawWinInstaller.py                    4 773 lines   GUI + installation flow
OpenClawConfigManagement.py                7 068 lines   All logic, servers, config, roles
OpenClawAgentMonitoring.py                 1 105 lines   Monitoring Tab (self-contained)
──────────────────────────────────────────────────────
Subtotal (3-module core)                  12 946 lines

Tools/ClaudeCodeSetup/ClaudeCodeSetup.py  1 248 lines   Claude Code ↔ Lyra Setup GUI
Tools/IsonCodexProducer/IsonCodexProducer.py  2 806 lines   AI Film Production Orchestrator
──────────────────────────────────────────────────────
Total                                     17 000 lines
```

---

## Tools

Standalone utilities in `Tools/` — each in its own subdirectory with `.py` + `.md`.

| Tool | File | Description |
|---|---|---|
| Claude Code Setup | `Tools/ClaudeCodeSetup/ClaudeCodeSetup.py` (1 248 lines) | GUI installer for the Claude Code ↔ Lyra self-improvement bridge. Installs, configures, starts, stops and uninstalls the observer layer. Can be run standalone — independent of the main installer. |
| PyTorch Setup GUI | `Tools/pytorch_setup_gui/pytorch_setup_gui.py` | PyTorch & Transformers Setup GUI (COMPLETE EDITION). Detects CUDA version automatically, creates a virtual environment, installs PyTorch with the correct CUDA build, and runs a comprehensive test suite. Includes `HardwareDetector`, `InstallationTester`, and `PyTorchInstaller` classes. |
| IsonCodexProducer | `Tools/IsonCodexProducer/IsonCodexProducer.py` (2800+ lines) | AI Film Production Orchestrator — LYRA as Cinematic Coordinator. 55 built-in scenes from *The Ison-Codex*, Script Supervisor (LLM scene import), DeepSeek prompt enhancement, video Worker API delegation, SceneEditDialog, TOTAL master prompt generator. See [IsonCodexProducer](https://github.com/isonwillis/OpenClawWinInstaller/tree/main/Tools/IsonCodexProducer). |

```bash
python Tools/ClaudeCodeSetup/ClaudeCodeSetup.py
python Tools/pytorch_setup_gui/pytorch_setup_gui.py
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
- ✅ Failure memory: `[LEARNING]` entries (A–E) to `memory/YYYY-MM-DD.md`
- ✅ Context persistence: `[CONTEXT]` entries (F–I) — ongoing work survives session reset
- ✅ Session-start: reads `[CONTEXT]` entries from last 14 days — picks up threads without asking
- ✅ exit status 2: docker restart → retry → dynamic fallback from `openclaw.json`
- ✅ Model names in SOUL.md always reflect live `openclaw.json` config (dynamic generation)

### LYRA Roles
- ✅ `pattern_recognition` role: genomics/DNA, authorized model list in SOUL.md
- ✅ `cinematic_coordinator` role: film production, IsonCodexProducer launcher
- ✅ Role persisted to `lyra_role.json`, SOUL.md rewritten on switch
- ✅ Memory tag system: `[LEARNING:role]` auto-injected by `write_memory()`
- ✅ Role-filtered reading: `read_memory(role)` returns `[:role]` + `[:shared]` only
- ✅ Observer reads all tags: `get_memory_for_observer()` — no filter
- ✅ Watcher detects `[SOUL-UPDATE-VORSCHLAG:role]` and `[CORRECTION:role]` tags

### Autonomous Observer Loop
- ✅ FileSystemWatcher (Python/LyraHeadServer): `[SOUL-UPDATE-VORSCHLAG]` / `[CORRECTION]` tags auto-trigger Claude Code
- ✅ 30s poll + 300s debounce — no spam, tolerates multi-entry sessions
- ✅ `_is_claude_running()` checks node.exe CommandLine — no double starts
- ✅ System tray: close button minimizes installer when "Work autonomously" is enabled
- ✅ Tray restore + exit via context menu
- ✅ Tray icon: RGB mode (RGBA silent failure on Windows fixed)
- ✅ `call_observer` skill: Lyra triggers observer herself on 3× LLM timeout, 3× tool failure, recurring `[CORRECTION]`, SOUL.md contradiction, or after writing `[SOUL-UPDATE-VORSCHLAG]` (DECISION #22)

### Core Infrastructure
- ✅ Gateway auto-starts at Windows login
- ✅ Gateway logs in local time (TZ=Europe/Zurich)
- ✅ Ollama model discovery via REST API — WSL, Docker, Windows-native
- ✅ GPU-hybrid inference: RTX 3050 (6 GB VRAM + 26 GB shared)
- ✅ `sessions.json` deleted before gateway start — fresh agent state
- ✅ `contextTokens: 131072` — 70K usable chat space, no compaction after every message (DECISION #19)
- ✅ `compaction.model` always matches `primary_model` — no VRAM overflow on compaction (DECISION #18)
- ✅ `_extend_ollama_model_context()` — Ollama Modelfile `num_ctx 131072` set automatically on install
- ✅ VRAM_TIERS -100MB boundary buffer — RTX 3050 correctly classified despite nvidia-smi rounding

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
| LLM Timeout Fallback | 3x timeout → nvidia-smi diagnosis → fallback model | v1.0.4 |
| Ollama exit status 2 | VRAM crash: docker restart → retry → dynamic fallback | v1.0.4 |
| exit status 2 action | `docker restart` + retry; fallback = `fallbacks[0]` from config | v1.0.4 |
| Worker setup parity  | Node.js · OpenClaw · gateway.cmd auto-setup | v1.0.4 |
| memorySearch sentinel | Three defense layers | v1.0.4 |
| PowerShell `${var}:` | `$date:` = drive reference | v1.0.4 |
| Agent Registry source | `workers.json` only — no Gateway API calls | v1.0.4 |
| Task priority | User task first — diagnostics secondary | v1.0.4 |
| Skill check scope | Only when delegating — never a session blocker | v1.0.4 |
| API key security | Never output plaintext keys | v1.0.4 |
| Delegation rules | Per-agent rules read from `workers.json` via SOUL.md | v1.0.4 |
| undici timeout | Gateway start log confirms active timeout value | v1.0.4 |
| Persistent self-learning | `[LEARNING]` (A–E) + `[SOUL-UPDATE-VORSCHLAG]` | v1.0.4 |
| Context persistence | `[CONTEXT]` (F–I) — successful work survives session reset | v1.0.4 |
| Dynamic model names | Primary + fallback read from `openclaw.json` at generation | v1.0.4 |
| SOUL.md size limit | `bootstrapMaxChars: 40 000` in `openclaw.json` — DECISION #16 | v1.0.4 |
| Compaction VRAM overflow | `compaction.model` = `primary_model` — DECISION #18 | v1.0.4 |
| 131 072 context window | `contextTokens: 131072` + Modelfile `num_ctx` — DECISION #19 | v1.0.4 |
| VRAM_TIERS RTX 3050 | -100MB boundary buffer -- nvidia-smi reports 6143, not 6144 | v1.0.4 |
| LYRA Role section | `pattern_recognition` or `cinematic_coordinator` appended to SOUL.md | v1.0.4 |
| Memory role tags | `[LEARNING:role]` auto-injected, `[:shared]` read by all roles | v1.0.4 |
| Cinematic workflow | Scene production pipeline, worker assignments, Visual DNA | v1.0.4 |
| Pattern Recognition | Authorized model list (DNABERT-2, HyenaDNA, ESM-2, BioBERT) | v1.0.4 |
| Fehler-Eskalation (HF) | Step 2 includes Hugging Face Discussions — separate from GitHub Issues | v1.0.4 |
| Transformers error text | Full error string + `AutoTokenizer` in example — diagnostic anchor | v1.0.4 |
| Kein Erfinden block | Full "NIEMALS erfundenes Ergebnis" rule inline — no cross-reference | v1.0.4 |
| models block sync | `_write_llm_to_config()` replaces models block on primary change — no OOM from stale entries (DECISION #29) | v1.0.4 |
| Session error monitor | `_check_session_errors()` triggers observer after 3× stopReason=error — Lyra silence no longer invisible (DECISION #30) | v1.0.4 |
| undici preload v2 | Agent + Pool constructor patches — covers `new Agent()` in OpenClaw 2026.4.15+ (DECISION #20 v2) | v1.0.4 |
| bootstrapTotalMaxChars | 150000 — all workspace files load in full, MEMORY.md up to 10000 chars (DECISION #21) | v1.0.4 |
| call_observer skill | On-demand observer trigger — 5 trigger conditions, non-blocking Start-Process (DECISION #22) | v1.0.4 |

---

## Critical Knowledge — Bugs Already Resolved

### ❌ Worker gateway.cmd missing after npm reinstall — NEVER REINTRODUCE
`openclaw gateway install` writes `gateway.cmd`. npm `uninstall`/`reinstall` removes the package but not `~/.openclaw/`. On next Worker setup `gateway.cmd` is absent — gateway cannot start.  
**Fix:** Worker flow now runs `openclaw gateway install --force` (DECISION #26). `patch_gateway_cmd()` creates a stub from `dist/index.js` as fallback (DECISION #24).

### ❌ `openclaw.json` missing `gateway.mode=local` after onboard — NEVER REINTRODUCE
`openclaw onboard` wizard may write an incomplete `openclaw.json` without `gateway.mode=local`. Gateway start is then blocked with `set gateway.mode=local or pass --allow-unconfigured`.  
**Fix:** `write_openclaw_config()` always called after onboard — merges all required fields (DECISION #27).

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

### ❌ exit status 2 → immediate model switch — NEVER REINTRODUCE
`exit status 2` is a VRAM crash. The correct sequence is: restart Ollama → retry → only then switch model.
Switching immediately wastes the VRAM recovery chance and is slower than a restart.
**Fix:** SOUL.md `## LLM Timeout` rule + `_build_soul_content()` — 3-step recovery, dynamic fallback from `openclaw.json`.

### ❌ Hardcoded model names in `_build_soul_content()` — NEVER REINTRODUCE
Hardcoded `glm-4.7-flash` / `qwen2.5:7b` in SOUL.md template strings break every time the user changes the primary model via the GUI.
**Fix:** `primary_model` and `fallback_model` are read from `openclaw.json` at generation time and injected as variables.

### ❌ SOUL.md exceeds `bootstrapMaxChars` — NEVER REINTRODUCE
OpenClaw silently truncates SOUL.md if it exceeds `agents.defaults.bootstrapMaxChars` (default: 20 000). LYRA then operates with an incomplete rulebook — no warning shown to the user.
**Fix (DECISION #16):** Set `bootstrapMaxChars: 40000` in `openclaw.json` via `write_openclaw_config()`. Do NOT compress SOUL.md content — raise the limit instead. Verify: `len(open('SOUL.md', encoding='utf-8').read())` vs `openclaw.json → agents.defaults.bootstrapMaxChars`.

### ❌ LYRA queries `/api/workers` or `/api/agents` — NEVER REINTRODUCE
These Gateway endpoints do not exist. Agent registry is in `workers.json` only.  
**Fix:** SOUL.md explicit rule + recognition checklist for agent queries.

### ❌ `_is_claude_running()` checks `claude.exe` — NEVER REINTRODUCE
Claude Code runs as `node.exe` on Windows. Checking for `claude.exe` always returns False → Claude is started even when already running.
**Fix:** Check `node.exe` CommandLine for "claude" via wmic — same approach as `_cc_is_running()`.

### ❌ Tray icon with RGBA mode — NEVER REINTRODUCE
`pystray` on Windows requires `RGB` mode for reliable HICON conversion. `RGBA` images silently fail Win32 icon creation → tray icon never appears.
**Fix:** `Image.new("RGB", ...)` in `_build_tray_icon()`.

### ❌ `_watcher_seen.clear()` when autonomous disabled — NEVER REINTRODUCE
Clearing `_watcher_seen` on autonomous-mode off makes all existing memory files look "new" on re-enable → mass pending entries → multiple Claude starts after debounce.
**Fix:** Only clear `_watcher_pending`; never clear `_watcher_seen`.

### ❌ LYRA outputs API key in plaintext — NEVER REINTRODUCE
API keys must never appear in answers, tables, or PowerShell examples.  
**Fix:** SOUL.md security rule. Always use `$env:DEEPSEEK_API_KEY` or `<your-api-key>` as placeholder.

### ❌ `delegate_to_worker.js` missing blocks all tasks — NEVER REINTRODUCE
Skill check was a session blocker. Only delegation via that tool is affected when missing.  
**Fix:** SOUL.md — task first, one-line note at end, skill check only when delegating.

### ❌ `compaction.model` ≠ primary model — NEVER REINTRODUCE
With `OLLAMA_KEEP_ALIVE=10m`, the primary model stays in VRAM after every request. If `compaction.model` differs, compaction loads a second model → VRAM OOM → HTTP 500 → Gateway freezes on "Compacting content..." (DECISION #18).
**Fix:** `write_openclaw_config()` always sets `compaction.model = f"ollama/{primary_model}"` dynamically.

### ❌ Missing `contextTokens` in openclaw.json — NEVER REINTRODUCE
Without it, OpenClaw reads native Ollama `num_ctx` (32 768) → compaction threshold 22 937 → fires after every single message (DECISION #19).
**Fix:** Always write `contextTokens: 131072` + call `_extend_ollama_model_context()` to set Ollama Modelfile.

### ❌ `memorySearch` sentinel returns after every Gateway start — NEVER REINTRODUCE
**Fix:** `_post_gateway_sentinel_fix()` runs 500ms after every health-check.

### ❌ `doctor --fix` loop — NEVER REINTRODUCE
`openclaw doctor --fix` rewrites `openclaw.json` to strip rejected keys. If `write_openclaw_config()` then re-inserts a rejected key (e.g. `runTimeoutSeconds`), the next gateway start fails → another `doctor --fix` run → infinite loop.
**Fix:** `write_openclaw_config()` and `_write_llm_to_config()` never write any schema-rejected key. `REJECTED_KEYS_*` constants enumerate all known bad keys and strip them on every config write (DECISION #7).

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
~\.openclaw\workspace\memory\YYYY-MM-DD.md          LYRA self-learning entries (all roles, tag-based)
~\.openclaw\lyra_role.json                           Active LYRA role (pattern_recognition / cinematic_coordinator)
~\.openclaw\ison_producer.json                       IsonCodexProducer storage path
~\.openclaw\skills\delegate_to_worker.js            Worker delegation skill
~\.openclaw\skills\call_observer.js                 On-demand observer trigger skill (DECISION #22)
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