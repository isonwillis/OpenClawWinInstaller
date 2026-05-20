# 🌐 LYRA — ICIJ Network & Narrative Forensics

**Autonomous AI investigation suite: offshore network analysis + information-warfare forensics**

Part of the [OpenClaw](https://github.com/isonwillis/OpenClawWinInstaller) ecosystem · Tool path: `Tools/lyra_network_builder`

---

## What it does

LYRA is a local, offline-first investigation suite consisting of two complementary tools that can run **independently or as a unified platform**:

| Tool | Script | Port | Purpose |
|---|---|---|---|
| **ICIJ Network** | `lyra_network_builder.py` | 18800 | Offshore leak graph + autonomous research agent |
| **Narrative Forensics** | `lyra_narrative_forensic.py` | 18801 | Information-warfare narrative analysis + actor tracking |
| **Unified Platform** | `lyra_unified.py` | 18800 | Both tools in one interface with intelligent agent switching |

Everything runs entirely on your machine. No cloud APIs. No data leaves your system.

---

## Quick Start

### Recommended: Unified Platform

```cmd
python lyra_unified.py --auto
```

Opens `http://127.0.0.1:18800` — both tools accessible via tabs. The active tab's agent runs; the inactive one is paused and resumes where it left off on tab switch.

### Standalone: ICIJ Network only

```cmd
python lyra_network_builder.py --auto
```

Opens `http://127.0.0.1:18800/research`

### Standalone: Narrative Forensics only

```cmd
python lyra_narrative_forensic.py
```

Opens `http://127.0.0.1:18801`

---

## LYRA Unified

`lyra_unified.py` merges both tools into one web interface on port **18800**:

```
http://127.0.0.1:18800
  ├── 🗺️ ICIJ Network tab    → full lyra_network_builder UI
  └── 🕵️ Narrative Forensics tab → full lyra_narrative_forensic UI
```

**Context-switching:** Switching tabs automatically pauses the inactive agent and resumes the active one. Both agents save their full state (hypothesis queue / investigation list) on pause and restore it on resume — no progress is lost.

**Tab persistence:** The last active tab is remembered in `localStorage`. On page reload, the same tab is restored and the correct agent is signalled immediately — no unnecessary agent starts.

**Cross-tab linking:**
- In the Forensics tab, a **🔗 ICIJ** button appears next to actor names — click to jump to the ICIJ tab with that actor pre-searched
- In the ICIJ tab, actors can be sent to Forensics as a new investigation

**Architecture:**

```
lyra_unified.py  (Flask, port 18800)
  │
  ├── /icij/*      → proxy → internal ICIJ sub-server (port 18802)
  ├── /forensics/* → proxy → internal Forensics sub-server (port 18803)
  ├── /api/mode    → context-switch endpoint (pause/resume agents)
  └── /api/status  → agent status for tab-bar polling
```

Both sub-servers run as daemon threads inside the same process. Neo4j, Ollama, and SearXNG are initialised once and shared.

---

## ICIJ Network (`lyra_network_builder.py`)

Loads the full **ICIJ Offshore Leaks dataset** (Panama Papers, Paradise Papers, Pandora Papers, Offshore Leaks) into a local Neo4j graph and runs an autonomous AI research agent over it.

### Key Features

| Feature | Description |
|---|---|
| 🗄 **Graph Database** | 2.4M+ nodes, 2.9M+ edges from all four ICIJ datasets |
| 🤖 **ResearchAgent** | Generates hypotheses, web-searches via SearXNG, queries Ollama, writes Markdown dossiers |
| 🔬 **Research UI** | Live view of seeds, hypotheses, dossiers, activity log, and vis-network graph |
| 🔗 **Candidate Validation** | AI-suggested entity connections presented for manual review |
| 💾 **Queue Persistence** | `research_queue.json` survives restarts — agent resumes exactly where it stopped |
| 📄 **Dossier System** | Every hypothesis → Markdown dossier with findings, confidence score, new Neo4j edges |
| 🔗 **OpenClaw Integration** | Writes `research_report.md` on breakthroughs to trigger the LYRA gateway |

### Research Agent Behaviour

1. Pick next hypothesis from queue (seeds always first)
2. Query Neo4j for relevant entities
3. Web search via local SearXNG
4. LLM extraction via Ollama
5. Write/update Markdown dossier
6. Generate 2–3 follow-up hypotheses
7. Every 10 completions → write `research_report.md` for LYRA gateway

---

## Narrative Forensics (`lyra_narrative_forensic.py`)

Identifies actors that repeatedly appear as the **origin or early amplifier** of multiple narratives — across time, platforms, and deleted/archived sources.

### Key Features

| Feature | Description |
|---|---|
| 🕵️ **NarrativeAgent** | Autonomous loop: web search → LLM extraction → actor/narrative graph |
| 🌐 **Multi-platform** | Twitter, Reddit, 4chan, Telegram, blogs, YouTube — plus Wayback Machine for deleted content |
| 👤 **Actor Tracking** | NF_Actor nodes with stance, confidence, first-seen timestamps |
| 💬 **Narrative Graph** | NF_Narrative → NF_Platform → NF_Actor via SPREADS/COORDINATES_WITH edges |
| 📈 **Timeline View** | Chronological spread of a narrative across actors and platforms |
| 📂 **Corpus Import** | Drop `.txt` files as `YYYY-MM-DD_platform_title.txt` for manual artifact ingestion |

### Graph Node Types

| Label | Meaning |
|---|---|
| `NF_Actor` | Person, account, medium, organisation, botnet |
| `NF_Narrative` | The claim, meme, or framing being tracked |
| `NF_SpreadEvent` | Concrete spread instance (when/where) |
| `NF_Platform` | Twitter, Reddit, 4chan, Telegram, blog, etc. |
| `NF_Article` | Source article or thread |

All Narrative Forensics nodes use the `NF_` label prefix — no cross-contamination with ICIJ data in the shared Neo4j instance.

---

## Shared Infrastructure

| Service | Port | Used by |
|---|---|---|
| Neo4j Community | 7687 | Both (separate label namespaces) |
| Ollama | 11434 | Both |
| SearXNG (Docker) | 8080 | Both |
| OpenClaw Gateway | 18789 | ICIJ Network (research_report.md trigger) |

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | 64-bit |
| Python | 3.11 (32-bit) | As shipped with OpenClaw |
| Java | 11+ | Eclipse Adoptium — auto-installed by OpenClaw |
| Neo4j Community | 5.26.0 | Auto-installed and managed |
| Ollama | any | Local LLM — `qwen2.5:9b` or `glm-4.7-flash` |
| OpenClaw | 2026.5.7+ | For gateway integration |

Python packages (auto-installed on first run):
`pandas`, `neo4j`, `networkx`, `flask`, `requests`, `werkzeug`, `waitress`

---

## Architecture Overview

```
OpenClaw Gateway (18789)
        │  research_report.md trigger
        ▼
lyra_unified.py  ─── port 18800 (unified shell)
        │
        ├── ICIJ Sub-Server (18802)
        │     └── lyra_network_builder internals
        │           ├── ResearchAgent (autonomous loop)
        │           │     ├── Neo4j graph query
        │           │     ├── SearXNG web search
        │           │     ├── Ollama LLM extraction
        │           │     ├── Markdown dossier writer
        │           │     └── save_queue() → research_queue.json
        │           └── vis-network Web UI (Graph / Research / Candidates / Legend)
        │
        ├── Forensics Sub-Server (18803)
        │     └── lyra_narrative_forensic internals
        │           ├── NarrativeAgent (autonomous loop)
        │           │     ├── SearXNG + Wayback Machine search
        │           │     ├── Ollama LLM extraction
        │           │     └── _save_state() → narrative_queue.json
        │           └── vis-network Web UI (Actor / Narrative / Timeline)
        │
        └── Shared: Neo4j (7687) · Ollama (11434) · SearXNG (8080)

─── OR run each script standalone ───────────────────────────────────
lyra_network_builder.py   port 18800   (no forensics)
lyra_narrative_forensic.py port 18801  (no ICIJ)
```

---

## API Endpoints

### Unified Shell (`lyra_unified.py`)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Unified shell (tab UI) |
| GET/POST | `/api/mode` | Get or set active tab (`icij` / `forensics`) |
| GET | `/api/status` | Agent running/paused status for tab-bar |
| `*` | `/icij/<path>` | Proxy to ICIJ sub-server |
| `*` | `/forensics/<path>` | Proxy to Forensics sub-server |

### ICIJ Network

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Server health, node count |
| GET | `/api/graph` | Full ICIJ graph for vis-network |
| GET | `/api/research/status` | Agent status, hypotheses, activity log |
| POST | `/api/research/hypothesis` | Add hypothesis or seed |
| GET | `/api/research/dossiers` | List all dossiers |
| GET | `/api/research/dossier/<name>` | Get dossier content |
| POST | `/api/research/pause` | Pause agent after current task |
| POST | `/api/research/resume` | Resume agent |
| POST | `/api/research/clear` | Reset queue (dossiers preserved) |
| GET | `/api/candidates` | AI-suggested connections for review |
| POST | `/api/candidates/accept/<id>` | Accept candidate → write to Neo4j |

### Narrative Forensics

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Server health, node/edge counts |
| GET | `/api/status` | Agent status, investigation list |
| GET | `/api/graph` | Narrative graph for vis-network |
| POST | `/api/investigate` | Start new investigation |
| GET | `/api/narratives` | All narratives in DB |
| GET | `/api/timeline/<inv_uid>` | Timeline for one investigation |
| POST | `/api/agent/start` | Start NarrativeAgent |
| POST | `/api/agent/stop` | Stop NarrativeAgent |
| POST | `/api/import` | Import artifact from URL |
| POST | `/api/cleanup` | Remove orphan nodes |
| GET | `/api/export` | Export full graph as JSON |

---

## File Structure

```
Tools/lyra_network_builder/
├── lyra_unified.py              # Unified platform (recommended entry point)
├── lyra_network_builder.py      # ICIJ Network standalone (~5500 lines)
└── lyra_narrative_forensic.py   # Narrative Forensics standalone (~5300 lines)

~/.openclaw/workspace/
├── research_queue.json          # ResearchAgent hypothesis queue (persisted)
├── narrative_queue.json         # NarrativeAgent investigation state (persisted)
├── research_report.md           # Trigger file for LYRA gateway (auto-deleted after read)
├── research_query.ps1           # PowerShell helper — auto-written on start
├── narratives/                  # Per-investigation narrative data
├── corpus/                      # Manual artifact ingestion (YYYY-MM-DD_platform_title.txt)
└── dossiers/
    └── *.md                     # One Markdown dossier per ICIJ hypothesis
```

---

## Configuration

All configuration is handled automatically via OpenClaw. Manual overrides:

| Setting | Default | Where |
|---|---|---|
| Unified port | `18800` | `UNIFIED_PORT` in `lyra_unified.py` |
| ICIJ Flask port | `18800` | `FLASK_PORT` in `lyra_network_builder.py` |
| Forensics Flask port | `18801` | `FLASK_PORT` in `lyra_narrative_forensic.py` |
| Neo4j bolt | `7687` | auto-detected |
| Neo4j password | `lyra_network_2026` | shared across both scripts |
| Ollama endpoint | `127.0.0.1:11434` | read from `~/.openclaw/openclaw.json` |
| SearXNG | `127.0.0.1:8080` | constant in both scripts |
| Workspace | `~/.openclaw/workspace/` | auto-created |

---

## Notes

- **CPU load** during active research is expected — one Ollama LLM call per hypothesis (up to 10 min on modest hardware). CPU returns to idle as soon as the current task finishes and the agent is paused.
- **Pause is graceful** — the agent completes its current LLM call before stopping. State is always saved first.
- **Unified mode vs standalone:** `lyra_unified.py` imports both original scripts unchanged. Either script can still be launched independently on its own port if needed.
- **Neo4j namespace separation:** ICIJ nodes use labels `Person`, `Entity`, `Intermediary`, `Address`. Forensics nodes use `NF_*` labels exclusively. Both use the same Neo4j instance without conflict.
- The tools are designed for **32-bit Python 3.11** as distributed with OpenClaw on Windows.

---

## License

Part of the OpenClaw project. See repository root for license terms.

---

*Built for investigative research. All findings are AI-generated hypotheses — verify independently before drawing conclusions.*
