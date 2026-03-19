# pytorch_setup_gui.py — Documentation

**Version:** 2.0.5
**File:** `Tools/pytorch_setup_gui/pytorch_setup_gui.py`
**Lines:** 2,647
**Python:** 3.8+
**Run:** `python Tools/pytorch_setup_gui/pytorch_setup_gui.py`

---

## Purpose

GUI installer for PyTorch & HuggingFace Transformers with automatic hardware detection,
CUDA version detection, and mode-dependent package configuration. Runs on Windows, Linux and macOS.

---

## Architecture — Classes & Functions

```
pytorch_setup_gui.py
│
├── ensure_package(package_name)          L.28   Auto-pip-installs missing dependencies
├── safe_str(obj)                         L.66   Unicode-safe string converter
│
├── class HardwareDetector                L.83   Hardware detection & mode recommendation
│   ├── _get_cpu_info()                   L.99   Cores, threads, frequency via psutil
│   ├── _get_gpu_info()                   L.119  nvidia-smi / wmic / Darwin arm64
│   ├── _get_ram_info()                   L.173  RAM total/available via psutil
│   ├── _detect_nvidia_gpu()              L.188  Boolean flag
│   ├── _detect_amd_gpu()                 L.195  Boolean flag
│   ├── _detect_apple_silicon()           L.202  Darwin + arm64 check
│   ├── _check_avx2()                     L.206  Heuristic: >=4 cores assumed = AVX2
│   ├── _get_gpu_memory()                 L.221  VRAM in MB via nvidia-smi
│   ├── _recommend_mode()                 L.236  Returns mode + reason + pip command
│   ├── get_hardware_summary()            L.307  ASCII-formatted hardware report
│   └── get_mode_details(mode)            L.336  Package list + env_vars per mode
│
├── class InstallationTester              L.484  Test & verification of existing installation
│   ├── get_python_path()                 L.491  venv-aware Python path
│   ├── get_pip_path()                    L.511  venv-aware pip path
│   ├── check_package_installed(pkg)      L.530  importlib check via subprocess
│   ├── get_all_installed_packages()      L.572  pip list --format=json
│   ├── test_pytorch_basics()             L.616  Tensor test on CUDA/MPS/CPU
│   ├── test_transformers_basics()        L.700  distilgpt2 inference test (with download)
│   ├── test_transformers_simple()        L.787  gpt2 tokenizer test (no download)
│   ├── run_comprehensive_test()          L.848  All tests → status object
│   └── generate_test_report()            L.949  Human-readable ASCII report
│
├── class PyTorchInstaller                L.1083 Installation engine
│   ├── log(message, level)               L.1096 Central logging with ASCII symbols
│   ├── set_mode(mode)                    L.1127 CPU / GPU / HYBRID / MPS / ROCM
│   ├── check_existing_installation()     L.1135 run_comprehensive_test() with log output
│   ├── check_python_version()            L.1163 >= 3.8 required
│   ├── check_pip()                       L.1173 pip available?
│   ├── create_virtual_environment()      L.1184 ~/pytorch_env/venv, pip upgrade
│   ├── detect_cuda_version()             L.1233 CUDA_PATH → nvidia-smi → nvcc search
│   ├── get_pytorch_cuda_url(cuda_ver)    L.1379 CUDA version → PyTorch WHL URL
│   ├── verify_cuda_installation(python)  L.1440 Post-install CUDA tensor test
│   ├── install_pytorch()                 L.1539 torch+torchvision+torchaudio, then rest
│   ├── verify_installation()             L.1716 run_comprehensive_test() after install
│   ├── set_environment_variables()       L.1766 Writes into activate.bat / activate
│   ├── create_activation_scripts()       L.1801 .bat / .ps1 / .sh
│   ├── create_test_script()              L.1841 ~/pytorch_env/test_pytorch.py
│   ├── create_config_file()              L.1946 ~/pytorch_env/pytorch_config.json
│   ├── create_desktop_shortcut()         L.1992 Windows-only via WScript.Shell
│   ├── run_installation()                L.2020 9-step installation pipeline
│   ├── show_summary()                    L.2070 ASCII summary after installation
│   └── test_only()                       L.2111 Run tests only, no installation
│
└── class PyTorchSetupGUI                 L.2146 tkinter main window (1200x800)
    ├── setup_styles()                    L.2188 Color scheme for log levels
    ├── setup_gui()                       L.2212 PanedWindow: left = controls, right = log
    ├── create_hardware_frame()           L.2254 Hardware text box + buttons
    ├── create_mode_frame()               L.2280 5 radio buttons (CPU/GPU/HYBRID/MPS/ROCM)
    ├── create_options_frame()            L.2310 Shortcut + detailed log checkboxes
    ├── create_status_frame()             L.2325 Status label + indeterminate progressbar
    ├── create_action_buttons()           L.2338 Start / Test / Exit
    ├── create_log_frame()                L.2353 Color-coded scrolled text log on right
    ├── show_hardware_info()              L.--   HardwareDetector summary into text widget
    ├── detect_cuda()                     L.--   detect_cuda_version() in GUI thread
    ├── on_mode_change()                  L.--   installer.set_mode() on radio button change
    ├── auto_check_installation()         L.2455 Auto-triggered after 1s on startup
    ├── start_installation()              L.2514 run_installation() in daemon thread
    ├── test_installation()               L.2572 test_only() in daemon thread
    └── cancel_installation()             L.2608 Stop or root.quit()
```

