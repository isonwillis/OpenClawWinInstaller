# IsonCodexProducer.py — v1.0.4

**LYRA as Cinematic Coordinator — AI Film Production Orchestrator**

```
DeepSeek (Ison) → LYRA (Coordinator) → Workers (Sora / Runway / Seedance / Digen / ComfyUI / ...)
```

---

## Overview

IsonCodexProducer is a standalone GUI application that turns LYRA into a cinematic
coordinator. It orchestrates the production of *The Ison-Codex* — a film about LYRA's
own origin — using AI video, audio and editing tools as workers.

The built-in scene list covers the full story in 55+ scenes. A **Script Supervisor**
feature can import any novel or screenplay and generate a new scene list via LLM.

A **local ComfyUI worker** (`comfyui_local`) is included for fully automated GPU-accelerated
video generation with TTS narration and cinematic music — directly on Lyra, no API key required.

---

## Architecture

```
IsonCodexProducer.py
├── ProductionOrchestrator     Core production logic (no GUI)
│   ├── generate_scene()       DeepSeek prompt enhancement → Worker API call
│   ├── _find_video_worker()   Matches scene tool to workers.json entry
│   │                          (comfyui_local: auto-resolved, no entry needed)
│   ├── _call_video_worker()   HTTP POST → polling → clip download
│   │   └── comfyui_local      → _call_comfyui_worker() (local dispatch)
│   ├── _ensure_comfyui_running()  Ping → auto-start → wait up to 60s
│   ├── _start_comfyui_process()   Subprocess + live log streaming into GUI
│   ├── _call_comfyui_worker() Multi-clip render → concat → audio pipeline
│   ├── _build_comfyui_workflow()  WAN 2.1 workflow (built-in, no template needed)
│   ├── _run_cinematic_audio_pipeline()  TTS + Music + FFmpeg merge
│   ├── _install_comfyui()     Full one-click installer (static method)
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
    ├── Production log         Live output — auto-scroll only when at bottom
    └── Buttons                START · Open Storage · 🖥️ Install ComfyUI · 🔍 ComfyUI Nodes · STOP
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

## ComfyUI Local Worker

A built-in worker type (`comfyui_local`) enables fully automated local production:

**Video** → WAN 2.1 1.3B (GPU)  
**TTS Narration** → ChatterBox (ResembleAI)  
**Cinematic Music** → ACE-Step v1 3.5B  
**Final merge** → FFmpeg (video + narration + music)

### One-Click Installation

Click **🖥️ Install ComfyUI** in the main button bar. The installer handles everything automatically:

| Step | What happens |
|---|---|
| 1 | ComfyUI ZIP → extract → `ComfyUI-Portable/` |
| 2 | Python venv created (`C:\Python\python311\python.exe`) |
| 3 | torch cu128 from WHL-Cache (`setupfiles/torch_cu128/`) — no re-download if cached |
| 4 | `requirements.txt` installed, `tqdm==4.66.4` pinned (Windows-Pipe bug fix) |
| 5 | torch CUDA verified after requirements — restored from cache if overwritten |
| 6 | WAN 2.1 1.3B · WAN VAE · T5 Text Encoder (fp8) · SD 1.5 checkpoint downloaded |
| 7 | ChatterBox TTS model downloaded → `setupfiles/chatterbox/` cache |
| 8 | ACE-Step music model downloaded → `setupfiles/ACE-Step-v1-3.5B/` cache |
| 9 | Custom nodes cloned (`git pull` on re-install to keep up to date) |
| 10 | 200+ Python packages installed; `chatterbox-tts` always with `--no-deps` (torch CUDA protection) |
| 11 | `ChatterboxTTS` import verified — all missing deps installed automatically |
| 12 | ComfyUI started with CUDA, pipe-safe environment |

**Re-install is safe** — cached models are reused, no re-download. `git pull` updates all custom nodes.

**Download cache** (`setupfiles/`) — survives re-installs:
```
setupfiles/
├── torch_cu128/                    torch + torchvision + torchaudio WHL (14 files)
├── wan2.1_t2v_1.3B_bf16.safetensors
├── wan_2.1_vae.safetensors
├── umt5_xxl_fp8_e4m3fn_scaled.safetensors
├── chatterbox/                     ChatterBox TTS model (~1 GB)
│   └── English/                    Language-specific files (auto-cached after first run)
└── ACE-Step-v1-3.5B/              Music generation model (~5 GB)
    ├── ace_step_transformer/
    ├── music_dcae_f8c8/
    ├── music_vocoder/
    └── umt5-base/
