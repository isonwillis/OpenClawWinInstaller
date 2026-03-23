# ClaudeCodeSetup.py — Documentation

**Version:** 1.0.1
**File:** `Tools/ClaudeCodeSetup/ClaudeCodeSetup.py`
**Lines:** 1,102
**Python:** 3.10+
**Run:** `python Tools/ClaudeCodeSetup/ClaudeCodeSetup.py`

---

## Purpose

GUI installer that sets up the Claude Code ↔ Lyra Self-Improvement Observer layer.
It verifies prerequisites, generates configuration files and PowerShell scripts, and
provides Start / Stop / Uninstall controls for the observer session.
Windows-only (PowerShell scripts are not executed on other platforms).

---

## Architecture — Classes & Functions

```
ClaudeCodeSetup.py
│
├── build_claude_md(project_dir, openclaw_dir)   L.60   Generates CLAUDE.md content string
├── _ps(path)                                    L.318  Normalises path for PowerShell (backslashes)
├── build_observer_ps1(project_dir, openclaw_dir)L.323  Generates lyra_observer.ps1 content
├── build_stop_ps1(project_dir)                  L.376  Generates lyra_observer_stop.ps1 content
├── build_uninstall_ps1(project_dir)             L.409  Generates lyra_observer_uninstall.ps1 content
│
├── class InstallerLogic                         L.466  Headless installation logic
│   ├── __init__(log_cb, status_cb)              L.467  Stores GUI callbacks
│   ├── run_step(label, fn)                      L.471  Executes one step, logs result
│   ├── check_python()                           L.481  Requires Python >= 3.10
│   ├── _find_node_dir()                         L.490  Locates node.exe directory
│   ├── _npm_cmd()                               L.508  Resolves npm invocation list
│   ├── _claude_cmd()                            L.524  Resolves claude CLI invocation list
│   ├── check_node()                             L.546  Validates Node.js installation
│   ├── check_npm()                              L.565  Validates npm availability
│   ├── check_claude_code()                      L.583  Validates claude CLI
│   ├── fix_npm_path_and_install_claude(log_cb)  L.593  Adds Node dir to PATH, runs npm install -g
│   ├── create_dirs(project_dir)                 L.645  Creates ClaudeCode/, logs/, scripts/
│   ├── write_claude_md(project_dir, openclaw_dir)L.655 Writes CLAUDE.md
│   ├── write_scripts(project_dir, openclaw_dir) L.662  Writes three .ps1 scripts (UTF-8 BOM)
│   ├── write_install_log(project_dir, …)        L.676  Writes timestamped install log entry
│   ├── install(project_dir, openclaw_dir)       L.694  Full 8-step installation sequence
│   ├── start_observer(project_dir)              L.722  Launches observer in new terminal window
│   ├── stop_observer(project_dir)               L.753  Runs stop script via PowerShell
│   └── uninstall(project_dir)                   L.763  Runs uninstall script in new console
│
└── class App(tk.Tk)                             L.778  Main application window
    ├── __init__()                               L.779  Builds UI, attaches InstallerLogic
    ├── _center()                                L.794  Centers 860×700 window on screen
    ├── _build_ui()                              L.803  Calls all _build_* methods in order
    ├── _build_header()                          L.810  Title bar with app name and version
    ├── _build_paths()                           L.832  Path config panel (project + .openclaw)
    ├── _build_path_row(parent, label, var, row) L.859  Label + entry + browse button row
    ├── _build_status_bar()                      L.874  Single-line status indicator
    ├── _build_log()                             L.887  Scrolled text log with colour tags
    ├── _build_buttons()                         L.917  Two button rows (primary + fix)
    ├── _flat_btn(parent, text, cmd)             L.953  Secondary flat-style button
    ├── _action_btn(parent, text, cmd, color)    L.966  Primary accent-coloured button
    ├── _browse(var)                             L.981  Directory chooser → StringVar
    ├── _on_fix_npm()                            L.986  Button handler: npm fix + install
    ├── _on_install()                            L.1003 Button handler: full installation
    ├── _on_start()                              L.1025 Button handler: start observer
    ├── _on_stop()                               L.1033 Button handler: stop observer
    ├── _on_uninstall()                          L.1041 Button handler: uninstall (with confirm)
    ├── _safe_run(fn, *args)                     L.1055 Exception guard for daemon thread calls
    ├── _clear_log()                             L.1062 Clears log widget content
    ├── _log(msg, tag)                           L.1069 Thread-safe log append via after(0, ...)
    └── _set_status(msg, level)                  L.1077 Thread-safe status bar update
```

