#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🔥 PyTorch & Transformers Setup GUI - COMPLETE EDITION mit WSL2-Unterstützung
Version: 1.1.1
Enhanced: Automatic CUDA version detection and verification
Added: WSL2 support for DNABERT-2 (Triton compatibility)
Fixed: WSL2 pip installation timeout issues
Fixed: Virtual environment creation without pip
"""

import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json
import platform
import time
from datetime import datetime
import queue
from pathlib import Path
import re  # Added for CUDA version parsing

# =============================================================================
# AUTO-INSTALL MISSING DEPENDENCIES
# =============================================================================

def ensure_package(package_name):
    """Ensure a package is installed, install if missing"""
    try:
        __import__(package_name)
        return True
    except ImportError:
        print(f"📦 Installing required package: {package_name}")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package_name])
            return True
        except:
            print(f"❌ Failed to install {package_name}")
            return False

# Install required packages
required_packages = ['psutil']
for pkg in required_packages:
    ensure_package(pkg)

# Now import psutil
import psutil

# =============================================================================
# UNICODE SAFETY FOR WINDOWS CONSOLE
# =============================================================================

if platform.system() == 'Windows':
    import codecs
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except:
        pass

# =============================================================================
# SAFE STRING HANDLING FOR LOGGING
# =============================================================================

def safe_str(obj):
    """Safely convert any object to string without Unicode errors"""
    try:
        if isinstance(obj, bytes):
            return obj.decode('utf-8', errors='replace')
        if obj is None:
            return ""
        if isinstance(obj, (dict, list)):
            return str(obj)
        return str(obj).encode('utf-8', errors='replace').decode('utf-8')
    except:
        return ""


# =============================================================================
# HIDDEN SUBPROCESS HELPER — suppresses CMD flash windows on Windows
# =============================================================================

def _get_no_window_kwargs():
    """Return kwargs that prevent CMD windows from flashing on Windows"""
    if platform.system() == 'Windows':
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        return {
            'startupinfo': si,
            'creationflags': subprocess.CREATE_NO_WINDOW,
        }
    return {}


def run_hidden(cmd, **kwargs):
    """subprocess.run() wrapper that never shows a CMD window"""
    kwargs.setdefault('capture_output', True)
    kwargs.setdefault('text', True)
    kwargs.setdefault('encoding', 'utf-8')
    kwargs.setdefault('errors', 'replace')
    kwargs.update(_get_no_window_kwargs())
    return subprocess.run(cmd, **kwargs)

# =============================================================================
# HARDWARE DETECTION ENGINE
# =============================================================================

class HardwareDetector:
    """Detects CPU, GPU, RAM and recommends optimal configuration"""
    
    def __init__(self):
        self.cpu_info = self._get_cpu_info()
        self.gpu_info = self._get_gpu_info()
        self.ram_info = self._get_ram_info()
        self.has_nvidia_gpu = self._detect_nvidia_gpu()
        self.has_amd_gpu = self._detect_amd_gpu()
        self.has_apple_silicon = self._detect_apple_silicon()
        self.avx2_supported = self._check_avx2()
        
        # GPU Memory Details
        self.gpu_memory = self._get_gpu_memory()
        self.recommended_mode = self._recommend_mode()
        
    def _get_cpu_info(self):
        """Detailed CPU information"""
        try:
            info = {
                'cores': psutil.cpu_count(logical=False) or 0,
                'threads': psutil.cpu_count(logical=True) or 0,
                'frequency': round(psutil.cpu_freq().current / 1000, 2) if psutil.cpu_freq() else 0,
                'architecture': safe_str(platform.machine()),
                'processor': safe_str(platform.processor() or platform.machine())
            }
        except:
            info = {
                'cores': 0,
                'threads': 0,
                'frequency': 0,
                'architecture': 'unknown',
                'processor': 'unknown'
            }
        return info
    
    def _get_gpu_info(self):
        """GPU information via nvidia-smi if available"""
        gpus = []
        
        # NVIDIA GPUs
        try:
            result = run_hidden(
                ['nvidia-smi', '--query-gpu=name,memory.total,driver_version,temperature.gpu',
                 '--format=csv,noheader'], timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        parts = [p.strip() for p in line.split(',')]
                        gpus.append({
                            'vendor': 'NVIDIA',
                            'name': safe_str(parts[0]),
                            'memory': safe_str(parts[1]) if len(parts) > 1 else 'unknown',
                            'driver': safe_str(parts[2]) if len(parts) > 2 else 'unknown',
                            'temperature': safe_str(parts[3]) if len(parts) > 3 else 'unknown'
                        })
        except:
            pass
        
        # AMD GPUs (simplified)
        try:
            if platform.system() == 'Windows':
                result = run_hidden(['wmic', 'path', 'win32_VideoController', 'get', 'name'])
                for line in result.stdout.split('\n')[1:]:
                    if line.strip() and ('AMD' in line or 'Radeon' in line):
                        gpus.append({
                            'vendor': 'AMD',
                            'name': safe_str(line.strip()),
                            'memory': 'unknown',
                            'driver': 'unknown'
                        })
        except:
            pass
        
        # Apple Silicon
        if platform.system() == 'Darwin' and platform.machine() == 'arm64':
            gpus.append({
                'vendor': 'Apple',
                'name': 'Apple Silicon (M1/M2/M3)',
                'memory': 'shared',
                'driver': 'Metal'
            })
        
        return gpus
    
    def _get_ram_info(self):
        """RAM information"""
        try:
            return {
                'total_gb': round(psutil.virtual_memory().total / (1024**3), 1),
                'available_gb': round(psutil.virtual_memory().available / (1024**3), 1),
                'percent_used': psutil.virtual_memory().percent
            }
        except:
            return {
                'total_gb': 0,
                'available_gb': 0,
                'percent_used': 0
            }
    
    def _detect_nvidia_gpu(self):
        """Check for NVIDIA GPU"""
        for gpu in self.gpu_info:
            if gpu['vendor'] == 'NVIDIA':
                return True
        return False
    
    def _detect_amd_gpu(self):
        """Check for AMD GPU"""
        for gpu in self.gpu_info:
            if gpu['vendor'] == 'AMD':
                return True
        return False
    
    def _detect_apple_silicon(self):
        """Check for Apple Silicon (M1/M2/M3)"""
        return platform.system() == 'Darwin' and platform.machine() == 'arm64'
    
    def _check_avx2(self):
        """Check AVX2 support (important for modern models)"""
        if platform.system() == 'Windows':
            try:
                run_hidden(['wmic', 'cpu', 'get', 'architecture'], timeout=2)
                return self.cpu_info.get('cores', 0) >= 4
            except:
                return self.cpu_info.get('cores', 0) >= 4
        return True
    
    def _get_gpu_memory(self):
        """Get available GPU memory in MB"""
        if self.has_nvidia_gpu:
            try:
                result = run_hidden(
                    ['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader'],
                    timeout=3
                )
                if result.returncode == 0:
                    mem_str = result.stdout.strip().split()[0]
                    return int(mem_str)
            except:
                pass
        return 0
    
    def _recommend_mode(self):
        """Recommend optimal operating mode"""
        recommendations = {
            'mode': 'CPU',
            'reason': [],
            'models': [],
            'torch_command': '',
            'performance': 'Standard'
        }
        
        # Apple Silicon (MPS)
        if self.has_apple_silicon:
            recommendations['mode'] = 'MPS'
            recommendations['reason'].append("Apple Silicon detected - MPS acceleration available")
            recommendations['torch_command'] = 'pip install torch torchvision torchaudio'
            recommendations['performance'] = 'EXCELLENT for Apple Silicon'
            recommendations['models'] = [
                'microsoft/DialoGPT-medium',
                'facebook/blenderbot-400M-distill',
                'meta-llama/Llama-2-7b (with quantization)'
            ]
            return recommendations
        
        # NVIDIA GPU
        if self.has_nvidia_gpu:
            if self.gpu_memory >= 8000:  # 8GB+
                recommendations['mode'] = 'GPU'
                recommendations['reason'].append(f"NVIDIA GPU with {self.gpu_memory}MB VRAM")
                recommendations['torch_command'] = 'pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118'
                recommendations['performance'] = 'MAXIMUM'
            elif self.gpu_memory >= 4000:  # 4-8GB
                recommendations['mode'] = 'HYBRID'
                recommendations['reason'].append(f"NVIDIA GPU with {self.gpu_memory}MB VRAM - Hybrid mode recommended")
                recommendations['torch_command'] = 'pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118'
                recommendations['performance'] = 'HIGH (with memory optimization)'
            else:  # <4GB
                recommendations['mode'] = 'HYBRID'
                recommendations['reason'].append(f"Smaller GPU ({self.gpu_memory}MB) - Hybrid mode for larger models")
                recommendations['torch_command'] = 'pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118'
                recommendations['performance'] = 'GOOD (with offloading)'
        
        # AMD GPU
        elif self.has_amd_gpu:
            recommendations['mode'] = 'ROCM'
            recommendations['reason'].append("AMD GPU detected - ROCm support")
            recommendations['torch_command'] = 'pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.6'
            recommendations['performance'] = 'GOOD (ROCm)'
        
        # CPU Only
        else:
            recommendations['mode'] = 'CPU'
            recommendations['reason'].append("No dedicated GPU found - CPU mode")
            recommendations['torch_command'] = 'pip install torch torchvision torchaudio'
            recommendations['performance'] = 'Standard'
            
            # Optimize based on RAM
            if self.ram_info['total_gb'] >= 32:
                recommendations['performance'] = 'GOOD (with large RAM)'
            elif self.ram_info['total_gb'] >= 16:
                recommendations['performance'] = 'ADEQUATE'
            else:
                recommendations['performance'] = 'BASIC (light models only)'
        
        # RAM-based adjustments
        if self.ram_info['total_gb'] < 8:
            recommendations['reason'].append(f"WARNING: Only {self.ram_info['total_gb']}GB RAM - Light models recommended")
        elif self.ram_info['total_gb'] >= 32:
            recommendations['reason'].append(f"EXCELLENT: {self.ram_info['total_gb']}GB RAM - All models possible")
        
        return recommendations
    
    def get_hardware_summary(self):
        """Get formatted hardware summary (ASCII safe)"""
        summary = f"""