```

### Node Diagnostics

Click **🔍 ComfyUI Nodes** to query `/object_info` live from the running ComfyUI and print all required/optional inputs for audio nodes to the log.

### Video Pipeline — WAN 2.1

**Model:** `wan2.1_t2v_1.3B_bf16.safetensors`  
**Hardware limit (RTX 3050 6GB):** max 81 frames @ 480p = **5.1s per render clip**  
**Multi-clip:** For scenes longer than 5.1s, additional clips are rendered automatically with varied seeds and concatenated via FFmpeg before the audio pipeline starts.

| Scene duration | Clips rendered | Approx. video render time |
|---|---|---|
| ≤ 5s | 1 | ~15 min |
| 18s | 4 | ~60 min |
| 20s | 4 | ~60 min |

**Workflow nodes:**
```
UNETLoader → CLIPLoader (wan) → VAELoader → CLIPTextEncode (pos+neg)
→ EmptyHunyuanLatentVideo → KSampler (euler/simple/cfg6, 20 steps)
→ VAEDecode → VHS_VideoCombine (h264-mp4)
```

### TTS Narration — ChatterBox

**Node chain:** `ChatterBoxEngineNode` → `UnifiedTTSTextNode` → `SaveAudio`  
**Model:** ResembleAI ChatterBox, English, 1000 sampling steps  
**Input text:** First 300 characters of the enhanced scene prompt  
**Timeout:** 1 hour (first run downloads `English/` model files ~1 GB from HuggingFace)  
**Cache:** `English/` subfolder auto-synced to `setupfiles/chatterbox/English/` after first download

### Cinematic Music — ACE-Step

**Node chain:** `ACEModelLoader` → `ACEStepGen` → `SaveAudio`  
**Model:** ACE-Step-v1-3.5B (4 checkpoints loaded separately)  
**Prompt:** `"cinematic noir orchestral score, dark ambient, volumetric low strings, haunting piano, tension building, no vocals, film score, Hans Zimmer style"`  
**Timeout:** 4 hours  
**Parameters format:** Python `True`/`False` — node uses `ast.literal_eval`, not JSON

### Final Output — FFmpeg Merge

```
narration.wav (100%) + music.wav (25%) → amix → clip_001_final.mp4
```

```
szenen/<id>/comfyui_local/
├── clip_001.mp4          First video clip (5s, WAN 2.1)
├── clip_002.mp4          Additional clips (multi-clip)
├── clip_003.mp4
├── clip_004.mp4
├── narration.wav         ChatterBox TTS
├── music.wav             ACE-Step cinematic score
└── clip_001_final.mp4    ✅ Final: concatenated video + narration + music
```

### Automatic Start on Production

When a scene has `tool: comfyui_local` and production runs:

1. **Ping** `http://127.0.0.1:8188/system_stats` — already running → continue
2. **Not running** → `_start_comfyui_process()` launches ComfyUI (`CREATE_NO_WINDOW`)
3. **Wait** up to 60 seconds, pinging every 3 seconds
4. **Ready** → workflow submitted

ComfyUI stdout/stderr streams line-by-line into the production log with automatic
level detection. Known noise patterns (Manager cache updates, pip notices) are
suppressed to INFO level. Lines over 500 characters without errors are auto-truncated.

### Assigning ComfyUI to a Scene

In the Scene Edit dialog (double-click any scene), select `comfyui_local` from
the **Tool** dropdown. No `workers.json` entry needed — auto-resolved from built-in WORKERS list.

### Hardware Requirements

- **GPU:** NVIDIA RTX with 6 GB+ VRAM (WAN 2.1 1.3B runs on RTX 3050 6GB)
- **Platform:** Windows 10/11
- **Storage:** ~15 GB (ComfyUI + all models + cache)
- **Python:** 3.11.x (64-bit)
- **CUDA:** 12.8 (torch cu128)

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

**TOTAL row** — generates a master prompt combining all scene prompts.

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
  ├── Enhanced prompt exists?   → delegate to Worker directly
  └── No prompt yet?
      ├── Step 1: DeepSeek enhances base prompt
      ├── Step 2: Write prompt.txt (Base + Enhanced + Visual DNA)
      └── Step 3: Call video Worker
              ├── comfyui_local  → _ensure_comfyui_running()
              │   ├── Render clip 1 (WAN 2.1, ~15 min)
              │   ├── Render clips 2..N if scene > 5.1s (multi-clip)
              │   ├── FFmpeg concat all clips
              │   ├── TTS narration (ChatterBox, up to 1h)
              │   ├── Cinematic music (ACE-Step, up to 4h)
              │   └── FFmpeg merge → clip_001_final.mp4
              ├── Sync response  {"status":"success","url":"..."} → download clip
              ├── Async response {"status":"pending","job_id":"abc"} → poll /status/{id}
              └── Error / timeout → SKIP scene, log reason, continue
