#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LYRA-Unified  –  Integrierte Plattform für ICIJ Network & Narrative Forensics
═══════════════════════════════════════════════════════════════════════════════

Führt lyra_network_builder (Port 18800) und lyra_narrative_forensic (Port 18801)
in einer einzigen Web-Anwendung auf Port 18800 zusammen.

Features:
  - Einheitlicher Flask-Server, zwei Tab-Ansichten (ICIJ / Forensics)
  - Vollständige iframe-Isolation: kein JS/CSS-Konflikt zwischen den UIs
  - PausableWrapper: Agenten werden beim Tab-Wechsel intelligent pausiert/fortgesetzt
  - Zustandserhaltung: Queue und Investigations bleiben beim Wechsel erhalten
  - Cross-Tab-Linking: Akteur aus Forensics → ICIJ-Suche und umgekehrt
  - Neo4j, Ollama, SearXNG werden nur einmal initialisiert

Architektur:
  - /            → Unified Shell (Tab-Leiste + iframes)
  - /icij/       → ICIJ Network UI (eingebetteter lyra_network_builder WebServer)
  - /forensics/  → Narrative Forensics UI (eingebetteter NarrativeServer)
  - /api/mode    → Context-Switch-Endpunkt
  - /api/icij/*  → Proxy zu den ICIJ-API-Endpunkten
  - /api/forensics/* → Proxy zu den Forensics-API-Endpunkten

Starten:
  python lyra_unified.py --auto     # vollautomatisch (kein Prompt)
  python lyra_unified.py            # interaktiv

Version: 1.0.0
"""

import os
import sys
import time
import json
import threading
import logging
import argparse
import webbrowser
from pathlib import Path
from typing import Optional

# ── Logging-Setup (vor allem anderen) ────────────────────────────────────────
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Force UTF-8 stdout/stderr on Windows (CP1252 cannot encode emoji)
import sys as _sys
if hasattr(_sys.stdout, 'reconfigure'):
    try: _sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
if hasattr(_sys.stderr, 'reconfigure'):
    try: _sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

_LOG_LOCK = threading.Lock()

def _ts() -> str:
    return time.strftime("%H:%M:%S")

def unified_log(msg: str, level: str = "INFO"):
    icons = {"ERROR": "❌", "SUCCESS": "✅", "WARNING": "⚠️", "INFO": "📌"}
    icon = icons.get(level, "📌")
    with _LOG_LOCK:
        try:
            print(f"[{_ts()}] {icon} [LYRA-UNIFIED] {msg}")
        except UnicodeEncodeError:
            # Fallback: replace unencodable chars (CP1252 terminal)
            safe = f"[{_ts()}] {icon} [LYRA-UNIFIED] {msg}"
            print(safe.encode('cp1252', errors='replace').decode('cp1252'))

# ── Imports aus den Original-Modulen ─────────────────────────────────────────

def _import_modules():
    """
    Importiert die Originalmodule. Gibt (builder_ok, forensic_ok) zurück.
    Beide Module sind reine Klassendefinitionen – kein Code läuft beim Import.
    """
    builder_ok  = False
    forensic_ok = False

    try:
        import lyra_network_builder as _nb
        globals()['nb'] = _nb
        builder_ok = True
        unified_log("lyra_network_builder importiert ✓", "SUCCESS")
    except ImportError as e:
        unified_log(f"lyra_network_builder konnte nicht importiert werden: {e}", "WARNING")
        unified_log("ICIJ-Tab wird deaktiviert.", "WARNING")
    except Exception as e:
        unified_log(f"Fehler beim Import von lyra_network_builder: {e}", "ERROR")

    try:
        import lyra_narrative_forensic as _nf
        globals()['nf'] = _nf
        forensic_ok = True
        unified_log("lyra_narrative_forensic importiert ✓", "SUCCESS")
    except ImportError as e:
        unified_log(f"lyra_narrative_forensic konnte nicht importiert werden: {e}", "WARNING")
        unified_log("Forensics-Tab wird deaktiviert.", "WARNING")
    except Exception as e:
        unified_log(f"Fehler beim Import von lyra_narrative_forensic: {e}", "ERROR")

    return builder_ok, forensic_ok

# ══════════════════════════════════════════════════════════════════════════════
# PausableWrapper
# ══════════════════════════════════════════════════════════════════════════════

class PausableWrapper:
    """
    Dünner Wrapper um die bestehenden Agenten (ResearchAgent / NarrativeAgent).

    Strategie:
      pause()  → signalisiert _stop (sanftes Stop nach aktueller Iteration),
                 speichert Zustand via agent.stop() (enthält save_queue / _save_state)
      resume() → startet neuen Thread via agent.start() (lädt Zustand automatisch)

    Beide Agenten persistieren ihren vollständigen Zustand beim stop() –
    save_queue() (ResearchAgent) bzw. _save_state() (NarrativeAgent) –
    und laden ihn beim nächsten start() wieder. Kein Fortschrittsverlust.
    """

    def __init__(self, agent, name: str, log_fn=None):
        self._agent  = agent
        self._name   = name
        self._log    = log_fn or unified_log
        self._paused = False
        self._lock   = threading.Lock()

    # ── Öffentliche API ───────────────────────────────────────────────────────

    def pause(self):
        """
        Pausiert den Agenten nach Abschluss der aktuellen Iteration.
        Zustand (Queue/Investigations) wird automatisch gespeichert.
        """
        with self._lock:
            if self._paused:
                return
            self._log(f"{self._name}: pausiere…", "INFO")
            try:
                self._agent.stop()      # stop() enthält save_queue / _save_state
                self._paused = True
                self._log(f"{self._name}: pausiert ✓ (Zustand gespeichert)", "SUCCESS")
            except Exception as e:
                self._log(f"{self._name}: Fehler beim Pausieren: {e}", "WARNING")

    def resume(self):
        """
        Setzt den Agenten fort. Lädt gespeicherten Zustand automatisch.
        Wenn der Agent bereits läuft, passiert nichts.
        """
        with self._lock:
            if not self._paused and getattr(self._agent, 'running', False):
                return
            self._log(f"{self._name}: fortsetzen…", "INFO")
            try:
                self._agent.start()     # start() enthält load_queue / _load_state
                self._paused = False
                self._log(f"{self._name}: läuft wieder ✓", "SUCCESS")
            except Exception as e:
                self._log(f"{self._name}: Fehler beim Fortsetzen: {e}", "WARNING")

    def start_initial(self):
        """Erstmaliger Start beim App-Start."""
        with self._lock:
            try:
                self._agent.start()
                self._paused = False
                self._log(f"{self._name}: initial gestartet ✓", "SUCCESS")
            except Exception as e:
                self._log(f"{self._name}: Fehler beim Initialstart: {e}", "WARNING")

    def is_paused(self) -> bool:
        return self._paused

    def is_running(self) -> bool:
        return getattr(self._agent, 'running', False)

    @property
    def agent(self):
        return self._agent


# ══════════════════════════════════════════════════════════════════════════════
# Unified Flask App
# ══════════════════════════════════════════════════════════════════════════════

UNIFIED_PORT    = 18800
ICIJ_SUB_PORT   = 18802   # interner Sub-Server für ICIJ (nur lokal)
NF_SUB_PORT     = 18803   # interner Sub-Server für Forensics (nur lokal)

# Globaler Zustand
_current_mode   = "icij"   # "icij" | "forensics"
_mode_lock      = threading.Lock()

# Agenten-Wrapper (werden in build_unified_app() gesetzt)
_research_wrapper:  Optional[PausableWrapper] = None
_narrative_wrapper: Optional[PausableWrapper] = None

# Sub-Server-Apps (werden in _start_sub_servers() gesetzt)
_icij_app       = None
_forensics_app  = None


def _build_icij_sub_app(nb_module, neo4j_mgr, research_agent):
    """
    Baut die ICIJ-Flask-App aus lyra_network_builder.
    Gibt die fertige Flask-App zurück (nicht starten).
    """
    # WebServer-Instanz erzeugen, App bauen ohne zu starten
    web_server = nb_module.WebServer(neo4j_mgr, log_fn=unified_log)
    app = web_server._create_app()

    # Referenzen für API-Endpunkte setzen (wie in LYRANetworkBuilder.initialize)
    neo4j_mgr._research_agent = research_agent
    neo4j_mgr._enhancer_ref   = getattr(research_agent, 'enhancer', None)

    return app


def _build_forensics_sub_app(nf_module, narrative_db, narrative_agent):
    """
    Baut die Forensics-Flask-App aus lyra_narrative_forensic.
    Gibt die fertige Flask-App zurück.
    """
    server = nf_module.NarrativeServer(narrative_db, narrative_agent, log_fn=unified_log)
    app    = server.build_app()
    return app


def _run_sub_server(app, port: int, name: str):
    """Startet eine Flask-App als Sub-Server im Hintergrundthread."""
    def _run():
        try:
            try:
                from waitress import serve
                serve(app, host='127.0.0.1', port=port, threads=8)
            except ImportError:
                from werkzeug.serving import make_server
                srv = make_server('127.0.0.1', port, app, threaded=True)
                srv.serve_forever()
        except Exception as e:
            unified_log(f"{name} Sub-Server Fehler: {e}", "ERROR")

    t = threading.Thread(target=_run, daemon=True, name=f"SubServer-{name}")
    t.start()
    unified_log(f"{name} Sub-Server gestartet auf Port {port}", "INFO")
    return t


# ── Unified Shell HTML ────────────────────────────────────────────────────────

def _make_unified_template(icij_available: bool, forensics_available: bool) -> str:
    """Generiert das Haupt-HTML-Template der Unified Shell."""
    icij_disabled = "" if icij_available else 'disabled title="ICIJ Modul nicht verfügbar"'
    nf_disabled   = "" if forensics_available else 'disabled title="Forensics Modul nicht verfügbar"'

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LYRA Unified – ICIJ Network & Narrative Forensics</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: #0a0a14;
    color: #ccc;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}

  /* ── Tab-Leiste ── */
  #tabBar {{
    display: flex;
    align-items: stretch;
    background: #0d0d1a;
    border-bottom: 1px solid #1a2a4a;
    flex-shrink: 0;
    height: 42px;
    padding: 0 8px;
    gap: 4px;
  }}

  #tabBar .brand {{
    display: flex;
    align-items: center;
    font-size: 0.8em;
    color: #445;
    padding: 0 12px 0 4px;
    letter-spacing: 0.05em;
    border-right: 1px solid #1a2a4a;
    margin-right: 4px;
    white-space: nowrap;
  }}

  .tab-btn {{
    padding: 0 18px;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #556;
    cursor: pointer;
    font-size: 0.88em;
    font-family: inherit;
    letter-spacing: 0.03em;
    transition: color 0.15s, border-color 0.15s;
    white-space: nowrap;
  }}
  .tab-btn:hover:not(:disabled) {{ color: #88aacc; }}
  .tab-btn.active {{
    color: #00d4ff;
    border-bottom-color: #00d4ff;
  }}
  .tab-btn:disabled {{ color: #2a2a3a; cursor: not-allowed; }}

  /* Agent-Status-Anzeige */
  #agentStatus {{
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 0.75em;
    padding: 0 8px;
  }}
  .agent-pill {{
    padding: 2px 10px;
    border-radius: 10px;
    background: #111;
    border: 1px solid #223;
    transition: all 0.3s;
  }}
  .agent-pill.running  {{ border-color: #0a6; color: #0d9; }}
  .agent-pill.paused   {{ border-color: #444; color: #556; }}

  /* Mode-Wechsel-Overlay */
  #switchOverlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.5);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    font-size: 1em;
    color: #00d4ff;
    letter-spacing: 0.1em;
  }}
  #switchOverlay.visible {{ display: flex; }}

  /* ── Content-Bereich ── */
  #contentArea {{
    flex: 1;
    position: relative;
    overflow: hidden;
  }}

  .tab-frame {{
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    border: none;
    display: none;
    background: #0a0a14;
  }}
  .tab-frame.active {{ display: block; }}

  /* ── Fallback-Panel (wenn Modul fehlt) ── */
  .unavailable-panel {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 12px;
    color: #445;
  }}
  .unavailable-panel h2 {{ color: #556; font-size: 1.1em; }}
</style>
</head>
<body>

<!-- Tab-Leiste -->
<div id="tabBar">
  <div class="brand">🔎 LYRA UNIFIED</div>
  <button class="tab-btn active" id="tabIcij"      data-mode="icij"      {icij_disabled}>
    🗺️ ICIJ Network
  </button>
  <button class="tab-btn"        id="tabForensics" data-mode="forensics" {nf_disabled}>
    🕵️ Narrative Forensics
  </button>

  <div id="agentStatus">
    <span class="agent-pill" id="pillResearch" title="ResearchAgent">
      🔬 Research: <span id="researchState">–</span>
    </span>
    <span class="agent-pill" id="pillNarrative" title="NarrativeAgent">
      🕵️ Narrative: <span id="narrativeState">–</span>
    </span>
  </div>
</div>

<!-- Wechsel-Overlay -->
<div id="switchOverlay">
  <span id="switchMsg">⏳ Wechsle Modus…</span>
</div>

<!-- iframes -->
<div id="contentArea">
  {'<iframe id="frameIcij"      class="tab-frame active" src="/icij/"     sandbox="allow-scripts allow-same-origin allow-forms allow-modals"></iframe>' if icij_available else '<div id="frameIcij" class="tab-frame active unavailable-panel"><h2>⚠️ ICIJ-Modul nicht verfügbar</h2><p>lyra_network_builder.py konnte nicht geladen werden.</p></div>'}
  {'<iframe id="frameForensics" class="tab-frame"        src="/forensics/" sandbox="allow-scripts allow-same-origin allow-forms allow-modals"></iframe>' if forensics_available else '<div id="frameForensics" class="tab-frame unavailable-panel"><h2>⚠️ Forensics-Modul nicht verfügbar</h2><p>lyra_narrative_forensic.py konnte nicht geladen werden.</p></div>'}
</div>

<script>
(function() {{
  'use strict';

  // ── Tab-Persistenz via localStorage ────────────────────────────────────
  var _STORAGE_KEY = 'lyra_unified_mode';
  var _savedMode   = 'icij';
  try {{ _savedMode = localStorage.getItem(_STORAGE_KEY) || 'icij'; }} catch(e) {{}}

  var currentMode = 'icij';
  var switching   = false;

  // ── Status-Polling ──────────────────────────────────────────────────────
  function pollStatus() {{
    fetch('/api/status')
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        setAgentPill('research',  d.research_running,  d.research_paused);
        setAgentPill('narrative', d.narrative_running, d.narrative_paused);
      }})
      .catch(function() {{}});
  }}

  function setAgentPill(name, running, paused) {{
    var state = document.getElementById(name + 'State');
    var pill  = document.getElementById('pill' + name.charAt(0).toUpperCase() + name.slice(1));
    if (!state || !pill) return;
    if (running) {{
      state.textContent = 'läuft';
      pill.className    = 'agent-pill running';
    }} else if (paused) {{
      state.textContent = 'pausiert';
      pill.className    = 'agent-pill paused';
    }} else {{
      state.textContent = '–';
      pill.className    = 'agent-pill';
    }}
  }}

  setInterval(pollStatus, 3000);
  pollStatus();

  // ── Tab-Wechsel ─────────────────────────────────────────────────────────
  async function setMode(mode) {{
    if (switching || mode === currentMode) return;
    switching = true;

    // Overlay anzeigen
    var overlay = document.getElementById('switchOverlay');
    var msg     = document.getElementById('switchMsg');
    msg.textContent = mode === 'forensics'
      ? '⏳ Pausiere ResearchAgent… starte NarrativeAgent…'
      : '⏳ Pausiere NarrativeAgent… starte ResearchAgent…';
    overlay.classList.add('visible');

    try {{
      var resp = await fetch('/api/mode', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ mode: mode }})
      }});
      var data = await resp.json();
      currentMode = data.mode;
      try {{ localStorage.setItem(_STORAGE_KEY, currentMode); }} catch(e) {{}}

      // UI umschalten
      document.querySelectorAll('.tab-frame').forEach(function(f) {{
        f.classList.remove('active');
      }});
      document.querySelectorAll('.tab-btn').forEach(function(b) {{
        b.classList.toggle('active', b.dataset.mode === mode);
      }});
      var targetFrame = mode === 'icij' ? 'frameIcij' : 'frameForensics';
      document.getElementById(targetFrame).classList.add('active');

      // Cross-Tab-Linking: query aus URL-Param lesen und ins iframe weiterleiten
      var params = new URLSearchParams(window.location.search);
      var crossQuery = params.get('cross_query');
      if (crossQuery) {{
        // Kurz warten bis iframe bereit ist, dann Nachricht senden
        setTimeout(function() {{
          var frame = document.getElementById(targetFrame);
          if (frame && frame.contentWindow) {{
            frame.contentWindow.postMessage({{
              type: 'lyra_cross_link',
              query: crossQuery,
              source_mode: mode === 'icij' ? 'forensics' : 'icij'
            }}, '*');
          }}
          // URL-Param entfernen
          window.history.replaceState(null, '', window.location.pathname);
        }}, 800);
      }}

    }} catch(e) {{
      console.error('Mode switch failed:', e);
    }} finally {{
      overlay.classList.remove('visible');
      switching = false;
      pollStatus();
    }}
  }}

  // Tab-Buttons
  document.querySelectorAll('.tab-btn:not(:disabled)').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      setMode(btn.dataset.mode);
    }});
  }});

  // ── Auto-Restore beim Seitenload ────────────────────────────────────────
  // Gespeicherten Tab sofort ohne Overlay wiederherstellen.
  // Der Server wird via /api/mode informiert damit die Agenten korrekt stehen.
  (function restoreTab() {{
    if (_savedMode === 'icij') return;  // icij ist default, nichts zu tun
    var validModes = ['icij', 'forensics'];
    if (validModes.indexOf(_savedMode) === -1) return;

    // UI sofort umschalten (kein Overlay, kein Warten)
    document.querySelectorAll('.tab-frame').forEach(function(f) {{
      f.classList.remove('active');
    }});
    document.querySelectorAll('.tab-btn').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.mode === _savedMode);
    }});
    var targetId = _savedMode === 'icij' ? 'frameIcij' : 'frameForensics';
    var targetEl = document.getElementById(targetId);
    if (targetEl) targetEl.classList.add('active');
    currentMode = _savedMode;

    // Server asynchron informieren (Agenten korrekt pausieren/starten)
    fetch('/api/mode', {{
      method:  'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body:    JSON.stringify({{ mode: _savedMode }})
    }}).catch(function() {{}});
  }})();

  // Cross-Tab-Link-Handler: Nachrichten von iframes empfangen
  window.addEventListener('message', function(evt) {{
    var d = evt.data;
    if (!d || d.type !== 'lyra_cross_link_request') return;
    var targetMode = d.target_mode;
    var query      = d.query;

    // Ziel-URL mit cross_query-Param aufbauen
    var url = window.location.pathname + '?cross_query=' + encodeURIComponent(query);
    window.history.replaceState(null, '', url);

    // Zum Ziel-Tab wechseln
    setMode(targetMode).then ? null : setMode(targetMode);
    // setMode ist async, nach dem Wechsel wird cross_query aus URL gelesen
  }});

}})();
</script>
</body>
</html>"""


def build_unified_app(
    icij_available:      bool,
    forensics_available: bool,
    icij_app=None,
    forensics_app=None,
    research_wrapper:  Optional[PausableWrapper] = None,
    narrative_wrapper: Optional[PausableWrapper] = None,
):
    """
    Baut die zentrale Flask-App der Unified Shell.

    Routes:
      /              → Unified Shell HTML
      /icij/<path>   → Proxy/Weiterleitung zur ICIJ-App
      /forensics/<path> → Proxy/Weiterleitung zur Forensics-App
      /api/mode      → Context-Switch
      /api/status    → Agent-Status für Tab-Leiste
    """
    from flask import Flask, request, jsonify, Response
    import requests as req_lib

    app = Flask(__name__)
    unified_tmpl = _make_unified_template(icij_available, forensics_available)

    global _current_mode

    # ── Hauptseite ────────────────────────────────────────────────────────────
    @app.route('/')
    def index():
        return unified_tmpl, 200, {'Content-Type': 'text/html; charset=utf-8'}

    # ── Mode-API ──────────────────────────────────────────────────────────────
    @app.route('/api/mode', methods=['GET', 'POST'])
    def handle_mode():
        global _current_mode
        if request.method == 'POST':
            body     = request.get_json(silent=True) or {}
            new_mode = body.get('mode', _current_mode)

            if new_mode not in ('icij', 'forensics'):
                return jsonify({'error': f'Unbekannter Modus: {new_mode}'}), 400

            if new_mode != _current_mode:
                with _mode_lock:
                    if new_mode == 'forensics':
                        # ICIJ pausieren, Forensics starten
                        if research_wrapper:
                            research_wrapper.pause()
                        if narrative_wrapper:
                            narrative_wrapper.resume()
                    else:
                        # Forensics pausieren, ICIJ starten
                        if narrative_wrapper:
                            narrative_wrapper.pause()
                        if research_wrapper:
                            research_wrapper.resume()
                    _current_mode = new_mode
                    unified_log(f"Modus gewechselt → {_current_mode}", "INFO")

        return jsonify({
            'mode':              _current_mode,
            'research_running':  research_wrapper.is_running()  if research_wrapper  else False,
            'narrative_running': narrative_wrapper.is_running() if narrative_wrapper else False,
        })

    # ── Status-API (für Tab-Leiste Polling) ───────────────────────────────────
    @app.route('/api/status')
    def api_status():
        return jsonify({
            'mode':              _current_mode,
            'research_running':  research_wrapper.is_running()  if research_wrapper  else False,
            'research_paused':   research_wrapper.is_paused()   if research_wrapper  else False,
            'narrative_running': narrative_wrapper.is_running() if narrative_wrapper else False,
            'narrative_paused':  narrative_wrapper.is_paused()  if narrative_wrapper else False,
        })

    # ── ICIJ-Proxy ────────────────────────────────────────────────────────────
    # Alle /icij/* Anfragen werden an den internen ICIJ Sub-Server weitergeleitet.
    @app.route('/icij/', defaults={'path': ''})
    @app.route('/icij/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    def icij_proxy(path):
        if not icij_available:
            return '<h1>ICIJ-Modul nicht verfügbar</h1>', 503

        target = f'http://127.0.0.1:{ICIJ_SUB_PORT}/' + path
        qs = request.query_string.decode()
        if qs:
            target += '?' + qs

        try:
            resp = req_lib.request(
                method  = request.method,
                url     = target,
                headers = {k: v for k, v in request.headers if k.lower() not in
                           ('host', 'content-length', 'transfer-encoding')},
                data    = request.get_data(),
                timeout = 30,
                allow_redirects = False,
                stream  = True,
            )
            excluded = {'transfer-encoding', 'content-encoding', 'connection'}
            headers  = [(k, v) for k, v in resp.headers.items()
                        if k.lower() not in excluded]

            # HTML-Antworten: Links auf /icij/-Prefix umschreiben + Cross-Link-JS einbauen
            ct = resp.headers.get('Content-Type', '')
            if 'text/html' in ct:
                html = resp.content.decode('utf-8', errors='replace')
                html = _rewrite_icij_html(html)
                return Response(html, status=resp.status_code,
                                headers=dict(headers) | {'Content-Type': ct})

            return Response(resp.iter_content(chunk_size=8192),
                            status=resp.status_code,
                            headers=headers,
                            content_type=resp.headers.get('Content-Type', ''))

        except req_lib.exceptions.ConnectionError:
            return jsonify({'error': 'ICIJ Sub-Server nicht erreichbar'}), 503
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ── Forensics-Proxy ───────────────────────────────────────────────────────
    @app.route('/forensics/', defaults={'path': ''})
    @app.route('/forensics/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
    def forensics_proxy(path):
        if not forensics_available:
            return '<h1>Forensics-Modul nicht verfügbar</h1>', 503

        target = f'http://127.0.0.1:{NF_SUB_PORT}/' + path
        qs = request.query_string.decode()
        if qs:
            target += '?' + qs

        try:
            resp = req_lib.request(
                method  = request.method,
                url     = target,
                headers = {k: v for k, v in request.headers if k.lower() not in
                           ('host', 'content-length', 'transfer-encoding')},
                data    = request.get_data(),
                timeout = 30,
                allow_redirects = False,
                stream  = True,
            )
            excluded = {'transfer-encoding', 'content-encoding', 'connection'}
            headers  = [(k, v) for k, v in resp.headers.items()
                        if k.lower() not in excluded]

            ct = resp.headers.get('Content-Type', '')
            if 'text/html' in ct:
                html = resp.content.decode('utf-8', errors='replace')
                html = _rewrite_forensics_html(html)
                return Response(html, status=resp.status_code,
                                headers=dict(headers) | {'Content-Type': ct})

            return Response(resp.iter_content(chunk_size=8192),
                            status=resp.status_code,
                            headers=headers,
                            content_type=resp.headers.get('Content-Type', ''))

        except req_lib.exceptions.ConnectionError:
            return jsonify({'error': 'Forensics Sub-Server nicht erreichbar'}), 503
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return app


# ── HTML-Rewriter & Fetch-Interceptor ────────────────────────────────────────
#
# Strategie: Anstatt fetch()-Aufrufe im HTML per String-Replace zu patchen
# (was dynamisch konstruierte URLs wie `var url='/api/...'; fetch(url)` verfehlt),
# injizieren wir einen fetch()-Interceptor als ERSTES im <head>.
# Dieser Interceptor fängt ALLE fetch() und XMLHttpRequest-Aufrufe ab und
# leitet /api/* und /static/* automatisch auf den richtigen Sub-Pfad um.
# Zusätzlich werden statische src/href-Attribute per String-Replace korrigiert.

def _make_fetch_interceptor(prefix: str) -> str:
    """
    Erzeugt einen JS-fetch-Interceptor der alle /api/* und /static/* Pfade
    auf den angegebenen Prefix umschreibt.

    prefix: '/icij' oder '/forensics'
    """
    return f"""<script>
/* LYRA Unified – fetch/XHR Interceptor ({prefix}) */
(function() {{
  var _PREFIX = '{prefix}';

  function _rewrite(url) {{
    if (typeof url !== 'string') return url;
    // Nur absolute Pfade umschreiben die mit /api/ oder /static/ beginnen
    // Nicht umschreiben wenn bereits mit prefix beginnt
    if (url.startsWith('/api/') || url === '/api') {{
      return _PREFIX + url;
    }}
    if (url.startsWith('/static/')) {{
      return _PREFIX + url;
    }}
    // Sonderfall: Pfade ohne führenden Slash aber mit api/ Präfix
    if (url.startsWith('api/')) {{
      return _PREFIX + '/' + url;
    }}
    return url;
  }}

  // ── fetch() patchen ──────────────────────────────────────────────────────
  var _origFetch = window.fetch.bind(window);
  window.fetch = function(resource, init) {{
    if (typeof resource === 'string') {{
      resource = _rewrite(resource);
    }} else if (resource instanceof Request) {{
      var newUrl = _rewrite(resource.url);
      if (newUrl !== resource.url) {{
        resource = new Request(newUrl, resource);
      }}
    }}
    return _origFetch(resource, init);
  }};

  // ── XMLHttpRequest patchen (für ältere Code-Pfade) ──────────────────────
  var _origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url, async, user, pass) {{
    url = _rewrite(url);
    return _origOpen.call(this, method, url,
      async !== undefined ? async : true,
      user, pass);
  }};
}})();
</script>"""


_CROSS_LINK_JS_ICIJ = """
<script>
/* LYRA Unified – Cross-Tab-Link für ICIJ-Frame */
(function() {
  window.addEventListener('message', function(evt) {
    var d = evt.data;
    if (!d || d.type !== 'lyra_cross_link' || d.source_mode !== 'forensics') return;
    var q   = d.query;
    var inp = document.getElementById('searchInput') ||
              document.querySelector('input[placeholder*="Search"], input[placeholder*="Suche"], input[type="search"]');
    if (inp) {
      inp.value = q;
      inp.dispatchEvent(new Event('input', {bubbles: true}));
      inp.dispatchEvent(new KeyboardEvent('keypress', {key:'Enter', bubbles:true}));
    }
    if (window.performSearch) window.performSearch(q);
    else if (window.searchGraph) window.searchGraph(q);
  });

  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-cross-link]');
    if (!btn) return;
    window.parent.postMessage({
      type: 'lyra_cross_link_request', target_mode: 'forensics',
      query: btn.getAttribute('data-cross-link')
    }, '*');
  });
})();
</script>
"""

_CROSS_LINK_JS_FORENSICS = """
<script>
/* LYRA Unified – Cross-Tab-Link für Forensics-Frame */
(function() {
  window.addEventListener('message', function(evt) {
    var d = evt.data;
    if (!d || d.type !== 'lyra_cross_link' || d.source_mode !== 'icij') return;
    var q   = d.query;
    var inp = document.getElementById('queryInput') ||
              document.querySelector('input[placeholder*="narrative"], input[placeholder*="investigation"], input[placeholder*="Enter"]');
    if (inp) inp.value = q;
    if (window.addInvestigation) window.addInvestigation();
  });

  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-cross-icij]');
    if (!btn) return;
    window.parent.postMessage({
      type: 'lyra_cross_link_request', target_mode: 'icij',
      query: btn.getAttribute('data-cross-icij')
    }, '*');
  });

  // Auto-inject "🔗 ICIJ"-Buttons neben Akteur-Namen in Detail-Panels
  new MutationObserver(function() {
    document.querySelectorAll('.actor-detail, .node-detail, [class*="detail"], [class*="panel"]').forEach(function(panel) {
      if (panel.querySelector('[data-cross-icij]')) return;
      var nameEl = panel.querySelector('.actor-name, .name, h3, h4, strong');
      if (!nameEl) return;
      var name = (nameEl.textContent || '').trim().replace(/^[^a-zA-Z0-9äöüÄÖÜß]+/, '');
      if (!name || name.length < 2) return;
      var btn = document.createElement('button');
      btn.setAttribute('data-cross-icij', name);
      btn.title = 'Im ICIJ-Netzwerk suchen';
      btn.style.cssText = 'margin-left:6px;padding:1px 7px;font-size:0.72em;'
        + 'background:#1a2a4a;border:1px solid #4488ff;border-radius:3px;'
        + 'color:#4af;cursor:pointer;vertical-align:middle;';
      btn.textContent = '🔗 ICIJ';
      nameEl.appendChild(btn);
    });
  }).observe(document.body, {childList: true, subtree: true});
})();
</script>
"""


def _inject_interceptor(html: str, prefix: str) -> str:
    """
    Fügt den fetch-Interceptor als erstes Element im <head> ein.
    Korrigiert außerdem statische src/href-Attribute.
    Fügt Cross-Link-JS vor </body> ein.
    """
    interceptor = _make_fetch_interceptor(prefix)
    cross_js    = _CROSS_LINK_JS_ICIJ if prefix == '/icij' else _CROSS_LINK_JS_FORENSICS

    # 1. fetch-Interceptor: muss VOR jedem anderen Script stehen
    if '<head>' in html:
        html = html.replace('<head>', '<head>\n' + interceptor, 1)
    elif '<HEAD>' in html:
        html = html.replace('<HEAD>', '<HEAD>\n' + interceptor, 1)
    else:
        html = interceptor + '\n' + html

    # 2. Statische src/href-Attribute für /static/ korrigieren
    #    (fetch-Interceptor greift nur für JS-fetch/XHR, nicht für HTML-Attribute)
    html = html.replace("src='/static/",  f"src='{prefix}/static/")
    html = html.replace('src="/static/',  f'src="{prefix}/static/')
    html = html.replace("href='/static/", f"href='{prefix}/static/")
    html = html.replace('href="/static/', f'href="{prefix}/static/')

    # 3. Cross-Link-JS vor </body>
    if '</body>' in html:
        html = html.replace('</body>', cross_js + '\n</body>', 1)
    elif '</BODY>' in html:
        html = html.replace('</BODY>', cross_js + '\n</BODY>', 1)
    else:
        html += cross_js

    return html


def _rewrite_icij_html(html: str) -> str:
    """Schreibt ICIJ-HTML um: fetch-Interceptor + Cross-Link-JS."""
    return _inject_interceptor(html, '/icij')


def _rewrite_forensics_html(html: str) -> str:
    """Schreibt Forensics-HTML um: fetch-Interceptor + Cross-Link-JS."""
    return _inject_interceptor(html, '/forensics')


# ══════════════════════════════════════════════════════════════════════════════
# Startup-Orchestrierung
# ══════════════════════════════════════════════════════════════════════════════

def initialize_and_run(auto_mode: bool = False):
    """
    Hauptfunktion: Initialisiert alle Komponenten, startet Sub-Server und
    den Unified Flask-Server.

    auto_mode = True  → kein interaktiver Prompt (für --auto Flag)
    """
    unified_log("═" * 60)
    unified_log("LYRA Unified  v1.0.0  –  ICIJ Network & Narrative Forensics")
    unified_log("═" * 60)

    # ── Module importieren ────────────────────────────────────────────────────
    builder_ok, forensic_ok = _import_modules()

    if not builder_ok and not forensic_ok:
        unified_log("Kein Modul verfügbar – Abbruch.", "ERROR")
        sys.exit(1)

    # ── ICIJ-Komponenten initialisieren ───────────────────────────────────────
    research_wrapper  = None
    narrative_wrapper = None
    icij_app_instance = None
    nf_app_instance   = None

    if builder_ok:
        unified_log("Initialisiere ICIJ-Komponenten…")
        try:
            nb = globals()['nb']

            neo4j_mgr = nb.Neo4jManager(log_fn=unified_log)
            neo4j_ok  = neo4j_mgr.install()

            if not neo4j_ok:
                if (hasattr(neo4j_mgr, '_check_neo4j_online') and
                        neo4j_mgr._check_neo4j_online()):
                    unified_log("Neo4j läuft und ist erreichbar ✓", "SUCCESS")
                    neo4j_ok = True
                else:
                    unified_log("Neo4j nicht erreichbar – ICIJ-Tab eingeschränkt", "WARNING")

            if neo4j_ok:
                try:
                    neo4j_mgr.init_schema()
                    unified_log("Neo4j Schema ✓", "SUCCESS")
                except Exception as e:
                    unified_log(f"Schema-Init (nicht kritisch): {e}", "WARNING")

            ai_enhancer    = nb.AIGraphEnhancer(neo4j_mgr, log_fn=unified_log)
            research_agent = nb.ResearchAgent(neo4j_mgr, ai_enhancer, log_fn=unified_log)

            neo4j_mgr._enhancer_ref   = ai_enhancer
            neo4j_mgr._research_agent = research_agent

            icij_app_instance = _build_icij_sub_app(nb, neo4j_mgr, research_agent)
            research_wrapper  = PausableWrapper(research_agent, "ResearchAgent", unified_log)

            unified_log("ICIJ-Komponenten bereit ✓", "SUCCESS")

        except Exception as e:
            unified_log(f"Fehler bei ICIJ-Init: {e}", "ERROR")
            import traceback; traceback.print_exc()
            builder_ok = False

    # ── Forensics-Komponenten initialisieren ──────────────────────────────────
    if forensic_ok:
        unified_log("Initialisiere Forensics-Komponenten…")
        try:
            nf = globals()['nf']

            narrative_db = nf.NarrativeNeo4j(log_fn=unified_log)
            db_ok        = narrative_db.connect()

            if db_ok:
                narrative_db.init_schema()
                unified_log("NarrativeNeo4j Schema ✓", "SUCCESS")
            else:
                unified_log("NarrativeNeo4j nicht erreichbar – In-Memory-Modus", "WARNING")

            narrative_agent  = nf.NarrativeAgent(db=narrative_db, log_fn=unified_log)
            nf_app_instance  = _build_forensics_sub_app(nf, narrative_db, narrative_agent)
            narrative_wrapper = PausableWrapper(narrative_agent, "NarrativeAgent", unified_log)

            unified_log("Forensics-Komponenten bereit ✓", "SUCCESS")

        except Exception as e:
            unified_log(f"Fehler bei Forensics-Init: {e}", "ERROR")
            import traceback; traceback.print_exc()
            forensic_ok = False

    # ── Globale Wrapper setzen ────────────────────────────────────────────────
    global _research_wrapper, _narrative_wrapper
    _research_wrapper  = research_wrapper
    _narrative_wrapper = narrative_wrapper

    # ── Sub-Server starten ────────────────────────────────────────────────────
    if builder_ok and icij_app_instance:
        _run_sub_server(icij_app_instance, ICIJ_SUB_PORT, "ICIJ")
        time.sleep(0.5)

    if forensic_ok and nf_app_instance:
        _run_sub_server(nf_app_instance, NF_SUB_PORT, "Forensics")
        time.sleep(0.5)

    # ── Agenten starten (nur aktiver Modus startet sofort) ────────────────────
    # Initial: ICIJ ist aktiv → ResearchAgent läuft, NarrativeAgent pausiert
    if research_wrapper:
        research_wrapper.start_initial()

    if narrative_wrapper:
        # NarrativeAgent im pausierten Zustand starten
        # (wird beim ersten Tab-Wechsel zu Forensics gestartet)
        unified_log("NarrativeAgent: wartet auf Tab-Wechsel zu Forensics", "INFO")

    # ── Unified App bauen ─────────────────────────────────────────────────────
    unified_app = build_unified_app(
        icij_available      = builder_ok,
        forensics_available = forensic_ok,
        icij_app            = icij_app_instance,
        forensics_app       = nf_app_instance,
        research_wrapper    = research_wrapper,
        narrative_wrapper   = narrative_wrapper,
    )

    # ── Browser öffnen ────────────────────────────────────────────────────────
    def _open_browser():
        time.sleep(2.0)
        webbrowser.open(f"http://127.0.0.1:{UNIFIED_PORT}")

    threading.Thread(target=_open_browser, daemon=True).start()

    # ── Port-Konflikt prüfen und auflösen ────────────────────────────────────
    import socket as _socket
    _test = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        _test.bind(('127.0.0.1', UNIFIED_PORT))
        _test.close()
    except OSError:
        unified_log(f"Port {UNIFIED_PORT} bereits belegt — versuche alten Prozess zu beenden...", "WARNING")
        try:
            import subprocess as _sp
            # Finde PID der den Port hält und beende ihn
            r = _sp.run(
                ['powershell', '-Command',
                 f'(Get-NetTCPConnection -LocalPort {UNIFIED_PORT} -ErrorAction SilentlyContinue).OwningProcess'],
                capture_output=True, text=True, timeout=5
            )
            pid_str = r.stdout.strip()
            if pid_str and pid_str.isdigit():
                _sp.run(['taskkill', '/PID', pid_str, '/F'], timeout=5, capture_output=True)
                unified_log(f"Prozess PID {pid_str} beendet — warte 2s...", "INFO")
                time.sleep(2)
            else:
                unified_log(f"Port {UNIFIED_PORT} belegt aber PID nicht ermittelbar — Abbruch.", "ERROR")
                sys.exit(1)
        except Exception as _e:
            unified_log(f"Port-Konflikt konnte nicht aufgelöst werden: {_e}", "ERROR")
            sys.exit(1)

    # ── Unified Server starten (blocking) ─────────────────────────────────────
    unified_log(f"Unified Server startet auf http://127.0.0.1:{UNIFIED_PORT}")
    unified_log(f"  ICIJ Network:         /icij/")
    unified_log(f"  Narrative Forensics:  /forensics/")
    unified_log("Fenster minimieren, nicht schliessen.")

    logging.getLogger('werkzeug').setLevel(logging.ERROR)

    try:
        try:
            from waitress import serve
            serve(unified_app, host='127.0.0.1', port=UNIFIED_PORT,
                  threads=16, channel_timeout=600)
        except ImportError:
            from werkzeug.serving import make_server
            srv = make_server('127.0.0.1', UNIFIED_PORT, unified_app, threaded=True)
            srv.serve_forever()

    except KeyboardInterrupt:
        unified_log("Shutdown…")
        if research_wrapper:
            research_wrapper.pause()  # speichert Queue
        if narrative_wrapper:
            narrative_wrapper.pause()  # speichert State
        unified_log("Beendet. Auf Wiedersehen.")


# ══════════════════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global UNIFIED_PORT

    parser = argparse.ArgumentParser(
        description='LYRA Unified – ICIJ Network & Narrative Forensics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python lyra_unified.py --auto    # vollautomatisch, kein Prompt
  python lyra_unified.py           # interaktiver Modus
        """
    )
    parser.add_argument('--auto', action='store_true',
                        help='Vollautomatischer Start ohne interaktive Prompts')
    parser.add_argument('--port', type=int, default=UNIFIED_PORT,
                        help=f'Port für den Unified Server (default: {UNIFIED_PORT})')
    args = parser.parse_args()

    if args.port != UNIFIED_PORT:
        UNIFIED_PORT = args.port

    initialize_and_run(auto_mode=args.auto)


if __name__ == '__main__':
    main()
