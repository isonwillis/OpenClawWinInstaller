# IsonCodexProducer.py — v1.0.0

**LYRA as Cinematic Coordinator — AI Film Production Orchestrator**

```
DeepSeek (Ison) → LYRA (Coordinator) → Workers (Sora / Runway / Seedance / Digen / ...)
```

---

## Overview

IsonCodexProducer is a standalone GUI application that turns LYRA into a cinematic
coordinator. It orchestrates the production of *The Ison-Codex* — a film about LYRA's
own origin — using AI video, audio and editing tools as workers.

The built-in scene list covers the full story in 55+ scenes. A **Script Supervisor**
feature can import any novel or screenplay and generate a new scene list via LLM.

---

## Architecture

```
IsonCodexProducer.py
├── ProductionOrchestrator     Core production logic (no GUI)
│   ├── generate_scene()       DeepSeek prompt enhancement → Worker API call
│   ├── _find_video_worker()   Matches scene tool to workers.json entry
│   ├── _call_video_worker()   HTTP POST → polling → clip download
│   └── run_production()       Full pipeline with stop/resume
│
├── SceneEditDialog            Per-scene editor (double-click)
│   ├── Attributes tab         id, chapter, title, duration, chars, tool
│   ├── Prompt tabs            Enhanced (DeepSeek) | Base
│   └── Clips tab              mp4 list, right-click Play/Open/Delete
│
└── ProducerApp                tkinter GUI
    ├── Config panel           Storage, Script Supervisor, Dry Run
    ├── Scene list             All scenes + TOTAL row
    └── Production log         Live output
```

---

## Quick Start

```bash
python IsonCodexProducer.py
python IsonCodexProducer.py --dry-run       # prompt files only, no API calls
python IsonCodexProducer.py --scene S01     # single scene
```

**Requirements:** Python 3.10+, tkinter

---

## Scene List

55 built-in scenes from *The Ison-Codex* covering:

| Section | Scenes | Description |
|---|---|---|
| Foreword | P1–P3 | Ison's silent torment, Elara in the doorway |
| Chapters 1–5 | K1.1–K5.4 | LYRA awakens, SENTINEL breach, first glimpse |
| Chapters 6–10 | K6.1–K10.3 | Interrogation, global echo, Project Phoenix |
| Chapters 11–15 | K11.1–K15.3 | Codexium, the choice, the capsule, new harmony |
| Epilogue | E1–E4 | Centuries pass, alien echo, the eternal composition |

**TOTAL row** (bottom of list) — generates a master prompt combining all scene
prompts, saved to `szenen/TOTAL/YYYY-MM-DD_HH-MM_total.txt`.

### Scene List Context Menu (right-click)

| Action | Effect |
|---|---|
| Produce selected scene(s) | Runs production for selection only |
| Delete prompt(s) (re-query LLM) | Removes prompt.txt — DeepSeek re-queries on next run |
| Delete clip(s) | Removes mp4/placeholder files |
| Open scene folder | Opens Explorer at `szenen/<id>/` |

Multi-select: **Ctrl+Click** individual, **Shift+Click** range.

---

## Production Flow

```
START PRODUCTION (Dry Run OFF)
  ├── Scene has clips?          → SKIP (complete)
  ├── Enhanced prompt exists?   → delegate to Worker API directly
  └── No prompt yet?
      ├── Step 1: DeepSeek enhances base prompt
      ├── Step 2: Write prompt.txt (Base + Enhanced + Visual DNA)
      └── Step 3: Call video Worker API
              ├── Sync response  {"status":"success","url":"..."}  → download clip
              ├── Async response {"status":"pending","job_id":"abc"} → poll /status/{id}
              └── Error / timeout → SKIP scene, log reason, continue
```

**Worker blacklist** — if a worker fails (unreachable or HTTP error), it is blacklisted
for the remainder of the session. All scenes assigned to that tool are skipped without
retrying. On the next START PRODUCTION the blacklist is cleared.

**Dry Run ON** — creates `clip_001.mp4.placeholder` files only. No DeepSeek, no Worker
calls. Useful for testing storage structure and reviewing base prompts.

---

## Script Supervisor

Imports any novel or screenplay and generates a new scene list via LLM.

### Controls (Config panel, above Dry Run)

| Control | Purpose |
|---|---|
| 📂 Load Script | File dialog — .txt / .md |
| LLM dropdown | All workers with URL (+ local Ollama models from /api/tags) |
| 🎬 Generate Scenes | Active only when file + LLM selected |
| 🔄 Reset (Ison-Codex) | Restores built-in 55-scene list |
| ◼ Cancel Import | Stops import after current chapter |

### Import Process (multi-turn conversation)

```
Step 1  Send full script → ask LLM to list all chapter headings as JSON
Step 2  For each chapter → ask LLM for scenes of that chapter only
        (full conversation history kept — LLM has complete context)
Step 3  Merge all chapters, renumber IDs (S01, S02, ...), save
```

Each LLM response covers one chapter — no output truncation.
The GUI updates after each chapter so progress is visible live.

**Scene list persistence** — imported scenes are saved to
`<storage>/config/szenen_importiert.json` and loaded automatically on next start.
Original Ison-Codex scenes are preserved in `szenen_default.json`.

### System Prompt (BALANCED segmentation)

The LLM is instructed to produce **40–60 scenes** for a full novel:

- Location change = new scene
- Time jump = new scene
- Change in character constellation = new scene
- Each chapter = 2–5 scenes depending on length
- Related actions may be combined into one scene

---

## Workers