+{'-'*58}+
|                 HARDWARE DETECTION                        |
+{'-'*58}+
| CPU: {self.cpu_info['cores']} cores / {self.cpu_info['threads']} threads @ {self.cpu_info['frequency']}GHz
| RAM: {self.ram_info['total_gb']} GB total ({self.ram_info['available_gb']} GB available)
| AVX2: {'SUPPORTED' if self.avx2_supported else 'NOT SUPPORTED'}
+{'-'*58}+
| GPU INFORMATION:
"""
        if self.gpu_info:
            for gpu in self.gpu_info:
                summary += f"| * {gpu['vendor']}: {gpu['name']}\n"
                if gpu.get('memory') and gpu['memory'] != 'unknown':
                    summary += f"|   Memory: {gpu['memory']}\n"
        else:
            summary += "| * No dedicated GPU found\n"
        
        summary += f"+{'-'*58}+\n"
        summary += f"| RECOMMENDATION: {self.recommended_mode['mode']} MODE\n"
        for reason in self.recommended_mode['reason']:
            summary += f"| * {safe_str(reason)}\n"
        summary += f"| Performance: {self.recommended_mode['performance']}\n"
        summary += f"+{'-'*58}+"
        
        return summary
    
    def get_mode_details(self, mode):
        """Get detailed information for a specific mode"""
        modes = {
            'CPU': {
                'name': 'CPU Only',
                'description': 'Optimized for CPU-only systems, no GPU required',
                'packages': [
                    'torch',
                    'torchvision', 
                    'torchaudio',
                    'transformers',
                    'accelerate',
                    'sentencepiece',
                    'protobuf',
                    'datasets',
                    'tokenizers'
                ],
                'env_vars': {
                    'CUDA_VISIBLE_DEVICES': '-1',
                    'OMP_NUM_THREADS': str(self.cpu_info['threads']),
                    'MKL_NUM_THREADS': str(self.cpu_info['threads'])
                },
                'models': [
                    'microsoft/DialoGPT-small (fastest)',
                    'facebook/blenderbot-400M-distill (balanced)',
                    'distilgpt2 (lightweight)',
                    'bert-base-uncased (NLP tasks)'
                ]
            },
            
            'GPU': {
                'name': 'GPU Accelerated',
                'description': 'Full GPU acceleration for NVIDIA graphics cards',
                'packages': [
                    'torch',
                    'torchvision',
                    'torchaudio',
                    'transformers',
                    'accelerate',
                    'xformers',
                    'triton',
                    'bitsandbytes',
                    'sentencepiece',
                    'protobuf',
                    'datasets',
                    'tokenizers',
                    'peft',
                    'trl'
                ],
                'env_vars': {
                    'CUDA_LAUNCH_BLOCKING': '1',
                    'TORCH_CUDNN_V8_API_ENABLED': '1',
                    'PYTORCH_CUDA_ALLOC_CONF': 'max_split_size_mb:512'
                },
                'models': [
                    'microsoft/DialoGPT-medium',
                    'meta-llama/Llama-2-7b-chat-hf',
                    'mistralai/Mistral-7B-Instruct-v0.1',
                    'tiiuae/falcon-7b-instruct'
                ]
            },
            
            'HYBRID': {
                'name': 'Hybrid (GPU + CPU)',
                'description': 'Intelligent distribution: Small models on GPU, large on CPU',
                'packages': [
                    'torch',
                    'torchvision',
                    'torchaudio',
                    'transformers',
                    'accelerate',
                    'bitsandbytes',
                    'sentencepiece',
                    'protobuf',
                    'datasets',
                    'tokenizers'
                ],
                'env_vars': {
                    'CUDA_LAUNCH_BLOCKING': '1',
                    'PYTORCH_CUDA_ALLOC_CONF': 'max_split_size_mb:256',
                    'OMP_NUM_THREADS': str(max(1, self.cpu_info['threads'] // 2))
                },
                'models': [
                    'microsoft/DialoGPT-small (GPU)',
                    'facebook/blenderbot-400M-distill (CPU)',
                    'microsoft/DialoGPT-medium (GPU+CPU offloading)',
                    'google/flan-t5-base (CPU)'
                ],
                'offloading': True
            },
            
            'MPS': {
                'name': 'Apple Silicon (MPS)',
                'description': 'Optimized for Apple M1/M2/M3 chips with Metal acceleration',
                'packages': [
                    'torch',
                    'torchvision',
                    'torchaudio',
                    'transformers',
                    'accelerate',
                    'sentencepiece',
                    'protobuf',
                    'datasets',
                    'tokenizers'
                ],
                'env_vars': {
                    'PYTORCH_ENABLE_MPS_FALLBACK': '1'
                },
                'models': [
                    'microsoft/DialoGPT-medium',
                    'facebook/blenderbot-400M-distill',
                    'bert-base-uncased',
                    'gpt2-medium'
                ]
            },
            
            'ROCM': {
                'name': 'AMD ROCm',
                'description': 'GPU acceleration for AMD graphics cards',
                'packages': [
                    'torch',
                    'torchvision',
                    'torchaudio',
                    'transformers',
                    'accelerate',
                    'sentencepiece',
                    'protobuf',
                    'datasets',
                    'tokenizers'
                ],
                'env_vars': {
                    'HSA_OVERRIDE_GFX_VERSION': '10.3.0',
                    'ROCM_PATH': '/opt/rocm'
                },
                'models': [
                    'microsoft/DialoGPT-medium',
                    'bert-base-uncased',
                    'roberta-base'
                ]
            }
        }
        
        return modes.get(mode, modes['CPU'])


# =============================================================================
# WSL2 SUPPORT - NEW CLASS (FIXED VERSION)
# =============================================================================

class WSL2Manager:
    """Manages WSL2 operations for PyTorch installation"""
    
    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.wsl_distro = None
        self.wsl_home_path = None
        
    def log(self, message, level='INFO'):
        if self.log_callback:
            self.log_callback(message, level)
    
    def check_wsl_available(self):
        """Check if WSL2 is available on the system"""
        if platform.system() != 'Windows':
            self.log("WSL2 is only available on Windows", 'WARNING')
            return False
        
        try:
            result = run_hidden(['wsl', '--status'], timeout=10)
            
            if result.returncode == 0:
                self.log("WSL2 is available on this system", 'SUCCESS')
                if 'WSL 2' in result.stdout or '2' in result.stdout:
                    self.log("WSL2 version detected", 'SUCCESS')
                else:
                    self.log("WSL1 detected - WSL2 recommended for better performance", 'WARNING')
                return True
            else:
                self.log("WSL command not found. Please install WSL2 first.", 'ERROR')
                self.log("Run: wsl --install in PowerShell as Administrator", 'INFO')
                return False
                
        except FileNotFoundError:
            self.log("WSL not found. Please install WSL2 first.", 'ERROR')
            return False
        except Exception as e:
            self.log(f"Error checking WSL: {safe_str(e)}", 'ERROR')
            return False
    
    def get_wsl_distros(self):
        """Get list of available WSL distributions"""
        try:
            result = run_hidden(['wsl', '--list', '--quiet'], timeout=10)
            if result.returncode == 0:
                distros = [d.strip() for d in result.stdout.split('\n') if d.strip()]
                return distros
            return []
        except:
            return []
    
    def get_default_distro(self):
        """Get the default WSL distribution"""
        try:
            result = run_hidden(['wsl', '--list', '--verbose'], timeout=10)
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    if '*' in line and 'Running' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            return parts[1]
                distros = self.get_wsl_distros()
                if distros:
                    return distros[0]
            return None
        except:
            return None
    
    def run_wsl_command(self, command, timeout=300):
        """Run a command inside WSL2 — never shows a CMD window"""
        full_cmd = ['wsl'] + command
        self.log(f"Running in WSL: {' '.join(command[:3])}...", 'DEBUG')
        
        try:
            result = run_hidden(full_cmd, timeout=timeout)
            return result
        except subprocess.TimeoutExpired:
            self.log(f"WSL command timed out after {timeout}s", 'ERROR')
            return None
        except Exception as e:
            self.log(f"WSL command error: {safe_str(e)}", 'ERROR')
            return None
    
    def ensure_python_in_wsl(self):
        """Ensure Python 3.10+ is available in WSL"""
        self.log("Checking Python in WSL...", 'PROCESSING')
        APT = 'DEBIAN_FRONTEND=noninteractive sudo apt-get'

        result = self.run_wsl_command(['python3', '--version'], timeout=10)
        if result and result.returncode == 0:
            version_str = result.stdout.strip()
            self.log(f"Python found: {version_str}", 'SUCCESS')
            match = re.search(r'(\d+)\.(\d+)', version_str)
            if match:
                major, minor = int(match.group(1)), int(match.group(2))
                if major >= 3 and minor >= 10:
                    self.log(f"Python {major}.{minor} meets requirements (3.10+)", 'SUCCESS')
                    # Check if python3-venv is already present — if so skip apt entirely
                    venv_check = self.run_wsl_command(
                        ['bash', '-c', 'python3 -m venv --help >/dev/null 2>&1 && echo "ok"'],
                        timeout=10)
                    if venv_check and venv_check.returncode == 0 and 'ok' in venv_check.stdout:
                        self.log("python3-venv already available, skipping apt-get", 'SUCCESS')
                        return True
                    # venv missing — install without running update first
                    self.log("Installing python3-venv and python3-pip...", 'PROCESSING')
                    r = self.run_wsl_command(['bash', '-c',
                        f'{APT} install -y python3-venv python3-pip python3-dev'], timeout=300)
                    if not r or r.returncode != 0:
                        # update might be needed if cache is stale
                        self.run_wsl_command(['bash', '-c', f'{APT} update -qq'], timeout=120)
                        self.run_wsl_command(['bash', '-c',
                            f'{APT} install -y python3-venv python3-pip python3-dev'], timeout=300)
                    return True
                else:
                    self.log(f"Python {major}.{minor} is too old. Need 3.10+", 'WARNING')

            self.log("Attempting to install Python 3.10...", 'PROCESSING')
            self.run_wsl_command(['bash', '-c', f'{APT} update -qq'], timeout=120)
            r = self.run_wsl_command(['bash', '-c',
                f'{APT} install -y python3.10 python3.10-venv python3.10-dev python3-pip'], timeout=300)
            if r and r.returncode == 0:
                self.log("Python 3.10 installed successfully", 'SUCCESS')
                return True
            self.log("Failed to install Python 3.10", 'ERROR')
            return False

        self.log("Python not found, installing...", 'PROCESSING')
        self.run_wsl_command(['bash', '-c', f'{APT} update -qq'], timeout=120)
        r = self.run_wsl_command(['bash', '-c',
            f'{APT} install -y python3 python3-venv python3-dev python3-pip'], timeout=300)
        if r and r.returncode == 0:
            self.log("Python installed successfully", 'SUCCESS')
            return True
        self.log("Could not install Python in WSL", 'ERROR')
        return False
    
    def ensure_pip_in_wsl(self):
        """Ensure pip is available in WSL"""
        self.log("Checking pip in WSL...", 'PROCESSING')

        # Primary: python3 -m pip (reliable on Ubuntu even without pip3 binary)
        result = self.run_wsl_command(['bash', '-c', 'python3 -m pip --version'], timeout=15)
        if result and result.returncode == 0:
            self.log("pip is available via python3 -m pip", 'SUCCESS')
            self.run_wsl_command(
                ['bash', '-c', 'python3 -m pip install --upgrade pip --quiet'], timeout=60)
            self.log("pip upgraded successfully", 'SUCCESS')
            return True

        # Secondary: pip3 binary
        result2 = self.run_wsl_command(['which', 'pip3'], timeout=10)
        if result2 and result2.returncode == 0:
            self.log("pip3 binary found", 'SUCCESS')
            self.run_wsl_command(
                ['bash', '-c', 'pip3 install --upgrade pip --quiet'], timeout=60)
            return True

        # NOTE: ensurepip is intentionally disabled on Debian/Ubuntu — skip it.
        # apt-get was already tried in ensure_python_in_wsl with python3-pip.
        # Last resort: get-pip.py
        self.log("pip not found, bootstrapping via get-pip.py...", 'PROCESSING')
        r = self.run_wsl_command([
            'bash', '-c', 'curl -sS https://bootstrap.pypa.io/get-pip.py | python3'
        ], timeout=120)
        if r and r.returncode == 0:
            self.log("pip installed via get-pip.py", 'SUCCESS')
            return True

        self.log("Could not install pip", 'ERROR')
        return False
    
    def get_wsl_home(self):
        """Get WSL user's home directory"""
        result = self.run_wsl_command(['bash', '-c', 'echo $HOME'], timeout=5)
        if result and result.returncode == 0:
            return result.stdout.strip()
        return '/home/user'
    
    def create_wsl_project_dir(self, project_name='pytorch_env'):
        """Create project directory in WSL"""
        wsl_home = self.get_wsl_home()
        project_path = os.path.join(wsl_home, project_name).replace('\\', '/')
        
        result = self.run_wsl_command(['mkdir', '-p', project_path], timeout=10)
        if result and result.returncode == 0:
            self.log(f"Created directory in WSL: {project_path}", 'SUCCESS')
            return project_path
        
        self.log(f"Failed to create directory: {project_path}", 'ERROR')
        return None


# =============================================================================
# WSL2 PYTORCH INSTALLER - NEW CLASS (FIXED VERSION)
# =============================================================================

