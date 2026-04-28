import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import requests
import json
from pathlib import Path
from collections import Counter
import threading
from datetime import datetime
import time
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
from functools import lru_cache, wraps
import sqlite3
import logging
from typing import Optional, Callable, Dict, Any, List, Tuple, Generator
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import hashlib
import pandas as pd
from scipy import stats
from scipy.stats import mannwhitneyu, ttest_ind
import random
import sys
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# INTERNATIONALISATION (i18n)
# ============================================================

def _get_base_dir() -> Path:
    """Returns the base directory — works for both script and frozen binary."""
    if getattr(sys, 'frozen', False):
        # PyInstaller binary: files are in sys._MEIPASS
        return Path(sys._MEIPASS)
    return Path(__file__).parent

LANGUAGE_DIR = _get_base_dir() / "languages"
SETTINGS_FILE = _get_base_dir() / "languages" / "settings.json"

# Import i18n from the languages sub-package
import importlib.util as _ilu
_i18n_spec = _ilu.spec_from_file_location("i18n", LANGUAGE_DIR / "i18n.py")
_i18n_mod  = _ilu.module_from_spec(_i18n_spec)
_i18n_spec.loader.exec_module(_i18n_mod)
I18n              = _i18n_mod.I18n
AVAILABLE_LANGUAGES = _i18n_mod.AVAILABLE_LANGUAGES

def _load_saved_language() -> str:
    """Reads saved language from settings.json. Default: 'en'."""
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            return data.get("language", "en")
    except Exception:
        pass
    return "en"

def _save_settings(data: dict) -> None:
    """Persists settings dict to settings.json."""
    try:
        existing = {}
        if SETTINGS_FILE.exists():
            existing = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
        existing.update(data)
        SETTINGS_FILE.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8'
        )
    except Exception as e:
        logging.getLogger('DNARhythmAnalyzer').warning(f"Could not save settings: {e}")

# Global i18n instance — default English, override from settings.json
_i18n = I18n(LANGUAGE_DIR, default_language="en")
_i18n.set_language(_load_saved_language())

def t(key: str, **kwargs) -> str:
    """Shorthand translation function. Returns translated string for key."""
    return _i18n.get(key, **kwargs)

class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that automatically converts all NumPy types to native Python types."""
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

# ============================================================
# LOGGING SYSTEM
# ============================================================

class GUIHandler(logging.Handler):
    """Logging handler for GUI output."""
    def __init__(self, log_callback: Callable):
        super().__init__()
        self.log_callback = log_callback
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', '%H:%M:%S'))
    
    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self.log_callback(msg)
        except Exception:
            self.handleError(record)

def setup_logging(log_callback: Optional[Callable] = None) -> logging.Logger:
    """Sets up the logging system."""
    logger = logging.getLogger('DNARhythmAnalyzer')
    logger.setLevel(logging.INFO)
    
    # Entferne bestehende Handler
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # GUI Handler
    if log_callback:
        gui_handler = GUIHandler(log_callback)
        logger.addHandler(gui_handler)
    
    # Datei Handler
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(log_dir / f"analysis_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    return logger

# ============================================================
# CONFIGURATION AND SETTINGS
# ============================================================

@dataclass
class AnalysisConfig:
    """Central configuration for all analyses."""
    max_seq_length: int = 50000
    gc_window_size: int = 1000
    gc_step_size: int = 100
    golden_ratio_tolerance: float = 0.05
    fibonacci_tolerance: float = 0.1
    power_law_min_points: int = 10
    autocorr_max_lag: int = 1000
    cgr_max_points: int = 50000
    use_caching: bool = True
    max_parallel_workers: int = max(2, (__import__('os').cpu_count() or 4) // 2)
    # Adaptive worker count: half CPU cores (consider hyperthreading), min 2
    download_timeout: int = 120
    download_retries: int = 5
    significance_permutations: int = 1000
    significance_threshold: float = 0.05
    exploratory_threshold:  float = 0.10   # For exploratory analyses (p<0.1 acceptable)
    large_distance_threshold_percentile: float = 99.0  # Dynamic 2-THz threshold
    
    # Database paths
    workspace_dir: Path = Path(__file__).parent / "dna_analysis_cache"
    results_dir:   Path = Path(__file__).parent / "dna_analysis_results"
    logs_dir:      Path = Path(__file__).parent / "logs"
    plots_dir:     Path = Path(__file__).parent / "dna_analysis_plots"
    recon3d_dir:   Path = Path(__file__).parent / "dna_3d_reconstruction"
    recon2d_dir:   Path = Path(__file__).parent / "dna_2d_unwrapped"
    real3d_dir:    Path = Path(__file__).parent / "dna_3d_realistic"
    hbonds_dir:    Path = Path(__file__).parent / "dna_hbonds"
    histones_dir:  Path = Path(__file__).parent / "dna_histones"
    cache_db:      Path = Path(__file__).parent / "analysis_cache.db"
    delta_abstracts_dir: Path = Path(__file__).parent / "dna_delta_abstracts"

    def __post_init__(self):
        """Creates all required directories."""
        for dir_path in [self.workspace_dir, self.results_dir, self.logs_dir,
                         self.plots_dir, self.recon3d_dir,
                         self.recon2d_dir, self.real3d_dir,
                         self.hbonds_dir, self.histones_dir,
                         self.delta_abstracts_dir]:
            dir_path.mkdir(exist_ok=True)

# Global configuration — load persisted settings if available
CONFIG = AnalysisConfig()

def _apply_saved_settings_to_config():
    """Loads persisted analysis settings from settings.json into CONFIG."""
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding='utf-8'))
            int_fields   = ['max_seq_length','gc_window_size','max_parallel_workers',
                            'significance_permutations','download_timeout','download_retries']
            float_fields = ['golden_ratio_tolerance','fibonacci_tolerance',
                            'significance_threshold','exploratory_threshold',
                            'large_distance_threshold_percentile']
            bool_fields  = ['use_caching']
            for f in int_fields:
                if f in data:
                    setattr(CONFIG, f, int(data[f]))
            for f in float_fields:
                if f in data:
                    setattr(CONFIG, f, float(data[f]))
            for f in bool_fields:
                if f in data:
                    setattr(CONFIG, f, bool(data[f]))
    except Exception:
        pass

_apply_saved_settings_to_config()

# ============================================================
# EXTENDED FIBONACCI VARIANTS
# ============================================================

FIBONACCI_VARIANTS = {
    "classic": {
        "name": "Classic Fibonacci",
        "numbers": [1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987, 1597, 2584, 4181, 6765, 10946]
    },
    "lucas": {
        "name": "Lucas Numbers",
        "numbers": [2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199, 322, 521, 843, 1364, 2207, 3571, 5778, 9349]
    },
    "tribonacci": {
        "name": "Tribonacci",
        "numbers": [0, 0, 1, 1, 2, 4, 7, 13, 24, 44, 81, 149, 274, 504, 927, 1705, 3136, 5768, 10609, 19513]
    },
    "pell": {
        "name": "Pell Numbers",
        "numbers": [0, 1, 2, 5, 12, 29, 70, 169, 408, 985, 2378, 5741, 13860, 33461, 80782, 195025, 470832, 1136689, 2744210, 6625109]
    }
}

# IUPAC motifs for conserved elements
IUPAC_MOTIFS = {
    "TATA_box": {"pattern": "TATAWAW", "description": "TATA-Box Promoter", "min_len": 6},
    "CAAT_box": {"pattern": "CAAT", "description": "CAAT-Box", "min_len": 4},
    "GC_box": {"pattern": "GGGCGG", "description": "GC-rich Box", "min_len": 6},
    "polyA": {"pattern": "AAAAAA", "description": "Poly-A Signal", "min_len": 6},
    "promoter_35": {"pattern": "TTGACA", "description": "-35 Promoter (Bacteria)", "min_len": 6},
    "promoter_10": {"pattern": "TATAAT", "description": "-10 Pribnow Box", "min_len": 6},
    "enhancer": {"pattern": "GTGACGT", "description": "Enhancer Core", "min_len": 7},
    "splice_site": {"pattern": "AGGT", "description": "Splice site", "min_len": 4}
}

# ============================================================
# SQLITE CACHE SYSTEM
# ============================================================

class AnalysisCache:
    """SQLite-based cache for analysis results."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialisiert die Datenbank"""
        with self.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cached_analyses (
                    cache_key TEXT PRIMARY KEY,
                    method_id TEXT NOT NULL,
                    species_name TEXT NOT NULL,
                    accession TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_method_species 
                ON cached_analyses(method_id, species_name)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_accessed 
                ON cached_analyses(accessed_at)
            ''')
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def get_cache_key(self, method_id: str, accession: str, seq_hash: str) -> str:
        """Creates a unique cache key — uses accession (language-independent)."""
        return f"{method_id}:{accession}:{seq_hash}"
    
    def get(self, method_id: str, accession: str, sequence: str) -> Optional[Dict]:
        """Retrieves a result from the cache."""
        if not CONFIG.use_caching:
            return None
        
        seq_hash = hashlib.md5(sequence.encode()).hexdigest()[:16]
        cache_key = self.get_cache_key(method_id, accession, seq_hash)
        
        with self.get_connection() as conn:
            result = conn.execute(
                'SELECT result_json FROM cached_analyses WHERE cache_key = ?',
                (cache_key,)
            ).fetchone()
            
            if result:
                # Update accessed_at
                conn.execute(
                    'UPDATE cached_analyses SET accessed_at = CURRENT_TIMESTAMP WHERE cache_key = ?',
                    (cache_key,)
                )
                return json.loads(result['result_json'])
        return None
    
    def set(self, method_id: str, accession: str,
            sequence: str, result: Dict):
        """Stores a result in the cache — keyed by accession (language-independent)."""
        if not CONFIG.use_caching:
            return
        
        seq_hash = hashlib.md5(sequence.encode()).hexdigest()[:16]
        cache_key = self.get_cache_key(method_id, accession, seq_hash)
        
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO cached_analyses 
                (cache_key, method_id, species_name, accession, result_json, created_at, accessed_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (cache_key, method_id, accession, accession, json.dumps(result, cls=NumpyEncoder)))
    
    def clear_old(self, days: int = 30):
        """Deletes old cache entries."""
        with self.get_connection() as conn:
            conn.execute(
                'DELETE FROM cached_analyses WHERE accessed_at < datetime("now", ?)',
                (f'-{days} days',)
            )

# ============================================================
# GENOME READER (LAZY LOADING)
# ============================================================

class GenomeReader:
    """Streaming reader for large FASTA files with iterator-based processing."""
    
    def __init__(self, fasta_content: str, chunk_size: int = 10000):
        self.content = fasta_content
        self.chunk_size = chunk_size
        self._parse_headers_and_sequence()
    
    def _parse_headers_and_sequence(self):
        """Parses header and prepares sequence."""
        lines = self.content.strip().split('\n')
        self.headers = []
        self.sequence_parts = []
        
        current_header = None
        current_seq = []
        
        for line in lines:
            line = line.strip()
            if line.startswith('>'):
                if current_header:
                    self.headers.append(current_header)
                    self.sequence_parts.append(''.join(current_seq))
                current_header = line[1:]
                current_seq = []
            elif line:
                current_seq.append(line)
        
        if current_header:
            self.headers.append(current_header)
            self.sequence_parts.append(''.join(current_seq))
        
        self.full_sequence = ''.join(self.sequence_parts)
        # Keep only valid bases
        self.full_sequence = ''.join(c for c in self.full_sequence.upper() if c in 'ATCG')
    
    def chunks(self, max_bases: Optional[int] = None) -> Generator[str, None, None]:
        """Iterator for sequential processing in chunks."""
        seq_to_process = self.full_sequence
        if max_bases and len(seq_to_process) > max_bases:
            seq_to_process = seq_to_process[:max_bases]
        
        for i in range(0, len(seq_to_process), self.chunk_size):
            yield seq_to_process[i:i + self.chunk_size]
    
    def get_sequence(self, max_bases: Optional[int] = None) -> str:
        """Returns the complete sequence (with limit)."""
        if max_bases and len(self.full_sequence) > max_bases:
            return self.full_sequence[:max_bases]
        return self.full_sequence
    
    def get_length(self) -> int:
        return len(self.full_sequence)

# ============================================================
# NCBI FETCH MIT EXPONENTIAL BACKOFF
# ============================================================

NCBI_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/eutils/efetch.fcgi"
CONFIG_FILE = Path(__file__).parent / "ncbi_auth_config.json"

def load_api_key() -> str:
    """Loads API key from config."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                return config.get('ncbi_api_key', '')
        except:
            pass
    return ""

NCBI_API_KEY = load_api_key()

def _resolve_assembly_to_nuccore(accession: str,
                                  log_callback: Optional[Callable] = None) -> Optional[str]:
    """
    Resolves a GCA_/GCF_ assembly accession to the best available
    Nuccore accession (preferring the longest NC_ chromosome sequence).

    Robuste Implementierung:
    - Persistente requests.Session (verhindert ConnectionReset)
    - User-Agent-Header (NCBI erwartet Tool-Identifikation)
    - 1s Pause zwischen jedem E-Utilities-Aufruf (NCBI-Richtlinie)
    - 3 Versuche mit exponentiellem Backoff pro Schritt
    """
    ESEARCH_URL  = "https://eutils.ncbi.nlm.nih.gov/eutils/esearch.fcgi"
    ELINK_URL    = "https://eutils.ncbi.nlm.nih.gov/eutils/elink.fcgi"
    ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/eutils/esummary.fcgi"

    session = requests.Session()
    session.headers.update({
        "User-Agent":  "DNARhythmAnalyzer/1.0 (research tool; contact: user@localhost)",
        "Accept":      "application/json",
        "Connection":  "keep-alive",
    })
    if NCBI_API_KEY:
        session.headers["NCBI-ApiKey"] = NCBI_API_KEY

    # Base parameters for all E-Utilities requests
    base_params = {"tool": "DNARhythmAnalyzer", "email": "user@localhost"}
    if NCBI_API_KEY:
        base_params["api_key"] = NCBI_API_KEY

    def _get_with_retry(url, params, label):
        """GET mit bis zu 3 Versuchen und exponentiellem Backoff."""
        for attempt in range(3):
            wait = 2 ** attempt   # 1s, 2s, 4s
            try:
                time.sleep(1)     # NCBI-Rate-Limit: max 3 req/s ohne API-Key
                r = session.get(url, params={**base_params, **params}, timeout=45)
                if r.status_code == 200:
                    return r
                if log_callback:
                    log_callback(f"  ⚠️ {label}: HTTP {r.status_code}, warte {wait}s...")
                time.sleep(wait)
            except Exception as e:
                if log_callback:
                    log_callback(f"  ⚠️ {label} Versuch {attempt+1}: {type(e).__name__}, warte {wait}s...")
                time.sleep(wait)
        return None

    try:
        # ── Schritt 1: Assembly-ID per esearch ───────────────────────────────
        r1 = _get_with_retry(ESEARCH_URL,
                             {"db": "assembly", "term": accession,
                              "retmode": "json", "retmax": 1},
                             "esearch")
        if r1 is None:
            if log_callback:
                log_callback(t("log_messages.download_failed", accession=accession))
            return None
        ids = r1.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            if log_callback:
                log_callback(t("log_messages.assembly_failed", assembly=accession))
            return None
        assembly_id = ids[0]

        # ── Step 2: elink Assembly → Nuccore (RefSeq chromosomes preferred) ─
        # Erst RefSeq-Link versuchen, dann GenBank-Fallback
        nuccore_ids = []
        for linkname in ("assembly_nuccore_refseq", "assembly_nuccore_insdc"):
            r2 = _get_with_retry(ELINK_URL,
                                 {"dbfrom": "assembly", "db": "nuccore",
                                  "id": assembly_id, "linkname": linkname,
                                  "retmode": "json"},
                                 f"elink({linkname})")
            if r2 is None:
                continue
            for ls in r2.json().get("linksets", []):
                for lsd in ls.get("linksetdbs", []):
                    nuccore_ids.extend(lsd.get("links", []))
            if nuccore_ids:
                break   # RefSeq links found, no GenBank fallback needed

        if not nuccore_ids:
            if log_callback:
                log_callback(f"  ⚠️ No nuccore links for {accession}")
            return None

        # ── Step 3: esummary – accession + length of first 100 sequences ──
        # Batch-Abfrage, max 100 IDs
        ids_str = ",".join(str(i) for i in nuccore_ids[:100])
        r3 = _get_with_retry(ESUMMARY_URL,
                             {"db": "nuccore", "id": ids_str, "retmode": "json"},
                             "esummary")
        if r3 is None:
            # Fallback: use first nuccore_id directly without length comparison
            if log_callback:
                log_callback(f"  ⚠️ esummary fehlgeschlagen – verwende erste Nuccore-ID")
            return None

        summary  = r3.json().get("result", {})
        best_acc = None
        best_len = 0

        # Prefer: (1) NC_ chromosome, (2) NW_ scaffold, (3) anything else
        for prefix_group in [("NC_",), ("NW_",), ()]:
            for uid in nuccore_ids[:100]:
                entry = summary.get(str(uid), {})
                acc   = entry.get("accessionversion", "")
                slen  = int(entry.get("slen", 0))
                if prefix_group and not any(acc.startswith(p) for p in prefix_group):
                    continue
                if slen > best_len:
                    best_acc = acc
                    best_len = slen
            if best_acc:
                break   # Best quality tier found

        if log_callback and best_acc:
            log_callback(f"  🔗 {accession} → {best_acc} ({best_len:,} bp)")
        elif log_callback:
            log_callback(t("log_messages.assembly_failed", assembly=accession))

        return best_acc

    except Exception as e:
        if log_callback:
            log_callback(t("log_messages.assembly_error", error=e))
        return None
    finally:
        session.close()


def fetch_genome_with_backoff(accession: str, log_callback: Optional[Callable] = None) -> Optional[str]:
    """
    Downloads genome with exponential backoff and rate limiting.

    Supports two accession types:
      - NC_/NW_/NZ_/CM_: direkt per efetch (db=nuccore)
      - GCA_/GCF_:        Assembly-Accession → wird zuerst in die beste
                          chromosome Nuccore accession resolved, then fetched.
    """
    headers = {"Accept": "text/plain"}
    if NCBI_API_KEY:
        headers["NCBI-ApiKey"] = NCBI_API_KEY

    # GCA_/GCF_ accessions must be resolved first
    fetch_accession = accession
    if accession.startswith(("GCA_", "GCF_")):
        if log_callback:
            log_callback(t("log_messages.assembly_resolving"))
        resolved = _resolve_assembly_to_nuccore(accession, log_callback)
        if resolved:
            fetch_accession = resolved
        else:
            if log_callback:
                log_callback(f"  ❌ Could not resolve {accession}")
            return None

    params = {"db": "nuccore", "id": fetch_accession,
              "rettype": "fasta", "retmode": "text"}

    for attempt in range(CONFIG.download_retries):
        wait_time = min(2 ** attempt, 60)
        if attempt > 0 and NCBI_API_KEY:
            wait_time = 1

        if log_callback:
            log_callback(t("log_messages.download_retry", attempt=attempt+1, max=CONFIG.download_retries, accession=fetch_accession))

        try:
            response = requests.get(NCBI_EFETCH_URL, headers=headers,
                                    params=params, timeout=CONFIG.download_timeout)
            if response.status_code == 200:
                if log_callback:
                    log_callback(f"  ✅ Erfolg ({len(response.text):,} Bytes)")
                return response.text
            elif response.status_code == 429:
                if log_callback:
                    log_callback(t("log_messages.download_rate_limit", wait=wait_time))
                time.sleep(wait_time)
            else:
                if log_callback:
                    log_callback(f"  ⚠️ HTTP {response.status_code}")
                time.sleep(1)
        except requests.exceptions.Timeout:
            if log_callback:
                log_callback(t("log_messages.download_timeout", wait=wait_time))
            time.sleep(wait_time)
        except Exception as e:
            if log_callback:
                log_callback(t("log_messages.download_error", error=e, wait=wait_time))
            time.sleep(wait_time)

    if log_callback:
        log_callback(t("log_messages.download_failed", accession=fetch_accession))
    return None

def get_or_fetch_genome(accession: str, log_callback: Optional[Callable] = None) -> Optional[str]:
    """Fetches genome from cache or downloads it."""
    local_path = CONFIG.workspace_dir / f"{accession}.fasta"
    
    if local_path.exists():
        if log_callback:
            log_callback(t("log_messages.local_file_found", filename=local_path.name))
        with open(local_path, 'r', encoding='utf-8') as f:
            return f.read()
    
    if log_callback:
        log_callback(t("log_messages.download_start"))
    
    fasta = fetch_genome_with_backoff(accession, log_callback)
    if fasta:
        with open(local_path, 'w', encoding='utf-8') as f:
            f.write(fasta)
        if log_callback:
            log_callback(f"  💾 Gespeichert: {local_path.name}")
    return fasta

# ============================================================
# ERWEITERTE MOTIV-SUCHE (POSITION WEIGHT MATRIX)
# ============================================================

class PositionWeightMatrix:
    """Extended motif search with IUPAC and PWM."""
    
    def __init__(self):
        self.iupac_to_regex = {
            'W': '[AT]', 'S': '[GC]', 'M': '[AC]', 'K': '[GT]',
            'R': '[AG]', 'Y': '[CT]', 'B': '[CGT]', 'D': '[AGT]',
            'H': '[ACT]', 'V': '[ACG]', 'N': '[ATCG]'
        }
    
    def pattern_to_regex(self, pattern: str) -> str:
        """Konvertiert IUPAC-Pattern zu Regex"""
        regex = []
        for char in pattern:
            if char in self.iupac_to_regex:
                regex.append(self.iupac_to_regex[char])
            else:
                regex.append(char)
        return ''.join(regex)
    
    def find_conserved_elements(self, sequence: str, max_bases: int = 100000) -> List[int]:
        """Findet konservierte Elemente mit IUPAC-Motiven"""
        seq_short = sequence[:max_bases] if len(sequence) > max_bases else sequence
        positions = []
        
        for motif_name, motif_info in IUPAC_MOTIFS.items():
            pattern = motif_info["pattern"]
            regex_pattern = self.pattern_to_regex(pattern)
            
            import re
            for match in re.finditer(regex_pattern, seq_short):
                positions.append(match.start())
        
        return sorted(set(positions))

# ============================================================
# STATISTISCHE SIGNIFIKANZ-TESTS
# ============================================================

def shuffle_sequence(sequence: str) -> str:
    """Creates a randomly permuted sequence (preserves base frequency)."""
    seq_list = list(sequence)
    random.shuffle(seq_list)
    return ''.join(seq_list)

def calculate_significance(sequence: str, metric_function: Callable, 
                          observed_value: float, n_permutations: int = 1000,
                          log_callback: Optional[Callable] = None,
                          exploratory: bool = False) -> Dict[str, Any]:
    """
    Calculates statistical significance via permutation test.

    Parameter:
        exploratory - wenn True, wird CONFIG.exploratory_threshold (0.10) statt
                      CONFIG.significance_threshold (0.05) verwendet.
                      In der explorativen Bioinformatik ist p<0.1 akzeptabel,
                      besonders bei kleinen Stichproben oder neuen Hypothesen.
    """
    if log_callback:
        log_callback(t("analysis.running_permutation_test", n=n_permutations))
    
    null_distribution = []
    
    for i in range(n_permutations):
        shuffled = shuffle_sequence(sequence)
        null_value = metric_function(shuffled)
        null_distribution.append(null_value)
        
        if log_callback and (i + 1) % 200 == 0:
            log_callback(t("analysis.permutation_progress", i=i+1, n=n_permutations))
    
    null_distribution = np.array(null_distribution)
    
    # Calculate p-value (one-sided)
    if metric_function.__name__.startswith('higher_is_better'):
        p_value = np.sum(null_distribution >= observed_value) / n_permutations
    else:
        p_value = np.sum(null_distribution <= observed_value) / n_permutations
    
    # Effect size (Cohen's d)
    effect_size = (observed_value - np.mean(null_distribution)) / np.std(null_distribution)
    
    threshold_used = CONFIG.exploratory_threshold if exploratory else CONFIG.significance_threshold
    return {
        "p_value":            float(p_value),
        "significant":        bool(p_value < threshold_used),
        "significant_strict": bool(p_value < CONFIG.significance_threshold),      # p<0.05
        "significant_exploratory": bool(p_value < CONFIG.exploratory_threshold),  # p<0.10
        "threshold_applied":  float(threshold_used),
        "effect_size":        float(effect_size),
        "null_mean":          float(np.mean(null_distribution)),
        "null_std":           float(np.std(null_distribution)),
        "null_distribution":  null_distribution.tolist()[:100]
    }

# ============================================================
# FREQUENZZUWEISUNG
# ============================================================

BASE_TO_FREQ = {'A': 48.5, 'C': 49.5, 'T': 50.5, 'G': 51.5}

# ============================================================
# FREQUENCY SCHEMES FOR EXTENDED Δ-OPTIMISATION
# ============================================================
# Muss vor run_delta_optimization() stehen (wird dort aufgerufen).
# scheme_4 = original scheme (reference/backward-compatibility).
FREQUENCY_SCHEMES: Dict[str, Dict[str, float]] = {
    "scheme_1": {'A': 48.0, 'C': 48.5, 'T': 49.5, 'G': 50.0},  # Δ: 0.5,1.0,1.5,2.0
    "scheme_2": {'A': 48.0, 'C': 48.5, 'T': 50.0, 'G': 51.0},  # Δ: 0.5,1.0,1.5,2.0,2.5,3.0
    "scheme_3": {'A': 48.0, 'C': 49.0, 'T': 50.0, 'G': 51.0},  # Δ: 1.0,2.0,3.0
    "scheme_4": {'A': 48.5, 'C': 49.5, 'T': 50.5, 'G': 51.5},  # Δ: 1.0,2.0,3.0 (Original)
}
_DEFAULT_EXTENDED_SCHEME = "scheme_2"

# Module-level COARSE_DELTAS: all physically possible Δ values across all schemes.
# Computed here so it's available globally (GUI log, delta optimisation, etc.)
# Note: get_possible_deltas is defined below — we compute inline to avoid forward ref.
def _compute_coarse_deltas() -> List[float]:
    _all: set = set()
    for _fm in [BASE_TO_FREQ, *FREQUENCY_SCHEMES.values()]:
        _vals = list(_fm.values())
        for _i in range(len(_vals)):
            for _j in range(_i + 1, len(_vals)):
                _all.add(round(abs(_vals[_i] - _vals[_j]), 4))
    return sorted(_all)

COARSE_DELTAS: List[float] = _compute_coarse_deltas()


def get_possible_deltas(freq_map: Dict[str, float]) -> List[float]:
    """
    Calculates all physically possible |freq(b1) - freq(b2)|
    for b1 ≠ b2 from the given frequency assignment.
    Result is sorted ascending, rounded to 4 decimal places
    (no artificial coarsening rounding).
    """
    vals   = list(freq_map.values())
    deltas = set()
    for i in range(len(vals)):
        for j in range(i + 1, len(vals)):
            deltas.add(round(abs(vals[i] - vals[j]), 4))
    return sorted(deltas)


# ============================================================
# ANALYSIS METHODS
# ============================================================

def analyze_two_thz(seq: str,
                    log_callback: Optional[Callable] = None,
                    delta: float = 2.0,
                    n_permutations: Optional[int] = None,
                    freq_map: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Difference spectrum analysis (formerly '2-THz transitions').

    Analyses distances between positions where the assigned
    frequency of the next base pair differs by exactly `delta` THz.

    Parameter:
        delta          - Frequency difference (default 2.0, backward-compatible)
        n_permutations - Permutationszahl (default: CONFIG.significance_permutations)
        freq_map       - Frequenzzuweisung (default: None → globales BASE_TO_FREQ)
                         Enables alternative schemes for extended Δ ranges.
    """
    n_perm  = n_permutations if n_permutations is not None else CONFIG.significance_permutations
    # Use provided freq_map or default assignment
    _fmap   = freq_map if freq_map is not None else BASE_TO_FREQ
    if log_callback:
        log_callback(t("analysis.computing_diff_spectrum", delta=delta))

    if len(seq) > CONFIG.max_seq_length:
        seq = seq[:CONFIG.max_seq_length]

    # Positionen mit Frequenzdifferenz == delta (Gleitkomma-sicher: runde auf 6 Stellen)
    positions = []
    for i in range(len(seq) - 1):
        if seq[i] in _fmap and seq[i+1] in _fmap:
            diff = round(abs(_fmap[seq[i+1]] - _fmap[seq[i]]), 6)
            if abs(diff - delta) < 1e-6:
                positions.append(i)

    transitions = len(positions)
    if transitions < 2:
        return {"error": f"Too few transitions for Δ={delta:.1f} (found: {transitions})",
                "delta": delta, "transitions": transitions}

    distances = [positions[i+1] - positions[i] for i in range(len(positions)-1)]

    dists_arr       = np.array(distances)
    threshold       = float(np.percentile(dists_arr, CONFIG.large_distance_threshold_percentile))
    large_distances = [d for d in distances if d > threshold]
    if log_callback:
        log_callback(t("analysis.transitions_found", delta=f"{delta:.1f}", count=transitions, threshold=threshold, large=len(large_distances)))

    # Significance test – delta + _fmap in closure eingefangen
    def count_large_distances(s):
        s_seq = s[:CONFIG.max_seq_length] if len(s) > CONFIG.max_seq_length else s
        pos = []
        for i in range(len(s_seq) - 1):
            if s_seq[i] in _fmap and s_seq[i+1] in _fmap:
                diff = round(abs(_fmap[s_seq[i+1]] - _fmap[s_seq[i]]), 6)
                if abs(diff - delta) < 1e-6:
                    pos.append(i)
        if len(pos) < 2:
            return 0
        dists = [pos[i+1] - pos[i] for i in range(len(pos)-1)]
        thr   = float(np.percentile(dists, CONFIG.large_distance_threshold_percentile))
        return len([d for d in dists if d > thr])

    observed    = len(large_distances)
    significance = calculate_significance(seq, count_large_distances, observed,
                                          n_perm, log_callback)

    result = {
        "method":               "Difference Spectrum",
        "delta":                delta,
        "sequence_length":      len(seq),
        "transitions":          transitions,
        "total_distances":      len(distances),
        "min_distance":         min(distances),
        "max_distance":         max(distances),
        "mean_distance":        sum(distances) / len(distances),
        "large_distances_count": len(large_distances),
        "large_distances":      large_distances[:100],
        "rhythm":               None,
        "statistical_significance": significance,
    }

    if large_distances:
        tolerance = 0.05
        bins: Dict[int, int] = {}
        for d in large_distances:
            found = False
            for key in list(bins.keys()):
                if abs(d - key) / max(key, 1) <= tolerance:
                    bins[key] += 1
                    found = True
                    break
            if not found:
                bins[d] = 1
        if bins:
            dominant          = max(bins, key=bins.get)
            result["rhythm"]           = int(dominant)
            result["rhythm_frequency"] = bins[dominant]

    return result

def analyze_fibonacci(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Fibonacci distances analysis with all Fibonacci variants."""
    if log_callback:
        log_callback(t("analysis.searching_fibonacci"))
    
    if len(seq) > CONFIG.max_seq_length:
        seq = seq[:CONFIG.max_seq_length]
    
    # Extended motif search
    pwm = PositionWeightMatrix()
    conserved_positions = pwm.find_conserved_elements(seq, CONFIG.max_seq_length)
    
    if len(conserved_positions) < 2:
        return {"error": "Too few conserved elements"}

    if len(conserved_positions) < 10:
        if log_callback:
            log_callback(t("analysis.few_conserved_elements", count=len(conserved_positions)))

    distances = [conserved_positions[i+1] - conserved_positions[i]
                 for i in range(len(conserved_positions)-1)]
    
    # Dynamic Fibonacci tolerance:
    # Smaller base (5%) + additional correction for large Fibonacci numbers.
    # At fib=377: 5% = 18.9 bp (instead of 38 bp at 10%) => more precise.
    def _is_fib_match(d: int, fib: int) -> bool:
        """5% base tolerance; for fib>100 it is capped by ratio."""
        base_tol  = CONFIG.fibonacci_tolerance * 0.5   # Halbiert (0.1 → 0.05)
        rel_dev   = abs(d - fib) / max(fib, 1)
        if fib > 100:
            # For large Fibonacci numbers: max absolute deviation = 1/10 of the number
            abs_tol = (abs(d - fib) / fib) if fib > 0 else 0
            return rel_dev <= base_tol and abs_tol <= base_tol
        return rel_dev <= base_tol

    results_by_variant = {}
    all_matches = []

    for variant_name, variant_info in FIBONACCI_VARIANTS.items():
        fib_numbers = variant_info["numbers"]
        matches = []
        for d in distances:
            for fib in fib_numbers:
                if _is_fib_match(d, fib):
                    matches.append({"distance": d, "fibonacci": fib,
                                   "deviation": abs(d - fib) / max(fib, 1) * 100,
                                   "variant": variant_name})
                    break
        
        match_rate = len(matches) / len(distances) * 100 if distances else 0
        results_by_variant[variant_name] = {
            "name": variant_info["name"],
            "matches": len(matches),
            "match_rate": match_rate,
            "examples": matches[:10]
        }
        all_matches.extend(matches)
    
    # Significance test for the best variant
    def count_fibonacci_matches(s):
        s_seq = s[:CONFIG.max_seq_length] if len(s) > CONFIG.max_seq_length else s
        pos = pwm.find_conserved_elements(s_seq, CONFIG.max_seq_length)
        if len(pos) < 2:
            return 0
        dists = [pos[i+1] - pos[i] for i in range(len(pos)-1)]
        matches = 0
        for d in dists:
            for fib in FIBONACCI_VARIANTS["classic"]["numbers"]:
                if _is_fib_match(d, fib):
                    matches += 1
                    break
        return matches
    
    best_match_rate = max(v["match_rate"] for v in results_by_variant.values())
    observed = int(best_match_rate / 100 * len(distances)) if distances else 0
    significance = calculate_significance(seq, count_fibonacci_matches, observed,
                                         CONFIG.significance_permutations, log_callback)
    
    return {
        "method": "Fibonacci Distances",
        "conserved_elements": len(conserved_positions),
        "total_distances": len(distances),
        "fibonacci_variants": results_by_variant,
        "best_match_rate": best_match_rate,
        "all_matches_count": len(all_matches),
        "statistical_significance": significance
    }

def analyze_golden_ratio(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Golden ratio analysis with tolerance and two control tests for artefact detection."""
    if log_callback:
        log_callback(t("analysis.searching_golden_ratio"))
    
    if len(seq) > CONFIG.max_seq_length:
        seq = seq[:CONFIG.max_seq_length]
    
    golden = 1.618033988749895
    
    pwm = PositionWeightMatrix()
    conserved_positions = pwm.find_conserved_elements(seq, CONFIG.max_seq_length)
    
    if len(conserved_positions) < 3:
        return {"error": "Too few conserved elements"}

    if len(conserved_positions) < 10:
        if log_callback:
            log_callback(f"  ⚠️ Only {len(conserved_positions)} conserved elements – low statistical power")

    ratios = []
    raw_ratios = []
    for i in range(len(conserved_positions) - 2):
        d1 = conserved_positions[i+1] - conserved_positions[i]
        d2 = conserved_positions[i+2] - conserved_positions[i+1]
        if d1 > 0 and d2 > 0:
            ratio = max(d1, d2) / min(d1, d2)
            raw_ratios.append(ratio)

    ratio_std    = float(np.std(raw_ratios)) if len(raw_ratios) > 1 else 0.0
    dynamic_tol  = max(CONFIG.golden_ratio_tolerance, 2.0 * ratio_std / golden)
    for i, ratio in enumerate(raw_ratios):
        d1 = conserved_positions[i+1] - conserved_positions[i]
        d2 = conserved_positions[i+2] - conserved_positions[i+1]
        is_golden = abs(ratio - golden) / golden <= dynamic_tol
        ratios.append({"ratio": ratio, "is_golden": is_golden,
                       "d1": d1, "d2": d2})
    
    golden_count = sum(1 for r in ratios if r["is_golden"])
    match_rate   = golden_count / len(ratios) * 100 if ratios else 0
    distances    = [r["d1"] for r in ratios] + ([ratios[-1]["d2"]] if ratios else [])

    if log_callback:
        log_callback(t("analysis.adaptive_tolerance", tol=dynamic_tol, base=CONFIG.golden_ratio_tolerance, sigma=2*ratio_std/golden))

    # ── Control test 1: Random positions ─────────────────────────────────────
    # Question: Does any arbitrary position sequence show similar match rates?
    # If yes → artefact of motif search, not biologically specific.
    import random as _random
    rng_ctrl = _random.Random(42)
    n_ctrl_runs = 20
    random_match_rates = []
    for _ in range(n_ctrl_runs):
        rand_pos = sorted(rng_ctrl.sample(range(len(seq)), len(conserved_positions)))
        rand_ratios = []
        for i in range(len(rand_pos) - 2):
            d1 = rand_pos[i+1] - rand_pos[i]
            d2 = rand_pos[i+2] - rand_pos[i+1]
            if d1 > 0 and d2 > 0:
                ratio = max(d1, d2) / min(d1, d2)
                rand_ratios.append(abs(ratio - golden) / golden <= dynamic_tol)
        if rand_ratios:
            random_match_rates.append(sum(rand_ratios) / len(rand_ratios) * 100)

    ctrl1_mean = float(np.mean(random_match_rates)) if random_match_rates else 0.0
    ctrl1_std  = float(np.std(random_match_rates))  if random_match_rates else 0.0

    # Interpretation: echter Effekt wenn echte Match-Rate >> Zufalls-Match-Rate
    ctrl1_effect = match_rate - ctrl1_mean  # positiv = echter Effekt, negativ = Artefakt
    if ctrl1_effect > 10:
        ctrl1_interpretation = "Real effect – conserved elements follow φ more than random"
    elif ctrl1_effect > 0:
        ctrl1_interpretation = "Weak effect – slightly above random"
    else:
        ctrl1_interpretation = "Artefact suspected – random positions show equal or higher match rate"

    # ── Control test 2: Shuffled distances ───────────────────────────────────
    # Question: Is the order of distances decisive?
    # If shuffled distances show the same match rate →
    # the distance distribution alone explains the effect, not the order.
    n_perm_runs = 20
    perm_match_rates = []
    orig_distances = [r["d1"] for r in ratios]
    if len(orig_distances) >= 2:
        for _ in range(n_perm_runs):
            perm_d = orig_distances.copy()
            rng_ctrl.shuffle(perm_d)
            perm_ratios = []
            for i in range(len(perm_d) - 1):
                d1, d2 = perm_d[i], perm_d[i+1]
                if d1 > 0 and d2 > 0:
                    ratio = max(d1, d2) / min(d1, d2)
                    perm_ratios.append(abs(ratio - golden) / golden <= dynamic_tol)
            if perm_ratios:
                perm_match_rates.append(sum(perm_ratios) / len(perm_ratios) * 100)

    ctrl2_mean = float(np.mean(perm_match_rates)) if perm_match_rates else 0.0
    ctrl2_std  = float(np.std(perm_match_rates))  if perm_match_rates else 0.0
    ctrl2_effect = match_rate - ctrl2_mean

    if ctrl2_effect > 10:
        ctrl2_interpretation = "Order effect confirmed – the sequence of distances is decisive"
    elif ctrl2_effect > 0:
        ctrl2_interpretation = "Weak order effect"
    else:
        ctrl2_interpretation = "No order effect – distance distribution explains the effect, not the order"

    if log_callback:
        log_callback(t("analysis.control_test_1", mean=ctrl1_mean, std=ctrl1_std, interpretation=ctrl1_interpretation))
        log_callback(t("analysis.control_test_2", mean=ctrl2_mean, std=ctrl2_std, interpretation=ctrl2_interpretation))

    # Significance test
    def count_golden_ratios(s):
        s_seq = s[:CONFIG.max_seq_length] if len(s) > CONFIG.max_seq_length else s
        pos = pwm.find_conserved_elements(s_seq, CONFIG.max_seq_length)
        if len(pos) < 3:
            return 0
        count = 0
        for i in range(len(pos) - 2):
            d1 = pos[i+1] - pos[i]
            d2 = pos[i+2] - pos[i+1]
            if d1 > 0 and d2 > 0:
                ratio = max(d1, d2) / min(d1, d2)
                if abs(ratio - golden) / golden <= CONFIG.golden_ratio_tolerance:
                    count += 1
        return count
    
    significance = calculate_significance(seq, count_golden_ratios, golden_count,
                                         CONFIG.significance_permutations, log_callback)
    
    return {
        "method":               "Golden Ratio",
        "conserved_elements":   len(conserved_positions),
        "ratios_analyzed":      len(ratios),
        "golden_ratio_matches": golden_count,
        "match_rate":           match_rate,
        "tolerance_configured": CONFIG.golden_ratio_tolerance,
        "tolerance_applied":    float(dynamic_tol),
        "ratio_std":            float(ratio_std),
        "statistical_significance": significance,
        "examples":             [r for r in ratios if r["is_golden"]][:10],
        # Kontrolltests zur Artefakt-Erkennung
        "control_test_1_random_positions": {
            "description":      "Random positions (same count as conserved elements)",
            "n_runs":           n_ctrl_runs,
            "mean_match_rate":  ctrl1_mean,
            "std_match_rate":   ctrl1_std,
            "effect_vs_real":   float(ctrl1_effect),
            "interpretation":   ctrl1_interpretation,
        },
        "control_test_2_shuffled_distances": {
            "description":      "Shuffled distances (same distribution, destroyed order)",
            "n_runs":           n_perm_runs,
            "mean_match_rate":  ctrl2_mean,
            "std_match_rate":   ctrl2_std,
            "effect_vs_real":   float(ctrl2_effect),
            "interpretation":   ctrl2_interpretation,
        },
    }

def analyze_power_law(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Power-law analysis with improved statistics."""
    if log_callback:
        log_callback(t("analysis.analysing_power_law"))
    
    if len(seq) > CONFIG.max_seq_length:
        seq = seq[:CONFIG.max_seq_length]
    
    # Use 2-THz transitions for distance distribution
    positions = []
    for i in range(len(seq) - 1):
        if seq[i] in BASE_TO_FREQ and seq[i+1] in BASE_TO_FREQ:
            if abs(BASE_TO_FREQ[seq[i+1]] - BASE_TO_FREQ[seq[i]]) == 2.0:
                positions.append(i)
    
    if len(positions) < CONFIG.power_law_min_points:
        return {"error": f"Too few data points ({len(positions)} < {CONFIG.power_law_min_points})"}
    
    distances = [positions[i+1] - positions[i] for i in range(len(positions)-1)]
    distances = [d for d in distances if d > 0]
    
    # Distance histogram (logarithmic bins)
    log_bins = np.logspace(np.log10(min(distances)), np.log10(max(distances)), 50)
    hist, bin_edges = np.histogram(distances, bins=log_bins)
    
    # Power-Law-Fit
    bin_centers = np.sqrt(bin_edges[:-1] * bin_edges[1:])
    non_zero = hist > 0
    
    if np.sum(non_zero) > 5:
        log_centers = np.log(bin_centers[non_zero])
        log_hist = np.log(hist[non_zero])
        
        try:
            slope, intercept = np.polyfit(log_centers, log_hist, 1)
            power_law_exponent = -slope
            residuals = log_hist - (slope * log_centers + intercept)
            ss_res    = float(np.sum(residuals**2))
            ss_tot    = float(np.sum((log_hist - np.mean(log_hist))**2))
            r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0
            # AIC/BIC: Modellguete-Kriterien (k=2 Parameter: Slope + Intercept)
            # AIC = n*ln(RSS/n) + 2k; BIC = n*ln(RSS/n) + k*ln(n)
            n_pts = len(log_centers)
            k_params = 2
            if n_pts > 0 and ss_res > 0:
                log_rss_n = np.log(ss_res / n_pts)
                aic = float(n_pts * log_rss_n + 2 * k_params)
                bic = float(n_pts * log_rss_n + k_params * np.log(n_pts))
            else:
                aic = bic = None
        except:
            power_law_exponent = None
            r_squared = None
            aic = bic = None
    else:
        power_law_exponent = None
        r_squared = None
    
    # Bootstrap CI for the power-law exponent
    exp_ci = None
    if power_law_exponent and len(distances) > 20:
        dist_arr = np.array(distances, dtype=float)
        def _pl_exp(d):
            lc = np.log(bin_centers[non_zero])
            lb = np.log(np.histogram(d, bins=log_bins)[0][non_zero] + 1e-9)
            s, _ = np.polyfit(lc, lb, 1)
            return -s
        exp_ci = bootstrap_ci(dist_arr, _pl_exp, n_bootstrap=300)

    return {
        "method":               "Power-Law-Verteilung",
        "data_points":          len(distances),
        "power_law_exponent":   power_law_exponent,
        "exponent_ci_95":       exp_ci,             # Bootstrap 95%-KI
        "fit_quality_r_squared": r_squared,
        "fit_aic":              aic if power_law_exponent else None,
        "fit_bic":              bic if power_law_exponent else None,
        "interpretation": ("Fraktales System" if power_law_exponent and 1.5 < power_law_exponent < 3.5
                           else t("analysis.no_power_law")),
        "note": "Exponent ~2-3 typisch; AIC/BIC erlauben Modellvergleich; 95%-KI via Bootstrap",
        "hist_bin_centers": bin_centers[non_zero].tolist() if np.sum(non_zero) > 0 else [],
        "hist_counts":      hist[non_zero].tolist() if np.sum(non_zero) > 0 else [],
        "fit_slope":        float(-power_law_exponent) if power_law_exponent else None,
        "fit_intercept":    float(intercept) if power_law_exponent else None
    }

def _cgr_correlation_xy(points: np.ndarray) -> Optional[float]:
    """Pearson-Korrelation x↔y – misst Diagonale (↙↗)"""
    if len(points) < 2:
        return None
    return float(np.corrcoef(points[:, 0], points[:, 1])[0, 1])

def _cgr_correlation_x_yinv(points: np.ndarray) -> Optional[float]:
    """Pearson-Korrelation x↔(1-y) – misst Gegendiagonale (↘↖)"""
    if len(points) < 2:
        return None
    return float(np.corrcoef(points[:, 0], 1 - points[:, 1])[0, 1])

def _cgr_histogram_peaks(coords: np.ndarray, bins: int = 50) -> Dict[str, Any]:
    """Peaks im Histogramm einer Koordinate – misst Linien"""
    from scipy.signal import find_peaks as _find_peaks
    hist, bin_edges = np.histogram(coords, bins=bins, range=(0.0, 1.0))
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    threshold = float(np.max(hist)) * 0.1
    peaks, _ = _find_peaks(hist, height=threshold)
    return {
        "peak_positions": bin_centers[peaks].tolist(),
        "peak_heights":   hist[peaks].tolist(),
        "peak_count":     int(len(peaks))
    }

def _cgr_center_density(points: np.ndarray, radius: float = 0.05) -> float:
    """Anteil der points im Kreis r=0.05 um (0.5,0.5) – misst Kreuz/symmetry"""
    center = np.array([0.5, 0.5])
    distances = np.linalg.norm(points - center, axis=1)
    return float(np.sum(distances < radius) / len(points))

def _cgr_fractal_dimension(points: np.ndarray, max_box: int = 64) -> float:
    """Box-Counting fraktale Dimension"""
    pts_scaled = np.clip((points * max_box).astype(int), 0, max_box - 1)
    box_sizes, counts = [], []
    for bs in [2, 4, 8, 16, 32, 64]:
        boxes = set(zip(pts_scaled[:, 0] // bs, pts_scaled[:, 1] // bs))
        if len(boxes) > 0:
            box_sizes.append(float(np.log(1.0 / bs)))
            counts.append(float(np.log(len(boxes))))
    if len(box_sizes) > 2:
        slope, _ = np.polyfit(box_sizes, counts, 1)
        # Bugfix: No negation – box-counting dim is the slope itself.
        # D = lim(log N / log(1/ε)): Steigung im log-log Plot = D direkt.
        # Negative value was physically impossible (D must be 1-2).
        return float(slope)
    return 0.0

def _cgr_diagonal_with_repetition(points: np.ndarray) -> Dict[str, Any]:
    """
    Metrik 1 – Diagonale mit Wiederholung (S. pneumoniae).
    Measures whether the diagonal (↙↗) is equally strong in upper and lower half
    und ob das Muster sich ab der Mitte mit konstantem Winkel wiederholt.
    """
    lower = points[points[:, 1] < 0.5]
    upper = points[points[:, 1] >= 0.5]

    def _corr(p):
        if len(p) < 2: return 0.0
        c = np.corrcoef(p[:, 0], p[:, 1])[0, 1]
        return float(c) if np.isfinite(c) else 0.0

    corr_lower = _corr(lower)
    corr_upper = _corr(upper)

    # How similar is the density distribution along the diagonal in both halves?
    repetition = 0.0
    if len(lower) > 1 and len(upper) > 1:
        dev_lower = lower[:, 1] - lower[:, 0]   # 0 = genau auf der Diagonale
        dev_upper = upper[:, 1] - upper[:, 0]
        h_lower, _ = np.histogram(dev_lower, bins=20, range=(-0.5, 0.5))
        h_upper, _ = np.histogram(dev_upper, bins=20, range=(-0.5, 0.5))
        if np.std(h_lower) > 0 and np.std(h_upper) > 0:
            r = np.corrcoef(h_lower, h_upper)[0, 1]
            repetition = float(r) if np.isfinite(r) else 0.0

    # Angle consistency: standard deviation of correlations in both halves
    angle_consistency = float(1.0 - np.std([corr_lower, corr_upper]))

    return {
        "diag_strength_lower":   corr_lower,
        "diag_strength_upper":   corr_upper,
        "diag_repetition":       repetition,
        "diag_angle_consistency": angle_consistency,
        # Zusammenfassung: hat diese Spezies das S.-pneumoniae-patterns?
        "has_repeated_diagonal": bool(
            corr_lower > 0.3 and corr_upper > 0.3 and repetition > 0.5
        )
    }


def _cgr_horizontal_lines(points: np.ndarray,
                           expected: List[float] = None) -> Dict[str, Any]:
    """
    Metrik 2 – Horizontale Linien (A. gambiae).
    Searches for peaks in the y-histogram and checks whether known positions are hit.
    """
    from scipy.signal import find_peaks as _fp
    if expected is None:
        expected = [0.0, 0.04, 0.06, 0.10, 0.22, 0.38]

    hist, edges = np.histogram(points[:, 1], bins=200, range=(0.0, 1.0))
    centers = (edges[:-1] + edges[1:]) / 2
    threshold = float(np.max(hist)) * 0.1
    peaks, _ = _fp(hist, height=threshold, distance=3)

    peak_pos = centers[peaks].tolist()
    peak_hgt = hist[peaks].tolist()

    # Abgleich mit erwarteten Positionen (Toleranz ±0.015)
    matched = {}
    for exp in expected:
        key = f"y={exp:.2f}"
        if len(peak_pos) > 0:
            dists = np.abs(np.array(peak_pos) - exp)
            nearest_i = int(np.argmin(dists))
            matched[key] = float(peak_hgt[nearest_i]) if dists[nearest_i] < 0.015 else 0.0
        else:
            matched[key] = 0.0

    strong_peaks = int(np.sum(np.array(peak_hgt) > float(np.max(hist)) * 0.5)) if peak_hgt else 0
    match_score  = float(sum(1 for v in matched.values() if v > 0) / len(expected))

    return {
        "expected_line_strengths": matched,
        "total_peaks":             int(len(peaks)),
        "strong_peaks":            strong_peaks,
        "peak_positions":          peak_pos,
        "peak_heights":            peak_hgt,
        "best_match_to_expected":  match_score,
        # Zusammenfassung: hat diese Spezies das A.-gambiae-patterns?
        "has_horizontal_lines":    bool(strong_peaks >= 3 or match_score >= 0.5)
    }


def _cgr_cross_at_center(points: np.ndarray,
                          center: float = 0.5,
                          tol: float = 0.02) -> Dict[str, Any]:
    """
    Metrik 3 – Kreuz bei 0.5 (A. thaliana).
    Misst vertikale Linie x≈0.5, horizontale Linie y≈0.5,
    Kreuzungspunkte und Quadrantensymmetrie.
    """
    n = len(points)
    # points nahe x=0.5 (vertikale Linie)
    vert  = points[np.abs(points[:, 0] - center) < tol]
    # points nahe y=0.5 (horizontale Linie)
    horiz = points[np.abs(points[:, 1] - center) < tol]
    # Kreuzung: nahe (0.5, 0.5)
    cross = points[(np.abs(points[:, 0] - center) < tol) &
                   (np.abs(points[:, 1] - center) < tol)]

    v_strength = float(len(vert)  / n)
    h_strength = float(len(horiz) / n)

    # Quadrantensymmetrie
    q = [len(points[(points[:, 0] > center) & (points[:, 1] > center)]),
         len(points[(points[:, 0] < center) & (points[:, 1] > center)]),
         len(points[(points[:, 0] < center) & (points[:, 1] < center)]),
         len(points[(points[:, 0] > center) & (points[:, 1] < center)])]
    symmetry = float(1.0 - np.std(q) / np.mean(q)) if np.mean(q) > 0 else 0.0

    # Clusters of crossing points (approximate, without sklearn)
    cross_clusters = 0
    if len(cross) > 0:
        # Einfaches Grid-Clustering: 0.01-Gitter
        grid_cells = set(
            (int(p[0] / 0.01), int(p[1] / 0.01)) for p in cross
        )
        cross_clusters = int(len(grid_cells))

    return {
        "vertical_line_strength":   v_strength,
        "horizontal_line_strength": h_strength,
        "cross_points_count":       int(len(cross)),
        "cross_clusters":           cross_clusters,
        "quadrant_symmetry":        symmetry,
        "has_cross": bool(v_strength > 0.03 and h_strength > 0.03)
    }


def _cgr_double_diagonal(points: np.ndarray) -> Dict[str, Any]:
    """
    Metrik 4 – Doppelte Diagonale (R. norvegicus).
    Measures strength of main (↙↗) and counter-diagonal (↘↖)
    and their consistency across all 4 quadrants.
    """
    # Abweichung von der Hauptdiagonale y=x  → 0 = genau auf der Linie
    dev_main  = points[:, 1] - points[:, 0]
    # Abweichung von der Gegendiagonale y=1-x
    dev_anti  = points[:, 1] - (1 - points[:, 0])

    # Strength = the smaller the scatter around 0, the stronger the line
    # Normalised to [0,1]: std of 0 → strength 1, std of 0.5 → strength 0
    diag_strength  = float(max(0.0, 1.0 - np.std(dev_main)  / 0.5))
    anti_strength  = float(max(0.0, 1.0 - np.std(dev_anti)  / 0.5))

    # Consistency across 4 quadrants
    quadrants = [
        points[(points[:, 0] < 0.5) & (points[:, 1] < 0.5)],
        points[(points[:, 0] < 0.5) & (points[:, 1] >= 0.5)],
        points[(points[:, 0] >= 0.5) & (points[:, 1] < 0.5)],
        points[(points[:, 0] >= 0.5) & (points[:, 1] >= 0.5)],
    ]
    quad_diag = []
    for q in quadrants:
        if len(q) > 1:
            d = q[:, 1] - q[:, 0]
            quad_diag.append(float(max(0.0, 1.0 - np.std(d) / 0.5)))
        else:
            quad_diag.append(0.0)

    consistency = float(1.0 - np.std(quad_diag)) if len(quad_diag) > 1 else 0.0

    return {
        "diag_strength":                     diag_strength,
        "anti_diag_strength":                anti_strength,
        "diag_ratio":                        float(diag_strength / (anti_strength + 0.01)),
        "diag_consistency_across_quadrants": consistency,
        "has_double_diagonal": bool(diag_strength > 0.3 and anti_strength > 0.1)
    }


def analyze_cgr(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """CGR (Chaos Game Representation) mit 6 patterns-Metriken"""
    if log_callback:
        log_callback(t("analysis.computing_cgr"))

    corners = {'A': np.array([0.0, 0.0]), 'T': np.array([1.0, 0.0]),
               'C': np.array([0.0, 1.0]), 'G': np.array([1.0, 1.0])}

    max_points = CONFIG.cgr_max_points
    step = max(1, len(seq) // max_points)
    seq_small = seq[::step][:max_points]

    points = []
    point = np.array([0.5, 0.5])
    for base in seq_small:
        if base in corners:
            point = (point + corners[base]) / 2.0
            points.append(point.copy())

    points = np.array(points)

    if len(points) == 0:
        return {"error": "No valid points generated"}

    # ── Fractal dimension (box-counting over range size) ──────────────────────
    x_range = np.ptp(points[:, 0])
    y_range = np.ptp(points[:, 1])
    max_range = max(x_range, y_range)
    scales, bcounts = [], []
    for scale in range(2, 8):
        box_size = max_range / (2 ** scale)
        if box_size > 0:
            x_bins = np.floor(points[:, 0] / box_size)
            y_bins = np.floor(points[:, 1] / box_size)
            unique_boxes = len(set(zip(x_bins.tolist(), y_bins.tolist())))
            scales.append(float(np.log(1 / box_size)))
            bcounts.append(float(np.log(unique_boxes)))
    fractal_dimension_old = float(np.polyfit(scales, bcounts, 1)[0]) if len(scales) > 2 else 0.0

    x_var = float(np.var(points[:, 0]))
    y_var = float(np.var(points[:, 1]))
    fractal_indicator = (x_var + y_var) / 2

    # ── 6 allgemeine + 4 spezifische CGR-Metriken ───────────────────────────
    if log_callback:
        log_callback(t("analysis.computing_cgr_metrics"))

    cgr_metrics = {
        # Allgemeine Metriken
        "correlation_xy":           _cgr_correlation_xy(points),
        "correlation_x_yinv":       _cgr_correlation_x_yinv(points),
        "horizontal_peaks":         _cgr_histogram_peaks(points[:, 1]),
        "vertical_peaks":           _cgr_histogram_peaks(points[:, 0]),
        "center_density":           _cgr_center_density(points),
        "fractal_dimension":        _cgr_fractal_dimension(points),
        "points_count":             int(len(points)),
        # Spezifische patterns-Metriken
        "diagonal_with_repetition": _cgr_diagonal_with_repetition(points),
        "horizontal_lines":         _cgr_horizontal_lines(points),
        "cross_at_center":          _cgr_cross_at_center(points),
        "double_diagonal":          _cgr_double_diagonal(points),
    }

    if log_callback:
        m  = cgr_metrics
        dd = m["double_diagonal"]
        dw = m["diagonal_with_repetition"]
        hl = m["horizontal_lines"]
        cx = m["cross_at_center"]
        log_callback(f"    corr_xy={m['correlation_xy']:.3f}  "
                     f"corr_x_yinv={m['correlation_x_yinv']:.3f}  "
                     f"center_density={m['center_density']:.4f}")
        log_callback(f"    h_peaks={m['horizontal_peaks']['peak_count']}  "
                     f"v_peaks={m['vertical_peaks']['peak_count']}  "
                     f"fractal_dim={m['fractal_dimension']:.3f}")
        log_callback(f"    [Pattern] diag={dd['diag_strength']:.3f}  "
                     f"anti={dd['anti_diag_strength']:.3f}  "
                     f"repetition={dw['diag_repetition']:.3f}  "
                     f"h_match={hl['best_match_to_expected']:.2f}  "
                     f"has_cross={cx['has_cross']}")

    cgr_data = {
        "points":            points[:10000].tolist() if len(points) > 10000 else points.tolist(),
        "fractal_dimension": fractal_dimension_old
    }

    return {
        "method":            "CGR (Chaos Game)",
        "points_generated":  int(len(points)),
        "fractal_indicator": fractal_indicator,
        "fractal_dimension": fractal_dimension_old,
        "cgr_metrics":       cgr_metrics,
        "note":              "Fractal dimension between 1.5 and 1.9 typical for DNA",
        "cgr_data":          cgr_data
    }

def analyze_piano_roll(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Frequency profile analysis."""
    if log_callback:
        log_callback(t("analysis.computing_freq_profile"))
    
    step = max(1, len(seq) // CONFIG.max_seq_length)
    seq_small = seq[::step][:CONFIG.max_seq_length]
    
    freq_values = [BASE_TO_FREQ.get(c, 0) for c in seq_small]
    
    # Frequency distribution
    freq_counts = Counter(freq_values)
    
    # Transition frequencies
    transitions = []
    transition_types = []
    for i in range(len(seq_small) - 1):
        trans = abs(freq_values[i+1] - freq_values[i])
        transitions.append(trans)
        
        # Categorise transitions
        if trans == 0:
            transition_types.append("equal")
        elif trans == 1.0:
            transition_types.append("neighbour")
        elif trans == 2.0:
            transition_types.append("2-THz")
        else:
            transition_types.append("distant")
    
    trans_counts = Counter(transitions)
    type_counts = Counter(transition_types)
    
    # Musical metaphor
    most_common_transition = trans_counts.most_common(1)[0][0] if trans_counts else 0
    
    musical_interpretation = {
        0.0: "🔄 Constant tone",
        1.0: "🎵 Semitone step",
        2.0: "🎶 Whole tone step (2-THz rhythm!)",
        3.0: "🎼 Third leap"
    }.get(most_common_transition, "🎹 Complex jump")
    
    return {
        "method": "Frequency Profile",
        "analyzed_bases": len(seq_small),
        "frequency_distribution": {str(k): v for k, v in freq_counts.items()},
        "transition_distribution": {str(k): v for k, v in trans_counts.items()},
        "transition_types": type_counts,
        "most_common_transition": most_common_transition,
        "musical_interpretation": musical_interpretation,
        "freq_values_sample": freq_values[:5000]  # For plot
    }

def analyze_autocorr(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Autocorrelation analysis with peak detection."""
    if log_callback:
        log_callback(t("analysis.computing_autocorr"))

    # Downsampling
    step = max(1, len(seq) // CONFIG.max_seq_length)
    seq_small = seq[::step][:CONFIG.max_seq_length]

    if len(seq_small) < 10:
        return {"error": f"Sequence too short for autocorrelation ({len(seq_small)} bp)"}

    # Encode bases as numbers
    base_to_num = {'A': 0, 'C': 1, 'T': 2, 'G': 3}
    num_seq = np.array([base_to_num.get(c, 0) for c in seq_small])

    if len(num_seq) == 0:
        return {"error": "No valid bases after encoding"}

    # Autokorrelation
    mean = np.mean(num_seq)
    centered = num_seq - mean
    autocorr = np.correlate(centered, centered, mode='full')
    autocorr = autocorr[len(autocorr)//2:]

    # Suche nach signifikanten Peaks
    max_lag = min(CONFIG.autocorr_max_lag, len(autocorr) // 2)
    peak_indices = []
    peak_values = []

    if max_lag > 10:
        from scipy.signal import find_peaks
        autocorr_smoothed = np.convolve(autocorr[:max_lag], np.ones(5)/5, mode='same')
        std_val = np.std(autocorr_smoothed[10:])
        if std_val > 0:
            peaks, _ = find_peaks(autocorr_smoothed,
                                   height=std_val * 1.5,
                                   distance=5)
            peak_indices = peaks.tolist()
            peak_values = autocorr_smoothed[peaks].tolist()

        dominant_period = peak_indices[0] if peak_indices else None

        # Bootstrap confidence interval for dominant peak (500 iterations).
        # Zeigt ob der Peak robust ist oder durch Rauschen entsteht.
        dominant_period_ci = None
        if peak_indices and len(autocorr_smoothed) > 20:
            n_boot = 500
            boot_peaks = []
            ac_len = len(autocorr_smoothed)
            rng_boot = np.random.default_rng(42)
            for _ in range(n_boot):
                idx_boot = rng_boot.integers(0, ac_len, ac_len)
                ac_boot  = autocorr_smoothed[idx_boot]
                pk_boot, _ = find_peaks(ac_boot, height=std_val * 1.5, distance=5)
                if len(pk_boot) > 0:
                    boot_peaks.append(float(ac_boot[pk_boot[0]]))
            if len(boot_peaks) > 10:
                ci_lo, ci_hi = float(np.percentile(boot_peaks, 2.5)), float(np.percentile(boot_peaks, 97.5))
                dominant_period_ci = [ci_lo, ci_hi]
    else:
        dominant_period = None
        dominant_period_ci = None

    return {
        "method":             "Autokorrelation",
        "analyzed_bases":     len(seq_small),
        "dominant_period":    dominant_period,
        "dominant_period_ci": dominant_period_ci,   # 95%-CI via Bootstrap
        "peak_count":         len(peak_indices),
        "peaks": list(zip(peak_indices[:10], peak_values[:10])) if peak_indices else [],
        "autocorr_values": autocorr[:max_lag].tolist() if max_lag > 0 else []
    }

def analyze_gc_content(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """GC-content variation analysis with periodicity search."""
    if log_callback:
        log_callback(t("analysis.analysing_gc_content"))
    
    window_size = CONFIG.gc_window_size
    step = CONFIG.gc_step_size
    gc_values = []
    positions = []
    
    for i in range(0, len(seq) - window_size, step):
        window = seq[i:i+window_size]
        gc = (window.count('G') + window.count('C')) / window_size * 100
        gc_values.append(gc)
        positions.append(i)
    
    if not gc_values:
        return {"error": t("analysis.no_windows_analysed")}
    
    mean_gc = np.mean(gc_values)
    std_gc = np.std(gc_values)
    min_gc = np.min(gc_values)
    max_gc = np.max(gc_values)
    
    # Search for periodicity in GC content
    dominant_gc_period = None
    gc_period_strength = None
    
    if len(gc_values) > 100:
        gc_array = np.array(gc_values) - mean_gc
        autocorr_gc = np.correlate(gc_array, gc_array, mode='full')
        autocorr_gc = autocorr_gc[len(autocorr_gc)//2:]
        
        from scipy.signal import find_peaks
        max_lag = min(500, len(autocorr_gc))
        peaks, _ = find_peaks(autocorr_gc[:max_lag], 
                             height=np.std(autocorr_gc[10:max_lag]) * 1.5,
                             distance=5)
        
        if len(peaks) > 0:
            dominant_gc_period = peaks[0] * step
            gc_period_strength = float(autocorr_gc[peaks[0]] / autocorr_gc[0]) if autocorr_gc[0] > 0 else 0
    
    return {
        "method": "GC-Content-Variation",
        "window_size": window_size,
        "step_size": step,
        "windows_analyzed": len(gc_values),
        "mean_gc_percent": float(mean_gc),
        "std_gc_percent": float(std_gc),
        "min_gc_percent": float(min_gc),
        "max_gc_percent": float(max_gc),
        "gc_range": float(max_gc - min_gc),
        "dominant_period_bp": dominant_gc_period,
        "period_strength": gc_period_strength,
        "gc_values": gc_values[:1000]  # First 1000 values for plots
    }

def analyze_dinucleotide(seq: str, log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Dinucleotide bias analysis (4x4 transition matrix) with statistical tests."""
    if log_callback:
        log_callback(t("analysis.computing_dinucleotide"))

    # Downsampling
    step = max(1, len(seq) // 200000)
    seq_small = seq[::step][:200000]

    if len(seq_small) < 2:
        return {"error": f"Sequence too short for dinucleotide analysis ({len(seq_small)} bp)"}

    bases = ['A', 'C', 'T', 'G']
    matrix = {b1: {b2: 0 for b2 in bases} for b1 in bases}

    for i in range(len(seq_small) - 1):
        b1 = seq_small[i]
        b2 = seq_small[i+1]
        if b1 in bases and b2 in bases:
            matrix[b1][b2] += 1

    # Normalisieren
    for b1 in bases:
        total = sum(matrix[b1].values())
        if total > 0:
            for b2 in bases:
                matrix[b1][b2] = matrix[b1][b2] / total

    # Expected values (based on base frequency)
    base_counts = {b: seq_small.count(b) for b in bases}
    total = sum(base_counts.values())

    if total == 0:
        return {"error": "No valid bases in sequence"}

    base_freq = {b: base_counts[b] / total for b in bases}

    # Check that all bases are present (min. 1 occurrence)
    missing = [b for b in bases if base_counts[b] == 0]
    if missing:
        if log_callback:
            log_callback(t("analysis.missing_bases_skipped", bases=missing))

    expected = {}
    observed = {}
    deviation = {}
    chi_square_contributions = {}

    for b1 in bases:
        for b2 in bases:
            key = f"{b1}{b2}"
            exp_val = base_freq[b1] * base_freq[b2]
            expected[key] = exp_val
            observed[key] = matrix[b1][b2]

            if exp_val > 0:
                deviation[key] = observed[key] / exp_val
                chi_square_contributions[key] = (observed[key] - exp_val) ** 2 / exp_val
            else:
                deviation[key] = 0.0
                chi_square_contributions[key] = 0.0

    # Chi-Quadrat-Test (nur wenn alle Basen vorhanden)
    chi_square = sum(chi_square_contributions.values())
    df = (len(bases) - 1) ** 2  # 9 Freiheitsgrade
    if not missing:
        from scipy.stats import chi2
        p_value = float(1 - chi2.cdf(chi_square, df))
        chi_significant = bool(p_value < 0.05)
    else:
        p_value = None
        chi_significant = None

    return {
        "method": t("methods.dinucleotide"),
        "analyzed_bases": len(seq_small),
        "missing_bases": missing,
        "transition_matrix": {b1: {b2: matrix[b1][b2] for b2 in bases} for b1 in bases},
        "deviation_from_random": deviation,
        "chi_square_test": {
            "statistic": float(chi_square),
            "degrees_of_freedom": int(df),
            "p_value": p_value,
            "significant": chi_significant
        },
        "base_frequencies": base_freq
    }

def _get_species_optimal_delta(accession: str) -> Tuple[float, str, Optional[Dict]]:
    """
    Reads the individually optimised Δ AND the associated frequency scheme
    from the most recent Δ-optimisation JSON.

    Lookup is by ACCESSION — language-independent and stable across sessions.

    Returns: (delta, source, freq_map)
        delta    - optimal Δ for this species
        source   - "optimized" | "default"
        freq_map - frequency assignment of optimal scheme (None = BASE_TO_FREQ)
    """
    try:
        delta_files = sorted(
            CONFIG.results_dir.glob("delta_optimization*.json"),
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        for json_file in delta_files:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for r in data.get("species", []):
                # Match by accession (language-independent) — fallback to name for legacy files
                if r.get("accession") == accession or r.get("name") == accession:
                    opt    = r.get("optimal_delta")
                    scheme = r.get("optimal_scheme")
                    if opt is not None:
                        fmap = FREQUENCY_SCHEMES.get(scheme) if scheme else None
                        return float(opt), "optimized", fmap
                    else:
                        return 2.0, t("analysis.default_no_signal"), None
    except Exception:
        pass
    return 2.0, "default", None


def run_method(method_id: str, seq: str,
               log_callback: Optional[Callable] = None,
               species_name: Optional[str] = None,
               accession: Optional[str] = None) -> Dict[str, Any]:
    """
    Runs the selected method and enriches with scientific context.

    Parameters:
        species_name - Optional. If provided, loads the individually optimised
                       Δ + scheme from Δ-optimisation for two_thz and piano_roll.
    """
    # ── Methoden-Dispatch ────────────────────────────────────────────────────
    if method_id == "two_thz":
        if accession:
            delta, delta_source, freq_map = _get_species_optimal_delta(accession)
        elif species_name:
            delta, delta_source, freq_map = _get_species_optimal_delta(species_name)
        else:
            delta, delta_source, freq_map = 2.0, "default", None
        if log_callback:
            icon   = "🎯" if delta_source == "optimized" else "📐"
            scheme = next((k for k,v in FREQUENCY_SCHEMES.items() if v == freq_map), "standard") if freq_map else "standard"
            log_callback(t("analysis.delta_icon_log", icon=icon, delta=delta, source=delta_source, scheme=scheme))
        result = analyze_two_thz(seq, log_callback, delta=delta, freq_map=freq_map)
        result["delta_source"]  = delta_source
        result["delta_applied"] = delta

    elif method_id == "piano_roll":
        if accession:
            delta, delta_source, _ = _get_species_optimal_delta(accession)
        elif species_name:
            delta, delta_source, _ = _get_species_optimal_delta(species_name)
        else:
            delta, delta_source = 2.0, "default"
        result = analyze_piano_roll(seq, log_callback)
        result["delta_source"]  = delta_source
        result["delta_applied"] = delta

    else:
        method_map = {
            "fibonacci":   analyze_fibonacci,
            "golden_ratio": analyze_golden_ratio,
            "power_law":   analyze_power_law,
            "cgr":         analyze_cgr,
            "autocorr":    analyze_autocorr,
            "gc_content":  analyze_gc_content,
            "dinucleotide": analyze_dinucleotide,
        }
        if method_id not in method_map:
            return {"error": t("analysis.unknown_method", method_id=method_id)}
        result = method_map[method_id](seq, log_callback)

    if result and "error" not in result:
        result = enrich_with_scientific_context(result, method_id)

    return result


# ============================================================
# SCIENTIFIC CONTEXT AND TRANSPARENCY HELPERS
# ============================================================

_SCIENTIFIC_CONTEXTS: Dict[str, Dict] = {
    "two_thz": {
        "display_name":     "Difference Spectrum (Δ=2.0)",
        "biological_basis": "Differenz der zugewiesenen Frequenzwerte (48.5-51.5 THz) – "
                            "purely mathematical convention, not a measured physical quantity. "
                            "The term 'THz' is physically misleading; DNA dynamics "
                            "spielt sich im GHz-Bereich ab.",
        "literature":       [],
        "caveats":          ["Frequency assignment is arbitrary",
                             "No biophysical validation",
                             "Dynamic threshold (99th percentile) replaces former fixed value of 1000 bp"]
    },
    "fibonacci": {
        "display_name":     "Fibonacci Distances",
        "biological_basis": "Observed in plant phyllotaxis; for linear DNA sequences "
                            "not established. Exploratory method.",
        "literature":       ["Jean, R.V. (1994) Phyllotaxis: A Systemic Study in Plant Morphogenesis"],
        "caveats":          ["Dynamic tolerance (5% base) more precise than former 10% fixed tolerance",
                             "Permutation test is the actual validator"]
    },
    "golden_ratio": {
        "display_name":     "Golden Ratio",
        "biological_basis": "Controversially discussed for DNA sequences.",
        "literature":       ["Perez, J.-C. (2010) Codon populations in single-stranded whole human genome DNA"],
        "caveats":          ["Adaptive Toleranz basiert auf Datenvarianz",
                             "Permutation test shows actual significance"]
    },
    "power_law": {
        "display_name":     "Power-Law Distribution",
        "biological_basis": "Fraktale Organisation von Genomen gut belegt.",
        "literature":       ["Li, W. (1992) Fractal nature of DNA sequences",
                             "Voss, R.F. (1992) Evolution of long-range fractal correlations"],
        "caveats":          ["AIC/BIC nur bei ausreichend Datenpunkten sinnvoll (>10)"]
    },
    "cgr": {
        "display_name":     "CGR (Chaos Game Representation)",
        "biological_basis": "Established method for genome comparison and pattern recognition.",
        "literature":       ["Jeffrey, H.J. (1990) Chaos game representation of gene structure"],
        "caveats":          ["Fractal dimension depends on sequence length",
                             "Mustererkennung bleibt explorativ"]
    },
    "piano_roll": {
        "display_name":     "Frequenzprofil",
        "biological_basis": "Visualisation of base sequence as frequency-over-position. "
                            "The frequency assignment (48.5–51.5 THz) is a mathematical convention.",
        "literature":       [],
        "caveats":          ["Frequency values are not measured physical quantities",
                             "Musikalische Metapher ohne direkte biologische Basis"]
    },
    "autocorr": {
        "display_name":     "Autocorrelation (Periodicity)",
        "biological_basis": "Standard method for periodicity detection in time series.",
        "literature":       [],
        "caveats":          ["Dominant period of 2 bp corresponds to base-pair level – trivial",
                             "Bootstrap-KI zeigt Robustheit des dominanten Peaks"]
    },
    "gc_content": {
        "display_name":     "GC-Content Variation",
        "biological_basis": "Standard genomics metric with broad literature support.",
        "literature":       [],
        "caveats":          ["Window size (1000 bp) influences periodicity detection"]
    },
    "dinucleotide": {
        "display_name":     "Dinucleotide Bias",
        "biological_basis": "Established for CpG island analysis and DNA flexibility.",
        "literature":       ["Satchwell et al. (1986) Sequence periodicities in chicken nucleosome core DNA"],
        "caveats":          ["Chi²-Test setzt alle Basen als vorhanden voraus"]
    },
}


def enrich_with_scientific_context(result: Dict[str, Any], method_id: str) -> Dict[str, Any]:
    """Adds scientific context, interpretation aids and significance notes."""
    ctx = _SCIENTIFIC_CONTEXTS.get(method_id, {})
    result["scientific_context"] = ctx

    # Automatische Interpretation der Signifikanz
    sig = result.get("statistical_significance", {})
    if sig:
        p = sig.get("p_value")
        if p is not None:
            if p < 0.05:
                interp = t("analysis.stat_significant", p=p)
            elif p < 0.10:
                interp = t("analysis.stat_exploratory", p=p)
            else:
                interp = t("analysis.not_significant", p=p)
            result["statistical_significance"]["interpretation"] = interp
            result["statistical_significance"]["permutations"] = CONFIG.significance_permutations

    return result


def bootstrap_ci(data: np.ndarray, statistic_fn,
                  n_bootstrap: int = 500, seed: int = 42) -> Dict[str, float]:
    """
    Calculates 95% bootstrap confidence interval for an arbitrary statistic.
    Anwendbar auf Power-Law-Exponenten, CGR-Fraktaldimension, etc.
    """
    rng = np.random.default_rng(seed)
    values = []
    n = len(data)
    for _ in range(n_bootstrap):
        sample = data[rng.integers(0, n, n)]
        try:
            values.append(float(statistic_fn(sample)))
        except Exception:
            pass
    if len(values) < 10:
        return {"ci_lower": None, "ci_upper": None,
                "bootstrap_mean": None, "bootstrap_std": None}
    return {
        "ci_lower":        float(np.percentile(values, 2.5)),
        "ci_upper":        float(np.percentile(values, 97.5)),
        "bootstrap_mean":  float(np.mean(values)),
        "bootstrap_std":   float(np.std(values)),
    }


def normalize_metric_per_10kb(value: float, seq_length: int, method_id: str) -> Optional[float]:
    """
    Normalises count metrics to 10,000 bp for species comparison.
    Only meaningful for additive count metrics (transitions, matches etc.).
    Nicht angewendet auf Exponenten, Korrelationen oder Dimensionen.
    """
    if value is None or seq_length <= 0:
        return None
    _NORMALIZABLE = {"two_thz", "fibonacci", "golden_ratio"}
    if method_id in _NORMALIZABLE:
        return float(value / seq_length * 10_000)
    return None   # Nicht normalisierbar (Exponent, Dimension etc.)

# ============================================================
# 3D-DNA-REKONSTRUKTION
# ============================================================

@dataclass
class DNAGeometry:
    """Physical parameters der B-DNA-Doppelhelix"""
    bp_per_turn:         float = 10.5   # Basenpaare pro Windung
    rise_per_bp:         float = 0.34   # nm – vertikaler Abstand
    radius:              float = 1.0    # nm – Helix-Radius
    base_tilt_deg:       float = 6.0    # ° – Basen-Neigung
    propeller_twist_deg: float = 15.0   # ° – Propeller-Twist

# Base-specific displacements (nm) – Roll/Tilt/Shift approximations
_BASE_OFFSETS: Dict[str, np.ndarray] = {
    'A': np.array([ 0.02,  0.01,  0.003]),
    'T': np.array([-0.02, -0.01, -0.003]),
    'C': np.array([ 0.01, -0.01,  0.001]),
    'G': np.array([-0.01,  0.01, -0.001]),
}

def reconstruct_3d_dna(sequence: str,
                        geometry: DNAGeometry = None,
                        max_bp: int = 5000) -> Tuple[np.ndarray, np.ndarray]:
    """
    Reconstructs 3D coordinates of strand-1 backbone from linear sequence.

    Returns:
        coords  – (N, 3) Array, coordinates in nm
        colors  – (N,)   Array, Farb-Index pro Base (0=A,1=T,2=C,3=G)
    """
    if geometry is None:
        geometry = DNAGeometry()

    seq = sequence[:max_bp]
    n   = len(seq)

    coords = np.zeros((n, 3))
    color_map = {'A': 0, 'T': 1, 'C': 2, 'G': 3}
    colors = np.zeros(n, dtype=int)

    angle_per_bp = 2 * np.pi / geometry.bp_per_turn

    for i, base in enumerate(seq):
        angle = i * angle_per_bp
        x = geometry.radius * np.cos(angle)
        y = geometry.radius * np.sin(angle)
        z = i * geometry.rise_per_bp
        off = _BASE_OFFSETS.get(base, np.zeros(3))
        # Verschiebung in lokales coordinatessystem (radial)
        coords[i] = [x + off[0] * np.cos(angle) - off[1] * np.sin(angle),
                     y + off[0] * np.sin(angle) + off[1] * np.cos(angle),
                     z + off[2]]
        colors[i] = color_map.get(base, 0)

    return coords, colors


def _box_count_3d(coords: np.ndarray) -> float:
    """Box-counting fractal dimension in 3D — normalised to unit cube."""
    if len(coords) < 10:
        return 0.0
    mn   = coords.min(axis=0)
    span = coords.max(axis=0) - mn
    max_span = float(np.max(span))
    if max_span < 1e-10:
        return 0.0
    # Normiere auf [0, 1]^3
    pts_norm = (coords - mn) / max_span

    scales, counts = [], []
    for k in range(1, 7):   # box sizes: 0.5, 0.25, 0.125, ...
        bs = 1.0 / (2 ** k)
        bins = np.floor(pts_norm / bs).astype(int)
        unique = len(set(map(tuple, bins.tolist())))
        if unique > 0:
            scales.append(float(np.log(1.0 / bs)))
            counts.append(float(np.log(unique)))
    if len(scales) > 2:
        slope, _ = np.polyfit(scales, counts, 1)
        return float(max(0.0, min(3.0, slope)))   # clamp to [0, 3]
    return 0.0


def analyze_3d_spatial_patterns(coords: np.ndarray,
                                  geometry: DNAGeometry = None,
                                  log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """
    Analyses spatial patterns of the 3D point cloud:
    Golden ratio, Fibonacci, helix periodicity, fractal dim, symmetry.
    """
    if geometry is None:
        geometry = DNAGeometry()

    result: Dict[str, Any] = {}
    n = len(coords)
    golden = 1.618033988749895

    # ── 1. Distances between consecutive bases ───────────────────────────────
    if log_callback:
        log_callback(t("analysis.computing_base_distances"))
    consec_dists = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    result["mean_consec_distance_nm"]   = float(np.mean(consec_dists))
    result["std_consec_distance_nm"]    = float(np.std(consec_dists))
    result["expected_rise_nm"]          = geometry.rise_per_bp

    # ── 2. Golden ratio – ratios of consecutive distances ───────────────────
    if log_callback:
        log_callback(t("analysis.searching_golden_ratio_3d"))
    ratios = consec_dists[1:] / (consec_dists[:-1] + 1e-12)
    golden_mask = np.abs(ratios - golden) / golden < 0.05
    result["golden_ratio_match_rate"]   = float(np.mean(golden_mask))
    result["golden_ratio_count"]        = int(np.sum(golden_mask))
    result["total_ratios"]              = int(len(ratios))

    # ── 3. Fibonacci distances (in bp units along the helix) ─────────────────
    if log_callback:
        log_callback(t("analysis.searching_fibonacci_3d"))
    fib_bp = [5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610, 987]
    # Distances in nm, converted to bp: d / rise_per_bp
    sample = min(n, 2000)
    idx = np.random.choice(n, sample, replace=False) if n > sample else np.arange(n)
    pts_sample = coords[idx]
    # Pairwise distances (nearest neighbours only for performance)
    pair_dists_bp = []
    for i in range(len(pts_sample) - 1):
        d_nm = float(np.linalg.norm(pts_sample[i+1] - pts_sample[i]))
        pair_dists_bp.append(d_nm / geometry.rise_per_bp)

    fib_matches = sum(
        1 for d in pair_dists_bp
        if any(abs(d - f) / f < 0.10 for f in fib_bp)
    )
    result["fibonacci_match_rate_3d"]   = float(fib_matches / len(pair_dists_bp)) if pair_dists_bp else 0.0
    result["fibonacci_match_count_3d"]  = fib_matches

    # ── 4. Helix periodicity: FFT of twist angle, not z ──────────────────────
    if log_callback:
        log_callback(t("analysis.fft_helix"))
    if len(coords) > 100:
        # Calculate den angle jedes pointss um die lokale Achse
        # Approximation: project onto xy-plane relative to sliding midpoint
        window = min(21, len(coords) // 10 * 2 + 1)   # odd window size
        # Sliding average as axis approximation
        from numpy.lib.stride_tricks import sliding_window_view
        half_w = window // 2
        # Einfacher: berechne kumulativen Twist-angle aus consecutive Vektoren
        v = np.diff(coords, axis=0)    # (N-1, 3) — Schrittrichtungen
        # angle zwischen aufeinanderfolgenden Schritten um die Fortschrittsachse
        cross_angles = []
        for k in range(len(v) - 1):
            v1 = v[k]
            v2 = v[k + 1]
            n1 = np.linalg.norm(v1)
            n2 = np.linalg.norm(v2)
            if n1 > 1e-10 and n2 > 1e-10:
                cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
                cross_angles.append(float(np.degrees(np.arccos(cos_a))))
        if len(cross_angles) > 50:
            ca = np.array(cross_angles)
            fft_ca   = np.abs(np.fft.rfft(ca - np.mean(ca)))
            freqs_ca = np.fft.rfftfreq(len(ca))
            # Ignoriere DC und suche Peak zwischen 5 und 20 bp
            mask = (freqs_ca > 1/25) & (freqs_ca < 1/3)
            if np.any(mask):
                peak_in_mask = int(np.argmax(fft_ca[mask]))
                valid_freqs  = freqs_ca[mask]
                dom_freq        = float(valid_freqs[peak_in_mask])
                measured        = float(1.0 / dom_freq) if dom_freq > 0 else None
                expected_period = (geometry.bp_per_turn_mean
                                   if hasattr(geometry, 'bp_per_turn_mean')
                                   else geometry.bp_per_turn) if geometry else 10.5
                # Wenn FFT-Ergebnis > 50 % vom Erwartungswert abweicht → theoretischen Wert nehmen
                if measured and abs(measured - expected_period) / expected_period < 0.5:
                    result["helix_period_bp"]     = measured
                    result["helix_period_source"] = "fft"
                else:
                    result["helix_period_bp"]     = expected_period
                    result["helix_period_source"] = "theoretical"
                result["helix_period_expected"] = expected_period
                result["helix_fft_peak_power"]  = float(fft_ca[mask][peak_in_mask])
            else:
                result["helix_period_bp"] = None

    # ── 5. Fraktale Dimension 3D ──────────────────────────────────────────────
    if log_callback:
        log_callback(t("analysis.box_counting_3d"))
    pts_fd = coords[::max(1, n // 5000)]
    result["fractal_dimension_3d"] = _box_count_3d(pts_fd)

    # ── 6. Rotationssymmetrie: angle distribution um die lokale Helix-Achse ─────
    # Calculate radius of each point relative to sliding midpoint (axis approximation)
    window_size = min(21, n // 5 * 2 + 1)
    half_w = window_size // 2
    local_radii = []
    local_angles = []
    for k in range(half_w, n - half_w):
        center = coords[k - half_w : k + half_w + 1].mean(axis=0)
        local_vec = coords[k] - center
        r_local = float(np.linalg.norm(local_vec[:2]))   # nur xy-Komponente
        local_radii.append(r_local)
        local_angles.append(float(np.arctan2(float(local_vec[1]), float(local_vec[0]))))

    if local_radii:
        result["mean_radius_nm"]  = float(np.mean(local_radii))
        result["std_radius_nm"]   = float(np.std(local_radii))
        result["radius_cv"]       = float(np.std(local_radii) / (np.mean(local_radii) + 1e-12))
        # Angle distribution: uniform → high symmetry
        angle_hist, _ = np.histogram(local_angles, bins=36, range=(-np.pi, np.pi))
        mean_h = float(np.mean(angle_hist))
        std_h  = float(np.std(angle_hist))
        result["rotational_symmetry"] = float(max(0.0, 1.0 - std_h / (mean_h + 1e-12)))
    else:
        result["mean_radius_nm"]      = float(geometry.radius_mean if geometry else 1.0)
        result["std_radius_nm"]       = 0.0
        result["radius_cv"]           = 0.0
        result["rotational_symmetry"] = 0.0

    return result


def build_3d_html(coords: np.ndarray,
                   colors: np.ndarray,
                   sequence: str,
                   species_name: str,
                   spatial_metrics: Dict[str, Any],
                   output_path: Path,
                   geometry: DNAGeometry = None) -> str:
    """
    Erstellt interaktive 3D-HTML-Visualisierung mit Plotly (eingebettet).
    No external server needed – everything inline.
    """
    if geometry is None:
        geometry = DNAGeometry()

    # Farben und Labels
    base_colors_hex = ['#E74C3C', '#27AE60', '#2980B9', '#F39C12']  # A T C G
    base_names      = ['A', 'T', 'C', 'G']
    point_colors = [base_colors_hex[c] for c in colors]

    # Helix-Linie (zentrale Achse ohne Basis-Offset)
    n = len(coords)
    t_arr = np.linspace(0, n * geometry.rise_per_bp, max(n * 2, 200))
    angle_arr = 2 * np.pi * t_arr / (geometry.rise_per_bp * geometry.bp_per_turn)
    hx = geometry.radius * np.cos(angle_arr)
    hy = geometry.radius * np.sin(angle_arr)

    # Downsample points for HTML performance (max 3000)
    step = max(1, n // 3000)
    c_sub  = coords[::step]
    col_sub = [point_colors[i] for i in range(0, n, step)]
    seq_sub = [sequence[i] for i in range(0, n, step)]

    # Metrics-Text
    gr  = spatial_metrics.get("golden_ratio_match_rate", 0)
    fib = spatial_metrics.get("fibonacci_match_rate_3d", 0)
    fd  = spatial_metrics.get("fractal_dimension_3d", 0)
    hp  = spatial_metrics.get("helix_period_bp")
    sym = spatial_metrics.get("rotational_symmetry", 0)
    metrics_text = (f"Golden Ratio: {gr:.3f} | Fibonacci: {fib:.3f} | "
                    f"Fractal Dim: {fd:.3f} | Helix Period: {hp:.1f} bp | "
                    f"Symmetry: {sym:.3f}") if hp else (
                    f"Golden Ratio: {gr:.3f} | Fibonacci: {fib:.3f} | "
                    f"Fractal Dim: {fd:.3f} | Symmetry: {sym:.3f}")

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>3D DNA – {species_name}</title>
<script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:sans-serif; }}
  #plot {{ width:100vw; height:90vh; }}
  #info {{ padding:8px 16px; font-size:12px; background:#1a1a2e; }}
  .legend {{ display:inline-block; margin:0 10px; }}
  .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; }}
</style>
</head>
<body>
<div id="info">
  <b>🧬 {species_name}</b> &nbsp;|&nbsp;
  {len(sequence):,} bp dargestellt &nbsp;|&nbsp;
  {metrics_text}
  &nbsp;&nbsp;
  <span class="legend"><span class="dot" style="background:#E74C3C"></span>A</span>
  <span class="legend"><span class="dot" style="background:#27AE60"></span>T</span>
  <span class="legend"><span class="dot" style="background:#2980B9"></span>C</span>
  <span class="legend"><span class="dot" style="background:#F39C12"></span>G</span>
</div>
<div id="plot"></div>
<script>
var bases = {{
  x: {c_sub[:,0].tolist()},
  y: {c_sub[:,1].tolist()},
  z: {c_sub[:,2].tolist()},
  mode: 'markers',
  type: 'scatter3d',
  marker: {{ size: 2.5, color: {col_sub}, opacity: 0.85 }},
  text: {seq_sub},
  hovertemplate: '%{{text}}<br>(%{{x:.3f}}, %{{y:.3f}}, %{{z:.3f}}) nm<extra></extra>',
  name: 'Basen'
}};
var helix = {{
  x: {hx.tolist()},
  y: {hy.tolist()},
  z: {t_arr.tolist()},
  mode: 'lines',
  type: 'scatter3d',
  line: {{ color: 'rgba(200,200,200,0.25)', width: 2 }},
  name: 'Helix-Achse'
}};
var layout = {{
  paper_bgcolor: '#111',
  plot_bgcolor:  '#111',
  font: {{ color: '#eee' }},
  title: {{ text: '3D-DNA-Rekonstruktion: {species_name}', font: {{ size: 14 }} }},
  scene: {{
    xaxis: {{ title: 'X (nm)', gridcolor:'#333', zerolinecolor:'#555' }},
    yaxis: {{ title: 'Y (nm)', gridcolor:'#333', zerolinecolor:'#555' }},
    zaxis: {{ title: 'Z (nm)', gridcolor:'#333', zerolinecolor:'#555' }},
    bgcolor: '#111',
    aspectmode: 'data'
  }},
  legend: {{ bgcolor:'rgba(0,0,0,0.5)' }},
  margin: {{ l:0, r:0, t:40, b:0 }}
}};
Plotly.newPlot('plot', [bases, helix], layout, {{responsive:true}});
</script>
</body>
</html>"""

    output_path.write_text(html, encoding='utf-8')
    return str(output_path)


def run_3d_reconstruction(species_name: str,
                           species_info: Dict,
                           log_callback: Optional[Callable] = None,
                           open_browser: bool = False) -> Dict[str, Any]:
    """Complete 3D pipeline: load → reconstruct → analyse → save."""
    geometry = DNAGeometry()

    fasta = get_or_fetch_genome(species_info["accession"], log_callback)
    if not fasta:
        return {"error": t("analysis.genome_load_failed")}

    reader = GenomeReader(fasta)
    seq    = reader.get_sequence(CONFIG.max_seq_length)
    if log_callback:
        log_callback(t("analysis.sequence_info_3d", length=len(seq)))

    # Limit to 5000 bp for visualisation (performance)
    seq_vis = seq[:5000]
    coords, colors = reconstruct_3d_dna(seq_vis, geometry)

    if log_callback:
        log_callback(t("analysis.points_calculated_3d", count=len(coords)))

    # Spatial patterns on full sequence (up to max_seq_length, but max 5000 for distances)
    if log_callback:
        log_callback(t("analysis.analysing_spatial"))
    spatial = analyze_3d_spatial_patterns(coords, geometry, log_callback)
    spatial["species"]    = species_name
    spatial["accession"]  = species_info["accession"]
    spatial["group"]      = species_info["group"]
    spatial["seq_length"] = len(seq_vis)
    spatial["timestamp"]  = datetime.now().isoformat()

    # Dateipfade
    safe = (species_name.replace(" ", "_").replace("(", "")
                        .replace(")", "").replace(",", ""))
    html_path = CONFIG.recon3d_dir / f"{safe}_3d.html"
    json_path = CONFIG.recon3d_dir / f"{safe}_spatial_metrics.json"

    # HTML
    build_3d_html(coords, colors, seq_vis, species_name, spatial, html_path, geometry)
    if log_callback:
        log_callback(t("analysis.visualization_3d", filename=html_path.name))

    # JSON
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(spatial, f, indent=2, cls=NumpyEncoder)
    if log_callback:
        log_callback(t("realistic_3d.metrics_saved", filename=json_path.name))

    if log_callback:
        log_callback(f"    Golden Ratio Match: {spatial.get('golden_ratio_match_rate',0):.4f}")
        log_callback(f"    Fibonacci Match:    {spatial.get('fibonacci_match_rate_3d',0):.4f}")
        log_callback(f"    Fraktale Dim (3D):  {spatial.get('fractal_dimension_3d',0):.3f}")
        hp = spatial.get('helix_period_bp')
        log_callback(f"    Helix-period:      {f'{hp:.1f} bp' if hp else 'N/A'}  "
                     f"(erwartet: {geometry.bp_per_turn} bp)")
        log_callback(f"    Rotationssymmetrie: {spatial.get('rotational_symmetry',0):.3f}")

    if open_browser:
        import webbrowser
        webbrowser.open(str(html_path))

    return spatial


# ============================================================
# REALISTISCHE 2D/3D-DNA-REKONSTRUKTION
# ============================================================

@dataclass
class RealisticDNAGeometry:
    """Physical parameters for realistic B-DNA with variability."""
    bp_per_turn_mean:   float = 10.5
    bp_per_turn_std:    float = 0.5
    rise_per_bp_mean:   float = 0.34   # nm
    rise_per_bp_std:    float = 0.02   # nm
    radius_mean:        float = 1.0    # nm
    radius_std:         float = 0.05   # nm
    # Biegung
    bend_amplitude:          float = 8.0   # Grad
    bend_correlation_length: int   = 50    # bp
    # Thermische Fluktuationen
    thermal_amplitude:       float = 0.04  # nm
    thermal_correlation:     int   = 10    # bp
    use_sequence_dependence: bool  = True

# Dinukleotid-Twist (Grad) und Rise (nm) – Olson et al. / 3DNA Daten
_DINUC_TWIST: Dict[str, float] = {
    'AA': 32.0, 'AT': 34.0, 'AC': 33.0, 'AG': 33.5,
    'TA': 34.0, 'TT': 32.0, 'TC': 33.0, 'TG': 33.5,
    'CA': 33.0, 'CT': 33.0, 'CC': 35.0, 'CG': 36.0,
    'GA': 33.5, 'GT': 33.5, 'GC': 36.0, 'GG': 35.0,
}
_DINUC_RISE: Dict[str, float] = {
    'AA': 0.32, 'AT': 0.34, 'AC': 0.33, 'AG': 0.33,
    'TA': 0.34, 'TT': 0.32, 'TC': 0.33, 'TG': 0.33,
    'CA': 0.33, 'CT': 0.33, 'CC': 0.35, 'CG': 0.36,
    'GA': 0.33, 'GT': 0.33, 'GC': 0.36, 'GG': 0.35,
}
_DINUC_ROLL: Dict[str, float] = {
    'AA': -2.0, 'AT': -1.5, 'AC': -1.0, 'AG': -1.0,
    'TA':  2.0, 'TT':  1.5, 'TC':  1.0, 'TG':  1.0,
    'CA':  1.0, 'CT':  0.5, 'CC':  0.5, 'CG':  1.0,
    'GA': -1.0, 'GT': -0.5, 'GC': -0.5, 'GG': -0.5,
}
_DINUC_TILT: Dict[str, float] = {
    'AA':  3.0, 'AT':  2.0, 'AC':  1.5, 'AG':  2.0,
    'TA': -3.0, 'TT': -2.0, 'TC': -1.5, 'TG': -2.0,
    'CA': -1.0, 'CT': -0.5, 'CC': -0.5, 'CG': -1.0,
    'GA':  1.0, 'GT':  0.5, 'GC':  0.5, 'GG':  0.5,
}


def _correlated_noise(n: int, std: float, corr_len: int,
                       rng: np.random.Generator) -> np.ndarray:
    """
    Ornstein-Uhlenbeck-like correlated noise.
    corr_len determines the decay length (in bp).
    """
    alpha = 1.0 - 1.0 / max(corr_len, 1)
    noise = np.zeros(n)
    noise[0] = rng.normal(0, std)
    sigma_drive = std * np.sqrt(1 - alpha ** 2)
    for i in range(1, n):
        noise[i] = alpha * noise[i - 1] + rng.normal(0, sigma_drive)
    return noise


def _rotation_matrix_axis(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rodrigues-Formel: Rotationsmatrix um beliebige Achse"""
    ax = axis / (np.linalg.norm(axis) + 1e-15)
    c, s = np.cos(angle_rad), np.sin(angle_rad)
    t = 1 - c
    x, y, z = ax
    return np.array([
        [t*x*x + c,   t*x*y - s*z, t*x*z + s*y],
        [t*x*y + s*z, t*y*y + c,   t*y*z - s*x],
        [t*x*z - s*y, t*y*z + s*x, t*z*z + c  ],
    ])



# ============================================================
# HELPER FUNCTIONS FOR PHYSICALLY CORRECT DNA PARAMETERS
# ============================================================

# Dinucleotide flexibility from DNase I sensitivity (Satchwell 1986, normalised to [0,1])
# Niedrige Werte = steif (GC-reich), hohe Werte = biegsam (AT-reich)
_DINUC_BENDABILITY: Dict[str, float] = {
    'AA': 0.50, 'AT': 0.80, 'AC': 0.40, 'AG': 0.40,
    'TA': 0.70, 'TT': 0.50, 'TC': 0.40, 'TG': 0.40,
    'CA': 0.30, 'CT': 0.30, 'CC': 0.20, 'CG': 0.20,
    'GA': 0.40, 'GT': 0.40, 'GC': 0.20, 'GG': 0.20,
}


def get_bendability_profile(seq: str, window: int = 5) -> np.ndarray:
    """
    Local flexibility profile from dinucleotide values (smoothed).
    Niedrige Werte = steifere Region, hohe Werte = biegsamere Region.
    Quelle: Satchwell et al. (1986), normiert auf [0, 1].
    """
    n = len(seq)
    if n < 2:
        return np.ones(n) * 0.4
    raw = np.array([_DINUC_BENDABILITY.get(seq[i:i+2], 0.4) for i in range(n - 1)])
    # Letzter Wert = Wiederholung des vorletzten
    raw = np.append(raw, raw[-1])
    # Sliding average
    return np.convolve(raw, np.ones(window) / window, mode='same')


def _dinuc_radius(dinuc: str) -> float:
    """
    Sequenzabhaengiger Helix-Radius basierend auf Basenpaar-Stapelung (nm).
    AT-reiche Regionen: kompakter (kleinerer Radius).
    GC-reiche Regionen: steifer, groesserer Radius.
    Quelle: Calladine & Drew, Understanding DNA (1992).
    """
    _RADIUS_MAP: Dict[str, float] = {
        'AA': 0.95, 'TT': 0.95, 'AT': 0.97, 'TA': 0.96,
        'GG': 1.05, 'CC': 1.05, 'GC': 1.06, 'CG': 1.06,
        'AG': 1.00, 'GA': 1.00, 'CT': 1.00, 'TC': 1.00,
        'AC': 0.98, 'CA': 0.98, 'GT': 1.02, 'TG': 1.02,
    }
    return _RADIUS_MAP.get(dinuc, 1.0)


def _get_bend_amplitude(group: str, total_height: float) -> float:
    """
    Gruppen-spezifische Biegungsamplitude der Helix-Achse.
    Bakterien haben weniger Biegung (prokaryotisches Nukleoid, weniger Histone).
    Eukaryoten haben mehr Biegung (Chromatinorganisation, Nukleosome).
    Living fossils: intermediate.
    """
    _GROUP_AMP: Dict[str, float] = {
        "bacteria":     0.05,   # Bakterien: steiferes Nukleoid
        "eukaryote":    0.12,   # eukaryotes: Chromatinfaltung
        "living_fossil": 0.08,  # Living fossils: intermediate
    }
    fraction = _GROUP_AMP.get(group, 0.10)
    return total_height * fraction


def _gc_radius_profile(sequence: str, window: int = 10) -> np.ndarray:
    """
    Lokaler GC-Gehalt beeinflusst den Helix-Radius (Fenstermittelung).
    GC-reiche DNA: steifer, groesserer Durchmesser.
    AT-reiche DNA: flexibler, kleinerer Durchmesser.
    Radius = 0.95 bei 0% GC, 1.05 bei 100% GC.
    """
    n = len(sequence)
    seq_arr = np.array(list(sequence))
    is_gc   = (seq_arr == 'G') | (seq_arr == 'C')
    # Gleichgewichtetes gleitendes Fenster (reflect-Padding fuer Randbehandlung)
    gc_frac = np.convolve(is_gc.astype(float),
                          np.ones(window) / window,
                          mode='same')
    return 0.95 + 0.10 * gc_frac   # [0.95, 1.05] nm


def reconstruct_realistic_3d_dna(
    sequence:        str,
    geometry:        RealisticDNAGeometry = None,
    include_bending: bool = True,
    include_thermal: bool = True,
    seed:            int  = 42,
    max_bp:          int  = 5000,
    group:           str  = "eukaryote",
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Physikalisch korrekte 3D-DNA-Rekonstruktion (Frenet-Serret + Paralleltransport).

    Korrekturen gemaess technischer Analyse (Dokument 3):
      1. Sequenzabhaengiger Radius via _dinuc_radius() und _gc_radius_profile()
      2. Gruppen-spezifische Biegungsamplitude via _get_bend_amplitude()
      3. Drift-Korrektur des kumulativen Twists (lineare Verteilung der Abweichung)
      4. Paralleltransport des Frenet-Serret Rahmens (stabil, Radius exakt)
      5. Anisotrope thermische Fluktuationen senkrecht zur Tangente

    Parameter:
        group - Spezies-Gruppe ('bacteria', 'eukaryote', 'living_fossil')
                beeinflusst Biegungsamplitude der Helix-Achse

    Returns:
        coords  - (N, 3) float64 in nm
        colors  - (N,)   int   0=A 1=T 2=C 3=G
    """
    if geometry is None:
        geometry = RealisticDNAGeometry()

    rng = np.random.default_rng(seed)
    seq = sequence[:max_bp]
    n   = len(seq)

    color_map = {'A': 0, 'T': 1, 'C': 2, 'G': 3}
    colors = np.array([color_map.get(b, 0) for b in seq], dtype=int)

    # ── 1. Kumulativer Twist aus Dinukleotid-Parametern + Drift-Korrektur ─────
    # Drift-Korrektur: lineare Verteilung der Abweichung vom Idealwert.
    # Ohne Korrektur koennen bei AT-reichen Sequenzen (Twist ~32°) vs.
    # GC-reichen (Twist ~36°) nach 1000 bp bis zu 2 volle Windungen abweichen.
    cum_twist = np.zeros(n)
    theta = 0.0
    for i in range(n):
        cum_twist[i] = theta
        dinuc = seq[i:i+2] if i + 1 < n else seq[i] + seq[i]
        if geometry.use_sequence_dependence:
            twist_deg = _DINUC_TWIST.get(dinuc, 34.0)
        else:
            twist_deg = 360.0 / geometry.bp_per_turn_mean
        theta += np.radians(twist_deg)

    # Drift-Korrektur: Gesamttwist auf idealen Wert normieren
    expected_total = n * np.radians(360.0 / geometry.bp_per_turn_mean)  # ~34.3° * n
    actual_total   = theta
    drift_per_bp   = (expected_total - actual_total) / max(n, 1)
    # Linear auf alle Positionen verteilen (i=0: kein Drift; i=n-1: voller Drift)
    cum_twist += np.arange(n) * drift_per_bp

    # ── 2. Sequenzabhaengiger radius-Profil ───────────────────────────────────
    radius_profile = _gc_radius_profile(seq, window=10)   # (n,) Array

    # ── 3. Helix-Achse: Supercoiling als Summe von Sinuswellen ───────────────
    rise_mean    = geometry.rise_per_bp_mean
    t_arr        = np.arange(n, dtype=float) * rise_mean
    total_height = float(t_arr[-1]) if n > 1 else rise_mean

    if include_bending:
        # Gruppen-spezifische Gesamtamplitude (Bakterien < eukaryotes)
        total_amp = _get_bend_amplitude(group, total_height)
        bend_modes = [
            {"period": max(n * 0.40, 20), "amp_ratio": 0.40},  # lange Boegen
            {"period": max(n * 0.15, 15), "amp_ratio": 0.30},  # mittlere Boegen
            {"period": max(n * 0.06, 10), "amp_ratio": 0.20},  # kurze Boegen
            {"period": max(n * 0.025, 5), "amp_ratio": 0.10},  # lokales Rauschen
        ]
        # Sequenzabhaengige flexibility: AT-reiche Regionen biegen sich staerker,
        # GC-reiche Regionen sind steifer (Persistenzlaenge B-DNA: ~150 bp = 50 nm).
        bendability = get_bendability_profile(seq, window=min(15, max(3, n // 20)))
        # Normiert auf [0.5, 1.5] um lokale Amplitude zu modulieren
        bend_scale  = 0.5 + bendability  # [0.5, 1.5]

        axis_x = np.zeros(n); axis_y = np.zeros(n)
        for mode in bend_modes:
            period  = mode["period"]
            amp     = total_amp * mode["amp_ratio"]
            phase_x = rng.uniform(0, 2 * np.pi)
            phase_y = rng.uniform(0, 2 * np.pi)
            wave_x  = amp * np.sin(2 * np.pi * t_arr / period + phase_x)
            wave_y  = amp * np.sin(2 * np.pi * t_arr / period + phase_y)
            axis_x += wave_x * bend_scale
            axis_y += wave_y * bend_scale
    else:
        axis_x = np.zeros(n); axis_y = np.zeros(n)

    # ── 4. Tangentenvektoren entlang der Achse ────────────────────────────────
    dx = np.gradient(axis_x)
    dy = np.gradient(axis_y)
    dz = np.full(n, rise_mean)
    tangent = np.column_stack([dx, dy, dz])
    t_norms = np.linalg.norm(tangent, axis=1, keepdims=True)
    t_norms[t_norms < 1e-12] = 1.0
    tangent /= t_norms

    # ── 5. Lokales coordinatessystem via Paralleltransport ────────────────────
    normal   = np.zeros((n, 3))
    binormal = np.zeros((n, 3))
    T0  = tangent[0]
    ref = np.array([1., 0., 0.]) if abs(T0[0]) < 0.9 else np.array([0., 1., 0.])
    N0  = ref - np.dot(ref, T0) * T0
    N0 /= np.linalg.norm(N0)
    normal[0]   = N0
    binormal[0] = np.cross(T0, N0)
    binormal[0] /= np.linalg.norm(binormal[0])

    for i in range(1, n):
        T = tangent[i]
        N = normal[i-1] - np.dot(normal[i-1], T) * T
        n_len = np.linalg.norm(N)
        if n_len < 1e-10:
            N = np.cross(binormal[i-1], T)
            n_len = np.linalg.norm(N)
            if n_len < 1e-10:
                N = normal[i-1]; n_len = 1.0
        N /= n_len
        B = np.cross(T, N)
        B /= (np.linalg.norm(B) + 1e-15)
        normal[i]   = N
        binormal[i] = B

    # ── 6. Thermische Fluktuationen (anisotrop, senkrecht zur Tangente) ───────
    if include_thermal:
        amp = geometry.thermal_amplitude
        therm_raw = np.column_stack([
            _correlated_noise(n, amp,       geometry.thermal_correlation, rng),
            _correlated_noise(n, amp,       geometry.thermal_correlation, rng),
            _correlated_noise(n, amp * 0.3, geometry.thermal_correlation, rng),
        ])
        # Tangentialkomponente entfernen (physikalisch: kein Rauschen entlang Achse)
        t_dot = np.sum(therm_raw * tangent, axis=1, keepdims=True)
        therm = therm_raw - t_dot * tangent
    else:
        therm = np.zeros((n, 3))

    # ── 7. Basiskoordinaten assemblieren ─────────────────────────────────────
    coords = np.zeros((n, 3))
    for i in range(n):
        N      = normal[i]; B = binormal[i]
        angle  = cum_twist[i]
        # Sequenzabhaengiger radius: Dinukleotid-Wert gewichtet mit GC-Profil
        dinuc  = seq[i:i+2] if i + 1 < n else seq[i] + seq[i]
        r_dinuc = _dinuc_radius(dinuc)
        r_gc    = float(radius_profile[i])
        radius  = (r_dinuc + r_gc) / 2.0   # average beider Korrekturen
        offset  = radius * (np.cos(angle) * N + np.sin(angle) * B)
        axis_pos = np.array([axis_x[i], axis_y[i], t_arr[i]])
        coords[i] = axis_pos + offset + therm[i]

    return coords, colors
def project_2d_dna(coords: np.ndarray) -> np.ndarray:
    """
    Zylindrische Abwicklung der 3D-Helix.
    X → angle (rad), Y → height Z (nm)
    """
    angles  = np.arctan2(coords[:, 1], coords[:, 0])
    heights = coords[:, 2]
    return np.column_stack([angles, heights])


def analyze_2d_patterns(coords_2d: np.ndarray,
                         sequence:  str,
                         log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """patternserkennung in der 2D-Abwicklung"""
    angles  = coords_2d[:, 0]
    heights = coords_2d[:, 1]
    result: Dict[str, Any] = {}

    # 1. angle-periodicity
    if len(angles) > 100:
        fft_a    = np.abs(np.fft.rfft(angles - np.mean(angles)))
        freqs_a  = np.fft.rfftfreq(len(angles))
        peak_a   = int(np.argmax(fft_a[1:]) + 1)
        dom_freq = float(freqs_a[peak_a])
        result["angle_dominant_period_bp"] = float(1.0 / dom_freq) if dom_freq > 0 else None
        result["angle_fft_peak_power"]     = float(fft_a[peak_a])

    # 2. Height periodicity
    if len(heights) > 100:
        fft_h   = np.abs(np.fft.rfft(heights - np.mean(heights)))
        freqs_h = np.fft.rfftfreq(len(heights))
        peak_h  = int(np.argmax(fft_h[1:]) + 1)
        dom_h   = float(freqs_h[peak_h])
        result["height_dominant_period_bp"] = float(1.0 / dom_h) if dom_h > 0 else None

    # 3. Golden ratio in height distances (consecutive pairs)
    h_dists = np.abs(np.diff(heights))
    h_dists = h_dists[h_dists > 1e-6]
    if len(h_dists) > 1:
        ratios  = h_dists[1:] / h_dists[:-1]
        golden  = 1.618033988749895
        gm      = float(np.mean(np.abs(ratios - golden) / golden < 0.05))
        result["golden_ratio_match_2d"] = gm

    # 4. Autokorrelation der angleserie (Wiederholungsstruktur)
    if len(angles) > 50:
        a_centered = angles - np.mean(angles)
        ac = np.correlate(a_centered, a_centered, mode='full')
        ac = ac[len(ac)//2:]
        ac_norm = ac / (ac[0] + 1e-12)
        result["angle_autocorr_peak1"] = float(ac_norm[1]) if len(ac_norm) > 1 else None

    # 5. Fraktale Dimension 2D (Box-Counting)
    pts = coords_2d
    mn, mx = pts.min(0), pts.max(0)
    span   = float(np.max(mx - mn)) or 1.0
    scales2, counts2 = [], []
    for k in range(2, 8):
        bs = span / (2 ** k)
        boxes = set(tuple(((pts - mn) / bs).astype(int).tolist()[i]) for i in range(len(pts)))
        if boxes:
            scales2.append(float(np.log(1.0 / bs)))
            counts2.append(float(np.log(len(boxes))))
    if len(scales2) > 2:
        slope2, _ = np.polyfit(scales2, counts2, 1)
        result["fractal_dimension_2d"] = float(-slope2)

    return result


def _js_list(lst: list) -> str:
    """Serialisiert eine Python-Liste als JavaScript-Array.
    Konvertiert Python None → JavaScript null (vermeidet JS-Fehler im Plotly-Code)."""
    import json as _json
    return _json.dumps(lst)


def build_realistic_html(coords:      np.ndarray,
                          colors:      np.ndarray,
                          sequence:    str,
                          species_name: str,
                          metrics_3d:  Dict[str, Any],
                          metrics_2d:  Dict[str, Any],
                          bonds:       List[Dict],
                          histones:    List[Dict],
                          disulfides:  List[Dict],
                          hbond_metrics: Dict[str, Any],
                          output_path: Path) -> str:
    """
    Complete integrated 3D-HTML with:
    - DNA-Basen (farbig nach A/T/C/G)
    - H-bonds (A-T cyan, C-G lime)
    - Histon-Oktamere (lila Kugeln)
    - Disulfide bridges (orange lines)
    - Alle Metriken in der Info-Leiste
    - Sichtbarkeits-Checkboxen pro Layer
    """
    base_hex = ['#E74C3C', '#27AE60', '#2980B9', '#F39C12']
    n        = len(coords)

    # ── DNA-points (max 3000 for performance) ───────────────────────────────
    step    = max(1, n // 3000)
    c_sub   = coords[::step]
    col_sub = [base_hex[colors[i]] for i in range(0, n, step)]
    seq_sub = [sequence[i] for i in range(0, n, step)]

    # ── H-bonds: AT (cyan) and CG (lime), max 600 per type ─────────────────
    wc = [b for b in bonds if b["is_watson_crick"]]
    at_bonds = [b for b in wc if b["num_hbonds"] == 2]
    cg_bonds = [b for b in wc if b["num_hbonds"] == 3]
    bstep_at = max(1, len(at_bonds) // 600)
    bstep_cg = max(1, len(cg_bonds) // 600)

    # Strand-2 coordinates: opposite side of the helix axis.
    # Helix axis = sliding average of coordinates over ~1 period (11 points).
    # Strang2[i] = 2 * Achse[i] - Strang1[i]  (Spiegelung an der Achse)
    _w = 11   # window size ≈ 1 helix period (10.5 bp)
    _kern = np.ones(_w) / _w
    _axis_x = np.convolve(coords[:, 0], _kern, mode='same')
    _axis_y = np.convolve(coords[:, 1], _kern, mode='same')

    def _strand2_pos(i_):
        """Strang-2 = Spiegelung von Strang-1 an der Helix-Achse."""
        if i_ >= n:
            return None, None, None
        x2 = float(2.0 * _axis_x[i_] - coords[i_, 0])
        y2 = float(2.0 * _axis_y[i_] - coords[i_, 1])
        z2 = float(coords[i_, 2])
        return x2, y2, z2

    at_x, at_y, at_z = [], [], []
    for b in at_bonds[::bstep_at]:
        i_ = b["i"]
        if i_ < n:
            x2, y2, z2 = _strand2_pos(i_)
            if x2 is not None:
                at_x += [float(coords[i_, 0]), x2, None]
                at_y += [float(coords[i_, 1]), y2, None]
                at_z += [float(coords[i_, 2]), z2, None]

    cg_x, cg_y, cg_z = [], [], []
    for b in cg_bonds[::bstep_cg]:
        i_ = b["i"]
        if i_ < n:
            x2, y2, z2 = _strand2_pos(i_)
            if x2 is not None:
                cg_x += [float(coords[i_, 0]), x2, None]
                cg_y += [float(coords[i_, 1]), y2, None]
                cg_z += [float(coords[i_, 2]), z2, None]

    # ── Histone ──────────────────────────────────────────────────────────────
    if histones:
        hpos  = np.array([h["center"] for h in histones])
        h_txt = [f"Nukleosom {h['id']}<br>bp {h['bp_start']}-{h['bp_end']}<br>"
                 f"r={h['radius_nm']:.1f} nm" for h in histones]
        histone_trace = (
            "{"
            f"x:{hpos[:,0].tolist()},y:{hpos[:,1].tolist()},z:{hpos[:,2].tolist()},"
            "mode:'markers',type:'scatter3d',"
            "marker:{size:14,color:'#9B59B6',opacity:0.7,"
            "line:{color:'#D2B4DE',width:1}},"
            f"text:{h_txt},"
            "hovertemplate:'%{text}<extra></extra>',"
            "name:'Histon-Oktamer',"
            "visible:true}"
        )
    else:
        histone_trace = (
            "{x:[],y:[],z:[],mode:'markers',type:'scatter3d',"
            "name:'Histon-Oktamer',visible:true}"
        )

    # ── Disulfide bridges ─────────────────────────────────────────────────────
    ds_x: List = []
    ds_y: List = []
    ds_z: List = []
    for d in disulfides:
        ci_ = np.array(histones[d["histone_i"]]["center"])
        cj_ = np.array(histones[d["histone_j"]]["center"])
        ds_x += [float(ci_[0]), float(cj_[0]), None]
        ds_y += [float(ci_[1]), float(cj_[1]), None]
        ds_z += [float(ci_[2]), float(cj_[2]), None]

    # ── Info-Leiste ───────────────────────────────────────────────────────────
    gr   = metrics_3d.get('golden_ratio_match_rate', 0)
    fib  = metrics_3d.get('fibonacci_match_rate_3d', 0)
    fd3  = metrics_3d.get('fractal_dimension_3d', 0)
    fd2  = metrics_2d.get('fractal_dimension_2d', 0)
    sym  = metrics_3d.get('rotational_symmetry', 0)
    hp   = metrics_3d.get('helix_period_bp')
    gc_f = hbond_metrics.get('gc_fraction', 0)
    tot_h = hbond_metrics.get('total_hbonds', 0)
    dg   = hbond_metrics.get('estimated_energy_kcal', 0)

    info = (
        f"GR {gr:.3f} | Fib {fib:.3f} | FD3 {fd3:.3f} | FD2 {fd2:.3f} | "
        f"Sym {sym:.3f}" + (f" | Helix {hp:.1f} bp" if hp else "") +
        f" || GC {gc_f:.1%} | H-bonds {tot_h:,} | ΔG≈{dg:,.0f} kcal/mol | "
        f"Nukleosome {len(histones)} | Disulfide {len(disulfides)}"
    )

    # ── HTML zusammenbauen (keine verschachtelten f-strings) ─────────────────
    html = (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset=\"utf-8\">\n"
        f"<title>Realistic DNA – {species_name}</title>\n"
        "<script src=\"https://cdn.plot.ly/plotly-2.26.0.min.js\"></script>\n"
        "<style>\n"
        "  body{margin:0;background:#0d0d1a;color:#eee;font-family:sans-serif}\n"
        "  #plot{width:100vw;height:86vh}\n"
        "  #info{padding:5px 12px;font-size:11px;background:#12122a;"
        "border-bottom:1px solid #333;line-height:1.8}\n"
        "  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;"
        "margin-right:3px;vertical-align:middle}\n"
        "</style></head><body>\n"
        "<div id=\"info\">\n"
        f"  <b>🧬 {species_name}</b> &nbsp;|&nbsp; {len(sequence):,} bp"
        " &nbsp;|&nbsp; " + info + "<br>\n"
        "  <span><span class=\"dot\" style=\"background:#E74C3C\"></span>A</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#27AE60\"></span>T</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#2980B9\"></span>C</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#F39C12\"></span>G</span> &nbsp;&nbsp;"
        "<span><span class=\"dot\" style=\"background:#00FFFF\"></span>A-T H-bond (2×)</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#00FF7F\"></span>C-G H-bond (3×)</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#9B59B6\"></span>Histon</span> &nbsp;"
        "<span><span class=\"dot\" style=\"background:#F39C12\"></span>Disulfid</span>\n"
        "</div>\n"
        "<div id=\"plot\"></div>\n"
        "<script>\n"
        "var traces = [\n"
        # Trace 0: DNA-Basen
        "  {\n"
        f"    x:{_js_list(c_sub[:,0].tolist())}, y:{_js_list(c_sub[:,1].tolist())}, z:{_js_list(c_sub[:,2].tolist())},\n"
        "    mode:'markers', type:'scatter3d',\n"
        f"    marker:{{size:2.5, color:{_js_list(col_sub)}, opacity:0.85}},\n"
        f"    text:{_js_list(seq_sub)},\n"
        "    hovertemplate:'%{text} (%{x:.2f}, %{y:.2f}, %{z:.2f}) nm<extra></extra>',\n"
        "    name:'DNA-Basen', visible:true\n"
        "  },\n"
        # Trace 1: A-T H-bonds
        f"  {{x:{_js_list(at_x)}, y:{_js_list(at_y)}, z:{_js_list(at_z)},\n"
        "    mode:'lines', type:'scatter3d',\n"
        "    line:{color:'cyan', width:1}, opacity:0.4,\n"
        "    name:'A-T H-bonds (2\u00d7)', visible:true},\n"
        # Trace 2: C-G H-bonds
        f"  {{x:{_js_list(cg_x)}, y:{_js_list(cg_y)}, z:{_js_list(cg_z)},\n"
        "    mode:'lines', type:'scatter3d',\n"
        "    line:{color:'#00FF7F', width:1.5}, opacity:0.5,\n"
        "    name:'C-G H-bonds (3\u00d7)', visible:true},\n"
        # Trace 3: Histone
        f"  {histone_trace},\n"
        # Trace 4: Disulfide bridges
        f"  {{x:{_js_list(ds_x)}, y:{_js_list(ds_y)}, z:{_js_list(ds_z)},\n"
        "    mode:'lines', type:'scatter3d',\n"
        "    line:{color:'#F39C12', width:3}, opacity:0.8,\n"
        "    name:'Disulfide bridges (Cys-Cys)', visible:true}\n"
        "];\n"
        "var layout = {\n"
        "  paper_bgcolor:'#0d0d1a', plot_bgcolor:'#0d0d1a',\n"
        "  font:{color:'#ddd'},\n"
        f"  title:{{text:'Realistische 3D-DNA: {species_name}', font:{{size:13}}}},\n"
        "  scene:{\n"
        "    xaxis:{title:'X (nm)', gridcolor:'#222', zerolinecolor:'#444'},\n"
        "    yaxis:{title:'Y (nm)', gridcolor:'#222', zerolinecolor:'#444'},\n"
        "    zaxis:{title:'Z (nm)', gridcolor:'#222', zerolinecolor:'#444'},\n"
        "    bgcolor:'#0d0d1a', aspectmode:'data'\n"
        "  },\n"
        "  legend:{bgcolor:'rgba(13,13,26,0.8)', bordercolor:'#333',\n"
        "          borderwidth:1, font:{size:10}},\n"
        "  margin:{l:0, r:0, t:36, b:0}\n"
        "};\n"
        "Plotly.newPlot('plot', traces, layout, {responsive:true});\n"
        "</script></body></html>"
    )
    output_path.write_text(html, encoding='utf-8')
    return str(output_path)


def build_2d_unwrapped_plot(coords: np.ndarray,
                              sequence: str,
                              species_name: str,
                              output_path: Path) -> str:
    """2D-Abwicklung als PNG-Plot"""
    coords_2d = project_2d_dna(coords)
    angles  = coords_2d[:, 0]
    heights = coords_2d[:, 1]

    base_colors_map = {'A': '#E74C3C', 'T': '#27AE60', 'C': '#2980B9', 'G': '#F39C12'}
    point_colors = [base_colors_map.get(b, '#aaa') for b in sequence[:len(coords)]]

    fig, axes = plt.subplots(1, 2, figsize=(16, 6),
                              gridspec_kw={'width_ratios': [3, 1]})
    fig.patch.set_facecolor('#0d0d1a')

    # Links: Abwicklung
    ax = axes[0]
    ax.set_facecolor('#0d0d1a')
    step = max(1, len(angles) // 10000)
    ax.scatter(angles[::step], heights[::step],
               c=point_colors[::step], s=0.8, alpha=0.5, rasterized=True)
    ax.set_xlabel(t('analysis.angle_rad_xlabel'), color='#ccc')
    ax.set_ylabel('Height Z (nm)', color='#ccc')
    ax.set_title(t('analysis.unwrapping_title', species=species_name), color='#eee')
    ax.tick_params(colors='#aaa')
    for sp in ax.spines.values():
        sp.set_color('#333')
    # Markiere 2π-periodn
    for k in range(-3, 4):
        ax.axvline(k * np.pi, color='#444', linewidth=0.5, linestyle='--')

    # Right: angle histogram (shows uniformity of rotation)
    ax2 = axes[1]
    ax2.set_facecolor('#0d0d1a')
    ax2.hist(angles, bins=72, color='#4C72B0', edgecolor='none', alpha=0.8,
             orientation='horizontal')
    ax2.set_xlabel('Frequency', color='#ccc')
    ax2.set_title(t('analysis.angle_dist_title'), color='#eee', fontsize=10)
    ax2.tick_params(colors='#aaa')
    for sp in ax2.spines.values():
        sp.set_color('#333')

    # Legende
    from matplotlib.patches import Patch
    legend_elements = [Patch(facecolor=c, label=b)
                       for b, c in base_colors_map.items()]
    axes[0].legend(handles=legend_elements, loc='lower right',
                   facecolor='#1a1a2e', labelcolor='#eee', fontsize=8)

    plt.tight_layout()
    plt.savefig(str(output_path), dpi=150, bbox_inches='tight',
                facecolor='#0d0d1a')
    plt.close(fig)
    return str(output_path)


def run_realistic_reconstruction(species_name:   str,
                                  species_info:   Dict,
                                  log_callback:   Optional[Callable] = None,
                                  open_browser:   bool = False) -> Dict[str, Any]:
    """
    Complete integrated 2D/3D pipeline:
    Realistisches 3D-Modell + H-bonds + Histone + Disulfide bridges
    in einer einzigen HTML-Ausgabe.
    """
    geometry = RealisticDNAGeometry()

    fasta = get_or_fetch_genome(species_info["accession"], log_callback)
    if not fasta:
        return {"error": t("analysis.genome_load_failed")}

    reader  = GenomeReader(fasta)
    seq     = reader.get_sequence(CONFIG.max_seq_length)

    # Visualisations-Sequenz: so viele bp, dass Z-Span ~300 nm erreicht wird.
    # Bei 0.34 nm/bp sind das ~882 bp. Begrenzt auf min(len(seq), 1000).
    # Dadurch ist das Aspect-Ratio (zusammen mit normaliseder Biegung) immer
    # klar darstellbar — ohne manuelle Achsen-Skalierung.
    # Spezies-Unterschiede bleiben sichtbar: kurze Genome < 1000 bp nutzen
    # all available bases; long genomes (eukaryotes) always 1000 bp.
    VIS_BP   = 1000
    seq_vis  = seq[:VIS_BP]
    z_height = len(seq_vis) * 0.34   # nm

    group_id = species_info.get("group", "eukaryote")
    bend_pct = {"bacteria": 5, "eukaryote": 12, "living_fossil": 8}.get(group_id, 10)
    if log_callback:
        log_callback(t("analysis.total_sequence", length=len(seq)))
        log_callback(t("analysis.model_sequence_full", length=len(seq_vis)))
        log_callback(t("realistic_3d.group_info", group=group_id, bend_pct=bend_pct))

    # ── 3D-Rekonstruktion ────────────────────────────────────────────────────
    if log_callback:
        log_callback(t("realistic_3d.reconstructing"))
    group_id = species_info.get("group", "eukaryote")
    coords, col = reconstruct_realistic_3d_dna(seq_vis, geometry,
                                                include_bending=True,
                                                include_thermal=True,
                                                group=group_id)
    if log_callback:
        log_callback(t("analysis.coords_calculated", count=len(coords)))

    # ── H-bonds ────────────────────────────────────────────────────────────
    if log_callback:
        log_callback(t("analysis.computing_hbonds"))
    bonds        = compute_hbonds(seq_vis)
    hbond_metrics = analyze_hbond_stability(seq_vis)
    if log_callback:
        log_callback(t("analysis.gc_hbonds_info", gc=hbond_metrics["gc_fraction"], hbonds=hbond_metrics.get("total_hbonds",0), dg=hbond_metrics.get("estimated_energy_kcal",0)))

    # ── Histone + Disulfide bridges ─────────────────────────────────────────────
    if log_callback:
        log_callback(t("analysis.placing_nucleosomes"))
    histones   = place_histones(coords, nucleosome_spacing=200, dna_per_nucleosome=147)
    disulfides = compute_disulfide_bonds(histones, max_dist_nm=4.0)
    if log_callback:
        log_callback(t("analysis.nucleosome_info", n=len(histones)))

    # ── 2D-Abwicklung ────────────────────────────────────────────────────────
    if log_callback:
        log_callback(t("analysis.projecting_2d"))
    coords_2d = project_2d_dna(coords)

    # ── Spatial patternsanalyse ───────────────────────────────────────────────
    if log_callback:
        log_callback(t("analysis.analysing_spatial_3d2d"))
    metrics_3d = analyze_3d_spatial_patterns(coords, geometry=None,
                                              log_callback=log_callback)
    metrics_2d = analyze_2d_patterns(coords_2d, seq_vis, log_callback)

    # ── Dateipfade ────────────────────────────────────────────────────────────
    safe      = (species_name.replace(" ", "_").replace("(", "")
                             .replace(")", "").replace(",", ""))
    html_path = CONFIG.real3d_dir  / f"{safe}_3d_realistic.html"
    png_path  = CONFIG.real3d_dir  / f"{safe}_2d_unwrapped.png"
    json_path = CONFIG.real3d_dir  / f"{safe}_3d_metrics.json"

    # ── Integrierte HTML (DNA + H-bonds + Histone + Disulfid) ──────────────
    if log_callback:
        log_callback(t("analysis.generating_integrated_3d"))
    build_realistic_html(
        coords, col, seq_vis, species_name,
        metrics_3d, metrics_2d,
        bonds, histones, disulfides, hbond_metrics,
        html_path
    )

    # ── H-bonds-Report im real3d-Ordner ────────────────────────────────────────────
    hbonds_html_path = CONFIG.real3d_dir / f"{safe}_hbonds.html"
    if log_callback:
        log_callback(t("analysis.generating_hbond_html"))
    build_hbonds_html(coords, col, seq_vis, bonds, species_name, hbond_metrics,
                      hbonds_html_path)

    # ── Histone-Report im real3d-Ordner ──────────────────────────────────────────────
    histones_html_path = CONFIG.real3d_dir / f"{safe}_histones.html"
    if log_callback:
        log_callback(t("analysis.generating_histone_html"))
    build_histones_html(coords, col, seq_vis, histones, disulfides, species_name,
                        histones_html_path)

    # ── 2D-PNG ────────────────────────────────────────────────────────────────
    build_2d_unwrapped_plot(coords, seq_vis, species_name, png_path)

    # ── Metriken-JSON ─────────────────────────────────────────────────────────
    all_metrics = {
        "species":        species_name,
        "accession":      species_info["accession"],
        "group":          species_info["group"],
        "seq_length":     len(seq_vis),
        "timestamp":      datetime.now().isoformat(),
        "model_type":     "realistic_frenet_serret_integrated",
        "3d_metrics":     metrics_3d,
        "2d_metrics":     metrics_2d,
        "hbond_metrics":  hbond_metrics,
        "nucleosomes":    len(histones),
        "disulfide_bonds": len(disulfides),
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_metrics, f, indent=2, cls=NumpyEncoder)

    if log_callback:
        log_callback(t("analysis.integrated_html", filename=html_path.name))
        log_callback(t("realistic_3d.hbonds_saved", filename=hbonds_html_path.name))
        log_callback(t("analysis.histone_html", filename=histones_html_path.name))
        log_callback(t("analysis.unwrapping_2d", filename=png_path.name))
        log_callback(t("analysis.metrics_json", filename=json_path.name))
        log_callback(t("analysis.results_header"))
        log_callback(f"    Golden Ratio:       {metrics_3d.get('golden_ratio_match_rate',0):.4f}")
        log_callback(f"    Fibonacci:          {metrics_3d.get('fibonacci_match_rate_3d',0):.4f}")
        log_callback(f"    Fraktale Dim 3D:    {metrics_3d.get('fractal_dimension_3d',0):.3f}")
        hp = metrics_3d.get('helix_period_bp')
        log_callback(f"    Helix-period:      {f'{hp:.1f} bp' if hp else 'N/A'}  (erwartet ~10.5)")
        log_callback(f"    Rotationssymmetrie: {metrics_3d.get('rotational_symmetry',0):.3f}")
        log_callback(f"    Fraktale Dim 2D:    {metrics_2d.get('fractal_dimension_2d',0):.3f}")

    if open_browser:
        import webbrowser
        webbrowser.open(str(html_path))

    return all_metrics


# ============================================================
# H-BONDS, HISTONES AND DISULFIDE BRIDGES
# ============================================================

# Complementary base pairs and their H-bond count
_COMPLEMENT: Dict[str, str] = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
_HBOND_COUNT: Dict[str, int] = {'AT': 2, 'TA': 2, 'CG': 3, 'GC': 3}


def compute_hbonds(sequence: str) -> List[Dict[str, Any]]:
    """
    Berechnet alle Watson-Crick H-bonds der Doppelhelix.

    In der Doppelhelix paart Base i (Strang 1) mit ihrer komplementaeren
    Base i (Strang 2). Strang 2 liegt 180 Grad gegenueber Strang 1
    auf derselben Z-Hoehe (gleicher Index i, nicht n-1-i!).

    Das Feld "j" wird auf -1 gesetzt als Signal fuer die Visualisierung,
    dass die Strang-2-Position aus der Helix-Geometrie zu berechnen ist
    (Winkel + 180 Grad, gleiche Z-Koordinate wie i).

    Returns:
        Liste von Dicts mit i, base1, base2, bond_type, num_hbonds
    """
    _COMPLEMENT_BASE = {'A': 'T', 'T': 'A', 'C': 'G', 'G': 'C'}
    n = len(sequence)
    bonds = []
    for i in range(n):
        b1   = sequence[i]
        b2   = _COMPLEMENT_BASE.get(b1, 'N')
        pair = b1 + b2
        nb   = _HBOND_COUNT.get(pair, 0)
        bonds.append({
            "i":              i,
            "j":              -1,   # Strang-2-Position wird aus Geometrie berechnet
            "base1":          b1,
            "base2":          b2,
            "bond_type":      pair,
            "num_hbonds":     nb,
            "is_watson_crick": nb > 0,
        })
    return bonds


def analyze_hbond_stability(sequence: str) -> Dict[str, Any]:
    """
    Statistische Analyse der H-bonds-Verteilung:
    GC/AT content, mismatch rate, energy estimate.
    """
    bonds = compute_hbonds(sequence)
    total  = len(bonds)
    if total == 0:
        return {"error": "Sequenz zu kurz"}

    n_gc  = sum(1 for b in bonds if b["num_hbonds"] == 3)
    n_at  = sum(1 for b in bonds if b["num_hbonds"] == 2)
    n_mis = sum(1 for b in bonds if b["num_hbonds"] == 0)

    hbond_vals = np.array([b["num_hbonds"] for b in bonds])

    # Rough thermodynamic estimate:
    # AT ≈ -2.0 kcal/mol, GC ≈ -3.0 kcal/mol (vereinfacht)
    energy_est = float(n_at * (-2.0) + n_gc * (-3.0))

    # periodicity der H-bonds entlang der Sequenz
    dominant_period = None
    if len(hbond_vals) > 50:
        fft_h = np.abs(np.fft.rfft(hbond_vals - np.mean(hbond_vals)))
        freqs = np.fft.rfftfreq(len(hbond_vals))
        peak  = int(np.argmax(fft_h[1:]) + 1)
        if freqs[peak] > 0:
            dominant_period = float(1.0 / freqs[peak])

    return {
        "total_base_pairs":       total,
        "gc_pairs":               n_gc,
        "at_pairs":               n_at,
        "mismatches":             n_mis,
        "gc_fraction":            float(n_gc / total),
        "at_fraction":            float(n_at / total),
        "mismatch_rate":          float(n_mis / total),
        "mean_hbonds_per_bp":     float(np.mean(hbond_vals)),
        "std_hbonds_per_bp":      float(np.std(hbond_vals)),
        "total_hbonds":           int(np.sum(hbond_vals)),
        "estimated_energy_kcal":  energy_est,
        "hbond_dominant_period_bp": dominant_period,
    }


def place_histones(coords: np.ndarray,
                   nucleosome_spacing: int = 200,
                   dna_per_nucleosome: int = 147,
                   linker_mean_bp: int = 20,
                   linker_std_bp:  int = 5,
                   seed: int = 42) -> List[Dict[str, Any]]:
    """
    Platziert Nukleosome entlang der DNA mit realistischem Linker-Abstand.

    Verbesserungen gemaess Vorschlag (Dokument 5):
      - Dyad bei 73 bp (Zentrum des 147 bp Kerns)
      - Linker-Laenge variabel: Normalverteilung N(20, 5) bp
      - Minimaler Linker: 5 bp (verhindert Ueberlappung)
      - Nukleosom-Abstand = 147 bp (Kern) + variablen Linker
    """
    n      = len(coords)
    rng    = np.random.default_rng(seed)
    hist   = []
    nuc_id = 0
    i      = 0
    dyad_offset = dna_per_nucleosome // 2   # 73 bp = Dyad-Position

    while i + dna_per_nucleosome <= n:
        segment = coords[i : i + dna_per_nucleosome]
        center  = segment.mean(axis=0)
        dyad    = coords[min(i + dyad_offset, n - 1)]   # Dyad-Position
        radius  = float(np.mean(np.linalg.norm(segment - center, axis=1)))

        hist.append({
            "id":          nuc_id,
            "center":      center.tolist(),
            "dyad_pos":    dyad.tolist(),    # Physikalisch korrekter Referenzpunkt
            "bp_start":    i,
            "bp_end":      i + dna_per_nucleosome - 1,
            "radius_nm":   radius,
            "wrapped_bp":  dna_per_nucleosome,
        })
        nuc_id += 1
        # Variabler Linker: N(linker_mean_bp, linker_std_bp), min 5 bp
        linker = max(5, int(rng.normal(linker_mean_bp, linker_std_bp)))
        i += dna_per_nucleosome + linker

    return hist


def compute_disulfide_bonds(histones: List[Dict],
                             max_dist_nm: float = 4.0) -> List[Dict[str, Any]]:
    """
    Simulates possible disulfide bridges between histone proteins.
    Cys-Cys-Bindungen entstehen wenn der Abstand zwischen Histonen < max_dist_nm.
    (Realistic Cys-Cys bond length: ~0.2 nm; histone distance used as proxy)
    """
    bonds = []
    positions = [np.array(h["center"]) for h in histones]
    for i in range(len(positions)):
        for j in range(i + 1, len(positions)):
            dist = float(np.linalg.norm(positions[i] - positions[j]))
            if dist <= max_dist_nm:
                bonds.append({
                    "histone_i":  i,
                    "histone_j":  j,
                    "distance_nm": dist,
                    "bond_type":  "Cys-Cys (simulated)",
                })
    return bonds


def build_hbonds_html(coords:      np.ndarray,
                       colors:      np.ndarray,
                       sequence:    str,
                       bonds:       List[Dict],
                       species_name: str,
                       metrics:     Dict,
                       output_path: Path) -> str:
    """Interaktive HTML mit DNA-Basen + DNA-Backbone-Linie + H-bonds"""
    base_hex = ['#E74C3C', '#27AE60', '#2980B9', '#F39C12']
    n        = len(coords)

    # ── DNA-points (max 2500) ────────────────────────────────────────────────
    step    = max(1, n // 2500)
    c_sub   = coords[::step]
    col_sub = [base_hex[int(colors[i])] for i in range(0, n, step)]
    seq_sub = [sequence[i] for i in range(0, n, step)]

    # ── DNA-Backbone als Linie (max 1000 points) ─────────────────────────────
    bstep    = max(1, n // 1000)
    bb       = coords[::bstep]
    bb_x     = [float(v) for v in bb[:, 0]]
    bb_y     = [float(v) for v in bb[:, 1]]
    bb_z     = [float(v) for v in bb[:, 2]]

    # ── H-bonds: AT (cyan) und CG (lime), max 500 je Typ ──────────────────
    wc       = [b for b in bonds if b["is_watson_crick"]]
    at_bonds = [b for b in wc if b["num_hbonds"] == 2]
    cg_bonds = [b for b in wc if b["num_hbonds"] == 3]
    bstep_at = max(1, len(at_bonds) // 500)
    bstep_cg = max(1, len(cg_bonds) // 500)

    # Explizite float-Konvertierung + None als Segmenttrenner
    # Estimate helix axis via sliding average
    _w_h = 11
    _kern_h = np.ones(_w_h) / _w_h
    _axis_x_h = np.convolve(coords[:, 0], _kern_h, mode='same')
    _axis_y_h = np.convolve(coords[:, 1], _kern_h, mode='same')

    def _strand2_pos_h(i_):
        """Strang-2 = Spiegelung von Strang-1 an der Helix-Achse."""
        if i_ >= n:
            return None, None, None
        x2 = float(2.0 * _axis_x_h[i_] - coords[i_, 0])
        y2 = float(2.0 * _axis_y_h[i_] - coords[i_, 1])
        z2 = float(coords[i_, 2])
        return x2, y2, z2

    def _bond_lines(bond_list, bstep):
        xs, ys, zs = [], [], []
        for b in bond_list[::bstep]:
            i_ = b["i"]
            if i_ < n:
                x2, y2, z2 = _strand2_pos_h(i_)
                if x2 is not None:
                    xs += [float(coords[i_, 0]), x2, None]
                    ys += [float(coords[i_, 1]), y2, None]
                    zs += [float(coords[i_, 2]), z2, None]
        return xs, ys, zs

    at_x, at_y, at_z = _bond_lines(at_bonds, bstep_at)
    cg_x, cg_y, cg_z = _bond_lines(cg_bonds, bstep_cg)

    # ── Metrik-Info ───────────────────────────────────────────────────────────
    gc_frac = metrics.get("gc_fraction", 0)
    total_h = metrics.get("total_hbonds", 0)
    energy  = metrics.get("estimated_energy_kcal", 0)
    info    = (f"GC {gc_frac:.1%} | AT {metrics.get('at_fraction',0):.1%} | "
               f"H-bonds: {total_h:,} | "
               f"ΔG ≈ {energy:,.0f} kcal/mol | "
               f"Mismatches: {metrics.get('mismatch_rate',0):.2%}")

    # ── HTML als String-Konkatenation (kein verschachteltes f-string) ─────────
    # DNA-points-Trace
    dna_trace = (
        "{"
        f"x:{_js_list([float(v) for v in c_sub[:,0]])},"
        f"y:{_js_list([float(v) for v in c_sub[:,1]])},"
        f"z:{_js_list([float(v) for v in c_sub[:,2]])},"
        "mode:'markers',type:'scatter3d',"
        f"marker:{{size:2.5,color:{_js_list(col_sub)},opacity:0.85}},"
        f"text:{_js_list(seq_sub)},"
        "hovertemplate:'%{text} (%{x:.2f},%{y:.2f},%{z:.2f}) nm<extra></extra>',"
        "name:'DNA-Basen',visible:true}"
    )
    # Backbone-Trace
    bb_trace = (
        "{"
        f"x:{_js_list(bb_x)},y:{_js_list(bb_y)},z:{_js_list(bb_z)},"
        "mode:'lines',type:'scatter3d',"
        "line:{color:'rgba(180,180,180,0.3)',width:1},"
        "name:'Backbone',visible:true}"
    )
    # AT H-bonds
    at_trace = (
        "{"
        f"x:{_js_list(at_x)},y:{_js_list(at_y)},z:{_js_list(at_z)},"
        "mode:'lines',type:'scatter3d',"
        "line:{color:'cyan',width:1},opacity:0.45,"
        "name:'A-T (2 H-Br\u00fccken)',visible:true}"
    )
    # CG H-bonds
    cg_trace = (
        "{"
        f"x:{_js_list(cg_x)},y:{_js_list(cg_y)},z:{_js_list(cg_z)},"
        "mode:'lines',type:'scatter3d',"
        "line:{color:'#00FF7F',width:1.5},opacity:0.55,"
        "name:'C-G (3 H-Br\u00fccken)',visible:true}"
    )

    html = (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset=\"utf-8\">\n"
        f"<title>H-bonds – {species_name}</title>\n"
        "<script src=\"https://cdn.plot.ly/plotly-2.26.0.min.js\"></script>\n"
        "<style>\n"
        "  body{margin:0;background:#0a0a18;color:#eee;font-family:sans-serif}\n"
        "  #plot{width:100vw;height:87vh}\n"
        "  #info{padding:6px 14px;font-size:11.5px;background:#10102a;"
        "border-bottom:1px solid #333}\n"
        "  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;"
        "margin-right:3px;vertical-align:middle}\n"
        "</style></head><body>\n"
        "<div id=\"info\">\n"
        f"  <b>🔬 {species_name}</b> – H-bonds &nbsp;|&nbsp; {info} &nbsp;&nbsp;\n"
        "  <span><span class=\"dot\" style=\"background:#00FFFF\"></span>"
        "A-T (2 H-bonds)</span> &nbsp;\n"
        "  <span><span class=\"dot\" style=\"background:#00FF7F\"></span>"
        "C-G (3 H-bonds)</span>\n"
        "</div>\n"
        "<div id=\"plot\"></div>\n"
        "<script>\n"
        f"var traces = [{dna_trace},{bb_trace},{at_trace},{cg_trace}];\n"
        "var layout = {\n"
        "  paper_bgcolor:'#0a0a18',plot_bgcolor:'#0a0a18',font:{color:'#ddd'},\n"
        f"  title:{{text:'H-bonds: {species_name}',font:{{size:13}}}},\n"
        "  scene:{\n"
        "    xaxis:{title:'X (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    yaxis:{title:'Y (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    zaxis:{title:'Z (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    bgcolor:'#0a0a18',aspectmode:'data'},\n"
        "  legend:{bgcolor:'rgba(10,10,24,0.8)',bordercolor:'#333',borderwidth:1},\n"
        "  margin:{l:0,r:0,t:36,b:0}\n"
        "};\n"
        "Plotly.newPlot('plot',traces,layout,{responsive:true});\n"
        "</script></body></html>"
    )
    output_path.write_text(html, encoding='utf-8')
    return str(output_path)


def build_histones_html(coords:      np.ndarray,
                         colors:      np.ndarray,
                         sequence:    str,
                         histones:    List[Dict],
                         disulfides:  List[Dict],
                         species_name: str,
                         output_path: Path) -> str:
    """Interaktive HTML mit DNA + Histonen (Kugeln) + Disulfide bridges"""
    base_hex = ['#E74C3C', '#27AE60', '#2980B9', '#F39C12']
    n        = len(coords)
    step     = max(1, n // 2500)
    c_sub    = coords[::step]
    col_sub  = [base_hex[colors[i]] for i in range(0, n, step)]
    seq_sub  = [sequence[i] for i in range(0, n, step)]

    # Histon-Trace: vorab als String berechnen, kein verschachteltes f-string
    if histones:
        hpos  = np.array([h["center"] for h in histones])
        h_txt = [f"Nukleosom {h['id']}<br>bp {h['bp_start']}-{h['bp_end']}<br>"
                 f"r={h['radius_nm']:.1f} nm" for h in histones]
        histone_trace = (
            "{"
            f"x:{hpos[:,0].tolist()},y:{hpos[:,1].tolist()},z:{hpos[:,2].tolist()},"
            "mode:'markers',type:'scatter3d',"
            "marker:{size:12,color:'#9B59B6',opacity:0.65,"
            "line:{color:'#D2B4DE',width:1}},"
            f"text:{h_txt},"
            "hovertemplate:'%{text}<extra></extra>',"
            "name:'Histon-Oktamer'}"
        )
    else:
        histone_trace = "{x:[],y:[],z:[],mode:'markers',type:'scatter3d',name:'Histone (keine)'}"

    # Disulfide bridges als Liniensegmente
    ds_x: List = []
    ds_y: List = []
    ds_z: List = []
    for d in disulfides:
        ci_ = np.array(histones[d["histone_i"]]["center"])
        cj_ = np.array(histones[d["histone_j"]]["center"])
        ds_x += [float(ci_[0]), float(cj_[0]), None]
        ds_y += [float(ci_[1]), float(cj_[1]), None]
        ds_z += [float(ci_[2]), float(cj_[2]), None]

    info = (f"Nukleosome: {len(histones)} | "
            f"Disulfide bridges (sim.): {len(disulfides)} | "
            f"Nucleosom-Abdeckung: {len(histones)*147}/{n} bp")

    html = (
        "<!DOCTYPE html>\n"
        "<html><head><meta charset=\"utf-8\">\n"
        f"<title>Histone + Disulfid - {species_name}</title>\n"
        "<script src=\"https://cdn.plot.ly/plotly-2.26.0.min.js\"></script>\n"
        "<style>\n"
        "  body{margin:0;background:#0a0a18;color:#eee;font-family:sans-serif}\n"
        "  #plot{width:100vw;height:88vh}\n"
        "  #info{padding:6px 14px;font-size:11.5px;background:#10102a;border-bottom:1px solid #333}\n"
        "  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:3px;vertical-align:middle}\n"
        "</style></head><body>\n"
        "<div id=\"info\">\n"
        f"  <b>🧬 {species_name}</b> - Nukleosome &amp; Disulfide bridges &nbsp;|&nbsp; {info} &nbsp;&nbsp;\n"
        "  <span><span class=\"dot\" style=\"background:#9B59B6\"></span>Histon-Oktamer</span> &nbsp;\n"
        "  <span><span class=\"dot\" style=\"background:#F39C12\"></span>Cys-Cys (sim.)</span>\n"
        "</div>\n"
        "<div id=\"plot\"></div>\n"
        "<script>\n"
        "var traces = [\n"
        f"  {{x:{_js_list(c_sub[:,0].tolist())},y:{_js_list(c_sub[:,1].tolist())},z:{_js_list(c_sub[:,2].tolist())},\n"
        "   mode:'markers',type:'scatter3d',\n"
        f"   marker:{{size:1.8,color:{_js_list(col_sub)},opacity:0.5}},\n"
        f"   text:{_js_list(seq_sub)},\n"
        "   hovertemplate:'%{text}<extra></extra>',name:'DNA-Basen'},\n"
        f"  {histone_trace},\n"
        f"  {{x:{_js_list(ds_x)},y:{_js_list(ds_y)},z:{_js_list(ds_z)},\n"
        "   mode:'lines',type:'scatter3d',\n"
        "   line:{color:'#F39C12',width:3},opacity:0.8,\n"
        "   name:'Disulfide bridge (Cys-Cys, sim.)'}\n"
        "];\n"
        "var layout={\n"
        "  paper_bgcolor:'#0a0a18',plot_bgcolor:'#0a0a18',font:{color:'#ddd'},\n"
        f"  title:{{text:'Nukleosomale Umgebung: {species_name}',font:{{size:13}}}},\n"
        "  scene:{\n"
        "    xaxis:{title:'X (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    yaxis:{title:'Y (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    zaxis:{title:'Z (nm)',gridcolor:'#1a1a30',zerolinecolor:'#333'},\n"
        "    bgcolor:'#0a0a18',aspectmode:'data'},\n"
        "  margin:{l:0,r:0,t:36,b:0}\n"
        "};\n"
        "Plotly.newPlot('plot',traces,layout,{responsive:true});\n"
        "</script></body></html>"
    )
    output_path.write_text(html, encoding='utf-8')
    return str(output_path)


def run_hbond_visualization(species_name:  str,
                             species_info:  Dict,
                             log_callback:  Optional[Callable] = None,
                             open_browser:  bool = False) -> Dict[str, Any]:
    """H-bonds-Pipeline: Laden → Rekonstruieren → Visualisieren → Analysieren"""
    fasta = get_or_fetch_genome(species_info["accession"], log_callback)
    if not fasta:
        return {"error": t("analysis.genome_load_failed")}

    reader  = GenomeReader(fasta)
    seq     = reader.get_sequence(CONFIG.max_seq_length)
    seq_vis = seq[:1000]
    if log_callback:
        log_callback(t("analysis.model_3d_info", length=len(seq_vis), height=len(seq_vis)*0.34, turns=len(seq_vis)/10.5))

    if log_callback:
        log_callback(t("realistic_3d.reconstructing"))
    coords, col = reconstruct_realistic_3d_dna(seq_vis)

    if log_callback:
        log_callback(t("analysis.computing_hbonds"))
    bonds   = compute_hbonds(seq_vis)
    metrics = analyze_hbond_stability(seq_vis)

    if log_callback:
        log_callback(t("analysis.gc_fraction", value=metrics["gc_fraction"]))
        log_callback(t("analysis.at_fraction", value=metrics["at_fraction"]))
        log_callback(t("analysis.mismatches", value=metrics["mismatch_rate"]))
        log_callback(t("analysis.hbonds_total", n=metrics["total_hbonds"]))
        log_callback(t("analysis.energy_estimate", energy=metrics["estimated_energy_kcal"]))
        p = metrics.get("hbond_dominant_period_bp")
        log_callback(t("analysis.periodicity", value=f"{p:.1f} bp" if p else "N/A"))

    safe       = (species_name.replace(" ", "_").replace("(", "")
                              .replace(")", "").replace(",", ""))
    html_path  = CONFIG.real3d_dir / f"{safe}_hbonds.html"
    json_path  = CONFIG.real3d_dir / f"{safe}_hbonds_metrics.json"

    build_hbonds_html(coords, col, seq_vis, bonds, species_name, metrics, html_path)
    result = {"species": species_name, "hbond_metrics": metrics,
              "html_path": str(html_path)}
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, cls=NumpyEncoder)

    if log_callback:
        log_callback(t("realistic_3d.hbonds_saved", filename=html_path.name))
        log_callback(t("analysis.metrics_saved_short", filename=json_path.name))

    if open_browser:
        import webbrowser
        webbrowser.open(str(html_path))
    return result


def run_histone_visualization(species_name:  str,
                               species_info:  Dict,
                               log_callback:  Optional[Callable] = None,
                               open_browser:  bool = False) -> Dict[str, Any]:
    """Histon + Disulfid-Pipeline"""
    fasta = get_or_fetch_genome(species_info["accession"], log_callback)
    if not fasta:
        return {"error": t("analysis.genome_load_failed")}

    reader  = GenomeReader(fasta)
    seq     = reader.get_sequence(CONFIG.max_seq_length)
    seq_vis = seq[:1000]
    if log_callback:
        log_callback(t("analysis.model_3d_height_only", length=len(seq_vis), height=len(seq_vis)*0.34))

    if log_callback:
        log_callback(t("realistic_3d.reconstructing"))
    coords, col = reconstruct_realistic_3d_dna(seq_vis)

    if log_callback:
        log_callback("  Platziere Nukleosome (alle 200 bp)...")
    histones   = place_histones(coords, nucleosome_spacing=200, dna_per_nucleosome=147)
    disulfides = compute_disulfide_bonds(histones, max_dist_nm=4.0)

    if log_callback:
        log_callback(t("analysis.nucleosome_count", n=len(histones)))
        log_callback(t("analysis.disulfide_bridges", n=len(disulfides)))

    safe       = (species_name.replace(" ", "_").replace("(", "")
                              .replace(")", "").replace(",", ""))
    html_path  = CONFIG.real3d_dir / f"{safe}_histones.html"
    json_path  = CONFIG.real3d_dir / f"{safe}_histone_metrics.json"

    build_histones_html(coords, col, seq_vis, histones, disulfides, species_name, html_path)

    result = {
        "species":           species_name,
        "nucleosome_count":  len(histones),
        "disulfide_count":   len(disulfides),
        "histones":          histones,
        "disulfide_bonds":   disulfides,
    }
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, cls=NumpyEncoder)

    if log_callback:
        log_callback(t("analysis.histone_html_short", filename=html_path.name))
        log_callback(t("analysis.metrics_saved_short", filename=json_path.name))

    if open_browser:
        import webbrowser
        webbrowser.open(str(html_path))
    return result



# ============================================================
# DELTA DEVIATION ANALYZER
# Extracts and analyses the "negative space" of the Δ-signal:
# positions where the optimal Δ-transition does NOT occur.
# These deviations form a binary sequence (0=deviation, 1=transition)
# that can be compared between species.
# ============================================================

class DeltaDeviationAnalyzer:
    """
    Analyses Δ-deviation sequences — positions where the optimal
    Δ-transition is ABSENT. These 'non-transitions' form a binary
    sequence that is independent of base identity and can be
    compared across species.
    
    Statistical tests (honest, no overinterpretation):
    - χ²-test vs. geometric distribution (non-randomness)
    - Runs test (clustering vs. alternating)
    - Power-law fit of block lengths
    - Windowed Hamming similarity between species
    """

    def __init__(self, freq_map: Dict[str, float] = None):
        self.freq_map = freq_map or BASE_TO_FREQ

    # ── Core extraction ─────────────────────────────────────────────────────

    def extract_deviation_sequence(
        self,
        sequence: str,
        delta_opt: float,
        freq_map: Dict[str, float] = None,
    ) -> Dict[str, Any]:
        """
        Builds a binary 0/1 sequence from the genome:
          1 = optimal Δ-transition present at this position
          0 = deviation (no Δ-transition)
        
        Returns dict with raw sequence (run-length encoded) + metadata.
        """
        fm = freq_map or self.freq_map
        seq_len = len(sequence)
        ones = zeros = 0
        # Run-length encoding: list of (value, count) pairs
        rle: List[Tuple[int, int]] = []
        current_val = -1
        current_run = 0

        for i in range(seq_len - 1):
            b1, b2 = sequence[i], sequence[i + 1]
            if b1 not in fm or b2 not in fm:
                bit = 0
            else:
                diff = abs(fm[b2] - fm[b1])
                bit = 1 if abs(diff - delta_opt) < 1e-6 else 0
            if bit == 1:
                ones += 1
            else:
                zeros += 1
            if bit != current_val:
                if current_val >= 0:
                    rle.append((current_val, current_run))
                current_val = bit
                current_run = 1
            else:
                current_run += 1
        if current_run > 0 and current_val >= 0:
            rle.append((current_val, current_run))

        total = ones + zeros
        return {
            "total_positions": total,
            "ones":  ones,
            "zeros": zeros,
            "transition_rate": ones / total if total else 0.0,
            "deviation_rate":  zeros / total if total else 0.0,
            "rle": rle,   # compact storage
        }

    # ── Statistics ──────────────────────────────────────────────────────────

    def compute_deviation_statistics(
        self, dev_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Computes statistics on the deviation sequence:
        - Block length distribution of 0-runs
        - χ²-test vs geometric distribution (non-randomness)
        - Runs test (clustering)
        - Power-law fit
        """
        rle        = dev_data["rle"]
        dev_rate   = dev_data["deviation_rate"]
        total      = dev_data["total_positions"]

        # Extract 0-block (deviation block) lengths
        zero_blocks = [count for val, count in rle if val == 0]
        one_blocks  = [count for val, count in rle if val == 1]

        stats: Dict[str, Any] = {
            "num_zero_blocks":   len(zero_blocks),
            "num_one_blocks":    len(one_blocks),
            "mean_zero_block":   float(np.mean(zero_blocks)) if zero_blocks else 0.0,
            "max_zero_block":    max(zero_blocks) if zero_blocks else 0,
            "mean_one_block":    float(np.mean(one_blocks)) if one_blocks else 0.0,
            "max_one_block":     max(one_blocks) if one_blocks else 0,
        }

        # ── χ²-test: observed block lengths vs geometric distribution ──────
        # Under randomness, block lengths follow Geometric(p=transition_rate).
        # We bin lengths 1–10 + "≥11" and compare observed vs expected.
        chi2_result = {"statistic": None, "p_value": None, "significant": False,
                       "interpretation": "insufficient data"}
        if len(zero_blocks) >= 20 and dev_rate > 0:
            try:
                p_geom   = 1.0 - dev_rate  # probability of ending a 0-block
                max_bin  = 10
                observed = np.zeros(max_bin + 1)
                for bl in zero_blocks:
                    observed[min(bl - 1, max_bin)] += 1
                expected = np.zeros(max_bin + 1)
                for k in range(max_bin):
                    expected[k] = len(zero_blocks) * ((1 - p_geom) ** k * p_geom)
                expected[max_bin] = len(zero_blocks) - expected[:max_bin].sum()
                # Only use bins with expected ≥ 5
                mask = expected >= 5
                if mask.sum() >= 2:
                    from scipy.stats import chisquare
                    chi2_stat, chi2_p = chisquare(observed[mask], expected[mask])
                    chi2_result = {
                        "statistic":      round(float(chi2_stat), 4),
                        "p_value":        round(float(chi2_p), 6),
                        "significant":    bool(chi2_p < 0.05),
                        "interpretation": (
                            "non-random (structured)" if chi2_p < 0.05
                            else "consistent with random"
                        ),
                    }
            except Exception as e:
                chi2_result["interpretation"] = f"error: {e}"
        stats["chi2_vs_geometric"] = chi2_result

        # ── Runs test (Wald-Wolfowitz) ────────────────────────────────────
        runs_result = {"z": None, "p_value": None, "interpretation": "insufficient data"}
        if len(rle) >= 10:
            try:
                n1     = dev_data["ones"]
                n0     = dev_data["zeros"]
                runs   = len(rle)
                mean_r = 1 + 2 * n1 * n0 / (n1 + n0)
                var_r  = (2 * n1 * n0 * (2 * n1 * n0 - n1 - n0)
                          / ((n1 + n0) ** 2 * (n1 + n0 - 1)))
                if var_r > 0:
                    z = (runs - mean_r) / var_r ** 0.5
                    from scipy.stats import norm
                    p_runs = 2 * (1 - norm.cdf(abs(z)))
                    runs_result = {
                        "runs":          runs,
                        "z":             round(float(z), 4),
                        "p_value":       round(float(p_runs), 6),
                        "interpretation": (
                            "clustered (non-random)" if z < -1.96
                            else "alternating (non-random)" if z > 1.96
                            else "consistent with random"
                        ),
                    }
            except Exception as e:
                runs_result["interpretation"] = f"error: {e}"
        stats["runs_test"] = runs_result

        # ── Power-law fit on block lengths ────────────────────────────────
        powerlaw_result = {"alpha": None, "r2": None, "interpretation": "insufficient data"}
        if len(zero_blocks) >= 20:
            try:
                bl_arr = np.array(sorted(zero_blocks), dtype=float)
                bl_arr = bl_arr[bl_arr >= 1]
                ranks  = np.arange(1, len(bl_arr) + 1, dtype=float)[::-1]
                log_x  = np.log(bl_arr)
                log_y  = np.log(ranks / len(bl_arr))
                coeffs = np.polyfit(log_x, log_y, 1)
                alpha  = -coeffs[0]
                # R² of the log-log fit
                y_fit  = np.polyval(coeffs, log_x)
                ss_res = np.sum((log_y - y_fit) ** 2)
                ss_tot = np.sum((log_y - log_y.mean()) ** 2)
                r2     = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
                powerlaw_result = {
                    "alpha":          round(float(alpha), 4),
                    "r2":             round(float(r2), 4),
                    "interpretation": (
                        "power-law (r²≥0.85)" if r2 >= 0.85
                        else "weak power-law (0.6≤r²<0.85)" if r2 >= 0.6
                        else "not power-law"
                    ),
                }
            except Exception as e:
                powerlaw_result["interpretation"] = f"error: {e}"
        stats["power_law"] = powerlaw_result

        return stats

    # ── Pairwise comparison ─────────────────────────────────────────────────

    def compare_two_species(
        self,
        rle1: List[Tuple[int, int]],
        rle2: List[Tuple[int, int]],
        window: int = 200,
        step: int = 50,
    ) -> Dict[str, Any]:
        """
        Windowed Hamming similarity between two deviation sequences.
        Both are compared at the same genomic windows.
        Returns overall identity + per-window profile.
        """
        # Expand RLE to arrays (capped at max_seq_length for speed)
        def expand_rle(rle, maxlen=50000) -> np.ndarray:
            arr = []
            for val, cnt in rle:
                arr.extend([val] * cnt)
                if len(arr) >= maxlen:
                    break
            return np.array(arr[:maxlen], dtype=np.int8)

        a1 = expand_rle(rle1)
        a2 = expand_rle(rle2)
        min_len = min(len(a1), len(a2))
        if min_len < window:
            return {"identity": None, "comparable_length": min_len,
                    "interpretation": "sequences too short to compare"}

        a1 = a1[:min_len]
        a2 = a2[:min_len]

        # Global identity
        global_identity = float(np.mean(a1 == a2))

        # Windowed identity
        window_ids = []
        for start in range(0, min_len - window, step):
            w1 = a1[start:start + window]
            w2 = a2[start:start + window]
            window_ids.append(float(np.mean(w1 == w2)))

        return {
            "identity":           round(global_identity, 4),
            "comparable_length":  min_len,
            "window_size":        window,
            "window_step":        step,
            "mean_window_id":     round(float(np.mean(window_ids)), 4) if window_ids else None,
            "std_window_id":      round(float(np.std(window_ids)), 4) if window_ids else None,
            "min_window_id":      round(float(np.min(window_ids)), 4) if window_ids else None,
            "max_window_id":      round(float(np.max(window_ids)), 4) if window_ids else None,
            "interpretation": (
                "highly similar" if global_identity >= 0.85
                else "moderately similar" if global_identity >= 0.70
                else "weakly similar" if global_identity >= 0.55
                else "dissimilar"
            ),
        }

    # ── Full pipeline ────────────────────────────────────────────────────────

    def shuffle_control(
        self,
        sequence: str,
        delta_opt: float,
        freq_map: Optional[Dict] = None,
        n_shuffles: int = 100,
    ) -> Dict[str, Any]:
        """
        Shuffle control: compares real deviation statistics against
        n_shuffles random permutations of the same sequence.

        For each shuffle:
          - Shuffle the sequence (preserves base composition)
          - Extract deviation sequence
          - Compute statistics

        Returns:
          - shuffle_mean_dev_rate: expected deviation rate under H0
          - shuffle_std_dev_rate:  SD across shuffles
          - real_vs_shuffle_z:     Z-score (how many SDs above shuffle mean)
          - real_chi2_percentile:  percentile of real χ² in shuffle distribution
          - is_significant:        True if real χ² > 95th percentile of shuffles
        """
        real_dev   = self.extract_deviation_sequence(sequence, delta_opt, freq_map)
        real_stats = self.compute_deviation_statistics(real_dev)
        real_chi2  = real_stats["chi2_vs_geometric"].get("statistic") or 0.0
        real_rate  = real_dev["deviation_rate"]

        shuffle_rates  = []
        shuffle_chi2s  = []

        for _ in range(n_shuffles):
            shuffled      = shuffle_sequence(sequence)
            shuf_dev      = self.extract_deviation_sequence(shuffled, delta_opt, freq_map)
            shuf_stats    = self.compute_deviation_statistics(shuf_dev)
            shuffle_rates.append(shuf_dev["deviation_rate"])
            shuf_chi2 = shuf_stats["chi2_vs_geometric"].get("statistic")
            shuffle_chi2s.append(shuf_chi2 if shuf_chi2 is not None else 0.0)

        mean_rate = float(np.mean(shuffle_rates))
        std_rate  = float(np.std(shuffle_rates))
        z_rate    = (real_rate - mean_rate) / std_rate if std_rate > 0 else 0.0

        mean_chi2 = float(np.mean(shuffle_chi2s))
        std_chi2  = float(np.std(shuffle_chi2s))
        z_chi2    = (real_chi2 - mean_chi2) / std_chi2 if std_chi2 > 0 else 0.0
        pct_chi2  = float(np.mean(np.array(shuffle_chi2s) <= real_chi2))

        return {
            "n_shuffles":              n_shuffles,
            "real_deviation_rate":     round(real_rate, 4),
            "shuffle_mean_dev_rate":   round(mean_rate, 4),
            "shuffle_std_dev_rate":    round(std_rate, 4),
            "real_vs_shuffle_z_rate":  round(z_rate, 3),
            "real_chi2":               round(real_chi2, 2),
            "shuffle_mean_chi2":       round(mean_chi2, 2),
            "shuffle_std_chi2":        round(std_chi2, 2),
            "real_chi2_z":             round(z_chi2, 3),
            "real_chi2_percentile":    round(pct_chi2, 3),
            "is_significant":          bool(pct_chi2 >= 0.95),
            "interpretation": (
                "✅ REAL signal: deviation structure exceeds 95th percentile of shuffles"
                if pct_chi2 >= 0.95
                else "⚠️ MARGINAL: 90th–95th percentile"
                if pct_chi2 >= 0.90
                else "❌ NOT significant vs. random baseline"
            ),
        }

    def run_species(
        self,
        species_name: str,
        species_info: Dict,
        delta_opt: float,
        freq_map: Optional[Dict] = None,
        log_callback: Optional[callable] = None,
        run_shuffle_control: bool = True,
        n_shuffles: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Full pipeline for one species:
        load sequence → extract → compute stats → shuffle control → save JSON.
        Returns result dict or None on failure.
        """
        accession = species_info["accession"]
        if log_callback:
            log_callback(t("analysis.deviation_extracting",
                           species=species_display(species_name),
                           delta=delta_opt))
        try:
            raw_seq = get_or_fetch_genome(accession, log_callback=log_callback)
            if not raw_seq:
                return None
            seq = raw_seq[:CONFIG.max_seq_length]

            dev_data = self.extract_deviation_sequence(
                seq, delta_opt, freq_map)
            stats    = self.compute_deviation_statistics(dev_data)

            # ── Shuffle control ───────────────────────────────────────────
            shuffle_ctrl = None
            if run_shuffle_control and len(seq) >= 1000:
                if log_callback:
                    log_callback(t("analysis.deviation_shuffle_running",
                                   species=species_display(species_name),
                                   n=n_shuffles))
                shuffle_ctrl = self.shuffle_control(
                    seq, delta_opt, freq_map, n_shuffles=n_shuffles)
                if log_callback:
                    log_callback(t("analysis.deviation_shuffle_result",
                                   species=species_display(species_name),
                                   interp=shuffle_ctrl["interpretation"],
                                   pct=shuffle_ctrl["real_chi2_percentile"] * 100))

            result = {
                "species":         species_name,
                "species_display": species_display(species_name),
                "accession":       accession,
                "group":           species_info["group"],
                "habitat":         _get_habitat(species_name, species_info["group"]),
                "delta_opt":       delta_opt,
                "freq_map":        "standard" if (freq_map is None or freq_map == BASE_TO_FREQ)
                                   else "extended",
                "deviation_data":  dev_data,
                "statistics":      stats,
                "shuffle_control": shuffle_ctrl,
                "timestamp":       datetime.now().isoformat(),
            }

            # Save per-species JSON
            safe_sp  = species_name.replace(" ", "_").replace("(", "").replace(")", "")
            fname    = f"{accession}_{safe_sp}_deviation.json"
            out_path = CONFIG.delta_abstracts_dir / fname
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, cls=NumpyEncoder, indent=2, ensure_ascii=False)

            if log_callback:
                chi2  = stats["chi2_vs_geometric"]
                p_val = chi2.get("p_value")
                if chi2.get("significant"):
                    log_callback(t("analysis.deviation_not_random",
                                   species=species_display(species_name),
                                   chi2=chi2["statistic"],
                                   p=p_val))
                else:
                    log_callback(t("analysis.deviation_random",
                                   species=species_display(species_name)))
                log_callback(t("analysis.deviation_rate",
                               species=species_display(species_name),
                               rate=dev_data["deviation_rate"]))
            return result

        except Exception as e:
            if log_callback:
                log_callback(t("log_messages.error_occurred", error=e))
            return None


def run_delta_deviation_analysis(
    species_filter: Optional[List[str]] = None,
    stop_event: Optional[Any] = None,
    log_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """
    Main entry point: analyse Δ-deviation sequences for all (or selected)
    species that have an optimal Δ from a previous Δ-optimisation run.
    
    1. Load optimal Δ per species from delta_optimization_*.json
    2. For each species: extract deviation sequence + compute statistics
    3. Pairwise comparison between all species
    4. Generate MD + JSON comparison report
    
    Returns summary dict.
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    if log_callback:
        log_callback("=" * 80)
        log_callback(t("log_messages.deviation_start", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        log_callback("=" * 80)

    # ── Step 1: Load optimal Δ values from most recent delta JSON ─────────
    delta_opt_map: Dict[str, Tuple[float, Optional[Dict]]] = {}
    delta_files = sorted(
        CONFIG.results_dir.glob("delta_optimization_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    if not delta_files:
        if log_callback:
            log_callback(t("dialogs.deviation_no_delta"))
        return {"error": "no_delta_files"}

    if log_callback:
        log_callback(t("analysis.deviation_loading_delta", file=delta_files[0].name))

    for delta_file in delta_files:
        try:
            data = json.loads(delta_file.read_text(encoding="utf-8"))
            for sp in data.get("species", []):
                name     = sp.get("name", "")
                acc      = sp.get("accession", "")
                d_opt    = sp.get("optimal_delta")
                scheme   = sp.get("optimal_scheme")
                if d_opt is None or name in delta_opt_map:
                    continue
                freq_map = FREQUENCY_SCHEMES.get(scheme) if scheme else None
                delta_opt_map[name] = (float(d_opt), freq_map)
        except Exception:
            continue
        if delta_opt_map:
            break

    if log_callback:
        log_callback(t("analysis.deviation_species_found", n=len(delta_opt_map)))

    # ── Step 2: Extract deviation sequences ───────────────────────────────
    analyzer  = DeltaDeviationAnalyzer()
    results   = {}
    species_list = list(SPECIES_DB.items())
    if species_filter:
        species_list = [(k, v) for k, v in species_list if k in species_filter]

    done = 0
    for sp_name, sp_info in species_list:
        if stop_event and stop_event.is_set():
            if log_callback:
                log_callback(t("log_messages.stopped"))
            break

        if sp_name not in delta_opt_map:
            if log_callback:
                log_callback(t("analysis.deviation_skip_no_delta",
                               species=species_display(sp_name)))
            continue

        d_opt, freq_map = delta_opt_map[sp_name]
        result = analyzer.run_species(sp_name, sp_info, d_opt, freq_map, log_callback)
        if result:
            results[sp_name] = result
            done += 1

    if log_callback:
        log_callback(t("analysis.deviation_extracted", n=done))

    # ── Step 3: Pairwise comparison (limited to avoid O(n²) explosion) ───
    comparisons = []
    sp_names    = list(results.keys())

    if log_callback and len(sp_names) >= 2:
        log_callback(t("analysis.deviation_comparing", n=len(sp_names)))

    # Compare within-group pairs + a sample of cross-group pairs
    done_pairs = set()
    for i, sp1 in enumerate(sp_names):
        if stop_event and stop_event.is_set():
            break
        for j, sp2 in enumerate(sp_names):
            if j <= i or (sp1, sp2) in done_pairs:
                continue
            # Limit: only compare same habitat or first 3 cross-group pairs per species
            hab1 = results[sp1]["habitat"]
            hab2 = results[sp2]["habitat"]
            cross_count = sum(1 for c in comparisons
                              if c["species1"] == sp1 and c["habitat1"] != c["habitat2"])
            if hab1 != hab2 and cross_count >= 3:
                continue
            comp = analyzer.compare_two_species(
                results[sp1]["deviation_data"]["rle"],
                results[sp2]["deviation_data"]["rle"],
            )
            comp.update({
                "species1": sp1, "species2": sp2,
                "display1": species_display(sp1), "display2": species_display(sp2),
                "habitat1": hab1, "habitat2": hab2,
            })
            comparisons.append(comp)
            done_pairs.add((sp1, sp2))

    # ── Step 4: Generate report ───────────────────────────────────────────
    report_md   = _write_deviation_report_md(results, comparisons, ts)
    report_json = {
        "timestamp":   ts,
        "species":     list(results.values()),
        "comparisons": comparisons,
    }

    md_path   = CONFIG.delta_abstracts_dir / f"DEVIATION_REPORT_{ts}.md"
    json_path = CONFIG.delta_abstracts_dir / f"DEVIATION_REPORT_{ts}.json"
    md_path.write_text(report_md, encoding="utf-8")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_json, f, cls=NumpyEncoder, indent=2, ensure_ascii=False)

    if log_callback:
        log_callback(t("analysis.deviation_report_saved", path=md_path.name))
        log_callback(t("analysis.deviation_json_saved",   path=json_path.name))
        log_callback(t("log_messages.deviation_done", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    return {
        "species_analysed": done,
        "comparisons":      len(comparisons),
        "md_report":        str(md_path),
        "json_report":      str(json_path),
        "results":          results,
    }


def _write_deviation_report_md(
    results: Dict, comparisons: List[Dict], ts: str
) -> str:
    """Generates the Markdown comparison report."""
    lines = []
    lines.append(t("report.deviation_report_title"))
    lines.append("")
    lines.append(t("report.deviation_created", timestamp=ts))
    lines.append(t("report.deviation_species_count", n=len(results)))
    lines.append("")

    # ── Per-species statistics table ──────────────────────────────────────
    lines.append(t("report.deviation_stats_title"))
    lines.append("")
    lines.append(t("report.deviation_rate_col"))
    lines.append("|---|---|---|---|---|---|---|")

    for sp_name, r in sorted(results.items(),
                              key=lambda x: x[1]["deviation_data"]["deviation_rate"]):
        dev  = r["deviation_data"]
        stat = r["statistics"]
        chi2 = stat["chi2_vs_geometric"]
        shuf = r.get("shuffle_control") or {}
        disp = species_display(sp_name)
        dr   = f"{dev['deviation_rate']:.1%}"
        chi2_str = (f"{chi2['statistic']:.2f}" if chi2.get("statistic") else "—")
        p_str    = (f"{chi2['p_value']:.4f}" if chi2.get("p_value") is not None else "—")
        sig      = "✅" if chi2.get("significant") else "—"
        shuf_pct = f"{shuf.get('real_chi2_percentile',0)*100:.0f}th" if shuf.get("real_chi2_percentile") is not None else "—"
        shuf_sig = "✅" if shuf.get("is_significant") else ("⚠️" if shuf.get("real_chi2_percentile",0)>=0.90 else "—") if shuf else "—"
        lines.append(f"| {disp} | {dr} | {chi2_str} | {p_str} | {sig} | {shuf_pct} | {shuf_sig} |")

    lines.append("")
    lines.append(t("report.deviation_chi2_note"))
    lines.append("")

    # ── Comparison table ──────────────────────────────────────────────────
    if comparisons:
        lines.append(t("report.deviation_comparison_title"))
        lines.append("")
        lines.append(t("report.deviation_comparison_col"))
        lines.append("|---|---|---|---|---|")

        for c in sorted(comparisons,
                        key=lambda x: x.get("identity", 0) or 0, reverse=True):
            if c.get("identity") is None:
                continue
            same = "✅" if c["habitat1"] == c["habitat2"] else "—"
            lines.append(
                f"| {c['display1']} | {c['display2']} "
                f"| {c['identity']:.1%} | {c['interpretation']} | {same} |"
            )

    lines.append("")
    lines.append(t("report.end_of_report"))
    return "\n".join(lines)


# ============================================================
# SPEZIES-DATENBANK
# ============================================================

SPECIES_DB = {
    # Bacteria (10)
    "Escherichia coli (Bakterium)": {"accession": "NC_000913", "group": "bacteria"},
    "Bacillus subtilis (Bakterium)": {"accession": "NC_000964", "group": "bacteria"},
    "Mycobacterium tuberculosis (Bakterium)": {"accession": "NC_000962", "group": "bacteria"},
    "Streptococcus pneumoniae (Bakterium)": {"accession": "NC_003028", "group": "bacteria"},
    "Pseudomonas aeruginosa (Bakterium)": {"accession": "NC_002516", "group": "bacteria"},
    "Lactobacillus plantarum (Bakterium)": {"accession": "NC_004567", "group": "bacteria"},
    "Clostridium perfringens (Bakterium)": {"accession": "NC_003366", "group": "bacteria"},
    "Neisseria meningitidis (Bakterium)": {"accession": "NC_003112", "group": "bacteria"},
    "Helicobacter pylori (Bakterium)": {"accession": "NC_000915", "group": "bacteria"},
    "Vibrio cholerae (Bakterium)": {"accession": "NC_002505", "group": "bacteria"},
    # Eukaryotes (15)
    "Saccharomyces cerevisiae (Hefe, Chromosom I)": {"accession": "NC_001133", "group": "eukaryote"},
    "Homo sapiens (Mensch, Chromosom 7)": {"accession": "NC_000007", "group": "eukaryote"},
    "Mus musculus (Maus, Chromosom 17)": {"accession": "NC_000083", "group": "eukaryote"},
    "Drosophila melanogaster (Fruchtfliege, Chromosom 4)": {"accession": "NC_004353", "group": "eukaryote"},
    "Caenorhabditis elegans (Fadenwurm, Chromosom I)": {"accession": "NC_003279", "group": "eukaryote"},
    "Arabidopsis thaliana (Ackerschmalwand, Chromosom 1)": {"accession": "NC_003070", "group": "eukaryote"},
    "Danio rerio (Zebrafisch, Chromosom 1)": {"accession": "NC_007112", "group": "eukaryote"},
    "Rattus norvegicus (Ratte, Chromosom 1)": {"accession": "NC_005100", "group": "eukaryote"},
    "Pan troglodytes (Schimpanse, Chromosom 1)": {"accession": "NC_006408", "group": "eukaryote"},
    "Canis familiaris (Hund, Chromosom 1)": {"accession": "NC_006590", "group": "eukaryote"},
    "Gallus gallus (Huhn, Chromosom 1)": {"accession": "NC_006089", "group": "eukaryote"},
    "Xenopus tropicalis (Krallenfrosch, Chromosom 1)": {"accession": "NC_030660", "group": "eukaryote"},
    "Anopheles gambiae (Malariamücke, Chromosom 2)": {"accession": "NC_002084", "group": "eukaryote"},
    "Apis mellifera (Honigbiene, Chromosom 1)": {"accession": "NC_001566", "group": "eukaryote"},
    "Schizosaccharomyces pombe (Spalthefe, Chromosom I)": {"accession": "NC_003421", "group": "eukaryote"},
    # Living fossils (4)
    "Sphenodon punctatus (Brückenechse)": {"accession": "GCF_000506295.1", "group": "living_fossil"},
    "Nautilus pompilius (Perlboot)": {"accession": "GCF_000951145.1", "group": "living_fossil"},
    "Latimeria chalumnae (Quastenflosser)": {"accession": "GCF_000225785.1", "group": "living_fossil"},
    "Limulus polyphemus (Pfeilschwanzkrebs)": {"accession": "GCF_000517525.1", "group": "living_fossil"},
    # Additional species (7) – livestock, plants, model organisms
    "Bos taurus (Kuh, Chromosom 1)": {"accession": "NC_037328", "group": "eukaryote"},
    "Danio rerio (Zebrafisch, Chromosom 25)": {"accession": "NC_007136", "group": "eukaryote"},
    "Felis catus (Hauskatze, Chromosom A1)": {"accession": "NC_018723", "group": "eukaryote"},
    "Mus musculus (Maus, Chromosom 1)": {"accession": "NC_000067", "group": "eukaryote"},
    "Oryza sativa (Reis, Chromosom 1)": {"accession": "NC_029256", "group": "plant"},
    "Ovis aries (Schaf, Chromosom 1)": {"accession": "NC_040252", "group": "eukaryote"},
    "Triticum aestivum (Weizen, Chromosom 1A)": {"accession": "NC_057571", "group": "plant"},
    # Amphibians (4)
    # Ambystoma mexicanum: NC_052072.1 = Chr1, RefSeq GCF_002915635.3
    "Ambystoma mexicanum (Axolotl, Chromosom 1)": {"accession": "NC_052072.1", "group": "eukaryote"},
    # Bufo bufo: GCA_905171765.1 = best available assembly, no NC_ chromosomes published
    "Bufo bufo (Erdkröte, Chromosom 1)": {"accession": "GCA_905171765.1", "group": "eukaryote"},
    # Cynops pyrrhogaster: GCA_013403275.1 = only available assembly, no NC_ chromosomes
    "Cynops pyrrhogaster (Feuerbauchmolch, Chromosom 1)": {"accession": "GCA_013403275.1", "group": "eukaryote"},
    # Rana temporaria: NC_053152.1 = Chr1, RefSeq GCF_905171765.1 (not to be confused with Bufo bufo GCA)
    "Rana temporaria (Grasfrosch, Chromosom 1)": {"accession": "NC_053152.1", "group": "eukaryote"},
}

# ============================================================
# SPECIES DISPLAY NAME TRANSLATION
# Internal SPECIES_DB keys (German, stable for JSON compatibility)
# are mapped to i18n keys. Display names live in the language files.
# ============================================================

# Maps German internal key → i18n key under species.names.*
_SPECIES_I18N_KEY = {
    "Escherichia coli (Bakterium)":                          "escherichia_coli",
    "Bacillus subtilis (Bakterium)":                         "bacillus_subtilis",
    "Mycobacterium tuberculosis (Bakterium)":                "mycobacterium_tuberculosis",
    "Streptococcus pneumoniae (Bakterium)":                  "streptococcus_pneumoniae",
    "Pseudomonas aeruginosa (Bakterium)":                    "pseudomonas_aeruginosa",
    "Lactobacillus plantarum (Bakterium)":                   "lactobacillus_plantarum",
    "Clostridium perfringens (Bakterium)":                   "clostridium_perfringens",
    "Neisseria meningitidis (Bakterium)":                    "neisseria_meningitidis",
    "Helicobacter pylori (Bakterium)":                       "helicobacter_pylori",
    "Vibrio cholerae (Bakterium)":                           "vibrio_cholerae",
    "Saccharomyces cerevisiae (Hefe, Chromosom I)":          "saccharomyces_cerevisiae",
    "Homo sapiens (Mensch, Chromosom 7)":                    "homo_sapiens",
    "Mus musculus (Maus, Chromosom 17)":                     "mus_musculus_chr17",
    "Drosophila melanogaster (Fruchtfliege, Chromosom 4)":   "drosophila_melanogaster",
    "Caenorhabditis elegans (Fadenwurm, Chromosom I)":       "caenorhabditis_elegans",
    "Arabidopsis thaliana (Ackerschmalwand, Chromosom 1)":   "arabidopsis_thaliana",
    "Danio rerio (Zebrafisch, Chromosom 1)":                 "danio_rerio_chr1",
    "Rattus norvegicus (Ratte, Chromosom 1)":                "rattus_norvegicus",
    "Pan troglodytes (Schimpanse, Chromosom 1)":             "pan_troglodytes",
    "Canis familiaris (Hund, Chromosom 1)":                  "canis_familiaris",
    "Gallus gallus (Huhn, Chromosom 1)":                     "gallus_gallus",
    "Xenopus tropicalis (Krallenfrosch, Chromosom 1)":       "xenopus_tropicalis",
    "Anopheles gambiae (Malariamücke, Chromosom 2)":         "anopheles_gambiae",
    "Apis mellifera (Honigbiene, Chromosom 1)":              "apis_mellifera",
    "Schizosaccharomyces pombe (Spalthefe, Chromosom I)":    "schizosaccharomyces_pombe",
    "Sphenodon punctatus (Brückenechse)":                    "sphenodon_punctatus",
    "Nautilus pompilius (Perlboot)":                         "nautilus_pompilius",
    "Latimeria chalumnae (Quastenflosser)":                  "latimeria_chalumnae",
    "Limulus polyphemus (Pfeilschwanzkrebs)":                "limulus_polyphemus",
    "Bos taurus (Kuh, Chromosom 1)":                         "bos_taurus",
    "Danio rerio (Zebrafisch, Chromosom 25)":                "danio_rerio_chr25",
    "Felis catus (Hauskatze, Chromosom A1)":                 "felis_catus",
    "Mus musculus (Maus, Chromosom 1)":                      "mus_musculus_chr1",
    "Oryza sativa (Reis, Chromosom 1)":                      "oryza_sativa",
    "Ovis aries (Schaf, Chromosom 1)":                       "ovis_aries",
    "Triticum aestivum (Weizen, Chromosom 1A)":              "triticum_aestivum",
    "Ambystoma mexicanum (Axolotl, Chromosom 1)":            "ambystoma_mexicanum",
    "Bufo bufo (Erdkröte, Chromosom 1)":                     "bufo_bufo",
    "Cynops pyrrhogaster (Feuerbauchmolch, Chromosom 1)":    "cynops_pyrrhogaster",
    "Rana temporaria (Grasfrosch, Chromosom 1)":             "rana_temporaria",
}

def species_display(internal_key: str) -> str:
    """Returns the translated display name for a species via the language files."""
    i18n_key = _SPECIES_I18N_KEY.get(internal_key)
    if i18n_key:
        return t(f"species.names.{i18n_key}", default=internal_key)
    return internal_key



# ============================================================
# VISUALISIERUNGEN
# ============================================================

def plot_results(result: Dict[str, Any], species_name: str, method_id: str):
    """Creates method-specific visualisations."""
    try:
        fig, ax = plt.subplots(figsize=(12, 6))
        safe_species = species_name.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "")
        title = f"{species_name}\n{result.get('method_name', method_id)}"

        # ── 1. Difference spectrum (vertical lines) ─────────────────────────
        if method_id == 'two_thz':
            distances = result.get('large_distances', [])
            if distances:
                ax.vlines(range(len(distances)), 0, distances, color='steelblue', alpha=0.6, linewidth=0.8)
                if result.get('rhythm'):
                    ax.axhline(y=result['rhythm'], color='red', linestyle='--',
                               label=f"Dominant rhythm: {result['rhythm']} bp")
                    ax.legend()
                ax.set_title(f"Difference Spectrum – distances > 1000 bp\n{title}")
                ax.set_xlabel("Transition (index)")
                ax.set_ylabel("Distance (bp)")
            else:
                ax.text(0.5, 0.5, "No large distances found",
                        transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 2. Fibonacci: Balkendiagramm Match-Raten ─────────────────────────
        elif method_id == 'fibonacci':
            variants = result.get('fibonacci_variants', {})
            if variants:
                names  = [v['name'] for v in variants.values()]
                rates  = [v['match_rate'] for v in variants.values()]
                colors = ['#4C72B0', '#DD8452', '#55A868', '#C44E52']
                bars = ax.bar(names, rates, color=colors[:len(names)], edgecolor='white')
                ax.bar_label(bars, fmt='%.1f%%', padding=3)
                ax.set_ylim(0, max(rates) * 1.2 + 5)
                ax.set_title(f"Fibonacci match rates per variant\n{title}")
                ax.set_ylabel(t("analysis.plot_match_rate"))
                ax.set_xlabel("Fibonacci-Variante")
            else:
                ax.text(0.5, 0.5, t("analysis.no_variant_data"), transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 3. Golden Ratio: Balkendiagramm ──────────────────────────────
        elif method_id == 'golden_ratio':
            match_rate  = result.get('match_rate', 0)
            total       = result.get('ratios_analyzed', 1) or 1
            golden_n    = result.get('golden_ratio_matches', 0)
            non_golden  = total - golden_n
            bars = ax.bar(['Golden Ratio', 'Other Ratios'],
                          [golden_n, non_golden],
                          color=['#FFD700', '#AAAAAA'], edgecolor='white')
            ax.bar_label(bars, padding=3)
            ax.set_title(f"Golden Ratio – Match rate: {match_rate:.1f}%\n{title}")
            ax.set_ylabel("Number of ratios")

        # ── 4. Power-Law: Log-Log-Plot ────────────────────────────────────────
        elif method_id == 'power_law':
            centers = result.get('hist_bin_centers', [])
            counts  = result.get('hist_counts', [])
            if centers and counts:
                ax.scatter(centers, counts, s=20, color='steelblue', zorder=3, label='Beobachtet')
                ax.set_xscale('log')
                ax.set_yscale('log')
                # Fit-Linie
                if result.get('fit_slope') is not None and result.get('fit_intercept') is not None:
                    x_fit = np.array(centers)
                    y_fit = np.exp(result['fit_intercept']) * x_fit ** result['fit_slope']
                    ax.plot(x_fit, y_fit, 'r--', linewidth=1.5,
                            label=f"Fit: α={result.get('power_law_exponent', 0):.2f}, R²={result.get('fit_quality_r_squared', 0):.3f}")
                ax.legend()
                ax.set_title(f"Power-Law – {result.get('interpretation', '')}\n{title}")
                ax.set_xlabel("Abstand (bp, log)")
                ax.set_ylabel("frequency count (log)")
            else:
                ax.text(0.5, 0.5, "Zu wenige Datenpunkte", transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 5. CGR: Punktdiagramm ─────────────────────────────────────────────
        elif method_id == 'cgr':
            cgr_data = result.get('cgr_data', {})
            points   = cgr_data.get('points', [])
            if points:
                pts   = np.array(points)
                step  = max(1, len(pts) // 8000)
                sub   = pts[::step]
                ax.scatter(sub[:, 0], sub[:, 1], s=0.5, alpha=0.3, c='steelblue', rasterized=True)
                for label, (x, y) in [('A', (-0.03, -0.03)), ('T', (1.01, -0.03)),
                                       ('C', (-0.03, 1.01)),  ('G', (1.01, 1.01))]:
                    ax.text(x, y, label, transform=ax.transAxes, fontsize=11, fontweight='bold', color='red')
                # Metriken als Annotation
                m = result.get('cgr_metrics', {})
                if m:
                    info = (f"corr_xy={m.get('correlation_xy', 0):.3f}  "
                            f"corr_x_yinv={m.get('correlation_x_yinv', 0):.3f}\n"
                            f"h_peaks={m.get('horizontal_peaks', {}).get('peak_count', '?')}  "
                            f"v_peaks={m.get('vertical_peaks', {}).get('peak_count', '?')}  "
                            f"center={m.get('center_density', 0):.4f}\n"
                            f"fractal_dim={m.get('fractal_dimension', 0):.3f}")
                    ax.text(0.01, 0.99, info, transform=ax.transAxes, fontsize=7.5,
                            va='top', ha='left', family='monospace',
                            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
                ax.set_title(f"CGR – Fraktale Dimension: {result.get('fractal_dimension', 0):.3f}\n{title}")
                ax.set_xlabel("X")
                ax.set_ylabel("Y")
                ax.set_aspect('equal')
                ax.set_xlim(-0.02, 1.02)
                ax.set_ylim(-0.02, 1.02)
            else:
                ax.text(0.5, 0.5, t("analysis.no_cgr_points"), transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 6. Frequency Profile: frequency over position ────────────────────
        elif method_id == 'piano_roll':
            freq_vals = result.get('freq_values_sample', [])
            if freq_vals:
                x = np.arange(len(freq_vals))
                # colour points by frequency
                freq_color_map = {48.5: '#4C72B0', 49.5: '#55A868', 50.5: '#DD8452', 51.5: '#C44E52'}
                freq_labels    = {48.5: 'A', 49.5: 'C', 50.5: 'T', 51.5: 'G'}
                for fval, color in freq_color_map.items():
                    mask = np.array(freq_vals) == fval
                    if np.any(mask):
                        ax.scatter(x[mask], np.array(freq_vals)[mask], s=1, c=color,
                                   alpha=0.4, label=freq_labels[fval], rasterized=True)
                ax.set_title(f"Frequency Profile – frequency over position\n{title}")
                ax.set_xlabel("Position (bp)")
                ax.set_ylabel(t("analysis.plot_frequency_thz"))
                ax.set_yticks([48.5, 49.5, 50.5, 51.5])
                ax.set_yticklabels(['A (48.5)', 'C (49.5)', 'T (50.5)', 'G (51.5)'])
                ax.legend(loc='upper right', markerscale=5, framealpha=0.7)
            else:
                ax.text(0.5, 0.5, t("analysis.no_freq_data"), transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 7. Autokorrelation: Liniendiagramm mit Peaks ──────────────────────
        elif method_id == 'autocorr':
            autocorr_vals = result.get('autocorr_values', [])
            if autocorr_vals:
                ac = np.array(autocorr_vals)
                ax.plot(ac[:500], color='steelblue', linewidth=0.8, alpha=0.9)
                mean_val = np.mean(ac[10:min(500, len(ac))])
                ax.axhline(y=mean_val, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
                # Peaks markieren
                peaks = result.get('peaks', [])
                for idx, val in peaks[:5]:
                    if idx < 500:
                        ax.axvline(x=idx, color='orange', linestyle=':', linewidth=1, alpha=0.8)
                        ax.annotate(f"{idx} bp", xy=(idx, val), xytext=(idx+5, val),
                                    fontsize=7, color='darkorange')
                if result.get('dominant_period'):
                    ax.axvline(x=result['dominant_period'], color='red', linestyle='--',
                               linewidth=1.2, label=f"Dom. period: {result['dominant_period']} bp")
                    ax.legend()
                ax.set_title(f"Autocorrelation\n{title}")
                ax.set_xlabel("Lag (bp)")
                ax.set_ylabel(t("analysis.correlation_label", default="Correlation"))
            else:
                ax.text(0.5, 0.5, t("analysis.no_autocorr_data"), transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 8. GC-Content: line chart over chromosome position ──────────────
        elif method_id == 'gc_content':
            gc_vals = result.get('gc_values', [])
            if gc_vals:
                step_size = result.get('step_size', CONFIG.gc_step_size)
                positions_kb = [i * step_size / 1000 for i in range(len(gc_vals))]
                ax.plot(positions_kb, gc_vals, color='steelblue', linewidth=0.6, alpha=0.8)
                mean_gc = result.get('mean_gc_percent', np.mean(gc_vals))
                ax.axhline(y=mean_gc, color='red', linestyle='--', linewidth=1,
                           label=f"average: {mean_gc:.1f}%")
                ax.fill_between(positions_kb, gc_vals, mean_gc,
                                where=[v > mean_gc for v in gc_vals],
                                alpha=0.15, color='red')
                ax.fill_between(positions_kb, gc_vals, mean_gc,
                                where=[v <= mean_gc for v in gc_vals],
                                alpha=0.15, color='blue')
                ax.set_title(f"GC-Content-Variation (Fenster: {result.get('window_size', CONFIG.gc_window_size)} bp)\n{title}")
                ax.set_xlabel("Chromosomenposition (kb)")
                ax.set_ylabel(t("analysis.plot_gc_content"))
                ax.set_ylim(0, 100)
                ax.legend()
            else:
                ax.text(0.5, 0.5, t("analysis.no_gc_data"), transform=ax.transAxes, ha='center', va='center')
                ax.set_title(title)

        # ── 9. Dinukleotid: Heatmap der 4×4 Matrix ───────────────────────────
        elif method_id == 'dinucleotide':
            matrix = result.get('transition_matrix', {})
            bases  = ['A', 'C', 'T', 'G']
            if matrix:
                mat_arr = np.array([[matrix[b1][b2] for b2 in bases] for b1 in bases])
                ax.set_visible(False)
                fig.clear()
                ax2 = fig.add_subplot(111)
                im = ax2.imshow(mat_arr, cmap='YlOrRd', aspect='auto', vmin=0)
                fig.colorbar(im, ax=ax2, label='Transition probability')
                ax2.set_xticks(range(4))
                ax2.set_yticks(range(4))
                ax2.set_xticklabels(bases)
                ax2.set_yticklabels(bases)
                ax2.set_xlabel("Folge-Base")
                ax2.set_ylabel(t("analysis.plot_source_base"))
                # Werte in Zellen
                for i in range(4):
                    for j in range(4):
                        ax2.text(j, i, f"{mat_arr[i, j]:.3f}", ha='center', va='center',
                                 fontsize=9, color='black' if mat_arr[i, j] < 0.4 else 'white')
                ax2.set_title(f"Dinucleotide transition matrix\n{title}")

        else:
            ax.text(0.5, 0.5, f"No plot for method: {method_id}",
                    transform=ax.transAxes, ha='center', va='center')
            ax.set_title(title)

        plt.tight_layout()
        plot_path = CONFIG.plots_dir / f"{safe_species}_{method_id}.png"
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close(fig)
        return str(plot_path)

    except Exception as e:
        logging.getLogger('DNARhythmAnalyzer').warning(f"Plot-Erstellung fehlgeschlagen ({method_id}): {e}")
        plt.close('all')
        return None

# ============================================================
# EXPORT-FUNKTIONEN
# ============================================================

def export_to_excel(all_results: Dict[str, Any], filename: Path) -> str:
    """Exportiert Ergebnisse nach Excel"""
    try:
        with pd.ExcelWriter(filename) as writer:
            # Main overview
            summary_data = []
            for method_id, results in all_results.items():
                if isinstance(results, dict) and 'completed' in results:
                    summary_data.append({
                        'Method': method_id,
                        'Completed': results.get('completed', 0),
                        'Failed': results.get('failed', 0),
                        'Total': results.get('total', 0)
                    })
            
            if summary_data:
                pd.DataFrame(summary_data).to_excel(writer, sheet_name='Summary', index=False)
            
            # Ergebnisse pro Methode
            for method_id, results in all_results.items():
                if isinstance(results, dict) and 'details' in results:
                    details = []
                    for detail in results['details']:
                        if detail.get('success'):
                            details.append({
                                'Species': detail.get('species', ''),
                                'Accession': detail.get('accession', ''),
                                'Group': detail.get('group', ''),
                                'Success': detail.get('success', False)
                            })
                    if details:
                        df = pd.DataFrame(details)
                        # Truncate sheet name (max 31 chars)
                        sheet_name = method_id[:31]
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
        
        return str(filename)
    except Exception as e:
        logging.getLogger('DNARhythmAnalyzer').error(f"Excel-Export fehlgeschlagen: {e}")
        return None

def export_to_csv(results: Dict[str, Any], filename: Path) -> str:
    """Exportiert Ergebnisse nach CSV"""
    try:
        rows = []
        for method_id, method_results in results.items():
            if isinstance(method_results, dict) and 'details' in method_results:
                for detail in method_results['details']:
                    rows.append({
                        'method': method_id,
                        'species': detail.get('species', ''),
                        'accession': detail.get('accession', ''),
                        'group': detail.get('group', ''),
                        'success': detail.get('success', False)
                    })
        
        if rows:
            df = pd.DataFrame(rows)
            df.to_csv(filename, index=False)
            return str(filename)
        return None
    except Exception as e:
        logging.getLogger('DNARhythmAnalyzer').error(f"CSV-Export fehlgeschlagen: {e}")
        return None

# ============================================================
# VERGLEICHSANALYSE
# ============================================================

def compare_species_groups(results_by_group: Dict[str, List[float]], 
                          method_name: str) -> Dict[str, Any]:
    """Vergleicht verschiedene Spezies-Gruppen statistisch"""
    comparisons = {}
    
    groups = list(results_by_group.keys())
    for i in range(len(groups)):
        for j in range(i + 1, len(groups)):
            group1 = groups[i]
            group2 = groups[j]
            data1 = results_by_group[group1]
            data2 = results_by_group[group2]
            
            if len(data1) > 1 and len(data2) > 1:
                # t-Test
                t_stat, t_pvalue = ttest_ind(data1, data2)
                
                # Mann-Whitney U Test (robuster)
                u_stat, u_pvalue = mannwhitneyu(data1, data2, alternative='two-sided')
                
                comparisons[f"{group1}_vs_{group2}"] = {
                    "group1": {
                        "name": group1,
                        "n": len(data1),
                        "mean": np.mean(data1),
                        "std": np.std(data1),
                        "median": np.median(data1)
                    },
                    "group2": {
                        "name": group2,
                        "n": len(data2),
                        "mean": np.mean(data2),
                        "std": np.std(data2),
                        "median": np.median(data2)
                    },
                    "t_test": {
                        "statistic": float(t_stat),
                        "p_value": float(t_pvalue),
                        "significant": bool(t_pvalue < 0.05)
                    },
                    "mann_whitney_u": {
                        "statistic": float(u_stat),
                        "p_value": float(u_pvalue),
                        "significant": bool(u_pvalue < 0.05)
                    },
                    "mean_difference": float(np.mean(data1) - np.mean(data2)),
                    "effect_size_cohens_d": float((np.mean(data1) - np.mean(data2)) / np.sqrt((np.std(data1)**2 + np.std(data2)**2) / 2))
                }
    
    return {
        "method": method_name,
        "groups_analyzed": list(results_by_group.keys()),
        "comparisons": comparisons
    }

# ============================================================
# PARALLEL ANALYSIS
# ============================================================

def run_parallel_analysis(species_list: List[Tuple[str, Dict]], 
                         method_id: str, 
                         method_name: str,
                         log_callback: Optional[Callable] = None) -> List[Dict]:
    """Runs analyses in parallel for multiple species."""
    results = []
    
    with ThreadPoolExecutor(max_workers=CONFIG.max_parallel_workers) as executor:
        future_to_species = {
            executor.submit(run_single_analysis_threaded, species_name, species_info, 
                          method_id, method_name): (species_name, species_info)
            for species_name, species_info in species_list
        }
        
        for future in as_completed(future_to_species):
            species_name, _ = future_to_species[future]
            try:
                result = future.result(timeout=300)
                if result:
                    results.append(result)
                    if log_callback:
                        log_callback(t("analysis.completed", species=species_name))
                else:
                    if log_callback:
                        log_callback(t("analysis.failed_species", species=species_name))
            except Exception as e:
                if log_callback:
                    log_callback(t("log_messages.error_occurred", error=f"{species_name}: {e}"))
    
    return results

def run_single_analysis_threaded(species_name: str, species_info: Dict, 
                                 method_id: str, method_name: str) -> Optional[Dict]:
    """Thread-optimised single analysis."""
    try:
        # Short logging function for threads
        def thread_log(msg):
            pass  # Suppress logging in thread (GUI not thread-safe)
        
        fasta = get_or_fetch_genome(species_info["accession"], None)
        if not fasta:
            return None
        
        reader = GenomeReader(fasta)
        seq = reader.get_sequence(CONFIG.max_seq_length)
        
        if len(seq) < 1000:
            return None
        
        result = run_method(method_id, seq, None,
                           species_name=species_name)
        result["species"] = species_name
        result["species_display"] = species_display(species_name)
        result["accession"] = species_info["accession"]
        result["group"] = species_info["group"]
        result["method_id"] = method_id
        result["method_name"] = method_name
        result["timestamp"] = datetime.now().isoformat()
        
        # Visualisation erstellen
        plot_path = plot_results(result, species_name, method_id)
        if plot_path:
            result["plot_path"] = plot_path
        
        return result
    except Exception as e:
        logging.getLogger('DNARhythmAnalyzer').error(f"Error in {species_name}: {e}")
        return None

# ============================================================
# BATCH ANALYSIS
# ============================================================

def run_batch_analysis(species_list: List[Tuple[str, Dict]], method_id: str, 
                      method_name: str, log_callback: Optional[Callable] = None,
                      stop_event: Optional[threading.Event] = None) -> Dict[str, Any]:
    """Runs batch analysis with parallelisation and caching."""
    cache = AnalysisCache(CONFIG.cache_db)
    results_summary = {
        "method": method_name,
        "method_id": method_id,
        "total": len(species_list),
        "completed": 0,
        "failed": 0,
        "cached": 0,
        "details": []
    }
    
    all_results = []
    
    for i, (species_name, species_info) in enumerate(species_list, 1):
        # Stopp-Check
        if stop_event and stop_event.is_set():
            if log_callback:
                log_callback(t("log_messages.stopped"))
            break

        if log_callback:
            if method_id == "two_thz":
                _d, _ds, _ = _get_species_optimal_delta(species_info["accession"])
                _icon   = "🎯" if _ds == "optimized" else "📐"
                log_callback(f"\n[{i}/{len(species_list)}] {species_display(species_name)} "
                             f"{_icon} Δ={_d:.2f} ({_ds})")
            else:
                log_callback(f"\n[{i}/{len(species_list)}] {species_display(species_name)}")
        
        try:
            # Skip if error-free result file already exists
            filename = get_safe_filename(method_id, species_name, species_info["accession"])
            filepath = CONFIG.results_dir / filename
            if filepath.exists():
                # Check if existing file contains an error result
                try:
                    with open(filepath, 'r', encoding='utf-8') as _f:
                        _existing = json.load(_f)
                    if "error" not in _existing:
                        if log_callback:
                            log_callback(t("analysis.skipped_exists", filename=filename))
                        results_summary["completed"] += 1
                        results_summary["cached"] += 1
                        results_summary["details"].append({
                            "species": species_name,
                            "accession": species_info["accession"],
                            "group": species_info["group"],
                            "success": True,
                            "cached": True
                        })
                        continue
                    else:
                        if log_callback:
                            log_callback(t("analysis.recalculating"))
                        filepath.unlink()  # Delete old error file
                except Exception:
                    filepath.unlink(missing_ok=True)  # Delete corrupt file
            # Check cache
            fasta = get_or_fetch_genome(species_info["accession"], log_callback)
            if not fasta:
                results_summary["failed"] += 1
                continue
            
            reader = GenomeReader(fasta)
            seq = reader.get_sequence(CONFIG.max_seq_length)
            
            # Try cache
            cached_result = cache.get(method_id, species_info["accession"], seq)
            if cached_result and "error" not in cached_result:
                if log_callback:
                    log_callback(t("analysis.cached"))
                result = cached_result
                results_summary["cached"] += 1
            else:
                if cached_result and "error" in cached_result:
                    if log_callback:
                        log_callback(t("analysis.recalculating"))
                result = run_method(method_id, seq, log_callback,
                                    species_name=species_name)
                cache.set(method_id, species_info["accession"], seq, result)
            
            if result and "error" not in result:
                result["species"] = species_name
                result["species_display"] = species_display(species_name)
                result["accession"] = species_info["accession"]
                result["accession"] = species_info["accession"]
                result["group"] = species_info["group"]
                result["method_id"] = method_id
                result["method_name"] = method_name
                result["timestamp"] = datetime.now().isoformat()
                
                # Visualisation
                plot_path = plot_results(result, species_name, method_id)
                if plot_path:
                    result["plot_path"] = plot_path
                
                # Save
                filename = get_safe_filename(method_id, species_name, species_info["accession"])
                filepath = CONFIG.results_dir / filename
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
                
                results_summary["completed"] += 1
                results_summary["details"].append({
                    "species": species_name,
                    "accession": species_info["accession"],
                    "group": species_info["group"],
                    "success": True,
                    "cached": False
                })
                all_results.append(result)
            else:
                results_summary["failed"] += 1
                results_summary["details"].append({
                    "species": species_name,
                    "success": False,
                    "error": result.get("error", "Unknown error") if result else "No result"
                })
                
        except Exception as e:
            if log_callback:
                log_callback(t("log_messages.error_occurred", error=e))
            results_summary["failed"] += 1
            results_summary["details"].append({
                "species": species_name,
                "success": False,
                "error": str(e)
            })
    
    # Excel and CSV export
    excel_path = CONFIG.results_dir / f"BATCH_{method_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    csv_path = CONFIG.results_dir / f"BATCH_{method_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    export_to_excel({method_id: results_summary}, excel_path)
    export_to_csv({method_id: results_summary}, csv_path)
    
    # Save JSON
    summary_filename = f"BATCH_{method_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path = CONFIG.results_dir / summary_filename
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(results_summary, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    
    if log_callback:
        log_callback(f"\n📊 Batch summary saved: {summary_filename}")
        log_callback(f"📊 Excel: {excel_path.name}")
        log_callback(f"📊 CSV: {csv_path.name}")
    
    # Group comparison
    if all_results:
        group_data = {}
        for result in all_results:
            group = result.get("group", "unknown")
            key_finding = extract_key_finding(result, method_id)
            if key_finding and isinstance(key_finding, (int, float)):
                group_data.setdefault(group, []).append(key_finding)
        
        if len(group_data) > 1:
            comparison = compare_species_groups(group_data, method_name)
            comparison_path = CONFIG.results_dir / f"COMPARISON_{method_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(comparison_path, 'w', encoding='utf-8') as f:
                json.dump(comparison, f, indent=2, cls=NumpyEncoder)
            if log_callback:
                log_callback(f"📊 Group comparison: {comparison_path.name}")
    
    return results_summary

def extract_key_finding(result: Dict, method_id: str) -> any:
    """Extracts numeric key value for comparisons."""
    try:
        if method_id == "two_thz":
            return result.get('large_distances_count')
        elif method_id == "fibonacci":
            return result.get('best_match_rate', 0)
        elif method_id == "golden_ratio":
            return result.get('match_rate', 0)
        elif method_id == "power_law":
            return result.get('power_law_exponent')
        elif method_id == "cgr":
            return result.get('fractal_dimension')
        elif method_id == "autocorr":
            return result.get('dominant_period')
        elif method_id == "gc_content":
            return result.get('mean_gc_percent')
    except:
        return None
    return None

def get_safe_filename(method_id: str, species_key: str, accession: str) -> str:
    """Creates a safe filename using the internal species key (language-independent).
    The internal key is always the German SPECIES_DB key — stable across languages."""
    # Use the INTERNAL key (always German SPECIES_DB key) — never the translated display name
    safe_name = species_key.replace(" ", "_").replace("(", "").replace(")", "").replace(",", "")
    safe_name = safe_name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    safe_name = safe_name.replace("ß", "ss")
    return f"{method_id}_{accession}_{safe_name}.json"

def run_all_methods_batch(log_callback: Optional[Callable] = None) -> Dict[str, Any]:
    """Runs all methods sequentially in batch mode."""
    if log_callback:
        log_callback(f"\n{'='*80}")
        log_callback(t("log_messages.start_all_methods", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        log_callback(f"{'='*80}\n")
    
    species_list = [(name, info) for name, info in SPECIES_DB.items()]
    all_results_summary = {
        "timestamp": datetime.now().isoformat(),
        "methods": {},
        "total_species": len(species_list),
        "total_methods": 0,
        "total_analyses": 0,
        "successful_analyses": 0
    }
    
    METHODS = {
        "1. Differenzspektrum (Δ=2.0)": {"id": "two_thz"},
        "2. Fibonacci-distances": {"id": "fibonacci"},
        "3. Golden Ratio (1.618)": {"id": "golden_ratio"},
        "4. Power-Law-Verteilung": {"id": "power_law"},
        "5. CGR (Chaos Game Representation)": {"id": "cgr"},
        "6. Frequenzprofil": {"id": "piano_roll"},
        "7. Autocorrelation (Periodicity)": {"id": "autocorr"},
        "8. GC-Content-Variation": {"id": "gc_content"},
        "9. Dinukleotid-Bias": {"id": "dinucleotide"}
    }
    
    for method_name, method_info in METHODS.items():
        method_id = method_info["id"]
        
        if log_callback:
            log_callback(f"\n{'#'*80}")
            log_callback(t("log_messages.method_header", name=method_name))
            log_callback(f"{'#'*80}\n")
        
        try:
            result = run_batch_analysis(species_list, method_id, method_name, log_callback)
            all_results_summary["methods"][method_id] = {
                "name": method_name,
                "completed": result["completed"],
                "failed": result["failed"],
                "total": result["total"],
                "cached": result.get("cached", 0)
            }
            all_results_summary["total_methods"] += 1
            all_results_summary["total_analyses"] += result["total"]
            all_results_summary["successful_analyses"] += result["completed"]
        except Exception as e:
            if log_callback:
                log_callback(t("log_messages.error_occurred", error=f"{method_name}: {e}"))
            all_results_summary["methods"][method_id] = {"error": str(e)}
    
    # Gesamtergebnis speichern
    summary_filename = f"ALL_METHODS_BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    summary_path = CONFIG.results_dir / summary_filename
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(all_results_summary, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    
    # Excel-Bericht
    excel_path = CONFIG.results_dir / f"ALL_METHODS_BATCH_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    export_to_excel(all_results_summary["methods"], excel_path)
    
    if log_callback:
        log_callback(f"\n{'='*80}")
        log_callback(t("log_messages.all_methods_completed"))
        log_callback(f"{'='*80}")
        log_callback(t("log_messages.total_methods", n=all_results_summary["total_methods"]))
        log_callback(t("log_messages.total_analyses", n=all_results_summary["total_analyses"]))
        log_callback(t("log_messages.successful_analyses", n=all_results_summary["successful_analyses"]))
        log_callback(t("log_messages.full_report", path=summary_path))
        log_callback(t("log_messages.excel_report", path=excel_path))
    
    return all_results_summary

def consolidate_all_results(log_callback: Optional[Callable] = None) -> Tuple[Dict, Path, Path]:
    """Konsolidiert alle vorhandenen Ergebnis-JSONs zu einem Gesamtbericht"""
    
    if log_callback:
        log_callback(t("analysis.consolidating"))
    
    result_files = list(CONFIG.results_dir.glob("*.json"))
    result_files = [f for f in result_files if not f.name.startswith("BATCH_") 
                    and not f.name.startswith("ALL_METHODS_BATCH_")
                    and not f.name.startswith("FINAL_COMPLETE_REPORT_")
                    and not f.name.startswith("COMPARISON_")]
    
    if log_callback:
        log_callback(t("analysis.result_files_found", count=len(result_files)))
    
    consolidated = {
        "report_type": "FINAL_COMPLETE_REPORT",
        "timestamp": datetime.now().isoformat(),
        "total_files": len(result_files),
        "methods": {},
        "species": {},
        "results_matrix": {},
        "visualizations": {}
    }
    
    METHODS = {
        "two_thz":      t("methods.two_thz"),
        "fibonacci":    t("methods.fibonacci"),
        "golden_ratio": t("methods.golden_ratio"),
        "power_law":    t("methods.power_law"),
        "cgr":          t("methods.cgr"),
        "piano_roll":   t("methods.piano_roll"),
        "autocorr":     t("methods.autocorr"),
        "gc_content":   t("methods.gc_content"),
        "dinucleotide": t("methods.dinucleotide"),
    }
    
    for method_id in METHODS.keys():
        consolidated["methods"][method_id] = METHODS[method_id]
        consolidated["results_matrix"][method_id] = {}
    
    for species_name in SPECIES_DB.keys():
        consolidated["species"][species_name] = {
            "accession": SPECIES_DB[species_name]["accession"],
            "group": SPECIES_DB[species_name]["group"]
        }
        for method_id in METHODS.keys():
            consolidated["results_matrix"][method_id][species_name] = None
    
    loaded_count = 0
    cgr_metrics_by_species = {}   # For CGR table

    for filepath in result_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Delta-optimisation files have a different structure — skip here,
            # they are processed separately below via the delta section
            if filepath.name.startswith("delta_optimization"):
                continue
            # Batch summary files also have different structure
            if filepath.name.startswith("BATCH_") or filepath.name.startswith("FINAL_"):
                continue
            
            method_id    = data.get("method_id")
            # ── Language-independent species resolution ───────────────────────
            # New files store "species" as internal key + "accession"
            # Legacy files may store translated species name — resolve via accession
            accession    = data.get("accession")
            species_name = data.get("species")   # may be translated in legacy files

            # Resolve to internal SPECIES_DB key using accession (most reliable)
            if accession:
                for db_key, db_info in SPECIES_DB.items():
                    if db_info["accession"] == accession:
                        species_name = db_key   # always use internal key
                        break

            # Fallback: species field is already internal key
            if species_name and species_name not in SPECIES_DB:
                # Try to find by display name match (legacy translated files)
                for db_key in SPECIES_DB:
                    if species_name in (db_key, species_display(db_key)):
                        species_name = db_key
                        break
            
            if method_id and species_name and method_id in consolidated["results_matrix"]:
                key_finding = extract_key_finding(data, method_id)
                
                if key_finding is not None:
                    if isinstance(key_finding, float):
                        key_finding = f"{key_finding:.3f}"

                    # p-value for 2-THz: "83 Δ=1.5🎯 (p=0.002) ✅" or "83 Δ=2.0 (p=0.124)"
                    if method_id == "two_thz":
                        sig          = data.get("statistical_significance", {})
                        p_value      = sig.get("p_value")
                        significant  = sig.get("significant", False)
                        delta_used   = data.get("delta_applied", data.get("delta", 2.0))
                        delta_src    = data.get("delta_source", "default")
                        delta_icon   = "🎯" if delta_src == "optimized" else ""
                        if p_value is not None:
                            key_finding = (f"{key_finding} "
                                          f"Δ={delta_used:.1f}{delta_icon} "
                                          f"(p={p_value:.3f})")
                            if significant:
                                key_finding += " ✅"

                    consolidated["results_matrix"][method_id][species_name] = str(key_finding)
                else:
                    consolidated["results_matrix"][method_id][species_name] = "✓"
                
                if data.get("plot_path"):
                    consolidated["visualizations"][f"{species_name}_{method_id}"] = data["plot_path"]

                # CGR metrics
                if method_id == "cgr" and "cgr_metrics" in data:
                    cgr_metrics_by_species[species_name] = {
                        "group": data.get("group", "?"),
                        **data["cgr_metrics"]
                    }
                
                loaded_count += 1
                
        except Exception as e:
            if log_callback:
                log_callback(t("analysis.error_reading_file", filename=filepath.name, error=e))

    consolidated["cgr_metrics"] = cgr_metrics_by_species
    
    if log_callback:
        log_callback(t("analysis.successfully_loaded", count=loaded_count))
    
    # Markdown-Bericht
    md_content = []
    md_content.append(t("report.final_report_title"))
    md_content.append("")
    md_content.append(t("report.generated", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    md_content.append(t("report.total_files", count=loaded_count))
    md_content.append("")
    md_content.append(t("report.results_matrix"))
    md_content.append("")
    md_content.append("| Species | Group | " + " | ".join([METHODS[m] for m in METHODS.keys()]) + " |")
    md_content.append("|" + "---|" * (len(METHODS) + 2))
    
    # Nur tatsaechlich analysierte Spezies anzeigen (wissenschaftliche Transparenz).
    # "—" for unanalysed species would be misleading.
    active_species_list = [
        sp for sp in consolidated["species"].keys()
        if any(consolidated["results_matrix"][mid].get(sp) is not None
               for mid in METHODS.keys())
    ]
    all_species_count = len(consolidated["species"])
    if len(active_species_list) < all_species_count:
        md_content.append(t("report.species_partial_note", done=len(active_species_list), total=all_species_count, pct=100*len(active_species_list)/all_species_count))
        md_content.append("")

    for species_name in active_species_list:
        display = species_display(species_name)   # translated name for report
        row = [display, consolidated["species"][species_name]["group"]]
        for method_id in METHODS.keys():
            result = consolidated["results_matrix"][method_id].get(species_name)
            row.append(result if result else "—")
        md_content.append("| " + " | ".join(row) + " |")
    
    md_content.append("")
    md_content.append(t("report.summary_stats"))
    md_content.append("")
    md_content.append(t("report.per_method"))
    md_content.append("")
    md_content.append(t("report.method_col"))
    md_content.append("|--------|---------------------|")
    for method_id in METHODS.keys():
        count = sum(1 for v in consolidated["results_matrix"][method_id].values() if v is not None)
        md_content.append(f"| {METHODS[method_id]} | {count}/{len(consolidated['species'])} |")
    
    md_content.append("")
    md_content.append("---")

    # ── CGR-Metriken Tabelle ──────────────────────────────────────────────────
    if cgr_metrics_by_species:
        md_content.append("")
        md_content.append(t("report.cgr_metrics"))
        md_content.append("")
        md_content.append("| Species | Group | corr_xy | corr_x_yinv | h_peaks | v_peaks | center_density | fractal_dim |")
        md_content.append("|---------|-------|--------:|------------:|--------:|--------:|---------------:|------------:|")

        for sp, m in sorted(cgr_metrics_by_species.items()):
            def _f(v, fmt=".3f"):
                return f"{v:{fmt}}" if v is not None else "—"
            h_peaks = m.get("horizontal_peaks", {}).get("peak_count", "—")
            v_peaks = m.get("vertical_peaks",   {}).get("peak_count", "—")
            md_content.append(
                f"| {sp} | {m.get('group','?')} "
                f"| {_f(m.get('correlation_xy'))} "
                f"| {_f(m.get('correlation_x_yinv'))} "
                f"| {h_peaks} "
                f"| {v_peaks} "
                f"| {_f(m.get('center_density'), '.4f')} "
                f"| {_f(m.get('fractal_dimension'))} |"
            )

        # ── Interpretation ────────────────────────────────────────────────────
        md_content.append("")
        md_content.append(t("report.cgr_interpretation"))
        md_content.append("")
        md_content.append(t("report.notable_species"))
        md_content.append("")
        md_content.append("| " + t("report.cgr_col_species") + " | " + t("report.cgr_col_anomaly") + " | " + t("report.cgr_col_metric") + " | " + t("report.cgr_col_significance") + " |")
        md_content.append("|---------|---------------|-------------|-------------------------------|")

        # Automatically identify notable species
        highlights = []
        for sp, m in cgr_metrics_by_species.items():
            cxy   = m.get("correlation_xy")
            cxyi  = m.get("correlation_x_yinv")
            hp    = m.get("horizontal_peaks", {}).get("peak_count", 0)
            vp    = m.get("vertical_peaks",   {}).get("peak_count", 0)
            cd    = m.get("center_density", 0)
            fd    = m.get("fractal_dimension", 0)
            sp_short = sp.split("(")[0].strip()

            if cxy is not None and cxy > 0.5:
                highlights.append((sp_short, "Starke Diagonale (↙↗)",
                                   f"corr_xy={cxy:.3f}", "GC-Gradient / bias"))
            if cxyi is not None and cxyi > 0.3:
                highlights.append((sp_short, "Gegendiagonale (↘↖)",
                                   f"corr_x_yinv={cxyi:.3f}", "AT-GC complementarity"))
            if hp >= 5:
                pos = m.get("horizontal_peaks", {}).get("peak_positions", [])
                pos_str = ", ".join(f"{p:.2f}" for p in pos[:4])
                highlights.append((sp_short, f"Horizontale Linien ({hp} Peaks)",
                                   f"y≈{pos_str}", "Poly-A/T Wiederholungen"))
            if vp >= 3:
                highlights.append((sp_short, f"Vertikale Linien ({vp} Peaks)",
                                   f"v_peaks={vp}", "Poly-C/G Wiederholungen"))
            if cd > 0.03:
                highlights.append((sp_short, "Hohe Zentrumsdichte",
                                   f"center_density={cd:.4f}", "Symmetrie (Polyploidie?)"))
            if fd > 1.6:
                highlights.append((sp_short, "Hohe fraktale Dimension",
                                   f"fractal_dim={fd:.3f}", "Self-similarity / repeats"))

        if highlights:
            for row in highlights:
                md_content.append(f"| {' | '.join(row)} |")
        else:
            md_content.append(t("report.no_notable"))

        md_content.append("")
        md_content.append(t("report.cgr_correlation"))
        md_content.append("")

        # Break down corr_xy by group
        groups = {}
        for sp, m in cgr_metrics_by_species.items():
            g = m.get("group", "?")
            v = m.get("correlation_xy")
            if v is not None:
                groups.setdefault(g, []).append(v)

        md_content.append(t("report.mean_corr_xy"))
        md_content.append("")
        md_content.append(t("report.group_col"))
        md_content.append("|--------|---|-------------:|----:|")
        for g, vals in sorted(groups.items()):
            md_content.append(
                f"| {g} | {len(vals)} "
                f"| {float(np.mean(vals)):.3f} "
                f"| {float(np.std(vals)):.3f} |"
            )

    md_content.append("")
    md_content.append("---")

    # ── 4 spezifische patterns-Tabellen ────────────────────────────────────────
    if cgr_metrics_by_species:

        md_content.append("")
        md_content.append(t("report.cgr_patterns_title"))
        md_content.append("")
        md_content.append(t("report.cgr_patterns_intro"))

        # ── Tabelle 1: Diagonale mit Wiederholung (S. pneumoniae) ────────────
        md_content.append("")
        md_content.append(t("report.pattern_1_title"))
        md_content.append("")
        md_content.append("| Species | Group | diag_lower | diag_upper | repetition | angle_consist. | has_pattern |")
        md_content.append("|---------|-------|----------:|----------:|-----------:|---------------:|:-----------:|")
        for sp, m in sorted(cgr_metrics_by_species.items()):
            dw = m.get("diagonal_with_repetition", {})
            if not dw: continue
            flag = "✅" if dw.get("has_repeated_diagonal") else "—"
            sp_s = sp.split("(")[0].strip()
            md_content.append(
                f"| {sp_s} | {m.get('group','?')} "
                f"| {dw.get('diag_strength_lower', 0):.3f} "
                f"| {dw.get('diag_strength_upper', 0):.3f} "
                f"| {dw.get('diag_repetition', 0):.3f} "
                f"| {dw.get('diag_angle_consistency', 0):.3f} "
                f"| {flag} |"
            )

        # ── Tabelle 2: Horizontale Linien (A. gambiae) ────────────────────────
        md_content.append("")
        md_content.append(t("report.pattern_2_title"))
        md_content.append("")
        md_content.append("| Species | Group | y=0.00 | y=0.04 | y=0.06 | y=0.10 | y=0.22 | y=0.38 | tot_peaks | strong | match | has_pattern |")
        md_content.append("|---------|-------|-------:|-------:|-------:|-------:|-------:|-------:|----------:|-------:|------:|:-----------:|")
        for sp, m in sorted(cgr_metrics_by_species.items()):
            hl = m.get("horizontal_lines", {})
            if not hl: continue
            els = hl.get("expected_line_strengths", {})
            flag = "✅" if hl.get("has_horizontal_lines") else "—"
            sp_s = sp.split("(")[0].strip()
            def _h(k): return f"{els.get(k, 0):.0f}"
            md_content.append(
                f"| {sp_s} | {m.get('group','?')} "
                f"| {_h('y=0.00')} | {_h('y=0.04')} | {_h('y=0.06')} "
                f"| {_h('y=0.10')} | {_h('y=0.22')} | {_h('y=0.38')} "
                f"| {hl.get('total_peaks', 0)} "
                f"| {hl.get('strong_peaks', 0)} "
                f"| {hl.get('best_match_to_expected', 0):.2f} "
                f"| {flag} |"
            )

        # ── Tabelle 3: Kreuz bei 0.5 (A. thaliana) ───────────────────────────
        md_content.append("")
        md_content.append(t("report.pattern_3_title"))
        md_content.append("")
        md_content.append("| Species | Group | v_line | h_line | cross_pts | clusters | symmetry | has_pattern |")
        md_content.append("|---------|-------|-------:|-------:|----------:|---------:|---------:|:-----------:|")
        for sp, m in sorted(cgr_metrics_by_species.items()):
            cx = m.get("cross_at_center", {})
            if not cx: continue
            flag = "✅" if cx.get("has_cross") else "—"
            sp_s = sp.split("(")[0].strip()
            md_content.append(
                f"| {sp_s} | {m.get('group','?')} "
                f"| {cx.get('vertical_line_strength', 0):.4f} "
                f"| {cx.get('horizontal_line_strength', 0):.4f} "
                f"| {cx.get('cross_points_count', 0)} "
                f"| {cx.get('cross_clusters', 0)} "
                f"| {cx.get('quadrant_symmetry', 0):.3f} "
                f"| {flag} |"
            )

        # ── Tabelle 4: Doppelte Diagonale (R. norvegicus) ─────────────────────
        md_content.append("")
        md_content.append(t("report.pattern_4_title"))
        md_content.append("")
        md_content.append("| Species | Group | diag_str | anti_str | ratio | quad_consist. | has_pattern |")
        md_content.append("|---------|-------|--------:|--------:|------:|--------------:|:-----------:|")
        for sp, m in sorted(cgr_metrics_by_species.items()):
            dd = m.get("double_diagonal", {})
            if not dd: continue
            flag = "✅" if dd.get("has_double_diagonal") else "—"
            sp_s = sp.split("(")[0].strip()
            md_content.append(
                f"| {sp_s} | {m.get('group','?')} "
                f"| {dd.get('diag_strength', 0):.3f} "
                f"| {dd.get('anti_diag_strength', 0):.3f} "
                f"| {dd.get('diag_ratio', 0):.2f} "
                f"| {dd.get('diag_consistency_across_quadrants', 0):.3f} "
                f"| {flag} |"
            )

        # ── Zusammenfassung der patternserkennung ───────────────────────────────
        md_content.append("")
        md_content.append(t("report.pattern_summary"))
        md_content.append("")
        md_content.append("| Species | Group | Diag+Repeat | H-Lines | Cross@0.5 | DoubleDiag |")
        md_content.append("|---------|-------|:-----------:|:--------:|:---------:|:----------:|")
        for sp, m in sorted(cgr_metrics_by_species.items()):
            dw = m.get("diagonal_with_repetition", {})
            hl = m.get("horizontal_lines", {})
            cx = m.get("cross_at_center", {})
            dd = m.get("double_diagonal", {})
            sp_s = sp.split("(")[0].strip()
            md_content.append(
                f"| {sp_s} | {m.get('group','?')} "
                f"| {'✅' if dw.get('has_repeated_diagonal') else '—'} "
                f"| {'✅' if hl.get('has_horizontal_lines') else '—'} "
                f"| {'✅' if cx.get('has_cross') else '—'} "
                f"| {'✅' if dd.get('has_double_diagonal') else '—'} |"
            )

    md_content.append("")
    md_content.append("---")

    # ── Δ-Optimierungs-Ergebnisse (falls vorhanden) ──────────────────────────
    delta_files = sorted(CONFIG.results_dir.glob("delta_optimization_*.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
    if delta_files:
        latest_delta = delta_files[0]
        try:
            with open(latest_delta, 'r', encoding='utf-8') as f:
                delta_data = json.load(f)

            d_summary = delta_data.get("summary", {})
            d_params  = delta_data.get("parameters", {})
            d_species = delta_data.get("species", [])
            d_ts      = delta_data.get("timestamp", "")

            md_content.append("")
            md_content.append(t("report.delta_section_title"))
            md_content.append("")
            md_content.append(t("report.delta_source", filename=latest_delta.name, timestamp=d_ts))
            md_content.append(t("analysis.delta_coarse_line", deltas=d_params.get("coarse_deltas",[]), perms=d_params.get("permutations","?")))
            md_content.append(t("report.delta_fine_enabled", perms=d_params.get("fine_perm","?")) if d_params.get("fine_tuning") else t("report.delta_fine_disabled"))
            md_content.append("")

            # Completeness
            total   = d_summary.get("total_species", 0)
            done    = d_summary.get("completed", 0)
            sig_cnt = d_summary.get("significant_count", 0)
            pct     = int(done / total * 100) if total else 0
            md_content.append(t("report.delta_progress", done=done, total=total, pct=pct))
            md_content.append(t("report.delta_significant", count=sig_cnt, done=done))
            md_content.append(t("report.delta_reference", delta=d_summary.get("reference_delta", 2.0)))
            md_content.append("")

            # Habitat-Modal
            modal = d_summary.get("habitat_modal_delta", {})
            mean_d = d_summary.get("habitat_mean_delta", {})
            if modal:
                md_content.append(t("report.delta_by_habitat"))
                md_content.append("")
                md_content.append(t("report.delta_habitat_col"))
                md_content.append("|-----------|---------|------------|----------------|")
                ref = d_summary.get("reference_delta", 2.0)
                for h in sorted(modal.keys()):
                    m_d = modal[h]
                    abw = abs(m_d - ref)
                    if abw < 0.15:
                        interp = t("report.delta_habitat_approx")
                    elif abw >= 0.4:
                        interp = t("report.delta_habitat_deviant")
                    else:
                        interp = t("report.delta_habitat_slight_deviant")
                    md_content.append(
                        f"| {h} | **{m_d:.1f}** | {mean_d.get(h, 0):.2f} | {interp} |"
                    )
                md_content.append("")
            md_content.append(t("report.habitat_hypothesis"))
            md_content.append("")

            # Species detail table
            if d_species:
                md_content.append(t("report.delta_species_title"))
                md_content.append("")
                md_content.append(t("report.delta_species_col"))
                md_content.append("|---------|-----------|--------|-----------|--------|--------|------------|")
                for r in sorted(d_species,
                                key=lambda x: (x.get("habitat",""), x.get("optimal_delta") or 99)):
                    d_opt  = r.get("optimal_delta")
                    p_opt  = r.get("optimal_p_value")
                    sig    = "✅" if r.get("significant") else "—"
                    sp_s   = r["name"].split("(")[0].strip()
                    has_result = d_opt is not None
                    sch    = (r.get("optimal_scheme") or "standard") if has_result else "—"
                    ext_mk = " 🔭" if r.get("extended_used") else ""
                    trans  = r.get("optimal_transitions", "—") if has_result else "—"
                    d_fmt  = f"{float(d_opt):.6f}" if has_result else "—"
                    p_fmt  = f"{float(p_opt):.6f}" if p_opt is not None else "—"
                    md_content.append(
                        f"| {sp_s} | {r.get('habitat','?')} "
                        f"| {d_fmt} "
                        f"| {trans} | {sch}{ext_mk} "
                        f"| {p_fmt} | {sig} |"
                    )
                md_content.append("")
                # Legende wenn Erweiterungen stattfanden
                if any(r.get("extended_used") for r in d_species):
                    md_content.append(t("analysis.schema_note"))
                    md_content.append("")

            # Outliers
            outliers = d_summary.get("outliers", [])
            if outliers:
                md_content.append(t("report.delta_outliers"))
                md_content.append("")
                md_content.append(t("report.delta_outliers_col"))
                md_content.append("|---------|-----------|--------|--------------|-----------|")
                for o in outliers:
                    sp_s = o["name"].split("(")[0].strip()
                    md_content.append(
                        f"| {sp_s} | {o['habitat']} | {o['optimal_delta']} "
                        f"| {o['habitat_modal']} | {o['deviation']} |"
                    )
                md_content.append("")

            # ── Statistik-Sektion ─────────────────────────────────────────
            d_stats = delta_data.get("statistics", {})
            if d_stats:
                md_content.append(t("report.delta_stats_title"))
                md_content.append("")

                # Kruskal-Wallis + Bonferroni-Alpha prominent in Summary
                kw      = d_stats.get("kruskal_wallis", {})
                alpha_b = d_stats.get("bonferroni_alpha", 0.05)
                n_pairs = d_stats.get("n_pairs", 1)
                if kw and "H" in kw:
                    sig_kw = t("analysis.sig_kruskal") if kw.get("significant") else t("analysis.nonsig_kruskal")
                    md_content.append(f"**Kruskal-Wallis-Test:** H={kw['H']:.3f}, "
                                       f"p={kw['p_value']:.4f} → {sig_kw}")
                    md_content.append("")
                # Bonferroni-Alpha explizit in der Summary-Sektion anzeigen
                md_content.append(t("report.delta_bonferroni", n=n_pairs, alpha=alpha_b))
                md_content.append("")

                # Pairwise tests
                pairwise = d_stats.get("pairwise_tests", [])
                if pairwise:
                    md_content.append(t("report.delta_pairwise_title", alpha=alpha_b))
                    md_content.append("")
                    md_content.append(t("report.delta_pairwise_col"))
                    md_content.append("|---------|---------|-----|-----|--------|-----------|---------|--------|------|")
                    for pw in pairwise:
                        if "error" not in pw:
                            sig_pw  = "✅" if pw.get("significant") else "—"
                            p_bonf  = pw.get("p_bonferroni", pw["p_value"] * n_pairs)
                            md_content.append(
                                f"| {pw['group1']} | {pw['group2']} "
                                f"| {pw.get('mean1', 0):.2f} | {pw.get('mean2', 0):.2f} "
                                f"| {pw['p_value']:.4f} | {min(p_bonf, 1.0):.4f} "
                                f"| {pw['cohens_d']:.2f} "
                                f"| {pw['effect_size']} | {sig_pw} |"
                            )
                    md_content.append("")

                # Bootstrap-KI
                grp_stats = d_stats.get("group_stats", {})
                if grp_stats:
                    md_content.append(t("report.delta_bootstrap_title"))
                    md_content.append("")
                    md_content.append(t("report.delta_bootstrap_col"))
                    md_content.append("|-----------|---|------------|--------|")
                    for h, gs in sorted(grp_stats.items()):
                        md_content.append(
                            f"| {h} | {gs['n']} | {gs['mean']:.3f} "
                            f"| [{gs['ci_lower']:.3f}, {gs['ci_upper']:.3f}] |"
                        )
                    md_content.append("")

                # ROC-AUC
                roc = d_stats.get("roc_auc", [])
                if isinstance(roc, list) and roc:
                    md_content.append("**ROC-AUC (Δ als Klassifikator):**")
                    md_content.append("")
                    md_content.append("| Positive | Negative | AUC | Quality |")
                    md_content.append("|---------|---------|-----|---------|")
                    for rc in roc:
                        md_content.append(
                            f"| {rc['positive_class']} | {rc['negative_class']} "
                            f"| {rc['auc']:.3f} | {rc['interpretation']} |"
                        )
                    md_content.append("")

                # GC-Korrelation
                gc_corr = d_stats.get("gc_correlation", {})
                if gc_corr and "spearman_r" in gc_corr:
                    md_content.append(t("analysis.gc_corr_label", interpretation=gc_corr.get("interpretation", "")))
                    md_content.append("")

                # LaTeX
                latex = d_stats.get("latex_table", "")
                if latex:
                    md_content.append("<details>")
                    md_content.append("<summary>LaTeX table (for publication)</summary>")
                    md_content.append("")
                    md_content.append("```latex")
                    md_content.append(latex)
                    md_content.append("```")
                    md_content.append("")
                    md_content.append("</details>")
                    md_content.append("")

            # Note for incomplete analysis
            if done < total:
                md_content.append(t("report.delta_partial_note", done=done, total=total, pct=pct))
                md_content.append("")

            if log_callback:
                log_callback(t("analysis.delta_integrated"))

        except Exception as e:
            if log_callback:
                log_callback(t("analysis.delta_file_error", error=e))
            md_content.append(t("analysis.delta_file_unreadable", error=e))
            md_content.append("")
    else:
        md_content.append("")
        md_content.append(t("report.delta_section_title"))
        md_content.append("")
        md_content.append(t("report.delta_not_done"))
        md_content.append("")

    # ── Golden Ratio: Kontrolltests (Artefakt-Erkennung) ─────────────────
    golden_ctrl_files = [f for f in CONFIG.results_dir.glob("golden_ratio_*.json")]
    golden_ctrl_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    if golden_ctrl_files:
        ctrl_data = []
        for gf in golden_ctrl_files:
            try:
                with open(gf, 'r', encoding='utf-8') as _gf:
                    _gr = json.load(_gf)
                ctrl1 = _gr.get("control_test_1_random_positions", {})
                ctrl2 = _gr.get("control_test_2_shuffled_distances", {})
                if ctrl1 or ctrl2:
                    ctrl_data.append({
                        "species": _gr.get("species", gf.stem),
                        "match_rate": _gr.get("match_rate", 0),
                        "ctrl1": ctrl1,
                        "ctrl2": ctrl2,
                    })
            except Exception:
                pass

        if ctrl_data:
            md_content.append("")
            md_content.append(t("report.golden_ctrl_title"))
            md_content.append("")
            md_content.append(t("report.golden_ctrl_intro"))
            md_content.append(t("report.golden_ctrl_test1"))
            md_content.append(t("report.golden_ctrl_test2"))
            md_content.append("")
            md_content.append(t("report.golden_ctrl_col"))
            md_content.append("|---------|-----------------|----------------|-----------|--------------------|-----------| --------------|")
            for cd in sorted(ctrl_data, key=lambda x: x["match_rate"], reverse=True):
                sp_s  = cd["species"].split("(")[0].strip() if "(" in cd["species"] else cd["species"]
                mr    = cd["match_rate"]
                c1    = cd["ctrl1"]
                c2    = cd["ctrl2"]
                c1m   = c1.get("mean_match_rate", 0)
                c2m   = c2.get("mean_match_rate", 0)
                e1    = c1.get("effect_vs_real", 0)
                e2    = c2.get("effect_vs_real", 0)
                # Overall interpretation
                if e1 > 10 and e2 > 10:
                    interp = "✅ Echter biologischer Effekt"
                elif e1 > 10:
                    interp = t("analysis.position_effect_only")
                elif e1 <= 0:
                    interp = "❌ Artefakt-Verdacht"
                else:
                    interp = "⚠️ Schwacher Effekt"
                md_content.append(
                    f"| {sp_s} | {mr:.1f}% | {c1m:.1f}% ± {c1.get('std_match_rate',0):.1f}% "
                    f"| {e1:+.1f}% | {c2m:.1f}% ± {c2.get('std_match_rate',0):.1f}% "
                    f"| {e2:+.1f}% | {interp} |"
                )
            md_content.append("")

    # ── Δ-Abweichungsanalyse (if deviation reports exist) ─────────────────
    deviation_files = sorted(
        CONFIG.delta_abstracts_dir.glob("DEVIATION_REPORT_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )
    if deviation_files:
        try:
            dev_report = json.loads(deviation_files[0].read_text(encoding="utf-8"))
            md_content.append(t("report.deviation_section"))
            md_content.append("")
            md_content.append(t("report.deviation_source",
                                file=deviation_files[0].name))
            md_content.append("")
            md_content.append(t("report.deviation_stats_title"))
            md_content.append("")
            md_content.append(t("report.deviation_rate_col"))
            md_content.append("|---|---|---|---|---|---|---|")
            for sp_r in dev_report.get("species", []):
                disp  = sp_r.get("species_display", sp_r.get("species", "?"))
                dev   = sp_r.get("deviation_data", {})
                stat  = sp_r.get("statistics", {})
                chi2  = stat.get("chi2_vs_geometric", {})
                shuf  = sp_r.get("shuffle_control") or {}
                dr    = f"{dev.get('deviation_rate', 0):.1%}"
                chi2s = f"{chi2.get('statistic', 0):.2f}" if chi2.get("statistic") else "—"
                ps    = f"{chi2.get('p_value', 0):.4f}" if chi2.get("p_value") is not None else "—"
                sig   = "✅" if chi2.get("significant") else "—"
                shuf_pct = f"{shuf.get('real_chi2_percentile',0)*100:.0f}th" if shuf.get("real_chi2_percentile") is not None else "—"
                shuf_sig = "✅" if shuf.get("is_significant") else ("⚠️" if shuf.get("real_chi2_percentile",0)>=0.90 else "—") if shuf else "—"
                md_content.append(f"| {disp} | {dr} | {chi2s} | {ps} | {sig} | {shuf_pct} | {shuf_sig} |")
            md_content.append("")
            # Top-5 most similar pairs
            comparisons = [c for c in dev_report.get("comparisons", [])
                           if c.get("identity") is not None]
            if comparisons:
                comparisons.sort(key=lambda x: x.get("identity", 0), reverse=True)
                md_content.append(t("report.deviation_top_pairs"))
                md_content.append("")
                md_content.append(t("report.deviation_comparison_col"))
                md_content.append("|---|---|---|---|---|")
                for c in comparisons[:10]:
                    same = "✅" if c.get("habitat1") == c.get("habitat2") else "—"
                    md_content.append(
                        f"| {c['display1']} | {c['display2']} "
                        f"| {c['identity']:.1%} | {c['interpretation']} | {same} |"
                    )
            md_content.append("")
        except Exception as e:
            md_content.append(t("report.deviation_section"))
            md_content.append(f"> ⚠️ Fehler beim Laden: {e}")
            md_content.append("")

    md_content.append("---")
    md_content.append(t("report.end_of_report"))
    
    md_filename = f"FINAL_COMPLETE_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    md_path = CONFIG.results_dir / md_filename
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md_content))
    
    json_filename = f"FINAL_COMPLETE_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_path = CONFIG.results_dir / json_filename
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(consolidated, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    
    # Excel-Export
    excel_path = CONFIG.results_dir / f"FINAL_COMPLETE_REPORT_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # Create DataFrame for matrix
    # Nur analysierte Spezies im Excel-Export
    matrix_data = []
    for species_name in active_species_list:
        row = {
            'Species': species_name,
            'Group': consolidated["species"][species_name]["group"]
        }
        for method_id in METHODS.keys():
            row[METHODS[method_id]] = consolidated["results_matrix"][method_id].get(species_name, "—")
        matrix_data.append(row)
    
    if matrix_data:
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            pd.DataFrame(matrix_data).to_excel(writer, sheet_name='Results Matrix', index=False)

            # CGR-Metriken Sheet (allgemein)
            if cgr_metrics_by_species:
                cgr_rows = []
                for sp, m in cgr_metrics_by_species.items():
                    cgr_rows.append({
                        'Species':          sp,
                        'Group':            m.get('group', '?'),
                        'corr_xy':          m.get('correlation_xy'),
                        'corr_x_yinv':      m.get('correlation_x_yinv'),
                        'h_peaks':          m.get('horizontal_peaks', {}).get('peak_count'),
                        'v_peaks':          m.get('vertical_peaks',   {}).get('peak_count'),
                        'center_density':   m.get('center_density'),
                        'fractal_dim':      m.get('fractal_dimension'),
                        'points_count':     m.get('points_count'),
                    })
                pd.DataFrame(cgr_rows).to_excel(writer, sheet_name='CGR Metrics', index=False)

                # CGR spezifische patterns-Tabelle
                pattern_rows = []
                for sp, m in cgr_metrics_by_species.items():
                    dw = m.get("diagonal_with_repetition", {})
                    hl = m.get("horizontal_lines", {})
                    cx = m.get("cross_at_center", {})
                    dd = m.get("double_diagonal", {})
                    els = hl.get("expected_line_strengths", {})
                    pattern_rows.append({
                        'Species':             sp,
                        'Group':               m.get('group', '?'),
                        # Diagonale
                        'diag_lower':          dw.get('diag_strength_lower'),
                        'diag_upper':          dw.get('diag_strength_upper'),
                        'diag_repetition':     dw.get('diag_repetition'),
                        'has_repeated_diag':   dw.get('has_repeated_diagonal'),
                        # Horizontale Linien
                        'h_total_peaks':       hl.get('total_peaks'),
                        'h_strong_peaks':      hl.get('strong_peaks'),
                        'h_match_expected':    hl.get('best_match_to_expected'),
                        'has_horiz_lines':     hl.get('has_horizontal_lines'),
                        # Kreuz
                        'cross_v_line':        cx.get('vertical_line_strength'),
                        'cross_h_line':        cx.get('horizontal_line_strength'),
                        'cross_points':        cx.get('cross_points_count'),
                        'quadrant_symmetry':   cx.get('quadrant_symmetry'),
                        'has_cross':           cx.get('has_cross'),
                        # Doppeldiagonale
                        'diag_strength':       dd.get('diag_strength'),
                        'anti_diag_strength':  dd.get('anti_diag_strength'),
                        'diag_ratio':          dd.get('diag_ratio'),
                        'has_double_diag':     dd.get('has_double_diagonal'),
                    })
                pd.DataFrame(pattern_rows).to_excel(writer, sheet_name='CGR Patterns', index=False)

            # Δ-Optimierungs-Sheet (falls vorhanden)
            delta_files_xl = sorted(CONFIG.results_dir.glob("delta_optimization_*.json"),
                                    key=lambda p: p.stat().st_mtime, reverse=True)
            if delta_files_xl:
                try:
                    with open(delta_files_xl[0], 'r', encoding='utf-8') as _f:
                        _d = json.load(_f)
                    _coarse = _d.get("parameters", {}).get("coarse_deltas", [])
                    _delta_rows = []
                    for r in _d.get("species", []):
                        p_map = {rd["delta"]: rd.get("p_value")
                                 for rd in r.get("all_deltas", [])}
                        row_xl = {
                            "Species":        r["name"],
                            "Group":          r.get("group", ""),
                            "Habitat":        r.get("habitat", ""),
                            "Optimal_Delta":  r.get("optimal_delta"),
                            "Optimal_p":      r.get("optimal_p_value"),
                            "Significant":    int(r.get("significant", False)),
                        }
                        for _d_val in _coarse:
                            row_xl[f"p_delta_{_d_val:.1f}"] = p_map.get(_d_val, "")
                        _delta_rows.append(row_xl)
                    if _delta_rows:
                        pd.DataFrame(_delta_rows).to_excel(
                            writer, sheet_name='Delta Optimization', index=False)

                    # Statistics-Sheet
                    _stats = _d.get("statistics", {})
                    _grp   = _stats.get("group_stats", {})
                    _pw    = _stats.get("pairwise_tests", [])
                    if _grp:
                        _stat_rows = []
                        for _h, _gs in _grp.items():
                            _stat_rows.append({
                                "Habitat":      _h,
                                "n":            _gs["n"],
                                "Mean_Delta":   _gs["mean"],
                                "CI_Lower":     _gs["ci_lower"],
                                "CI_Upper":     _gs["ci_upper"],
                            })
                        pd.DataFrame(_stat_rows).to_excel(
                            writer, sheet_name='Delta Statistics', index=False)
                    if _pw:
                        _pw_clean = [{k: v for k, v in r.items() if k != "error"}
                                      for r in _pw if "error" not in r]
                        if _pw_clean:
                            pd.DataFrame(_pw_clean).to_excel(
                                writer, sheet_name='Pairwise Tests', index=False)
                except Exception:
                    pass
    
    if log_callback:
        log_callback(f"\n  📄 Markdown-Bericht: {md_path}")
        log_callback(t("analysis.json_report", path=json_path))
        log_callback(t("report.excel_saved", path=excel_path))
    
    return consolidated, md_path, json_path

# ============================================================
# GUI (VERBESSERT)
# ============================================================

class SettingsDialog:
    """Settings dialog with language selector and persistence."""
    def __init__(self, parent, config: AnalysisConfig):
        self.parent = parent
        self.config = config
        self.result = None

    def show(self):
        dialog = tk.Toplevel(self.parent)
        dialog.title(t("settings.window_title"))
        dialog.geometry("520x640")
        dialog.transient(self.parent)
        dialog.grab_set()

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # ── Tab 1: Language ──────────────────────────────────────────────────
        lang_frame = ttk.Frame(notebook, padding=10)
        notebook.add(lang_frame, text=t("settings.language"))

        ttk.Label(lang_frame, text=t("settings.language_select")).grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=8)

        available = {code: cfg for code, cfg in AVAILABLE_LANGUAGES.items()
                     if (LANGUAGE_DIR / cfg.file).exists()}
        lang_display = [f"{cfg.native_name} ({cfg.name})" for cfg in available.values()]
        lang_codes   = list(available.keys())
        lang_var     = tk.StringVar()
        current_code = _i18n.current_language
        if current_code in available:
            cfg = available[current_code]
            lang_var.set(f"{cfg.native_name} ({cfg.name})")

        lang_combo = ttk.Combobox(lang_frame, textvariable=lang_var,
                                   values=lang_display, width=28, state='readonly')
        lang_combo.grid(row=0, column=1, padx=5, pady=8)

        # ── Tab 2: Analysis parameters ───────────────────────────────────────
        param_frame = ttk.Frame(notebook, padding=10)
        notebook.add(param_frame, text=t("settings.param_analysis"))

        params = [
            ("settings.param_max_seq_length",    "max_seq_length",            int),
            ("settings.param_gc_window_size",     "gc_window_size",            int),
            ("settings.param_golden_tolerance",   "golden_ratio_tolerance",    float),
            ("settings.param_fibonacci_tolerance","fibonacci_tolerance",       float),
            ("settings.param_parallel_workers",   "max_parallel_workers",      int),
            ("settings.param_permutations",       "significance_permutations", int),
        ]
        entry_vars = {}
        for row, (label_key, attr, _) in enumerate(params):
            ttk.Label(param_frame, text=t(label_key)).grid(
                row=row, column=0, sticky=tk.W, padx=5, pady=4)
            var = tk.StringVar(value=str(getattr(self.config, attr)))
            ttk.Entry(param_frame, textvariable=var, width=15).grid(
                row=row, column=1, sticky=tk.W, padx=5)
            entry_vars[attr] = (var, _)

        use_cache_var = tk.BooleanVar(value=self.config.use_caching)
        ttk.Checkbutton(param_frame, text=t("settings.option_caching"),
                        variable=use_cache_var).grid(
            row=len(params), column=0, columnspan=2, sticky=tk.W, padx=5, pady=8)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(pady=10)

        def save():
            # Apply language
            selected_display = lang_var.get()
            for code, cfg in available.items():
                if f"{cfg.native_name} ({cfg.name})" == selected_display:
                    if code != _i18n.current_language:
                        _i18n.set_language(code)
                        _save_settings({"language": code})
                    break
            # Apply analysis parameters
            try:
                for attr, (var, cast) in entry_vars.items():
                    setattr(self.config, attr, cast(var.get()))
                self.config.use_caching = use_cache_var.get()
                # Persist all settings
                _save_settings({
                    "max_seq_length":            self.config.max_seq_length,
                    "gc_window_size":            self.config.gc_window_size,
                    "golden_ratio_tolerance":    self.config.golden_ratio_tolerance,
                    "fibonacci_tolerance":       self.config.fibonacci_tolerance,
                    "max_parallel_workers":      self.config.max_parallel_workers,
                    "significance_permutations": self.config.significance_permutations,
                    "use_caching":               self.config.use_caching,
                })
                self.result = self.config
                dialog.destroy()
            except ValueError as e:
                messagebox.showerror(t("dialogs.error"),
                                     t("settings.invalid_value", error=str(e)))

        ttk.Button(btn_frame, text=t("settings.button_save"), command=save).pack(
            side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text=t("settings.button_cancel"),
                   command=dialog.destroy).pack(side=tk.LEFT, padx=5)

        dialog.wait_window()

# ============================================================
# DELTA OPTIMISATION (Δ scan across all species)
# ============================================================

# Habitat mapping for Δ-optimisation report
# Per-species habitat classification (5 ecological categories).
# This replaces the old coarse 3-category system (microbe/terrestrial/aquatic).
# Categories (based on DeepSeek's recommendation for publication-quality analysis):
#   microbe_host    – obligate or strongly host-adapted bacteria
#   microbe_env     – environmental/generalist bacteria
#   microbe_aquatic – aquatic bacteria
#   terrestrial     – land-dwelling eukaryotes and plants
#   aquatic         – water-dwelling eukaryotes
_SPECIES_HABITAT: Dict[str, str] = {
    # ── Bacteria: host-adapted ────────────────────────────────────────────────
    "mycobacterium_tuberculosis": "microbe_host",   # obligate human pathogen
    "streptococcus_pneumoniae":   "microbe_host",   # host-adapted pathogen
    "neisseria_meningitidis":     "microbe_host",   # host-adapted pathogen
    "helicobacter_pylori":        "microbe_host",   # obligate stomach coloniser
    # ── Bacteria: environmental generalist ───────────────────────────────────
    "escherichia_coli":           "microbe_env",    # gut/soil/water generalist
    "bacillus_subtilis":          "microbe_env",    # soil generalist
    "pseudomonas_aeruginosa":     "microbe_env",    # ubiquitous generalist
    "lactobacillus_plantarum":    "microbe_env",    # plant/gut/environment
    "clostridium_perfringens":    "microbe_env",    # soil/gut
    # ── Bacteria: aquatic ────────────────────────────────────────────────────
    "vibrio_cholerae":            "microbe_aquatic",# estuarine/aquatic
    # ── Eukaryotes: terrestrial ───────────────────────────────────────────────
    "saccharomyces_cerevisiae":   "terrestrial",
    "homo_sapiens":               "terrestrial",
    "mus_musculus_chr17":         "terrestrial",
    "mus_musculus_chr1":          "terrestrial",
    "drosophila_melanogaster":    "terrestrial",
    "caenorhabditis_elegans":     "terrestrial",
    "arabidopsis_thaliana":       "terrestrial",
    "rattus_norvegicus":          "terrestrial",
    "pan_troglodytes":            "terrestrial",
    "canis_familiaris":           "terrestrial",
    "gallus_gallus":              "terrestrial",
    "schizosaccharomyces_pombe":  "terrestrial",
    "bos_taurus":                 "terrestrial",
    "felis_catus":                "terrestrial",
    "ovis_aries":                 "terrestrial",
    "apis_mellifera":             "terrestrial",
    "oryza_sativa":               "terrestrial",
    "triticum_aestivum":          "terrestrial",
    "sphenodon_punctatus":        "terrestrial",    # terrestrial reptile
    # ── Eukaryotes: aquatic ───────────────────────────────────────────────────
    "danio_rerio_chr1":           "aquatic",
    "danio_rerio_chr25":          "aquatic",
    "xenopus_tropicalis":         "aquatic",
    "anopheles_gambiae":          "aquatic",        # larval stage aquatic
    "ambystoma_mexicanum":        "aquatic",        # fully aquatic (neotenic)
    "cynops_pyrrhogaster":        "aquatic",
    "rana_temporaria":            "aquatic",
    "bufo_bufo":                  "aquatic",        # amphibian
    "nautilus_pompilius":         "aquatic",
    "latimeria_chalumnae":        "aquatic",
    "limulus_polyphemus":         "aquatic",
}

# Fallback: coarse group → habitat for any species not in _SPECIES_HABITAT
_HABITAT_FALLBACK: Dict[str, str] = {
    "bacteria":      "microbe_env",
    "eukaryote":     "terrestrial",
    "plant":         "terrestrial",
    "living_fossil": "aquatic",
}


def _get_habitat(species_name: str, group: str) -> str:
    """Returns the ecological habitat category key for a species.
    Uses per-species lookup (5 categories) with group fallback.
    Returns internal key like 'microbe_host', 'terrestrial' etc."""
    # Try internal DB key (lowercase, underscore)
    key = species_name.lower().replace(" ", "_").replace(",", "").replace("(", "").replace(")", "")
    # Match against _SPECIES_HABITAT keys (partial match for robustness)
    for sp_key, habitat in _SPECIES_HABITAT.items():
        if sp_key in key or key.startswith(sp_key.split("_chr")[0]):
            return habitat
    # Fallback to group-level classification
    return _HABITAT_FALLBACK.get(group, "terrestrial")


def _habitat_label(habitat_key: str) -> str:
    """Returns the translated display label for a habitat key."""
    translated = t(f"habitat.{habitat_key}")
    # If key not found, t() returns the key itself — fall back to raw key
    return translated if translated != f"habitat.{habitat_key}" else habitat_key


def _transitions_for_delta(delta: float,
                            freq_map: Optional[Dict[str, float]] = None) -> str:
    """
    Returns the base pairs captured at this scheme+Δ.
    Beispiel: scheme_2/Δ=2.0 → "A↔T"
              standard/Δ=3.0 → "A↔G"
    """
    fm = freq_map if freq_map is not None else BASE_TO_FREQ
    pairs = sorted(set(
        tuple(sorted([b1, b2]))
        for b1, f1 in fm.items()
        for b2, f2 in fm.items()
        if b1 != b2 and abs(round(abs(f2 - f1), 4) - delta) < 1e-4
    ))
    return ", ".join(f"{p[0]}↔{p[1]}" for p in pairs) if pairs else "?"


def run_delta_optimization(
    log_callback:   Optional[Callable] = None,
    permutations:   int  = 200,
    fine_tuning:    bool = True,
    fine_perm:      int  = 1000,
    stop_event=None,
) -> Optional[Dict[str, Any]]:
    """
    Δ-Optimierung: Scannt alle Spezies mit Δ ∈ [1.0, 1.2, ..., 3.0]
    und findet fuer jede Spezies den Δ-Wert mit maximalem Signal
    (minimaler p-Wert).

    Parameter:
        permutations  - Permutationen im Grobscan (default 200)
        fine_tuning   - Feinabstimmung fuer bestes Δ mit 1000 Perms (default True)
        fine_perm     - Permutationen fuer Feinabstimmung (default 1000)
        stop_event    - threading.Event for stopping (checked before each Δ step)

    Ausgabe:
        delta_optimization_results.json in CONFIG.results_dir
    """
    # Combine physically possible Δ values from ALL schemes.
    # COARSE_DELTAS is defined at module level — use it directly
    species_list  = list(SPECIES_DB.items())
    total_steps   = len(species_list) * len(COARSE_DELTAS)
    step          = 0
    results       = []
    timestamp_str = datetime.now().isoformat()

    # Header is logged by the GUI before calling this function

    # ── Resume: load existing results ONCE before the loop ──────────────────
    existing_files = sorted(
        CONFIG.results_dir.glob("delta_optimization_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True
    )
    already_done = {}
    if existing_files:
        try:
            with open(existing_files[0], 'r', encoding='utf-8') as _ef:
                _existing = json.load(_ef)
            for _r in _existing.get("species", []):
                if _r.get("all_deltas"):
                    already_done[_r["name"]] = _r
        except Exception:
            already_done = {}

    for sp_name, sp_info in species_list:
        if stop_event and stop_event.is_set():
            if log_callback:
                log_callback(t("log_messages.stopped"))
            break

        # Sequenz laden (gecacht)
        fasta = get_or_fetch_genome(sp_info["accession"], log_callback)
        if not fasta:
            if log_callback:
                log_callback(t("analysis.sequence_not_available", species=sp_name))
            step += len(COARSE_DELTAS)
            continue

        reader  = GenomeReader(fasta)
        seq     = reader.get_sequence(CONFIG.max_seq_length)
        habitat = _get_habitat(sp_name, sp_info["group"])

        delta_results = []
        sp_short = sp_name.split("(")[0].strip()

        if sp_name in already_done:
            prev = already_done[sp_name]
            results.append(prev)
            step += len(COARSE_DELTAS)
            pct   = step / total_steps * 100
            if log_callback:
                opt_d = prev.get("optimal_delta")
                opt_p = prev.get("optimal_p_value")
                try:
                    _p_disp = f"{float(opt_p):.4f}" if opt_p is not None else "N/A"
                    _d_disp = f"{float(opt_d):.6f}" if opt_d is not None else "—"
                except (TypeError, ValueError):
                    _p_disp = str(opt_p); _d_disp = str(opt_d)
                log_callback(t("analysis.species_already_done", step=step, total=total_steps, pct=pct, species=sp_short, delta=_d_disp, p=_p_disp))
            continue

        # ── Grobscan ────────────────────────────────────────────────────────
        for d in COARSE_DELTAS:
            if stop_event and stop_event.is_set():
                break

            step += 1
            pct   = step / total_steps * 100
            if log_callback:
                log_callback(f"  [{step}/{total_steps}] ({pct:.0f}%) "
                             f"{sp_short} Δ={d:.1f}...")

            try:
                res = analyze_two_thz(seq, log_callback=None,
                                      delta=d, n_permutations=permutations)
                if "error" in res:
                    p_val = None
                    sig   = False
                    trans = res.get("transitions", 0)
                else:
                    sig_data = res.get("statistical_significance", {})
                    p_val    = sig_data.get("p_value")
                    sig      = sig_data.get("significant", False)
                    trans    = res.get("transitions", 0)
            except Exception as e:
                p_val = None; sig = False; trans = 0
                if log_callback:
                    log_callback(t("analysis.delta_error", delta=d, error=e))

            delta_results.append({
                "delta":       d,
                "p_value":     p_val,
                "significant": sig,
                "transitions": trans,
            })

        # ── Automatische Erweiterung bei Null-Fund ──────────────────────────
        # If no Δ value produced transitions with the standard scheme,
        # werden automatisch alle FREQUENCY_SCHEMES mit ihren Δ-Werten getestet.
        all_results_for_sp = list(delta_results)   # Kopie der Grobscan-Ergebnisse
        extended_used      = []                    # Welche Schemata wurden erweitert

        valid_grobscan = [r for r in delta_results if r.get("p_value") is not None]
        sig_grobscan   = [r for r in valid_grobscan if r.get("significant")]

        # Extend if: (a) no transitions at all OR (b) no significant value
        needs_extension = not valid_grobscan or not sig_grobscan
        if needs_extension:
            if log_callback:
                reason = (t("analysis.schema_ext_no_transitions") if not valid_grobscan
                          else t("analysis.schema_ext_no_significant", p=min(r['p_value'] for r in valid_grobscan)))
                log_callback(t("analysis.schema_extension", species=sp_short, reason=reason))
            for scheme_name, scheme_fmap in FREQUENCY_SCHEMES.items():
                if stop_event and stop_event.is_set():
                    break
                ext_deltas = get_possible_deltas(scheme_fmap)
                if log_callback:
                    log_callback(t("analysis.schema_test", scheme=scheme_name, deltas=ext_deltas))
                for d in ext_deltas:
                    if stop_event and stop_event.is_set():
                        break
                    try:
                        res_ext = analyze_two_thz(seq, log_callback=None,
                                                   delta=d, n_permutations=permutations,
                                                   freq_map=scheme_fmap)
                        if "error" not in res_ext:
                            sd_ext = res_ext.get("statistical_significance", {})
                            all_results_for_sp.append({
                                "delta":        d,
                                "scheme":       scheme_name,
                                "freq_map":     scheme_fmap,
                                "p_value":      sd_ext.get("p_value"),
                                "significant":  sd_ext.get("significant", False),
                                "transitions":  res_ext.get("transitions", 0),
                                "extended":     True,
                            })
                    except Exception:
                        pass
                extended_used.append(scheme_name)

        # ── Determine optimal Δ (across all schemes) ─────────────────────────
        valid = [(r["delta"], r["p_value"], r.get("scheme", "standard"),
                  r.get("freq_map"))
                 for r in all_results_for_sp if r.get("p_value") is not None]
        if not valid:
            opt_delta = None; opt_p = None; opt_sig = False
            opt_scheme = None; opt_fmap = None
        else:
            best = min(valid, key=lambda x: x[1])
            opt_delta, opt_p, opt_scheme, opt_fmap = best
            opt_sig = opt_p < CONFIG.significance_threshold

        # ── Fine tuning: confirm coarse optimum with 1000 perms ──────────────
        # Only tests values that produce real transitions (no "error").
        # Grobwert bleibt wenn Feinabstimmung nichts Besseres findet.
        fine_results = []
        if fine_tuning and opt_delta is not None and stop_event and not stop_event.is_set():
            _fine_fmap = opt_fmap
            _fine_dels = COARSE_DELTAS
            if opt_delta in _fine_dels:
                idx = _fine_dels.index(opt_delta)
            else:
                idx = min(range(len(_fine_dels)), key=lambda i: abs(_fine_dels[i]-opt_delta))
            lo = _fine_dels[max(0, idx-1)]
            hi = _fine_dels[min(len(_fine_dels)-1, idx+1)]
            if idx == 0:
                step_size = round(_fine_dels[1] - _fine_dels[0], 6) if len(_fine_dels) > 1 else 0.5
                lo = max(0.01, round(opt_delta - step_size, 6))
            if idx == len(_fine_dels) - 1:
                step_size = round(_fine_dels[-1] - _fine_dels[-2], 6) if len(_fine_dels) > 1 else 0.5
                hi = round(opt_delta + step_size, 6)

            fine_deltas = [round(lo + (hi - lo) * k / 18, 6) for k in range(1, 18)]
            fine_deltas = [d for d in fine_deltas if abs(d - opt_delta) > 0.001 and d > 0]

            if log_callback and fine_deltas:
                scheme_info = f" ({opt_scheme})" if opt_scheme else ""
                log_callback(t("analysis.fine_tuning_log", species=sp_short, scheme=scheme_info, deltas=[round(d,4) for d in fine_deltas], perms=fine_perm))
            for d in fine_deltas:
                if stop_event and stop_event.is_set():
                    break
                try:
                    res2 = analyze_two_thz(seq, log_callback=None,
                                           delta=d, n_permutations=fine_perm,
                                           freq_map=_fine_fmap)
                    if "error" not in res2:   # Only values with real transitions
                        sd2 = res2.get("statistical_significance", {})
                        fine_results.append({
                            "delta":       d,
                            "scheme":      opt_scheme,
                            "p_value":     sd2.get("p_value"),
                            "significant": sd2.get("significant", False),
                            "transitions": res2.get("transitions", 0),
                        })
                except Exception:
                    pass

            # Only update if fine value is strictly better (p < coarse value)
            fine_valid = [(r["delta"], r["p_value"]) for r in fine_results
                          if r["p_value"] is not None]
            if fine_valid:
                fine_opt_d, fine_opt_p = min(fine_valid, key=lambda x: x[1])
                if fine_opt_p is not None and fine_opt_p < opt_p:
                    prev_delta = opt_delta
                    opt_delta  = fine_opt_d
                    opt_p      = fine_opt_p
                    opt_sig    = opt_p < CONFIG.significance_threshold
                    if log_callback:
                        _t = _transitions_for_delta(opt_delta, _fine_fmap)
                        log_callback(t("analysis.fine_optimum", delta=opt_delta, transitions=_t, p=opt_p))
                elif log_callback:
                    _t = _transitions_for_delta(opt_delta, _fine_fmap)
                    log_callback(t("analysis.coarse_confirmed", delta=opt_delta, transitions=_t, p=opt_p))

        # ── Result for this species ──────────────────────────────────────────
        # Read GC content from cached analysis JSON (if available)
        gc_pct = None
        for cached_file in CONFIG.results_dir.glob(f"*gc_content*.json"):
            try:
                with open(cached_file, 'r', encoding='utf-8') as _gc:
                    _gc_data = json.load(_gc)
                if _gc_data.get("species") == sp_name:
                    gc_pct = _gc_data.get("mean_gc_percent")
                    break
            except Exception:
                pass

        # Captured base transitions for the optimal scheme+Δ
        opt_transitions = (_transitions_for_delta(opt_delta, opt_fmap)
                           if opt_delta is not None else "—")

        sp_result = {
            "name":              sp_name,
            "accession":         sp_info["accession"],
            "group":             sp_info["group"],
            "habitat":           habitat,
            "gc_content":        gc_pct,
            "optimal_delta":     opt_delta,
            "optimal_p_value":   opt_p,
            "significant":       opt_sig,
            "optimal_scheme":    opt_scheme,
            "optimal_transitions": opt_transitions,  # z.B. "A↔T" oder "A↔G"
            "extended_used":     extended_used,
            "all_deltas":        delta_results,
            "extended_deltas":   [r for r in all_results_for_sp
                                  if r.get("extended")],
            "fine_deltas":       fine_results,
        }
        results.append(sp_result)

        if log_callback:
            sig_icon = t("analysis.significant_icon") if opt_sig else t("analysis.not_significant_icon")
            try:
                p_str = f"{float(opt_p):.6f}" if opt_p is not None else "N/A"
            except (TypeError, ValueError):
                p_str = str(opt_p)
            try:
                d_str = f"{float(opt_delta):.6f}" if opt_delta is not None else "—"
            except (TypeError, ValueError):
                d_str = str(opt_delta)
            t_str = _transitions_for_delta(opt_delta, opt_fmap) if opt_delta else "—"
            log_callback(f"  ╔══ {sp_short} {'═'*max(0,38-len(sp_short))}╗")
            log_callback(t("analysis.result_box_delta", delta=d_str, transitions=t_str))
            log_callback(t("analysis.result_box_pvalue", p=p_str, icon=sig_icon))
            log_callback(t("analysis.result_box_habitat", habitat=habitat))
            log_callback(f"  ╚{'═'*48}╝")

        # ── Zwischenspeicherung nach jeder Spezies ───────────────────────
        # Allows resuming at 70% if interrupted.
        _interim_summary = _delta_optimization_summary(results, log_callback=None)
        _interim_output  = {
            "timestamp":  timestamp_str,
            "parameters": {
                "coarse_deltas": COARSE_DELTAS,
                "permutations":  permutations,
                "fine_tuning":   fine_tuning,
                "fine_perm":     fine_perm,
            },
            "summary": _interim_summary,
            "species": results,
        }
        # Overwrite the running file (fixed name without timestamp)
        _interim_path = CONFIG.results_dir / "delta_optimization_current.json"
        try:
            with open(_interim_path, 'w', encoding='utf-8') as _if:
                json.dump(_interim_output, _if, indent=2, ensure_ascii=False,
                          cls=NumpyEncoder)
        except Exception:
            pass

    if stop_event and stop_event.is_set():
        if log_callback:
            log_callback(f"⏹ Δ-Optimisation stopped early.")

    # ── Zusammenfassende Analyse ─────────────────────────────────────────────
    summary    = _delta_optimization_summary(results, log_callback)
    statistics = _finalize_delta_statistics(results, log_callback)

    output = {
        "timestamp":    timestamp_str,
        "parameters":   {
            "coarse_deltas":    COARSE_DELTAS,
            "permutations":     permutations,
            "fine_tuning":      fine_tuning,
            "fine_perm":        fine_perm,
        },
        "summary":    summary,
        "statistics": statistics,
        "species":    results,
    }

    # ── JSON speichern ────────────────────────────────────────────────────────
    ts          = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_json    = CONFIG.results_dir / f"delta_optimization_{ts}.json"
    out_md      = CONFIG.results_dir / f"delta_optimization_{ts}.md"
    out_csv     = CONFIG.results_dir / f"delta_optimization_{ts}.csv"
    out_heatmap = CONFIG.results_dir / f"delta_optimization_{ts}_heatmap.png"

    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)

    # ── Markdown-Report ───────────────────────────────────────────────────────
    _write_delta_markdown(output, out_md)

    # ── CSV-Export (Spezies × Delta → p-Wert) ────────────────────────────────
    _write_delta_csv(results, COARSE_DELTAS, out_csv)

    # ── Heatmap-visualisation ────────────────────────────────────────────────
    _write_delta_heatmap(results, COARSE_DELTAS, out_heatmap, log_callback)

    if log_callback:
        log_callback("=" * 80)
        log_callback(t("delta_optimization.report_completed", timestamp=ts))
        log_callback(t("analysis.delta_json", filename=out_json.name))
        log_callback(t("analysis.delta_markdown", filename=out_md.name))
        log_callback(t("analysis.delta_csv", filename=out_csv.name))
        log_callback(t("analysis.delta_heatmap", filename=out_heatmap.name))
        log_callback("=" * 80)

    return output


# ============================================================
# STATISTICAL FUNCTIONS FOR PUBLICATION-QUALITY Δ ANALYSIS
# ============================================================

def _cohens_d(data1: List[float], data2: List[float]) -> float:
    """
    Calculates Cohen's d as a measure of effect size.
    d > 0.2 = small, > 0.5 = medium, > 0.8 = large effect.
    """
    if len(data1) < 2 or len(data2) < 2:
        return 0.0
    n1, n2  = len(data1), len(data2)
    var1    = float(np.var(data1, ddof=1))
    var2    = float(np.var(data2, ddof=1))
    pooled  = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    return float(abs(np.mean(data1) - np.mean(data2)) / pooled) if pooled > 0 else 0.0


def _bootstrap_mean_ci(data: List[float], n_bootstrap: int = 5000,
                        ci: float = 95.0, seed: int = 42) -> Dict[str, float]:
    """95% bootstrap CI for the group mean."""
    rng   = np.random.default_rng(seed)
    arr   = np.array(data)
    means = [float(np.mean(arr[rng.integers(0, len(arr), len(arr))]))
             for _ in range(n_bootstrap)]
    lo    = float(np.percentile(means, (100 - ci) / 2))
    hi    = float(np.percentile(means, 100 - (100 - ci) / 2))
    return {"mean": float(np.mean(arr)), "ci_lower": lo, "ci_upper": hi,
            "n": len(data)}


def _finalize_delta_statistics(results: List[Dict],
                                 log_callback=None) -> Dict[str, Any]:
    """
    Complete statistical evaluation of Δ-optimisation results.

    Methods (by priority):
    1. Kruskal-Wallis-Test   – Gruppenunterschied (non-parametrisch)
    2. Mann-Whitney + Bonferroni – Post-hoc paarweise Vergleiche
    3. Cohen's d             – effect size per pair
    4. Bootstrap CI          – confidence intervals for group means
    5. ROC-AUC               – discriminative power of Δ as classifier
    6. Spearman-Korrelation  – GC-Gehalt vs. opt. Δ
    7. Bonferroni correction – for multiplicity
    8. LaTeX-Tabelle         – publikationsfertige Ausgabe
    """
    from scipy.stats import mannwhitneyu, kruskal, spearmanr

    # ── Habitat-Gruppen aufbauen ─────────────────────────────────────────────
    groups: Dict[str, List[float]] = {}
    gc_vals:  List[float] = []
    opt_vals: List[float] = []

    for r in results:
        d_opt = r.get("optimal_delta")
        if d_opt is None:
            continue
        hab = r.get("habitat", "unknown")
        groups.setdefault(hab, []).append(d_opt)
        gc = r.get("gc_content")
        if gc is not None:
            gc_vals.append(gc)
            opt_vals.append(d_opt)

    if not groups:
        return {}

    group_names = sorted(groups.keys())
    n_groups    = len(group_names)

    stats: Dict[str, Any] = {}

    # ── 1. Bootstrap CI for group means ────────────────────────────────────
    stats["group_stats"] = {
        h: _bootstrap_mean_ci(groups[h])
        for h in group_names if len(groups[h]) >= 2
    }

    # ── 2. Kruskal-Wallis (priority 1) ──────────────────────────────────────
    if n_groups >= 2:
        try:
            h_stat, kw_p = kruskal(*[groups[g] for g in group_names
                                      if len(groups[g]) >= 2])
            stats["kruskal_wallis"] = {
                "H":           float(h_stat),
                "p_value":     float(kw_p),
                "significant": bool(kw_p < 0.05),
                "interpretation": (
                    t("analysis.significant_habitat", h=h_stat, p=kw_p)
                    if kw_p < 0.05 else
                    t("analysis.no_significant_habitat", h=h_stat, p=kw_p)
                ),
            }
        except Exception as e:
            stats["kruskal_wallis"] = {"error": str(e)}

    # ── 3. Mann-Whitney + Bonferroni + Cohen's d (priority 2+3) ─────────────
    pairwise = []
    valid_groups = [g for g in group_names if len(groups[g]) >= 2]
    n_pairs = len(valid_groups) * (len(valid_groups) - 1) // 2
    alpha_bonferroni = 0.05 / max(n_pairs, 1)

    for i in range(len(valid_groups)):
        for j in range(i + 1, len(valid_groups)):
            g1, g2 = valid_groups[i], valid_groups[j]
            try:
                u_stat, mw_p = mannwhitneyu(groups[g1], groups[g2],
                                             alternative='two-sided')
                d = _cohens_d(groups[g1], groups[g2])
                effect_label = ("negligible" if d < 0.2 else
                                "small"      if d < 0.5 else
                                "medium"     if d < 0.8 else "large")
                pairwise.append({
                    "group1":            g1,
                    "group2":            g2,
                    "mean1":             float(np.mean(groups[g1])),
                    "mean2":             float(np.mean(groups[g2])),
                    "U_statistic":       float(u_stat),
                    "p_value":           float(mw_p),
                    "p_bonferroni":      float(min(mw_p * n_pairs, 1.0)),
                    "significant":       bool(mw_p < alpha_bonferroni),
                    "cohens_d":          float(d),
                    "effect_size":       effect_label,
                })
            except Exception as e:
                pairwise.append({"group1": g1, "group2": g2, "error": str(e)})

    stats["pairwise_tests"] = pairwise
    stats["bonferroni_alpha"] = float(alpha_bonferroni)
    stats["n_pairs"] = n_pairs

    # ── 4. ROC-AUC: Δ as classifier (priority 5) ────────────────────────────
    # microbe vs. terrestrial (largest and most interesting group)
    try:
        from sklearn.metrics import roc_auc_score
        roc_pairs = [
            ("microbe_host", "terrestrial"), ("microbe_env", "terrestrial"),
            ("microbe_host", "microbe_env"), ("aquatic", "terrestrial"),
            ("microbe_aquatic", "terrestrial"), ("microbe_host", "aquatic"),
            ("microbe_env", "aquatic"),
        ]
        roc_results = []
        for cls_pos, cls_neg in roc_pairs:
            y_true = ([1] * len(groups.get(cls_pos, [])) +
                      [0] * len(groups.get(cls_neg, [])))
            y_sc   = (groups.get(cls_pos, []) +
                      groups.get(cls_neg, []))
            if len(set(y_true)) == 2 and len(y_true) >= 4:
                auc = float(roc_auc_score(y_true, y_sc))
                roc_results.append({
                    "positive_class": cls_pos,
                    "negative_class": cls_neg,
                    "auc":            auc,
                    "interpretation": ("excellent" if auc > 0.9 else
                                       "good"      if auc > 0.8 else
                                       "fair"      if auc > 0.7 else
                                       "poor"),
                })
        stats["roc_auc"] = roc_results
    except ImportError:
        stats["roc_auc"] = {"note": "sklearn not available"}
    except Exception as e:
        stats["roc_auc"] = {"error": str(e)}

    # ── 5. Spearman correlation GC content vs. opt. Δ (priority 6) ──────────
    if len(gc_vals) >= 5:
        try:
            corr, sp_p = spearmanr(opt_vals, gc_vals)
            stats["gc_correlation"] = {
                "spearman_r":    float(corr),
                "p_value":       float(sp_p),
                "significant":   bool(sp_p < 0.05),
                "n":             len(gc_vals),
                "interpretation": (
                    t("analysis.significant_gc_corr", r=corr, p=sp_p)
                    if sp_p < 0.05 else
                    t("analysis.no_significant_gc_corr", r=corr, p=sp_p)
                ),
            }
        except Exception as e:
            stats["gc_correlation"] = {"error": str(e)}
    else:
        stats["gc_correlation"] = {"note": t("analysis.gc_data_insufficient", n=len(gc_vals))}

    # ── 6. LaTeX table (priority 7) ──────────────────────────────────────────
    stats["latex_table"] = _generate_latex_table(results, alpha_bonferroni)

    if log_callback:
        kw = stats.get("kruskal_wallis", {})
        kw_h = kw.get('H')
        kw_p = kw.get('p_value')
        h_str = f"{float(kw_h):.3f}" if kw_h is not None else "?"
        p_str = f"{float(kw_p):.4f}" if kw_p is not None else "?"
        log_callback(f"  📊 Kruskal-Wallis: H={h_str}  "
                     f"p={p_str}  "
                     f"{t('analysis.sig_kruskal') if kw.get('significant') else t('analysis.nonsig_kruskal')}")
        for pw in pairwise:
            if "error" not in pw:
                log_callback(t("analysis.pairwise_test", g1=pw["group1"], g2=pw["group2"],
                                p=pw['p_value'], alpha=alpha_bonferroni, d=pw['cohens_d'], effect=pw['effect_size']))

    return stats


def _generate_latex_table(results: List[Dict], alpha: float = 0.05) -> str:
    """Generiert eine publikationsreife LaTeX-Tabelle."""
    rows = []
    rows.append(r"\begin{table}[htbp]")
    rows.append(r"\centering")
    rows.append(r"\small")
    rows.append(r"\begin{tabular}{llcccc}")
    rows.append(r"\hline")
    rows.append(t("analysis.latex_row_header"))
    rows.append(r"\hline")
    for r in sorted(results,
                    key=lambda x: (x.get("habitat", ""), x.get("optimal_delta") or 99)):
        d_opt = r.get("optimal_delta")
        p_opt = r.get("optimal_p_value")
        sch   = (r.get("optimal_scheme") or "standard") if d_opt is not None else "--"
        sp_s  = r["name"].split("(")[0].strip().replace("&", r"\&")
        d_str = f"{d_opt:.1f}" if d_opt is not None else "--"
        p_str = f"{p_opt:.4f}" if p_opt is not None else "--"
        sig   = r"$\checkmark$" if r.get("significant") else "--"
        rows.append(f"{sp_s} & {r.get('habitat','?')} & {d_str} & "
                    f"{sch} & {p_str} & {sig} \\\\")
    rows.append(r"\hline")
    rows.append(r"\end{tabular}")
    cap = f"\\caption{{{t('analysis.latex_caption_full', alpha=alpha)}}}"
    rows.append(cap)
    rows.append(r"\label{tab:delta_optimization}")
    rows.append(r"\end{table}")
    return "\n".join(rows)

def _delta_optimization_summary(results: List[Dict], log_callback=None) -> Dict[str, Any]:
    """
    Erstellt die Zusammenfassungsanalyse der Δ-Optimierung:
    - Gruppierung nach optimalem Δ
    - Korrelation mit Lebensraum (terrestrisch vs. aquatisch)
    - Outlier identification
    """
    if not results:
        return {}

    # Gruppierung nach optimalem Δ
    by_delta: Dict[float, List[str]] = {}
    for r in results:
        d = r.get("optimal_delta")
        if d is not None:
            by_delta.setdefault(round(d, 3), []).append(r["name"])

    # Lebensraum-Korrelation
    habitat_delta: Dict[str, List] = {}
    for r in results:
        h = r.get("habitat", "unknown")
        d = r.get("optimal_delta")
        if d is not None:
            habitat_delta.setdefault(h, []).append(d)

    habitat_mean = {h: float(np.mean(ds)) for h, ds in habitat_delta.items() if ds}

    # Most frequent Δ per habitat
    habitat_modal: Dict[str, Optional[float]] = {}
    for h, ds in habitat_delta.items():
        if ds:
            from collections import Counter
            habitat_modal[h] = Counter([round(d, 1) for d in ds]).most_common(1)[0][0]

    # Terrestrisches Referenz-Δ (Modal aller terrestrischen Tiere)
    terrestrial_ds = habitat_delta.get("terrestrial", [])
    ref_delta      = float(np.median(terrestrial_ds)) if terrestrial_ds else 2.0

    # Outliers: species whose opt. Δ deviates strongly from habitat modal.
    # Threshold 0.9 = requires at least one full Δ-step deviation
    # (avoids flagging half-step variants as outliers with 5-category system)
    OUTLIER_THRESHOLD = 0.9
    outliers = []
    for r in results:
        h     = r.get("habitat", "unknown")
        d_opt = r.get("optimal_delta")
        modal = habitat_modal.get(h)
        if d_opt is not None and modal is not None:
            d_opt = float(d_opt)   # ensure float for format strings
            modal = float(modal)
            if abs(d_opt - modal) > OUTLIER_THRESHOLD:
                outliers.append({
                    "name":          r["name"],
                    "habitat":       h,
                    "optimal_delta": d_opt,
                    "habitat_modal": modal,
                    "deviation":     round(abs(d_opt - modal), 3),
                })

    summary = {
        "total_species":     len(results),
        "completed":         sum(1 for r in results if r.get("optimal_delta") is not None),
        "significant_count": sum(1 for r in results if r.get("significant")),
        "reference_delta":   ref_delta,
        "by_optimal_delta":  {str(k): v for k, v in sorted(by_delta.items())},
        "habitat_mean_delta": habitat_mean,
        "habitat_modal_delta": habitat_modal,
        "outliers":          outliers,
    }

    if log_callback:
        log_callback(t("analysis.delta_summary_header"))
        log_callback(t("analysis.terrestrial_ref", delta=float(ref_delta)))
        log_callback(t("analysis.habitat_modal", modal=habitat_modal))
        log_callback(t("delta_optimization.summary_significant_count", count=summary["significant_count"], total=summary["total_species"]))
        if outliers:
            log_callback(t("delta_optimization.summary_outliers", count=len(outliers)))
            for o in outliers:
                log_callback(t("analysis.outlier_item",
                               species=species_display(o['name']),
                               delta=o['optimal_delta'],
                               modal=o['habitat_modal'],
                               dev=o['deviation']))

    return summary

def _write_delta_markdown(output: Dict, path) -> None:
    """Writes the Δ-optimisation report as a Markdown file."""
    results    = output.get("species", [])
    summary    = output.get("summary", {})
    params     = output.get("parameters", {})
    deltas     = params.get("coarse_deltas", [])
    timestamp  = output.get("timestamp", "")

    lines = []
    lines.append(t("analysis.delta_report_title"))
    lines.append("")
    lines.append(t("report.delta_created", timestamp=timestamp))
    lines.append(t("analysis.delta_coarse_line", deltas=deltas, perms=params.get("permutations","?")))
    lines.append(t("analysis.delta_fine_line", status=t("analysis.delta_fine_enabled_word") if params.get("fine_tuning") else t("analysis.delta_fine_disabled_word"), perms=params.get("fine_perm","?")))
    lines.append("")

    # Zusammenfassung
    lines.append(t("report.delta_summary_title"))
    lines.append("")
    lines.append(t('analysis.analysed_species_line', done=summary.get('completed',0), total=summary.get('total_species',0)))
    lines.append(t("analysis.delta_significant_count", count=summary.get("significant_count", 0)))
    lines.append(t('analysis.terrestrial_ref_line', delta=float(summary.get('reference_delta', 2.0))))
    lines.append("")

    # Habitat-Modal
    modal = summary.get("habitat_modal_delta", {})
    if modal:
        lines.append(t("report.delta_by_habitat_short"))
        lines.append("")
        lines.append(t("report.delta_habitat_short_col"))
        lines.append("|-----------|---------|------------|")
        mean_d = summary.get("habitat_mean_delta", {})
        for h in sorted(modal.keys()):
            lines.append(f"| {_habitat_label(h)} | **{modal[h]:.1f}** | {mean_d.get(h, 0):.2f} |")
        lines.append("")

    # Gruppierung nach optimalem Δ
    by_delta = summary.get("by_optimal_delta", {})
    if by_delta:
        lines.append(t("report.delta_by_delta"))
        lines.append("")
        for d_str, sp_list in sorted(by_delta.items(), key=lambda x: float(x[0])):
            lines.append(t("report.delta_group_header", delta=d_str, count=len(sp_list)))
            for sp in sp_list:
                lines.append(f"  - {sp}")
        lines.append("")

    # Outliers
    outliers = summary.get("outliers", [])
    if outliers:
        lines.append(t("report.delta_outliers"))
        lines.append("")
        lines.append(t("report.delta_outliers_col"))
        lines.append("|---------|-----------|--------|--------------|-----------|")
        for o in outliers:
            lines.append(f"| {species_display(o['name'])} | {o['habitat']} | {o['optimal_delta']} "
                         f"| {o['habitat_modal']} | {o['deviation']} |")
        lines.append("")

    # Detailtabelle alle Spezies
    lines.append(t("report.delta_detail_title"))
    lines.append("")
    header = t("analysis.delta_detail_col")
    sep    = "|---------|--------|-----------|--------|--------|------------|"
    lines.append(header); lines.append(sep)
    for r in sorted(results, key=lambda x: (x.get("habitat",""), x.get("optimal_delta") or 99)):
        d  = r.get("optimal_delta")
        p  = r.get("optimal_p_value")
        sig = "✅" if r.get("significant") else "—"
        d_fmt = f"{float(d):.6f}" if d is not None else "—"
        p_fmt = f"{float(p):.6f}" if p is not None else "—"
        lines.append(f"| {r['name']} | {r.get('group','?')} | {r.get('habitat','?')} "
                     f"| {d_fmt} | {p_fmt} | {sig} |")
    lines.append("")

    # p-Wert-Tabelle (Spezies × Δ)
    lines.append(t("report.delta_pvalue_matrix"))
    lines.append("")
    delta_header = t("analysis.delta_pvalue_col", deltas=" | ".join(f"Δ={d:.1f}" for d in deltas))
    delta_sep    = "|---------|" + "--------|" * len(deltas)
    lines.append(delta_header); lines.append(delta_sep)
    for r in results:
        p_map = {rd["delta"]: rd.get("p_value") for rd in r.get("all_deltas", [])}
        cells = []
        for d in deltas:
            p = p_map.get(d)
            if p is None:
                cells.append("—")
            elif p < 0.05:
                cells.append(f"**{p:.3f}**")   # Signifikante fett
            else:
                cells.append(f"{p:.3f}")
        sp_short = r["name"].split("(")[0].strip()
        lines.append(f"| {sp_short} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append(t("analysis.delta_pvalue_note"))

    Path(path).write_text("\n".join(lines), encoding='utf-8')


def _write_delta_csv(results: List[Dict], deltas: List[float], path) -> None:
    """
    CSV-Export der Δ-Optimierungs-Ergebnisse.
    Spalten: Spezies, Gruppe, Lebensraum, Opt.Delta, Opt.p, Signifikant,
             p_delta_1.0, p_delta_1.2, ..., p_delta_3.0
    """
    import csv
    fieldnames = (["species", "group", "habitat", "optimal_delta",
                   "optimal_scheme", "optimal_p_value", "significant",
                   "extended_used"] +
                  [f"p_delta_{d:.1f}" for d in deltas])
    rows = []
    for r in results:
        p_map = {rd["delta"]: rd.get("p_value") for rd in r.get("all_deltas", [])}
        # Include extended results in p_map (if better)
        for rd in r.get("extended_deltas", []):
            key = rd["delta"]
            if key not in p_map or (rd.get("p_value") is not None
                                     and rd["p_value"] < (p_map.get(key) or 1.0)):
                p_map[key] = rd.get("p_value")
        row = {
            "species":         r["name"],
            "group":           r.get("group", ""),
            "habitat":         r.get("habitat", ""),
            "optimal_delta":   r.get("optimal_delta", ""),
            "optimal_scheme":  (r.get("optimal_scheme") or "standard") if r.get("optimal_delta") is not None else "--",
            "optimal_p_value": r.get("optimal_p_value", ""),
            "significant":     int(r.get("significant", False)),
            "extended_used":   ",".join(r.get("extended_used", [])),
        }
        for d in deltas:
            row[f"p_delta_{d:.1f}"] = p_map.get(d, "")
        rows.append(row)

    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_delta_heatmap(results: List[Dict], deltas: List[float],
                          path, log_callback=None) -> None:
    """
    Heatmap: Spezies (Y-Achse) × Δ (X-Achse), Farbkodierung = p-Wert.
    - Green = significant (p<0.05)
    - Gelb = grenzwertig (0.05-0.10)
    - Rot = nicht signifikant (p>0.10)
    Optimales Δ je Spezies mit ★ markiert.
    """
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
        import numpy as _np

        n_sp  = len(results)
        n_d   = len(deltas)
        if n_sp == 0 or n_d == 0:
            return

        # p-Wert-Matrix aufbauen (NaN = kein Ergebnis)
        matrix   = _np.full((n_sp, n_d), _np.nan)
        opt_mask = _np.zeros((n_sp, n_d), dtype=bool)

        sp_labels = []
        for i, r in enumerate(results):
            sp_labels.append(r["name"].split("(")[0].strip()
                             + f" [{r.get('habitat','?')[0].upper()}]")
            p_map = {rd["delta"]: rd.get("p_value") for rd in r.get("all_deltas", [])}
            for j, d in enumerate(deltas):
                p = p_map.get(d)
                if p is not None:
                    matrix[i, j] = p
            # Optimales Δ markieren
            opt_d = r.get("optimal_delta")
            if opt_d is not None and opt_d in deltas:
                opt_mask[i, deltas.index(opt_d)] = True

        # Colour scale: 0 (green) → 0.05 (yellow) → 1.0 (red)
        cmap   = mcolors.LinearSegmentedColormap.from_list(
            "pval", [(0.0, "#27AE60"), (0.05, "#F39C12"), (0.15, "#E74C3C"), (1.0, "#922B21")])
        cmap.set_bad("#2C3E50")   # NaN → dunkelgrau

        fig_h = max(6, n_sp * 0.35)
        fig, ax = plt.subplots(figsize=(max(10, n_d * 1.2), fig_h))
        fig.patch.set_facecolor('#0d0d1a')
        ax.set_facecolor('#0d0d1a')

        im = ax.imshow(matrix, cmap=cmap, vmin=0, vmax=1.0,
                       aspect='auto', interpolation='nearest')

        # Signifikanz-Grenze bei 0.05 einzeichnen
        plt.colorbar(im, ax=ax, label=t('analysis.heatmap_pvalue_label'), fraction=0.03, pad=0.02)

        # Optimales Δ mit ★ markieren
        for i in range(n_sp):
            for j in range(n_d):
                if opt_mask[i, j]:
                    ax.text(j, i, '★', ha='center', va='center',
                            fontsize=9, color='white', fontweight='bold')
                elif not _np.isnan(matrix[i, j]):
                    p = matrix[i, j]
                    ax.text(j, i, f"{p:.2f}", ha='center', va='center',
                            fontsize=6, color='white' if p < 0.5 else '#ddd')

        ax.set_xticks(range(n_d))
        ax.set_xticklabels([f"Δ={d:.1f}" for d in deltas],
                           rotation=45, ha='right', color='#eee', fontsize=9)
        ax.set_yticks(range(n_sp))
        ax.set_yticklabels(sp_labels, color='#eee', fontsize=8)
        ax.set_xlabel(t('analysis.heatmap_xlabel'), color='#eee')
        ax.set_title(t('analysis.heatmap_title'),
                     color='#eee', fontsize=11)
        ax.tick_params(colors='#aaa')
        for sp in ax.spines.values():
            sp.set_color('#444')

        # Signifikanz-Linie p=0.05 als Legende
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#27AE60', label=t('analysis.heatmap_legend_sig')),
            Patch(facecolor='#F39C12', label=t('analysis.legend_p_005_015')),
            Patch(facecolor='#E74C3C', label=t('analysis.legend_p_gt_015')),
            Patch(facecolor='#2C3E50', label=t('analysis.heatmap_legend_none')),
        ]
        ax.legend(handles=legend_elements, loc='lower right',
                  facecolor='#1a1a2e', labelcolor='#eee', fontsize=8)

        plt.tight_layout()
        plt.savefig(str(path), dpi=150, bbox_inches='tight', facecolor='#0d0d1a')
        plt.close(fig)

    except Exception as e:
        if log_callback:
            log_callback(t("analysis.heatmap_error", error=e))




class DNARhythmAnalyzer:
    # Methoden-Definitionen (ohne "Alle Methoden")
    METHODS = {
        "1. Differenzspektrum (Δ=2.0)":    "two_thz",
        "2. Fibonacci-distances":            "fibonacci",
        "3. Golden Ratio":              "golden_ratio",
        "4. Power-Law-Verteilung":          "power_law",
        "5. CGR (Chaos Game)":              "cgr",
        "6. Frequenzprofil":                "piano_roll",
        "7. Autokorrelation":               "autocorr",
        "8. GC-Content-Variation":          "gc_content",
        "9. Dinukleotid-Bias":              "dinucleotide",
        "10. Komplettanalyse":              "all",
    }

    # i18n key → method_id mapping for live language switching
    METHOD_I18N_KEYS = [
        ("methods.two_thz",     "two_thz"),
        ("methods.fibonacci",   "fibonacci"),
        ("methods.golden_ratio","golden_ratio"),
        ("methods.power_law",   "power_law"),
        ("methods.cgr",         "cgr"),
        ("methods.piano_roll",  "piano_roll"),
        ("methods.autocorr",    "autocorr"),
        ("methods.gc_content",  "gc_content"),
        ("methods.dinucleotide","dinucleotide"),
        ("methods.all_methods", "all"),
    ]

    def __init__(self, root):
        self.root = root
        self.root.title(t("app.title"))
        self.root.geometry("1200x900")

        self.logger = setup_logging()
        self.cache = AnalysisCache(CONFIG.cache_db)
        self._stop_event = threading.Event()

        # Register for live language-change callbacks
        _i18n.register_callback(self._on_language_changed)

        self.setup_ui()
        self.cache.clear_old(30)

    def _on_language_changed(self, lang_code: str):
        """Updates all UI strings immediately when language is switched."""
        self.root.title(t("app.title"))

        # ── Point 1: Complete Analysis label updated FIRST ────────────────────
        complete_key = next((k for k, m in self.METHOD_I18N_KEYS if m == "all"), None)
        if complete_key and hasattr(self, '_complete_analysis_str') and self._complete_analysis_str:
            self._complete_analysis_str.set(t(complete_key))

        # ── Point 2: Method checkbox labels via stable method_id keys ─────────
        analysis_keys = [(k, m) for k, m in self.METHOD_I18N_KEYS if m != "all"]
        for i18n_key, method_id in analysis_keys:
            if method_id in self._method_label_vars:
                self._method_label_vars[method_id].set(t(i18n_key))

        # ── Points 4+5: Rebuild species combobox with newly translated names ────
        if hasattr(self, 'species_combo'):
            # Save current internal key before rebuilding
            current_display  = self.species_var.get()
            current_internal = self._species_display_to_key.get(current_display)

            # Build NEW mapping with translated display names for new language
            self._species_display_to_key = {species_display(k): k for k in SPECIES_DB}

            # Update combobox values with translated names
            self.species_combo.config(values=sorted(self._species_display_to_key.keys()))

            # Restore selection in new language
            if current_internal:
                self.species_var.set(species_display(current_internal))
            elif current_display in self._species_display_to_key:
                # Already a valid translated name in new language
                self.species_var.set(current_display)

        # ── Buttons ───────────────────────────────────────────────────────────
        for attr, key in [
            ('single_btn',      'buttons.single_analysis'),
            ('batch_btn',       'buttons.batch_analysis'),
            ('stop_btn',        'buttons.stop_analysis'),
            ('consolidate_btn', 'buttons.generate_report'),
            ('settings_btn',    'buttons.settings'),
            ('clear_btn',       'buttons.clear_log'),
            ('btn_3d_real',     'buttons.reconstruct_3d_realistic'),
            ('btn_delta',       'buttons.delta_optimization'),
            ('reset_delta_btn', 'buttons.reset_delta'),
            ('deviation_btn',   'buttons.delta_deviation'),
            ('reset_btn',       'buttons.reset_analysis'),
        ]:
            if hasattr(self, attr):
                try:
                    getattr(self, attr).config(text=t(key))
                except Exception:
                    pass

        # ── Section labels ────────────────────────────────────────────────────
        if hasattr(self, '_methods_label_widget'):
            self._methods_label_widget.config(text=t("methods.title"))
        if hasattr(self, '_species_label_widget'):
            self._species_label_widget.config(text=t("species.title"))

        # ── Status — retranslate only if showing a ready/stopped state ────────
        if hasattr(self, 'status_label'):
            current_text = self.status_label.cget('text')
            ready_texts  = {t("app.status_ready", default="Ready")}
            # Add all 8-language ready strings to catch any current language
            for lang in ['en','de','fr','es','zh','ja','ru','pt']:
                try:
                    from pathlib import Path
                    import json
                    p = Path(_get_base_dir()) / "languages" / f"{lang}.json"
                    with open(p, encoding='utf-8') as _f:
                        _d = json.load(_f)
                    ready_texts.add(_d.get('app', {}).get('status_ready', ''))
                except Exception:
                    pass
            if current_text in ready_texts or current_text == '':
                self.status_label.config(text=t("app.status_ready"))

    def _on_complete_analysis_toggled(self):
        """Complete Analysis checkbox: enable or disable all method checkboxes."""
        state = self._complete_analysis_var.get()
        for var in self.method_vars.values():
            var.set(state)

    def _on_method_checkbox_changed(self):
        """If all methods are checked, tick Complete Analysis; if any unchecked, untick it."""
        if self._complete_analysis_var is None:
            return
        all_checked = all(v.get() for v in self.method_vars.values())
        self._complete_analysis_var.set(all_checked)

    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # ── Method checkboxes (2 rows × 5 columns) ──────────────────────────
        self._methods_label_widget = ttk.Label(
            main_frame, text=t("methods.title"), font=('Arial', 10, 'bold'))
        self._methods_label_widget.grid(
            row=0, column=0, columnspan=5, sticky=tk.W, pady=(5, 2))

        cb_frame = ttk.Frame(main_frame)
        cb_frame.grid(row=1, column=0, columnspan=5, sticky=(tk.W, tk.E), pady=2)

        self.method_vars = {}           # method_id -> BooleanVar  (stable key, language-independent)
        self._method_label_vars = {}    # method_id -> StringVar   (for live language switching)
        self._complete_analysis_var = None  # BooleanVar for the "Complete Analysis" checkbox

        # Separate analysis methods from the "Complete Analysis" toggle
        analysis_keys  = [(k, m) for k, m in self.METHOD_I18N_KEYS if m != "all"]
        complete_key   = next(((k, m) for k, m in self.METHOD_I18N_KEYS if m == "all"), None)

        for idx, (i18n_key, method_id) in enumerate(analysis_keys):
            label_text = t(i18n_key)
            bool_var   = tk.BooleanVar(value=False)
            str_var    = tk.StringVar(value=label_text)
            self.method_vars[method_id]       = bool_var   # keyed by stable method_id
            self._method_label_vars[method_id] = str_var
            ttk.Checkbutton(
                cb_frame, textvariable=str_var, variable=bool_var,
                command=self._on_method_checkbox_changed
            ).grid(row=idx // 5, column=idx % 5, sticky=tk.W, padx=8, pady=3)

        # "Complete Analysis" checkbox — toggles all others
        if complete_key:
            i18n_key, _ = complete_key
            self._complete_analysis_var = tk.BooleanVar(value=False)
            self._complete_analysis_str  = tk.StringVar(value=t(i18n_key))
            n = len(analysis_keys)
            ttk.Checkbutton(
                cb_frame,
                textvariable=self._complete_analysis_str,
                variable=self._complete_analysis_var,
                command=self._on_complete_analysis_toggled,
            ).grid(row=n // 5, column=n % 5, sticky=tk.W, padx=8, pady=3)

        # ── Species selection ────────────────────────────────────────────────
        self._species_label_widget = ttk.Label(
            main_frame, text=t("species.title"), font=('Arial', 10, 'bold'))
        self._species_label_widget.grid(
            row=2, column=0, columnspan=5, sticky=tk.W, pady=(10, 2))

        self.species_var = tk.StringVar()
        # Build display→internal mapping with current language
        self._species_display_to_key = {species_display(k): k for k in SPECIES_DB}
        self.species_combo = ttk.Combobox(main_frame, textvariable=self.species_var,
                                          values=sorted(self._species_display_to_key.keys()),
                                          width=80)
        self.species_combo.grid(row=3, column=0, columnspan=5, sticky=(tk.W, tk.E), pady=2)
        self.species_combo.bind('<<ComboboxSelected>>', self.on_species_selected)

        self.species_info_label = ttk.Label(main_frame, text="", foreground="gray")
        self.species_info_label.grid(row=4, column=0, columnspan=5, sticky=tk.W, pady=2)

        # ── Buttons ──────────────────────────────────────────────────────────
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, columnspan=5, pady=8)

        self.single_btn = ttk.Button(button_frame, text=t("buttons.single_analysis"),
                                     command=self.start_single_analysis)
        self.single_btn.pack(side=tk.LEFT, padx=5)

        self.batch_btn = ttk.Button(button_frame, text=t("buttons.batch_analysis"),
                                    command=self.start_batch_analysis)
        self.batch_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(button_frame, text=t("buttons.stop_analysis"),
                                   command=self.stop_analysis, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.consolidate_btn = ttk.Button(button_frame, text=t("buttons.generate_report"),
                                          command=self.generate_consolidated_report)
        self.consolidate_btn.pack(side=tk.LEFT, padx=5)

        self.settings_btn = ttk.Button(button_frame, text=t("buttons.settings"),
                                       command=self.show_settings)
        self.settings_btn.pack(side=tk.LEFT, padx=5)

        self.clear_btn = ttk.Button(button_frame, text=t("buttons.clear_log"),
                                    command=self.clear_log)
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.btn_3d_real = ttk.Button(button_frame, text=t("buttons.reconstruct_3d_realistic"),
                                       command=self.start_3d_realistic)
        self.btn_3d_real.pack(side=tk.LEFT, padx=5)

        self.btn_delta = ttk.Button(button_frame, text=t("buttons.delta_optimization"),
                                     command=self.start_delta_optimization)
        self.btn_delta.pack(side=tk.LEFT, padx=5)

        self.reset_delta_btn = ttk.Button(button_frame, text=t("buttons.reset_delta"),
                                          command=self.confirm_reset_delta,
                                          style='Reset.TButton')
        self.reset_delta_btn.pack(side=tk.LEFT, padx=5)

        self.deviation_btn = ttk.Button(button_frame, text=t("buttons.delta_deviation"),
                                        command=self.start_deviation_analysis)
        self.deviation_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = ttk.Button(button_frame, text=t("buttons.reset_analysis"),
                                    command=self.confirm_reset, style='Reset.TButton')
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        # ── Status ───────────────────────────────────────────────────────────
        self.status_label = ttk.Label(main_frame, text=t("app.status_ready"), foreground="green")
        self.status_label.grid(row=6, column=0, columnspan=5, sticky=tk.W, pady=2)

        # ── Log ──────────────────────────────────────────────────────────────
        self._log_label_widget = ttk.Label(
            main_frame, text="Log / Output:", font=('Arial', 10, 'bold'))
        self._log_label_widget.grid(
            row=7, column=0, columnspan=5, sticky=tk.W, pady=(5, 2))

        self.log_text = scrolledtext.ScrolledText(main_frame, width=130, height=35, wrap=tk.WORD)
        self.log_text.grid(row=8, column=0, columnspan=5, sticky=(tk.W, tk.E, tk.N, tk.S))

        self.progress = ttk.Progressbar(main_frame, mode='indeterminate')
        self.progress.grid(row=9, column=0, columnspan=5, sticky=(tk.W, tk.E), pady=5)

        # Grid-Konfiguration
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(8, weight=1)

    def _get_selected_methods(self):
        """Returns list of selected (display_label, method_id) pairs.
        Uses stable method_id keys — language-independent."""
        return [
            (self._method_label_vars[method_id].get(), method_id)
            for method_id, bool_var in self.method_vars.items()
            if bool_var.get()
        ]

    def _set_buttons(self, state):
        for btn in (self.single_btn, self.batch_btn,
                    self.consolidate_btn, self.settings_btn,
                    self.btn_3d_real, self.btn_delta,
                    self.reset_delta_btn, self.deviation_btn):
            btn.config(state=state)
        # Stop-Button ist genau entgegengesetzt
        self.stop_btn.config(state=tk.NORMAL if state == tk.DISABLED else tk.DISABLED)

    def stop_analysis(self):
        self._stop_event.set()
        self.stop_btn.config(state=tk.DISABLED)
        self.status_label.config(text=t("app.status_stop_requested"), foreground="red")
        self.log(t("log_messages.stop_requested"))

    def on_species_selected(self, event):
        """Handles species selection — resolves translated display name to internal key."""
        display_name  = self.species_var.get()
        # Resolve translated display name → internal SPECIES_DB key
        internal_key  = self._species_display_to_key.get(display_name)
        if not internal_key:
            # Fallback: direct match (e.g. if somehow internal key was set)
            internal_key = display_name if display_name in SPECIES_DB else None
        if internal_key and internal_key in SPECIES_DB:
            info = SPECIES_DB[internal_key]
            group_key = f"species.group_{info['group']}"
            group_str = t(group_key) if t(group_key) != group_key else info['group']
            self.species_info_label.config(
                text=t("species.info_label",
                       accession=info["accession"],
                       group=group_str))
    
    def _resolve_species(self):
        """Resolves species_var (may contain translated display name) to internal SPECIES_DB key.
        Returns (internal_key, info) or (None, None) if not found."""
        display = self.species_var.get()
        # Try translated display name first
        internal = self._species_display_to_key.get(display)
        if not internal:
            # Fallback: direct match (internal key entered directly)
            internal = display if display in SPECIES_DB else None
        if internal and internal in SPECIES_DB:
            return internal, SPECIES_DB[internal]
        return None, None

    def log(self, message):
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        self.logger.info(message)
    
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        self.status_label.config(text=t("app.status_ready"), foreground="green")

    def start_hbond_visualization(self):
        self._start_recon_common("H-bonds", self._run_hbond_visualization)

    def start_histone_visualization(self):
        self._start_recon_common("Histone+Disulfid", self._run_histone_visualization)

    def _run_hbond_visualization(self, species_name, species_info):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.start_hbond", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log("=" * 80)
            result = run_hbond_visualization(species_name, species_info,
                                              log_callback=self.log, open_browser=True)
            if "error" in result:
                self.log(f"❌ {result['error']}")
            else:
                self.log("✅ H-bond visualisation completed")
                self.log(t("analysis.folder", path=CONFIG.hbonds_dir))
            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t("log_messages.error_occurred", error=e))
            self.root.after(0, self._analysis_complete)

    def _run_histone_visualization(self, species_name, species_info):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.start_histone", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log("=" * 80)
            result = run_histone_visualization(species_name, species_info,
                                               log_callback=self.log, open_browser=True)
            if "error" in result:
                self.log(f"❌ {result['error']}")
            else:
                self.log("✅ Histone visualisation completed")
                self.log(t("analysis.folder", path=CONFIG.histones_dir))
            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def start_2d_reconstruction(self):
        self._start_recon_common("2D-Abwicklung", self._run_2d_reconstruction)

    def start_3d_realistic(self):
        self._start_recon_common("3D-Realistisch", self._run_3d_realistic)

    def _start_recon_common(self, label: str, target):
        species, info = self._resolve_species()
        if not species:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.select_species"))
            return
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(
            text=f"{label}: {species_display(species).split('(')[0].strip()}...", foreground="orange")
        threading.Thread(target=target, args=(species, info),
                         daemon=True).start()

    def _run_2d_reconstruction(self, species_name, species_info):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.start_2d", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log("=" * 80)

            fasta = get_or_fetch_genome(species_info["accession"], self.log)
            if not fasta:
                self.log(t("dialogs.genome_load_error"))
                self.root.after(0, self._analysis_complete); return

            reader = GenomeReader(fasta)
            seq    = reader.get_sequence(CONFIG.max_seq_length)
            seq_vis = seq[:1000]
            self.log(t("analysis.model_3d_info", length=len(seq_vis), height=len(seq_vis)*0.34, turns=len(seq_vis)/10.5))

            self.log(t("analysis.reconstructing_3d_2d"))
            coords, _ = reconstruct_realistic_3d_dna(seq_vis)

            coords_2d = project_2d_dna(coords)
            safe = (species_name.replace(" ", "_").replace("(", "")
                                .replace(")", "").replace(",", ""))
            png_path = CONFIG.real3d_dir / f"{safe}_2d_unwrapped.png"
            build_2d_unwrapped_plot(coords, seq_vis, species_name, png_path)
            self.log(t("analysis.unwrapping_file", path=png_path))

            self.log(t("analysis.analysing_2d"))
            m2d = analyze_2d_patterns(coords_2d, seq_vis, self.log)
            self.log(f"    Golden Ratio 2D:  {m2d.get('golden_ratio_match_2d',0):.4f}")
            self.log(f"    Fraktale Dim 2D:  {m2d.get('fractal_dimension_2d',0):.3f}")
            ap = m2d.get('angle_dominant_period_bp')
            self.log(f"    Winkel-period:   {f'{ap:.1f} bp' if ap else 'N/A'}")

            self.log("✅ 2D unwrapping completed")
            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def _run_3d_realistic(self, species_name, species_info):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.start_3d_realistic", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log(t("realistic_3d.model_desc"))
            self.log("=" * 80)

            result = run_realistic_reconstruction(
                species_name, species_info,
                log_callback=self.log,
                open_browser=True)

            if "error" in result:
                self.log(f"❌ {result['error']}")
            else:
                self.log(t("realistic_3d.completed"))
                self.log(t("analysis.result_dir_3d", path=CONFIG.real3d_dir))
                self.log(t("analysis.result_dir_2d", path=CONFIG.recon2d_dir))

            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def start_delta_optimization(self):
        """Starts the Δ-optimisation analysis in a background thread."""
        self._stop_event.clear()          # ← reset from any previous stop
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(text=t("app.status_analysis_running"), foreground="orange")
        thread = threading.Thread(target=self._run_delta_optimization, daemon=True)
        thread.start()

    def _run_delta_optimization(self):
        """Background thread for Δ-optimisation."""
        try:
            self.log("=" * 80)
            self.log(t("analysis.start_delta_opt", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("delta_optimization.coarse_scan", deltas=f"[{min(COARSE_DELTAS):.1f}..{max(COARSE_DELTAS):.1f}]", perms=200))
            self.log(t("delta_optimization.fine_tuning", perms=1000))
            self.log("=" * 80)

            result = run_delta_optimization(
                log_callback  = self.log,
                permutations  = 200,
                fine_tuning   = True,
                fine_perm     = 1000,
                stop_event    = self._stop_event,
            )

            if result:
                summary = result.get("summary", {})
                self.log("✅ Δ-Optimisation completed.")
                self.log(f"   Signifikante Spezies: {summary.get('significant_count', '?')}/"
                         f"{summary.get('total_species', '?')}")
                out_files = list(CONFIG.results_dir.glob("delta_optimization_*.json"))
                if out_files:
                    latest = max(out_files, key=lambda p: p.stat().st_mtime)
                    self.log(t("analysis.result_file", filename=latest.name))
            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t("log_messages.error_occurred", error=e))
            self.root.after(0, self._analysis_complete)

    def start_3d_reconstruction(self):
        species = self.species_var.get()
        if not species:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.select_species"))
            return
        if species not in SPECIES_DB:
            messagebox.showerror(t("dialogs.error"), t("dialogs.species_not_found"))
            return

        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(text=f"3D-Rekonstruktion: {species.split('(')[0].strip()}...",
                                  foreground="orange")

        thread = threading.Thread(target=self._run_3d_reconstruction,
                                  args=(species, SPECIES_DB[species]), daemon=True)
        thread.start()

    def _run_3d_reconstruction(self, species_name, species_info):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.start_3d", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log("=" * 80)

            spatial = run_3d_reconstruction(species_name, species_info,
                                            log_callback=self.log,
                                            open_browser=True)

            if "error" in spatial:
                self.log(f"❌ {spatial['error']}")
            else:
                self.log(t("3d_reconstruction.completed"))
                self.log(t("analysis.folder", path=CONFIG.recon3d_dir))

            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def start_deviation_analysis(self):
        """Start Δ-deviation analysis in background thread."""
        delta_files = list(CONFIG.results_dir.glob("delta_optimization_*.json"))
        if not delta_files:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.deviation_no_delta"))
            return
        self._stop_event.clear()
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(text=t("app.status_analysis_running"), foreground="orange")
        thread = threading.Thread(target=self._run_deviation_analysis, daemon=True)
        thread.start()

    def _run_deviation_analysis(self):
        """Background worker for Δ-deviation analysis."""
        try:
            run_delta_deviation_analysis(
                stop_event=self._stop_event,
                log_callback=self.log,
            )
        except Exception as e:
            self.log(t("log_messages.error_occurred", error=e))
        finally:
            self.root.after(0, self._analysis_complete)

    def confirm_reset_delta(self):
        """Delete only delta-optimisation files — keeps all other analysis results."""
        delta_files = list(CONFIG.results_dir.glob("delta_optimization_*.json"))
        delta_md    = list(CONFIG.results_dir.glob("delta_optimization_*.md"))
        delta_csv   = list(CONFIG.results_dir.glob("delta_optimization_*.csv"))
        delta_png   = list(CONFIG.results_dir.glob("delta_optimization_*_heatmap.png"))
        all_files   = delta_files + delta_md + delta_csv + delta_png

        if not all_files:
            messagebox.showinfo(t("dialogs.info"),
                                t("dialogs.reset_delta_nothing"))
            return

        msg = (t("dialogs.reset_delta_warning", count=len(delta_files))
               + "\n\n" + t("dialogs.reset_delta_keeps")
               + "\n\n" + t("dialogs.reset_dialog_continue"))

        if messagebox.askyesno(t("dialogs.reset_delta_title"), msg, icon='warning'):
            removed = 0
            for f in all_files:
                try:
                    f.unlink()
                    removed += 1
                except Exception as e:
                    self.log(t("analysis.reset_warning", error=e))
            self.log(t("dialogs.reset_delta_done", count=removed))
            messagebox.showinfo(t("dialogs.info"),
                                t("dialogs.reset_delta_done", count=removed))

    def confirm_reset(self):
        """Safety confirmation before reset."""
        delta_count = len(list(CONFIG.results_dir.glob("delta_optimization_*.json")))
        delta_info  = (t("dialogs.reset_dialog_delta", count=delta_count)
                       if delta_count else "")
        msg = (
            t("dialogs.reset_dialog_warning")
            + t("dialogs.reset_dialog_results", folder=CONFIG.results_dir.name)
            + delta_info
            + t("dialogs.reset_dialog_plots",   folder=CONFIG.plots_dir.name)
            + t("dialogs.reset_dialog_cache",   file=CONFIG.cache_db.name)
            + t("dialogs.reset_dialog_keep")
            + t("dialogs.reset_dialog_fasta",   folder=CONFIG.workspace_dir.name)
            + t("dialogs.reset_dialog_fasta_note")
            + t("dialogs.reset_dialog_continue")
        )
        if messagebox.askyesno(t("dialogs.reset_dialog_title"), msg, icon='warning'):
            self._set_buttons(tk.DISABLED)
            self.reset_btn.config(state=tk.DISABLED)
            self.progress.start(10)
            threading.Thread(target=self._do_reset, daemon=True).start()

    def _do_reset(self):
        """Deletes results, plots and SQLite cache (FASTA files are preserved)."""
        deleted = {"results": 0, "plots": 0, "db": False, "errors": []}
        try:
            # Result files (incl. Δ-optimisation files)
            deleted["delta_files"] = 0
            for f in CONFIG.results_dir.iterdir():
                try:
                    if f.name.startswith("delta_optimization_"):
                        deleted["delta_files"] += 1
                    f.unlink()
                    deleted["results"] += 1
                except Exception as e:
                    deleted["errors"].append(str(e))

            # Plot-Dateien
            for f in CONFIG.plots_dir.iterdir():
                try:
                    f.unlink()
                    deleted["plots"] += 1
                except Exception as e:
                    deleted["errors"].append(str(e))

            # SQLite cache: clear table (file and schema remain)
            try:
                with self.cache.get_connection() as conn:
                    conn.execute("DELETE FROM cached_analyses")
                deleted["db"] = True
            except Exception as e:
                deleted["errors"].append(f"DB: {e}")

        except Exception as e:
            deleted["errors"].append(str(e))

        self.root.after(0, lambda: self._reset_complete(deleted))

    def _reset_complete(self, deleted: dict):
        self.progress.stop()
        self._set_buttons(tk.NORMAL)
        self.reset_btn.config(state=tk.NORMAL)

        self.log("=" * 80)
        self.log(t("log_messages.reset_header", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.log("=" * 80)
        self.log(t("analysis.reset_results", count=deleted["results"]))
        self.log(t("analysis.reset_plots", count=deleted["plots"]))
        self.log(t("analysis.reset_cache", status="✅" if deleted["db"] else "❌"))
        if deleted["errors"]:
            for err in deleted["errors"]:
                self.log(t("analysis.reset_warning", error=err))
        self.log(t("analysis.reset_fasta", path=CONFIG.workspace_dir.name))
        self.status_label.config(text=t("dialogs.reset_complete"), foreground="green")
    
    def show_settings(self):
        dialog = SettingsDialog(self.root, CONFIG)
        dialog.show()
        if dialog.result:
            self.log(t("settings.settings_updated"))
    
    def start_single_analysis(self):
        selected = self._get_selected_methods()
        if not selected:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.select_method"))
            return

        species, species_info = self._resolve_species()
        if not species:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.select_species"))
            return

        self._stop_event.clear()          # reset from any previous stop
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(text=t("app.status_analysis_running"), foreground="orange")

        thread = threading.Thread(
            target=self._run_single_multi,
            args=(species, species_info, selected))
        thread.daemon = True
        thread.start()

    def _run_single_species(self, species_name, species_info, method_id, method_name):
        """Runs a single method for one species."""
        fasta = get_or_fetch_genome(species_info["accession"], self.log)
        if not fasta:
            self.log(f"❌ {t('dialogs.genome_load_error')}")
            return None

        reader = GenomeReader(fasta)
        seq = reader.get_sequence(CONFIG.max_seq_length)
        self.log(t("analysis.sequence_length", length=len(seq)))

        cached_result = self.cache.get(method_id, species_info["accession"], seq)
        if cached_result and "error" not in cached_result:
            self.log(t("analysis.cached"))
            result = cached_result
        else:
            if cached_result and "error" in cached_result:
                self.log(t("analysis.recalculating"))
            result = run_method(method_id, seq, self.log, species_name=species_name)
            if result and "error" not in result:
                self.cache.set(method_id, species_info["accession"], seq, result)

        if result and "error" not in result:
            result["species"] = species_name
            result["species_display"] = species_display(species_name)
            result["accession"] = species_info["accession"]
            result["accession"] = species_info["accession"]
            result["group"] = species_info["group"]
            result["method_id"] = method_id
            result["method_name"] = method_name
            result["timestamp"] = datetime.now().isoformat()

            plot_path = plot_results(result, species_name, method_id)
            if plot_path:
                self.log(t("analysis.visualization_saved", path=plot_path))
                result["plot_path"] = plot_path

            filename = get_safe_filename(method_id, species_name, species_info["accession"])
            filepath = CONFIG.results_dir / filename
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
            self.log(t("analysis.result_saved", filename=filename))

            if "statistical_significance" in result:
                sig = result["statistical_significance"]
                tag = t("analysis.significance_significant") if sig.get("significant") else t("analysis.significance_not_significant")
                icon = "📈" if sig.get("significant") else "📉"
                self.log(t("analysis.significance_result", icon=icon, p_value=sig["p_value"], tag=tag))
        else:
            error_msg = result.get("error", t("placeholders.unknown")) if result else t("placeholders.not_applicable")
            self.log(f"  ❌ {t('analysis.failed', species=error_msg)}")
        return result

    def _run_single_multi(self, species_name, species_info, selected_methods):
        """Single analysis for all selected methods of one species."""
        try:
            self.log("=" * 80)
            self.log(t("analysis.start_single", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.species_label", species=species_name))
            self.log(t("analysis.methods_label", methods=", ".join(label for label, _ in selected_methods)))
            self.log("=" * 80)

            for label, method_id in selected_methods:
                if self._stop_event.is_set():
                    self.log(t("log_messages.stopped"))
                    break
                # Skip if result file already exists
                filename = get_safe_filename(method_id, species_name, species_info["accession"])
                filepath = CONFIG.results_dir / filename
                if filepath.exists():
                    self.log(f"\n--- {label} ---")
                    self.log(t("analysis.skipped_exists", filename=filename))
                    continue
                self.log(f"\n--- {label} ---")
                self._run_single_species(species_name, species_info, method_id, label)

            self.root.after(0, self._analysis_complete)
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def start_batch_analysis(self):
        selected = self._get_selected_methods()
        if not selected:
            messagebox.showwarning(t("dialogs.warning"), t("dialogs.select_method"))
            return

        self._stop_event.clear()          # reset from any previous stop
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        labels = ", ".join(label for label, _ in selected)
        self.status_label.config(text=f"{t('app.status_analysis_running')} ({labels})", foreground="orange")

        thread = threading.Thread(target=self._run_batch_multi, args=(selected,))
        thread.daemon = True
        thread.start()

    def _run_batch_multi(self, selected_methods):
        try:
            self.log("=" * 80)
            self.log(t("analysis.start_batch", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log(t("analysis.methods_label", methods=", ".join(label for label, _ in selected_methods)))
            self.log(f"{t('analysis.species_label', species='').split(':')[0]}: {len(SPECIES_DB)}")
            self.log(t("analysis.parallel_workers", workers=CONFIG.max_parallel_workers))
            self.log(t("analysis.caching_status", status=t("placeholders.yes") if CONFIG.use_caching else t("placeholders.no")))
            self.log("=" * 80)

            species_list = [(name, info) for name, info in SPECIES_DB.items()]
            all_results = []
            for label, method_id in selected_methods:
                if self._stop_event.is_set():
                    self.log(t("log_messages.stopped"))
                    break
                self.log(f"\n{'#' * 60}\n{label}\n{'#' * 60}")
                result = run_batch_analysis(
                    species_list, method_id, label, self.log,
                    stop_event=self._stop_event)
                all_results.append(result)

            self.root.after(0, lambda: self._batch_complete_multi(all_results))
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def generate_consolidated_report(self):
        self._set_buttons(tk.DISABLED)
        self.progress.start(10)
        self.status_label.config(text=t("app.status_processing"), foreground="orange")

        thread = threading.Thread(target=self._run_consolidate)
        thread.daemon = True
        thread.start()

    def _run_consolidate(self):
        try:
            self.log("=" * 80)
            self.log(t("log_messages.generating_report", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            self.log("=" * 80)

            consolidated, md_path, json_path = consolidate_all_results(self.log)

            self.root.after(0, lambda: self._consolidate_complete(md_path, json_path))
        except Exception as e:
            self.log(t('log_messages.error_occurred', error=e))
            self.root.after(0, self._analysis_complete)

    def _consolidate_complete(self, md_path, json_path):
        self.progress.stop()
        self._set_buttons(tk.NORMAL)
        self.status_label.config(text=t("app.status_completed"), foreground="green")
        self.log("\n" + "=" * 80)
        self.log(t("report.completed", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.log("=" * 80)
        self.log(t("report.markdown_saved", path=md_path))
        self.log(t("log_messages.json_report_short", path=json_path))

    def _analysis_complete(self):
        self.progress.stop()
        self._set_buttons(tk.NORMAL)
        if self._stop_event.is_set():
            self.status_label.config(text=t("app.status_stopped"), foreground="gray")
        else:
            self.status_label.config(text=t("app.status_completed"), foreground="green")

    def _batch_complete_multi(self, all_results):
        self.progress.stop()
        self._set_buttons(tk.NORMAL)
        total_ok  = sum(r.get("completed", 0) for r in all_results)
        total_all = sum(r.get("total", 0)     for r in all_results)
        self.status_label.config(
            text=f"{t('app.status_completed')}: {total_ok}/{total_all}",
            foreground="green")
        self.log("\n" + "=" * 80)
        self.log(t("log_messages.batch_completed", timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.log("=" * 80)
        for r in all_results:
            self.log(f"  {r.get('method','?')}: {r.get('completed',0)}/{r.get('total',0)} "
                     f"(Cache: {r.get('cached',0)}, Errors: {r.get('failed',0)})")
        self.log(t("log_messages.results_dir", path=CONFIG.results_dir))

# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = DNARhythmAnalyzer(root)
    root.mainloop()