---

## Installation Sequence (install, L.694)

| Step | Method | Action |
|---|---|---|
| 1 | `check_python()` | Python >= 3.10 required |
| 2 | `check_node()` | Node.js must be installed |
| 3 | `check_npm()` | npm must be reachable |
| 4 | `check_claude_code()` | claude CLI must be installed |
| 5 | `create_dirs()` | Creates `ClaudeCode/`, `logs/`, `scripts/` |
| 6 | `write_claude_md()` | Writes `CLAUDE.md` to project root |
| 7 | `write_scripts()` | Writes three PowerShell scripts |
| 8 | `write_install_log()` | Writes timestamped log entry |

Each step runs through `run_step()` — failures are logged but do not abort the sequence.

---

## Generated Files

| File | Location | Purpose |
|---|---|---|
| `CLAUDE.md` | `<project_dir>/` | Claude Code context: identity, paths, rules |
| `lyra_observer.ps1` | `<project_dir>/` | Starts the Claude Code observer session |
| `lyra_observer_stop.ps1` | `<project_dir>/` | Terminates all observer sessions |
| `lyra_observer_uninstall.ps1` | `<project_dir>/` | Removes ClaudeCode layer files |
| `ClaudeCode/logs/` | `<project_dir>/` | Log directory (never deleted) |
| `ClaudeCode/scripts/` | `<project_dir>/` | Scripts directory (never deleted) |
| `ClaudeCode/logs/YYYY-MM-DD_HH-MM_install.log` | above | Install log entry |

PowerShell scripts are written as **UTF-8 with BOM** (`utf-8-sig`) so PowerShell 5
reads non-ASCII characters correctly on systems with non-UTF-8 default codepages.

---

## Node.js / npm Resolution Strategy

`_find_node_dir()` searches in this order:
1. `shutil.which("node")` — already on PATH
2. `%ProgramFiles%\nodejs`
3. `%ProgramFiles(x86)%\nodejs`
4. `%APPDATA%\nvm\current`
5. `%LOCALAPPDATA%\Programs\nodejs`

`_npm_cmd()` tries: `npm.cmd` → `npm` → `<node_dir>\npm.cmd` → `node npm-cli.js`

`_claude_cmd()` tries: `claude.cmd` → `claude` → `<node_dir>\claude.cmd` → `%APPDATA%\npm\claude.cmd`

---

## Observer Launch Strategy (start_observer, L.722)

Claude Code requires an interactive terminal and cannot run headless.

1. **Windows Terminal** (`wt.exe`) — preferred, opens a named tab
2. **`cmd /c start`** — fallback, forces a new visible console window

---

## Threading Model

All long-running operations (`install`, `start_observer`, `stop_observer`, `uninstall`,
`fix_npm_path_and_install_claude`) are dispatched as `daemon=True` threads via
`threading.Thread`. GUI updates from threads use `self.after(0, fn)` to stay thread-safe.

---

## GUI Colour Scheme

| Key | Usage |
|---|---|
| `accent` (`#00c8ff`) | Step headings, primary buttons, title |
| `accent2` (`#7b5cf0`) | Version label, npm fix button |
| `success` | OK status and log lines |
| `warn` | Warning status and log lines |
| `error` | Error status, uninstall button |
| `text_dim` | Subtitle, status bar default |

Log tags: `step`, `ok`, `warn`, `error`, `info` — each mapped to the colour scheme above.

---

## Prerequisites

| Requirement | Minimum | Check |
|---|---|---|
| Python | 3.10 | `check_python()` |
| Node.js | any LTS | `check_node()` |
| npm | bundled with Node | `check_npm()` |
| Claude Code CLI | latest | `check_claude_code()` |

If npm or Claude Code are missing, the **npm fix + install** button runs
`npm install -g @anthropic-ai/claude-code` automatically after adding the Node
directory to the user PATH.
