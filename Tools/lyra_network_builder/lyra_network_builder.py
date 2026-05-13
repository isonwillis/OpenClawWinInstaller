#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LYRA-NET – Semantische Netzwerk-Datenbank globaler Eliten (2000–2026)
======================================================================

Ein autonomes, semantisches Netzwerk (Knowledge Graph) basierend auf öffentlich zugänglichen 
Leak-Daten (Panama Papers, Paradise Papers, Pandora Papers, Offshore Leaks, ICIJ-Datenbank).

Das System:
  - Beschafft, bereinigt und normalisiert Leak-Daten automatisch
  - Baut eine Neo4j-Graphdatenbank auf (Knoten: Personen, Firmen, Adressen, Vermittler)
  - Startet eine iterative, lokale KI-Recherche für fehlende Verbindungen
  - Stellt eine interaktive Weboberfläche (Force-Directed Graph) bereit
  - Nutzt Worker-Verbund (Junior/Senior) zur Parallelisierung

Technische Basis:
  - OpenClaw Gateway (Port 18789) für Kommunikation
  - Neo4j Community Edition (Port 7687, Browser: 7474)
  - Ollama mit glm-4.7-flash / qwen2.5:14b
  - SearXNG (Docker) für anonyme Websuche
  - Flask + vis-network für Visualisierung