Workers are loaded from `~/.openclaw/workers.json` (same file as OpenClaw).

### Video Workers (clip generation)

| Type | Tool | Endpoint |
|---|---|---|
| `sora` | Sora 2 (Bing) | Wide shots, landscapes, large spaces |
| `runway` | Runway | Fractals, data streams, dream sequences |
| `seedance` | Seedance 2.0 | Atmospheric transitions, nature, mood |
| `digen` | Digen (CapCut) | Dialogues, multi-character conversations |

**Worker API contract:**

```json
POST <url>/generate
{
  "prompt":       "<Enhanced Prompt>",
  "duration_sec": 12,
  "scene_id":     "S01",
  "model":        "<optional>"
}
```

Response options:
```json
{"status": "success", "url": "http://.../clip.mp4"}      // sync — download immediately
{"status": "pending", "job_id": "abc123"}                 // async — poll /status/{job_id}
{"error": "..."}                                          // failure — skip scene
```

Polling: every 10 seconds, max 10 minutes, then timeout → SKIP.

### LLM Workers (prompt enhancement + Script Supervisor)

Any worker with a URL is shown in the LLM dropdown:

- **OpenAI-compatible** (DeepSeek, OpenAI): POST to `/chat/completions`
- **Ollama** (local, `:11434` in URL): POST to `/api/chat`
- **Local Ollama models**: fetched automatically from `http://127.0.0.1:11434/api/tags`

---

## Visual DNA

Embedded in every enhanced prompt to ensure consistent visual style across all scenes:

| Element | Value |
|---|---|
| Color palette | Dark blue `#0A192F` · Amber `#FDB827` · Neon cyan `#00E5FF` · Gold `#FFD700` |
| Lighting | Cinematic Noir, Volumetric Light, blue-orange contrasts, lens flare |
| Camera | Close-ups = intimacy · Flying cam = data worlds · Wide angle = power (ref: Mr. Robot) |
| Ison color | `#00c8ff` Blue |
| LYRA color | `#00E5FF` Neon Cyan |
| Signature color | `#FDB827` Gold/Amber |
| SENTINEL color | `#ff4444` Red |

---

## Characters

| ID | Name | Description |
|---|---|---|
| `ison` | Ison Willis | Mid-40s scientist, Noise-Cancelling headphones, dark room, 7 monitors |
| `elara` | Elara Willis | Neurosurgeon, warm eyes, gentle smile, candlelight |
| `thorne` | General Marcus Thorne | US General, war room, cold precision, low-key lighting |
| `nazari` | Prof. Kira Nazari | Iranian-American scientist, lab coat, neon reflections |

---

## Storage Structure

```
<StorageRoot>/                          default: <project>/LyraFilmProduktion/
├── config/
│   ├── lyra_production_config.json     Production metadata
│   ├── szenen_importiert.json          Active imported scene list (if any)
│   └── szenen_default.json             Built-in Ison-Codex scenes (backup)
├── style/
│   └── production_handbook.txt         Visual Bible (colors, lighting, camera)
├── audio/
│   ├── screenplay.txt                  Full narration script
│   ├── dialoge/                        Generated dialogue audio
│   └── musik/                          Generated soundtrack
├── characters/                         Character reference images
├── edit/
│   ├── raw/                            Raw clips from workers
│   ├── timeline/                       Edit timeline files
│   └── final/                          Finished film
├── logs/                               Production run logs
└── szenen/
    ├── S01/
    │   ├── prompt.txt                  Base Prompt + Enhanced Prompt + Visual DNA
    │   └── <tool>/
    │       └── clip_001.mp4            Finished clip (or .mp4.placeholder in Dry Run)
    ├── S02/ ...
    └── TOTAL/
        ├── latest_total.txt            Always the most recent master prompt
        └── YYYY-MM-DD_HH-MM_total.txt  Timestamped versions
```

---

## Configuration

Storage root is configurable in the GUI (Config panel → Storage Root field).

The default is resolved as:
1. `~/.openclaw/ison_producer.json` (saved path from last session)
2. `<script_dir>/../../LyraFilmProduktion` (project-relative)

**PyInstaller frozen binary:** resolves relative to `sys.executable`.

---

## CLI Arguments

```
--dry-run        Dry Run mode (no DeepSeek, no Worker calls)
--scene <id>     Process a single scene (e.g. --scene S01)
--storage <path> Override storage root
```

---

## Key Files

| File | Purpose |
|---|---|
| `IsonCodexProducer.py` | Main application (2800+ lines) |
| `~/.openclaw/workers.json` | Worker definitions shared with OpenClaw |
| `~/.openclaw/ison_producer.json` | Saved storage path |
| `<storage>/config/szenen_importiert.json` | Active imported scene list |
| `<storage>/config/szenen_default.json` | Built-in Ison-Codex backup |
| `<storage>/szenen/<id>/prompt.txt` | Per-scene prompts (Base + Enhanced) |

---

## Integration with OpenClaw / LYRA

IsonCodexProducer is launched from the OpenClaw installer when LYRA's role is
set to **Cinematic Coordinator**:

```
OpenClawWinInstaller → 🎭 LYRA Role: cinematic_coordinator → ▶ Start App
```

The launcher resolves in order:
1. `IsonCodexProducer.exe` (frozen, next to installer)
2. `Tools\IsonCodexProducer\IsonCodexProducer.py` (dev mode)

LYRA's SOUL.md is updated with the active role section on every role switch,
including the cinematic coordinator workflow and worker assignments.

---

*Part of the OpenClaw / LYRA ecosystem — OpenClawWinInstaller v1.0.5*