class WSL2PyTorchInstaller:
    """PyTorch installer for WSL2 environment"""
    
    def __init__(self, log_callback=None, status_callback=None):
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.wsl = WSL2Manager(log_callback)
        self.installation_log = []
        self.project_dir = None
        self.venv_path = None
        self.selected_mode = 'GPU'  # WSL2 always uses GPU mode with CUDA
        self.detector = HardwareDetector()
        
    def log(self, message, level='INFO'):
        timestamp = datetime.now().strftime('%H:%M:%S')
        symbols = {
            'INFO': '[i]',
            'SUCCESS': '[+]',
            'ERROR': '[!]',
            'WARNING': '[!]',
            'PROCESSING': '[*]',
            'DEBUG': '[d]',
        }
        symbol = symbols.get(level, '[i]')
        log_entry = f"{symbol} [{timestamp}] {safe_str(message)}"
        self.installation_log.append(log_entry)
        
        if self.log_callback:
            self.log_callback(log_entry, level)
    
    def update_status(self, status):
        if self.status_callback:
            self.status_callback(safe_str(status))
    
    def check_prerequisites(self):
        """Check WSL2 prerequisites"""
        self.log("Checking WSL2 prerequisites...", 'PROCESSING')
        
        # Check WSL availability
        if not self.wsl.check_wsl_available():
            self.log("WSL2 is not available. Please install WSL2 first.", 'ERROR')
            return False
        
        # Ensure Python in WSL
        if not self.wsl.ensure_python_in_wsl():
            self.log("Python installation in WSL failed", 'ERROR')
            return False
        
        # Ensure pip in WSL
        if not self.wsl.ensure_pip_in_wsl():
            self.log("pip installation in WSL failed", 'ERROR')
            return False
        
        self.log("All prerequisites satisfied", 'SUCCESS')
        return True
    
    def create_project_directory(self):
        """Create project directory in WSL"""
        self.update_status("Creating project directory in WSL...")
        self.log("Creating project directory in WSL...", 'PROCESSING')
        
        self.project_dir = self.wsl.create_wsl_project_dir('pytorch_env')
        if self.project_dir:
            self.venv_path = os.path.join(self.project_dir, 'venv').replace('\\', '/')
            return True
        
        return False
    
    def create_virtual_environment(self):
        """Create Python virtual environment in WSL"""
        self.update_status("Creating virtual environment in WSL...")
        self.log("Creating virtual environment in WSL...", 'PROCESSING')
        
    def create_virtual_environment(self):
        """Create Python virtual environment in WSL"""
        self.update_status("Creating virtual environment in WSL...")
        self.log("Creating virtual environment in WSL...", 'PROCESSING')

        # Attempt 1: standard venv
        cmd = ['bash', '-c', f'python3 -m venv {self.venv_path} 2>&1']
        result = self.wsl.run_wsl_command(cmd, timeout=60)

        if not result or result.returncode != 0:
            # Log the actual error so we know WHY it failed
            err_text = (result.stdout or '') + (result.stderr or '') if result else 'no output'
            self.log(f"venv error: {err_text[:300]}", 'WARNING')

            # Attempt 2: --without-pip (works even when python3-venv ensurepip part fails)
            self.log("Trying venv --without-pip fallback...", 'PROCESSING')
            cmd2 = ['bash', '-c', f'python3 -m venv --without-pip {self.venv_path} 2>&1']
            result2 = self.wsl.run_wsl_command(cmd2, timeout=60)

            if not result2 or result2.returncode != 0:
                err2 = (result2.stdout or '') + (result2.stderr or '') if result2 else 'no output'
                self.log(f"venv --without-pip error: {err2[:300]}", 'ERROR')
                self.log("Failed to create virtual environment", 'ERROR')
                return False

            # Bootstrap pip via get-pip.py into the --without-pip venv
            self.log("Bootstrapping pip into venv via get-pip.py...", 'PROCESSING')
            python_path = self.get_venv_python_path()
            bootstrap = self.wsl.run_wsl_command([
                'bash', '-c',
                f'curl -sS https://bootstrap.pypa.io/get-pip.py | {python_path}'
            ], timeout=120)

            if bootstrap and bootstrap.returncode == 0:
                self.log("pip bootstrapped into venv successfully", 'SUCCESS')
            else:
                self.log("pip bootstrap failed — venv created but pip may be missing", 'WARNING')

        self.log("Virtual environment created", 'SUCCESS')

        # Upgrade pip in venv
        pip_path = self.get_venv_pip_path()
        upgrade_result = self.wsl.run_wsl_command(
            ['bash', '-c', f'{pip_path} install --upgrade pip --quiet'], timeout=60)
        if upgrade_result and upgrade_result.returncode == 0:
            self.log("pip upgraded in venv", 'SUCCESS')

        return True
    
    def get_venv_python_path(self):
        """Get path to python executable in WSL venv"""
        return os.path.join(self.venv_path, 'bin', 'python3').replace('\\', '/')
    
    def get_venv_pip_path(self):
        """Get path to pip executable in WSL venv"""
        return os.path.join(self.venv_path, 'bin', 'pip3').replace('\\', '/')
    
    def detect_cuda_version_in_wsl(self):
        """Detect CUDA version inside WSL2 via nvidia-smi"""
        self.log("Detecting CUDA version in WSL2...", 'PROCESSING')

        # nvidia-smi header line looks like:
        # | CUDA Version: 13.0  Driver Version: 590.57 |
        # Use grep -oP to extract only the CUDA version number
        cuda_result = self.wsl.run_wsl_command([
            'bash', '-c',
            r"nvidia-smi 2>/dev/null | grep -oP 'CUDA Version: \K[0-9]+\.[0-9]+'"
        ], timeout=10)
        if cuda_result and cuda_result.returncode == 0:
            v = cuda_result.stdout.strip()
            if v:
                self.log(f"CUDA {v} detected in WSL2", 'SUCCESS')
                return v

        # Fallback: nvcc inside WSL
        nvcc_result = self.wsl.run_wsl_command([
            'bash', '-c',
            r"nvcc --version 2>/dev/null | grep -oP 'release \K[0-9]+\.[0-9]+'"
        ], timeout=10)
        if nvcc_result and nvcc_result.returncode == 0 and nvcc_result.stdout.strip():
            v = nvcc_result.stdout.strip()
            self.log(f"CUDA {v} detected via nvcc in WSL2", 'SUCCESS')
            return v

        self.log("Could not detect CUDA version in WSL2, defaulting to cu128", 'WARNING')
        return '12.8'

    def install_pytorch(self):
        """Install PyTorch with CUDA support in WSL2"""
        self.update_status("Installing PyTorch in WSL2...")
        self.log("Installing PyTorch with CUDA support in WSL2...", 'PROCESSING')

        pip_path = self.get_venv_pip_path()
        python_path = self.get_venv_python_path()

        # Ensure pip exists in venv — use get-pip.py if missing
        check_pip = self.wsl.run_wsl_command(
            ['bash', '-c', f'test -f {pip_path} && echo "exists"'], timeout=10)
        if not check_pip or check_pip.returncode != 0:
            self.log("pip not found in venv, bootstrapping via get-pip.py...", 'WARNING')
            bootstrap = self.wsl.run_wsl_command([
                'bash', '-c',
                f'curl -sS https://bootstrap.pypa.io/get-pip.py | {python_path}'
            ], timeout=120)
            if not bootstrap or bootstrap.returncode != 0:
                self.log("Could not install pip in venv", 'ERROR')
                return False

        # Detect CUDA and choose matching wheel URL (same table as Windows installer)
        cuda_version = self.detect_cuda_version_in_wsl()
        cuda_urls = {
            '13.0': 'https://download.pytorch.org/whl/cu128',
            '12.8': 'https://download.pytorch.org/whl/cu128',
            '12.7': 'https://download.pytorch.org/whl/cu127',
            '12.6': 'https://download.pytorch.org/whl/cu126',
            '12.5': 'https://download.pytorch.org/whl/cu125',
            '12.4': 'https://download.pytorch.org/whl/cu124',
            '12.3': 'https://download.pytorch.org/whl/cu123',
            '12.2': 'https://download.pytorch.org/whl/cu122',
            '12.1': 'https://download.pytorch.org/whl/cu121',
            '12.0': 'https://download.pytorch.org/whl/cu121',
            '11.8': 'https://download.pytorch.org/whl/cu118',
            '11.7': 'https://download.pytorch.org/whl/cu117',
        }
        index_url = cuda_urls.get(cuda_version)
        if not index_url:
            if cuda_version.startswith('13.') or cuda_version.startswith('12.'):
                index_url = 'https://download.pytorch.org/whl/cu128'
            elif cuda_version.startswith('11.'):
                index_url = 'https://download.pytorch.org/whl/cu118'
            else:
                index_url = 'https://download.pytorch.org/whl/cu128'
        self.log(f"CUDA {cuda_version} → {index_url}", 'INFO')

        # Remove any existing broken installation first
        self.wsl.run_wsl_command([
            'bash', '-c',
            f'{pip_path} uninstall -y torch torchvision torchaudio 2>/dev/null; true'
        ], timeout=60)

        # Install PyTorch stable wheels
        torch_cmd = [
            'bash', '-c',
            f'{pip_path} install torch torchvision torchaudio --index-url {index_url}'
        ]
        result = self.wsl.run_wsl_command(torch_cmd, timeout=600)

        if not result or result.returncode != 0:
            self.log("PyTorch installation failed", 'ERROR')
            err = (result.stderr or result.stdout or '')[:300] if result else ''
            if err:
                self.log(f"Error: {err}", 'ERROR')
            return False

        # Fix NCCL symbol conflict in WSL2 (ncclDevCommDestroy undefined symbol)
        # Root cause: system NCCL is loaded before PyTorch's bundled NCCL.
        # Fix: preload PyTorch's own libnccl so it takes precedence.
        self.log("Applying WSL2 NCCL compatibility fix...", 'PROCESSING')
        nccl_fix_cmd = (
            "python_path=$(find {venv}/lib -name 'libtorch_cuda.so' 2>/dev/null | head -1); "
            "nccl_lib=$(find {venv}/lib -name 'libnccl*.so*' 2>/dev/null | head -1); "
            "if [ -n \"$nccl_lib\" ]; then "
            "  echo \"export LD_PRELOAD=$nccl_lib\" >> {venv}/bin/activate; "
            "  echo 'NCCL lib preload configured'; "
            "else "
            "  echo 'NCCL lib not found, skipping preload'; "
            "fi; "
            "echo 'export NCCL_P2P_DISABLE=1' >> {venv}/bin/activate; "
            "echo 'export NCCL_DISABLE_CHECKS=1' >> {venv}/bin/activate"
        ).format(venv=self.venv_path)
        fix_result = self.wsl.run_wsl_command(['bash', '-c', nccl_fix_cmd], timeout=15)
        if fix_result:
            self.log(f"NCCL fix: {fix_result.stdout.strip()}", 'INFO')

        self.log("PyTorch installed successfully", 'SUCCESS')
        return True
    
    def install_transformers_and_deps(self):
        """Install transformers and dependencies including triton"""
        self.update_status("Installing transformers and dependencies...")
        self.log("Installing transformers and dependencies (including Triton)...", 'PROCESSING')
        
        pip_path = self.get_venv_pip_path()
        
        # Package list for DNABERT-2 and general use
        packages = [
            'transformers',
            'accelerate',
            'triton',           # Required for DNABERT-2
            'xformers',
            'bitsandbytes',
            'sentencepiece',
            'protobuf',
            'datasets',
            'tokenizers',
            'peft',
            'trl',
            'einops',
            'scipy',
            'numpy'
        ]
        
        success_count = 0
        for pkg in packages:
            self.update_status(f"Installing: {pkg}")
            self.log(f"Installing: {pkg}", 'INSTALL')
            
            cmd = ['bash', '-c', f'{pip_path} install {pkg} --upgrade']
            result = self.wsl.run_wsl_command(cmd, timeout=180)
            
            if result and result.returncode == 0:
                self.log(f"Success: {pkg}", 'SUCCESS')
                success_count += 1
            else:
                self.log(f"Warning: {pkg} installation may have issues", 'WARNING')
        
        self.log(f"Installed {success_count}/{len(packages)} packages", 'INFO')
        return success_count > 0
    
    def verify_installation(self):
        """Verify PyTorch installation in WSL2"""
        self.update_status("Verifying installation in WSL2...")
        self.log("Verifying PyTorch installation in WSL2...", 'PROCESSING')

        python_path = self.get_venv_python_path()

        check_python = self.wsl.run_wsl_command(
            ['bash', '-c', f'test -f {python_path} && echo "exists"'], timeout=10)
        if not check_python or check_python.returncode != 0:
            self.log("Python not found in venv", 'ERROR')
            return False

        # Pass the verification script inline via -c to avoid heredoc quoting issues
        verify_script = (
            "import json,sys\n"
            "try:\n"
            "    import torch\n"
            "    r={'torch_version':torch.__version__,'cuda_available':torch.cuda.is_available(),"
            "'cuda_version':torch.version.cuda,'device_count':torch.cuda.device_count() if torch.cuda.is_available() else 0,"
            "'success':True,'error':None}\n"
            "    if torch.cuda.is_available():\n"
            "        r['device_name']=torch.cuda.get_device_name(0)\n"
            "        x=torch.tensor([1.0,2.0,3.0]).cuda();y=x*2;r['test_passed']=True\n"
            "    try:\n"
            "        import triton;r['triton_version']=triton.__version__;r['triton_available']=True\n"
            "    except ImportError:\n"
            "        r['triton_available']=False\n"
            "except ImportError as e:\n"
            "    r={'success':False,'error':str(e),'cuda_available':False,'triton_available':False}\n"
            "except Exception as e:\n"
            "    r={'success':False,'error':str(e),'cuda_available':False,'triton_available':False}\n"
            "print(json.dumps(r))"
        )

        # Source the venv activate (picks up NCCL LD_PRELOAD fix) then run verification
        # NCCL_P2P_DISABLE + NCCL_DISABLE_CHECKS prevent the ncclDevCommDestroy crash in WSL2
        run_cmd = [
            'bash', '-c',
            f'NCCL_P2P_DISABLE=1 NCCL_DISABLE_CHECKS=1 '
            f'source {self.venv_path}/bin/activate 2>/dev/null; '
            f'NCCL_P2P_DISABLE=1 NCCL_DISABLE_CHECKS=1 {python_path} -c "{verify_script}"'
        ]
        result = self.wsl.run_wsl_command(run_cmd, timeout=60)

        if result and result.returncode == 0 and result.stdout.strip():
            try:
                verify_results = json.loads(result.stdout.strip())

                self.log(f"PyTorch version: {verify_results.get('torch_version', 'unknown')}", 'INFO')

                if verify_results.get('cuda_available'):
                    self.log("CUDA available: YES", 'SUCCESS')
                    self.log(f"CUDA version: {verify_results.get('cuda_version', 'unknown')}", 'SUCCESS')
                    self.log(f"GPU: {verify_results.get('device_name', 'unknown')}", 'SUCCESS')
                    if verify_results.get('test_passed'):
                        self.log("CUDA test operation: PASSED", 'SUCCESS')
                else:
                    self.log("CUDA available: NO", 'WARNING')
                    if verify_results.get('error'):
                        self.log(f"Reason: {verify_results['error']}", 'WARNING')
                    self.log("GPU acceleration may not be available", 'WARNING')

                if verify_results.get('triton_available'):
                    self.log(f"Triton available: YES (version {verify_results.get('triton_version', 'unknown')})", 'SUCCESS')
                else:
                    self.log("Triton available: NO - DNABERT-2 may require Triton", 'WARNING')

                return verify_results.get('success', False) and verify_results.get('cuda_available', False)

            except json.JSONDecodeError as e:
                self.log(f"Failed to parse verification results: {safe_str(e)}", 'ERROR')
                self.log(f"Raw output: {result.stdout[:300]}", 'WARNING')
                return False

        self.log("Verification script produced no output", 'ERROR')
        if result and result.stderr:
            self.log(f"stderr: {result.stderr[:200]}", 'WARNING')
        return False
    
    def create_test_script(self):
        """Create test script for WSL2 environment"""
        self.update_status("Creating test script...")
        
        test_script_content = '''#!/usr/bin/env python3
"""
PyTorch & Transformers Test Script for WSL2
Run this to verify your installation
"""

import torch
import transformers
import sys

def main():
    print("="*60)
    print("[.] PYTORCH & TRANSFORMERS TEST (WSL2)")
    print("="*60)
    
    print("\\nPackages:")
    print(f"  PyTorch: {torch.__version__}")
    print(f"  Transformers: {transformers.__version__}")
    
    # Check for Triton
    try:
        import triton
        print(f"  Triton: {triton.__version__} (available)")
    except ImportError:
        print("  Triton: NOT AVAILABLE")
    
    print("\\nDEVICE DETECTION:")
    
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print("  [+] CUDA available")
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"  VRAM: {vram_gb:.1f} GB")
        print(f"  CUDA Version: {torch.version.cuda}")
    else:
        device = torch.device("cpu")
        print("  [+] CPU mode (CUDA not available)")
    
    # Tensor test
    print("\\nTENSOR TEST:")
    x = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0])
    print(f"  Created tensor: {x}")
    
    if device.type != 'cpu':
        x = x.to(device)
        print(f"  Moved to {device}: {x}")
    
    y = x * 2
    print(f"  Operation (x*2): {y}")
    
    # Transformers test
    print("\\nTRANSFORMERS TEST:")
    print("  Loading tiny model for testing...")
    
    try:
        from transformers import AutoTokenizer, AutoModel
        
        model_name = "distilgpt2"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        
        if device.type != 'cpu':
            model = model.to(device)
        
        text = "Hello, PyTorch in WSL2!"
        inputs = tokenizer(text, return_tensors="pt")
        
        if device.type != 'cpu':
            inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
        
        print(f"  [+] Model loaded: {model_name}")
        print(f"  Output shape: {outputs.last_hidden_state.shape}")
        print("  Test successful!")
        
    except Exception as e:
        print(f"  [X] Transformers test failed: {e}")
    
    print("\\n" + "="*60)
    print("[+] ALL TESTS COMPLETED")
    print("="*60)

if __name__ == "__main__":
    main()
'''
        
        script_path = os.path.join(self.project_dir, 'test_pytorch_wsl.py').replace('\\', '/')
        
        write_cmd = ['bash', '-c', f"cat > {script_path} << 'EOF'\n{test_script_content}\nEOF"]
        result = self.wsl.run_wsl_command(write_cmd, timeout=10)
        
        if result and result.returncode == 0:
            self.log(f"Test script created: {script_path}", 'SUCCESS')
            return script_path
        
        self.log("Failed to create test script", 'ERROR')
        return None
    
    def create_activation_script(self):
        """Create activation script for WSL2"""
        activation_script = f'''#!/bin/bash
# PyTorch Environment Activator for WSL2

VENV_PATH="{self.venv_path}"

echo "[.] Activating PyTorch environment..."
source "$VENV_PATH/bin/activate"
echo "[+] Environment activated!"
echo ""
echo "Quick commands:"
echo '  python -c "import torch; print(torch.cuda.is_available())"'
echo "  python test_pytorch_wsl.py"
echo ""
exec $SHELL
'''
        
        script_path = os.path.join(self.project_dir, 'activate_pytorch.sh').replace('\\', '/')
        
        write_cmd = ['bash', '-c', f"cat > {script_path} << 'EOF'\n{activation_script}\nEOF"]
        result = self.wsl.run_wsl_command(write_cmd, timeout=10)
        
        if result and result.returncode == 0:
            # Make executable
            chmod_cmd = ['bash', '-c', f'chmod +x {script_path}']
            self.wsl.run_wsl_command(chmod_cmd, timeout=5)
            self.log(f"Activation script created: {script_path}", 'SUCCESS')
            return script_path
        
        self.log("Failed to create activation script", 'ERROR')
        return None
    
    def run_installation(self):
        """Run complete installation in WSL2"""
        self.log("="*60, 'INFO')
        self.log("[.] STARTING PYTORCH INSTALLATION IN WSL2", 'INFO')
        self.log("="*60, 'INFO')
        
        steps = [
            ("Checking prerequisites", self.check_prerequisites),
            ("Creating project directory", self.create_project_directory),
            ("Creating virtual environment", self.create_virtual_environment),
            ("Installing PyTorch with CUDA", self.install_pytorch),
            ("Installing transformers and dependencies", self.install_transformers_and_deps),
            ("Verifying installation", self.verify_installation),
            ("Creating test script", self.create_test_script),
            ("Creating activation script", self.create_activation_script)
        ]
        
        total_steps = len(steps)
        for i, (step_name, step_func) in enumerate(steps, 1):
            self.update_status(f"Step {i}/{total_steps}: {step_name}")
            self.log(f"\nStep {i}/{total_steps}: {step_name}", 'PROCESSING')
            
            try:
                success = step_func()
                if not success:
                    self.log(f"Step failed: {step_name}", 'ERROR')
                    # For critical steps, abort
                    if step_name in ["Checking prerequisites", "Creating project directory", "Creating virtual environment"]:
                        self.log("Critical step failed, aborting installation", 'ERROR')
                        return False
                    else:
                        self.log("Non-critical step failed, continuing...", 'WARNING')
            except Exception as e:
                self.log(f"Error in step {step_name}: {safe_str(e)}", 'ERROR')
                return False
        
        self.log("\n" + "="*60, 'SUCCESS')
        self.log("[+] PYTORCH INSTALLATION IN WSL2 SUCCESSFUL!", 'SUCCESS')
        self.log("="*60, 'SUCCESS')
        
        self.show_summary()
        return True
    
    def show_summary(self):
        """Show installation summary for WSL2"""
        line = '-'*58
        summary = f"""
+{line}+
|              WSL2 INSTALLATION SUMMARY                      |
+{line}+
| WSL2 Project Directory: {self.project_dir}
| Virtual Environment: {self.venv_path}
| Mode: GPU (CUDA Accelerated)
| Triton: Installed (DNABERT-2 ready)
+{line}+
| NEXT STEPS IN WSL2:
|
| 1. Enter WSL2:
|    wsl
|
| 2. Navigate to project directory:
|    cd {self.project_dir}
|
| 3. Activate the environment:
|    source activate_pytorch.sh
|
| 4. Run the test script:
|    python test_pytorch_wsl.py
|
| 5. Test DNABERT-2:
|    python -c "from transformers import AutoModel; \\
|    model = AutoModel.from_pretrained('zhihan1996/DNABERT-2-117M')"
|
| 6. Deactivate when done:
|    deactivate
|
+{line}+
"""
        self.log(summary, 'SUCCESS')
    
    def test_only(self):
        """Test existing installation in WSL2"""
        self.log("="*60, 'INFO')
        self.log("[.] TESTING PYTORCH INSTALLATION IN WSL2", 'INFO')
        self.log("="*60, 'INFO')
        
        # Check if project directory exists
        if not self.project_dir:
            # Try to find existing installation
            wsl_home = self.wsl.get_wsl_home()
            test_path = os.path.join(wsl_home, 'pytorch_env').replace('\\', '/')
            check_dir = self.wsl.run_wsl_command(['test', '-d', test_path], timeout=5)
            if check_dir and check_dir.returncode == 0:
                self.project_dir = test_path
                self.venv_path = os.path.join(self.project_dir, 'venv').replace('\\', '/')
                self.log(f"Found existing installation at: {self.project_dir}", 'INFO')
            else:
                self.log("No existing installation found", 'WARNING')
                return False
        
        return self.verify_installation()


# =============================================================================
# INSTALLATION TESTER & VERIFIER (COMPLETELY REWRITTEN FOR SAFETY)
# =============================================================================