Version: 2.0.0 (Research Agent Option C: ResearchAgent, /api/research/*, 🔬 Tab)
"""

import os
import sys
import json
import time
import shutil
import subprocess
import tempfile
import zipfile
import tarfile
import urllib.request
import urllib.parse
import threading
import hashlib
import re
import gc
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict

# Drittanbieter-Importe (werden bei Bedarf installiert)
try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from neo4j import GraphDatabase, exceptions as neo4j_exceptions
except ImportError:
    neo4j = None
    GraphDatabase = None

try:
    import networkx as nx
except ImportError:
    nx = None

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:
    Flask = None

try:
    import requests
except ImportError:
    requests = None

# Konstanten
NEO4J_PORT = 7687
NEO4J_BROWSER_PORT = 7474
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "lyra_network_2026"
NEO4J_DEFAULT_PASSWORD = "neo4j"

FLASK_PORT = 18800
LYRA_HEAD_PORT = 18790
OPENCLAW_GATEWAY_PORT = 18789

# ICIJ Offshore Leaks Datenquellen (aktuell 2025/2026)
DATASETS = {
    "panama_papers": {
        "url": "https://offshoreleaks.icij.org/dumps/panama_papers_nodes.csv",
        "edges_url": "https://offshoreleaks.icij.org/dumps/panama_papers_edges.csv",
        "description": "Panama Papers (Mossack Fonseca)"
    },
    "paradise_papers": {
        "url": "https://offshoreleaks.icij.org/dumps/paradise_papers_nodes.csv",
        "edges_url": "https://offshoreleaks.icij.org/dumps/paradise_papers_edges.csv",
        "description": "Paradise Papers (Appleby)"
    },
    "pandora_papers": {
        "url": "https://offshoreleaks.icij.org/dumps/pandora_papers_nodes.csv",
        "edges_url": "https://offshoreleaks.icij.org/dumps/pandora_papers_edges.csv",
        "description": "Pandora Papers"
    },
    "offshore_leaks": {
        "url": "https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip",
        "description": "ICIJ Offshore Leaks Database (komplett)",
        "files": {
            "entities": "nodes-entities.csv",
            "officers": "nodes-officers.csv",
            "intermediaries": "nodes-intermediaries.csv",
            "addresses": "nodes-addresses.csv",
            "others": "nodes-others.csv",
            "relationships": "relationships.csv"
        }
    }
}

# Fallback: Alternative Quelle über Zenodo
FALLBACK_DATASETS = {
    "offshore_leaks_zenodo": {
        "url": "https://zenodo.org/record/7953895/files/offshoreleaks_nodes.csv",
        "edges_url": "https://zenodo.org/record/7953895/files/offshoreleaks_edges.csv",
        "description": "ICIJ Offshore Leaks (Zenodo Mirror)"
    }
}

# Neo4j Schema Definition
SCHEMA_CYPHER = """
// Constraints - erzeugen implizit je einen Index auf .id
CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT intermediary_id IF NOT EXISTS FOR (i:Intermediary) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT address_id IF NOT EXISTS FOR (a:Address) REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT country_name IF NOT EXISTS FOR (c:Country) REQUIRE c.name IS UNIQUE;

// Expliziter id-Index fuer sonstige Knoten (Other)
CREATE INDEX other_id_idx IF NOT EXISTS FOR (o:Other) ON (o.id);

// B-Tree Namens-Indizes fuer exakte Suche
CREATE INDEX person_name_idx IF NOT EXISTS FOR (p:Person) ON (p.name);
CREATE INDEX entity_name_idx IF NOT EXISTS FOR (e:Entity) ON (e.name);
CREATE INDEX intermediary_name_idx IF NOT EXISTS FOR (i:Intermediary) ON (i.name);
CREATE INDEX country_idx IF NOT EXISTS FOR (c:Country) ON (c.name);
CREATE INDEX address_idx IF NOT EXISTS FOR (a:Address) ON (a.full_address);

// TEXT-Indizes fuer CONTAINS-Suche (Neo4j 5.x)
CREATE TEXT INDEX person_name_text IF NOT EXISTS FOR (n:Person) ON (n.name);
CREATE TEXT INDEX entity_name_text IF NOT EXISTS FOR (n:Entity) ON (n.name);
CREATE TEXT INDEX intermediary_name_text IF NOT EXISTS FOR (n:Intermediary) ON (n.name);

// SUGGESTED_CONNECTION: KI-vorgeschlagene Verbindungen (noch nicht validiert)
CREATE INDEX suggested_validated_idx IF NOT EXISTS
FOR ()-[r:SUGGESTED_CONNECTION]-() ON (r.validated);
CREATE INDEX suggested_rejected_idx IF NOT EXISTS
FOR ()-[r:SUGGESTED_CONNECTION]-() ON (r.rejected);
CREATE INDEX suggested_confidence_idx IF NOT EXISTS
FOR ()-[r:SUGGESTED_CONNECTION]-() ON (r.confidence);
"""

# HTML Template für die Weboberfläche
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="initial-tab" content="graph">
    <title>LYRA-NET – Semantisches Netzwerk globaler Eliten</title>

    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0a0a0a 0%, #1a1a2e 100%);
            color: #e0e0e0;
            overflow: hidden;
            height: 100vh;
        }
        .container {
            display: flex;
            height: 100vh;
            width: 100%;
        }
        .sidebar {
            width: 320px;
            min-width: 180px;
            max-width: 60vw;
            background: rgba(20, 20, 40, 0.95);
            backdrop-filter: blur(10px);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            z-index: 10;
            box-shadow: 2px 0 20px rgba(0,0,0,0.5);
        }
        .sidebar-inner {
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            overflow-y: auto;
            flex: 1;
            min-height: 0;
        }
        /* tab-panels container */
        .tab-panels {
            flex: 1;
            min-height: 0;
            position: relative;
            display: flex;
            flex-direction: column;
            padding: 0 14px;
        }
        .tab-panel {
            display: none;
            flex: 1;
            min-height: 0;
            overflow-y: auto;
            padding: 8px 0;
            flex-direction: column;
        }
        .tab-panel.active {
            display: flex;
        }
        #tabLegend, #tabLegend.active {
            padding: 0;
            overflow: hidden;
            flex-direction: row;
            margin: 0 -14px;  /* negate parent padding */
        }
        .graph-container {
            flex: 1;
            position: relative;
            overflow: hidden;
        }
        #mynetwork {
            width: 100%;
            height: 100%;
            background: #0a0a14;
        }
        h1 {
            font-size: 1.5em;
            margin-bottom: 10px;
            color: #00d4ff;
            border-bottom: 2px solid #00d4ff;
            padding-bottom: 8px;
        }
        h2 {
            font-size: 1.1em;
            margin: 15px 0 8px 0;
            color: #aaa;
            letter-spacing: 1px;
        }
        .stats {
            background: rgba(0,0,0,0.5);
            border-radius: 8px;
            padding: 10px;
            font-size: 0.85em;
        }
        .stats p {
            margin: 5px 0;
        }
        .stats .value {
            color: #00d4ff;
            font-weight: bold;
        }
        .search-box {
            display: flex;
            gap: 8px;
            margin: 10px 0;
        }
        .search-box input {
            flex: 1;
            padding: 8px 12px;
            background: #1a1a2e;
            border: 1px solid #334;
            border-radius: 6px;
            color: #e0e0e0;
            font-size: 0.9em;
        }
        .search-box input:focus {
            outline: none;
            border-color: #00d4ff;
        }
        .search-box button {
            padding: 8px 15px;
            background: #00d4ff;
            border: none;
            border-radius: 6px;
            color: #0a0a0a;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }
        .search-box button:hover {
            background: #00b4df;
            transform: scale(1.02);
        }
        .legend {
            display: flex;
            flex-wrap: wrap;
            gap: 12px;
            margin: 10px 0;
            padding: 10px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
        }
        .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 0.75em;
        }
        .legend-color {
            width: 14px;
            height: 14px;
            border-radius: 50%;
        }
        .node-info {
            background: rgba(0,0,0,0.5);
            border-radius: 8px;
            padding: 12px;
            font-size: 0.8em;
            min-height: 60px;
            max-height: 180px;
            overflow-y: auto;
            flex-shrink: 0;
        }
        .node-info pre {
            white-space: pre-wrap;
            font-family: monospace;
            font-size: 0.75em;
            color: #ccc;
        }
        button.control {
            padding: 8px 12px;
            background: #2a2a4e;
            border: 1px solid #445;
            border-radius: 6px;
            color: #ddd;
            cursor: pointer;
            font-size: 0.85em;
            transition: all 0.2s;
        }
        button.control:hover {
            background: #3a3a6e;
            border-color: #00d4ff;
        }
        .status {
            font-size: 0.72em;
            color: #888;
            border-top: 1px solid #334;
            padding: 6px 8px 4px 8px;
            flex-shrink: 0;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .status-line {
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            line-height: 1.4;
        }
        .status-footer {
            color: #446;
            font-size: 0.85em;
        }
        .badge {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7em;
            font-weight: bold;
        }
        .badge-politician { background: #ff4444; color: white; }
        .badge-corp { background: #4488ff; color: white; }
        .badge-offshore { background: #ff8844; color: white; }
        .badge-intermediary { background: #888888; color: white; }
        ::-webkit-scrollbar {
            width: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #1a1a2e;
        }
        ::-webkit-scrollbar-thumb {
            background: #334;
            border-radius: 3px;
        }

        /* ── Kandidaten-Tab ── */
        .tab-bar {
            display: flex;
            gap: 4px;
            margin-bottom: 10px;
        }
        .tab-btn {
            flex: 1;
            padding: 6px 4px;
            background: #1a1a2e;
            border: 1px solid #334;
            border-radius: 5px;
            color: #aaa;
            cursor: pointer;
            font-size: 0.72em;
            text-align: center;
            transition: all 0.2s;
        }
        .tab-btn.active { background: #00d4ff22; border-color: #00d4ff; color: #00d4ff; }
        .tab-btn:hover  { border-color: #00d4ff88; color: #ddd; }
        .resizer {
            width: 6px;
            background: rgba(100,100,150,0.3);
            cursor: col-resize;
            flex-shrink: 0;
            transition: background 0.2s;
            z-index: 20;
        }
        .resizer:hover, .resizer.dragging { background: #4488ff; }
        .candidate-card {
            background: rgba(0,0,0,0.45);
            border: 1px solid #334;
            border-radius: 7px;
            padding: 10px;
            margin-bottom: 8px;
            font-size: 0.78em;
        }
        .candidate-card:hover { border-color: #556; }
        .candidate-card.accepted { border-color: #44bb44; opacity: 0.5; }
        .candidate-card.rejected { border-color: #bb4444; opacity: 0.4; }
        .cand-names { color: #e0e0e0; font-weight: bold; margin-bottom: 4px; }
        .cand-reason { color: #999; font-size: 0.9em; margin-bottom: 6px; word-break: break-word; }
        .conf-bar-bg {
            background: #223;
            border-radius: 3px;
            height: 6px;
            margin-bottom: 6px;
        }
        .conf-bar-fill {
            height: 6px;
            border-radius: 3px;
            background: linear-gradient(90deg, #ff4444, #ffaa00, #44bb44);
            transition: width 0.3s;
        }
        .cand-actions { display: flex; gap: 5px; align-items: center; flex-wrap: wrap; }
        .btn-accept { padding: 3px 8px; background: #1a4a1a; border: 1px solid #44bb44;
                      border-radius: 4px; color: #44bb44; cursor: pointer; font-size: 0.85em; }
        .btn-reject { padding: 3px 8px; background: #4a1a1a; border: 1px solid #bb4444;
                      border-radius: 4px; color: #bb4444; cursor: pointer; font-size: 0.85em; }
        .btn-search { padding: 3px 8px; background: #1a2a4a; border: 1px solid #4488ff;
                      border-radius: 4px; color: #4488ff; cursor: pointer; font-size: 0.85em; }
        .btn-accept:hover { background: #2a6a2a; }
        .btn-reject:hover { background: #6a2a2a; }
        .conf-slider { width: 60px; accent-color: #00d4ff; cursor: pointer; }
        .conf-label   { color: #888; font-size: 0.8em; min-width: 28px; }
        .cand-filter  { display: flex; gap: 5px; margin-bottom: 8px; }
        .cand-filter input { flex:1; padding: 4px 7px; background: #1a1a2e;
                             border: 1px solid #334; border-radius: 4px;
                             color: #e0e0e0; font-size: 0.8em; }
        .cand-count   { color: #888; font-size: 0.75em; margin-bottom: 6px; }
        .candidates-list { max-height: 480px; overflow-y: auto; }

        /* ── Research Agent Tab ── */
        .research-seed-box { display: flex; gap: 6px; margin-bottom: 10px; }
        .research-seed-box input {
            flex: 1; padding: 7px 10px;
            background: #0d1a2e; border: 1px solid #1a3a5a;
            border-radius: 6px; color: #e0e0e0; font-size: 0.82em;
        }
        .research-seed-box input:focus { outline: none; border-color: #00aaff; }
        .btn-research-start {
            padding: 6px 12px; background: #003a5a;
            border: 1px solid #00aaff; border-radius: 6px;
            color: #00aaff; cursor: pointer; font-size: 0.82em; white-space: nowrap;
        }
        .btn-research-start:hover { background: #004a7a; }
        .research-section { margin-bottom: 12px; }
        .research-section-title {
            font-size: 0.7em; color: #668; letter-spacing: 1px;
            text-transform: uppercase; margin-bottom: 5px;
            border-bottom: 1px solid #223; padding-bottom: 3px;
        }
        .hypothesis-item {
            display: flex; align-items: flex-start; gap: 6px;
            padding: 5px 7px; margin-bottom: 4px;
            background: rgba(0,0,0,0.35); border: 1px solid #223;
            border-radius: 5px; font-size: 0.76em;
        }
        .hypothesis-item.active { border-color: #00aaff44; background: #001a2e; }
        .hypothesis-item.done   { opacity: 0.55; }
        .hyp-status { font-size: 1.1em; flex-shrink: 0; margin-top: 1px; }
        .hyp-text { color: #ccc; line-height: 1.35; }
        .dossier-item {
            display: flex; justify-content: space-between; align-items: center;
            padding: 5px 8px; margin-bottom: 4px;
            background: rgba(0,0,0,0.3); border: 1px solid #223;
            border-radius: 5px; font-size: 0.76em; cursor: pointer;
        }
        .dossier-item:hover { border-color: #446; }
        .dossier-name { color: #00aaff; }
        .dossier-meta { color: #666; font-size: 0.85em; }
        .activity-item {
            padding: 4px 6px; font-size: 0.72em; color: #999;
            border-left: 2px solid #223; margin-bottom: 3px;
        }
        .activity-item.breakthrough { border-color: #00aaff; color: #cce; }
        .research-controls { display: flex; gap: 5px; margin-top: 8px; }
        .btn-rctrl {
            flex: 1; padding: 5px 8px; background: #1a1a2e;
            border: 1px solid #334; border-radius: 5px;
            color: #aaa; cursor: pointer; font-size: 0.75em; text-align: center;
        }
        .btn-rctrl:hover { border-color: #00aaff88; color: #ddd; }
        .btn-rctrl.danger { border-color: #aa444488; color: #aa6666; }
        .btn-rctrl.danger:hover { border-color: #cc4444; color: #ff8888; }
        .research-list { overflow-y: auto; }
        .research-list.list-hypotheses { max-height: 280px; }
        .research-list.list-dossiers   { max-height: 200px; }
        .research-list.list-activity   { max-height: 120px; }
        /* Neues Research-Tab Layout */
        .rs-section { margin-bottom:8px; }
        .rs-title { font-size:0.72em; font-weight:bold; color:#778; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px; padding-bottom:2px; border-bottom:1px solid #223; }
        .rs-empty { color:#445; font-size:0.75em; padding:4px; }
        .rs-suggestions { font-size:0.75em; color:#556; }
        .rs-seeds   { max-height:200px; overflow-y:auto; }
        .rs-hyps    { max-height:240px; overflow-y:auto; }
        .rs-dossiers{ max-height:180px; overflow-y:auto; }
        .rs-activity{ max-height:100px; overflow-y:auto; }
        /* Seed-Karte */
        .seed-card { background:rgba(68,136,255,0.12); border:1px solid #2a4a8a; border-radius:5px; padding:6px 8px; margin-bottom:4px; font-size:0.75em; }
        .seed-card-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:3px; }
        .seed-badge { color:#4488ff; font-weight:bold; font-size:0.85em; }
        .seed-stop  { background:#1a1a2e; border:1px solid #664; color:#cc8866; border-radius:3px; padding:2px 8px; cursor:pointer; font-size:0.85em; }
        .seed-stop:hover { border-color:#cc4444; color:#ff6644; }
        .seed-text  { color:#ccd; line-height:1.3; }
    </style>
</head>
<body>
<div class="container">
    <div class="sidebar" id="sidebarEl">

        <!-- ── Header (fixiert oben) ─────────────────────────────── -->
        <div style="padding:14px 14px 0 14px;flex-shrink:0;">
            <h1>🌐 LYRA-NET</h1>
            <p style="font-size:0.8em;color:#aaa;margin:4px 0 10px 0;">Semantisches Netzwerk globaler Eliten<br>Panama · Paradise · Pandora · Offshore Leaks</p>
            <div class="tab-bar">
                <div class="tab-btn active" onclick="switchTab('graph')">🗺️ Graph</div>
                <div class="tab-btn" onclick="switchTab('candidates')" id="tabCandBtn">🔍 Kandidaten</div>
                <div class="tab-btn" onclick="switchTab('research')" id="tabResearchBtn">🔬 Research</div>
                <div class="tab-btn" onclick="switchTab('legend')">📖 Legende</div>
            </div>
        </div>

        <!-- ── Tab-Panels (flex:1, scrollbar intern) ─────────────── -->
        <div class="tab-panels">

            <div class="tab-panel active" id="tabGraph">
                <div class="stats" id="stats">
                    <p>📊 <span id="nodeCount">0</span> Knoten · <span id="edgeCount">0</span> Verbindungen</p>
                    <p>🏢 Personen: <span id="personCount" class="value">0</span> | Offshores: <span id="entityCount" class="value">0</span></p>
                    <p>🌍 Länder: <span id="countryCount" class="value">0</span></p>
                </div>
                <div class="search-box">
                    <input type="text" id="searchInput" placeholder="Person, Firma suchen..." onkeypress="if(event.key==='Enter') searchNode()">
                    <button onclick="searchNode()">🔍</button>
                </div>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                    <button class="control" onclick="resetView()">🔄 Zentrieren</button>
                    <button class="control" onclick="togglePhysics()">⚡ Physics</button>
                    <button class="control" onclick="loadGraph()">🔃 Neu</button>
                </div>
                <div class="node-info" id="nodeInfo">
                    <strong>ℹ️ Knoten-Info</strong>
                    <pre>Klicke auf einen Knoten für Details</pre>
                </div>
            </div>

            <div class="tab-panel" id="tabCandidates">
                <div class="cand-filter">
                    <input type="text" id="candSearch" placeholder="Person filtern..." oninput="filterCandidates()">
                    <input type="number" id="candMinConf" placeholder="Min%" min="0" max="100" value="0" style="width:52px" oninput="filterCandidates()">
                </div>
                <div class="cand-count" id="candCount">Lade Kandidaten...</div>
                <div class="candidates-list" id="candidatesList"></div>
                <div style="margin-top:8px;display:flex;gap:5px;">
                    <button class="control" onclick="loadCandidates()" style="flex:1">🔃 Aktualisieren</button>
                    <button class="control" onclick="exportCandidates()" style="flex:1">💾 Export</button>
                </div>
            </div>

            <div class="tab-panel" id="tabResearch">

                <!-- Seed-Eingabe -->
                <div class="research-seed-box">
                    <input type="text" id="researchSeedInput"
                        placeholder="Seed-Frage eingeben..."
                        onkeypress="if(event.key==='Enter') startResearch()">
                    <button class="btn-research-start" onclick="startResearch()">▶ Start</button>
                </div>

                <!-- Vorschläge -->
                <div class="rs-section" id="suggestionsSection">
                    <div class="rs-title">💡 Vorschläge</div>
                    <div id="suggestionsList" class="rs-suggestions">Lade...</div>
                </div>

                <!-- Queue-Limit -->
                <div class="rs-section">
                    <div class="rs-title">⚙ Queue-Limit: <span id="queueLimitDisplay" style="color:#4488ff;">30</span></div>
                    <div style="display:flex;align-items:center;gap:6px;padding:4px 0;">
                        <span style="font-size:0.7em;color:#556;">10</span>
                        <input type="range" id="queueLimitSlider" min="10" max="200" step="10" value="30"
                            style="flex:1;accent-color:#4488ff;" oninput="updateQueueLimit(this.value)">
                        <button class="btn-rctrl" style="padding:1px 8px;" onclick="updateQueueLimit(0)">∞</button>
                    </div>
                </div>

                <!-- ── SEEDS ─────────────────────────────────── -->
                <div class="rs-section">
                    <div class="rs-title" style="color:#4488ff;">🌱 Seeds</div>
                    <div id="seedList" class="rs-seeds">
                        <div class="rs-empty">Kein Seed aktiv</div>
                    </div>
                </div>

                <!-- ── HYPOTHESEN ─────────────────────────────── -->
                <div class="rs-section">
                    <div class="rs-title">📋 Hypothesen</div>
                    <div id="hypothesisList" class="rs-hyps">
                        <div class="rs-empty">⏳ Warte auf Seed-Frage...</div>
                    </div>
                </div>

                <!-- ── DOSSIERS ───────────────────────────────── -->
                <div class="rs-section">
                    <div class="rs-title">📄 Dossiers</div>
                    <div id="dossierList" class="rs-dossiers">
                        <div class="rs-empty">Keine Dossiers vorhanden</div>
                    </div>
                </div>

                <!-- ── AKTIVITÄT ──────────────────────────────── -->
                <div class="rs-section">
                    <div class="rs-title">⚡ Letzte Aktivität</div>
                    <div id="activityList" class="rs-activity">
                        <div class="rs-empty">⏳ Bereit</div>
                    </div>
                </div>

                <!-- Steuerung -->
                <div class="research-controls">
                    <button class="btn-rctrl" onclick="loadResearchStatus()">🔃</button>
                    <button class="btn-rctrl" id="btnPauseResearch" onclick="toggleResearchAgent()">⏸ Pause</button>
                    <button class="btn-rctrl danger" onclick="clearResearch()">🗑 Reset</button>
                </div>

                <!-- Dossier-Detail -->
                <div id="dossierModal" style="display:none;margin-top:8px;background:rgba(0,0,0,0.7);border:1px solid #334;border-radius:6px;padding:10px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:5px;">
                        <span id="dossierModalTitle" style="color:#00aaff;font-size:0.8em;font-weight:bold;"></span>
                        <span style="color:#666;cursor:pointer;" onclick="document.getElementById('dossierModal').style.display='none'">✕</span>
                    </div>
                    <pre id="dossierModalContent" style="white-space:pre-wrap;font-size:0.7em;color:#ccc;max-height:200px;overflow-y:auto;"></pre>
                </div>

            </div>

            <!-- Legende: kein overflow-y, füllt ganzen Panel-Bereich -->
            <div class="tab-panel" id="tabLegend">
                <div style="display:flex;width:100%;height:100%;overflow:hidden;">
                    <div style="width:190px;min-width:150px;padding:8px;font-size:0.78em;color:#aab;overflow-y:auto;border-right:1px solid #334;flex-shrink:0;">
                        <div style="color:#ccd;font-weight:bold;margin-bottom:6px;">Knotentypen</div>
                        <div class="legend-item" style="margin-bottom:4px;"><div class="legend-color" style="background:#ff4444;"></div><span>Person</span></div>
                        <div class="legend-item" style="margin-bottom:4px;"><div class="legend-color" style="background:#ff8844;"></div><span>Offshore-Firma</span></div>
                        <div class="legend-item" style="margin-bottom:4px;"><div class="legend-color" style="background:#4488ff;"></div><span>Unternehmen</span></div>
                        <div class="legend-item" style="margin-bottom:4px;"><div class="legend-color" style="background:#888888;"></div><span>Intermediary</span></div>
                        <div class="legend-item" style="margin-bottom:4px;"><div class="legend-color" style="background:#44ff88;"></div><span>Land</span></div>
                        <div class="legend-item" style="margin-bottom:8px;"><div class="legend-color" style="background:#aa44ff;"></div><span>Nominee</span></div>
                        <div style="color:#ccd;font-weight:bold;margin-bottom:6px;">Verbindungen</div>
                        <div style="margin-bottom:3px;"><span style="color:#ffaa44;">──</span> officer_of</div>
                        <div style="margin-bottom:3px;"><span style="color:#44aaff;">╌╌</span> registered_address</div>
                        <div style="margin-bottom:3px;"><span style="color:#ff4488;">──</span> intermediary_of</div>
                        <div style="margin-bottom:3px;"><span style="color:#44ff88;">╌╌</span> same_as</div>
                        <div style="margin-bottom:8px;"><span style="color:#00aaff;">╌╌</span> ASSOCIATE</div>
                        <div style="color:#ccd;font-weight:bold;margin-bottom:6px;">Quellen</div>
                        <div style="margin-bottom:2px;">🇵🇦 Panama Papers</div>
                        <div style="margin-bottom:2px;">🏝 Paradise Papers</div>
                        <div style="margin-bottom:2px;">🌊 Pandora Papers</div>
                        <div style="margin-bottom:8px;">🔍 Offshore Leaks</div>
                        <div id="legendStats" style="color:#556;font-size:0.9em;border-top:1px solid #334;padding-top:6px;"></div>
                    </div>
                    <div style="flex:1;position:relative;min-width:0;">
                        <div id="legendGraph" style="width:100%;height:100%;"></div>
                        <div style="position:absolute;bottom:4px;right:6px;font-size:0.7em;color:#446;">Beispiel-Netzwerk</div>
                    </div>
                </div>
            </div>

        </div>  <!-- Ende .tab-panels -->

        <!-- ── Status-Bar (fixiert unten) ────────────────────────── -->
        <div class="status">
            <div class="status-line" id="statusMsg">🟢 Online</div>
            <div class="status-line" id="researchStatus">🔬 Recherche: wartet...</div>
            <div class="status-line status-footer">LYRA-NET · Lokale Recherche · Keine Cloud-APIs</div>
        </div>

    </div>  <!-- Ende der Sidebar (.sidebar) -->

    <div class="resizer" id="sidebarResizer"></div>

    <div class="graph-container">
        <div id="mynetwork"></div>
        <div id="loadingOverlay" style="
            position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
            color:#00d4ff; font-size:1.2em; text-align:center; pointer-events:none;">
            ⏳ Lade Graph...<br>
            <span style="font-size:0.7em;color:#888;">Erste Anfrage kann 5-10s dauern</span>
        </div>
    </div>
</div>  <!-- Ende .container -->

<script src="/static/jquery.min.js"></script>
<script src="/static/vis-network.min.js"></script>
<script>
// dbg() global definieren damit alle Bloecke darauf zugreifen koennen
window.dbg = function(msg) {
    const el = document.getElementById('debugLog');
    if (el) el.innerHTML += (el.innerHTML ? '<br>' : '') + msg;
    console.log('[DBG]', msg);
};
function dbg(msg) { window.dbg(msg); }

let network = null;
let nodes = null;
let edges = null;
let physicsEnabled = true;
let graphData = null;

// Farben nach Knotentyp
const colors = {
    'Person': '#ff4444',
    'Politician': '#ff4444',
    'Entity': '#4488ff',
    'Offshore': '#ff8844',
    'Intermediary': '#888888',
    'Address': '#aaaaaa',
    'Country': '#44ff88'
};

// Initialisierung erfolgt ueber window.onload am Ende der Seite
window.onload = function() {
    // Standard: Graph-Tab aktiv. /research-Route setzt INITIAL_TAB via Meta-Tag.
    var meta = document.querySelector('meta[name="initial-tab"]');
    var tab  = (meta && meta.content) ? meta.content : 'graph';
    switchTab(tab);
};

function setStatus(msg) {
    // Setzt Statustext ohne jQuery-Abhaengigkeit
    var el = document.getElementById('statusMsg');
    if (el) el.innerHTML = msg;
}

function loadGraph() {
    setStatus('⏳ Lade Graph...');
    fetch('/api/graph')
        .then(function(response) {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(function(data) {
            if (!data.nodes || data.nodes.length === 0) {
                setStatus('⚠️ 0 Knoten empfangen');
                    return;
            }
            var overlay = document.getElementById('loadingOverlay');
            if (overlay) overlay.style.display = 'none';
            graphData = data;
            updateStats(data);
            buildNetwork(data);
            setStatus('🟢 ' + data.nodes.length + ' Knoten · ' + data.edges.length + ' Kanten geladen');
        })
        .catch(function(err) {
            var overlay = document.getElementById('loadingOverlay');
            if (overlay) overlay.innerHTML = '❌ ' + err.message + '<br><button onclick="loadGraph()" style="margin-top:8px;padding:4px 12px;background:#1a2a4a;border:1px solid #4488ff;border-radius:4px;color:#4488ff;cursor:pointer;">🔃 Erneut versuchen</button>';
            setStatus('❌ ' + err.message);
            console.error('loadGraph error:', err);
        });
}

function setText(id, val) {
    var el = document.getElementById(id);
    if (el) el.textContent = val;
}

function updateStats(data) {
    setText('nodeCount',  data.nodes.length);
    setText('edgeCount',  data.edges.length);

    let personCount = 0, entityCount = 0;
    const countries = new Set();
    data.nodes.forEach(function(n) {
        if (n.group === 'Person' || n.group === 'Politician') personCount++;
        else if (n.group === 'Entity' || n.group === 'Offshore') entityCount++;
        if (n.tooltip) {
            const m = n.tooltip.match(/Land: (.+)/);
            if (m && m[1] && m[1] !== 'unbekannt' && m[1].trim() !== '') {
                countries.add(m[1].trim());
            }
        }
    });
    setText('personCount',  personCount);
    setText('entityCount',  entityCount);
    setText('countryCount', countries.size);
}

function buildNetwork(data) {
    nodes = new vis.DataSet(data.nodes.map(n => ({
        id: n.id,
        label: n.label,
        title: n.tooltip || n.label,
        group: n.group,
        color: colors[n.group] || '#aaaaaa',
        font: { color: '#fff', size: 12 }
    })));
    
    edges = new vis.DataSet(data.edges.map(e => ({
        from: e.from,
        to: e.to,
        label: e.label || '',
        arrows: 'to',
        color: { color: 'rgba(100,100,150,0.4)' },
        font: { color: '#888', size: 10 }
    })));
    
    const container = document.getElementById('mynetwork');
    const options = {
        nodes: {
            shape: 'dot',
            size: 12,
            font: { color: '#fff', size: 12, face: 'Segoe UI' },
            borderWidth: 1,
            borderWidthSelected: 3,
            shadow: true
        },
        edges: {
            smooth: { type: 'curvedCW', roundness: 0.2 },
            width: 1.5,
            selectionWidth: 3,
            shadow: true
        },
        physics: {
            enabled: true,
            stabilization: { iterations: 200 },
            solver: 'forceAtlas2Based',
            forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.005, springLength: 100 }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200,
            navigationButtons: true,
            zoomView: true,
            dragView: true
        },
        layout: { improvedLayout: true }
    };
    
    network = new vis.Network(container, { nodes, edges }, options);
    
    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            showNodeInfo(params.nodes[0]);
        }
    });

    // Doppelklick: Suche nach diesem Knoten und zeige alle Verbindungen
    network.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            const nodeId = params.nodes[0];
            // Finde den Knoten im aktuellen Datensatz
            const nodeData = graphData && graphData.nodes
                ? graphData.nodes.find(function(n) { return n.id === nodeId; })
                : null;
            if (nodeData && nodeData.label) {
                const searchTerm = nodeData.label.replace(/[.]{3}$/,'').trim();
                document.getElementById('searchInput').value = searchTerm;
                setStatus('🔍 Lade Verbindungen fuer: ' + searchTerm);
                fetch('/api/graph/node/' + encodeURIComponent(nodeId))
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        if (!data.nodes || data.nodes.length === 0) {
                            setStatus('❌ Keine Verbindungen gefunden');
                            return;
                        }
                        graphData = data;
                        updateStats(data);
                        buildNetwork(data);
                        // Treffer zentrieren
                        if (network) {
                            network.selectNodes([nodeId]);
                            network.focus(nodeId, {scale: 1.5, animation: true});
                        }
                        setStatus('🔍 ' + data.nodes.length + ' Knoten · ' +
                                  data.edges.length + ' Verbindungen');
                    })
                    .catch(function(err) {
                        setStatus('❌ ' + err.message);
                    });
            }
        }
    });
    
    network.on('stabilizationIterationsDone', function() {
        network.fit();
    });

    // Sicherstellen dass das Netzwerk korrekt dimensioniert ist
    setTimeout(function() { if (network) network.fit(); }, 300);
    
    $('#statusMsg').html('🟢 Graph geladen (' + data.nodes.length + ' Knoten)');
    // Ausstehende Kontext-Visualisierung ausführen
    if (_pendingContextRender) {
        var p = _pendingContextRender;
        _pendingContextRender = null;
        setTimeout(function() { renderContextGraph(p.nodesData, p.edgesData, p.title); }, 100);
    }
}

function showNodeInfo(nodeId) {
    $.getJSON('/api/node/' + nodeId, function(data) {
        var info = '';
        if (data.type === 'Person' || data.type === 'Politician') {
            info = (data.name || data.label) + '\\n';
            info += 'Land: ' + (data.country || 'unbekannt') + '\\n';
            info += 'Rolle: ' + (data.role || 'unbekannt') + '\\n';
            if (data.connections) info += 'Verbindungen: ' + data.connections + '\\n';
        } else if (data.type === 'Entity' || data.type === 'Offshore') {
            info = (data.name || data.label) + '\\n';
            info += 'Jurisdiktion: ' + (data.country || 'unbekannt') + '\\n';
            info += 'Gruendung: ' + (data.incorporation_date || 'unbekannt') + '\\n';
        } else if (data.type === 'Country') {
            info = (data.name || '') + '\\n';
            info += 'Offshore-Firmen: ' + (data.entity_count || 0) + '\\n';
            info += 'Personen: ' + (data.person_count || 0) + '\\n';
        } else {
            info = (data.name || data.label || '') + '\\n';
            info += 'Typ: ' + (data.type || '') + '\\n';
        }
        $('#nodeInfo pre').text(info);
    }).fail(function() {
        $('#nodeInfo pre').text('Keine Details verfuegbar');
    });
}

function searchNode() {
    const query = document.getElementById('searchInput').value.trim();
    if (!query || query.length < 2) return;

    setStatus('🔍 Suche nach "' + query + '"...');

    fetch('/api/graph/search?q=' + encodeURIComponent(query) + '&depth=1')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error && data.nodes.length === 0) {
                setStatus('❌ ' + data.error);
                return;
            }
            // Graph komplett durch Suchergebnis ersetzen
            graphData = data;
            updateStats(data);
            buildNetwork(data);

            // Treffer-Knoten hervorheben (isHit=true)
            if (network) {
                const hitIds = data.nodes
                    .filter(function(n) { return n.isHit; })
                    .map(function(n) { return n.id; });
                if (hitIds.length > 0) {
                    network.selectNodes(hitIds);
                    network.focus(hitIds[0], { scale: 1.8, animation: true });
                }
            }
            setStatus('🔍 ' + data.hits + ' Treffer fuer "' + query +
                      '" · ' + data.nodes.length + ' Knoten · ' +
                      data.edges.length + ' Verbindungen');
        })
        .catch(function(err) {
            setStatus('❌ Suche fehlgeschlagen: ' + err.message);
        });
}

function resetView() {
    network.fit({ animation: true });
}

function togglePhysics() {
    physicsEnabled = !physicsEnabled;
    network.setOptions({ physics: { enabled: physicsEnabled } });
    $('#statusMsg').html(physicsEnabled ? '⚡ Physics aktiviert' : '⚡ Physics deaktiviert');
}

function startAutoRefresh() {
    setInterval(function() {
        fetch('/api/health')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.status === 'ok') {
                    setStatus('🟢 Online · ' + data.node_count + ' Knoten · ' + (data.last_update || 'gerade'));
                }
            })
            .catch(function() { setStatus('🔴 Verbindung verloren'); });
    }, 30000);
}
function updateResearchStatusBar() {
    fetch('/api/research/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var hyps = data.hypotheses || [];
            // Zähler aus server-seitigem counts-Objekt (vollständige Liste, nicht [:30])
            var counts  = data.counts || {};
            var active  = counts.active  !== undefined ? counts.active  : hyps.filter(function(h) { return h.status === 'active';  }).length;
            var pending = counts.pending !== undefined ? counts.pending : hyps.filter(function(h) { return h.status === 'pending'; }).length;
            var done    = counts.done    !== undefined ? counts.done    : hyps.filter(function(h) { return h.status === 'done';    }).length;
            
            var lastActivity = '';
            if (data.activity && data.activity.length > 0) {
                var a = data.activity[0];
                lastActivity = a.time + ' ' + a.message;
                if (lastActivity.length > 45) lastActivity = lastActivity.substring(0, 42) + '...';
            } else {
                lastActivity = 'wartet auf Anfrage';
            }
            
            var runningIcon = data.running ? '🟢' : '⏸';
            var statusText = runningIcon + ' aktiv:' + active + ' · ausstehend:' + pending + ' · fertig:' + done;
            document.getElementById('researchStatus').innerHTML = '🔬 ' + statusText + ' · ' + lastActivity;
        })
        .catch(function(e) {
            document.getElementById('researchStatus').innerHTML = '🔬 Recherche: nicht verfügbar';
        });
}

// Research-Status alle 10 Sekunden aktualisieren (auch wenn Tab nicht aktiv)
setInterval(updateResearchStatusBar, 10000);
// Sofort einmal beim Laden
setTimeout(updateResearchStatusBar, 2000);
// ── Tab-System ───────────────────────────────────────────────────────────────
var allCandidates = [];

function switchTab(name) {
    ['graph','candidates','research','legend'].forEach(function(t) {
        var panel = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
        var btn   = document.querySelector('.tab-btn[onclick*="' + t + '"]');
        if (panel) panel.classList.toggle('active', t === name);
        if (btn)   btn.classList.toggle('active',   t === name);
    });
    if (name === 'candidates') { loadCandidates(); }
    if (name === 'research')   {
        var p = document.getElementById('tabResearch');
        if (p) p.scrollTop = 0;
        loadResearchStatus(); loadResearchGraph();
    }
    if (name === 'legend')     { loadLegendStats(); }
    if (name === 'graph')      { loadGraph(); }
}

function loadLegendStats() {
    fetch('/api/health').then(function(r){return r.json();}).then(function(d){
        var el = document.getElementById('legendStats');
        if (el) el.innerHTML =
            '🗄 <b>' + (d.node_count||0).toLocaleString() + '</b> Knoten<br>' +
            '🕐 ' + (d.last_update||'-');
    }).catch(function(){});
    initLegendGraph();
}

function initLegendGraph() {
    var container = document.getElementById('legendGraph');
    if (!container || container._legendInit) return;
    container._legendInit = true;

    var legendNodes = new vis.DataSet([
        {id:1, label:'Max Mustermann\\nPerson',       color:{background:'#ff4444',border:'#ff6666'}, shape:'dot',      size:18, font:{color:'#fff',size:10}},
        {id:2, label:'Offshore Ltd\\nBVI',             color:{background:'#ff8844',border:'#ffaa66'}, shape:'box',      size:16, font:{color:'#fff',size:10}},
        {id:3, label:'Holding AG\\nSchweiz',           color:{background:'#4488ff',border:'#66aaff'}, shape:'triangle', size:16, font:{color:'#fff',size:10}},
        {id:4, label:'Mossack Fonseca\\nIntermediary', color:{background:'#888888',border:'#aaaaaa'}, shape:'diamond',  size:16, font:{color:'#fff',size:10}},
        {id:5, label:'Panama\\nLand',                  color:{background:'#44ff88',border:'#66ffaa'}, shape:'ellipse',  size:16, font:{color:'#333',size:10}},
        {id:6, label:'Nominee Ltd\\nNominee',          color:{background:'#aa44ff',border:'#cc66ff'}, shape:'dot',      size:14, font:{color:'#fff',size:10}}
    ]);

    var legendEdges = new vis.DataSet([
        {from:1, to:2, label:'officer_of',         color:{color:'#ffaa44'}, font:{color:'#ffaa44',size:9}, arrows:'to'},
        {from:4, to:2, label:'intermediary_of',    color:{color:'#ff4488'}, font:{color:'#ff4488',size:9}, arrows:'to'},
        {from:2, to:5, label:'reg_address',        color:{color:'#44aaff'}, font:{color:'#44aaff',size:9}, dashes:true, arrows:'to'},
        {from:2, to:3, label:'same_as',            color:{color:'#44ff88'}, font:{color:'#44ff88',size:9}, dashes:true},
        {from:1, to:6, label:'ASSOCIATE',          color:{color:'#00aaff'}, font:{color:'#00aaff',size:9}, dashes:true, arrows:'to'}
    ]);

    var legendOptions = {
        physics:    {stabilization:{iterations:100}},
        interaction:{dragNodes:true, zoomView:true},
        nodes:      {borderWidth:1.5, font:{face:'monospace'}},
        edges:      {smooth:{type:'continuous'}, width:1.5}
    };

    new vis.Network(container, {nodes:legendNodes, edges:legendEdges}, legendOptions);
}

function legendHighlight(type) { /* reserved for future filter */ }

// ── Sidebar Resizer ───────────────────────────────────────────────────────────
(function() {
    var resizer  = document.getElementById('sidebarResizer');
    var sidebar  = document.getElementById('sidebarEl');
    var dragging = false;
    if (!resizer || !sidebar) return;
    resizer.addEventListener('mousedown', function(e) {
        dragging = true;
        resizer.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        var newW = e.clientX;
        if (newW < 180) newW = 180;
        if (newW > window.innerWidth * 0.6) newW = window.innerWidth * 0.6;
        sidebar.style.width = newW + 'px';
        if (network) network.redraw();
    });
    document.addEventListener('mouseup', function() {
        if (!dragging) return;
        dragging = false;
        resizer.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        if (network) { network.redraw(); network.fit(); }
    });
})();

// ── Research-Tab: letzter Fund beim Öffnen ────────────────────────────────────
var researchAgentRunning = false;

function loadResearchStatus() {
    // Prüfe ob research_report.md auf LYRA wartet
    fetch('/api/research/report-status')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var el = document.getElementById('reportPendingBadge');
            if (!el) {
                el = document.createElement('div');
                el.id = 'reportPendingBadge';
                el.style.cssText = 'background:#ff8800;color:#fff;font-size:0.72em;padding:3px 8px;border-radius:4px;margin-bottom:6px;display:none;';
                var seed = document.getElementById('suggestionsSection');
                if (seed) seed.parentNode.insertBefore(el, seed);
            }
            if (d.report_pending) {
                el.style.display = 'block';
                el.textContent = '📋 Zwischenbericht wartet auf LYRA (' + (d.written_at||'') + ')';
            } else {
                el.style.display = 'none';
            }
        }).catch(function(){});

    fetch('/api/research/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            researchAgentRunning = data.running || false;
            var btn = document.getElementById('btnPauseResearch');
            if (btn) btn.textContent = researchAgentRunning ? '⏸ Pause' : '▶ Fortsetzen';
            renderSeeds(data.hypotheses || [], data.queue_limit || 30);
            renderHypotheses(data.hypotheses || []);
            renderActivity(data.activity || []);
        })
        .catch(function(e) { console.warn('Research status error:', e); });

    fetch('/api/research/dossiers')
        .then(function(r) { return r.json(); })
        .then(function(data) { renderDossiers(data.dossiers || []); })
        .catch(function(e) { console.warn('Dossiers error:', e); });

    loadSuggestions();
}

function loadSuggestions() {
    fetch('/api/research/suggestions')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var list = document.getElementById('suggestionsList');
            if (!list) return;
            var suggestions = data.suggestions || [];
            if (suggestions.length === 0) {
                list.innerHTML = '<span style="color:#445;">Keine Vorschläge verfügbar</span>';
                return;
            }
            list.innerHTML = '';
            suggestions.forEach(function(s) {
                var btn = document.createElement('div');
                btn.style.cssText = 'padding:4px 7px;margin-bottom:3px;cursor:pointer;' +
                    'background:rgba(0,80,120,0.15);border:1px solid #1a3a5a;' +
                    'border-radius:4px;color:#7ab;font-size:0.78em;line-height:1.4;';
                btn.textContent = '💡 ' + s;
                btn.onmouseover = function() { this.style.borderColor='#00aaff'; this.style.color='#adf'; };
                btn.onmouseout  = function() { this.style.borderColor='#1a3a5a'; this.style.color='#7ab'; };
                btn.onclick = (function(text) {
                    return function() {
                        document.getElementById('researchSeedInput').value = text;
                        document.getElementById('researchSeedInput').focus();
                    };
                })(s);
                list.appendChild(btn);
            });
        })
        .catch(function() {
            var list = document.getElementById('suggestionsList');
            if (list) list.innerHTML = '';
        });
}

function updateQueueLimit(val) {
    val = parseInt(val) || 0;
    var display = document.getElementById('queueLimitDisplay');
    var slider  = document.getElementById('queueLimitSlider');
    if (display) display.textContent = val === 0 ? 'unbegrenzt' : val;
    if (slider && val > 0) slider.value = Math.min(val, 200);
    fetch('/api/research/queue-limit', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({limit:val})}).catch(function(){});
}

function stopSeed(seedId) {
    if (!confirm('Seed stoppen? Alle pending Subhypothesen werden entfernt. Fertige Dossiers bleiben erhalten.')) return;
    fetch('/api/research/stop-seed/' + seedId, {method:'POST'})
        .then(function(r) { return r.json(); })
        .then(function() { loadResearchStatus(); });
}

function renderSeeds(hyps, queueLimit) {
    var el = document.getElementById('seedList');
    if (!el) return;
    var seeds = hyps.filter(function(h) {
        return h.is_seed || (h.priority >= 3 && !h.parent_id);
    });
    if (seeds.length === 0) {
        el.innerHTML = '<div class="rs-empty">Kein Seed aktiv</div>';
        return;
    }
    var html = '';
    seeds.forEach(function(h) {
        var icon = h.status === 'active' ? '🔄' : h.status === 'done' ? '✅' : '🌱';
        var conf = h.confidence ? ' ' + h.confidence + '%' : '';
        var canStop = (h.status !== 'done');
        html += '<div class="seed-card">';
        html += '<div class="seed-card-header">';
        html += '<span class="seed-badge">' + icon + ' SEED' + conf + '</span>';
        if (canStop) {
            html += '<button class="seed-stop seed-stop-btn" data-seed-id="' + h.id + '">🛑 Stop</button>';
        }
        html += '</div>';
        html += '<div class="seed-text">' + escHtml(h.text) + '</div>';
        html += '</div>';
    });
    el.innerHTML = html;
    el.querySelectorAll('.seed-stop-btn').forEach(function(btn) {
        btn.addEventListener('click', function() { stopSeed(btn.getAttribute('data-seed-id')); });
    });
    var display = document.getElementById('queueLimitDisplay');
    var slider  = document.getElementById('queueLimitSlider');
    if (display) display.textContent = queueLimit === 0 ? 'unbegrenzt' : queueLimit;
    if (slider && queueLimit > 0) slider.value = Math.min(queueLimit, 200);
}

function renderHypotheses(hypotheses) {
    var list = document.getElementById('hypothesisList');
    if (!list) return;
    // Seeds werden separat in renderSeeds gezeigt – hier nur Nicht-Seeds
    var nonSeeds = hypotheses.filter(function(h) { return !h.is_seed; });
    if (nonSeeds.length === 0) {
        list.innerHTML = '<div style="color:#555;font-size:0.8em;padding:6px;">Keine Subhypothesen aktiv</div>';
        return;
    }
    list.innerHTML = '';
    nonSeeds.forEach(function(h) {
        var div = document.createElement('div');
        var statusMap = { 'pending': '⏳', 'active': '🔄', 'done': '✅', 'failed': '❌' };
        var icon = statusMap[h.status] || '⏳';
        div.className = 'hypothesis-item' + (h.status === 'active' ? ' active' : '') + (h.status === 'done' ? ' done' : '');
        div.innerHTML = '<span class="hyp-status">' + icon + '</span>' + '<span class="hyp-text">' + escHtml(h.text) + (h.confidence ? ' <span style="color:#00aaff;font-size:0.85em;">(' + h.confidence + '%)</span>' : '') + '</span>';
        list.appendChild(div);
    });
}

function renderDossiers(dossiers) {
    var list = document.getElementById('dossierList');
    if (!list) return;
    if (dossiers.length === 0) {
        list.innerHTML = '<div style="color:#555;font-size:0.8em;padding:6px;">Keine Dossiers vorhanden</div>';
        return;
    }
    list.innerHTML = '';
    dossiers.forEach(function(d) {
        var div = document.createElement('div');
        div.className = 'dossier-item';
        div.innerHTML = '<span class="dossier-name">📄 ' + escHtml(d.name) + '</span>' + '<span class="dossier-meta">' + (d.updated || '') + ' · ' + (d.findings || 0) + ' Erkenntnisse</span>';
        div.onclick = (function(name) { return function() { openDossier(name); }; })(d.name);
        list.appendChild(div);
    });
}

function renderActivity(activities) {
    var list = document.getElementById('activityList');
    if (!list) return;
    if (activities.length === 0) {
        list.innerHTML = '<div style="color:#555;font-size:0.8em;padding:6px;">Warte auf Aktivität...</div>';
        return;
    }
    list.innerHTML = '';
    activities.slice(0, 12).forEach(function(a) {
        var div = document.createElement('div');
        div.className = 'activity-item' + (a.breakthrough ? ' breakthrough' : '');
        div.textContent = (a.time || '') + ' ' + (a.message || '');
        list.appendChild(div);
    });
}

function startResearch() {
    var seed = document.getElementById('researchSeedInput').value.trim();
    if (!seed) { setStatus('⚠️ Bitte Seed-Frage eingeben'); return; }
    setStatus('🔬 Starte Recherche zu: ' + seed.substring(0, 50) + '...');
    fetch('/api/research/hypothesis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hypothesis: seed, is_seed: true })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        setStatus('✅ Recherche gestartet: ' + (data.hypotheses_generated || 0) + ' Hypothesen generiert');
        document.getElementById('researchSeedInput').value = '';
        setTimeout(loadResearchStatus, 1000);
    })
    .catch(function(e) { setStatus('❌ Fehler: ' + e.message); });
}

function toggleResearchAgent() {
    var action = researchAgentRunning ? 'pause' : 'resume';
    fetch('/api/research/' + action, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() { loadResearchStatus(); });
}

function clearResearch() {
    if (!confirm('Alle Hypothesen und Aktivitäten zurücksetzen?')) return;
    fetch('/api/research/clear', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() { loadResearchStatus(); });
}

function openDossier(name) {
    fetch('/api/research/dossier/' + encodeURIComponent(name))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var modal = document.getElementById('dossierModal');
            document.getElementById('dossierModalTitle').textContent = '📄 ' + name;
            document.getElementById('dossierModalContent').textContent = data.content || '(leer)';
            modal.style.display = 'block';
            // Visualisierung: Graph-Tab sicherstellen dann rendern
            if (!network) {
                loadGraph();
            }
            loadResearchGraph(name);
        });
}

// ── Kontextsensitives vis-Netzwerk ────────────────────────────────────────────
function loadResearchGraph(dossierName) {
    // Lädt ASSOCIATE-Verbindungen aus Neo4j und zeigt sie im vis-Netzwerk
    var url = '/api/research/graph';
    if (dossierName) url += '?dossier=' + encodeURIComponent(dossierName);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!data.nodes || data.nodes.length === 0) return;
            renderContextGraph(data.nodes, data.edges, dossierName);
        })
        .catch(function(e) { console.log('Research graph error:', e); });
}

var _pendingContextRender = null;

function renderContextGraph(nodesData, edgesData, title) {
    if (!network || !nodes || !edges) {
        // Speichern und nach Graph-Load nochmal versuchen
        _pendingContextRender = {nodesData: nodesData, edgesData: edgesData, title: title};
        if (!network) loadGraph();
        return;
    }
    _pendingContextRender = null;
    // Bestehenden Graph ersetzen
    var nds = nodesData.map(function(n) {
        return {
            id:    n.id,
            label: (n.label || n.id).substring(0, 30),
            color: { background: n.color || '#4488ff', border: '#aaccff' },
            font:  { color: '#fff', size: 10 },
            title: n.label
        };
    });
    var eds = edgesData.map(function(e) {
        var isAssoc = e.type === 'ASSOCIATE';
        return {
            from:   e.from,
            to:     e.to,
            label:  e.type || '',
            color:  { color: isAssoc ? '#00aaff' : '#445566' },
            dashes: isAssoc,
            arrows: 'to',
            font:   { color: isAssoc ? '#00aaff' : '#556677', size: 9 }
        };
    });
    nodes.clear(); nodes.add(nds);
    edges.clear(); edges.add(eds);
    // Titel im Graph-Container anzeigen
    var overlay = document.getElementById('loadingOverlay');
    if (overlay) {
        overlay.style.display = 'block';
        overlay.style.color = '#00aaff';
        overlay.innerHTML = '🔬 ' + (title || 'Research-Funde') +
            '<br><span style="font-size:0.7em;color:#556;">' +
            nds.length + ' Knoten · ' + eds.length + ' Verbindungen</span>';
        setTimeout(function() { overlay.style.display = 'none'; }, 3000);
    }
    network.fit();
}

function showCandidateInGraph(c) {
    var label1 = (c.person1 || '?').substring(0, 28);
    var label2 = (c.person2 || '?').substring(0, 28);
    var title  = label1 + ' \u2194 ' + label2;
    fetch('/api/research/graph?candidate=' + encodeURIComponent((c.person1||'') + '|' + (c.person2||'')))
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.nodes && data.nodes.length > 0) {
                // Neo4j-Treffer gefunden – vorgeschlagene Verbindung als extra gestrichelte Kante
                var n1 = data.nodes.find(function(n) { return n.label && c.person1 && n.label.toLowerCase().indexOf(c.person1.substring(0,10).toLowerCase()) >= 0; });
                var n2 = data.nodes.find(function(n) { return n.label && c.person2 && n.label.toLowerCase().indexOf(c.person2.substring(0,10).toLowerCase()) >= 0; });
                if (n1 && n2 && n1.id !== n2.id) {
                    data.edges.push({from: n1.id, to: n2.id, type: 'ASSOCIATE (' + (c.confidence||0) + '%)', confidence: c.confidence});
                }
                renderContextGraph(data.nodes, data.edges, title);
            } else {
                // Fallback: nur die zwei Kandidaten-Knoten + gestrichelte Verbindung
                var conf     = c.confidence || 0;
                var reason   = (c.reason || '').substring(0, 60);
                var edgeLbl  = (c.rel_type || 'ASSOCIATE') + ' ' + conf + '%';
                var nds = [
                    {id:'c1', label:label1, color:{background:'#ff4444',border:'#ff6666'}, font:{color:'#fff',size:11}, title:(c.person1||'')},
                    {id:'c2', label:label2, color:{background:'#aa44ff',border:'#cc66ff'}, font:{color:'#fff',size:11}, title:(c.person2||'')}
                ];
                var eds = [{from:'c1', to:'c2', label:edgeLbl, color:{color:'#00aaff'}, dashes:true, arrows:'to', font:{color:'#00aaff',size:10}, title:reason}];
                renderContextGraph(nds, eds, title);
            }
        })
        .catch(function() {
            var nds = [
                {id:'c1', label:label1, color:{background:'#ff4444',border:'#ff6666'}, font:{color:'#fff',size:11}},
                {id:'c2', label:label2, color:{background:'#aa44ff',border:'#cc66ff'}, font:{color:'#fff',size:11}}
            ];
            var eds = [{from:'c1', to:'c2', label:(c.rel_type||'ASSOCIATE'), color:{color:'#00aaff'}, dashes:true, arrows:'to', font:{color:'#00aaff',size:10}}];
            renderContextGraph(nds, eds, title);
        });
}

function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// Polling fuer Research-Tab (alle 15s wenn aktiv)
setInterval(function() {
    var panel = document.getElementById('tabResearch');
    if (panel && panel.classList.contains('active')) loadResearchStatus();
}, 5000);

// ── Kandidaten-Tab ────────────────────────────────────────────────────────────
function loadCandidates() {
    document.getElementById('candCount').textContent = 'Lade...';
    fetch('/api/candidates')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            allCandidates = data.candidates || [];
            renderCandidates(allCandidates);
            var btn = document.getElementById('tabCandBtn');
            if (btn) btn.textContent = '🔍 Kandidaten (' + allCandidates.length + ')';
        })
        .catch(function(e) {
            document.getElementById('candCount').textContent = 'Fehler: ' + e.message;
        });
}

function filterCandidates() {
    var q       = (document.getElementById('candSearch').value || '').toLowerCase();
    var minConf = parseInt(document.getElementById('candMinConf').value || '0', 10);
    var filtered = allCandidates.filter(function(c) {
        var names = ((c.person1 || '') + ' ' + (c.person2 || '')).toLowerCase();
        return (c.confidence || 0) >= minConf && (!q || names.includes(q));
    });
    renderCandidates(filtered);
}

function renderCandidates(candidates) {
    var list  = document.getElementById('candidatesList');
    var count = document.getElementById('candCount');
    count.textContent = candidates.length + ' unbestätigte Verbindungen';
    list.innerHTML = '';

    if (candidates.length === 0) {
        list.innerHTML = '<div style="color:#888;text-align:center;padding:20px;">Keine Kandidaten gefunden</div>';
        return;
    }

    candidates.forEach(function(c) {
        var conf      = c.confidence || 0;
        var confColor = conf > 70 ? '#44bb44' : conf > 40 ? '#ffaa00' : '#ff6644';
        var relType   = c.rel_type || 'UNKNOWN';
        var date      = c.suggested_at ? c.suggested_at.substring(0, 10) : '';

        var card = document.createElement('div');
        card.className = 'candidate-card';
        card.id = 'card-' + c.id;

        var names = document.createElement('div');
        names.className = 'cand-names';
        names.textContent = '👤 ' + (c.person1 || '?') + ' ↔ ' + (c.person2 || '?');
        names.style.cursor = 'pointer';
        names.title = 'Im Netzwerk anzeigen';
        names.onclick = (function(cand) { return function() { showCandidateInGraph(cand); }; })(c);
        card.appendChild(names);

        var reason = document.createElement('div');
        reason.className = 'cand-reason';
        reason.textContent = c.reason || '';
        card.appendChild(reason);

        var meta = document.createElement('div');
        meta.style.cssText = 'display:flex;justify-content:space-between;margin-bottom:3px;';
        meta.innerHTML = '<span style="color:' + confColor + ';font-size:0.85em;">Confidence: ' + conf + '%</span>' + '<span style="color:#666;font-size:0.78em;">' + relType + ' · ' + date + '</span>';
        card.appendChild(meta);

        var barBg = document.createElement('div');
        barBg.className = 'conf-bar-bg';
        var barFill = document.createElement('div');
        barFill.className = 'conf-bar-fill';
        barFill.style.cssText = 'width:' + conf + '%;background:' + confColor;
        barBg.appendChild(barFill);
        card.appendChild(barBg);

        var actions = document.createElement('div');
        actions.className = 'cand-actions';

        var btnA = document.createElement('button');
        btnA.className = 'btn-accept';
        btnA.textContent = '✅ Akzeptieren';
        btnA.onclick = (function(sid) { return function() { acceptCandidate(sid); }; })(c.id);
        actions.appendChild(btnA);

        var btnR = document.createElement('button');
        btnR.className = 'btn-reject';
        btnR.textContent = '❌ Ablehnen';
        btnR.onclick = (function(sid) { return function() { rejectCandidate(sid); }; })(c.id);
        actions.appendChild(btnR);

        var btnW = document.createElement('button');
        btnW.className = 'btn-search';
        btnW.textContent = '🔍 Web';
        btnW.onclick = (function(p1, p2) {
            return function() { window.open('https://www.google.com/search?q=' + encodeURIComponent(p1 + ' ' + p2), '_blank'); };
        })(c.person1 || '', c.person2 || '');
        actions.appendChild(btnW);

        var slider = document.createElement('input');
        slider.type = 'range';
        slider.className = 'conf-slider';
        slider.min = 0; slider.max = 100; slider.value = conf;
        var confLabel = document.createElement('span');
        confLabel.className = 'conf-label';
        confLabel.textContent = conf + '%';
        slider.oninput  = function() { confLabel.textContent = this.value + '%'; };
        slider.onchange = (function(sid) { return function() { updateConfidence(sid, this.value); }; })(c.id);
        actions.appendChild(slider);
        actions.appendChild(confLabel);

        card.appendChild(actions);
        list.appendChild(card);
    });
}


function acceptCandidate(sid) {
    fetch('/api/candidates/' + sid + '/accept', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({relationship_type:'ASSOCIATE'})})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var card = document.getElementById('card-' + sid);
            if (card) { card.classList.add('accepted'); card.querySelector('.cand-actions').innerHTML = '<span style="color:#44bb44">✅ Akzeptiert</span>'; }
            setStatus('✅ Verbindung akzeptiert und als RELATED_TO gespeichert');
        });
}

function rejectCandidate(sid) {
    fetch('/api/candidates/' + sid + '/reject', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reason:'Manuell abgelehnt'})})
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var card = document.getElementById('card-' + sid);
            if (card) { card.classList.add('rejected'); card.querySelector('.cand-actions').innerHTML = '<span style="color:#bb4444">❌ Abgelehnt</span>'; }
        });
}

function updateConfidence(sid, value) {
    fetch('/api/candidates/' + sid + '/confidence', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({confidence: parseInt(value)})});
}

function exportCandidates() {
    fetch('/api/candidates/export')
        .then(function(r) { return r.json(); })
        .then(function(d) { setStatus('💾 Export: ' + (d.path || 'Fehler')); });
}

try {
    startAutoRefresh();
    // Kleine Verzoegerung damit vis-network den Container korrekt misst
    setTimeout(function() {
        try {
            setStatus('⏳ Verbinde mit Datenbank...');
            loadGraph();
        } catch(e) {
            setStatus('❌ ' + e.message);
            console.error('loadGraph error:', e);
        }
    }, 500);
} catch(e) {
    document.getElementById('statusMsg').innerHTML = '❌ Init-Fehler: ' + e.message;
    console.error('Init error:', e);
}
</script>
</body>
</html>
"""


class Neo4jManager:
    """
    Verwaltet Neo4j-Installation, -Start und -Stopp.
    Automatischer Download der Community Edition für Windows.
    """
    
    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[Neo4j] {msg}"))
        self.neo4j_home = os.path.join(os.path.expanduser("~"), ".neo4j", "neo4j-community")
        self.install_path = None
        self._driver = None
        self.initialized = False
        
    def _detect_java(self) -> bool:
        """Prüft, ob Java 11+ installiert ist (Neo4j benötigt Java 11-17)."""
        java_home = os.environ.get("JAVA_HOME", "")
        if java_home:
            java_exe = os.path.join(java_home, "bin", "java.exe")
            if os.path.isfile(java_exe):
                try:
                    result = subprocess.run(
                        [java_exe, "-version"],
                        capture_output=True, text=True, timeout=10,
                        creationflags=0x08000000
                    )
                    output = (result.stderr + result.stdout).lower()
                    if any(version in output for version in ["11.", "12.", "13.", "14.", "15.", "16.", "17.", "18.", "19.", "20.", "21."]):
                        self.log(f"Java gefunden (JAVA_HOME): {java_home}", "SUCCESS")
                        return True
                except Exception:
                    pass
        
        try:
            result = subprocess.run(
                ["java", "-version"],
                capture_output=True, text=True, timeout=10,
                creationflags=0x08000000
            )
            output = (result.stderr + result.stdout).lower()
            self.log(f"Java Version erkannt: {output[:100]}", "INFO")
            
            if any(version in output for version in ["11.", "12.", "13.", "14.", "15.", "16.", "17.", "18.", "19.", "20.", "21."]):
                self.log("Java 11+ gefunden ✓", "SUCCESS")
                return True
            else:
                self.log(f"Java-Version zu alt: {output[:50]}", "WARNING")
                return False
        except FileNotFoundError:
            self.log("Java nicht im PATH gefunden", "WARNING")
            return False
        except Exception as e:
            self.log(f"Java-Erkennungsfehler: {e}", "WARNING")
            return False
    
    def _download_neo4j(self) -> bool:
        """Lädt Neo4j Community Edition herunter."""
        self.log("Lade Neo4j Community Edition herunter...")
        
        neo4j_version = "5.26.0"
        download_urls = [
            f"https://neo4j.com/artifact.php?name=neo4j-community-{neo4j_version}-windows.zip",
            f"https://dist.neo4j.org/neo4j-community-{neo4j_version}-windows.zip",
            f"https://github.com/neo4j/neo4j/releases/download/{neo4j_version}/neo4j-community-{neo4j_version}-windows.zip"
        ]
        
        zip_path = os.path.join(tempfile.gettempdir(), f"neo4j-{neo4j_version}.zip")
        
        for url in download_urls:
            try:
                self.log(f"Versuche: {url[:80]}...")
                urllib.request.urlretrieve(url, zip_path)
                self.log(f"Download abgeschlossen", "SUCCESS")
                break
            except Exception as e:
                self.log(f"Download fehlgeschlagen: {e}", "WARNING")
                continue
        else:
            self.log("Neo4j Download fehlgeschlagen!", "ERROR")
            return False
        
        os.makedirs(os.path.dirname(self.neo4j_home), exist_ok=True)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(os.path.dirname(self.neo4j_home))
            self.install_path = os.path.join(os.path.dirname(self.neo4j_home), f"neo4j-community-{neo4j_version}")
            self.log(f"Neo4j entpackt nach: {self.install_path}", "SUCCESS")
            os.remove(zip_path)
            return True
        except Exception as e:
            self.log(f"Entpacken fehlgeschlagen: {e}", "ERROR")
            return False
    
    def install(self) -> bool:
        """Installiert Neo4j falls nötig."""
        self.log("Neo4j Installation prüfen...")
        
        if not self._detect_java():
            self.log("Java 11+ wird benötigt. Bitte installieren: https://adoptium.net/", "ERROR")
            return False
        
        if self._check_neo4j_online():
            self.log("Neo4j läuft bereits (Port 7687 erreichbar)", "SUCCESS")
            if self._check_password():
                self.log("Neo4j Verbindung erfolgreich ✓", "SUCCESS")
                self.initialized = True
                return True
            else:
                self.log("Neo4j läuft aber Passwort ist falsch", "WARNING")
        
        if os.path.isdir(self.neo4j_home) and os.path.isfile(os.path.join(self.neo4j_home, "bin", "neo4j.bat")):
            self.install_path = self.neo4j_home
            self.log(f"Neo4j bereits vorhanden: {self.install_path}", "SUCCESS")
            return self.start()
        
        self.log("Neo4j nicht gefunden - starte Neuinstallation...", "INFO")
        if self._download_neo4j():
            self.neo4j_home = self.install_path
            return self.start()
        
        return False

    def _check_password(self) -> bool:
        """Prüft ob das Passwort korrekt ist."""
        try:
            from neo4j import GraphDatabase
            driver = GraphDatabase.driver(
                f"bolt://localhost:{NEO4J_PORT}",
                auth=(NEO4J_USER, NEO4J_PASSWORD)
            )
            driver.verify_connectivity()
            driver.close()
            return True
        except Exception as e:
            self.log(f"Passwortprüfung fehlgeschlagen: {e}", "INFO")
            return False
    
    def start(self) -> bool:
        """Startet Neo4j als Windows-Dienst (oder im Vordergrund)."""
        if not self.install_path:
            self.log("Neo4j nicht installiert!", "ERROR")
            return False
        
        bin_path = os.path.join(self.install_path, "bin", "neo4j.bat")
        if not os.path.isfile(bin_path):
            self.log(f"neo4j.bat nicht gefunden: {bin_path}", "ERROR")
            return False
        
        self.log("Starte Neo4j...")
        
        try:
            result = subprocess.run(
                [bin_path, "windows-service", "install"],
                capture_output=True, text=True, timeout=30,
                creationflags=0x08000000
            )
            if result.returncode == 0:
                self.log("Neo4j Dienst installiert", "SUCCESS")
            else:
                self.log(f"Dienst-Installation: {result.stderr[:100]}", "WARNING")
            
            subprocess.run(
                [bin_path, "start"],
                capture_output=True, text=True, timeout=60,
                creationflags=0x08000000
            )
            self.log("Neo4j Dienst gestartet", "SUCCESS")
            
            self.log("Warte auf Neo4j Start (max 60s)...")
            for i in range(60):
                time.sleep(1)
                if self._check_neo4j_online():
                    self.log(f"Neo4j online nach {i+1}s", "SUCCESS")
                    return self._update_password()
            
            self.log("Neo4j Start-Timeout", "WARNING")
            return False
            
        except Exception as e:
            self.log(f"Neo4j Start fehlgeschlagen: {e}", "ERROR")
            return False
    
    def _check_neo4j_online(self) -> bool:
        """Prüft ob Neo4j erreichbar ist."""
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', NEO4J_PORT))
            sock.close()
            return result == 0
        except:
            return False
    
    def _update_password(self) -> bool:
        """Setzt das Passwort für neo4j Benutzer."""
        try:
            from neo4j import GraphDatabase
            
            try:
                driver = GraphDatabase.driver(
                    f"bolt://localhost:{NEO4J_PORT}",
                    auth=(NEO4J_USER, NEO4J_PASSWORD)
                )
                driver.verify_connectivity()
                driver.close()
                self.log("Neo4j mit korrektem Passwort verbunden ✓", "SUCCESS")
                return True
            except Exception as e:
                self.log(f"Verbindung mit gespeichertem Passwort fehlgeschlagen", "INFO")
            
            try:
                driver = GraphDatabase.driver(
                    f"bolt://localhost:{NEO4J_PORT}",
                    auth=(NEO4J_USER, "neo4j")
                )
                driver.verify_connectivity()
                
                with driver.session(database="system") as session:
                    session.run(
                        f"ALTER CURRENT USER SET PASSWORD FROM 'neo4j' TO '{NEO4J_PASSWORD}'"
                    )
                driver.close()
                self.log("Neo4j Passwort aktualisiert (neo4j → lyra_network_2026) ✓", "SUCCESS")
                return True
                
            except Exception as inner_e:
                error_msg = str(inner_e).lower()
                if "credentials expired" in error_msg or "must be changed" in error_msg:
                    self.log("Passwort muss geändert werden, aber Verbindung mit Standard-Passwort fehlgeschlagen", "ERROR")
                    self.log("Bitte manuell in Neo4j Browser ändern:", "WARNING")
                    self.log("  http://localhost:7474", "WARNING")
                    self.log("  Login: neo4j / neo4j", "WARNING")
                    self.log("  Dann Passwort setzen auf: lyra_network_2026", "WARNING")
                else:
                    self.log(f"Passwort-Update fehlgeschlagen: {inner_e}", "WARNING")
                return False
                
        except Exception as e:
            self.log(f"Passwort-Update Ausnahme: {e}", "WARNING")
            return False
    
    def stop(self) -> bool:
        """Stoppt Neo4j."""
        if not self.install_path:
            return True
        
        bin_path = os.path.join(self.install_path, "bin", "neo4j.bat")
        try:
            subprocess.run(
                [bin_path, "stop"],
                capture_output=True, text=True, timeout=30,
                creationflags=0x08000000
            )
            self.log("Neo4j gestoppt", "INFO")
            return True
        except Exception as e:
            self.log(f"Neo4j Stop fehlgeschlagen: {e}", "WARNING")
            return False
    
    def get_driver(self):
        """Gibt einen Neo4j-Treiber zurück."""
        if self._driver is None:
            try:
                try:
                    self._driver = GraphDatabase.driver(
                        f"bolt://localhost:{NEO4J_PORT}",
                        auth=(NEO4J_USER, NEO4J_PASSWORD),
                        max_connection_pool_size=50,
                        notifications_min_severity="OFF"
                    )
                except TypeError:
                    # Aeltere Treiberversionen unterstuetzen notifications_min_severity nicht
                    self._driver = GraphDatabase.driver(
                        f"bolt://localhost:{NEO4J_PORT}",
                        auth=(NEO4J_USER, NEO4J_PASSWORD),
                        max_connection_pool_size=50
                    )
            except Exception as e:
                self.log(f"Treiber-Erstellung fehlgeschlagen: {e}", "ERROR")
                raise
        return self._driver
    
    def close(self):
        """Schließt den Neo4j-Treiber."""
        if self._driver:
            self._driver.close()
            self._driver = None
    
    def init_schema(self):
        """Initialisiert das Neo4j-Schema mit Constraints und Indizes."""
        driver = self.get_driver()
        try:
            with driver.session() as session:
                for statement in SCHEMA_CYPHER.split(";"):
                    if statement.strip():
                        session.run(statement)
            self.log("Neo4j Schema initialisiert ✓", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Schema-Initialisierung fehlgeschlagen: {e}", "WARNING")
            return False


class DataImporter:
    """
    Importiert ICIJ-Daten in Neo4j.
    Entity Resolution mit LLM-Unterstützung.
    Batch-Processing mit Checkpoints für grosse Dateien.
    """
    
    def __init__(self, neo4j_manager: Neo4jManager, log_fn=None):
        self.neo4j = neo4j_manager
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[Importer] {msg}"))
        self.driver = None

    def _find_column(self, header: list, candidates: list) -> int:
        """Findet eine Spalte anhand von Kandidaten (case-insensitive)."""
        header_lower = [h.lower() for h in header]
        for cand in candidates:
            cand_lower = cand.lower()
            if cand_lower in header_lower:
                return header_lower.index(cand_lower)
        return -1

    def _parse_csv_line(self, line: str) -> list:
        """Parst eine CSV-Zeile korrekt (mit Anführungszeichen)."""
        result = []
        current = []
        in_quotes = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"':
                if in_quotes and i + 1 < len(line) and line[i + 1] == '"':
                    current.append('"')
                    i += 1
                else:
                    in_quotes = not in_quotes
            elif ch == ',' and not in_quotes:
                result.append(''.join(current))
                current = []
            else:
                current.append(ch)
            i += 1
        result.append(''.join(current))
        return [r.strip() for r in result]

    def _clean_value(self, val: str) -> str:
        """Bereinigt einen CSV-Wert."""
        if not val:
            return ""
        val = val.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        return val

    def _normalize_rel_type(self, rel_type: str) -> str:
        """Normalisiert den Beziehungstyp."""
        rel_map = {
            'officer_of': 'OFFICER_OF',
            'officer': 'OFFICER_OF',
            'director': 'OFFICER_OF',
            'beneficial_owner': 'BENEFICIARY_OF',
            'shareholder': 'SHAREHOLDER_OF',
            'intermediary': 'INTERMEDIARY_OF',
            'intermediary_of': 'INTERMEDIARY_OF',
            'registered_address': 'REGISTERED_AT',
            'address': 'REGISTERED_AT',
            'same_address': 'REGISTERED_AT',
        }
        rel_lower = rel_type.lower().strip()
        return rel_map.get(rel_lower, 'RELATED_TO')

    def _execute_batch_node_insert(self, session, batch: list, label: str):
        """Führt einen Batch-Insert von Knoten durch."""
        if label == "Person":
            query = """
                UNWIND $nodes AS node
                MERGE (p:Person {id: node.id})
                SET p.name = node.name,
                    p.country = node.country,
                    p.subtype = node.subtype,
                    p.source = 'ICIJ'
                RETURN count(p)
            """
        elif label == "Entity":
            query = """
                UNWIND $nodes AS node
                MERGE (e:Entity {id: node.id})
                SET e.name = node.name,
                    e.country = node.country,
                    e.subtype = node.subtype,
                    e.source = 'ICIJ'
                RETURN count(e)
            """
        elif label == "Intermediary":
            query = """
                UNWIND $nodes AS node
                MERGE (i:Intermediary {id: node.id})
                SET i.name = node.name,
                    i.country = node.country,
                    i.source = 'ICIJ'
                RETURN count(i)
            """
        else:
            query = """
                UNWIND $nodes AS node
                MERGE (a:Address {id: node.id})
                SET a.full_address = node.name,
                    a.country = node.country
                RETURN count(a)
            """
        
        try:
            session.run(query, nodes=batch)
        except Exception as e:
            self.log(f"Batch-Node-Fehler: {e}", "WARNING")
            # Fallback: einzeln einfügen
            for node in batch:
                try:
                    if label == "Person":
                        session.run(
                            "MERGE (p:Person {id: $id}) SET p.name = $name, p.country = $country, p.source = 'ICIJ'",
                            id=node["id"], name=node["name"][:500], country=node["country"][:200]
                        )
                    elif label == "Entity":
                        session.run(
                            "MERGE (e:Entity {id: $id}) SET e.name = $name, e.country = $country, e.source = 'ICIJ'",
                            id=node["id"], name=node["name"][:500], country=node["country"][:200]
                        )
                    else:
                        session.run(
                            "MERGE (a:Address {id: $id}) SET a.full_address = $name",
                            id=node["id"], name=node["name"][:500]
                        )
                except Exception:
                    pass

    def _execute_batch_rel_insert(self, session, batch: list):
        """Führt einen Batch-Insert von Beziehungen durch.

        Performance-Hinweise
        --------------------
        * MATCH ohne Label erzwingt einen Full-Graph-Scan; deshalb suchen wir
          mit OPTIONAL MATCH über alle vier möglichen Node-Labels und nehmen
          den ersten Treffer (coalesce). So greifen die bestehenden id-Indizes.
        * rel_type wird als Relationship-Property gespeichert (nicht als
          dynamischer Relationship-Typ, da Cypher parametrisierte Typen nur
          via APOC unterstützt).
        * Zeilen, bei denen kein Start- oder Endknoten gefunden wird (WITH …
          WHERE a IS NOT NULL …), werden übersprungen statt einen Fehler zu
          werfen.
        """
        query = """
            UNWIND $rels AS rel
            OPTIONAL MATCH (pa:Person      {id: rel.from_id})
            OPTIONAL MATCH (ea:Entity      {id: rel.from_id})
            OPTIONAL MATCH (ia:Intermediary{id: rel.from_id})
            OPTIONAL MATCH (aa:Address     {id: rel.from_id})
            WITH rel,
                 coalesce(pa, ea, ia, aa) AS a
            WHERE a IS NOT NULL
            OPTIONAL MATCH (pb:Person      {id: rel.to_id})
            OPTIONAL MATCH (eb:Entity      {id: rel.to_id})
            OPTIONAL MATCH (ib:Intermediary{id: rel.to_id})
            OPTIONAL MATCH (ab:Address     {id: rel.to_id})
            WITH rel, a,
                 coalesce(pb, eb, ib, ab) AS b
            WHERE b IS NOT NULL
            MERGE (a)-[r:RELATED_TO]->(b)
            SET r.type   = rel.rel_type,
                r.source = 'ICIJ'
        """
        remapped = [
            {"from_id": rel["from"], "to_id": rel["to"], "rel_type": rel["type"]}
            for rel in batch
        ]
        try:
            session.run(query, rels=remapped)
        except Exception as e:
            self.log(f"Batch-Relationship-Fehler: {e}", "WARNING")
            for rel in batch:
                try:
                    session.run(
                        """
                        OPTIONAL MATCH (pa:Person      {id: $from_id})
                        OPTIONAL MATCH (ea:Entity      {id: $from_id})
                        OPTIONAL MATCH (ia:Intermediary{id: $from_id})
                        OPTIONAL MATCH (aa:Address     {id: $from_id})
                        WITH coalesce(pa, ea, ia, aa) AS a
                        WHERE a IS NOT NULL
                        OPTIONAL MATCH (pb:Person      {id: $to_id})
                        OPTIONAL MATCH (eb:Entity      {id: $to_id})
                        OPTIONAL MATCH (ib:Intermediary{id: $to_id})
                        OPTIONAL MATCH (ab:Address     {id: $to_id})
                        WITH a, coalesce(pb, eb, ib, ab) AS b
                        WHERE b IS NOT NULL
                        MERGE (a)-[r:RELATED_TO]->(b)
                        SET r.type = $rel_type, r.source = 'ICIJ'
                        """,
                        from_id=rel["from"],
                        to_id=rel["to"],
                        rel_type=rel["type"]
                    )
                except Exception:
                    pass

    def _import_node_csv_batched(self, csv_path: str, node_type: str, batch_size: int = 10000) -> int:
        """Importiert eine Knoten-CSV-Datei mit Batch-Transaktionen."""
        self.log(f"Importiere {node_type} aus {os.path.basename(csv_path)}...")
        
        label_mapping = {
            "entities": "Entity",
            "officers": "Person",
            "intermediaries": "Intermediary", 
            "addresses": "Address",
            "others": "Other"
        }
        label = label_mapping.get(node_type, "Node")
        
        count = 0
        batch_nodes = []
        
        try:
            with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                header = f.readline().strip().split(',')
                header = [h.strip().replace('\ufeff', '').strip('"') for h in header]
                
                id_col = self._find_column(header, ['node_id', 'id', '_id'])
                name_col = self._find_column(header, ['name', 'label', 'title', 'name_original', 'name_cleaned'])
                country_col = self._find_column(header, ['countries', 'country', 'jurisdiction', 'country_codes'])
                type_col = self._find_column(header, ['type', 'category', 'entity_type', 'status'])
                
                if id_col == -1:
                    self.log(f"  Keine ID-Spalte in {node_type} gefunden! Header: {header[:5]}", "ERROR")
                    return 0
                
                checkpoint_file = csv_path + ".checkpoint"
                start_line = 0
                if os.path.exists(checkpoint_file):
                    try:
                        with open(checkpoint_file, 'r') as cf:
                            start_line = int(cf.read().strip())
                        self.log(f"  Setze fort bei Zeile {start_line}", "INFO")
                        for _ in range(start_line):
                            f.readline()
                    except Exception:
                        pass
                
                with self.driver.session() as session:
                    for line_num, line in enumerate(f, start=start_line + 2):
                        parts = self._parse_csv_line(line)
                        n = len(parts)
                        # Skip short/malformed rows: must at least cover every
                        # column index that is actually used below.
                        required = id_col
                        if name_col >= 0:    required = max(required, name_col)
                        if country_col >= 0: required = max(required, country_col)
                        if type_col >= 0:    required = max(required, type_col)
                        if n <= required:
                            continue
                        
                        node_id = self._clean_value(parts[id_col])
                        name = self._clean_value(parts[name_col]) if name_col >= 0 else "Unbekannt"
                        country = self._clean_value(parts[country_col]) if country_col >= 0 else ""
                        node_subtype = self._clean_value(parts[type_col]) if type_col >= 0 else ""
                        
                        name = name[:500] if name else "Unbekannt"
                        
                        batch_nodes.append({
                            "id": node_id,
                            "name": name,
                            "country": country,
                            "subtype": node_subtype
                        })
                        
                        if len(batch_nodes) >= batch_size:
                            self._execute_batch_node_insert(session, batch_nodes, label)
                            count += len(batch_nodes)
                            self.log(f"     {count} {label} Knoten importiert...")
                            batch_nodes = []
                            
                            with open(checkpoint_file, 'w') as cf:
                                cf.write(str(line_num))
                            
                            if count % 100000 == 0 and count > 0:
                                time.sleep(1)
                                gc.collect()
                    
                    if batch_nodes:
                        self._execute_batch_node_insert(session, batch_nodes, label)
                        count += len(batch_nodes)
                
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)
                
                self.log(f"  {count} {label} Knoten importiert", "SUCCESS")
                return count
                
        except Exception as e:
            self.log(f"Import von {node_type} fehlgeschlagen bei Zeile {count}: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "DEBUG")
            return count

    def _import_relationships_batched(self, csv_path: str, batch_size: int = 20000) -> int:
        """Importiert Beziehungen mit Batch-Transaktionen."""
        self.log(f"Importiere Beziehungen aus {os.path.basename(csv_path)}...")
        
        count = 0
        batch_rels = []
        
        try:
            with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
                header = f.readline().strip().split(',')
                header = [h.strip().replace('\ufeff', '').strip('"') for h in header]
                
                from_col = self._find_column(header, ['node_id_start', 'start_id', 'from', 'source'])
                to_col = self._find_column(header, ['node_id_end', 'end_id', 'to', 'target'])
                rel_col = self._find_column(header, ['relationship', 'rel_type', 'type'])
                
                if from_col == -1 or to_col == -1:
                    self.log(f"  Keine FROM/TO-Spalten! Header: {header[:8]}", "ERROR")
                    return 0
                
                checkpoint_file = csv_path + ".rel_checkpoint"
                start_line = 0
                if os.path.exists(checkpoint_file):
                    try:
                        with open(checkpoint_file, 'r') as cf:
                            start_line = int(cf.read().strip())
                        self.log(f"  Setze Beziehungsimport fort bei Zeile {start_line}", "INFO")
                        for _ in range(start_line):
                            f.readline()
                    except Exception:
                        pass
                
                with self.driver.session() as session:
                    for line_num, line in enumerate(f, start=start_line + 2):
                        parts = self._parse_csv_line(line)
                        required = max(from_col, to_col)
                        if rel_col >= 0: required = max(required, rel_col)
                        if len(parts) <= required:
                            continue

                        from_id = self._clean_value(parts[from_col])
                        to_id = self._clean_value(parts[to_col])
                        rel_type_raw = self._clean_value(parts[rel_col]) if rel_col >= 0 else "RELATED_TO"
                        
                        rel_type = self._normalize_rel_type(rel_type_raw)
                        
                        # Store with safe key names (no Python keywords)
                        batch_rels.append({
                            "from": from_id,
                            "to": to_id,
                            "type": rel_type
                        })
                        
                        if len(batch_rels) >= batch_size:
                            self._execute_batch_rel_insert(session, batch_rels)
                            count += len(batch_rels)
                            self.log(f"     {count} Beziehungen importiert...")
                            batch_rels = []
                            
                            with open(checkpoint_file, 'w') as cf:
                                cf.write(str(line_num))
                            
                            if count % 200000 == 0 and count > 0:
                                time.sleep(2)
                                gc.collect()
                    
                    if batch_rels:
                        self._execute_batch_rel_insert(session, batch_rels)
                        count += len(batch_rels)
                
                if os.path.exists(checkpoint_file):
                    os.remove(checkpoint_file)
                
                self.log(f"  {count} Beziehungen importiert", "SUCCESS")
                return count
                
        except Exception as e:
            self.log(f"Beziehungs-Import fehlgeschlagen: {e}", "ERROR")
            return count

    def import_icij_zip(self) -> bool:
        """Importiert die ICIJ-Daten aus der aktuellen ZIP-Datei mit Batch-Processing."""
        self.log("Starte Import der ICIJ Offshore Leaks Daten...")
        
        dataset = DATASETS["offshore_leaks"]
        zip_url = dataset["url"]
        
        zip_path = os.path.join(tempfile.gettempdir(), "icij_offshoreleaks.zip")
        extract_path = os.path.join(tempfile.gettempdir(), "icij_offshoreleaks_extracted")
        
        self.log(f"Lade Daten herunter: {zip_url}")
        try:
            urllib.request.urlretrieve(zip_url, zip_path)
            self.log("Download abgeschlossen", "SUCCESS")
        except Exception as e:
            self.log(f"Download fehlgeschlagen: {e}", "ERROR")
            return False
        
        self.log("Entpacke ZIP-Datei...")
        try:
            if os.path.exists(extract_path):
                shutil.rmtree(extract_path)
            os.makedirs(extract_path, exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_path)
            self.log("Entpacken abgeschlossen", "SUCCESS")
        except Exception as e:
            self.log(f"Entpacken fehlgeschlagen: {e}", "ERROR")
            return False
        
        self.driver = self.neo4j.get_driver()
        
        node_files = ["entities", "officers", "intermediaries", "addresses", "others"]
        total_nodes = 0
        
        for node_type in node_files:
            if node_type in dataset["files"]:
                csv_path = os.path.join(extract_path, dataset["files"][node_type])
                if os.path.isfile(csv_path):
                    imported = self._import_node_csv_batched(csv_path, node_type)
                    total_nodes += imported
        
        rel_path = os.path.join(extract_path, dataset["files"]["relationships"])
        total_rels = 0
        if os.path.isfile(rel_path):
            total_rels = self._import_relationships_batched(rel_path)
        
        try:
            os.remove(zip_path)
            shutil.rmtree(extract_path)
        except Exception:
            pass
        
        self.log(f"ICIJ Datenimport abgeschlossen! {total_nodes} Knoten, {total_rels} Beziehungen", "SUCCESS")
        return True

    def import_all_datasets(self) -> bool:
        """Importiert alle verfügbaren ICIJ-Datensätze (für Kompatibilität)."""
        self.log("Starte Import aller ICIJ-Datensätze...")
        
        self.driver = self.neo4j.get_driver()
        
        total_nodes = 0
        total_edges = 0
        
        for dataset_name, dataset_info in DATASETS.items():
            if dataset_name == "offshore_leaks":
                continue
                
            self.log(f"\n--- Importiere {dataset_info['description']} ---")
            
            nodes_path = self._download_dataset(f"{dataset_name}_nodes", dataset_info["url"])
            if nodes_path:
                nodes_imported = self._import_nodes_fallback(nodes_path, dataset_name)
                total_nodes += nodes_imported
                self.log(f"  {nodes_imported} Knoten importiert", "SUCCESS")
            
            edges_path = self._download_dataset(f"{dataset_name}_edges", dataset_info["edges_url"])
            if edges_path:
                edges_imported = self._import_edges_fallback(edges_path, dataset_name)
                total_edges += edges_imported
                self.log(f"  {edges_imported} Kanten importiert", "SUCCESS")
        
        self.log(f"\n📊 Import abgeschlossen: {total_nodes} Knoten, {total_edges} Kanten", "SUCCESS")
        return True
    
    def _download_dataset(self, name: str, url: str) -> Optional[str]:
        """Lädt einen Datensatz herunter."""
        self.log(f"Lade {name} herunter: {url[:80]}...")
        
        temp_dir = os.path.join(tempfile.gettempdir(), "lyra_network_data")
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"{name}.csv")
        
        try:
            urllib.request.urlretrieve(url, file_path)
            self.log(f"Download abgeschlossen: {file_path}", "SUCCESS")
            return file_path
        except Exception as e:
            self.log(f"Download fehlgeschlagen: {e}", "WARNING")
            return None
    
    def _import_nodes_fallback(self, file_path: str, source: str) -> int:
        """Fallback-Import ohne pandas (mit Batch)."""
        count = 0
        batch_nodes = []
        batch_size = 5000
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                header = f.readline().strip().split(',')
                header = [h.strip().replace('\ufeff', '') for h in header]
                id_col = self._find_column(header, ['node_id', 'id'])
                name_col = self._find_column(header, ['name', 'label', 'title'])
                country_col = self._find_column(header, ['countries', 'jurisdiction', 'country'])
                
                if id_col == -1:
                    self.log(f"  Keine ID-Spalte in {source} gefunden", "WARNING")
                    return 0
                
                with self.driver.session() as session:
                    for line in f:
                        parts = self._parse_csv_line(line)
                        n = len(parts)
                        required = id_col
                        if name_col >= 0:    required = max(required, name_col)
                        if country_col >= 0: required = max(required, country_col)
                        if n <= required:
                            continue
                        
                        node_id = self._clean_value(parts[id_col])
                        name = self._clean_value(parts[name_col]) if name_col >= 0 else "Unbekannt"
                        country = self._clean_value(parts[country_col]) if country_col >= 0 else ""
                        
                        node_type = self._determine_node_type_by_name(name)
                        
                        batch_nodes.append({
                            "id": node_id,
                            "name": name[:500],
                            "country": country[:200]
                        })
                        
                        if len(batch_nodes) >= batch_size:
                            label = "Person" if node_type == 'Person' else "Entity"
                            self._execute_batch_node_insert(session, batch_nodes, label)
                            count += len(batch_nodes)
                            batch_nodes = []
                    
                    if batch_nodes:
                        label = "Person" if self._determine_node_type_by_name(batch_nodes[0]["name"]) == 'Person' else "Entity"
                        self._execute_batch_node_insert(session, batch_nodes, label)
                        count += len(batch_nodes)
            
            return count
        except Exception as e:
            self.log(f"Fallback-Import fehlgeschlagen: {e}", "ERROR")
            return 0
    
    def _import_edges_fallback(self, file_path: str, source: str) -> int:
        """Fallback-Import für Kanten ohne pandas (mit Batch)."""
        count = 0
        batch_rels = []
        batch_size = 10000
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                header = f.readline().strip().split(',')
                header = [h.strip().replace('\ufeff', '') for h in header]
                from_col = self._find_column(header, ['node_id_start', 'from', 'source'])
                to_col = self._find_column(header, ['node_id_end', 'to', 'target'])
                
                if from_col == -1 or to_col == -1:
                    self.log(f"  Keine FROM/TO-Spalten in {source}", "WARNING")
                    return 0
                
                with self.driver.session() as session:
                    for line in f:
                        parts = self._parse_csv_line(line)
                        if len(parts) <= max(from_col, to_col):
                            continue
                        
                        from_id = self._clean_value(parts[from_col])
                        to_id = self._clean_value(parts[to_col])
                        
                        # Store with safe key names (no Python keywords)
                        batch_rels.append({
                            "from": from_id,
                            "to": to_id,
                            "type": "RELATED_TO"
                        })
                        
                        if len(batch_rels) >= batch_size:
                            self._execute_batch_rel_insert(session, batch_rels)
                            count += len(batch_rels)
                            batch_rels = []
                    
                    if batch_rels:
                        self._execute_batch_rel_insert(session, batch_rels)
                        count += len(batch_rels)
            
            return count
        except Exception as e:
            self.log(f"Fallback-Edge-Import fehlgeschlagen: {e}", "ERROR")
            return 0
    
    def _determine_node_type_by_name(self, name: str) -> str:
        """Bestimmt den Knotentyp anhand des Namens (Fallback)."""
        name_lower = name.lower()
        if any(term in name_lower for term in ['ltd', 'limited', 'inc', 'corp', 'gmbh', 'ag', 'holding', 'offshore']):
            return 'Entity'
        elif any(term in name_lower for term in ['law', 'legal', 'trust', 'fiduciary', 'agent']):
            return 'Intermediary'
        elif any(term in name_lower for term in ['mr.', 'ms.', 'mrs.', 'dr.', 'prof.']) or (' ' in name and len(name) < 50):
            return 'Person'
        elif 'address' in name_lower or 'street' in name_lower or 'road' in name_lower:
            return 'Address'
        else:
            return 'Entity'


class AIGraphEnhancer:
    """
    KI-gestützte Graph-Erweiterung.
    Nutzt Ollama + SearXNG für autonome Recherche.
    """
    
    def __init__(self, neo4j_manager: Neo4jManager, log_fn=None, worker_client=None):
        self.neo4j = neo4j_manager
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[AIEnhancer] {msg}"))
        self.worker_client = worker_client
        self.running = False
        self.thread = None
        self._stop = threading.Event()
    
    def _get_ollama_model(self) -> str:
        """Liest Ollama-Modell aus openclaw.json oder gibt Default zurueck."""
        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            model = cfg.get("ollama", {}).get("model", "") or cfg.get("model", "")
            if model:
                return model
        except Exception:
            pass
        return "glm-4.7-flash"  # Fallback

    def _query_ollama(self, prompt: str, system_prompt: str = "") -> str:
        """Fragt Ollama-Modell an via curl subprocess (kein GIL-Blocking)."""
        import subprocess, tempfile, shutil
        try:
            payload = {
                "model": self._get_ollama_model(),
                "messages": [],
                "stream": False
            }
            if system_prompt:
                payload["messages"].append({"role": "system", "content": system_prompt})
            payload["messages"].append({"role": "user", "content": prompt})

            payload_str = json.dumps(payload, ensure_ascii=False)

            # curl via stdin statt -d Argument – vermeidet Shell-Encoding-Probleme mit Umlauten
            result = subprocess.run(
                ["curl", "-s", "-X", "POST",
                 "http://127.0.0.1:11434/api/chat",
                 "-H", "Content-Type: application/json",
                 "--data-binary", "@-",
                 "--max-time", "600"],
                input=payload_str,
                capture_output=True, encoding="utf-8", errors="replace", timeout=620
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                return data.get("message", {}).get("content", "")
            else:
                # Fallback: requests (falls curl nicht verfügbar)
                import requests as _req
                r = _req.post("http://127.0.0.1:11434/api/chat",
                              json=payload, timeout=600)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "")
                self.log(f"Ollama Fehler: {r.status_code}", "WARNING")
                return ""
        except Exception as e:
            self.log(f"Ollama-Anfrage fehlgeschlagen: {e}", "WARNING")
            return ""
        except Exception as e:
            self.log(f"Ollama-Anfrage fehlgeschlagen: {e}", "WARNING")
            return ""
    
    def _search_web(self, query: str) -> List[Dict]:
        """Führt eine Websuche über SearXNG oder Worker durch."""
        if self.worker_client and hasattr(self.worker_client, 'head_address'):
            self.log(f"Delegiere Suche an Worker: {query}")
            return []
        
        try:
            searxng_url = "http://127.0.0.1:8080/search"
            params = {
                "q": query,
                "format": "json",
                "language": "de"
            }
            response = requests.get(searxng_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get("results", [])[:5]
        except Exception as e:
            self.log(f"SearXNG-Anfrage fehlgeschlagen: {e}", "WARNING")
        return []
    
    def _find_missing_connections(self) -> List[Tuple[str, str, str]]:
        """Identifiziert fehlende Verbindungen im Graph.

        Alle Beziehungen liegen als RELATED_TO mit r.type-Property vor
        (kein separater Relationship-Typ OFFICER_OF / REGISTERED_AT).
        Die Queries filtern deshalb ueber r.type statt ueber den Typ-Namen.
        """
        driver = self.neo4j.get_driver()
        suggestions = []

        try:
            with driver.session() as session:
                # Personen, die ueber dieselbe Adresse verbunden sind
                result = session.run(
                    """
                    MATCH (p1:Person)-[r1:RELATED_TO]->(a:Address)
                    WHERE r1.type IN ['REGISTERED_AT', 'registered_address', 'address']
                      AND a.full_address IS NOT NULL
                      AND trim(a.full_address) <> ''
                      AND toLower(trim(a.full_address)) <> 'unbekannt'
                    MATCH (p2:Person)-[r2:RELATED_TO]->(a)
                    WHERE r2.type IN ['REGISTERED_AT', 'registered_address', 'address']
                      AND p1.id < p2.id
                      AND NOT (p1)-[:RELATED_TO]-(p2)
                      AND NOT (p1)-[:SUGGESTED_CONNECTION]-(p2)
                      AND NOT (p1)-[:REJECTED_CONNECTION]-(p2)
                    RETURN p1.name AS person1, p2.name AS person2,
                           a.full_address AS address
                    LIMIT 100
                    """
                )
                for record in result:
                    addr = (record['address'] or '').strip()
                    if not addr or addr.lower() == 'unbekannt':
                        continue
                    suggestions.append((
                        record["person1"] or "?",
                        record["person2"] or "?",
                        f"Gleiche Adresse: {addr[:100]}"
                    ))

                # Personen, die dieselbe Firma als Officer teilen
                result = session.run(
                    """
                    MATCH (p1:Person)-[r1:RELATED_TO]->(e:Entity)
                    WHERE r1.type IN ['OFFICER_OF', 'officer_of', 'officer', 'director',
                                      'BENEFICIARY_OF', 'SHAREHOLDER_OF']
                      AND e.name IS NOT NULL
                      AND trim(e.name) <> ''
                      AND p1.name IS NOT NULL AND trim(p1.name) <> ''
                    MATCH (p2:Person)-[r2:RELATED_TO]->(e)
                    WHERE r2.type IN ['OFFICER_OF', 'officer_of', 'officer', 'director',
                                      'BENEFICIARY_OF', 'SHAREHOLDER_OF']
                      AND p2.name IS NOT NULL AND trim(p2.name) <> ''
                      AND p1.id < p2.id
                      AND NOT (p1)-[:RELATED_TO]-(p2)
                      AND NOT (p1)-[:SUGGESTED_CONNECTION]-(p2)
                      AND NOT (p1)-[:REJECTED_CONNECTION]-(p2)
                    RETURN p1.name AS person1, p2.name AS person2,
                           e.name AS entity, e.country AS country
                    LIMIT 100
                    """
                )
                for record in result:
                    entity = (record['entity'] or '').strip()
                    if not entity:
                        continue
                    country = f" ({record['country']})" if record.get('country') else ""
                    suggestions.append((
                        record["person1"] or "?",
                        record["person2"] or "?",
                        f"Gemeinsame Firma: {entity[:80]}{country}"
                    ))

        except Exception as e:
            self.log(f"Fehlende Verbindungen suchen fehlgeschlagen: {e}", "WARNING")
        
        return suggestions
    
    def _enhance_with_llm(self, suggestion: Tuple[str, str, str]) -> Optional[Dict]:
        """Nutzt LLM zur Überprüfung einer Verbindung."""
        person1, person2, reason = suggestion
        
        prompt = f"""
Analysiere die folgende potenzielle Verbindung zwischen zwei Personen aus den Offshore-Leaks:

Person A: {person1}
Person B: {person2}
Hinweis: {reason}

Aufgabe:
1. Bewerte die Wahrscheinlichkeit einer echten Verbindung (0-100%).
2. Gib eine kurze Begründung.

Antwortformat (JSON):
{{
    "connected": true/false,
    "confidence": 0-100,
    "reason": "Deine Begründung hier",
    "relationship_type": "BUSINESS_PARTNER/FAMILY/ASSOCIATE/UNKNOWN"
}}
"""
        
        response = self._query_ollama(prompt)
        if not response:
            return None
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return result
        except json.JSONDecodeError:
            pass
        
        return None
    
    def _suggest_entities_from_search(self) -> List[Dict]:
        """Schlaegt Offshore-Entitaeten ohne bekannte Officer vor.

        Da alle Beziehungen als RELATED_TO mit r.type-Property gespeichert
        sind, pruefen wir auf das Fehlen einer RELATED_TO-Kante mit dem
        passenden type-Wert statt auf einen nicht-existenten Typ OFFICER_OF.
        """
        driver = self.neo4j.get_driver()
        suggestions = []

        OFFSHORE_COUNTRIES = [
            'Panama', 'British Virgin Islands', 'Cayman Islands', 'Seychelles',
            'Bermuda', 'Bahamas', 'Jersey', 'Guernsey', 'Isle of Man',
            'Marshall Islands', 'Samoa', 'Vanuatu'
        ]

        try:
            with driver.session() as session:
                result = session.run(
                    """
                    MATCH (e:Entity)
                    WHERE e.country IN $countries
                      AND NOT EXISTS {
                          MATCH (p)-[r:RELATED_TO]->(e)
                          WHERE r.type IN ['OFFICER_OF', 'officer_of', 'officer',
                                           'director', 'BENEFICIARY_OF', 'SHAREHOLDER_OF']
                      }
                    WITH e, rand() AS r
                    ORDER BY r
                    RETURN e.name AS entity, e.country AS country
                    LIMIT 20
                    """,
                    countries=OFFSHORE_COUNTRIES
                )
                for record in result:
                    entity_name = record["entity"]
                    if entity_name and len(entity_name) > 3:
                        suggestions.append({
                            "entity":         entity_name[:100],
                            "country":        record["country"] or "?",
                            "search_results": []
                        })
        except Exception as e:
            self.log(f"Entity-Vorschlaege suchen fehlgeschlagen: {e}", "WARNING")

        return suggestions
    
    def start_background_loop(self, interval_seconds: int = 300):
        """Startet Hintergrundlopp für kontinuierliche Verbesserung."""
        if self.running:
            self.log("AI Enhancer läuft bereits", "WARNING")
            return
        
        self.running = True
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, args=(interval_seconds,), daemon=True)
        self.thread.start()
        self.log(f"AI Enhancer gestartet (Intervall: {interval_seconds}s)", "SUCCESS")
    
    def _save_suggested_connection(self, person1_id: str, person2_id: str,
                                       person1_name: str, person2_name: str,
                                       reason: str, confidence: int,
                                       rel_type: str = "UNKNOWN") -> Optional[str]:
        """Speichert eine vorgeschlagene Verbindung als SUGGESTED_CONNECTION in Neo4j.

        Gibt die generierte ID zurueck oder None bei Fehler.
        Bereits vorhandene oder abgelehnte Verbindungen werden uebersprungen.
        """
        import uuid
        suggestion_id = str(uuid.uuid4())
        driver = self.neo4j.get_driver()
        try:
            with driver.session() as session:
                # Pruefen ob bereits vorhanden (SUGGESTED oder REJECTED)
                existing = session.run(
                    """
                    MATCH (p1 {id: $id1})-[r:SUGGESTED_CONNECTION|REJECTED_CONNECTION]-(p2 {id: $id2})
                    RETURN count(r) AS cnt
                    """,
                    id1=person1_id, id2=person2_id
                ).single()
                if existing and existing["cnt"] > 0:
                    return None  # bereits vorhanden

                session.run(
                    """
                    MATCH (p1 {id: $id1}), (p2 {id: $id2})
                    MERGE (p1)-[r:SUGGESTED_CONNECTION {id: $sid}]->(p2)
                    SET r.person1       = $p1name,
                        r.person2       = $p2name,
                        r.reason        = $reason,
                        r.confidence    = $confidence,
                        r.relationship_type = $rel_type,
                        r.validated     = false,
                        r.rejected      = false,
                        r.suggested_at  = datetime(),
                        r.source        = 'ai_enhancer'
                    """,
                    id1=person1_id, id2=person2_id,
                    sid=suggestion_id,
                    p1name=person1_name[:200],
                    p2name=person2_name[:200],
                    reason=reason[:500],
                    confidence=confidence,
                    rel_type=rel_type
                )
            return suggestion_id
        except Exception as e:
            self.log(f"_save_suggested_connection Fehler: {e}", "WARNING")
            return None

    def _get_node_ids_for_names(self, name1: str, name2: str) -> tuple:
        """Gibt (id1, id2) fuer zwei Personennamen zurueck."""
        driver = self.neo4j.get_driver()
        try:
            with driver.session() as session:
                r1 = session.run(
                    "MATCH (n {name: $name}) RETURN n.id AS nid LIMIT 1",
                    name=name1
                ).single()
                r2 = session.run(
                    "MATCH (n {name: $name}) RETURN n.id AS nid LIMIT 1",
                    name=name2
                ).single()
                id1 = r1["nid"] if r1 else None
                id2 = r2["nid"] if r2 else None
                return id1, id2
        except Exception:
            return None, None

    def _loop(self, interval: int):
        """Hauptloop des AI Enhancers."""
        self.log("AI Enhancer Loop gestartet")

        while not self._stop.is_set():
            try:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                self.log(f"── AI Enhancer Durchlauf [{ts}] ──────────────────────────")

                # ── 1. Fehlende Verbindungen suchen ───────────────────────
                missing = self._find_missing_connections()
                if missing:
                    self.log(f"Potenzielle Verbindungen: {len(missing)}")
                    for i, (p1, p2, reason) in enumerate(missing[:10], 1):
                        self.log(f"  [{i:2d}] {p1[:40]} ↔ {p2[:40]}")
                        self.log(f"       Grund: {reason[:80]}")

                    # Alle Kandidaten speichern + LLM-Validierung
                    saved = 0
                    validated = 0
                    for suggestion in missing:
                        p1_name, p2_name, reason = suggestion
                        id1, id2 = self._get_node_ids_for_names(p1_name, p2_name)
                        if not id1 or not id2:
                            continue

                        # LLM-Validierung (Ollama)
                        confidence = 0
                        rel_type   = "UNKNOWN"
                        llm_result = self._enhance_with_llm(suggestion)
                        if llm_result:
                            confidence = llm_result.get("confidence", 0)
                            rel_type   = llm_result.get("relationship_type", "UNKNOWN")
                        else:
                            # Ollama nicht erreichbar – DeepSeek-Fallback
                            ds_result = self._query_deepseek_fallback(suggestion)
                            if ds_result:
                                confidence = ds_result.get("confidence", 0)
                                rel_type   = ds_result.get("relationship_type", "UNKNOWN")

                        # Immer speichern (Confidence=0 wenn kein LLM)
                        sid = self._save_suggested_connection(
                            id1, id2, p1_name, p2_name, reason, confidence, rel_type
                        )
                        if sid:
                            saved += 1

                        # Sofort als bestätigt übernehmen wenn Confidence > 70
                        if confidence > 70 and llm_result:
                            self._add_connection(p1_name, p2_name, llm_result)
                            validated += 1
                            self.log(
                                f"  ✅ Validiert ({confidence}%): "
                                f"{p1_name[:30]} ↔ {p2_name[:30]} [{rel_type}]",
                                "SUCCESS"
                            )

                    self.log(f"  {saved} Kandidaten gespeichert, {validated} direkt validiert")
                else:
                    self.log("Keine potenziellen Verbindungen gefunden")

                # ── 2. Offshore-Entitaeten ohne bekannte Officer ───────────
                new_entities = self._suggest_entities_from_search()
                if new_entities:
                    self.log(f"Offshore-Entitaeten ohne Officer: {len(new_entities)}")
                    for i, e in enumerate(new_entities[:10], 1):
                        self.log(f"  [{i:2d}] {e['entity'][:50]} ({e['country']})")
                else:
                    self.log("Alle Offshore-Entitaeten haben bekannte Officer")


                # ── 3. Cleanup alter Kandidaten (> 90 Tage) ──────────────
                try:
                    driver = self.neo4j.get_driver()
                    with driver.session() as session:
                        rec = session.run(
                            """
                            MATCH ()-[r:SUGGESTED_CONNECTION]->()
                            WHERE r.suggested_at < datetime() - duration({days: 90})
                              AND r.validated = false AND r.rejected = false
                            WITH r LIMIT 1000
                            DELETE r
                            RETURN count(r) AS deleted
                            """
                        ).single()
                        deleted = rec["deleted"] if rec else 0
                        if deleted > 0:
                            self.log(f"  Cleanup: {deleted} Kandidaten > 90 Tage geloescht")
                except Exception as cleanup_err:
                    self.log(f"Cleanup (nicht kritisch): {cleanup_err}", "WARNING")

                self.log(f"── Naechster Durchlauf in {interval}s ──────────────────────")

                for _ in range(interval):
                    if self._stop.is_set():
                        break
                    time.sleep(1)

            except Exception as e:
                self.log(f"Loop-Fehler: {e}", "WARNING")
                time.sleep(60)

        self.log("AI Enhancer Loop gestoppt")
    
    def _add_connection(self, person1: str, person2: str, result: Dict):
        """Fügt eine validierte Verbindung zum Graph hinzu."""
        driver = self.neo4j.get_driver()
        try:
            with driver.session() as session:
                session.run(
                    """
                    MATCH (p1:Person {name: $p1}), (p2:Person {name: $p2})
                    MERGE (p1)-[r:RELATED_TO {type: $rel_type, confidence: $confidence, reason: $reason}]->(p2)
                    SET r.ai_discovered = true, r.discovered_at = datetime()
                    """,
                    p1=person1,
                    p2=person2,
                    rel_type=result.get("relationship_type", "ASSOCIATE"),
                    confidence=result.get("confidence", 50),
                    reason=result.get("reason", "KI-gestützte Verbindung")[:500]
                )
            
            self.log(f"Verbindung hinzugefügt: {person1} – {person2}", "SUCCESS")
        except Exception as e:
            self.log(f"Verbindung hinzufügen fehlgeschlagen: {e}", "WARNING")
    
    def _query_deepseek_fallback(self, suggestion: tuple) -> Optional[Dict]:
        """DeepSeek-API als Fallback wenn Ollama nicht antwortet.

        Liest API-Key aus workers.json. Rate-Limit: 10 Calls/Tag.
        """
        # Rate-Limiting pruefen
        today = time.strftime("%Y-%m-%d")
        if not hasattr(self, '_ds_calls'):
            self._ds_calls = {}
        calls_today = self._ds_calls.get(today, 0)
        if calls_today >= 10:
            self.log("DeepSeek Rate-Limit erreicht (10/Tag)", "WARNING")
            return None

        # API-Key lesen
        api_key = None
        for path in [
            os.path.join(os.path.expanduser("~"), ".openclaw", "workers.json"),
            os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json"),
        ]:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                api_key = (cfg.get("deepseek", {}).get("api_key") or
                           cfg.get("deepseek_api_key") or
                           cfg.get("api_keys", {}).get("deepseek"))
                if api_key:
                    break
            except Exception:
                continue

        # Fallback: Umgebungsvariable DEEPSEEK_API_KEY
        if not api_key:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return None  # kein Key konfiguriert – kein Fehler

        person1, person2, reason = suggestion
        prompt = f"""Analysiere diese potenzielle Verbindung aus Offshore-Leaks-Daten:
Person A: {person1}
Person B: {person2}
Hinweis: {reason}

Antworte NUR als JSON (kein Markdown):
{"connected": true/false, "confidence": 0-100, "reason": "kurze Begruendung", "relationship_type": "BUSINESS_PARTNER/FAMILY/ASSOCIATE/UNKNOWN"}"""

        try:
            response = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.1
                },
                timeout=30
            )
            if response.status_code == 200:
                self._ds_calls[today] = calls_today + 1
                text = response.json()["choices"][0]["message"]["content"]
                json_match = re.search(r'\{.*\}', text, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            else:
                self.log(f"DeepSeek API-Fehler: {response.status_code}", "WARNING")
        except Exception as e:
            self.log(f"DeepSeek-Anfrage fehlgeschlagen: {e}", "WARNING")
        return None

    def export_candidates_json(self, output_path: str = None) -> str:
        """Exportiert alle Kandidaten als JSON fuer Backup/Weitergabe."""
        if not output_path:
            output_path = os.path.join(
                os.path.expanduser("~"),
                f"lyra_candidates_{time.strftime('%Y%m%d_%H%M%S')}.json"
            )
        driver = self.neo4j.get_driver()
        candidates = []
        try:
            with driver.session() as session:
                res = session.run(
                    """
                    MATCH (p1)-[r:SUGGESTED_CONNECTION]->(p2)
                    RETURN r.id AS id, r.person1 AS person1, r.person2 AS person2,
                           r.reason AS reason, r.confidence AS confidence,
                           r.relationship_type AS rel_type,
                           r.validated AS validated, r.rejected AS rejected,
                           toString(r.suggested_at) AS suggested_at
                    ORDER BY r.confidence DESC
                    """
                )
                for rec in res:
                    candidates.append(dict(rec))
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump({"candidates": candidates,
                           "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "total": len(candidates)}, f, ensure_ascii=False, indent=2)
            self.log(f"Kandidaten exportiert: {output_path} ({len(candidates)} Eintraege)", "SUCCESS")
            return output_path
        except Exception as e:
            self.log(f"Export fehlgeschlagen: {e}", "ERROR")
            return ""

    def stop(self):
        """Stoppt den Hintergrundloop."""
        self.running = False
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=10)




# ══════════════════════════════════════════════════════════════════════════════
# RESEARCH AGENT – Autonomer Hintergrund-Recherche-Agent (Option C)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Hypothesis:
    """Einzelne Hypothese mit Metadaten."""
    id: str
    text: str
    priority: int = 1
    status: str = "pending"   # pending | active | done | failed
    confidence: Optional[int] = None
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    findings_count: int = 0
    is_seed: bool = False
    parent_id: Optional[str] = None


@dataclass
class ActivityEntry:
    """Eintrag im Aktivitäts-Log."""
    time: str
    message: str
    breakthrough: bool = False


class ResearchAgent:
    """
    Autonomer Research-Agent – läuft als Background-Thread in LYRA.
    Generiert Hypothesen aus Seed-Fragen, recherchiert autonom über
    Neo4j-Graph + SearXNG + LLM und schreibt lebende Dossiers.
    
    Steuerung via /api/research/... Endpunkte im WebServer.
    """

    # Vorschläge für die Web-UI – werden NICHT automatisch gestartet.
    # Nur angezeigt wenn der Benutzer im Research-Tab auf einen Vorschlag klickt.
    DEFAULT_HYPOTHESES = [
        "Warum ist der US-Dollar trotz 31 Billionen Schulden nicht zusammengebrochen?",
        "Welche Personen und Netzwerke kontrollieren die globale Energieversorgung?",
        "Wie sind die größten Tech-Konzerne mit Offshore-Strukturen verbunden?",
    ]

    def __init__(self, neo4j_manager, ai_enhancer, log_fn=None):
        self.neo4j       = neo4j_manager
        self.ai_enhancer = ai_enhancer
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[ResearchAgent] {msg}"))

        self.running  = False
        self.thread   = None
        self._stop    = threading.Event()
        self._lock    = threading.RLock()
        self._new_work = threading.Event()

        self.hypotheses: List[Hypothesis] = []
        self.activity:   List[ActivityEntry] = []
        self._done_since_last_trigger: int = 0  # Zähler seit letztem Trigger
        self.queue_limit: int = 30  # Max pending auto-Hypothesen (0 = unbegrenzt)

        self.dossiers_dir = os.path.join(
            os.path.expanduser("~"), ".openclaw", "workspace", "dossiers"
        )
        os.makedirs(self.dossiers_dir, exist_ok=True)

        # Option C: Queue-Persistenz
        self.queue_path = os.path.join(
            os.path.expanduser("~"), ".openclaw", "workspace", "research_queue.json"
        )
        self._last_save = 0  # Timestamp letzter Auto-Save

    # ── Queue-Persistenz ──────────────────────────────────────────────────────

    def save_queue(self):
        """Speichert aktuelle Queue in research_queue.json."""
        try:
            with self._lock:
                data = {
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "done_since_last_trigger": self._done_since_last_trigger,
                    "hypotheses": [
                        {
                            "id":            h.id,
                            "text":          h.text,
                            "priority":      h.priority,
                            "status":        "pending" if h.status == "active" else h.status,
                            "confidence":    h.confidence,
                            "findings_count": h.findings_count,
                            "is_seed":       h.is_seed,
                            "parent_id":     h.parent_id,
                            "created_at":    h.created_at,
                            "updated_at":    h.updated_at,
                        }
                        for h in self.hypotheses
                    ]
                }
            os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
            with open(self.queue_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._last_save = time.time()
        except Exception as e:
            self.log(f"Queue-Save Fehler: {e}", "WARNING")

    def load_queue(self) -> bool:
        """Lädt gespeicherte Queue – gibt True zurück wenn Hypothesen geladen wurden."""
        if not os.path.isfile(self.queue_path):
            return False
        try:
            with open(self.queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            hypotheses = data.get("hypotheses", [])
            if not hypotheses:
                return False
            loaded_pending = 0
            loaded_done    = 0
            with self._lock:
                for hd in hypotheses:
                    status = hd.get("status", "pending")
                    # Duplikat-Check
                    exists = any(
                        h.text.lower() == hd["text"].lower()
                        for h in self.hypotheses
                    )
                    if exists:
                        continue
                    h = Hypothesis(
                        id=hd["id"],
                        text=hd["text"],
                        priority=hd.get("priority", 1),
                        status=status if status == "done" else "pending",
                        confidence=hd.get("confidence"),
                        findings_count=hd.get("findings_count", 0),
                        is_seed=hd.get("is_seed", False),
                        parent_id=hd.get("parent_id"),
                        created_at=hd.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
                        updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    )
                    self.hypotheses.append(h)
                    if status == "done":
                        loaded_done += 1
                    else:
                        loaded_pending += 1
            total_loaded = loaded_pending + loaded_done
            if total_loaded:
                saved_at = data.get("saved_at", "?")
                self._done_since_last_trigger = data.get("done_since_last_trigger", 0)
                self.log(
                    f"Queue wiederhergestellt: {loaded_pending} ausstehend + "
                    f"{loaded_done} fertig (gespeichert: {saved_at})", "SUCCESS"
                )
                self._add_activity(
                    f"🔄 Queue wiederhergestellt: {loaded_pending} ausstehend, "
                    f"{loaded_done} fertig (vom {saved_at})"
                )
                if loaded_pending > 0:
                    self._new_work.set()
            return loaded_pending > 0
        except Exception as e:
            self.log(f"Queue-Load Fehler: {e}", "WARNING")
            return False

    def start(self, interval_minutes: int = 60):
        """Startet den autonomen Hintergrundloop – stellt Queue automatisch wieder her."""
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self.thread = threading.Thread(
            target=self._loop,
            args=(interval_minutes,),
            daemon=True,
            name="ResearchAgent"
        )
        self.thread.start()
        self.log("ResearchAgent gestartet", "SUCCESS")
        self._add_activity("🚀 ResearchAgent gestartet")
        # Auto-Resume: gespeicherte Queue laden
        self.load_queue()

    def stop(self):
        """Stoppt den Loop und speichert Queue für spätere Wiederaufnahme."""
        self.running = False
        self._stop.set()
        self.save_queue()
        if self.thread:
            self.thread.join(timeout=15)
        self.log("ResearchAgent gestoppt – Queue gespeichert")

    def add_hypothesis(self, text: str, priority: int = 1,
                       is_seed: bool = False, parent_id: str = None,
                       source: str = "api") -> "Hypothesis":
        """Fügt eine neue Hypothese zur Queue hinzu (thread-safe)."""
        h = Hypothesis(
            id=hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:12],
            text=text.strip(),
            priority=priority,
            is_seed=is_seed,
            parent_id=parent_id
        )
        with self._lock:
            # Duplikat-Check (gleicher Text, pending/active)
            existing = [x for x in self.hypotheses
                        if x.text.lower() == h.text.lower()
                        and x.status in ("pending", "active")]
            if not existing:
                # Queue-Limit: max 30 pending – auto-generierte ignorieren wenn voll
                pending_count = sum(1 for x in self.hypotheses if x.status == "pending")
                if source == "auto" and not is_seed and self.queue_limit > 0 and pending_count >= self.queue_limit:
                    return h  # still verwerfen, kein Fehler
                self.hypotheses.append(h)
                self.log(f"Hypothese hinzugefügt: {text[:80]}")
                src = {"lyra": "LYRA", "ui": "Web-UI", "auto": "Auto"}.get(source, "API")
                label = "🌱 Seed" if is_seed else "➕"
                self._add_activity(f"{label} [{src}] {text[:80]}")
                self._new_work.set()  # ← WICHTIG: Loop sofort aufwecken
        return h

    def get_status(self) -> Dict:
        """Gibt aktuellen Status für Web-UI zurück."""
        with self._lock:
            # Zähler immer aus der vollständigen Liste
            total_active  = sum(1 for h in self.hypotheses if h.status == "active")
            total_pending = sum(1 for h in self.hypotheses if h.status == "pending")
            total_done    = sum(1 for h in self.hypotheses if h.status == "done")
            # Seeds IMMER zurückgeben, Non-Seeds auf 30 begrenzen
            all_seeds = [h for h in self.hypotheses if h.is_seed]
            non_seeds = [h for h in self.hypotheses if not h.is_seed]
            non_seeds_sorted = sorted(
                non_seeds,
                key=lambda x: (0 if x.status == "active" else 1 if x.status == "pending" else 2, -x.priority)
            )[:30]
            combined = all_seeds + non_seeds_sorted

            def h_dict(h):
                return {
                    "id":         h.id,
                    "text":       h.text,
                    "status":     h.status,
                    "confidence": h.confidence,
                    "priority":   h.priority,
                    "findings":   h.findings_count,
                    "is_seed":    h.is_seed,
                    "parent_id":  h.parent_id,
                }
            hyps = [h_dict(h) for h in combined]
            acts = [
                {"time": a.time, "message": a.message, "breakthrough": a.breakthrough}
                for a in self.activity[-20:][::-1]
            ]
        return {
            "running":     self.running,
            "hypotheses":  hyps,
            "activity":    acts,
            "total":       len(self.hypotheses),
            "queue_limit": self.queue_limit,
            "counts": {
                "active":  total_active,
                "pending": total_pending,
                "done":    total_done,
            }
        }

    def list_dossiers(self) -> List[Dict]:
        """Listet alle Dossier-Dateien mit Metadaten auf."""
        result = []
        try:
            for fname in sorted(os.listdir(self.dossiers_dir)):
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(self.dossiers_dir, fname)
                mtime = time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(os.path.getmtime(fpath)))
                # Zähle ## Erkenntnisse-Einträge
                findings = 0
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.startswith("### Erkenntnis") or line.startswith("- **"):
                                findings += 1
                except Exception:
                    pass
                result.append({
                    "name":     fname,
                    "updated":  mtime,
                    "findings": findings,
                    "path":     fpath,
                })
        except Exception as e:
            self.log(f"Dossier-Liste Fehler: {e}", "WARNING")
        return result

    def get_dossier(self, name: str) -> Optional[str]:
        """Gibt Inhalt eines Dossiers zurück."""
        # Sicherheits-Check: nur .md, keine Pfad-Traversal
        safe_name = os.path.basename(name)
        if not safe_name.endswith(".md"):
            safe_name += ".md"
        fpath = os.path.join(self.dossiers_dir, safe_name)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def set_queue_limit(self, limit: int):
        """Setzt das Queue-Limit für auto-generierte Hypothesen (0 = unbegrenzt)."""
        self.queue_limit = max(0, limit)
        self.log(f"Queue-Limit gesetzt: {self.queue_limit if self.queue_limit > 0 else 'unbegrenzt'}")

    def stop_seed(self, seed_id: str) -> dict:
        """
        Stoppt einen Seed und alle pending Subhypothesen.
        Fertige Dossiers und done-Hypothesen bleiben erhalten.
        """
        removed = 0
        seed_text = ''
        with self._lock:
            # Seed selbst auf done setzen
            for h in self.hypotheses:
                if h.id == seed_id and h.is_seed:
                    h.status = 'done'
                    seed_text = h.text[:60]
                    break

            # Alle pending Subhypothesen dieses Seeds entfernen
            # (rekursiv: auch Subhypothesen von Subhypothesen)
            to_remove = set()
            def collect_children(parent_id):
                for h in self.hypotheses:
                    if h.parent_id == parent_id and h.status == 'pending':
                        to_remove.add(h.id)
                        collect_children(h.id)
            collect_children(seed_id)

            self.hypotheses = [h for h in self.hypotheses if h.id not in to_remove]
            removed = len(to_remove)

        self._add_activity(f"🛑 Seed gestoppt: {seed_text} ({removed} pending entfernt)")
        self.save_queue()
        return {"stopped": seed_id, "removed_pending": removed}

    def clear(self):
        """Setzt Hypothesen und Aktivitäts-Log zurück (Dossiers bleiben)."""
        with self._lock:
            self.hypotheses = []
            self.activity   = []
        # Queue-File ebenfalls löschen
        try:
            if os.path.isfile(self.queue_path):
                os.remove(self.queue_path)
        except Exception:
            pass
        self._add_activity("🗑 Research-Queue zurückgesetzt")

    # ── Core Loop ─────────────────────────────────────────────────────────────

    def _loop(self, interval_minutes: int = 60):
        """
        Hauptloop des Research Agent.
        
        Der Agent startet im IDLE-Modus und wartet auf eine Benutzeranfrage.
        Erst wenn über die Web-UI oder /api/research/hypothesis eine Seed-Frage
        oder Hypothese eingeht, beginnt die gezielte Arbeit.
        Keine automatische Arbeit ohne Benutzerauftrag.
        """
        self.log("Research Agent bereit – warte auf Benutzeranfrage...")
        self._add_activity("⏳ Bereit – warte auf Seed-Frage oder Hypothese")

        while not self._stop.is_set():
            try:
                hypothesis = self._get_next_hypothesis()

                # Keine offenen Hypothesen → idle, warte auf Benutzeranfrage
                if hypothesis is None:
                    self._new_work.clear()
                    self._new_work.wait(timeout=30)
                    # Auto-Save alle 60s auch im Idle
                    if time.time() - self._last_save > 60:
                        self.save_queue()
                    continue

                # Status → active
                with self._lock:
                    hypothesis.status     = "active"
                    hypothesis.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._add_activity(f"🔬 Bearbeite: {hypothesis.text[:80]}")

                # Seed-Hypothese: zuerst Subhypothesen generieren
                if hypothesis.is_seed:
                    self._add_activity("🧠 Generiere Subhypothesen (LLM)...")
                    try:
                        subs = self._generate_hypotheses_from_seed(hypothesis.text)
                        for sub in subs:
                            self.add_hypothesis(sub, priority=2, parent_id=hypothesis.id)
                        self._add_activity(f"✅ {len(subs)} Subhypothesen generiert")
                    except Exception as e:
                        self.log(f"Subhypothesen-Fehler: {e}", "WARNING")

                # Recherche
                findings = self._research_hypothesis(hypothesis)

                # Dossier aktualisieren
                self._update_dossier(hypothesis, findings)

                # Weitere Subhypothesen aus Findings
                if findings.get("sub_hypotheses"):
                    for sub in findings["sub_hypotheses"][:3]:
                        if sub and len(sub) > 10:
                            self.add_hypothesis(sub, priority=2, parent_id=hypothesis.id)

                # Status → done
                with self._lock:
                    hypothesis.status        = "done"
                    hypothesis.updated_at    = time.strftime("%Y-%m-%dT%H:%M:%S")
                    hypothesis.confidence    = findings.get("confidence", 0)
                    hypothesis.findings_count = len(findings.get("facts", []))

                conf  = findings.get("confidence", 0)
                facts = len(findings.get("facts", []))
                self._add_activity(
                    f"✅ Fertig: {hypothesis.text[:60]} | {conf}% | {facts} Fakten"
                )

                if self._check_for_breakthrough(findings):
                    self._alert_user(hypothesis, findings)

                self.log(f"Hypothese abgeschlossen: {hypothesis.text[:60]}", "SUCCESS")
                # Auto-Save nach jeder Hypothese (oder alle 60s)
                if time.time() - self._last_save > 60:
                    self.save_queue()

            except Exception as e:
                self.log(f"Loop-Fehler: {e}", "WARNING")
                if hypothesis:
                    with self._lock:
                        hypothesis.status = "failed"
                self.save_queue()  # Auch bei Fehler speichern

            time.sleep(1)  # Kurze Pause zwischen Hypothesen – sofort nächste aus Queue

    # ── Hypothesis Engine ─────────────────────────────────────────────────────

    def _get_next_hypothesis(self) -> Optional[Hypothesis]:
        """Holt die nächste Hypothese nach Priorität."""
        with self._lock:
            pending = [h for h in self.hypotheses if h.status == "pending"]
            if not pending:
                return None
            return sorted(pending, key=lambda h: -h.priority)[0]

    def _generate_hypotheses_from_seed(self, seed: str) -> List[str]:
        """Leitet 3-5 Teilhypothesen aus einer Seed-Frage ab."""
        prompt = f"""Du bist ein investigativer Recherche-Analyst.
Aus der folgenden übergeordneten Frage leite 4 konkrete, unterschiedliche Teilhypothesen ab,
die autonom recherchiert werden können. Jede Hypothese soll eine spezifische, überprüfbare
Aussage über Personen, Netzwerke oder Strukturen sein.

Seed-Frage: {seed}

Antworte NUR als JSON-Array (kein Markdown, keine Erklärung):
["Hypothese 1", "Hypothese 2", "Hypothese 3", "Hypothese 4"]"""

        response = self.ai_enhancer._query_ollama(prompt)
        try:
            # JSON aus Response extrahieren
            match = re.search(r'\[.*?\]', response, re.DOTALL)
            if match:
                hypotheses = json.loads(match.group())
                return [h.strip() for h in hypotheses if isinstance(h, str) and len(h) > 10]
        except Exception as e:
            self.log(f"Hypothesen-Parsing Fehler: {e}", "WARNING")
        # Fallback: einfache Ableitung
        return [
            f"Welche Schlüsselpersonen sind mit '{seed[:40]}' verbunden?",
            f"Welche Offshore-Strukturen spielen bei '{seed[:40]}' eine Rolle?",
            f"Welche historischen Ereignisse erklären '{seed[:40]}'?",
        ]

    # ── Research Engine ───────────────────────────────────────────────────────

    def _research_hypothesis(self, hypothesis: Hypothesis) -> Dict:
        """
        Vollständige Recherche-Pipeline:
        Neo4j Graph-Analyse → SearXNG Websuche → LLM-Extraktion → neue Knoten/Kanten
        """
        findings = {
            "hypothesis": hypothesis.text,
            "researched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "graph_entities": [],
            "web_results":    [],
            "facts":          [],
            "new_connections": [],
            "sub_hypotheses": [],
            "confidence":     0,
        }

        # ── Phase 1: Graph-Analyse ────────────────────────────────────────────
        try:
            graph_entities = self._analyze_graph_for_hypothesis(hypothesis.text)
            findings["graph_entities"] = graph_entities
            self.log(f"  Graph: {len(graph_entities)} relevante Entitäten gefunden")
        except Exception as e:
            self.log(f"  Graph-Analyse Fehler: {e}", "WARNING")

        # ── Phase 2: Web-Recherche via SearXNG ───────────────────────────────
        try:
            search_query = self._hypothesis_to_search_query(hypothesis.text)
            web_results  = self.ai_enhancer._search_web(search_query)
            findings["web_results"] = [
                {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:300]}
                for r in web_results[:5]
            ]
            self.log(f"  Web: {len(web_results)} Treffer für '{search_query[:50]}'")
        except Exception as e:
            self.log(f"  Web-Recherche Fehler: {e}", "WARNING")

        # ── Phase 3: LLM-Extraktion ───────────────────────────────────────────
        try:
            extracted = self._extract_with_llm(hypothesis.text, findings)
            findings["facts"]          = extracted.get("facts", [])
            findings["new_connections"] = extracted.get("new_connections", [])
            findings["sub_hypotheses"] = extracted.get("sub_hypotheses", [])
            findings["confidence"]      = extracted.get("confidence", 0)
            self.log(f"  LLM: {len(findings['facts'])} Fakten, Confidence {findings['confidence']}%")
        except Exception as e:
            self.log(f"  LLM-Extraktion Fehler: {e}", "WARNING")

        # ── Phase 4: Neue Knoten/Kanten in Neo4j ─────────────────────────────
        if findings["new_connections"]:
            self._persist_new_connections(findings["new_connections"])

        return findings

    def _analyze_graph_for_hypothesis(self, hypothesis_text: str) -> List[Dict]:
        """Extrahiert relevante Graph-Entitäten für die Hypothese."""
        # Schlüsselwörter aus Hypothese extrahieren
        keywords = [w for w in re.findall(r'\b[A-ZÜÄÖ][a-züäöA-ZÜÄÖ]{3,}\b', hypothesis_text)
                    if len(w) > 4][:5]

        driver = self.neo4j.get_driver()
        entities = []
        try:
            with driver.session() as session:
                for kw in keywords:
                    res = session.run(
                        """
                        CALL {
                            MATCH (p:Person) WHERE toLower(p.name) CONTAINS toLower($kw)
                            RETURN p.name AS name, p.country AS country, 'Person' AS type LIMIT 5
                            UNION
                            MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($kw)
                            RETURN e.name AS name, e.country AS country, 'Entity' AS type LIMIT 5
                        }
                        RETURN name, country, type LIMIT 10
                        """,
                        kw=kw
                    )
                    for r in res:
                        entities.append({
                            "name":    r["name"],
                            "country": r["country"] or "?",
                            "type":    r["type"],
                            "keyword": kw
                        })

                # Zentralste Knoten im Graph (Betweenness-Proxy via Degree)
                central = session.run(
                    """
                    MATCH (p:Person)-[r:RELATED_TO]->()
                    WITH p, count(r) AS degree
                    ORDER BY degree DESC LIMIT 10
                    RETURN p.name AS name, p.country AS country, degree
                    """
                )
                for r in central:
                    entities.append({
                        "name":    r["name"],
                        "country": r["country"] or "?",
                        "type":    "Person (zentral)",
                        "degree":  r["degree"]
                    })
        except Exception as e:
            self.log(f"Graph-Analyse Query Fehler: {e}", "WARNING")
        return entities[:20]

    def _hypothesis_to_search_query(self, hypothesis: str) -> str:
        """Wandelt eine Hypothese in eine knappe Suchanfrage um."""
        # Stopwörter entfernen, Schlüsselbegriffe extrahieren
        stopwords = {"warum", "wie", "welche", "sind", "ist", "die", "der", "das",
                     "und", "oder", "aber", "nicht", "trotz", "eine", "einer"}
        words = [w for w in re.findall(r'\b\w{4,}\b', hypothesis.lower())
                 if w not in stopwords][:6]
        return " ".join(words)

    def _extract_with_llm(self, hypothesis: str, findings: Dict) -> Dict:
        """Nutzt LLM um Fakten, neue Verbindungen und Sub-Hypothesen zu extrahieren."""
        # Kontext aufbauen
        graph_ctx = "\n".join([
            f"- {e['name']} ({e['type']}, {e['country']})"
            for e in findings["graph_entities"][:10]
        ])
        web_ctx = "\n".join([
            f"- {r['title']}: {r['snippet'][:200]}"
            for r in findings["web_results"][:5]
        ])

        prompt = f"""Du bist ein investigativer KI-Analyst. Analysiere die folgende Hypothese
anhand der Graph-Daten und Web-Recherche-Ergebnisse.

HYPOTHESE: {hypothesis}

RELEVANTE PERSONEN/ENTITÄTEN IM GRAPH:
{graph_ctx or '(keine gefunden)'}

WEB-RECHERCHE-ERGEBNISSE:
{web_ctx or '(keine gefunden)'}

Antworte NUR als JSON (kein Markdown):
{{
  "facts": ["Fakt 1", "Fakt 2", "Fakt 3"],
  "new_connections": [
    {{"person1": "Name A", "person2": "Name B", "reason": "Verbindungsgrund", "confidence": 70}}
  ],
  "sub_hypotheses": ["Teilhypothese 1", "Teilhypothese 2"],
  "confidence": 0,
  "summary": "Kurze Zusammenfassung (2 Sätze)"
}}"""

        response = self.ai_enhancer._query_ollama(prompt)
        try:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            self.log(f"LLM-Extraktion JSON Fehler: {e}", "WARNING")
        return {"facts": [], "new_connections": [], "sub_hypotheses": [], "confidence": 0}

    def _persist_new_connections(self, connections: List[Dict]):
        """Speichert neue LLM-extrahierte Verbindungen als SUGGESTED_CONNECTION in Neo4j."""
        driver = self.neo4j.get_driver()
        saved = 0
        try:
            with driver.session() as session:
                for conn in connections:
                    p1 = conn.get("person1", "").strip()
                    p2 = conn.get("person2", "").strip()
                    if not p1 or not p2 or p1 == p2:
                        continue
                    confidence = int(conn.get("confidence", 50))
                    reason     = conn.get("reason", "ResearchAgent-Erkenntnis")[:500]
                    sid        = hashlib.md5(f"{p1}{p2}research".encode()).hexdigest()[:16]
                    session.run(
                        """
                        MERGE (x:ResearchNode {name: $p1})
                        MERGE (y:ResearchNode {name: $p2})
                        MERGE (x)-[r:SUGGESTED_CONNECTION {id: $sid}]->(y)
                        SET r.confidence   = $confidence,
                            r.reason       = $reason,
                            r.person1      = $p1,
                            r.person2      = $p2,
                            r.source       = 'research_agent',
                            r.validated    = false,
                            r.rejected     = false,
                            r.suggested_at = datetime()
                        """,
                        p1=p1, p2=p2, sid=sid,
                        confidence=confidence, reason=reason
                    )
                    saved += 1
            if saved:
                self.log(f"  {saved} neue Verbindungen in Neo4j gespeichert", "SUCCESS")
        except Exception as e:
            self.log(f"Verbindungen speichern Fehler: {e}", "WARNING")

    # ── Dossier Engine ────────────────────────────────────────────────────────

    def _update_dossier(self, hypothesis: Hypothesis, findings: Dict):
        """Aktualisiert das lebende Dossier für diese Hypothese (Markdown)."""
        # Dateiname aus Hypothese ableiten
        safe_name = re.sub(r'[^a-zA-Z0-9_äöüÄÖÜ]', '_', hypothesis.text[:50]).strip('_')
        safe_name = re.sub(r'_+', '_', safe_name).lower()
        fpath = os.path.join(self.dossiers_dir, f"{safe_name}.md")

        timestamp = time.strftime("%Y-%m-%d %H:%M")
        facts_md  = "\n".join([f"- {f}" for f in findings.get("facts", [])]) or "- (keine neuen Fakten)"
        conns_md  = "\n".join([
            f"- **{c.get('person1','?')}** ↔ **{c.get('person2','?')}**: {c.get('reason','?')} (Confidence: {c.get('confidence',0)}%)"
            for c in findings.get("new_connections", [])
        ]) or "- (keine neuen Verbindungen)"

        section = f"""
## Recherche-Durchlauf: {timestamp}

**Confidence:** {findings.get('confidence', 0)}%  
**Gefundene Fakten:** {len(findings.get('facts', []))}  
**Neue Verbindungen:** {len(findings.get('new_connections', []))}

### Erkenntnisse
{facts_md}

### Neue Verbindungen (unvalidiert)
{conns_md}

### Web-Quellen
{chr(10).join(['- [' + r.get('title','?')[:60] + '](' + r.get('url','') + ')' for r in findings.get('web_results', [])[:5]]) or '- (keine)'}

---
"""
        try:
            if os.path.exists(fpath):
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(section)
            else:
                header = f"""# Dossier: {hypothesis.text}

**Erstellt:** {timestamp}  
**Typ:** {'Seed-Frage' if hypothesis.is_seed else 'Teilhypothese'}  
**Pfad:** {fpath}

---
"""
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(header + section)
            self.log(f"Dossier aktualisiert: {os.path.basename(fpath)}", "SUCCESS")
            self._add_activity(f"📄 Dossier: {os.path.basename(fpath)}")
        except Exception as e:
            self.log(f"Dossier-Update Fehler: {e}", "WARNING")

    # ── Breakthrough & Alerts ─────────────────────────────────────────────────

    def _check_for_breakthrough(self, findings: Dict) -> bool:
        """Prüft ob ein Durchbruch oder ein periodischer Zwischenbericht fällig ist."""
        confidence = findings.get("confidence", 0)
        new_conns  = len(findings.get("new_connections", []))
        # Klassischer Durchbruch
        if confidence >= 80 or new_conns >= 5:
            return True
        # Periodischer Trigger: alle 10 abgeschlossenen Hypothesen seit letztem Trigger
        self._done_since_last_trigger += 1
        if self._done_since_last_trigger >= 10:
            self._done_since_last_trigger = 0  # Zähler zurücksetzen
            return True
        return False

    def _build_summary_message(self) -> str:
        """Erstellt Zwischenbericht für OpenClaw."""
        with self._lock:
            done  = [h for h in self.hypotheses if h.status == "done"]
            total = len(self.hypotheses)
            facts = sum(h.findings_count for h in done)
            top   = sorted(done, key=lambda h: h.confidence or 0, reverse=True)[:3]
        dossiers = len(self.list_dossiers())
        lines = [
            f"📊 LYRA-NET Zwischenbericht – {len(done)}/{total} Hypothesen abgeschlossen",
            f"   Fakten: {facts} | Dossiers: {dossiers}",
            "",
            "🔍 Top-Erkenntnisse:"
        ]
        for h in top:
            conf = f"{h.confidence}%" if h.confidence else "?"
            lines.append(f"  • [{conf}] {h.text[:80]}")
        lines.append(f"\n📁 Dossiers: http://127.0.0.1:{FLASK_PORT}/research")
        return "\n".join(lines)

    def _alert_user(self, hypothesis: Hypothesis, findings: Dict):
        """Sendet Durchbruch oder Zwischenbericht an OpenClaw Gateway."""
        confidence = findings.get("confidence", 0)
        new_conns  = len(findings.get("new_connections", []))
        is_periodic = self._done_since_last_trigger == 0  # wurde gerade zurückgesetzt

        if is_periodic and confidence < 80 and new_conns < 5:
            msg = self._build_summary_message()
        else:
            msg = (f"🚨 DURCHBRUCH: '{hypothesis.text[:60]}' – "
                   f"Confidence {confidence}%, "
                   f"{new_conns} neue Verbindungen")

        self.log(msg[:200], "SUCCESS")
        self._add_activity(msg[:120], breakthrough=True)

        # LYRA über Workspace-Datei benachrichtigen
        # OpenClaw 5.7 hat keinen REST-Endpunkt für Message-Injection (läuft über WebSocket).
        # Stattdessen: Bericht in research_report.md schreiben.
        # SOUL.md-Regel weist LYRA an diese Datei beim nächsten Turn zu lesen.
        try:
            workspace = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace")
            os.makedirs(workspace, exist_ok=True)
            report_path = os.path.join(workspace, "research_report.md")
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(f"# LYRA-NET Bericht\n")
                f.write(f"**Erstellt:** {timestamp}\n\n")
                f.write(msg)
                f.write(f"\n\n---\n*Gelesen? Diese Datei nach dem Lesen löschen.*\n")
            self.log(f"Bericht geschrieben: {report_path}", "SUCCESS")
        except Exception as e:
            self.log(f"Bericht-Datei Fehler: {e}", "WARNING")

    def _add_activity(self, message: str, breakthrough: bool = False):
        """Fügt einen Eintrag zum Aktivitäts-Log hinzu (thread-safe, max 100 Einträge)."""
        entry = ActivityEntry(
            time=time.strftime("%H:%M"),
            message=message,
            breakthrough=breakthrough
        )
        with self._lock:
            self.activity.append(entry)
            if len(self.activity) > 100:
                self.activity = self.activity[-100:]


class WebServer:
    """
    Flask-Webserver für die Graph-Visualisierung.
    """
    
    def __init__(self, neo4j_manager: Neo4jManager, log_fn=None):
        self.neo4j = neo4j_manager
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[WebServer] {msg}"))
        self.app = None
        self.server = None
        self.thread = None
        
    def _ensure_static_libs(self):
        """Laedt jQuery und vis-network lokal herunter falls noetig."""
        static_dir = os.path.join(os.path.expanduser("~"), ".lyra_net_static")
        os.makedirs(static_dir, exist_ok=True)

        libs = {
            "jquery.min.js": [
                "https://code.jquery.com/jquery-3.6.0.min.js",
                "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js",
            ],
            "vis-network.min.js": [
                "https://unpkg.com/vis-network@9.1.2/dist/vis-network.min.js",
                "https://cdnjs.cloudflare.com/ajax/libs/vis/9.1.2/vis-network.min.js",
            ],
        }

        for filename, urls in libs.items():
            dest = os.path.join(static_dir, filename)
            if os.path.isfile(dest) and os.path.getsize(dest) > 10000:
                self.log(f"Bibliothek bereits vorhanden: {filename}", "INFO")
                continue
            downloaded = False
            for url in urls:
                try:
                    self.log(f"Lade {filename} von {url[:60]}...")
                    urllib.request.urlretrieve(url, dest)
                    if os.path.getsize(dest) > 10000:
                        self.log(f"{filename} gespeichert ({os.path.getsize(dest)//1024} KB)", "SUCCESS")
                        downloaded = True
                        break
                except Exception as e:
                    self.log(f"Download fehlgeschlagen ({url[:50]}): {e}", "WARNING")

            if not downloaded:
                self.log(f"WARNUNG: {filename} konnte nicht heruntergeladen werden!", "WARNING")
                self.log("Bitte manuell herunterladen oder Internetverbindung pruefen.", "WARNING")

        return static_dir

    def _create_app(self):
        """Erstellt die Flask-App mit allen Routen."""
        static_dir = self._ensure_static_libs()
        app = Flask(__name__, static_folder=static_dir, static_url_path="/static")
        neo4j_mgr = self.neo4j
        log = self.log
        
        @app.route('/')
        def index():
            return render_template_string(HTML_TEMPLATE)
        
        @app.route('/api/graph')
        def get_graph():
            """Gibt den Graph als JSON zurueck. Ausfuehrliches Debugging aktiv."""
            driver = neo4j_mgr.get_driver()
            nodes  = []
            edges  = []

            OFFSHORE_JURISDICTIONS = {
                "Panama", "British Virgin Islands", "Cayman Islands",
                "Seychelles", "Bermuda", "Bahamas", "Jersey", "Guernsey",
                "Isle of Man", "Liechtenstein", "Luxembourg", "Malta",
                "Marshall Islands", "Samoa", "Vanuatu"
            }

            try:
                with driver.session() as session:

                    # ── Schritt 1: Erste N Knoten je Label ────────────────────
                    import random
                    # Zufaelliger Offset – zeigt bei jedem Reload anderen Ausschnitt
                    # Kein ORDER BY rand() – SKIP ist schnell da Index-basiert
                    offsets = {
                        "Person":       random.randint(0, 770000),
                        "Entity":       random.randint(0, 813000),
                        "Intermediary": random.randint(0, 25000),
                        "Address":      random.randint(0, 400000),
                    }
                    label_limits = [
                        ("Person",       300),
                        ("Entity",       300),
                        ("Intermediary", 100),
                        ("Address",      100),
                    ]
                    node_id_set = set()   # n.id (ICIJ-Property) fuer Edge-Filter

                    for label, lim in label_limits:
                        skip = offsets[label]
                        res = session.run(
                            f"""
                            MATCH (n:{label})
                            RETURN n.id      AS nid,
                                   n.name    AS name,
                                   n.country AS country
                            SKIP {skip}
                            LIMIT {lim}
                            """
                        )
                        null_id_count = 0
                        for record in res:
                            nid     = record["nid"]
                            name    = record["name"]    or "Unbekannt"
                            country = record["country"] or ""

                            if not nid:
                                null_id_count += 1
                                continue

                            if label == "Person":
                                group = "Person"
                            elif label == "Entity":
                                group = "Offshore" if country in OFFSHORE_JURISDICTIONS else "Entity"
                            elif label == "Intermediary":
                                group = "Intermediary"
                            else:
                                group = "Address"

                            node_id_set.add(nid)
                            nodes.append({
                                "id":      nid,
                                "label":   name[:40],
                                "group":   group,
                                "tooltip": f"{name}\nTyp: {label}\nLand: {country or 'unbekannt'}"
                            })



                    # ── Schritt 2: Kanten per Label-spezifischem UNWIND ────────
                    # Label im MATCH ist zwingend damit der Index greift.
                    # Ohne Label: Full-Graph-Scan pro Knoten → haengt.
                    # Trenne IDs nach Label – nodes-Liste hat group-Info
                    ids_by_label: Dict[str, List[str]] = {
                        "Person": [], "Entity": [], "Intermediary": [], "Address": []
                    }
                    for n in nodes:
                        lbl = n["group"]
                        # group "Offshore" → Label "Entity"
                        key = "Entity" if lbl == "Offshore" else lbl
                        if key in ids_by_label:
                            ids_by_label[key].append(n["id"])

                    edge_count = 0
                    new_node_ids: Dict[str, dict] = {}  # id -> node dict

                    for label, id_list in ids_by_label.items():
                        if not id_list or edge_count >= 800:
                            break
                        res = session.run(
                            f"""
                            UNWIND $ids AS src_id
                            MATCH (a:{label} {{id: src_id}})-[r:RELATED_TO]->(b)
                            RETURN a.id  AS src,
                                   b.id  AS tgt,
                                   b.name AS tgt_name,
                                   b.country AS tgt_country,
                                   labels(b)[0] AS tgt_label,
                                   r.type AS lbl
                            LIMIT 400
                            """,
                            ids=id_list
                        )
                        for record in res:
                            src = record["src"]
                            tgt = record["tgt"]
                            if not src or not tgt:
                                continue
                            edges.append({
                                "from":  src,
                                "to":    tgt,
                                "label": (record["lbl"] or "")[:15]
                            })
                            edge_count += 1
                            # Zielknoten merken falls noch nicht in nodes
                            if tgt not in node_id_set:
                                node_id_set.add(tgt)
                                tgt_country = record["tgt_country"] or ""
                                tgt_label   = record["tgt_label"]   or "Entity"
                                tgt_group   = ("Offshore"
                                               if tgt_country in OFFSHORE_JURISDICTIONS
                                               else tgt_label
                                               if tgt_label in ("Person","Intermediary","Address")
                                               else "Entity")
                                new_node_ids[tgt] = {
                                    "id":      tgt,
                                    "label":   (record["tgt_name"] or "Unbekannt")[:40],
                                    "group":   tgt_group,
                                    "tooltip": f"{record['tgt_name'] or 'Unbekannt'}\nTyp: {tgt_label}\nLand: {tgt_country or 'unbekannt'}"
                                }

                    nodes.extend(new_node_ids.values())
                return jsonify({"nodes": nodes, "edges": edges})

            except Exception as e:
                log(f"Graph-API-Fehler: {e}", "ERROR")
                import traceback
                log(traceback.format_exc(), "ERROR")
                return jsonify({"error": str(e), "nodes": [], "edges": []}), 500

        @app.route('/api/node/<path:node_id>')
        def get_node(node_id):
            """Gibt Details zu einem Knoten per ICIJ n.id Property zurueck."""
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    result = session.run(
                        """
                        MATCH (n {id: $nid})
                        RETURN n.name    AS name,
                               labels(n)[0] AS type,
                               properties(n) AS props,
                               size([(n)-[r]-(m) | 1]) AS connection_count
                        LIMIT 1
                        """,
                        nid=node_id
                    )
                    record = result.single()
                    if record:
                        props = record["props"]
                        return jsonify({
                            "name":        record["name"],
                            "type":        record["type"],
                            "country":     props.get("country", ""),
                            "source":      props.get("source", ""),
                            "connections": record["connection_count"] or 0
                        })
                    else:
                        return jsonify({"error": "Node not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500
        
        @app.route('/api/graph/node/<path:node_id>')
        def graph_node(node_id):
            """Alle Verbindungen eines Knotens – Label-unabhaengig, beide Richtungen.

            Funktioniert fuer Person, Entity, Intermediary, Address und jeden
            anderen Knotentyp. Das Label wird aus der DB gelesen, nicht geraten.
            """
            driver = neo4j_mgr.get_driver()
            OFFSHORE_JURISDICTIONS = {
                "Panama", "British Virgin Islands", "Cayman Islands",
                "Seychelles", "Bermuda", "Bahamas", "Jersey", "Guernsey",
                "Isle of Man", "Liechtenstein", "Luxembourg", "Malta",
                "Marshall Islands", "Samoa", "Vanuatu"
            }

            def make_node(nid, name, country, lbl, is_hit=False):
                country = country or ""
                lbl     = lbl or "Entity"
                group   = ("Offshore" if country in OFFSHORE_JURISDICTIONS
                           else lbl if lbl in ("Person","Intermediary","Address")
                           else "Entity")
                return {
                    "id":      nid,
                    "label":   (name or "?")[:40],
                    "group":   group,
                    "tooltip": f"{name or '?'}\nTyp: {lbl}\nLand: {country or 'unbekannt'}",
                    "isHit":   is_hit
                }

            nodes      = []
            edges      = []
            seen_nodes = set()
            seen_edges = set()

            try:
                with driver.session() as session:

                    # ── Schritt 1: Hauptknoten laden – OHNE Label-Annahme ──
                    # MATCH (n {id: $nid}) findet den Knoten unabhaengig vom
                    # Label solange n.id indiziert ist (Constraint vorhanden).
                    rec = session.run(
                        """
                        MATCH (n {id: $nid})
                        RETURN n.id      AS nid,
                               n.name    AS name,
                               n.country AS country,
                               labels(n)[0] AS lbl
                        LIMIT 1
                        """,
                        nid=node_id
                    ).single()

                    if not rec:
                        return jsonify({"nodes": [], "edges": [],
                                        "error": f"Knoten {node_id} nicht gefunden"})

                    lbl = rec["lbl"] or "Entity"
                    seen_nodes.add(node_id)
                    nodes.append(make_node(node_id, rec["name"],
                                           rec["country"], lbl, True))

                    # ── Schritt 2: Verbindungen BEIDER Richtungen ──────────
                    # Ausgehend: (dieser Knoten) → (Nachbar)
                    res = session.run(
                        """
                        MATCH (a {id: $nid})-[r:RELATED_TO]->(b)
                        RETURN a.id          AS src,
                               b.id          AS tgt,
                               b.name        AS bname,
                               b.country     AS bcountry,
                               labels(b)[0]  AS blbl,
                               r.type        AS rtype
                        LIMIT 500
                        """,
                        nid=node_id
                    )
                    for r in res:
                        src = r["src"]; tgt = r["tgt"]
                        if not src or not tgt:
                            continue
                        ekey = f"{src}→{tgt}"
                        if ekey not in seen_edges:
                            seen_edges.add(ekey)
                            edges.append({"from": src, "to": tgt,
                                          "label": (r["rtype"] or "")[:15]})
                        if tgt not in seen_nodes:
                            seen_nodes.add(tgt)
                            nodes.append(make_node(tgt, r["bname"],
                                                   r["bcountry"], r["blbl"]))

                    # Eingehend: (Nachbar) → (dieser Knoten)
                    res = session.run(
                        """
                        MATCH (b)-[r:RELATED_TO]->(a {id: $nid})
                        RETURN b.id          AS src,
                               a.id          AS tgt,
                               b.name        AS bname,
                               b.country     AS bcountry,
                               labels(b)[0]  AS blbl,
                               r.type        AS rtype
                        LIMIT 500
                        """,
                        nid=node_id
                    )
                    for r in res:
                        src = r["src"]; tgt = r["tgt"]
                        if not src or not tgt:
                            continue
                        ekey = f"{src}→{tgt}"
                        if ekey not in seen_edges:
                            seen_edges.add(ekey)
                            edges.append({"from": src, "to": tgt,
                                          "label": (r["rtype"] or "")[:15]})
                        if src not in seen_nodes:
                            seen_nodes.add(src)
                            nodes.append(make_node(src, r["bname"],
                                                   r["bcountry"], r["blbl"]))

                log(f"Node-Expand '{node_id}': {len(nodes)} Knoten, {len(edges)} Kanten", "INFO")
                return jsonify({"nodes": nodes, "edges": edges, "hits": 1})

            except Exception as e:
                log(f"Node-Expand Fehler: {e}", "ERROR")
                return jsonify({"nodes": [], "edges": [], "error": str(e)})

        # ── Kandidaten-API (Phase 3) ──────────────────────────────────────

        @app.route('/api/candidates')
        def get_candidates():
            """Alle unbestaetigten Verbindungsvorschlaege."""
            driver = neo4j_mgr.get_driver()
            try:
                min_conf = int(request.args.get('min_confidence', 0))
                search   = request.args.get('q', '').lower()
                with driver.session() as session:
                    res = session.run(
                        """
                        MATCH (p1)-[r:SUGGESTED_CONNECTION]->(p2)
                        WHERE r.validated = false AND r.rejected = false
                          AND r.confidence >= $min_conf
                        RETURN r.id AS id, r.person1 AS person1, r.person2 AS person2,
                               r.reason AS reason, r.confidence AS confidence,
                               r.relationship_type AS rel_type,
                               toString(r.suggested_at) AS suggested_at,
                               r.source AS source
                        ORDER BY r.confidence DESC
                        LIMIT 200
                        """,
                        min_conf=min_conf
                    )
                    candidates = []
                    for r in res:
                        c = dict(r)
                        if search and search not in (c.get('person1','') + c.get('person2','')).lower():
                            continue
                        candidates.append(c)
                return jsonify({"candidates": candidates, "total": len(candidates)})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/candidates/<sid>/accept', methods=['POST'])
        def accept_candidate(sid):
            """Verbindung akzeptieren → als RELATED_TO speichern."""
            data = request.get_json(silent=True) or {}
            rel_type = data.get('relationship_type', 'ASSOCIATE')
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    # Kandidat laden
                    rec = session.run(
                        """
                        MATCH (p1)-[r:SUGGESTED_CONNECTION {id: $sid}]->(p2)
                        RETURN p1.id AS id1, p2.id AS id2,
                               r.person1 AS p1name, r.person2 AS p2name,
                               r.confidence AS confidence
                        """,
                        sid=sid
                    ).single()
                    if not rec:
                        return jsonify({"error": "Kandidat nicht gefunden"}), 404

                    # Als RELATED_TO speichern
                    session.run(
                        """
                        MATCH (p1 {id: $id1}), (p2 {id: $id2})
                        MERGE (p1)-[r:RELATED_TO {type: $rel_type}]->(p2)
                        SET r.source        = 'manual_accept',
                            r.confidence    = $confidence,
                            r.ai_discovered = true,
                            r.accepted_at   = datetime()
                        """,
                        id1=rec["id1"], id2=rec["id2"],
                        rel_type=rel_type,
                        confidence=rec["confidence"] or 0
                    )
                    # Kandidat als validiert markieren
                    session.run(
                        """
                        MATCH ()-[r:SUGGESTED_CONNECTION {id: $sid}]->()
                        SET r.validated = true, r.validated_at = datetime()
                        """,
                        sid=sid
                    )
                log(f"Kandidat akzeptiert: {rec['p1name']} ↔ {rec['p2name']} [{rel_type}]", "SUCCESS")
                return jsonify({"status": "accepted", "relationship_type": rel_type})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/candidates/<sid>/reject', methods=['POST'])
        def reject_candidate(sid):
            """Verbindung ablehnen → als REJECTED_CONNECTION (Blacklist) speichern."""
            data = request.get_json(silent=True) or {}
            reject_reason = data.get('reason', '')
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    rec = session.run(
                        """
                        MATCH (p1)-[r:SUGGESTED_CONNECTION {id: $sid}]->(p2)
                        RETURN p1.id AS id1, p2.id AS id2,
                               r.person1 AS p1name, r.person2 AS p2name
                        """,
                        sid=sid
                    ).single()
                    if not rec:
                        return jsonify({"error": "Kandidat nicht gefunden"}), 404

                    # Als REJECTED_CONNECTION speichern (Blacklist)
                    session.run(
                        """
                        MATCH (p1 {id: $id1}), (p2 {id: $id2})
                        MERGE (p1)-[r:REJECTED_CONNECTION]->(p2)
                        SET r.reason      = $reason,
                            r.rejected_at = datetime()
                        """,
                        id1=rec["id1"], id2=rec["id2"],
                        reason=reject_reason[:500]
                    )
                    # SUGGESTED_CONNECTION als abgelehnt markieren
                    session.run(
                        """
                        MATCH ()-[r:SUGGESTED_CONNECTION {id: $sid}]->()
                        SET r.rejected = true, r.rejected_at = datetime()
                        """,
                        sid=sid
                    )
                log(f"Kandidat abgelehnt: {rec['p1name']} ↔ {rec['p2name']}", "INFO")
                return jsonify({"status": "rejected"})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/candidates/<sid>/confidence', methods=['POST'])
        def update_confidence(sid):
            """Confidence-Wert manuell anpassen."""
            data = request.get_json(silent=True) or {}
            confidence = max(0, min(100, int(data.get('confidence', 50))))
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    session.run(
                        """
                        MATCH ()-[r:SUGGESTED_CONNECTION {id: $sid}]->()
                        SET r.confidence = $confidence, r.manually_adjusted = true
                        """,
                        sid=sid, confidence=confidence
                    )
                return jsonify({"status": "updated", "confidence": confidence})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/candidates/blacklist')
        def get_blacklist():
            """Alle abgelehnten Verbindungen (Blacklist)."""
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    res = session.run(
                        """
                        MATCH (p1)-[r:REJECTED_CONNECTION]->(p2)
                        RETURN p1.name AS person1, p2.name AS person2,
                               r.reason AS reason,
                               toString(r.rejected_at) AS rejected_at
                        ORDER BY r.rejected_at DESC
                        LIMIT 100
                        """
                    )
                    return jsonify({"blacklist": [dict(r) for r in res]})
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @app.route('/api/candidates/export')
        def export_candidates():
            """JSON-Export aller Kandidaten."""
            enhancer = getattr(neo4j_mgr, '_enhancer_ref', None)
            if enhancer is None:
                return jsonify({"status": "error",
                                "message": "AI Enhancer nicht aktiv – Export nicht verfuegbar"}), 503
            path = enhancer.export_candidates_json()
            if not path:
                return jsonify({"status": "error", "message": "Export fehlgeschlagen"}), 500
            return jsonify({"status": "ok", "path": path,
                            "message": f"Export gespeichert: {path}"})

        @app.route('/api/health')
        @app.route('/health')  # Alias für OpenClaw das /health statt /api/health fragt
        def health():
            """Health-Check Endpunkt."""
            driver = neo4j_mgr.get_driver()
            node_count = 0
            try:
                with driver.session() as session:
                    result = session.run("MATCH (n) RETURN count(n) AS cnt")
                    node_count = result.single()["cnt"]
            except Exception:
                pass
            
            return jsonify({
                "status": "ok",
                "node_count": node_count,
                "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
            })
        
        @app.route('/api/search')
        def search():
            """Schnelle Autovervollstaendigung – gibt nur Namen zurueck."""
            query = request.args.get('q', '').lower()
            if not query or len(query) < 2:
                return jsonify([])
            driver = neo4j_mgr.get_driver()
            try:
                with driver.session() as session:
                    result = session.run(
                        """
                        CALL {
                            MATCH (n:Person) WHERE toLower(n.name) CONTAINS $query
                            RETURN n.id AS nid, n.name AS name, labels(n)[0] AS lbl LIMIT 5
                            UNION
                            MATCH (n:Entity) WHERE toLower(n.name) CONTAINS $query
                            RETURN n.id AS nid, n.name AS name, labels(n)[0] AS lbl LIMIT 5
                            UNION
                            MATCH (n:Intermediary) WHERE toLower(n.name) CONTAINS $query
                            RETURN n.id AS nid, n.name AS name, labels(n)[0] AS lbl LIMIT 5
                        }
                        RETURN nid, name, lbl LIMIT 15
                        """,
                        query=query
                    )
                    return jsonify([
                        {"id": r["nid"], "name": r["name"], "type": r["lbl"]}
                        for r in result
                    ])
            except Exception:
                return jsonify([])

        @app.route('/api/graph/search')
        def graph_search():
            """Graph-Suche: Treffer + alle Verbindungen (beide Richtungen)."""
            query = request.args.get('q', '').strip()
            if not query or len(query) < 2:
                return jsonify({"nodes": [], "edges": [],
                                "error": "Suchbegriff zu kurz"})

            driver = neo4j_mgr.get_driver()
            OFFSHORE_JURISDICTIONS = {
                "Panama", "British Virgin Islands", "Cayman Islands",
                "Seychelles", "Bermuda", "Bahamas", "Jersey", "Guernsey",
                "Isle of Man", "Liechtenstein", "Luxembourg", "Malta",
                "Marshall Islands", "Samoa", "Vanuatu"
            }

            def make_node(nid, name, country, lbl, is_hit=False):
                country = country or ""
                lbl     = lbl or "Entity"
                group   = ("Offshore" if country in OFFSHORE_JURISDICTIONS
                           else lbl if lbl in ("Person","Intermediary","Address")
                           else "Entity")
                return {
                    "id":      nid,
                    "label":   (name or "?")[:40],
                    "group":   group,
                    "tooltip": f"{name or '?'}\nTyp: {lbl}\nLand: {country or 'unbekannt'}",
                    "isHit":   is_hit
                }

            nodes      = []
            edges      = []
            seen_nodes = set()
            seen_edges = set()

            try:
                with driver.session() as session:

                    # ── 1. Treffer finden ──────────────────────────────────
                    res = session.run(
                        """
                        CALL {
                            MATCH (n:Person) WHERE toLower(n.name) CONTAINS toLower($search_term)
                            RETURN n.id AS nid, n.name AS name, n.country AS country, labels(n)[0] AS lbl LIMIT 7
                            UNION
                            MATCH (n:Entity) WHERE toLower(n.name) CONTAINS toLower($search_term)
                            RETURN n.id AS nid, n.name AS name, n.country AS country, labels(n)[0] AS lbl LIMIT 7
                            UNION
                            MATCH (n:Intermediary) WHERE toLower(n.name) CONTAINS toLower($search_term)
                            RETURN n.id AS nid, n.name AS name, n.country AS country, labels(n)[0] AS lbl LIMIT 6
                        }
                        RETURN nid, name, country, lbl LIMIT 20
                        """,
                        search_term=query
                    )
                    hit_ids   = []
                    hit_label = {}  # nid -> label fuer spaeteren Index-Lookup
                    for r in res:
                        nid = r["nid"]
                        if not nid or nid in seen_nodes:
                            continue
                        seen_nodes.add(nid)
                        hit_ids.append(nid)
                        lbl = r["lbl"] or "Entity"
                        hit_label[nid] = "Entity" if lbl == "Offshore" else lbl
                        nodes.append(make_node(nid, r["name"], r["country"], lbl, True))

                    if not hit_ids:
                        return jsonify({"nodes": [], "edges": [],
                                        "error": f"Keine Ergebnisse fuer '{query}'"})

                    # ── 2. Verbindungen BEIDER Richtungen ─────────────────
                    # Ausgehend UND eingehend – sonst fehlen Personen die
                    # auf eine Offshore-Entity zeigen (Person→Entity)
                    for nid in hit_ids:
                        lbl = hit_label.get(nid, "Entity")

                        # Ausgehend: (hit)→(neighbor)
                        res = session.run(
                            f"""
                            MATCH (a:{lbl} {{id: $nid}})-[r:RELATED_TO]->(b)
                            RETURN a.id AS src, b.id AS tgt,
                                   b.name AS bname, b.country AS bcountry,
                                   labels(b)[0] AS blbl, r.type AS rtype
                            LIMIT 200
                            """,
                            nid=nid
                        )
                        for r in res:
                            ekey = f"{r['src']}→{r['tgt']}"
                            if ekey not in seen_edges:
                                seen_edges.add(ekey)
                                edges.append({"from": r["src"], "to": r["tgt"],
                                              "label": (r["rtype"] or "")[:15]})
                            if r["tgt"] not in seen_nodes:
                                seen_nodes.add(r["tgt"])
                                nodes.append(make_node(r["tgt"], r["bname"],
                                                       r["bcountry"], r["blbl"]))

                        # Eingehend: (neighbor)→(hit)
                        res = session.run(
                            f"""
                            MATCH (b)-[r:RELATED_TO]->(a:{lbl} {{id: $nid}})
                            RETURN b.id AS src, a.id AS tgt,
                                   b.name AS bname, b.country AS bcountry,
                                   labels(b)[0] AS blbl, r.type AS rtype
                            LIMIT 200
                            """,
                            nid=nid
                        )
                        for r in res:
                            ekey = f"{r['src']}→{r['tgt']}"
                            if ekey not in seen_edges:
                                seen_edges.add(ekey)
                                edges.append({"from": r["src"], "to": r["tgt"],
                                              "label": (r["rtype"] or "")[:15]})
                            if r["src"] not in seen_nodes:
                                seen_nodes.add(r["src"])
                                nodes.append(make_node(r["src"], r["bname"],
                                                       r["bcountry"], r["blbl"]))

                log(f"Suche '{query}': {len(nodes)} Knoten, {len(edges)} Kanten", "INFO")
                return jsonify({"nodes": nodes, "edges": edges,
                                "query": query, "hits": len(hit_ids)})

            except Exception as e:
                log(f"Graph-Suche Fehler: {e}", "ERROR")
                return jsonify({"nodes": [], "edges": [], "error": str(e)})

        # ══════════════════════════════════════════════════════════════════════
        # Research Agent API – /api/research/...
        # ══════════════════════════════════════════════════════════════════════

        @app.route('/api/research/report-status')
        def research_report_status():
            """Prüft ob research_report.md auf LYRA wartet."""
            report_path = os.path.join(
                os.path.expanduser("~"), ".openclaw", "workspace", "research_report.md"
            )
            exists = os.path.isfile(report_path)
            mtime  = None
            if exists:
                mtime = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(os.path.getmtime(report_path))
                )
            return jsonify({
                "report_pending": exists,
                "report_path":    report_path,
                "written_at":     mtime
            })

        @app.route('/api/research/status')
        def research_status():
            """Status des Research Agent (Hypothesen, Aktivität, running)."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"running": False, "hypotheses": [], "activity": [],
                                "error": "ResearchAgent nicht initialisiert"})
            return jsonify(agent.get_status())

        @app.route('/api/research/hypothesis', methods=['POST'])
        def add_research_hypothesis():
            """Neue Hypothese hinzufügen – NUR Queue, sofortige Antwort."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503

            data = (request.get_json(silent=True, force=True) or {})
            if not data and request.data:
                try:
                    data = json.loads(request.data.decode('utf-8', errors='replace').lstrip('\ufeff'))
                except Exception:
                    data = {}

            hypothesis = (data.get('hypothesis') or '').strip()
            is_seed    = bool(data.get('is_seed', False))

            if not hypothesis:
                return jsonify({"error": "Kein Hypothesentext angegeben"}), 400

            # Hypothese in Queue – fertig. Agent-Loop verarbeitet den Rest.
            h = agent.add_hypothesis(hypothesis, priority=3 if is_seed else 1, is_seed=is_seed)

            if not agent.running:
                agent.start()

            resp = {"status": "added", "id": h.id, "text": h.text, "hypotheses_generated": 1}
            log(f"POST /hypothesis → returning: {resp['id']}", "INFO")
            return jsonify(resp)

        @app.route('/api/research/hypotheses')
        def get_research_hypotheses():
            """Alle aktiven Hypothesen als Liste."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"hypotheses": []})
            return jsonify({"hypotheses": agent.get_status()["hypotheses"]})

        @app.route('/api/research/dossiers')
        def list_research_dossiers():
            """Alle vorhandenen Dossiers."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"dossiers": []})
            return jsonify({"dossiers": agent.list_dossiers()})

        @app.route('/api/research/graph')
        def research_graph():
            """Gibt ASSOCIATE-Verbindungen aus Neo4j zurück für vis-Netzwerk."""
            dossier   = request.args.get('dossier', '')
            candidate = request.args.get('candidate', '')
            driver    = neo4j_mgr.get_driver()
            if driver is None:
                return jsonify({"nodes": [], "edges": []})
            try:
                with driver.session() as session:
                    if candidate:
                        # Kandidat: beide Knoten + ihre direkten Nachbarn
                        parts = candidate.split('|', 1)
                        p1 = parts[0].strip() if len(parts) > 0 else ''
                        p2 = parts[1].strip() if len(parts) > 1 else ''
                        # Erst exakter Match, dann CONTAINS als Fallback
                        result = session.run("""
                            MATCH (a)
                            WHERE toLower(a.name) CONTAINS toLower($p1)
                               OR toLower(a.name) CONTAINS toLower($p2)
                            WITH a LIMIT 10
                            OPTIONAL MATCH (a)-[r]-(b)
                            RETURN a, r, b LIMIT 120
                        """, p1=p1[:60], p2=p2[:60])
                    elif dossier:
                        # Dossier: lese Inhalt und extrahiere Entitätsnamen
                        agent = getattr(neo4j_mgr, '_research_agent', None)
                        dossier_content = agent.get_dossier(dossier) if agent else None
                        keywords = []
                        if dossier_content:
                            # Extrahiere Namen aus "Neue Verbindungen" und "Erkenntnisse"
                            import re as _re
                            # Suche nach **Name** Patterns (fett in Markdown)
                            bold = _re.findall(r'\*\*([^*]{3,40})\*\*', dossier_content)
                            keywords = [k.strip() for k in bold if len(k.strip()) > 4][:8]
                        if not keywords:
                            # Fallback: Keywords aus Dossier-Name
                            clean = dossier.replace('_', ' ').replace('.md', '')
                            keywords = [w for w in clean.split() if len(w) > 4][:5]
                        if not keywords:
                            keywords = [dossier[:20]]
                        result = session.run("""
                            MATCH (a) WHERE any(kw IN $kws WHERE toLower(a.name) CONTAINS toLower(kw))
                            OPTIONAL MATCH (a)-[r]-(b)
                            RETURN a, r, b LIMIT 100
                        """, kws=keywords)
                    else:
                        # Standard: letzte ASSOCIATE-Verbindungen
                        result = session.run("""
                            MATCH (a)-[r:ASSOCIATE]-(b)
                            RETURN a, r, b
                            ORDER BY r.created_at DESC LIMIT 60
                        """)

                    nmap, elist = {}, []
                    type_colors = {
                        'Person':       '#ff4444',
                        'Entity':       '#ff8844',
                        'Intermediary': '#888888',
                        'Address':      '#aaaaaa',
                        'Country':      '#44ff88',
                        'Officer':      '#ffcc44',
                    }
                    for record in result:
                        for node in [record.get('a'), record.get('b')]:
                            if node is None:
                                continue
                            nid = node.element_id  # neo4j 5.x: element_id statt id
                            if nid not in nmap:
                                labels = list(node.labels)
                                color  = type_colors.get(labels[0] if labels else '', '#4488ff')
                                nmap[nid] = {
                                    "id":    nid,
                                    "label": node.get('name', str(nid))[:50],
                                    "color": color,
                                    "type":  labels[0] if labels else 'Unknown'
                                }
                        rel = record.get('r')
                        if rel:
                            sid = rel.start_node.element_id
                            eid = rel.end_node.element_id
                            if sid in nmap and eid in nmap:
                                elist.append({
                                    "from": sid,
                                    "to":   eid,
                                    "type": rel.type
                                })
                    return jsonify({"nodes": list(nmap.values()), "edges": elist})
            except Exception as e:
                return jsonify({"nodes": [], "edges": [], "error": str(e)})

        @app.route('/api/research/dossier/<path:name>')
        def get_research_dossier(name):
            """Inhalt eines Dossiers als Markdown/JSON."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            content = agent.get_dossier(name)
            if content is None:
                return jsonify({"error": "Dossier nicht gefunden"}), 404
            fmt = request.args.get('format', 'json')
            if fmt == 'md':
                from flask import Response
                return Response(content, mimetype='text/markdown; charset=utf-8')
            return jsonify({"name": name, "content": content})

        @app.route('/api/research/stop-seed/<seed_id>', methods=['POST'])
        def stop_seed(seed_id):
            """Stoppt einen Seed und alle pending Subhypothesen."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            result = agent.stop_seed(seed_id)
            return jsonify(result)

        @app.route('/api/research/queue-limit', methods=['POST'])
        def set_queue_limit():
            """Setzt das Queue-Limit für auto-generierte Hypothesen."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            data  = request.get_json(silent=True) or {}
            limit = int(data.get('limit', 30))
            agent.set_queue_limit(limit)
            return jsonify({"queue_limit": agent.queue_limit})

        @app.route('/api/research/pause', methods=['POST'])
        def pause_research():
            """Research Agent pausieren (Loop unterbricht nach aktuellem Zyklus)."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            agent.stop()
            return jsonify({"status": "paused"})

        @app.route('/api/research/resume', methods=['POST'])
        def resume_research():
            """Research Agent fortsetzen."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            if not agent.running:
                agent.start()
            return jsonify({"status": "running"})

        @app.route('/api/research/clear', methods=['POST'])
        def clear_research():
            """Hypothesen-Queue und Aktivitäts-Log zurücksetzen (Dossiers bleiben)."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            if agent is None:
                return jsonify({"error": "ResearchAgent nicht initialisiert"}), 503
            agent.clear()
            return jsonify({"status": "cleared"})

        @app.route('/api/research/suggestions')
        def get_research_suggestions():
            """Vorschläge für Seed-Fragen (DEFAULT_HYPOTHESES) für die Web-UI."""
            agent = getattr(neo4j_mgr, '_research_agent', None)
            suggestions = []
            if agent is not None:
                suggestions = agent.DEFAULT_HYPOTHESES
            return jsonify({"suggestions": suggestions})

        @app.route('/api/research/enhancer/start', methods=['POST'])
        def start_enhancer():
            """AI Enhancer auf explizite Anfrage starten."""
            enhancer = getattr(neo4j_mgr, '_enhancer_ref', None)
            if enhancer is None:
                return jsonify({"error": "AI Enhancer nicht verfügbar"}), 503
            if enhancer.running:
                return jsonify({"status": "already_running"})
            data     = request.get_json(silent=True) or {}
            interval = int(data.get("interval_seconds", 300))
            enhancer.start_background_loop(interval)
            log(f"AI Enhancer manuell gestartet (Intervall: {interval}s)", "SUCCESS")
            return jsonify({"status": "started", "interval_seconds": interval})

        @app.route('/research')
        def research_page():
            """Direktzugriff auf Research-Seite – setzt initial-tab auf 'research'."""
            return render_template_string(
                HTML_TEMPLATE.replace(
                    '<meta name="initial-tab" content="graph">',
                    '<meta name="initial-tab" content="research">',
                    1
                )
            )

        return app

    def start(self):
        """Startet den Flask-Server in einem Hintergrundthread."""
        self.app = self._create_app()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        time.sleep(2)
        self.log(f"Webserver gestartet auf http://127.0.0.1:{FLASK_PORT}", "SUCCESS")
        return True

    def _run(self):
        """Fuehrt den Flask-Server aus."""
        try:
            # Werkzeug Access-Log deaktivieren – verhindert Log-Spam bei 5s-Polling
            import logging
            logging.getLogger('werkzeug').setLevel(logging.ERROR)
            try:
                from waitress import serve
                serve(self.app, host='127.0.0.1', port=FLASK_PORT,
                      threads=16, channel_timeout=600)
            except ImportError:
                from werkzeug.serving import make_server
                self.server = make_server('127.0.0.1', FLASK_PORT, self.app, threaded=True)
                self.server.serve_forever()
        except Exception as e:
            self.log(f"Server-Fehler: {e}", "ERROR")

    def stop(self):
        """Stoppt den Flask-Server."""
        if self.server:
            self.server.shutdown()
            self.server = None
        self.log("Webserver gestoppt", "INFO")

    def open_browser(self):
        """Oeffnet den Standard-Browser."""
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")


class LYRAIntegration:
    """
    Integration mit bestehender LYRA-Instanz.
    """
    
    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda msg, lvl="INFO": print(f"[LYRA] {msg}"))
        self.gateway_url = f"http://127.0.0.1:{OPENCLAW_GATEWAY_PORT}"
        self.token = None
        
    def _read_token(self) -> str:
        """Liest das Gateway-Token aus der config."""
        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            token = config.get("gateway", {}).get("auth", {}).get("token", "")
            if token:
                return token
        except Exception:
            pass
        return "lyra-local-token"
    
    def send_to_lyra(self, message: str) -> Optional[str]:
        """Sendet eine Nachricht an LYRA und gibt die Antwort zurueck."""
        token = self._read_token()
        try:
            payload = {
                "message": message,
                "sessionId": "lyra-network-builder"
            }
            response = requests.post(
                f"{self.gateway_url}/api/v1/message",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=600
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("response", data.get("content", ""))
            else:
                self.log(f"LYRA API-Fehler: {response.status_code}", "WARNING")
                return None
        except Exception as e:
            self.log(f"LYRA-Kommunikation fehlgeschlagen: {e}", "WARNING")
            return None

    def check_gateway(self) -> bool:
        """Prueft ob das OpenClaw Gateway laeuft."""
        try:
            response = requests.get(f"{self.gateway_url}/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False


class LYRANetworkBuilder:
    """
    Hauptklasse fuer LYRA-NET - koordiniert alle Komponenten.
    Version 2.0.0 – inkl. autonomem Research Agent (Option C)
    """
    
    def __init__(self, log_fn=None):
        self._log_fn = log_fn
        self.neo4j = None
        self.importer = None
        self.ai_enhancer = None
        self.research_agent = None
        self.web_server = None
        self.lyra = None
        self.initialized = False
    
    _log_lock = threading.Lock()

    def log(self, message: str, level: str = "INFO"):
        """Loggt eine Nachricht mit Zeitstempel (thread-safe)."""
        ts = time.strftime("%H:%M:%S")
        icons = {"ERROR": "❌", "SUCCESS": "✅", "WARNING": "⚠️", "INFO": "📌"}
        icon = icons.get(level, "📌")
        with LYRANetworkBuilder._log_lock:
            print(f"[{ts}] {icon} [LYRA-NET] {message}")
    
    def initialize(self) -> bool:
        """Initialisiert alle Komponenten inkl. Research Agent."""
        self.log("Initialisiere LYRA-NET...")
        
        self.neo4j = Neo4jManager(log_fn=self.log)
        neo4j_ok = self.neo4j.install()
        
        if not neo4j_ok:
            if hasattr(self.neo4j, '_check_neo4j_online') and self.neo4j._check_neo4j_online():
                if hasattr(self.neo4j, '_check_password') and self.neo4j._check_password():
                    self.log("Neo4j laeuft und ist erreichbar", "SUCCESS")
                    neo4j_ok = True
                else:
                    self.log("Neo4j laeuft aber Passwort ist falsch", "WARNING")
            else:
                self.log("Neo4j konnte nicht initialisiert werden!", "ERROR")
                return False
        
        if neo4j_ok:
            try:
                self.neo4j.init_schema()
                self.log("Neo4j Schema initialisiert ✓", "SUCCESS")
            except Exception as e:
                self.log(f"Schema-Initialisierung fehlgeschlagen (nicht kritisch): {e}", "WARNING")
        
        self.importer       = DataImporter(self.neo4j, log_fn=self.log)
        self.ai_enhancer    = AIGraphEnhancer(self.neo4j, log_fn=self.log)
        self.research_agent = ResearchAgent(self.neo4j, self.ai_enhancer, log_fn=self.log)
        self.web_server     = WebServer(self.neo4j, log_fn=self.log)
        self.lyra           = LYRAIntegration(log_fn=self.log)

        # Referenzen für API-Endpunkte
        self.neo4j._enhancer_ref      = self.ai_enhancer
        self.neo4j._research_agent    = self.research_agent
        
        self.initialized = True
        self.log("LYRA-NET Initialisierung abgeschlossen ✓", "SUCCESS")
        return True
    
    def import_data(self) -> bool:
        """Importiert alle ICIJ-Datensaetze."""
        if not self.initialized:
            self.log("System nicht initialisiert!", "ERROR")
            return False
        self.log("Starte Datenimport...")
        success = self.importer.import_icij_zip()
        if success:
            self.log("Datenimport abgeschlossen!", "SUCCESS")
        else:
            self.log("Datenimport fehlgeschlagen!", "ERROR")
        return success
    
    def start_webserver(self) -> bool:
        """Startet den Webserver fuer die Visualisierung."""
        if not self.initialized:
            self.log("System nicht initialisiert!", "ERROR")
            return False
        return self.web_server.start()
    
    def start_ai_enhancer(self, interval_seconds: int = 300) -> bool:
        """Startet den KI-gestuetzten Hintergrundloop."""
        if not self.initialized:
            self.log("System nicht initialisiert!", "ERROR")
            return False
        self.ai_enhancer.start_background_loop(interval_seconds)
        return True

    def start_research_agent(self, interval_minutes: int = 60) -> bool:
        """Startet den autonomen Research Agent als Hintergrundthread."""
        if not self.initialized:
            self.log("System nicht initialisiert!", "ERROR")
            return False
        self.research_agent.start(interval_minutes)
        self.log(f"Research Agent gestartet (Intervall: {interval_minutes} Min)", "SUCCESS")
        return True
    
    def print_summary(self):
        """Gibt eine Zusammenfassung des Systems aus."""
        self.log("=" * 70)
        self.log("LYRA-NET SYSTEM ZUSAMMENFASSUNG  v2.0.0")
        self.log("=" * 70)
        
        person_count = entity_count = edge_count = 0
        try:
            driver = self.neo4j.get_driver()
            with driver.session() as session:
                rec = session.run("MATCH (p:Person) RETURN count(p) AS cnt").single()
                person_count = rec["cnt"] if rec else 0
                rec = session.run("MATCH (e:Entity) RETURN count(e) AS cnt").single()
                entity_count = rec["cnt"] if rec else 0
                rec = session.run("MATCH ()-[r]->() RETURN count(r) AS cnt").single()
                edge_count = rec["cnt"] if rec else 0
        except Exception:
            pass
        
        ra_status = "inaktiv"
        if self.research_agent:
            hyp_count = len(self.research_agent.hypotheses)
            ra_status = f"{'aktiv' if self.research_agent.running else 'pausiert'} · {hyp_count} Hypothesen"

        self.log(f"  🗄️  Neo4j:           {person_count} Personen / {entity_count} Entitäten / {edge_count} Verbindungen")
        self.log(f"  🌐  Webserver:       http://127.0.0.1:{FLASK_PORT}")
        self.log(f"  🤖  AI Enhancer:     {'aktiv' if self.ai_enhancer and self.ai_enhancer.running else 'inaktiv'}")
        self.log(f"  🔬  Research Agent:  {ra_status}")
        self.log(f"  📁  Dossiers:        {self.research_agent.dossiers_dir if self.research_agent else '-'}")
        self.log(f"  🔗  LYRA Gateway:    {'online' if self.lyra and self.lyra.check_gateway() else 'offline'}")
        self.log(f"  🔬  Research UI:     http://127.0.0.1:{FLASK_PORT}/research")
        self.log("=" * 70)


def main():
    """
    Hauptfunktion - startet das gesamte LYRA-NET System.
    """
    print("\n" + "=" * 70)
    print("LYRA-NET – Semantische Netzwerk-Datenbank globaler Eliten")
    print("Version 2.0.0 – mit autonomem Research Agent (Option C)")
    print("=" * 70 + "\n")
    
    deps = ["pandas", "neo4j", "networkx", "flask", "requests", "werkzeug"]
    missing = []
    for dep in deps:
        try:
            __import__(dep.replace("-", "_"))
        except ImportError:
            missing.append(dep)
    
    if missing:
        print(f"Fehlende Abhaengigkeiten: {missing}")
        install = input("Sollen diese automatisch installiert werden? (j/n): ").lower()
        if install == 'j':
            for dep in missing:
                subprocess.run([sys.executable, "-m", "pip", "install", dep])
            print("Abhaengigkeiten installiert. Bitte starten Sie das Skript neu.")
            return
        else:
            print("Bitte installieren Sie die fehlenden Abhaengigkeiten manuell:")
            print(f"pip install {' '.join(missing)}")
            return
    
    builder = LYRANetworkBuilder()
    
    if not builder.initialize():
        print("Initialisierung fehlgeschlagen!")
        return
    
    print("\nMoechten Sie die ICIJ-Daten importieren?")
    print("  j = Daten importieren (erster Start, dauert 10-30 Minuten)")
    print("  n = Nur existierende Daten verwenden (falls bereits importiert)")
    import_choice = input("Auswahl (j/n): ").lower()
    
    if import_choice == 'j':
        if not builder.import_data():
            print("Datenimport fehlgeschlagen!")
            return
    
    builder.start_webserver()
    
    print("\nMoechten Sie den KI-gestuetzten Hintergrundloop starten?")
    print("  Der AI Enhancer sucht automatisch nach fehlenden Verbindungen")
    ai_choice = input("Auswahl (j/n): ").lower()
    if ai_choice == 'j':
        interval = input("Intervall in Sekunden (default: 300): ").strip()
        interval = int(interval) if interval else 300
        builder.start_ai_enhancer(interval)
    
    print("\nMoechten Sie den autonomen Research Agent starten?")
    print("  Der Research Agent generiert Hypothesen und erstellt lebende Dossiers")
    print("  (laeuft im Hintergrund, steuerbar via Web-UI > 🔬 Research)")
    ra_choice = input("Auswahl (j/n): ").lower()
    if ra_choice == 'j':
        ra_interval = input("Intervall in Minuten (default: 60): ").strip()
        ra_interval = int(ra_interval) if ra_interval else 60
        builder.start_research_agent(ra_interval)
    
    builder.print_summary()
    
    print("\nOeffne Browser mit Graph-Visualisierung...")
    builder.web_server.open_browser()
    
    print("\nLYRA-NET laeuft im Hintergrund.")
    print(f"  Graph:    http://127.0.0.1:{FLASK_PORT}")
    print(f"  Research: http://127.0.0.1:{FLASK_PORT}/research")
    print("Druecken Sie Ctrl+C zum Beenden.")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\nShutdown LYRA-NET...")
        if builder.research_agent and builder.research_agent.running:
            builder.research_agent.stop()
        if builder.ai_enhancer:
            builder.ai_enhancer.stop()
        builder.web_server.stop()
        builder.neo4j.close()
        print("LYRA-NET beendet.")


def main_auto():
    """
    Vollautomatischer Start ohne jede Benutzerabfrage.
    Gestartet von OpenClawWinInstaller via: python lyra_network_builder.py --auto

    Entscheidungslogik:
      1. Fehlende Python-Deps  → pip install, direkter Reimport (kein Neustart)
      2. Java fehlt            → winget install Temurin 21 JRE, dann weiter
      3. Neo4j nicht online    → Neo4jManager.install() (Download + Start, bereits autonom)
      4. Datenbank leer        → ICIJ-Import automatisch starten
      5. Alles bereit          → Webserver + AI Enhancer (300s) + Research Agent (60min)
      6. Browser öffnen        → http://127.0.0.1:18800/research
    """
    _auto_log("=" * 70)
    _auto_log("LYRA-NET – Autonomer Start (--auto)")
    _auto_log("Version 2.0.0 – Research Agent Mode")
    _auto_log("=" * 70)

    # ── Schritt 1: Python-Abhängigkeiten ─────────────────────────────────────
    deps = ["pandas", "neo4j", "networkx", "flask", "requests", "werkzeug", "waitress"]

    # Marker-File: einmal installiert = nie wieder prüfen
    marker = os.path.join(os.path.expanduser("~"), ".openclaw", ".lyranet_deps_ok")
    missing = []
    if not os.path.isfile(marker):
        # Nur prüfen via direkten Import-Test – pip show ist zu langsam
        for d in deps:
            try:
                __import__(d.replace("-", "_"))
            except ImportError:
                missing.append(d)

    if missing:
        _auto_log(f"Installiere fehlende Pakete: {missing}")
        for dep in missing:
            _auto_log(f"  pip install {dep} ...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", dep, "--quiet"],
                capture_output=True, text=True
            )
        _auto_log("Python-Pakete installiert ✓", "SUCCESS")

    # Marker schreiben – verhindert pip-Check bei jedem nächsten Start
    if not os.path.isfile(marker):
        try:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            open(marker, 'w').close()
        except Exception:
            pass

    # ── Schritt 2: Java prüfen und ggf. installieren ─────────────────────────
    if not _auto_detect_java():
        _auto_log("Java 11+ nicht gefunden – starte automatische Installation...")
        if not _auto_install_java():
            _auto_log("Java-Installation fehlgeschlagen!", "ERROR")
            _auto_log("Bitte manuell installieren: winget install EclipseAdoptium.Temurin.21.JRE")
            # Trotzdem weiter – vielleicht läuft Neo4j bereits als Dienst
        else:
            _auto_log("Java installiert ✓", "SUCCESS")

    # ── Schritt 3: Builder initialisieren (Neo4j auto-install inklusive) ──────
    builder = LYRANetworkBuilder()

    if not builder.initialize():
        _auto_log("Initialisierung fehlgeschlagen!", "ERROR")
        _auto_log("Prüfe: Java installiert? Neo4j-Dienst aktiv?")
        input("Drücke Enter zum Beenden...")
        return

    # ── Schritt 4: Datenbank-Leer-Check → ggf. ICIJ-Import ──────────────────
    node_count = 0
    try:
        driver = builder.neo4j.get_driver()
        with driver.session() as session:
            rec = session.run("MATCH (n) RETURN count(n) AS cnt").single()
            node_count = rec["cnt"] if rec else 0
    except Exception as e:
        _auto_log(f"Datenbank-Check Fehler: {e}", "WARNING")

    _auto_log(f"Datenbank: {node_count} Knoten vorhanden")

    if node_count < 1000:
        _auto_log("Datenbank leer – starte ICIJ-Import automatisch...")
        _auto_log("(Dauert 10–30 Minuten – Fenster bitte offen lassen)")
        if not builder.import_data():
            _auto_log("ICIJ-Import fehlgeschlagen – weiter mit leerer Datenbank", "WARNING")
        else:
            _auto_log("ICIJ-Import abgeschlossen ✓", "SUCCESS")
    else:
        _auto_log(f"Datenbank bereit ✓", "SUCCESS")

    # ── Schritt 5a: Webserver ────────────────────────────────────────────────
    builder.start_webserver()

    # ── Schritt 5b: AI Enhancer – NICHT automatisch starten ──────────────────
    # Der AIGraphEnhancer durchsucht alle 2M Datensätze nach Adress-Verbindungen.
    # Das ist willkürliche Massenarbeit. Er startet nur auf explizite Anfrage:
    #   - Manuell im interaktiven main()-Modus (j/n-Abfrage)
    #   - Oder via Web-UI wenn der Benutzer es bewusst aktiviert
    # builder.start_ai_enhancer() wird hier bewusst NICHT aufgerufen.
    _auto_log("AI Enhancer bereit (wartet auf explizite Aktivierung via Web-UI)")

    # ── Schritt 5c: Research Agent starten – wartet auf Benutzeranfrage ───────
    # Der Agent registriert sich und hält den Thread bereit.
    # Er beginnt erst zu arbeiten wenn LYRA oder der Benutzer eine
    # Seed-Frage über die Web-UI oder /api/research/hypothesis sendet.
    builder.start_research_agent(interval_minutes=60)
    _auto_log("Research Agent bereit – wartet auf Benutzeranfrage ✓", "SUCCESS")

    # ── Schritt 5d: research_query.ps1 schreiben ─────────────────────────────
    _auto_write_research_query_ps1()

    # ── Schritt 6: Zusammenfassung ───────────────────────────────────────────
    builder.print_summary()

    _auto_log(f"Bereit: http://127.0.0.1:{FLASK_PORT}/research")
    _auto_log(f"Graph:  http://127.0.0.1:{FLASK_PORT}")
    _auto_log("LYRA-NET läuft. Fenster minimieren, nicht schliessen.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        _auto_log("Shutdown LYRA-NET...")
        if builder.research_agent and builder.research_agent.running:
            builder.research_agent.stop()
        if builder.ai_enhancer:
            builder.ai_enhancer.stop()
        builder.web_server.stop()
        builder.neo4j.close()
        _auto_log("LYRA-NET beendet.")


# ── Hilfsfunktionen für main_auto() ──────────────────────────────────────────

def _auto_write_research_query_ps1():
    """Schreibt research_query.ps1 in den OpenClaw-Workspace."""
    workspace = os.path.join(os.path.expanduser("~"), ".openclaw", "workspace")
    os.makedirs(workspace, exist_ok=True)
    ps1_path = os.path.join(workspace, "research_query.ps1")
    ps1_content = (
        'param(\r\n'
        '    [string]$hypothesis = $env:RESEARCH_HYPOTHESIS,\r\n'
        '    [string]$source     = "lyra",\r\n'
        '    [string]$baseUrl    = "http://127.0.0.1:18800"\r\n'
        ')\r\n'
        'if (-not $hypothesis) { Write-Host "[ERROR] Kein hypothesis-Parameter"; exit 1 }\r\n'
        'try {\r\n'
        '    Invoke-RestMethod -Uri "$baseUrl/api/health" -TimeoutSec 3 | Out-Null\r\n'
        '    Write-Host "[OK] LYRA-NET erreichbar"\r\n'
        '} catch {\r\n'
        '    Write-Host "[ERROR] LYRA-NET nicht erreichbar auf $baseUrl"\r\n'
        '    exit 1\r\n'
        '}\r\n'
        # Body als UTF-8 Bytes senden – verhindert Umlaut-Verlust
        '$b = [ordered]@{ hypothesis = $hypothesis; is_seed = $true; source = $source } | ConvertTo-Json -Compress\r\n'
        '$bytes = [System.Text.Encoding]::UTF8.GetBytes($b)\r\n'
        'try {\r\n'
        '    $r = Invoke-RestMethod -Uri "$baseUrl/api/research/hypothesis" -Method POST -ContentType "application/json; charset=utf-8" -Body $bytes\r\n'
        '    Write-Host "[OK] Gestartet: $($r.hypotheses_generated) Hypothesen | ID: $($r.id)"\r\n'
        '} catch {\r\n'
        '    Write-Host "[ERROR] POST fehlgeschlagen: $_"\r\n'
        '    exit 1\r\n'
        '}\r\n'
    )
    try:
        # utf-8-sig = UTF-8 mit BOM – PowerShell liest Umlaute korrekt
        with open(ps1_path, "w", encoding="utf-8-sig") as f:
            f.write(ps1_content)
        _auto_log(f"research_query.ps1 geschrieben: {ps1_path}", "SUCCESS")
    except Exception as e:
        _auto_log(f"research_query.ps1 Fehler: {e}", "WARNING")


def _auto_log(msg: str, level: str = "INFO"):
    """Einfaches Logging für den Auto-Modus."""
    icons = {"ERROR": "❌", "SUCCESS": "✅", "WARNING": "⚠️", "INFO": "📌"}
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {icons.get(level, '📌')} [AUTO] {msg}", flush=True)


def _auto_can_import(module: str) -> bool:
    """Prüft ob ein Paket installiert ist (via pip show, nicht Import)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", module.replace("-", "_")],
            capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def _auto_detect_java() -> bool:
    """Prüft ob Java 11+ verfügbar ist."""
    try:
        r = subprocess.run(["java", "-version"], capture_output=True, text=True,
                           timeout=10, creationflags=0x08000000)
        out = (r.stdout + r.stderr).lower()
        if any(v in out for v in ["11.", "12.", "13.", "14.", "15.", "16.", "17.",
                                   "18.", "19.", "20.", "21.", "22.", "23.", "24."]):
            return True
    except Exception:
        pass
    # JAVA_HOME Fallback
    jh = os.environ.get("JAVA_HOME", "")
    if jh and os.path.isfile(os.path.join(jh, "bin", "java.exe")):
        return True
    return False


