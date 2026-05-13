# 🌐 LYRA-NET — Semantic Network of Global Elites

**Autonomous AI research agent over 2.4M+ ICIJ Offshore Leak nodes**

Part of the [OpenClaw](https://github.com/isonwillis/OpenClawWinInstaller) ecosystem · Tool path: `Tools/Lyra_Network_Builder`

---

## What it does

LYRA-NET is a local, offline-first investigation tool that loads the full **ICIJ Offshore Leaks dataset** (Panama Papers, Paradise Papers, Pandora Papers, Offshore Leaks) into a local Neo4j graph database and lets an autonomous AI research agent explore it — generating hypotheses, searching the web, extracting findings, and writing dossiers — while you watch in a live web UI.

It runs entirely on your machine. No cloud APIs. No data leaves your system.

---

## Key Features

| Feature | Description |
|---|---|
| 🗄 **Graph Database** | 2.4M+ nodes, 2.9M+ edges from all four ICIJ leak datasets |
| 🤖 **Autonomous Research Agent** | Generates hypotheses, searches the web via SearXNG, queries Ollama LLM, writes dossiers |
| 📄 **Dossier System** | Every hypothesis produces a Markdown dossier with findings, confidence score, and new Neo4j connections |
| 🔬 **Research UI** | Live web interface showing seeds, hypotheses, dossiers, and activity — with vis-network graph |
| 🔗 **Candidate Validation** | AI-suggested entity connections shown for manual review and acceptance into the graph |
| 💾 **Queue Persistence** | Research queue survives restarts — agent resumes exactly where it left off |
| 🔗 **OpenClaw Integration** | Triggers LYRA via `research_report.md` when breakthroughs are found |

---

## Screenshots

```
🌐 LYRA-NET — Semantisches Netzwerk globaler Eliten
Panama · Paradise · Pandora · Offshore Leaks

🗺️ Graph   🔍 Kandidaten   🔬 Research   📖 Legende

🌱 Seeds
✅ SEED 0.3% — Machtstruktur der 10 mächtigsten Personen

📋 Hypothesen
🔄 Portcullis TrustNet agiert als zentraler Nominee-Dienst in 20+ Ländern
⏳ Sharecorp Limited erscheint als Person UND Entity in BVI — Dateninkonsistenz
⏳ EXISTENZIA TRUST könnte Oberkontrolle über Service-Netzwerk haben

📄 Dossiers  [click → live network visualization]
📄 portcullis_trustnet_fungiert_als_hauptagentur... · 4 Erkenntnisse
📄 sharecorp_limited_als_master_shell...            · 3 Erkenntnisse
```

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Windows | 10 / 11 | 64-bit |
| Python | 3.11 (32-bit) | As shipped with OpenClaw |
| Java | 11+ | Eclipse Adoptium recommended — auto-installed |
| Neo4j Community | 5.26.0 | Auto-installed and managed |
| Ollama | any | Local LLM — `qwen2.5:9b` or similar |
| OpenClaw | 2026.5.7+ | For LYRA gateway integration |

Python packages installed automatically on first run:
`pandas`, `neo4j`, `networkx`, `flask`, `requests`, `werkzeug`, `waitress`

---

## Quick Start

### 1. Via OpenClaw Installer (recommended)

In the OpenClaw installer, set LYRA's role to **Research Agent**. The tool starts automatically with `--auto`.

### 2. Manual start

```cmd
python lyra_network_builder.py --auto
```

Open `http://127.0.0.1:18800/research` in your browser.

### 3. Send a research seed via PowerShell

```powershell
$env:RESEARCH_HYPOTHESIS = "Wer kontrolliert die globale Energieversorgung?"
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\.openclaw\workspace\research_query.ps1"
```

---

## Architecture

```
OpenClaw Gateway (18789)
        │
        ▼
LYRA (local LLM, Ollama)
        │  research_report.md trigger
        ▼
LYRA-NET (Flask/Waitress :18800)
        │
        ├── ResearchAgent (autonomous loop)
        │       ├── _generate_hypotheses_from_seed()  → Ollama
        │       ├── _research_hypothesis()
        │       │       ├── Neo4j graph query
        │       │       ├── SearXNG web search
        │       │       └── Ollama LLM extraction
        │       ├── _update_dossier()                 → Markdown file
        │       └── save_queue()                      → research_queue.json
        │
        ├── Neo4j Community (7687)
        │       └── 2.4M nodes · 2.9M edges
        │
        └── vis-network Web UI
                ├── Graph Tab      — main ICIJ network
                ├── Research Tab   — seeds, hypotheses, dossiers, live vis
                ├── Candidates Tab — AI-suggested connections for review
                └── Legend Tab     — node types, edge types, example graph
```

---

## Research Agent Behaviour

The agent runs a continuous loop:

1. **Pick next hypothesis** from queue (priority: active → pending, seeds always included)
2. **Query Neo4j** — find relevant entities in the graph
3. **Web search** — via local SearXNG instance
4. **LLM extraction** — Ollama analyses results, extracts facts and confidence score
5. **Write dossier** — Markdown file with findings and unvalidated connections
6. **Generate sub-hypotheses** — 2–3 follow-up hypotheses added to queue
7. **Periodic trigger** — every 10 completed hypotheses, write `research_report.md` for LYRA

Queue limit (default 30 auto-generated hypotheses) is adjustable via slider in the UI. Seeds from the user always pass through regardless of limit.

---

## Data Sources

All data is from the [ICIJ Offshore Leaks Database](https://offshoreleaks.icij.org/):

| Dataset | Year | Source |
|---|---|---|
| Panama Papers | 2016 | Mossack Fonseca & Co. |
| Paradise Papers | 2017 | Appleby, Estera, corporate registries |
| Pandora Papers | 2021 | 14 offshore service providers |
| Offshore Leaks | 2013 | BVI, Cook Islands |

The data is **not included** in this repository. Download CSV files from the [ICIJ download page](https://offshoreleaks.icij.org/pages/database) and place them in the configured import directory. The tool imports them automatically on first run.

---

## Configuration

All configuration is handled automatically via OpenClaw. Manual overrides:

| Setting | Default | Location |
|---|---|---|
| Flask port | `18800` | `FLASK_PORT` constant in script |
| OpenClaw gateway | `18789` | `OPENCLAW_GATEWAY_PORT` constant |
| Neo4j bolt | `7687` | auto-detected |
| Ollama endpoint | `127.0.0.1:11434` | read from `~/.openclaw/openclaw.json` |
| Workspace | `~/.openclaw/workspace/` | auto-created |
| Dossiers | `~/.openclaw/workspace/dossiers/` | auto-created |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Server health, node count |
| GET | `/api/graph` | Full graph data for vis-network |
| GET | `/api/research/status` | Agent status, hypotheses, activity |
| POST | `/api/research/hypothesis` | Add seed hypothesis |
| GET | `/api/research/dossiers` | List all dossiers |
| GET | `/api/research/dossier/<name>` | Get dossier content |
| GET | `/api/research/graph` | Context graph for dossier or candidate |
| POST | `/api/research/stop-seed/<id>` | Stop seed and remove pending sub-hypotheses |
| POST | `/api/research/queue-limit` | Set auto-generation queue limit |
| POST | `/api/research/pause` | Pause agent (after current task) |
| POST | `/api/research/resume` | Resume agent |
| POST | `/api/research/clear` | Reset queue (dossiers preserved) |
| GET | `/api/candidates` | Get connection candidates for review |
| POST | `/api/candidates/accept/<id>` | Accept candidate → write to Neo4j |

---

## File Structure

```
Tools/Lyra_Network_Builder/
└── lyra_network_builder.py     # Single-file tool (~5500 lines)

~/.openclaw/workspace/
├── research_queue.json          # Persisted hypothesis queue
├── research_report.md           # Trigger file for LYRA (auto-deleted after read)
├── research_query.ps1           # PowerShell helper — auto-written on start
└── dossiers/
    └── *.md                     # One Markdown dossier per hypothesis
```

---

## Notes

- **CPU load** during active research is expected — the agent runs an Ollama LLM call (up to 10 min on modest hardware) per hypothesis. CPU drops to idle immediately after the current task finishes when paused.
- **Pause is graceful** — the agent finishes its current LLM call before stopping.
- **Queue persists across restarts** — done hypotheses and their counts are restored correctly.
- The tool is designed for **32-bit Python 3.11** as distributed with OpenClaw on Windows.

---

## License

Part of the OpenClaw project. See repository root for license terms.

---

*Built for investigative research. All findings are AI-generated hypotheses — verify independently before drawing conclusions.*
