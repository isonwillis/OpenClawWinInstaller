# PyTorch Setup GUI — Documentation

**Version:** 1.1.1  
**Files:**
- `pytorch_setup_gui.py` — Current active file (Windows + WSL2 support)
- `pytorch_setup_gui_wsl.py` — Previous filename (renamed)

**Lines:** 3,769  
**Python:** 3.8+ (Windows) / 3.10+ (WSL2)  
**Run:** `python pytorch_setup_gui.py`

---

## Purpose

GUI installer for PyTorch & HuggingFace Transformers with automatic hardware detection,
CUDA version detection, and mode-dependent package configuration. Supports two platforms:

- **Windows** — native venv, CUDA 12.8, cu128 wheels
- **WSL2** — Ubuntu venv via `--without-pip` + `get-pip.py` bootstrap, Triton support for DNABERT-2

---

## Architecture — Classes & Functions

```
pytorch_setup_gui.py
│
├── ensure_package(package_name)              L.30    Auto-pip-installs missing dependencies
├── safe_str(obj)                             L.68    Unicode-safe string converter
├── _get_no_window_kwargs()                   L.86    CREATE_NO_WINDOW flags for Windows
├── run_hidden(cmd, **kwargs)                 L.99    subprocess.run() wrapper — no CMD flash
│
├── class HardwareDetector                    L.112   Hardware detection & mode recommendation
│   ├── _get_cpu_info()                       L.128   Cores, threads, frequency via psutil
│   ├── _get_gpu_info()                       L.148   nvidia-smi / wmic / Darwin arm64
│   ├── _get_ram_info()                       L.198   RAM total/available via psutil
│   ├── _detect_nvidia_gpu()                  L.213   Boolean flag
│   ├── _detect_amd_gpu()                     L.220   Boolean flag
│   ├── _detect_apple_silicon()               L.227   Darwin + arm64 check
│   ├── _check_avx2()                         L.231   Heuristic: >=4 cores assumed = AVX2
│   ├── _get_gpu_memory()                     L.241   VRAM in MB via nvidia-smi
│   ├── _recommend_mode()                     L.256   Returns mode + reason + pip command
│   ├── get_hardware_summary()                L.327   ASCII-formatted hardware report
│   └── get_mode_details(mode)                L.356   Package list + env_vars per mode
│
├── class WSL2Manager                         L.505   Low-level WSL2 command execution
│   ├── check_wsl_available()                 L.517   wsl --status check
│   ├── get_wsl_distros()                     L.545   wsl --list --quiet
│   ├── get_default_distro()                  L.556   Finds * Running distro
│   ├── run_wsl_command(cmd, timeout)         L.574   run_hidden(['wsl'] + cmd) wrapper
│   ├── ensure_python_in_wsl()                L.589   Python 3.10+ check; skips apt if venv ok
│   ├── ensure_pip_in_wsl()                   L.643   python3 -m pip → pip3 → get-pip.py
│   ├── get_wsl_home()                        L.678   echo $HOME in WSL
│   └── create_wsl_project_dir(name)          L.685   mkdir -p ~/pytorch_env
│
├── class WSL2PyTorchInstaller                L.703   8-step WSL2 installation engine
│   ├── check_prerequisites()                 L.737   Python + pip checks
│   ├── create_project_directory()            L.759   ~/pytorch_env in WSL
│   ├── create_virtual_environment()          L.776   venv → --without-pip → get-pip.py
│   ├── detect_cuda_version_in_wsl()          L.833   nvidia-smi grep -oP → nvcc fallback
│   ├── install_pytorch()                     L.863   CUDA-adaptive cu128 wheels + NCCL fix
│   ├── install_transformers_and_deps()       L.953   14 packages incl. triton for DNABERT-2
│   ├── verify_installation()                 L.995   python3 -c inline script, NCCL env vars
│   ├── create_test_script()                  L.1075  test_pytorch_wsl.py
│   ├── create_activation_script()            L.1180  activate_pytorch.sh
│   ├── run_installation()                    L.1213  8-step pipeline
│   ├── show_summary()                        L.1256  ASCII summary
│   └── test_only()                           L.1293  Tests without install
│
├── class InstallationTester                  L.1320  Test & verification of existing install
│   ├── get_python_path()                     L.1327  venv-aware Python path
│   ├── get_pip_path()                        L.1347  venv-aware pip path
│   ├── check_package_installed(pkg)          L.1366  importlib check via run_hidden()
│   ├── get_all_installed_packages()          L.1401  pip list --format=json
│   ├── test_pytorch_basics()                 L.1437  Tensor test on CUDA/MPS/CPU
│   ├── test_transformers_basics()            L.1513  distilgpt2 inference test
│   ├── test_transformers_simple()            L.1592  gpt2 tokenizer test (no download)
│   ├── run_comprehensive_test()              L.1645  All tests → status object
│   └── generate_test_report()               L.1746  Human-readable ASCII report
│
├── class PyTorchInstaller                    L.1884  Windows installation engine
│   ├── check_existing_installation()         L.1936  run_comprehensive_test() with log output
│   ├── check_python_version()                L.1964  >= 3.8 required
│   ├── check_pip()                           L.1974  pip available?
│   ├── create_virtual_environment()          L.1984  %USERPROFILE%\pytorch_env\venv
│   ├── detect_cuda_version()                 L.2030  CUDA_PATH → nvidia-smi → nvcc search
│   ├── get_pytorch_cuda_url(cuda_ver)        L.2162  CUDA version → PyTorch WHL URL
│   ├── verify_cuda_installation(python)      L.2223  Post-install CUDA tensor test
│   ├── install_pytorch()                     L.2315  torch+torchvision+torchaudio + rest
│   ├── verify_installation()                 L.2477  run_comprehensive_test() after install
│   ├── set_environment_variables()           L.2527  Writes into activate.bat / activate
│   ├── create_activation_scripts()           L.2562  .bat / .ps1 / .sh
│   ├── create_test_script()                  L.2602  test_pytorch.py
│   ├── create_config_file()                  L.2707  pytorch_config.json
│   ├── create_desktop_shortcut()             L.2753  Windows-only via PowerShell
│   ├── run_installation(create_shortcut)     L.2781  10-step pipeline
│   ├── show_summary()                        L.2831  ASCII summary after installation
│   └── test_only()                           L.2873  Run tests only, no installation
│
├── class PlatformSelector                    L.2909  Routes between Windows and WSL2
│   ├── set_platform(platform)                L.2930  PLATFORM_WINDOWS / PLATFORM_WSL2
│   ├── get_windows_installer()               L.2938  Returns PyTorchInstaller instance
│   ├── get_wsl2_installer()                  L.2947  Returns WSL2PyTorchInstaller instance
│   ├── run_installation(create_shortcut)     L.2956  Delegates to active platform
│   ├── test_installation()                   L.2965  Delegates to active platform
│   └── check_wsl_availability()             L.2974  WSL2Manager.check_wsl_available()
│
└── class PyTorchSetupGUI                     L.2987  tkinter main window (1200×800)
    ├── setup_styles()                        L.3033  Color scheme for log levels
    ├── setup_gui()                           L.3057  PanedWindow: left = controls, right = log
    ├── create_platform_frame()               L.3102  Windows / WSL2 radio buttons
    ├── create_hardware_frame()               L.3138  Hardware text box + buttons
    ├── create_mode_frame()                   L.3164  5 radio buttons (CPU/GPU/HYBRID/MPS/ROCM)
    ├── create_options_frame()                L.3194  Shortcut + detailed log checkboxes
    ├── create_status_frame()                 L.3209  Status label + progressbar
    ├── create_action_buttons()               L.3222  Start / Test / Exit
    ├── create_log_frame()                    L.3237  Color-coded scrolled text log
    ├── check_wsl_availability_ui()           L.3262  WSL2 check on platform switch
    ├── on_platform_change()                  L.3291  PlatformSelector.set_platform()
    ├── auto_check_installation()             L.3383  Triggers startup checklist window
    ├── _show_startup_check_window()          L.3387  Modal checklist with live ✔/✘ icons
    ├── _auto_check_complete()                L.3556  Logs result to main log after splash
    ├── start_installation()                  L.3596  run_installation() in daemon thread
    ├── test_installation()                   L.3644  test_only() in daemon thread
    └── cancel_installation()                 L.3669  Stop or root.quit()
```