def _auto_install_java() -> bool:
    """
    Installiert Eclipse Temurin 21 JRE via winget (Windows, silent).
    Erweitert danach PATH um den typischen Temurin-Installationspfad.
    """
    _auto_log("winget install EclipseAdoptium.Temurin.21.JRE ...")
    try:
        result = subprocess.run(
            ["winget", "install", "--id", "EclipseAdoptium.Temurin.21.JRE",
             "--accept-package-agreements", "--accept-source-agreements", "--silent"],
            capture_output=True, text=True, timeout=300,
            creationflags=0x08000000
        )
        _auto_log(f"winget exit: {result.returncode}")
        if result.stdout.strip():
            _auto_log(result.stdout[:200])
        # 0 = OK, -1978335189 (0x8A150101) = already installed
        if result.returncode in (0, -1978335189):
            import glob
            for pattern in [
                r"C:\Program Files\Eclipse Adoptium\jre-21*\bin",
                r"C:\Program Files\Eclipse Adoptium\jdk-21*\bin",
                r"C:\Program Files\Microsoft\jdk-21*\bin",
            ]:
                matches = glob.glob(pattern)
                if matches:
                    os.environ["PATH"] = matches[0] + ";" + os.environ.get("PATH", "")
                    _auto_log(f"PATH += {matches[0]}")
                    break
            return True
        _auto_log(f"winget stderr: {result.stderr[:200]}", "WARNING")
        return False
    except FileNotFoundError:
        _auto_log("winget nicht gefunden", "ERROR")
        return False
    except Exception as e:
        _auto_log(f"Java-Install Fehler: {e}", "ERROR")
        return False


if __name__ == "__main__":
    if "--auto" in sys.argv:
        main_auto()
    else:
        main()