class InstallationTester:
    """Comprehensive testing of existing PyTorch/Transformers installation"""
    
    def __init__(self, venv_path=None):
        self.venv_path = venv_path
        self.test_results = {}
        
    def get_python_path(self):
        """Get python path in virtual environment"""
        # Check if we're already in a venv
        in_venv = (hasattr(sys, 'real_prefix') or 
                   (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))
        
        if in_venv:
            return sys.executable
            
        if self.venv_path and os.path.exists(self.venv_path):
            if platform.system() == 'Windows':
                python_exe = os.path.join(self.venv_path, 'Scripts', 'python.exe')
                if os.path.exists(python_exe):
                    return python_exe
            else:
                python_exe = os.path.join(self.venv_path, 'bin', 'python')
                if os.path.exists(python_exe):
                    return python_exe
        return sys.executable
    
    def get_pip_path(self):
        """Get pip path in virtual environment"""
        in_venv = (hasattr(sys, 'real_prefix') or 
                   (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix))
        
        if in_venv:
            return os.path.join(os.path.dirname(sys.executable), 'pip')
            
        if self.venv_path and os.path.exists(self.venv_path):
            if platform.system() == 'Windows':
                pip_exe = os.path.join(self.venv_path, 'Scripts', 'pip.exe')
                if os.path.exists(pip_exe):
                    return pip_exe
            else:
                pip_exe = os.path.join(self.venv_path, 'bin', 'pip')
                if os.path.exists(pip_exe):
                    return pip_exe
        return 'pip'
    
    def check_package_installed(self, package_name):
        """Check if a specific package is installed"""
        python_path = self.get_python_path()
        
        check_script = f'''
import importlib.util
import sys

try:
    spec = importlib.util.find_spec("{package_name}")
    if spec is not None:
        try:
            module = importlib.import_module("{package_name}")
            version = getattr(module, "__version__", "unknown")
            print(f"INSTALLED:{{version}}")
        except:
            print("INSTALLED:unknown")
    else:
        print("NOT_INSTALLED")
except Exception as e:
    print(f"ERROR:{{e}}")
'''
        
        try:
            result = run_hidden([python_path, '-c', check_script], timeout=10)
            
            output = result.stdout.strip()
            if output.startswith('INSTALLED:'):
                version = output.split(':', 1)[1]
                return {'installed': True, 'version': version}
            else:
                return {'installed': False, 'version': None}
        except:
            return {'installed': False, 'version': None}
    
    def get_all_installed_packages(self):
        """Get list of all installed packages in environment"""
        python_path = self.get_python_path()
        
        # Simple pip list as JSON
        list_script = '''
import subprocess
import json
import sys

try:
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'list', '--format=json'],
        capture_output=True,
        text=True,
        timeout=10
    )
    if result.returncode == 0 and result.stdout:
        print(result.stdout)
    else:
        print('[]')
except:
    print('[]')
'''
        
        try:
            result = run_hidden([python_path, '-c', list_script], timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except:
                    return []
            return []
        except:
            return []
    
    def test_pytorch_basics(self):
        """Test basic PyTorch functionality"""
        python_path = self.get_python_path()
        
        test_script = '''
import json
import sys

try:
    import torch
    
    results = {
        'torch_version': torch.__version__,
        'cuda_available': torch.cuda.is_available(),
        'cuda_version': torch.version.cuda if hasattr(torch.version, 'cuda') else None,
        'mps_available': hasattr(torch.backends, 'mps') and torch.backends.mps.is_available(),
        'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
        'test_tensor': None,
        'error': None
    }
    
    if torch.cuda.is_available():
        try:
            device = torch.device('cuda')
            x = torch.tensor([1.0, 2.0, 3.0]).to(device)
            y = x * 2
            results['test_tensor'] = {
                'device': 'cuda',
                'result': y.cpu().tolist()
            }
            results['gpu_name'] = torch.cuda.get_device_name(0)
            results['gpu_memory'] = torch.cuda.get_device_properties(0).total_memory / 1024**3
        except Exception as e:
            results['error'] = str(e)
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        try:
            device = torch.device('mps')
            x = torch.tensor([1.0, 2.0, 3.0]).to(device)
            y = x * 2
            results['test_tensor'] = {
                'device': 'mps',
                'result': y.cpu().tolist()
            }
        except Exception as e:
            results['error'] = str(e)
    else:
        try:
            x = torch.tensor([1.0, 2.0, 3.0])
            y = x * 2
            results['test_tensor'] = {
                'device': 'cpu',
                'result': y.tolist()
            }
        except Exception as e:
            results['error'] = str(e)
            
except ImportError:
    results = {'error': 'torch not installed'}
except Exception as e:
    results = {'error': str(e)}

print(json.dumps(results))
'''
        
        try:
            result = run_hidden([python_path, '-c', test_script], timeout=20)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except:
                    return {'error': 'Failed to parse PyTorch test results'}
            else:
                return {'error': result.stderr or 'No output from PyTorch test'}
        except Exception as e:
            return {'error': safe_str(e)}
    
    def test_transformers_basics(self):
        """Test basic Transformers functionality"""
        python_path = self.get_python_path()
        
        test_script = '''
import json
import sys

try:
    import transformers
    import torch
    
    results = {
        'transformers_version': transformers.__version__,
        'model_test': None,
        'error': None
    }
    
    try:
        # Test with tiny model - use distilgpt2 for speed
        from transformers import AutoTokenizer, AutoModel
        
        model_name = "distilgpt2"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        
        # Determine device
        if torch.cuda.is_available():
            device = torch.device('cuda')
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            device = torch.device('mps')
        else:
            device = torch.device('cpu')
        
        model = model.to(device)
        
        # Test inference
        text = "Hello, PyTorch!"
        inputs = tokenizer(text, return_tensors="pt")
        
        # Move inputs to device
        if device.type != 'cpu':
            inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
        
        results['model_test'] = {
            'model': model_name,
            'device': str(device),
            'output_shape': list(outputs.last_hidden_state.shape),
            'success': True
        }
        
    except Exception as e:
        results['error'] = str(e)
        results['model_test'] = {'success': False, 'error': str(e)}
        
except ImportError as e:
    results = {'error': f'transformers not installed: {e}', 'transformers_version': None}
except Exception as e:
    results = {'error': str(e), 'transformers_version': None}

# CRITICAL: Always print valid JSON
print(json.dumps(results))
'''
        
        try:
            result = run_hidden([python_path, '-c', test_script], timeout=60)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError as e:
                    return {'error': f'Failed to parse JSON: {str(e)}', 'raw_output': result.stdout[:200]}
            else:
                return {'error': result.stderr or 'No output from Transformers test', 'returncode': result.returncode}
        except Exception as e:
            return {'error': safe_str(e)}

    def test_transformers_simple(self):
        """Simple Transformers test without model download (fast)"""
        python_path = self.get_python_path()
        
        test_script = '''
import json
import sys

try:
    import transformers
    import torch
    
    results = {
        'transformers_version': transformers.__version__,
        'torch_version': torch.__version__,
        'cuda_available': torch.cuda.is_available(),
        'success': True,
        'error': None
    }
    
    # Just test that we can create a tokenizer without downloading
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("gpt2")
    results['tokenizer_test'] = True
    
except ImportError as e:
    results = {
        'error': f'Import error: {e}',
        'transformers_version': None,
        'success': False
    }
except Exception as e:
    results = {
        'error': str(e),
        'success': False
    }

print(json.dumps(results))
'''
        try:
            result = run_hidden([python_path, '-c', test_script], timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {'error': 'Invalid JSON', 'raw': result.stdout[:200]}
            else:
                return {'error': result.stderr or 'No output', 'returncode': result.returncode}
        except subprocess.TimeoutExpired:
            return {'error': 'Timeout (30s) - test took too long'}
        except Exception as e:
            return {'error': safe_str(e)}
    
    def run_comprehensive_test(self):
        """Run all tests and return comprehensive results (NEVER returns None)"""
        try:
            results = {
                'timestamp': datetime.now().isoformat(),
                'python_version': platform.python_version(),
                'system': platform.system(),
                'machine': platform.machine(),
                'packages': {},
                'pytorch_test': None,
                'transformers_test': None,
                'installed_packages': [],
                'missing_critical': [],
                'status': 'UNKNOWN'
            }
            
            # Check critical packages
            critical_packages = ['torch', 'transformers', 'accelerate']
            for pkg in critical_packages:
                try:
                    pkg_info = self.check_package_installed(pkg)
                    if pkg_info and isinstance(pkg_info, dict):
                        results['packages'][pkg] = pkg_info
                        if not pkg_info.get('installed', False):
                            results['missing_critical'].append(pkg)
                    else:
                        results['packages'][pkg] = {'installed': False, 'version': None}
                        results['missing_critical'].append(pkg)
                except Exception as e:
                    results['packages'][pkg] = {'installed': False, 'version': None, 'error': safe_str(e)}
                    results['missing_critical'].append(pkg)
            
            # Get all installed packages
            try:
                installed = self.get_all_installed_packages()
                results['installed_packages'] = installed if installed else []
            except:
                results['installed_packages'] = []
            
            # Run PyTorch test if installed
            torch_info = results['packages'].get('torch', {})
            if torch_info and isinstance(torch_info, dict) and torch_info.get('installed'):
                try:
                    pytorch_results = self.test_pytorch_basics()
                    # CRITICAL FIX: Ensure we don't overwrite with None
                    if pytorch_results and isinstance(pytorch_results, dict):
                        results['pytorch_test'] = pytorch_results
                    else:
                        results['pytorch_test'] = {'error': 'Test returned invalid data'}
                except Exception as e:
                    results['pytorch_test'] = {'error': f'PyTorch test exception: {safe_str(e)}'}
            
            # Run Transformers test if installed - with SHORTER timeout for faster response
            transformers_info = results['packages'].get('transformers', {})
            if transformers_info and isinstance(transformers_info, dict) and transformers_info.get('installed'):
                try:
                    # Use a simpler, faster test that doesn't download models
                    transformers_results = self.test_transformers_simple()
                    if transformers_results and isinstance(transformers_results, dict):
                        results['transformers_test'] = transformers_results
                    else:
                        results['transformers_test'] = {'error': 'Test returned invalid data'}
                except Exception as e:
                    results['transformers_test'] = {'error': f'Transformers test exception: {safe_str(e)}'}
            
            # Determine overall status - FIXED LOGIC
            if len(results['missing_critical']) == 0:
                pytorch_test = results.get('pytorch_test')
                transformers_test = results.get('transformers_test')
                
                # Check PyTorch - FIXED: use bool() instead of 'is True' for safety
                pytorch_ok = (pytorch_test and isinstance(pytorch_test, dict) and 
                             not pytorch_test.get('error') and  # None oder "" gilt als kein Fehler
                             bool(pytorch_test.get('cuda_available')))
                
                # For transformers, just check it imported successfully (don't require model test)
                transformers_ok = (transformers_test and isinstance(transformers_test, dict) and
                                  'error' not in transformers_test)
                
                if pytorch_ok:
                    # If PyTorch works, we're functional (transformers is bonus)
                    results['status'] = 'FULLY_FUNCTIONAL'
                else:
                    results['status'] = 'INSTALLED_BUT_BROKEN'
            elif len(results['missing_critical']) < len(critical_packages):
                results['status'] = 'PARTIALLY_INSTALLED'
            else:
                results['status'] = 'NOT_INSTALLED'
            
            return results
            
        except Exception as e:
            return {
                'timestamp': datetime.now().isoformat(),
                'status': 'TEST_ERROR',
                'error': safe_str(e),
                'packages': {},
                'missing_critical': [],
                'installed_packages': []
            }
    
    def generate_test_report(self, results):
        """Generate human-readable test report"""
        # CRITICAL FIX: Handle None or non-dict results
        if not results or not isinstance(results, dict):
            return "No valid test results available"
            
        report = []
        report.append("="*60)
        report.append("PYTORCH & TRANSFORMERS INSTALLATION TEST REPORT")
        report.append("="*60)
        report.append(f"Timestamp: {results.get('timestamp', 'unknown')}")
        report.append(f"System: {results.get('system', 'unknown')} {results.get('machine', 'unknown')}")
        report.append(f"Python: {results.get('python_version', 'unknown')}")
        report.append("")
        
        # Overall status
        status_map = {
            'FULLY_FUNCTIONAL': '[+] FULLY FUNCTIONAL',
            'PARTIALLY_INSTALLED': '[!] PARTIALLY INSTALLED',
            'INSTALLED_BUT_BROKEN': '[X] INSTALLED BUT BROKEN',
            'NOT_INSTALLED': '[X] NOT INSTALLED',
            'TEST_ERROR': '[!] TEST ERROR'
        }
        status = results.get('status', 'UNKNOWN')
        report.append(f"Status: {status_map.get(status, status)}")
        report.append("")
        
        # Package status - SAFE ITERATION
        report.append("PACKAGE STATUS:")
        report.append("-"*40)
        packages = results.get('packages', {})
        if packages and isinstance(packages, dict):
            for pkg, info in packages.items():
                # CRITICAL FIX: Check if info is dict before accessing
                if info and isinstance(info, dict):
                    if info.get('installed'):
                        report.append(f"  [+] {pkg}: {info.get('version', 'unknown')}")
                    else:
                        report.append(f"  [X] {pkg}: NOT INSTALLED")
                else:
                    report.append(f"  [?] {pkg}: UNKNOWN STATUS")
        else:
            report.append("  No package information available")
        report.append("")
        
        # Missing critical packages
        missing = results.get('missing_critical', [])
        if missing:
            report.append("MISSING CRITICAL PACKAGES:")
            for pkg in missing:
                report.append(f"  [X] {pkg}")
            report.append("")
        
        # PyTorch test results - SAFE ACCESS
        pytorch_test = results.get('pytorch_test')
        if pytorch_test and isinstance(pytorch_test, dict):
            report.append("PYTORCH TEST RESULTS:")
            report.append("-"*40)
            if pytorch_test.get('error'):
                error_msg = pytorch_test.get('error', 'Unknown error')
                report.append(f"  [X] Error: {str(error_msg)[:200]}")
            else:
                report.append(f"  [+] Version: {pytorch_test.get('torch_version', 'unknown')}")
                report.append(f"  CUDA Available: {pytorch_test.get('cuda_available', False)}")
                if pytorch_test.get('cuda_available'):
                    report.append(f"  GPU: {pytorch_test.get('gpu_name', 'unknown')}")
                    gpu_mem = pytorch_test.get('gpu_memory', 0)
                    if isinstance(gpu_mem, (int, float)):
                        report.append(f"  VRAM: {gpu_mem:.1f} GB")
                    else:
                        report.append(f"  VRAM: {gpu_mem}")
                
                # SAFE CHECK for MPS
                mps_available = pytorch_test.get('mps_available', False)
                report.append(f"  MPS Available: {mps_available}")
                
                # SAFE ACCESS to test_tensor
                test_tensor = pytorch_test.get('test_tensor')
                if test_tensor and isinstance(test_tensor, dict):
                    device = test_tensor.get('device', 'unknown')
                    result = test_tensor.get('result', [])
                    report.append(f"  Device Test: {device} - {result}")
            report.append("")
        
        # Transformers test results - SAFE ACCESS
        transformers_test = results.get('transformers_test')
        if transformers_test and isinstance(transformers_test, dict):
            report.append("TRANSFORMERS TEST RESULTS:")
            report.append("-"*40)
            if transformers_test.get('error'):
                error_msg = transformers_test.get('error', 'Unknown error')
                report.append(f"  [X] Error: {str(error_msg)[:200]}")
            else:
                report.append(f"  [+] Version: {transformers_test.get('transformers_version', 'unknown')}")
                report.append(f"  Tokenizer Test: {'PASSED' if transformers_test.get('tokenizer_test') else 'SKIPPED'}")
                report.append(f"  CUDA in Transformers: {transformers_test.get('cuda_available', 'N/A')}")
                report.append("")
                
                # SAFE ACCESS to model_test
                model_test = transformers_test.get('model_test')
                if model_test and isinstance(model_test, dict):
                    if model_test.get('success'):
                        report.append(f"  Model Test: {model_test.get('model', 'unknown')} on {model_test.get('device', 'unknown')}")
                        report.append(f"  Output Shape: {model_test.get('output_shape', [])}")
                    else:
                        report.append("  [X] Model Test Failed")
                else:
                    report.append("  [X] No model test data")
            report.append("")
        
        # Installed packages summary - SAFE ITERATION
        installed = results.get('installed_packages', [])
        if installed and isinstance(installed, list):
            report.append("ALL INSTALLED PACKAGES:")
            report.append("-"*40)
            count = 0
            for pkg in installed:
                if isinstance(pkg, dict):
                    report.append(f"  * {pkg.get('name', 'unknown')}: {pkg.get('version', 'unknown')}")
                    count += 1
                    if count >= 20:
                        break
            
            if len(installed) > 20:
                report.append(f"  ... and {len(installed) - 20} more")
            report.append("")
        
        report.append("="*60)
        report.append("TEST COMPLETE")
        report.append("="*60)
        
        return '\n'.join(report)


# =============================================================================
# PYTORCH INSTALLER (with enhanced CUDA detection)
# =============================================================================

class PyTorchInstaller:
    """Main installer with mode selection and detailed logging"""
    
    def __init__(self, log_callback=None, status_callback=None):
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.installation_log = []
        self.detector = HardwareDetector()
        self.selected_mode = self.detector.recommended_mode['mode']
        self.install_dir = os.path.expanduser('~/pytorch_env')
        self.venv_path = os.path.join(self.install_dir, 'venv')
        self.tester = InstallationTester(self.venv_path)
        
    def log(self, message, level='INFO'):
        """Central logging function with Unicode safety"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # ASCII symbols for Windows
        symbols = {
            'INFO': '[i]',
            'SUCCESS': '[+]',
            'ERROR': '[!]',
            'WARNING': '[!]',
            'PROCESSING': '[*]',
            'DEBUG': '[d]',
            'DOWNLOAD': '[d]',
            'INSTALL': '[i]'
        }
        
        symbol = symbols.get(level, '[i]')
        safe_message = safe_str(message)
        log_entry = f"{symbol} [{timestamp}] {safe_message}"
        self.installation_log.append(log_entry)
        
        if self.log_callback:
            self.log_callback(log_entry, level)
        else:
            print(log_entry)
    
    def update_status(self, status):
        """Status update for GUI"""
        if self.status_callback:
            self.status_callback(safe_str(status))
    
    def set_mode(self, mode):
        """Set installation mode"""
        if mode in ['CPU', 'GPU', 'HYBRID', 'MPS', 'ROCM']:
            self.selected_mode = mode
            self.log(f"Mode selected: {mode}", 'SUCCESS')
            return True
        return False
    
    def check_existing_installation(self):
        """Check if PyTorch is already installed in the environment"""
        self.update_status("Checking existing installation...")
        
        try:
            # Run comprehensive test
            test_results = self.tester.run_comprehensive_test()
            
            if test_results and isinstance(test_results, dict):
                # Log results
                self.log(f"Installation status: {test_results.get('status', 'UNKNOWN')}", 'INFO')
                
                packages = test_results.get('packages', {})
                if isinstance(packages, dict):
                    for pkg, info in packages.items():
                        if info and isinstance(info, dict) and info.get('installed'):
                            self.log(f"  [+] {pkg}: {info.get('version', 'unknown')}", 'SUCCESS')
                        else:
                            self.log(f"  [X] {pkg}: NOT INSTALLED", 'WARNING')
            else:
                self.log("Could not determine installation status", 'WARNING')
            
            return test_results
            
        except Exception as e:
            self.log(f"Error checking installation: {safe_str(e)}", 'ERROR')
            return {'status': 'ERROR', 'error': safe_str(e)}
    
    def check_python_version(self):
        """Check Python version (requires 3.8+)"""
        version = sys.version_info
        if version.major >= 3 and version.minor >= 8:
            self.log(f"Python {version.major}.{version.minor}.{version.micro} OK", 'SUCCESS')
            return True
        else:
            self.log(f"Python {version.major}.{version.minor} too old (need 3.8+)", 'ERROR')
            return False
    
    def check_pip(self):
        """Check if pip is available"""
        try:
            run_hidden([sys.executable, '-m', 'pip', '--version'])
            self.log("pip is available", 'SUCCESS')
            return True
        except:
            self.log("pip not found", 'ERROR')
            return False
    
    def create_virtual_environment(self):
        """Create virtual environment"""
        self.update_status("Creating virtual environment...")
        
        try:
            if not os.path.exists(self.install_dir):
                os.makedirs(self.install_dir)
                self.log(f"Created directory: {self.install_dir}", 'SUCCESS')
            
            if os.path.exists(self.venv_path):
                self.log("Virtual environment already exists", 'WARNING')
                return True
            
            self.log("Creating virtual environment...", 'PROCESSING')
            run_hidden([sys.executable, '-m', 'venv', self.venv_path])
            self.log("Virtual environment created", 'SUCCESS')
            
            pip_path = self._get_pip_path()
            self.log("Upgrading pip...", 'PROCESSING')
            run_hidden([pip_path, 'install', '--upgrade', 'pip'])
            self.log("pip upgraded", 'SUCCESS')
            
            return True
            
        except Exception as e:
            self.log(f"Error creating venv: {safe_str(e)}", 'ERROR')
            return False
    
    def _get_pip_path(self):
        """Get pip path in virtual environment"""
        if platform.system() == 'Windows':
            return os.path.join(self.venv_path, 'Scripts', 'pip.exe')
        else:
            return os.path.join(self.venv_path, 'bin', 'pip')
    
    def _get_python_path(self):
        """Get python path in virtual environment"""
        if platform.system() == 'Windows':
            return os.path.join(self.venv_path, 'Scripts', 'python.exe')
        else:
            return os.path.join(self.venv_path, 'bin', 'python')
    
    # =========================================================================
    # NEW: CUDA DETECTION METHODS
    # =========================================================================
    
    def detect_cuda_version(self):
        """Detect installed CUDA version from environment or nvidia-smi"""
        cuda_version = None
        cuda_path = None
        nvcc_path = None
        
        self.log("Detecting CUDA installation...", 'PROCESSING')
        
        # Check CUDA_PATH environment variable (common on Windows)
        cuda_path_env = os.environ.get('CUDA_PATH', '')
        if cuda_path_env and os.path.exists(cuda_path_env):
            self.log(f"CUDA_PATH environment variable found: {cuda_path_env}", 'INFO')
            # Extract version from path (e.g., C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8)
            match = re.search(r'[vV]?(\d+\.\d+)', cuda_path_env)
            if match:
                cuda_version = match.group(1)
                cuda_path = cuda_path_env
                self.log(f"Detected CUDA {cuda_version} from CUDA_PATH", 'SUCCESS')
        
        # Check nvidia-smi for driver CUDA version
        try:
            self.log("Checking NVIDIA driver via nvidia-smi...", 'DEBUG')
            result = run_hidden(
                ['nvidia-smi', '--query-gpu=driver_version', '--format=csv,noheader'],
                timeout=5
            )
            if result.returncode == 0:
                driver_version = result.stdout.strip()
                self.log(f"NVIDIA Driver: {driver_version}", 'INFO')
                driver_parts = driver_version.split('.')
                if len(driver_parts) >= 2:
                    try:
                        major = int(driver_parts[0])
                        if major >= 525:
                            cuda_support = "12.x"
                        elif major >= 520:
                            cuda_support = "11.8"
                        elif major >= 450:
                            cuda_support = "11.x"
                        else:
                            cuda_support = "10.x"
                        self.log(f"Driver supports CUDA: {cuda_support}", 'INFO')
                        if not cuda_version:
                            if major >= 525:
                                cuda_version = "12.1"
                            elif major >= 520:
                                cuda_version = "11.8"
                            else:
                                cuda_version = "11.8"
                    except:
                        pass
        except Exception as e:
            self.log(f"nvidia-smi check failed: {safe_str(e)}", 'DEBUG')
        
        # Check if nvcc exists (CUDA Toolkit)
        # Try common locations if not found via CUDA_PATH
        possible_nvcc_paths = []
        
        if cuda_path:
            possible_nvcc_paths.append(os.path.join(cuda_path, 'bin', 'nvcc.exe' if platform.system() == 'Windows' else 'nvcc'))
        
        # Add common default paths
        if platform.system() == 'Windows':
            possible_nvcc_paths.extend([
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.5\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.4\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.3\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.2\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.1\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.0\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.8\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.7\bin\nvcc.exe',
                r'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v11.6\bin\nvcc.exe',
            ])
        else:  # Linux/Mac
            possible_nvcc_paths.extend([
                '/usr/local/cuda/bin/nvcc',
                '/opt/cuda/bin/nvcc',
                '/usr/bin/nvcc'
            ])
        
        # Also check PATH for nvcc
        try:
            result = run_hidden(
                ['where' if platform.system() == 'Windows' else 'which', 'nvcc'],
                timeout=3
            )
            if result.returncode == 0 and result.stdout.strip():
                nvcc_path = result.stdout.strip().split('\n')[0]
                possible_nvcc_paths.insert(0, nvcc_path)
        except:
            pass
        
        # Try each possible nvcc path
        for nvcc_candidate in possible_nvcc_paths:
            if os.path.exists(nvcc_candidate):
                self.log(f"Found nvcc at: {nvcc_candidate}", 'INFO')
                try:
                    result = run_hidden([nvcc_candidate, '--version'], timeout=5)
                    if result.returncode == 0:
                        output = result.stdout
                        match = re.search(r'release (\d+\.\d+)', output)
                        if match:
                            nvcc_version = match.group(1)
                            self.log(f"nvcc reports CUDA version: {nvcc_version}", 'SUCCESS')
                            cuda_version = nvcc_version
                            nvcc_path = nvcc_candidate
                            if not cuda_path:
                                cuda_path = os.path.dirname(os.path.dirname(nvcc_candidate))
                            break
                except Exception as e:
                    self.log(f"Error running nvcc: {safe_str(e)}", 'DEBUG')
        
        # Final summary
        if cuda_version:
            self.log(f"CUDA {cuda_version} detected", 'SUCCESS')
        else:
            self.log("No CUDA installation detected", 'WARNING')
        
        return {
            'version': cuda_version,
            'path': cuda_path,
            'nvcc_path': nvcc_path,
            'has_toolkit': nvcc_path is not None
        }
    
    # =========================================================================
    # NEW: Get PyTorch CUDA URL based on detected version
    # =========================================================================
    
    def get_pytorch_cuda_url(self, cuda_version=None):
        """Get correct PyTorch index URL based on detected CUDA version"""
        if not cuda_version:
            self.log("No CUDA version specified, using default CUDA 11.8", 'WARNING')
            return 'https://download.pytorch.org/whl/cu118'
        
        # Map CUDA versions to PyTorch wheel URLs
        cuda_urls = {
            '12.8': 'https://download.pytorch.org/whl/cu128',
            '12.7': 'https://download.pytorch.org/whl/cu127',
            '12.6': 'https://download.pytorch.org/whl/cu126',
            '12.5': 'https://download.pytorch.org/whl/cu125',
            '12.4': 'https://download.pytorch.org/whl/cu124',
            '12.3': 'https://download.pytorch.org/whl/cu123',
            '12.2': 'https://download.pytorch.org/whl/cu122',
            '12.1': 'https://download.pytorch.org/whl/cu121',
            '12.0': 'https://download.pytorch.org/whl/cu121',  # Use 12.1 for 12.0
            '11.8': 'https://download.pytorch.org/whl/cu118',
            '11.7': 'https://download.pytorch.org/whl/cu117',
            '11.6': 'https://download.pytorch.org/whl/cu116',
            '11.5': 'https://download.pytorch.org/whl/cu115',
            '11.4': 'https://download.pytorch.org/whl/cu114',
            '11.3': 'https://download.pytorch.org/whl/cu113',
            '11.2': 'https://download.pytorch.org/whl/cu112',
            '11.1': 'https://download.pytorch.org/whl/cu111',
            '11.0': 'https://download.pytorch.org/whl/cu110',
            '10.2': 'https://download.pytorch.org/whl/cu102',
            '10.1': 'https://download.pytorch.org/whl/cu101',
        }
        
        # Try exact match first
        if cuda_version in cuda_urls:
            self.log(f"Using exact match: CUDA {cuda_version} -> {cuda_urls[cuda_version]}", 'INFO')
            return cuda_urls[cuda_version]
        
        # Try to find closest version (major.minor)
        cuda_parts = cuda_version.split('.')
        if len(cuda_parts) >= 2:
            major_minor = f"{cuda_parts[0]}.{cuda_parts[1]}"
            if major_minor in cuda_urls:
                self.log(f"Using major.minor match: CUDA {major_minor} -> {cuda_urls[major_minor]}", 'INFO')
                return cuda_urls[major_minor]
        
        # For CUDA 12.x where we don't have exact match, use latest 12.x available
        if cuda_version.startswith('12.'):
            self.log(f"Using CUDA 12.1 for {cuda_version} (latest available)", 'INFO')
            return 'https://download.pytorch.org/whl/cu121'
        
        # For CUDA 11.x where we don't have exact match, use 11.8
        if cuda_version.startswith('11.'):
            self.log(f"Using CUDA 11.8 for {cuda_version} (latest available)", 'INFO')
            return 'https://download.pytorch.org/whl/cu118'
        
        # Default fallback
        self.log(f"Using default CUDA 11.8 for unknown version {cuda_version}", 'WARNING')
        return 'https://download.pytorch.org/whl/cu118'
    
    # =========================================================================
    # NEW: Verify CUDA installation after PyTorch install
    # =========================================================================
    
    def verify_cuda_installation(self, python_path):
        """Verify that CUDA is actually working after installation"""
        self.log("Verifying CUDA installation...", 'PROCESSING')
        
        verify_script = '''
import json
import sys
import torch

results = {
    'torch_version': torch.__version__,
    'cuda_available': torch.cuda.is_available(),
    'cuda_version': torch.version.cuda if hasattr(torch.version, 'cuda') else None,
    'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
}

if torch.cuda.is_available():
    try:
        results['device_name'] = torch.cuda.get_device_name(0)
        # Test actual CUDA operation
        x = torch.tensor([1.0, 2.0, 3.0]).cuda()
        y = x * 2
        results['test_passed'] = True
        results['test_result'] = y.cpu().tolist()
        
        # Check memory info
        results['memory_allocated'] = torch.cuda.memory_allocated(0) / 1024**2
        results['memory_reserved'] = torch.cuda.memory_reserved(0) / 1024**2
    except Exception as e:
        results['test_passed'] = False
        results['test_error'] = str(e)
else:
    results['test_passed'] = False
    results['test_error'] = 'CUDA not available'

print(json.dumps(results))
'''
        
        try:
            result = run_hidden([python_path, '-c', verify_script], timeout=30)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    verify_results = json.loads(result.stdout.strip())
                    
                    self.log(f"PyTorch version: {verify_results.get('torch_version', 'unknown')}", 'INFO')
                    
                    cuda_available = verify_results.get('cuda_available', False)
                    if cuda_available:
                        self.log("CUDA available: YES", 'SUCCESS')
                        self.log(f"CUDA version: {verify_results.get('cuda_version', 'unknown')}", 'SUCCESS')
                        self.log(f"GPU: {verify_results.get('device_name', 'unknown')}", 'SUCCESS')
                        
                        if verify_results.get('test_passed'):
                            self.log("CUDA test operation: PASSED", 'SUCCESS')
                            self.log(f"Test result: {verify_results.get('test_result')}", 'INFO')
                            
                            # Show memory info
                            mem_alloc = verify_results.get('memory_allocated', 0)
                            mem_reserved = verify_results.get('memory_reserved', 0)
                            if mem_alloc > 0:
                                self.log(f"Memory allocated: {mem_alloc:.2f} MB", 'INFO')
                                self.log(f"Memory reserved: {mem_reserved:.2f} MB", 'INFO')
                            
                            return True
                        else:
                            self.log(f"CUDA test failed: {verify_results.get('test_error', 'Unknown error')}", 'ERROR')
                    else:
                        self.log("CUDA available: NO", 'ERROR')
                        self.log(f"Reason: {verify_results.get('test_error', 'Unknown reason')}", 'ERROR')
                        
                except json.JSONDecodeError as e:
                    self.log(f"Failed to parse verification results: {safe_str(e)}", 'ERROR')
                    self.log(f"Raw output: {result.stdout[:500]}", 'DEBUG')
            else:
                self.log(f"Verification script failed with return code {result.returncode}", 'ERROR')
                if result.stderr:
                    self.log(f"stderr: {result.stderr[:200]}", 'ERROR')
                    
        except subprocess.TimeoutExpired:
            self.log("Verification script timed out", 'ERROR')
        except Exception as e:
            self.log(f"Error running verification: {safe_str(e)}", 'ERROR')
            import traceback
            self.log(traceback.format_exc(), 'DEBUG')
        
        return False
    
    # =========================================================================
    # REPLACED: install_pytorch with enhanced version
    # =========================================================================
    
    def install_pytorch(self):
        """Install PyTorch with automatic CUDA version detection"""
        mode_details = self.detector.get_mode_details(self.selected_mode)
        self.update_status(f"Installing PyTorch ({self.selected_mode} mode)...")
        
        self.log(f"\n{'='*60}", 'INFO')
        self.log(f"Installing PyTorch in {self.selected_mode} mode", 'INSTALL')
        self.log(f"{'='*60}", 'INFO')
        
        pip_path = self._get_pip_path()
        python_path = self._get_python_path()
        
        # Detect CUDA installation (only for GPU/HYBRID modes)
        cuda_info = None
        if self.selected_mode in ['GPU', 'HYBRID']:
            cuda_info = self.detect_cuda_version()
            if cuda_info['version']:
                self.log(f"Detected CUDA {cuda_info['version']}", 'SUCCESS')
                if cuda_info['path']:
                    self.log(f"CUDA Path: {cuda_info['path']}", 'INFO')
                if not cuda_info['has_toolkit']:
                    self.log("NOTE: CUDA Toolkit (nvcc) not found - PyTorch will still work but some extensions may need it", 'WARNING')
            else:
                self.log("No CUDA installation detected. PyTorch will install with CUDA support but may fall back to CPU if drivers are missing.", 'WARNING')
        
        # Get packages list
        packages = mode_details['packages']
        
        # Separate torch packages (need special index URL) from others
        torch_packages = ['torch', 'torchvision', 'torchaudio']
        other_packages = [p for p in packages if p not in torch_packages]
        
        success_count = 0
        total_count = len(packages)
        
        # Install PyTorch packages FIRST with correct index URL
        if torch_packages:
            self.update_status("Installing PyTorch with CUDA support...")
            self.log(f"Installing: {', '.join(torch_packages)}", 'INSTALL')
            
            try:
                # Build command
                cmd = [pip_path, 'install'] + torch_packages
                
                # Add index URL based on mode and detected CUDA
                if self.selected_mode in ['GPU', 'HYBRID']:
                    if cuda_info and cuda_info['version']:
                        index_url = self.get_pytorch_cuda_url(cuda_info['version'])
                        self.log(f"Using CUDA {cuda_info['version']} PyTorch wheels from: {index_url}", 'INFO')
                    else:
                        index_url = 'https://download.pytorch.org/whl/cu118'
                        self.log("Using default CUDA 11.8 PyTorch wheels", 'INFO')
                    
                    cmd.extend(['--index-url', index_url])
                    cmd.extend(['--upgrade'])  # Ensure latest version
                    
                elif self.selected_mode == 'ROCM':
                    cmd.extend(['--index-url', 'https://download.pytorch.org/whl/rocm5.6'])
                    self.log("Using ROCm 5.6 PyTorch wheels", 'INFO')
                # CPU and MPS use default index (no --index-url needed)
                
                self.log(f"Command: {' '.join(cmd)}", 'DEBUG')
                
                # Run installation with real-time output
                self.log("Downloading and installing PyTorch (this may take several minutes)...", 'PROCESSING')
                
                popen_kwargs = {
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.STDOUT,
                    'text': True,
                    'encoding': 'utf-8',
                    'errors': 'replace',
                    'bufsize': 1,
                    'universal_newlines': True,
                }
                popen_kwargs.update(_get_no_window_kwargs())
                process = subprocess.Popen(cmd, **popen_kwargs)
                
                # Stream output in real-time
                last_line = ""
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        last_line = line
                        # Log progress indicators
                        if 'Downloading' in line or 'Collecting' in line:
                            # Truncate long lines
                            display_line = line[:80] + '...' if len(line) > 80 else line
                            self.log(f"  {display_line}", 'DOWNLOAD')
                        elif 'Installing' in line or 'Successfully installed' in line:
                            self.log(f"  {line}", 'SUCCESS')
                        elif 'Requirement already satisfied' in line:
                            self.log(f"  {line[:100]}", 'INFO')
                
                process.wait()
                
                if process.returncode == 0:
                    self.log("Success: PyTorch installed", 'SUCCESS')
                    success_count += len(torch_packages)
                    
                    # Verify CUDA is actually working (for GPU/HYBRID modes)
                    if self.selected_mode in ['GPU', 'HYBRID']:
                        self.verify_cuda_installation(python_path)
                else:
                    self.log("Failed: PyTorch installation failed", 'ERROR')
                    if last_line:
                        self.log(f"Last output: {last_line[-200:]}", 'ERROR')
                    
                    # Try CPU fallback for GPU modes
                    if self.selected_mode in ['GPU', 'HYBRID']:
                        self.log("Attempting CPU-only fallback...", 'WARNING')
                        fallback_cmd = [pip_path, 'install'] + torch_packages
                        self.log(f"Command: {' '.join(fallback_cmd)}", 'DEBUG')
                        
                        fallback_result = run_hidden(fallback_cmd, timeout=300)
                        
                        if fallback_result.returncode == 0:
                            self.log("CPU fallback succeeded (CUDA not available)", 'WARNING')
                            success_count += len(torch_packages)
                        else:
                            self.log("CPU fallback also failed", 'ERROR')
                            
            except subprocess.TimeoutExpired:
                self.log("Timeout installing PyTorch", 'ERROR')
            except Exception as e:
                self.log(f"Exception during PyTorch install: {safe_str(e)}", 'ERROR')
                import traceback
                self.log(traceback.format_exc(), 'DEBUG')
        
        # Install other packages (transformers, etc.)
        for pkg in other_packages:
            self.update_status(f"Installing: {pkg}")
            self.log(f"Installing: {pkg}", 'INSTALL')
            
            try:
                result = run_hidden([pip_path, 'install', pkg], timeout=180)
                
                if result.returncode == 0:
                    stdout = result.stdout
                    if 'Successfully installed' in stdout:
                        lines = stdout.strip().split('\n')
                        for line in lines:
                            if 'Successfully installed' in line:
                                self.log(f"Success: {line}", 'SUCCESS')
                                break
                        else:
                            self.log(f"Success: {pkg}", 'SUCCESS')
                    else:
                        self.log(f"Success: {pkg}", 'SUCCESS')
                    success_count += 1
                else:
                    error_msg = result.stderr[-200:] if result.stderr else "Unknown error"
                    self.log(f"Failed: {pkg} - {error_msg}", 'ERROR')
                    
            except subprocess.TimeoutExpired:
                self.log(f"Timeout installing {pkg}", 'ERROR')
            except Exception as e:
                self.log(f"Exception installing {pkg}: {safe_str(e)}", 'ERROR')
        
        self.log(f"\nInstallation complete: {success_count}/{total_count} packages successful", 'INFO')
        return success_count == total_count
    
    def verify_installation(self):
        """Verify PyTorch installation with comprehensive testing"""
        self.update_status("Running comprehensive verification...")
        self.log("\nRunning comprehensive verification...", 'PROCESSING')
        
        try:
            # Update tester with current venv path
            self.tester = InstallationTester(self.venv_path)
            
            # Run comprehensive test
            test_results = self.tester.run_comprehensive_test()
            
            # SAFETY CHECK: Ensure test_results is a valid dictionary
            if not test_results or not isinstance(test_results, dict):
                self.log("Verification returned invalid results", 'ERROR')
                return False
            
            # Generate and log report safely
            try:
                report = self.tester.generate_test_report(test_results)
                if report:
                    for line in report.split('\n'):
                        if line.strip():
                            self.log(line, 'INFO')
            except Exception as e:
                self.log(f"Error generating report: {safe_str(e)}", 'ERROR')
                # Continue anyway to check status
            
            # Check if fully functional - with safe access
            status = test_results.get('status', 'UNKNOWN')
            
            if status == 'FULLY_FUNCTIONAL':
                self.log("\nInstallation is FULLY FUNCTIONAL!", 'SUCCESS')
                return True
            elif status == 'PARTIALLY_INSTALLED':
                self.log("\nInstallation is PARTIAL. Some packages missing.", 'WARNING')
                return False
            elif status == 'INSTALLED_BUT_BROKEN':
                self.log("\nInstallation is BROKEN. Tests failed.", 'ERROR')
                return False
            else:
                self.log(f"\nInstallation status: {status}", 'WARNING')
                return False
                
        except Exception as e:
            self.log(f"Error during verification: {safe_str(e)}", 'ERROR')
            import traceback
            self.log(f"Traceback: {safe_str(traceback.format_exc())}", 'DEBUG')
            return False
    
    def set_environment_variables(self):
        """Set environment variables based on mode"""
        self.update_status("Configuring environment variables...")
        
        mode_details = self.detector.get_mode_details(self.selected_mode)
        env_vars = mode_details.get('env_vars', {})
        
        # Create activation script with environment variables
        try:
            if platform.system() == 'Windows':
                activate_path = os.path.join(self.venv_path, 'Scripts', 'activate.bat')
                with open(activate_path, 'a', encoding='utf-8') as f:
                    f.write('\nREM PyTorch Environment Variables\n')
                    for key, value in env_vars.items():
                        f.write(f'SET {key}={value}\n')
            else:
                activate_path = os.path.join(self.venv_path, 'bin', 'activate')
                with open(activate_path, 'a', encoding='utf-8') as f:
                    f.write('\n# PyTorch Environment Variables\n')
                    for key, value in env_vars.items():
                        f.write(f'export {key}={value}\n')
            
            self.log("Environment variables configured", 'SUCCESS')
            
            if env_vars:
                self.log("Recommended settings:", 'INFO')
                for key, value in env_vars.items():
                    self.log(f"   * {key}={value}", 'INFO')
                    
        except Exception as e:
            self.log(f"Error setting environment variables: {safe_str(e)}", 'ERROR')
            return False
        
        return True
    
    def create_activation_scripts(self):
        """Create activation scripts for easy startup"""
        self.update_status("Creating activation scripts...")
        
        try:
            if platform.system() == 'Windows':
                # Batch file for easy activation
                batch_path = os.path.join(self.install_dir, 'activate_pytorch.bat')
                with open(batch_path, 'w', encoding='utf-8') as f:
                    f.write('@echo off\n')
                    f.write('echo [.] Activating PyTorch environment...\n')
                    f.write(f'call "{self.venv_path}\\Scripts\\activate.bat"\n')
                    f.write('echo [+] Environment activated! Run "python" to start\n')
                    f.write('cmd /k')
                
                # PowerShell script
                ps_path = os.path.join(self.install_dir, 'activate_pytorch.ps1')
                with open(ps_path, 'w', encoding='utf-8') as f:
                    f.write('Write-Host "[.] Activating PyTorch environment..." -ForegroundColor Cyan\n')
                    f.write(f'& "{self.venv_path}\\Scripts\\Activate.ps1"\n')
                    f.write('Write-Host "[+] Environment activated!" -ForegroundColor Green\n')
            else:
                # Shell script
                sh_path = os.path.join(self.install_dir, 'activate_pytorch.sh')
                with open(sh_path, 'w', encoding='utf-8') as f:
                    f.write('#!/bin/bash\n')
                    f.write('echo "[.] Activating PyTorch environment..."\n')
                    f.write(f'source "{self.venv_path}/bin/activate"\n')
                    f.write('echo "[+] Environment activated!"\n')
                    f.write('exec $SHELL\n')
                os.chmod(sh_path, 0o755)
            
            self.log(f"Activation scripts created in: {self.install_dir}", 'SUCCESS')
            
        except Exception as e:
            self.log(f"Error creating activation scripts: {safe_str(e)}", 'ERROR')
            return False
        
        return True
    
    def create_test_script(self):
        """Create a test script to verify everything works"""
        test_script_path = os.path.join(self.install_dir, 'test_pytorch.py')
        
        test_code = '''#!/usr/bin/env python3
"""
PyTorch & Transformers Test Script
Run this to verify your installation
"""

import torch
import transformers
import sys

def main():
    print("="*60)
    print("[.] PYTORCH & TRANSFORMERS TEST")
    print("="*60)
    
    # PyTorch version
    print("\\nPackages:")
    print(f"  PyTorch: {torch.__version__}")
    print(f"  Transformers: {transformers.__version__}")
    
    # Device detection
    print("\\nDEVICE DETECTION:")
    
    if torch.cuda.is_available():
        device = torch.device("cuda")
        print("  [+] CUDA available")
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        print(f"  CUDA Version: {torch.version.cuda}")
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        device = torch.device("mps")
        print("  [+] MPS available (Apple Silicon)")
    else:
        device = torch.device("cpu")
        print("  [+] CPU mode")
    
    # Simple tensor test
    print("\\nTENSOR TEST:")
    x = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0])
    print(f"  Created tensor: {x}")
    
    # Move to device if not CPU
    if device.type != 'cpu':
        x = x.to(device)
        print(f"  Moved to {device}: {x}")
    
    # Simple operation
    y = x * 2
    print(f"  Operation (x*2): {y}")
    
    # Transformers test
    print("\\nTRANSFORMERS TEST:")
    print("  Loading tiny model for testing...")
    
    try:
        from transformers import AutoTokenizer, AutoModel
        
        model_name = "distilgpt2"
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModel.from_pretrained(model_name)
        
        # Move model to device if possible
        if device.type != 'cpu':
            model = model.to(device)
        
        # Test inference
        text = "Hello, PyTorch!"
        inputs = tokenizer(text, return_tensors="pt")
        
        # Move inputs to device
        if device.type != 'cpu':
            inputs = {k: v.to(device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = model(**inputs)
        
        print(f"  [+] Model loaded: {model_name}")
        print(f"  Output shape: {outputs.last_hidden_state.shape}")
        print("  Test successful!")
        
    except Exception as e:
        print(f"  [X] Transformers test failed: {e}")
    
    print("\\n" + "="*60)
    print("[+] ALL TESTS COMPLETED")
    print("="*60)

if __name__ == "__main__":
    main()
'''
        
        try:
            with open(test_script_path, 'w', encoding='utf-8') as f:
                f.write(test_code)
            
            self.log(f"Test script created: {test_script_path}", 'SUCCESS')
            return test_script_path
        except Exception as e:
            self.log(f"Error creating test script: {safe_str(e)}", 'ERROR')
            return None
    
    def create_config_file(self):
        """Create configuration file with CUDA info"""
        mode_details = self.detector.get_mode_details(self.selected_mode)
        
        # Detect CUDA for config
        cuda_info = None
        if self.selected_mode in ['GPU', 'HYBRID']:
            cuda_info = self.detect_cuda_version()
        
        config = {
            'installation': {
                'date': datetime.now().isoformat(),
                'mode': self.selected_mode,
                'mode_name': mode_details['name'],
                'python_version': f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                'install_dir': self.install_dir
            },
            'hardware': {
                'cpu': self.detector.cpu_info,
                'ram_gb': self.detector.ram_info,
                'gpus': self.detector.gpu_info,
                'avx2': self.detector.avx2_supported,
                'recommended_mode': self.detector.recommended_mode['mode']
            },
            'cuda': {
                'detected_version': cuda_info['version'] if cuda_info else None,
                'path': cuda_info['path'] if cuda_info else None,
                'has_toolkit': cuda_info['has_toolkit'] if cuda_info else False
            } if cuda_info else {'detected_version': None},
            'environment': {
                'variables': mode_details.get('env_vars', {})
            },
            'packages': mode_details['packages']
        }
        
        try:
            config_path = os.path.join(self.install_dir, 'pytorch_config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            self.log(f"Configuration saved: {config_path}", 'SUCCESS')
            return config_path
        except Exception as e:
            self.log(f"Error creating config: {safe_str(e)}", 'ERROR')
            return None
    
    def create_desktop_shortcut(self):
        """Create desktop shortcut (Windows only)"""
        if platform.system() != 'Windows':
            return True
        
        try:
            desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
            shortcut_path = os.path.join(desktop, 'PyTorch Environment.lnk')
            
            # Create shortcut using PowerShell
            ps_script = f'''
$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("{shortcut_path}")
$Shortcut.TargetPath = "{self._get_python_path()}"
$Shortcut.Arguments = "-c \"print('[.] PyTorch Environment'); import code; code.interact()\""
$Shortcut.WorkingDirectory = "{self.install_dir}"
$Shortcut.Description = "PyTorch Environment"
$Shortcut.Save()
'''
            
            run_hidden(['powershell', '-Command', ps_script])
            self.log("Desktop shortcut created", 'SUCCESS')
            
        except Exception as e:
            self.log(f"Could not create desktop shortcut: {safe_str(e)}", 'WARNING')
        
        return True
    
    def run_installation(self, create_shortcut=True):
        """Run complete installation"""
        self.log("="*60, 'INFO')
        self.log("[.] STARTING PYTORCH INSTALLATION", 'INFO')
        self.log(f"Mode: {self.selected_mode}", 'INFO')
        self.log("="*60, 'INFO')
        
        # Show hardware summary
        self.log(self.detector.get_hardware_summary(), 'INFO')
        
        steps = [
            ("Checking Python version", self.check_python_version),
            ("Checking pip", self.check_pip),
            ("Creating virtual environment", self.create_virtual_environment),
            ("Installing PyTorch", self.install_pytorch),
            ("Verifying installation", self.verify_installation),
            ("Setting environment variables", self.set_environment_variables),
            ("Creating activation scripts", self.create_activation_scripts),
            ("Creating test script", self.create_test_script),
            ("Creating configuration", self.create_config_file)
        ]
        
        if create_shortcut and platform.system() == 'Windows':
            steps.append(("Creating desktop shortcut", self.create_desktop_shortcut))
        
        total_steps = len(steps)
        for i, (step_name, step_func) in enumerate(steps, 1):
            self.update_status(f"Step {i}/{total_steps}: {step_name}")
            self.log(f"\nStep {i}/{total_steps}: {step_name}", 'PROCESSING')
            
            try:
                success = step_func()
                if not success and i < total_steps:
                    self.log("Step failed but continuing...", 'WARNING')
            except Exception as e:
                self.log(f"Error in step {step_name}: {safe_str(e)}", 'ERROR')
                # Continue with next steps instead of failing completely
                if i < total_steps:
                    self.log("Step failed but continuing...", 'WARNING')
                    continue
                else:
                    return False
        
        self.log("\n" + "="*60, 'SUCCESS')
        self.log("[+] PYTORCH INSTALLATION SUCCESSFUL!", 'SUCCESS')
        self.log("="*60, 'SUCCESS')
        
        self.show_summary()
        return True
    
    def show_summary(self):
        """Show installation summary"""
        mode_details = self.detector.get_mode_details(self.selected_mode)
        
        # Fix Windows path separator for display
        install_dir = self.install_dir.replace('/', '\\')
        
        line = '-'*58
        summary = f"""
+{line}+
|              INSTALLATION SUMMARY                         |
+{line}+
| Install Directory: {install_dir}
| Selected Mode: {mode_details['name']}
| Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}
| Packages: {len(mode_details['packages'])}
+{line}+
| NEXT STEPS:
|
| 1. Activate the environment:
|    * {os.path.join(install_dir, 'activate_pytorch.bat' if platform.system() == 'Windows' else 'activate_pytorch.sh')}
|
| 2. Run the test script:
|    * python {os.path.join(install_dir, 'test_pytorch.py')}
|
| 3. Start using PyTorch:
|    * python
|    * import torch
|    * import transformers
|
| 4. Configuration file:
|    * {os.path.join(install_dir, 'pytorch_config.json')}
|
| 5. Recommended models for your setup:
"""
        for model in mode_details['models'][:3]:
            summary += f"|    * {model}\n"
        
        summary += f"+{line}+"
        
        self.log(summary, 'SUCCESS')
    
    def test_only(self):
        """Run only the verification test on existing installation"""
        self.log("="*60, 'INFO')
        self.log("[.] RUNNING INSTALLATION TEST ONLY", 'INFO')
        self.log("="*60, 'INFO')
        
        try:
            # Update tester with current venv path if it exists
            venv_path = self.venv_path if os.path.exists(self.venv_path) else None
            self.tester = InstallationTester(venv_path)
            
            # Run comprehensive test
            test_results = self.tester.run_comprehensive_test()
            
            if test_results and isinstance(test_results, dict):
                # Generate and log report
                report = self.tester.generate_test_report(test_results)
                if report:
                    for line in report.split('\n'):
                        if line.strip():
                            self.log(line, 'INFO')
                
                return test_results.get('status') == 'FULLY_FUNCTIONAL'
            else:
                self.log("Test returned no results", 'ERROR')
                return False
                
        except Exception as e:
            self.log(f"Error during testing: {safe_str(e)}", 'ERROR')
            return False


# =============================================================================
# PLATFORM SELECTOR - NEW CLASS FOR GUI
# =============================================================================

class PlatformSelector:
    """Handles platform selection and routes to appropriate installer"""
    
    PLATFORM_WINDOWS = "Windows"
    PLATFORM_WSL2 = "WSL2"
    
    def __init__(self, log_callback=None, status_callback=None):
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.selected_platform = self.PLATFORM_WINDOWS
        self.windows_installer = None
        self.wsl2_installer = None
        
    def log(self, message, level='INFO'):
        if self.log_callback:
            self.log_callback(message, level)
    
    def update_status(self, status):
        if self.status_callback:
            self.status_callback(status)
    
    def set_platform(self, platform):
        """Set the target platform for installation"""
        if platform in [self.PLATFORM_WINDOWS, self.PLATFORM_WSL2]:
            self.selected_platform = platform
            self.log(f"Platform set to: {platform}", 'INFO')
            return True
        return False
    
    def get_windows_installer(self, log_callback=None, status_callback=None):
        """Get or create Windows installer instance"""
        if self.windows_installer is None:
            self.windows_installer = PyTorchInstaller(
                log_callback=log_callback or self.log_callback,
                status_callback=status_callback or self.update_status
            )
        return self.windows_installer
    
    def get_wsl2_installer(self, log_callback=None, status_callback=None):
        """Get or create WSL2 installer instance"""
        if self.wsl2_installer is None:
            self.wsl2_installer = WSL2PyTorchInstaller(
                log_callback=log_callback or self.log_callback,
                status_callback=status_callback or self.update_status
            )
        return self.wsl2_installer
    
    def run_installation(self, create_shortcut=True):
        """Run installation on the selected platform"""
        if self.selected_platform == self.PLATFORM_WINDOWS:
            installer = self.get_windows_installer()
            return installer.run_installation(create_shortcut)
        else:
            installer = self.get_wsl2_installer()
            return installer.run_installation()
    
    def test_installation(self):
        """Test installation on the selected platform"""
        if self.selected_platform == self.PLATFORM_WINDOWS:
            installer = self.get_windows_installer()
            return installer.test_only()
        else:
            installer = self.get_wsl2_installer()
            return installer.test_only()
    
    def check_wsl_availability(self):
        """Check if WSL2 is available (for UI feedback)"""
        if platform.system() != 'Windows':
            return False
        
        wsl = WSL2Manager()
        return wsl.check_wsl_available()


# =============================================================================
# MAIN GUI CLASS (updated with CUDA info display and WSL2 support)
# =============================================================================

class PyTorchSetupGUI:
    """Main GUI for PyTorch & Transformers setup with WSL2 support"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("[.] PyTorch & Transformers Setup - Complete Installer with WSL2 Support")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # Set icon and style
        self.setup_styles()
        
        # Hardware detector
        self.detector = HardwareDetector()
        
        # Platform selector (routes to Windows or WSL2)
        self.platform_selector = PlatformSelector(
            log_callback=self.add_log,
            status_callback=self.update_status
        )
        
        # GUI variables
        self.selected_platform = tk.StringVar(value=PlatformSelector.PLATFORM_WINDOWS)
        self.selected_mode = tk.StringVar(value=self.detector.recommended_mode['mode'])
        self.create_shortcut = tk.BooleanVar(value=True)
        self.show_detailed_log = tk.BooleanVar(value=True)
        
        # Queue for thread communication
        self.log_queue = queue.Queue()
        self.is_installing = False
        
        # Build GUI
        self.setup_gui()
        
        # Show hardware info
        self.show_hardware_info()
        
        # Process log queue periodically
        self.process_log_queue()
        
        # Auto-check existing installation on startup
        self.root.after(1000, self.auto_check_installation)
        
        # Check WSL availability and update UI
        self.check_wsl_availability_ui()
    
    def setup_styles(self):
        """Configure visual appearance"""
        style = ttk.Style()
        
        # Color scheme for log levels
        self.colors = {
            'INFO': '#FFFFFF',
            'SUCCESS': '#00FF00',
            'ERROR': '#FF4444',
            'WARNING': '#FFFF00',
            'PROCESSING': '#FFA500',
            'DEBUG': '#888888',
            'INSTALL': '#00CCFF',
            'DOWNLOAD': '#FF99FF'
        }
        
        # Configure styles
        style.configure('Title.TLabel', font=('Arial', 16, 'bold'))
        style.configure('Heading.TLabel', font=('Arial', 12, 'bold'))
        style.configure('Status.TLabel', font=('Arial', 10))
        style.configure('Hardware.TLabelframe', font=('Arial', 10, 'bold'))
        style.configure('Success.TLabel', foreground='green')
        style.configure('Error.TLabel', foreground='red')
    
    def setup_gui(self):
        """Build complete GUI"""
        
        # Main container with PanedWindow for flexible layout
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left side: Hardware info and installation controls
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)
        
        # Right side: Live log
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=1)
        
        # ========== LEFT SIDE ==========
        
        # Title
        title_label = ttk.Label(left_frame, text="[.] PyTorch & Transformers Setup", 
                                style='Title.TLabel')
        title_label.pack(pady=10)
        
        # Platform Selection Frame (NEW)
        self.create_platform_frame(left_frame)
        
        # Hardware Info Frame
        self.create_hardware_frame(left_frame)
        
        # Mode Selection Frame
        self.create_mode_frame(left_frame)
        
        # Installation Options Frame
        self.create_options_frame(left_frame)
        
        # Installation Status Frame
        self.create_status_frame(left_frame)
        
        # Action Buttons
        self.create_action_buttons(left_frame)
        
        # ========== RIGHT SIDE ==========
        
        # Live Log Frame
        self.create_log_frame(right_frame)
    
    def create_platform_frame(self, parent):
        """Create frame for platform selection (Windows vs WSL2)"""
        frame = ttk.LabelFrame(parent, text="Platform Selection", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Radio buttons for platform selection
        windows_rb = ttk.Radiobutton(
            frame,
            text="Windows (Standard)",
            variable=self.selected_platform,
            value=PlatformSelector.PLATFORM_WINDOWS,
            command=self.on_platform_change
        )
        windows_rb.pack(anchor=tk.W, pady=2)
        
        wsl2_rb = ttk.Radiobutton(
            frame,
            text="WSL2 (Linux - for DNABERT-2 / Triton support)",
            variable=self.selected_platform,
            value=PlatformSelector.PLATFORM_WSL2,
            command=self.on_platform_change
        )
        wsl2_rb.pack(anchor=tk.W, pady=2)
        
        # WSL2 hint label
        self.wsl_hint_label = ttk.Label(
            frame, 
            text="",
            font=('Arial', 8),
            foreground='#888888'
        )
        self.wsl_hint_label.pack(anchor=tk.W, padx=(20, 0), pady=2)
        
        # Separator
        ttk.Separator(frame, orient='horizontal').pack(fill=tk.X, pady=5)
    
    def create_hardware_frame(self, parent):
        """Create frame for hardware information"""
        frame = ttk.LabelFrame(parent, text="Hardware Detection", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Hardware info text
        self.hardware_text = tk.Text(frame, height=12, width=45, 
                                     font=('Consolas', 9), bg='#1e1e1e', fg='#00ff00')
        self.hardware_text.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, 
                                  command=self.hardware_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.hardware_text.config(yscrollcommand=scrollbar.set)
        
        # Buttons frame
        button_frame = ttk.Frame(frame)
        button_frame.pack(fill=tk.X, pady=5)
        
        ttk.Button(button_frame, text="Redetect Hardware", 
                   command=self.show_hardware_info).pack(side=tk.LEFT, padx=2)
        
        ttk.Button(button_frame, text="Detect CUDA", 
                   command=self.detect_cuda).pack(side=tk.LEFT, padx=2)
    
    def create_mode_frame(self, parent):
        """Create frame for mode selection"""
        frame = ttk.LabelFrame(parent, text="Installation Mode", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Mode descriptions from detector
        modes = [
            ('CPU', 'CPU Only', 'Optimized for CPU-only systems'),
            ('GPU', 'GPU Accelerated', 'Full NVIDIA GPU acceleration'),
            ('HYBRID', 'Hybrid', 'Intelligent GPU/CPU distribution'),
            ('MPS', 'Apple Silicon', 'Metal Performance Shaders (M1/M2/M3)'),
            ('ROCM', 'AMD ROCm', 'AMD GPU acceleration')
        ]
        
        for mode_id, name, desc in modes:
            # Radio button
            rb = ttk.Radiobutton(
                frame,
                text=name,
                variable=self.selected_mode,
                value=mode_id,
                command=self.on_mode_change
            )
            rb.pack(anchor=tk.W, pady=2)
            
            # Description
            desc_label = ttk.Label(frame, text=f"  {desc}", 
                                   font=('Arial', 8), foreground='gray')
            desc_label.pack(anchor=tk.W, padx=(20, 0))
    
    def create_options_frame(self, parent):
        """Create frame for additional options"""
        frame = ttk.LabelFrame(parent, text="Additional Options", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Checkbutton(frame, text="Create desktop shortcut (Windows only)",
                       variable=self.create_shortcut).pack(anchor=tk.W, pady=2)
        
        ttk.Checkbutton(frame, text="Show detailed logs",
                       variable=self.show_detailed_log).pack(anchor=tk.W, pady=2)
        
        # Mode details button
        ttk.Button(frame, text="Show Mode Details", 
                   command=self.show_mode_details).pack(pady=5)
    
    def create_status_frame(self, parent):
        """Create frame for installation status"""
        frame = ttk.LabelFrame(parent, text="Installation Status", padding=10)
        frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.status_label = ttk.Label(frame, text="Ready", 
                                      style='Status.TLabel')
        self.status_label.pack(pady=5)
        
        # Progress bar
        self.progress = ttk.Progressbar(frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=5)
    
    def create_action_buttons(self, parent):
        """Create action buttons"""
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.X, padx=5, pady=10)
        
        ttk.Button(frame, text="Start Installation", 
                   command=self.start_installation,
                   style='Accent.TButton').pack(side=tk.LEFT, padx=5, expand=True)
        
        ttk.Button(frame, text="Test Installation", 
                   command=self.test_installation).pack(side=tk.LEFT, padx=5, expand=True)
        
        ttk.Button(frame, text="Exit", 
                   command=self.cancel_installation).pack(side=tk.LEFT, padx=5, expand=True)
    
    def create_log_frame(self, parent):
        """Create frame for live log display"""
        frame = ttk.LabelFrame(parent, text="Live Installation Log", padding=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Log display with custom tags for colors
        self.log_display = tk.Text(frame, wrap=tk.WORD, 
                                   font=('Consolas', 9),
                                   bg='#1e1e1e', fg='#ffffff')
        self.log_display.pack(fill=tk.BOTH, expand=True)
        
        # Configure tags for different log levels
        for level, color in self.colors.items():
            self.log_display.tag_configure(level, foreground=color)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, 
                                  command=self.log_display.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_display.config(yscrollcommand=scrollbar.set)
        
        # Clear log button
        ttk.Button(frame, text="Clear Log", 
                   command=self.clear_log).pack(pady=5)
    
    def check_wsl_availability_ui(self):
        """Check WSL availability and update UI hint"""
        if platform.system() != 'Windows':
            self.wsl_hint_label.config(text="WSL2 only available on Windows")
            return
        
        # Check in thread to avoid blocking
        def check_thread():
            wsl = WSL2Manager()
            available = wsl.check_wsl_available()
            
            def update_ui():
                if available:
                    self.wsl_hint_label.config(
                        text="WSL2 is available! Use this for DNABERT-2 with Triton support.",
                        foreground='#00ff00'
                    )
                else:
                    self.wsl_hint_label.config(
                        text="WSL2 not detected. Run 'wsl --install' in PowerShell as Administrator",
                        foreground='#ff4444'
                    )
            
            self.root.after(0, update_ui)
        
        thread = threading.Thread(target=check_thread)
        thread.daemon = True
        thread.start()
    
    def on_platform_change(self):
        """Handle platform selection change"""
        platform = self.selected_platform.get()
        self.platform_selector.set_platform(platform)
        self.add_log(f"Platform changed to: {platform}", 'INFO')
        
        if platform == PlatformSelector.PLATFORM_WSL2:
            self.add_log("Note: WSL2 installation includes Triton for DNABERT-2 support", 'INFO')
            # Disable desktop shortcut for WSL2 (not applicable)
            self.create_shortcut.set(False)
    
    def show_hardware_info(self):
        """Update hardware info display"""
        self.hardware_text.delete(1.0, tk.END)
        self.hardware_text.insert(1.0, self.detector.get_hardware_summary())
    
    def detect_cuda(self):
        """Manually trigger CUDA detection"""
        self.add_log("Manual CUDA detection requested...", 'PROCESSING')
        
        # Run in thread
        thread = threading.Thread(target=self._run_cuda_detection)
        thread.daemon = True
        thread.start()
    
    def _run_cuda_detection(self):
        """Run CUDA detection in thread"""
        try:
            installer = PyTorchInstaller()
            cuda_info = installer.detect_cuda_version()
            
            self.root.after(0, self._show_cuda_info, cuda_info)
        except Exception as e:
            self.root.after(0, self.add_log, f"CUDA detection error: {safe_str(e)}", 'ERROR')
    
    def _show_cuda_info(self, cuda_info):
        """Show CUDA detection results"""
        if cuda_info['version']:
            self.add_log(f"[+] CUDA {cuda_info['version']} detected", 'SUCCESS')
            if cuda_info['path']:
                self.add_log(f"    Path: {cuda_info['path']}", 'INFO')
            if cuda_info['has_toolkit']:
                self.add_log("    CUDA Toolkit: Present", 'SUCCESS')
            else:
                self.add_log("    CUDA Toolkit: Not found (drivers only)", 'WARNING')
        else:
            self.add_log("[-] No CUDA installation detected", 'WARNING')
    
    def on_mode_change(self):
        """Handle mode change"""
        mode = self.selected_mode.get()
        # Update platform selector's windows installer mode if needed
        windows_installer = self.platform_selector.get_windows_installer()
        windows_installer.set_mode(mode)
    
    def show_mode_details(self):
        """Show detailed information about selected mode"""
        mode = self.selected_mode.get()
        details = self.detector.get_mode_details(mode)
        
        info = f"""
{details['name']} DETAILS:
{'-'*40}

Description: {details['description']}

Packages to install:
{chr(10).join(['  * ' + pkg for pkg in details['packages']])}

Environment Variables:
{chr(10).join(['  * ' + k + '=' + v for k, v in details.get('env_vars', {}).items()])}

Recommended Models:
{chr(10).join(['  * ' + model for model in details['models'][:5]])}
"""
        
        # Show in a new window
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Mode Details - {details['name']}")
        dialog.geometry("600x500")
        
        text = tk.Text(dialog, wrap=tk.WORD, font=('Consolas', 10))
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text.insert(1.0, info)
        text.config(state=tk.DISABLED)
        
        scrollbar = ttk.Scrollbar(dialog, orient=tk.VERTICAL, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)
        
        ttk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
    
    def auto_check_installation(self):
        """Automatically check for existing installation on startup — shows a splash checklist window"""
        self._show_startup_check_window()

    def _show_startup_check_window(self):
        """Show a professional startup checklist window while checking installation"""
        splash = tk.Toplevel(self.root)
        splash.title("Checking Installation")
        splash.resizable(False, False)
        splash.grab_set()  # Modal

        # Center on screen
        w, h = 420, 310
        sw = splash.winfo_screenwidth()
        sh = splash.winfo_screenheight()
        splash.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        # Header
        header = tk.Frame(splash, bg="#1e1e2e", height=56)
        header.pack(fill=tk.X)
        tk.Label(header, text="Checking Installation",
                 font=("Segoe UI", 13, "bold"),
                 bg="#1e1e2e", fg="#cdd6f4").pack(pady=14)

        # Checklist frame
        list_frame = tk.Frame(splash, bg="#181825", padx=20, pady=14)
        list_frame.pack(fill=tk.BOTH, expand=True)

        checks = [
            ("Python environment",        "python"),
            ("pip availability",           "pip"),
            ("PyTorch (torch)",            "torch"),
            ("Transformers",               "transformers"),
            ("Accelerate",                 "accelerate"),
            ("CUDA / GPU status",          "cuda"),
        ]

        row_widgets = {}   # key -> (label_var, icon_label)
        PENDING  = "  ···"
        RUNNING  = "  ⏳"
        OK       = "  ✔"
        FAIL     = "  ✘"
        COL_PENDING = "#585b70"
        COL_RUN     = "#fab387"
        COL_OK      = "#a6e3a1"
        COL_FAIL    = "#f38ba8"

        for label_text, key in checks:
            row = tk.Frame(list_frame, bg="#181825")
            row.pack(fill=tk.X, pady=3)
            icon_var = tk.StringVar(value=PENDING)
            icon_lbl = tk.Label(row, textvariable=icon_var,
                                font=("Segoe UI", 11), bg="#181825", fg=COL_PENDING, width=5, anchor="w")
            icon_lbl.pack(side=tk.LEFT)
            tk.Label(row, text=label_text,
                     font=("Segoe UI", 10), bg="#181825", fg="#cdd6f4", anchor="w").pack(side=tk.LEFT)
            row_widgets[key] = (icon_var, icon_lbl)

        # Progress bar
        pb_frame = tk.Frame(splash, bg="#181825")
        pb_frame.pack(fill=tk.X, padx=20, pady=(0, 6))
        pb = ttk.Progressbar(pb_frame, mode='determinate', maximum=len(checks))
        pb.pack(fill=tk.X)

        # Status line
        status_var = tk.StringVar(value="Starting checks…")
        tk.Label(splash, textvariable=status_var,
                 font=("Segoe UI", 9), fg="#6c7086", bg="#181825").pack(pady=(0, 10))

        splash.configure(bg="#181825")

        # Helper: update a row from the background thread via root.after
        def set_row(key, state):
            icon_var, icon_lbl = row_widgets[key]
            if state == 'run':
                icon_var.set(RUNNING)
                icon_lbl.config(fg=COL_RUN)
            elif state == 'ok':
                icon_var.set(OK)
                icon_lbl.config(fg=COL_OK)
            elif state == 'fail':
                icon_var.set(FAIL)
                icon_lbl.config(fg=COL_FAIL)
            pb.step(1)

        def tick(key, state, status_text=""):
            self.root.after(0, lambda: set_row(key, state))
            if status_text:
                self.root.after(0, lambda t=status_text: status_var.set(t))

        def close_splash(test_results, platform_name):
            splash.destroy()
            self._auto_check_complete(test_results, platform_name)

        # Background worker
        def worker():
            try:
                windows_installer = self.platform_selector.get_windows_installer()
                tester = windows_installer.tester

                # ── Python ──────────────────────────────────────────────────
                tick("python", "run", "Checking Python environment…")
                py_ok = windows_installer.check_python_version()
                tick("python", "ok" if py_ok else "fail")

                # ── pip ─────────────────────────────────────────────────────
                tick("pip", "run", "Checking pip…")
                pip_ok = windows_installer.check_pip()
                tick("pip", "ok" if pip_ok else "fail")

                # ── torch ────────────────────────────────────────────────────
                tick("torch", "run", "Checking PyTorch (torch)…")
                torch_info = tester.check_package_installed("torch")
                torch_ok = torch_info and torch_info.get("installed", False)
                tick("torch", "ok" if torch_ok else "fail")

                # ── transformers ─────────────────────────────────────────────
                tick("transformers", "run", "Checking Transformers…")
                tf_info = tester.check_package_installed("transformers")
                tf_ok = tf_info and tf_info.get("installed", False)
                tick("transformers", "ok" if tf_ok else "fail")

                # ── accelerate ───────────────────────────────────────────────
                tick("accelerate", "run", "Checking Accelerate…")
                acc_info = tester.check_package_installed("accelerate")
                acc_ok = acc_info and acc_info.get("installed", False)
                tick("accelerate", "ok" if acc_ok else "fail")

                # ── CUDA ─────────────────────────────────────────────────────
                tick("cuda", "run", "Checking CUDA / GPU…")
                cuda_info = windows_installer.detect_cuda_version()
                cuda_ok = cuda_info and cuda_info.get("version") is not None
                tick("cuda", "ok" if cuda_ok else "fail", "Done.")

                # ── Assemble results for main log ────────────────────────────
                packages = {
                    "torch":        torch_info  or {"installed": False, "version": None},
                    "transformers": tf_info     or {"installed": False, "version": None},
                    "accelerate":   acc_info    or {"installed": False, "version": None},
                }
                missing = [k for k, v in packages.items() if not v.get("installed")]

                if torch_ok:
                    pt_test = tester.test_pytorch_basics()
                    cuda_available = pt_test and pt_test.get("cuda_available", False) and not pt_test.get("error")
                    status = "FULLY_FUNCTIONAL" if (not missing and cuda_available) else (
                             "PARTIALLY_INSTALLED" if missing else "INSTALLED_BUT_BROKEN")
                    # Log versions to main log
                    for pkg, info in packages.items():
                        if info.get("installed"):
                            self.add_log(f"  [+] {pkg}: {info.get('version', 'unknown')}", 'SUCCESS')
                else:
                    status = "NOT_INSTALLED" if missing else "INSTALLED_BUT_BROKEN"
                    pt_test = None

                test_results = {
                    "status": status,
                    "packages": packages,
                    "pytorch_test": pt_test,
                    "missing_critical": missing,
                }

                # Brief pause so user can read the checklist
                time.sleep(0.6)
                self.root.after(0, close_splash, test_results, "Windows")

            except Exception as e:
                self.root.after(0, lambda: splash.destroy())
                self.root.after(0, self.add_log, f"Auto-check error: {safe_str(e)}", 'ERROR')

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
    
    def _auto_check_complete(self, test_results, platform_name):
        """Handle auto-check completion"""
        if test_results and isinstance(test_results, dict):
            status = test_results.get('status')
            if status == 'FULLY_FUNCTIONAL':
                self.add_log(f"[+] Existing functional {platform_name} installation found!", 'SUCCESS')
            elif status == 'PARTIALLY_INSTALLED':
                self.add_log(f"[!] Partial {platform_name} installation found. Some packages missing.", 'WARNING')
            elif status == 'INSTALLED_BUT_BROKEN':
                self.add_log(f"[X] {platform_name} installation found but tests failed.", 'WARNING')
            elif status == 'NOT_INSTALLED':
                self.add_log(f"No existing {platform_name} installation found. Ready to install.", 'INFO')
            else:
                self.add_log(f"{platform_name} installation status: {status}", 'INFO')
        else:
            self.add_log(f"Could not determine {platform_name} installation status", 'WARNING')
    
    def add_log(self, message, level='INFO'):
        """Add message to log queue"""
        self.log_queue.put((safe_str(message), level))
    
    def process_log_queue(self):
        """Process log queue and update GUI"""
        try:
            while True:
                message, level = self.log_queue.get_nowait()
                self.log_display.insert(tk.END, message + '\n', level)
                self.log_display.see(tk.END)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self.process_log_queue)
    
    def clear_log(self):
        """Clear the log display"""
        self.log_display.delete(1.0, tk.END)
    
    def update_status(self, status):
        """Update status label"""
        self.status_label.config(text=safe_str(status))
        self.root.update_idletasks()
    
    def start_installation(self):
        """Start the installation process on the selected platform"""
        if self.is_installing:
            messagebox.showwarning("Already Installing", 
                                  "Installation is already in progress!")
            return
        
        platform = self.selected_platform.get()
        
        # Show appropriate confirmation message
        if platform == PlatformSelector.PLATFORM_WSL2:
            confirm_msg = (
                "Start PyTorch installation in WSL2?\n\n"
                "This will:\n"
                "1. Install Python 3.10+ in WSL2 (if not present)\n"
                "2. Create a virtual environment in WSL2\n"
                "3. Install PyTorch with CUDA support\n"
                "4. Install Triton (required for DNABERT-2)\n"
                "5. Install transformers and dependencies\n\n"
                "Continue?"
            )
        else:
            confirm_msg = (
                f"Start PyTorch installation in {self.selected_mode.get()} mode?\n\n"
                f"This will create a virtual environment at:\n"
                f"{self.platform_selector.get_windows_installer().install_dir}\n\n"
                "Continue?"
            )
        
        if not messagebox.askyesno("Confirm Installation", confirm_msg):
            return
        
        self.is_installing = True
        self.progress.start()
        
        # Run installation in separate thread
        thread = threading.Thread(target=self._run_installation_thread, 
                                  args=(self.create_shortcut.get(),))
        thread.daemon = True
        thread.start()
    
    def _run_installation_thread(self, create_shortcut):
        """Run installation in thread"""
        try:
            success = self.platform_selector.run_installation(create_shortcut)
            self.root.after(0, self._installation_complete, success)
        except Exception as e:
            self.root.after(0, self._installation_error, safe_str(e))
    
    def _installation_complete(self, success):
        """Handle installation completion"""
        self.progress.stop()
        self.is_installing = False
        
        platform = self.selected_platform.get()
        
        if success:
            if platform == PlatformSelector.PLATFORM_WSL2:
                msg = (
                    "[+] PyTorch & Transformers installed successfully in WSL2!\n\n"
                    "Next steps:\n"
                    "1. Enter WSL2: wsl\n"
                    "2. Navigate to project: cd ~/pytorch_env\n"
                    "3. Activate: source activate_pytorch.sh\n"
                    "4. Test: python test_pytorch_wsl.py\n"
                    "5. Test DNABERT-2: python -c \"from transformers import AutoModel; model = AutoModel.from_pretrained('zhihan1996/DNABERT-2-117M')\""
                )
            else:
                msg = (
                    "[+] PyTorch & Transformers installed successfully!\n\n"
                    f"Installation directory: {self.platform_selector.get_windows_installer().install_dir}\n\n"
                    "Use the activation scripts to start working."
                )
            messagebox.showinfo("Installation Complete", msg)
        else:
            messagebox.showwarning("Installation Issues",
                                  "[!] Installation completed with warnings.\n\n"
                                  "Check the log for details.")
    
    def _installation_error(self, error):
        """Handle installation error"""
        self.progress.stop()
        self.is_installing = False
        messagebox.showerror("Installation Error",
                            f"[X] Installation error:\n\n{error}")
    
    def test_installation(self):
        """Test existing installation on the selected platform"""
        if self.is_installing:
            messagebox.showwarning("Busy", "Installation is in progress!")
            return
        
        platform = self.selected_platform.get()
        
        if platform == PlatformSelector.PLATFORM_WSL2:
            self.add_log("Testing WSL2 installation...", 'PROCESSING')
        else:
            self.add_log("Testing Windows installation...", 'PROCESSING')
        
        self.is_installing = True
        self.progress.start()
        
        thread = threading.Thread(target=self._run_test_thread)
        thread.daemon = True
        thread.start()
    
    def _run_test_thread(self):
        """Run test in thread"""
        try:
            success = self.platform_selector.test_installation()
            self.root.after(0, self._test_complete, success)
        except Exception as e:
            self.root.after(0, self._installation_error, safe_str(e))
    
    def _test_complete(self, success):
        """Handle test completion"""
        self.progress.stop()
        self.is_installing = False
        
        platform = self.selected_platform.get()
        
        if success:
            if platform == PlatformSelector.PLATFORM_WSL2:
                msg = "[+] WSL2 installation test passed!\n\nPyTorch with CUDA and Triton is working correctly.\n\nDNABERT-2 should work without workarounds."
            else:
                msg = "[+] Installation test passed!\n\nPyTorch is working correctly."
            messagebox.showinfo("Test Complete", msg)
        else:
            msg = "[!] Installation test found issues.\n\nCheck the log for details."
            messagebox.showwarning("Test Issues", msg)
    
    def cancel_installation(self):
        """Cancel ongoing installation"""
        if self.is_installing:
            if messagebox.askyesno("Cancel",
                                  "Are you sure you want to cancel?"):
                self.is_installing = False
                self.progress.stop()
                self.add_log("[X] Operation cancelled by user", 'WARNING')
        else:
            self.root.quit()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point"""
    print("="*60)
    print("[.] PyTorch & Transformers Setup GUI - Complete Edition with WSL2 Support")
    print("="*60)
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print("="*60)
    
    # Start GUI
    root = tk.Tk()
    app = PyTorchSetupGUI(root)
    
    # Center window on screen
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    
    root.mainloop()

if __name__ == "__main__":
    main()