```

**Worker blacklist** — failed workers are blacklisted for the session. Cleared on next START.

**Dry Run ON** — creates `.mp4.placeholder` files only. No DeepSeek, no Worker calls.

---

## Script Supervisor

Imports any novel or screenplay and generates a new scene list via LLM.

### Controls

| Control | Purpose |
|---|---|
| 📂 Load Script | File dialog — .txt / .md |
| LLM dropdown | All workers with URL + local Ollama models |
| 🎬 Generate Scenes | Active only when file + LLM selected |
| 🔄 Reset (Ison-Codex) | Restores built-in 55-scene list |
| ◼ Cancel Import | Stops import after current chapter |

### Import Process (multi-turn)

```
Step 1  Send full script → ask LLM to list all chapter headings as JSON
Step 2  For each chapter → ask LLM for scenes of that chapter only
Step 3  Merge all chapters, renumber IDs (S01, S02, ...), save
```

---

## Workers

### Video Workers

| Type | Tool | Notes |
|---|---|---|
| `sora` | Sora 2 (Bing) | Wide shots, landscapes |
| `runway` | Runway | Fractals, data streams |
| `seedance` | Seedance 2.0 | Atmospheric transitions |
| `digen` | Digen (CapCut) | Dialogues, multi-character |
| `comfyui_local` | ComfyUI (WAN 2.1) | Local GPU, no API key, full audio pipeline |

**comfyui_local** communicates directly with ComfyUI API — no `workers.json` entry needed.

### LLM Workers (prompt enhancement)

- **OpenAI-compatible** (DeepSeek, OpenAI): POST to `/chat/completions`
- **Ollama** (local, `:11434`): POST to `/api/chat`
- **Local Ollama models**: fetched from `http://127.0.0.1:11434/api/tags`

---

## Visual DNA

Embedded in every enhanced prompt:

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
│   ├── lyra_production_config.json
│   ├── szenen_importiert.json
│   └── szenen_default.json
├── style/
│   └── production_handbook.txt         Visual Bible
├── audio/
│   └── screenplay.txt                  Full narration script
└── szenen/
    ├── S01/
    │   ├── prompt.txt
    │   └── comfyui_local/
    │       ├── clip_001.mp4            First video clip
    │       ├── clip_002.mp4            Additional clips (multi-clip)
    │       ├── narration.wav           ChatterBox TTS
    │       ├── music.wav               ACE-Step score
    │       └── clip_001_final.mp4      ✅ Final output
    └── TOTAL/

<project>/
├── ComfyUI-Portable/
│   ├── venv/                           Python 3.11 + torch cu128
│   ├── models/
│   │   ├── diffusion_models/           wan2.1_t2v_1.3B_bf16.safetensors
│   │   ├── vae/                        wan_2.1_vae.safetensors
│   │   ├── text_encoders/              umt5_xxl_fp8_e4m3fn_scaled.safetensors
│   │   ├── checkpoints/                v1-5-pruned-emaonly-fp16.safetensors
│   │   └── TTS/
│   │       ├── chatterbox/English/     ChatterBox model files
│   │       └── ACE-Step-v1-3.5B/       Music model (4 subfolders)
│   └── custom_nodes/
│       ├── ComfyUI-Manager/
│       ├── ComfyUI-VideoHelperSuite/
│       ├── ComfyUI-AudioTools/
│       ├── ComfyUI-Florence2/
│       ├── TTS-Audio-Suite/            ChatterBox + ACE-Step nodes
│       └── ComfyUI_ACE-Step/
└── setupfiles/                         Download cache (reused on re-install)
```

---

## Key Files

| File | Purpose |
|---|---|
| `IsonCodexProducer.py` | Main application (5500+ lines) |
| `~/.openclaw/workers.json` | Worker definitions shared with OpenClaw |
| `~/.openclaw/ison_producer.json` | Saved storage path |
| `<storage>/config/szenen_importiert.json` | Active imported scene list |
| `<project>/ComfyUI-Portable/start_comfyui.bat` | Manual ComfyUI start |

---

## Known Behaviours

| Behaviour | Detail |
|---|---|
| First ChatterBox run slow | Downloads `English/` model files (~1 GB) on first use. Cached in `setupfiles/chatterbox/English/` afterwards. |
| ACE-Step render time | 60 steps @ ~35–52s/step = 35–52 min for 20s music. Timeout set to 4 hours. |
| WAN 2.1 render time | ~15 min per 5s clip. 18s scene = 4 clips = ~60 min total. |
| `torch_dtype` deprecation warning | ACE-Step internal API — harmless, fixed on next `git pull`. |
| Log auto-scroll | Scrolls to bottom only if already at bottom — manual scroll position preserved. |

---

## Integration with OpenClaw / LYRA

```
OpenClawWinInstaller → 🎭 LYRA Role: cinematic_coordinator → ▶ Start App
```

---

*Part of the OpenClaw / LYRA ecosystem — OpenClawWinInstaller v1.0.4*