---

## Installation Modes

| Mode | Trigger | Packages | Environment Variables |
|---|---|---|---|
| **CPU** | No GPU detected | torch, torchvision, torchaudio, transformers, accelerate, sentencepiece, protobuf, datasets, tokenizers | `CUDA_VISIBLE_DEVICES=-1`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` |
| **GPU** | NVIDIA >= 8 GB VRAM | + xformers, triton, bitsandbytes, peft, trl | `CUDA_LAUNCH_BLOCKING=1`, `TORCH_CUDNN_V8_API_ENABLED=1`, `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512` |
| **HYBRID** | NVIDIA < 8 GB VRAM | torch, transformers, accelerate, bitsandbytes, ... | `CUDA_LAUNCH_BLOCKING=1`, `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:256`, `OMP_NUM_THREADS` |
| **MPS** | Apple Silicon (arm64) | torch, transformers, accelerate, ... | `PYTORCH_ENABLE_MPS_FALLBACK=1` |
| **ROCM** | AMD GPU (wmic) | torch, transformers, accelerate, ... | `HSA_OVERRIDE_GFX_VERSION=10.3.0`, `ROCM_PATH=/opt/rocm` |

---

## CUDA Detection (detect_cuda_version)

Three-stage method (L.1233):

1. **CUDA_PATH** environment variable → regex `v(\d+\.\d+)` from path
2. **nvidia-smi** `--query-gpu=driver_version` → driver-to-CUDA mapping:
   - Driver >= 525 → CUDA 12.x
   - Driver >= 520 → CUDA 11.8
   - Driver >= 450 → CUDA 11.x
3. **nvcc** — searches in CUDA_PATH, then 11 fixed paths (v12.8 down to v11.6), then PATH

### PyTorch WHL URL Mapping (L.1386)

```
CUDA 12.8 → cu128
CUDA 12.6 → cu126
CUDA 12.4 → cu124
CUDA 12.1 → cu121
CUDA 11.8 → cu118  (default fallback for 11.x)
CUDA 11.x → cu118
ROCm      → rocm5.6
CPU / MPS → default index (no --index-url)
```

---

## Installation Pipeline (run_installation, L.2020)

| Step | Method | Notes |
|---|---|---|
| 1 | `check_python_version()` | >= 3.8 required |
| 2 | `check_pip()` | pip must be available |
| 3 | `create_virtual_environment()` | ~/pytorch_env/venv |
| 4 | `install_pytorch()` | torch + mode packages |
| 5 | `verify_installation()` | functional test |
| 6 | `set_environment_variables()` | patches activate.bat |
| 7 | `create_activation_scripts()` | .bat / .ps1 / .sh |
| 8 | `create_test_script()` | test_pytorch.py |
| 9 | `create_config_file()` | pytorch_config.json |
| 10 | `create_desktop_shortcut()` | Windows optional |

Failures in steps 1–9 are logged but **do not abort** the pipeline (continue logic).

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

| File | Path | Content |
|---|---|---|
| venv | `~/pytorch_env/venv/` | Virtual environment |
| Activation (Windows) | `~/pytorch_env/activate_pytorch.bat` | Activates venv |
| Activation (PS) | `~/pytorch_env/activate_pytorch.ps1` | PowerShell version |
| Activation (Unix) | `~/pytorch_env/activate_pytorch.sh` | Shell version |
| Test script | `~/pytorch_env/test_pytorch.py` | Standalone test |
| Configuration | `~/pytorch_env/pytorch_config.json` | Hardware + CUDA + packages |
| Desktop shortcut | `~/Desktop/PyTorch Environment.lnk` | Windows optional |

---

## Notable Design Decisions

**AVX2 heuristic (L.206–218):** `_check_avx2()` does not actually detect AVX2 — it uses
`cores >= 4` as a proxy. On Windows, `wmic cpu get architecture` does not expose AVX2 flags.
This is a deliberate simplification; the value is only displayed informally and has no
functional impact on the installation.

**FULLY_FUNCTIONAL status excludes CPU-only (L.918–931):** The status logic treats
`cuda_available=False` as a failure, meaning a correctly working CPU-only installation
is marked as `INSTALLED_BUT_BROKEN`. Transformers is not factored into the status at all.
This may produce confusing messages on CPU-only systems.

**Automatic CPU fallback on GPU failure (L.1647–1665):** If the CUDA-enabled installation
fails, `install_pytorch()` automatically retries with a CPU-only install (no `--index-url`).

**Threading model (L.2536, 2581):** All long-running operations run in `daemon=True` threads.
Results are passed back to the GUI thread via `root.after(0, callback)`.
Log output flows through a `queue.Queue` that is drained every 100ms (L.2503).

---

## Dependencies

| Package | Source | Purpose |
|---|---|---|
| `tkinter` | stdlib | GUI |
| `psutil` | pip (auto-install) | RAM / CPU info |
| `subprocess` | stdlib | nvidia-smi, nvcc, pip |
| `threading` | stdlib | Non-blocking operations |
| `queue` | stdlib | Thread → GUI communication |
| `json` | stdlib | Config, pip output |
| `re` | stdlib | CUDA version parsing |

---

## Running

```bash
python Tools/pytorch_setup_gui/pytorch_setup_gui.py
```

Window: 1200×800, resizable (min 1000×700), centered on startup.
On startup, `auto_check_installation()` is triggered automatically after 1 second.