---

## Platform Selection

| Platform | Class | venv Location | pip Strategy |
|---|---|---|---|
| **Windows** | `PyTorchInstaller` | `%USERPROFILE%\pytorch_env\venv` | Standard `python -m venv` |
| **WSL2** | `WSL2PyTorchInstaller` | `~/pytorch_env/venv` (in WSL) | `--without-pip` + `get-pip.py` bootstrap |

Platform is selected via radio buttons in the GUI. Switching to WSL2 automatically checks
WSL2 availability via `wsl --status`.

---

## Installation Modes (Windows)

| Mode | Trigger | Key Packages | Environment Variables |
|---|---|---|---|
| **CPU** | No GPU | torch, transformers, accelerate, sentencepiece, protobuf, datasets, tokenizers | `CUDA_VISIBLE_DEVICES=-1`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` |
| **GPU** | NVIDIA >= 8 GB VRAM | + xformers, triton, bitsandbytes, peft, trl | `CUDA_LAUNCH_BLOCKING=1`, `TORCH_CUDNN_V8_API_ENABLED=1`, `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512` |
| **HYBRID** | NVIDIA < 8 GB VRAM | torch, transformers, accelerate, bitsandbytes, ... | `CUDA_LAUNCH_BLOCKING=1`, `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:256`, `OMP_NUM_THREADS` |
| **MPS** | Apple Silicon (arm64) | torch, transformers, accelerate, ... | `PYTORCH_ENABLE_MPS_FALLBACK=1` |
| **ROCM** | AMD GPU | torch, transformers, accelerate, ... | `HSA_OVERRIDE_GFX_VERSION=10.3.0`, `ROCM_PATH=/opt/rocm` |

---

## WSL2 Installation Pipeline

| Step | Method | Notes |
|---|---|---|
| 1 | `check_prerequisites()` | `python3 -m venv --help` skips apt if already ok |
| 2 | `create_project_directory()` | `mkdir -p ~/pytorch_env` in WSL |
| 3 | `create_virtual_environment()` | `python3 -m venv` → `--without-pip` → `get-pip.py` |
| 4 | `install_pytorch()` | CUDA autodetect → cu128 wheels + NCCL fix |
| 5 | `install_transformers_and_deps()` | 14 packages incl. triton (DNABERT-2) |
| 6 | `verify_installation()` | Inline `python3 -c` with `NCCL_P2P_DISABLE=1` |
| 7 | `create_test_script()` | `test_pytorch_wsl.py` |
| 8 | `create_activation_script()` | `activate_pytorch.sh` |

---

## Windows Installation Pipeline

| Step | Method | Notes |
|---|---|---|
| 1 | `check_python_version()` | >= 3.8 required |
| 2 | `check_pip()` | pip must be available |
| 3 | `create_virtual_environment()` | `%USERPROFILE%\pytorch_env\venv` |
| 4 | `install_pytorch()` | torch + mode packages with CUDA detection |
| 5 | `verify_installation()` | `run_comprehensive_test()` |
| 6 | `set_environment_variables()` | Patches `activate.bat` |
| 7 | `create_activation_scripts()` | `.bat` / `.ps1` / `.sh` |
| 8 | `create_test_script()` | `test_pytorch.py` |
| 9 | `create_config_file()` | `pytorch_config.json` |
| 10 | `create_desktop_shortcut()` | Windows optional via PowerShell |

---

## CUDA Detection

### Windows (`detect_cuda_version`, L.2030)

1. **`CUDA_PATH`** env variable → regex `v(\d+\.\d+)` from path
2. **`nvidia-smi`** `--query-gpu=driver_version` → driver-to-CUDA mapping
3. **`nvcc`** — searches `CUDA_PATH/bin`, then 11 fixed paths (v12.8 down to v11.6), then `PATH`

### WSL2 (`detect_cuda_version_in_wsl`, L.833)

1. `nvidia-smi` with `grep -oP 'CUDA Version: \K[0-9]+\.[0-9]+'` — extracts CUDA version only
2. `nvcc --version` with `grep -oP 'release \K[0-9]+\.[0-9]+'` as fallback
3. Defaults to `12.8` if neither is available

### PyTorch WHL URL Mapping

```
CUDA 13.x → cu128  (WSL2 driver reports 13.x; cu128 is latest stable)
CUDA 12.8 → cu128
CUDA 12.7 → cu127
CUDA 12.6 → cu126
CUDA 12.4 → cu124
CUDA 12.1 → cu121
CUDA 11.8 → cu118
CUDA 11.x → cu118  (fallback)
ROCm      → rocm5.6
CPU / MPS → default index (no --index-url)
```

---

## NCCL Conflict Fix (WSL2)

WSL2 with CUDA 13.x drivers can produce:
```
libtorch_cuda.so: undefined symbol: ncclDevCommDestroy
```

**Root cause:** System NCCL loads before PyTorch's bundled NCCL.

**Fix applied in `install_pytorch()` and `verify_installation()`:**
- `NCCL_P2P_DISABLE=1` — disables P2P NCCL (not needed for single GPU)
- `NCCL_DISABLE_CHECKS=1` — suppresses NCCL version assertion
- `LD_PRELOAD` set to PyTorch's bundled `libnccl*.so` in `venv/bin/activate` (if found)

---

## Startup Checklist Window (`_show_startup_check_window`, L.3387)

On launch, a modal splash window runs 6 checks in a background thread:

| Check | Method |
|---|---|
| Python environment | `check_python_version()` |
| pip availability | `check_pip()` |
| PyTorch (torch) | `check_package_installed("torch")` |
| Transformers | `check_package_installed("transformers")` |
| Accelerate | `check_package_installed("accelerate")` |
| CUDA / GPU status | `detect_cuda_version()` |

Each row updates live: `···` → `⏳` → `✔` / `✘`. Window closes automatically when done.
Results flow into the main log via `_auto_check_complete()`.

---

## subprocess — No CMD Flash (`run_hidden`, L.99)

All subprocess calls use `run_hidden()` which sets `STARTUPINFO` with `SW_HIDE` and
`creationflags=CREATE_NO_WINDOW` on Windows. Covers: HardwareDetector, WSL2Manager,
InstallationTester, PyTorchInstaller, CUDA detection, package installs, PowerShell shortcut.

---

## Installation Status Values

| Status | Meaning |
|---|---|
| `FULLY_FUNCTIONAL` | All 3 critical packages installed + CUDA test passed |
| `PARTIALLY_INSTALLED` | Some critical packages missing |
| `INSTALLED_BUT_BROKEN` | Installed but tests failed |
| `NOT_INSTALLED` | All critical packages missing |
| `TEST_ERROR` | Exception within the test framework itself |

Critical packages: `torch`, `transformers`, `accelerate`

---

## Output Files

### Windows
| File | Path |
|---|---|
| venv | `%USERPROFILE%\pytorch_env\venv\` |
| Activation (Windows) | `%USERPROFILE%\pytorch_env\activate_pytorch.bat` |
| Activation (PS) | `%USERPROFILE%\pytorch_env\activate_pytorch.ps1` |
| Test script | `%USERPROFILE%\pytorch_env\test_pytorch.py` |
| Configuration | `%USERPROFILE%\pytorch_env\pytorch_config.json` |
| Desktop shortcut | `%USERPROFILE%\Desktop\PyTorch Environment.lnk` |

### WSL2
| File | Path (inside WSL) |
|---|---|
| venv | `~/pytorch_env/venv/` |
| Activation | `~/pytorch_env/activate_pytorch.sh` |
| Test script | `~/pytorch_env/test_pytorch_wsl.py` |

---

## Notable Design Decisions

**`run_hidden()` global wrapper:** Single point of control for suppressing CMD flashes.
Covers every `subprocess.run()` and `subprocess.Popen()` call in the codebase.

**WSL2 venv strategy:** Ubuntu disables `ensurepip` by policy. Fallback chain:
standard venv → `--without-pip` → `get-pip.py` via curl. Requires no apt access.

**apt-get skipped when venv is available:** `ensure_python_in_wsl()` tests
`python3 -m venv --help` before any `apt-get`. Avoids the 120s `apt-get update`
timeout on subsequent runs when packages are already present.

**CUDA version vs driver in WSL2:** `awk '{print $NF}'` on the nvidia-smi header line
returns the driver version (`590.57`), not the CUDA version. Fixed with
`grep -oP 'CUDA Version: \K[0-9]+\.[0-9]+'`.

**Inline `-c` verification script:** WSL2 `verify_installation()` passes Python inline
via `-c` instead of writing a heredoc file. Heredocs through subprocess + WSL have
quoting issues that silently produce empty or broken files.

**AVX2 heuristic:** `_check_avx2()` uses `cores >= 4` as proxy. Display-only, no
functional impact on installation.

**Threading model:** All long-running operations run in `daemon=True` threads. Results
passed to GUI via `root.after(0, callback)`. Log queue drained every 100ms.

---

## Dependencies

| Package | Source | Purpose |
|---|---|---|
| `tkinter` | stdlib | GUI |
| `psutil` | pip (auto-install) | RAM / CPU info |
| `subprocess` | stdlib | nvidia-smi, nvcc, pip, wsl |
| `threading` | stdlib | Non-blocking operations |
| `queue` | stdlib | Thread → GUI communication |
| `json` | stdlib | Config, pip output, verify results |
| `re` | stdlib | CUDA version parsing |
| `time` | stdlib | Splash window delay |

---

## Running

```bash
python pytorch_setup_gui.py
```

Window: 1200×800, resizable (min 1000×700), centered on startup.
On startup, a modal checklist splash window runs automatically and closes when done.

### WSL2 — After Installation

```bash
wsl
cd ~/pytorch_env
source activate_pytorch.sh
python test_pytorch_wsl.py

# Test DNABERT-2:
python -c "from transformers import AutoModel; model = AutoModel.from_pretrained('zhihan1996/DNABERT-2-117M')"
```
