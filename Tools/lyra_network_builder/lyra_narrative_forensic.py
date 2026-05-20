"""
lyra_narrative.py  –  LYRA Narrative Forensics  v0.1.0
═══════════════════════════════════════════════════════
Forensisches Werkzeug zur Analyse von Informationskriegs-Narrativen.
Forensic tool for the analysis of information-warfare narratives.

Ziel / Goal:
  Akteure identifizieren die wiederholt als Ursprung oder frühe Verstärker
  verschiedener Narrative auftauchen – über Zeit, über Plattformen, über
  gelöschte/archivierte Quellen hinweg.
  Identify actors that repeatedly appear as origin or early amplifiers of
  multiple narratives – across time, platforms and deleted/archived sources.

Architektur / Architecture:
  - Eigene Neo4j-Datenbank (Port 7687)   / Dedicated Neo4j database (port 7687)
  - Eigener Flask-Server (Port 18801)    / Dedicated Flask server (port 18801)
  - Teilt Ollama (11434) und SearXNG (8080) mit lyra_network_builder
    / Shares Ollama (11434) and SearXNG (8080) with lyra_network_builder
  - Keine Cross-Contamination mit ICIJ-Daten / No cross-contamination with ICIJ data

Konventionen: identisch zu lyra_network_builder.py
Conventions : identical to lyra_network_builder.py
"""

import os
import sys
import json
import time
import random
import threading
import hashlib
import re
import uuid
import requests
import subprocess
import tempfile
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Neo4j Warnings für leere DB unterdrücken (normal beim ersten Start)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# ── Konstanten / Constants ────────────────────────────────────────────────────

VERSION             = "0.1.0"
FLASK_PORT          = 18801          # Separater Port – kein Konflikt mit LYRA-NET / Separate port – no conflict with LYRA-NET
NEO4J_PORT          = 7687           # Gleiche Neo4j-Instanz wie LYRA-NET / Same Neo4j instance as LYRA-NET
NEO4J_BOLT          = f"bolt://127.0.0.1:{NEO4J_PORT}"
NEO4J_USER          = "neo4j"
NEO4J_PASSWORD      = "lyra_network_2026"   # Gleiches Passwort wie LYRA-NET / Same password as LYRA-NET
OLLAMA_URL          = "http://127.0.0.1:11434/api/chat"
SEARXNG_URL         = "http://127.0.0.1:8080/search"
ARCHIVE_API         = "http://archive.org/wayback/available"
OPENCLAW_PORT       = 18789

WORKSPACE           = Path.home() / ".openclaw" / "workspace"
NARRATIVE_DIR       = WORKSPACE / "narratives"
CORPUS_DIR          = WORKSPACE / "corpus"        # Manuelle Artefakt-Einspeisung / Manual artifact ingestion
NARRATIVE_DB_FILE   = WORKSPACE / "narrative_queue.json"

# ── Knotentypen (Neo4j Labels) / Node types ───────────────────────────────────
#
#   Actor        – Wer / Who: Person, Account, Medium, Organisation, Botnetz/Botnet
#   Narrative    – Was / What: Die Aussage, das Meme, das Framing / The claim, meme, framing
#   SpreadEvent  – Wann/Wo / When/Where: Konkrete Verbreitungsinstanz / Concrete spread instance
#   Platform     – Twitter, Reddit, 4chan, Telegram, Blog etc.
#   Artifact     – Konkretes Dokument/Screenshot/Archiv-Snapshot / Concrete document/screenshot/archive snapshot
#
# Kantentypen / Edge types:
#   ORIGINATED   – Akteur → Narrativ (älteste bekannte Quelle / oldest known source)
#   AMPLIFIED    – Akteur → Narrativ (Weiterverbreitung / amplification)
#   COORDINATES_WITH – Akteur → Akteur (Koordinationsindiz / coordination signal)
#   SUPPORTS     – Narrativ → Narrativ (semantische Verwandtschaft / semantic similarity)
#   CONTRADICTS  – Narrativ → Narrativ
#   APPEARED_ON  – SpreadEvent → Platform
#   ARCHIVED_AT  – Artifact → URL (Wayback-Link)
#   QUOTES       – SpreadEvent → SpreadEvent (direktes Zitat / direct quote)
#   INSPIRED_BY  – SpreadEvent → SpreadEvent (semantisch ähnlich, nicht identisch / semantically similar, not identical)


# ── Hilfsfunktionen / Helper functions ───────────────────────────────────────

def _ts() -> str:
    return time.strftime("%H:%M:%S")

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _fingerprint(text: str) -> str:
    """Kurzer semantischer Fingerabdruck für Duplikat-Erkennung.
    Short semantic fingerprint for duplicate detection."""
    clean = re.sub(r'\s+', ' ', text.lower().strip())
    return hashlib.sha256(clean[:500].encode()).hexdigest()[:16]


# ── Neo4j-Manager ─────────────────────────────────────────────────────────────

class NarrativeNeo4j:
    """
    Neo4j-Datenbank für Narrative-Forensik.
    Neo4j database for narrative forensics.

    Neues Schema: Platform → Article → Actor, mit Stance und Cluster-Logik.
    New schema : Platform → Article → Actor, with stance and cluster logic.

    Knotentypen / Node types:
      NF_Narrative   – das untersuchte Narrativ (Seed) / the investigated narrative (seed)
      NF_Platform    – Twitter, Reddit, 4chan etc. (Cluster-Zentrum / cluster centre)
      NF_Article     – Artikel, Thread, Post (hängt an Platform / attached to platform)
      NF_Actor       – Person, Account, Organisation (Autor oder Kommentator / author or commenter)
      NF_Comment     – Kommentar (hängt an Article, hat Actor / attached to article, has actor)

    Kantentypen / Edge types:
      PUBLISHED_ON   – Article → Platform
      AUTHORED_BY    – Article → Actor (Autor / author)
      COMMENTED_BY   – Comment → Actor
      PART_OF        – Comment → Article
      SPREADS        – Actor → Narrative (mit stance: supporting|opposing|neutral, confidence)
      LINKS_TO       – Actor → Platform (wenn Link im Text / when link found in text)
      COORDINATES_WITH – Actor → Actor (Koordinationsindiz / coordination signal)
      SUPPORTS       – Narrative → Narrative
    """

    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [NEO4J-N] {m}"))
        self._driver = None

    def connect(self) -> bool:
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(
                NEO4J_BOLT, auth=(NEO4J_USER, NEO4J_PASSWORD),
                connection_timeout=10
            )
            self._driver.verify_connectivity()
            self.log("Narrative database connected ✓", "SUCCESS")
            return True
        except Exception as e:
            self.log(f"Narrative-DB nicht erreichbar: {e}", "WARNING")
            self.log("Starting without persistent database (in-memory mode)", "WARNING")
            return False

    def get_driver(self):
        return self._driver

    def init_schema(self):
        if not self._driver:
            return
        try:
            with self._driver.session() as s:
                for label, prop in [
                    ("NF_Narrative", "uid"), ("NF_Platform", "uid"),
                    ("NF_Article",   "uid"), ("NF_Actor",    "uid"),
                    ("NF_Comment",   "uid"),
                ]:
                    try:
                        s.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.uid IS UNIQUE")
                    except Exception:
                        pass
            self.log("Schema initialised ✓", "SUCCESS")
        except Exception as e:
            self.log(f"Schema init failed: {e}", "WARNING")

    def close(self):
        if self._driver:
            self._driver.close()

    def _run(self, query: str, **params) -> bool:
        """Führt einen Schreib-Query aus, gibt True bei Erfolg."""
        if not self._driver:
            return False
        try:
            with self._driver.session() as s:
                s.run(query, **params)
            return True
        except Exception as e:
            self.log(f"DB error: {e}", "WARNING")
            return False

    # ── Narrative ─────────────────────────────────────────────────────────────

    def upsert_narrative(self, uid: str, text: str, inv_uid: str,
                         first_seen: str = "") -> bool:
        return self._run("""
            MERGE (n:NF_Narrative {uid: $uid})
            SET n.text       = $text,
                n.inv_uid    = $inv_uid,
                n.first_seen = $first_seen,
                n.updated    = $now
        """, uid=uid, text=text[:2000], inv_uid=inv_uid,
             first_seen=first_seen, now=_now_iso())

    # ── Platform ──────────────────────────────────────────────────────────────

    def upsert_platform(self, name: str, url: str = "", inv_uid: str = "") -> str:
        """Erstellt/updated Platform-Knoten. Gibt uid zurück.
        Creates/updates a Platform node. Returns uid."""
        # Tracking/Asset/Cookie-Domains nicht als Platform speichern
        reject_names = {
            'google-analytics', 'googletagmanager', 'onetrust', 'geolocation.onetrust',
            'cookielaw', 'doubleclick', 'googlesyndication', 'googleadservices',
            'facebook.net', 'fbcdn', 'twimg', 'cloudflare', 'fastly', 'akamai',
            'jquery', 'bootstrap', 'cdnjs', 'jsdelivr', 'unpkg',
        }
        reject_url_patterns = (
            'google-analytics.com', 'googletagmanager.com', 'onetrust.com',
            'geolocation.onetrust', 'doubleclick.net', 'cookielaw.org',
        )
        name_lower = name.lower()
        if name_lower in reject_names or any(p in url.lower() for p in reject_url_patterns):
            # Gib eine Dummy-UID zurück ohne in DB zu schreiben
            return f"plat_rejected_{_fingerprint(name)}"

        uid = f"plat_{_fingerprint(name)}"
        self._run("""
            MERGE (p:NF_Platform {uid: $uid})
            SET p.name    = $name,
                p.url     = $url,
                p.inv_uid = $inv_uid,
                p.updated = $now
        """, uid=uid, name=name, url=url, inv_uid=inv_uid, now=_now_iso())
        return uid

    # ── Article/Thread ────────────────────────────────────────────────────────

    def upsert_article(self, uid: str, title: str, url: str,
                       platform_uid: str, date: str,
                       inv_uid: str, stance: str = "neutral",
                       stance_confidence: float = 0.5) -> bool:
        """Artikel/Thread – hängt an Platform.
        Article/Thread node – attached to a Platform node."""
        ok = self._run("""
            MERGE (a:NF_Article {uid: $uid})
            SET a.title             = $title,
                a.url               = $url,
                a.date              = $date,
                a.inv_uid           = $inv_uid,
                a.stance            = $stance,
                a.stance_confidence = $sc,
                a.updated           = $now
            WITH a
            MERGE (p:NF_Platform {uid: $puid})
            ON CREATE SET p.inv_uid = $inv_uid, p.updated = $now
            MERGE (a)-[r:PUBLISHED_ON]->(p)
            ON CREATE SET r.created = $now
        """, uid=uid, title=title[:200], url=url[:500],
             date=date, inv_uid=inv_uid, stance=stance, sc=stance_confidence,
             puid=platform_uid, now=_now_iso())
        return ok

    # ── Actor ─────────────────────────────────────────────────────────────────

    def upsert_actor(self, uid: str, name: str, platform_name: str,
                     actor_type: str, first_seen: str,
                     confidence: float, inv_uid: str,
                     stance: str = "neutral",
                     stance_confidence: float = 0.5,
                     source_url: str = "",
                     is_author: bool = False,
                     is_editor: bool = False) -> bool:
        return self._run("""
            MERGE (a:NF_Actor {uid: $uid})
            SET a.name              = $name,
                a.platform          = $platform,
                a.type              = $type,
                a.first_seen        = CASE
                    WHEN $first_seen <> '' AND ($first_seen < coalesce(a.first_seen, '9999') OR coalesce(a.first_seen,'') = '')
                    THEN $first_seen
                    ELSE coalesce(a.first_seen, $first_seen)
                END,
                a.confidence        = CASE WHEN $confidence > coalesce(a.confidence, 0) THEN $confidence ELSE a.confidence END,
                a.inv_uid           = $inv_uid,
                a.stance            = $stance,
                a.stance_confidence = $sc,
                a.url               = CASE WHEN $url <> '' THEN $url ELSE coalesce(a.url,'') END,
                a.is_author         = CASE WHEN $is_author = true THEN true ELSE coalesce(a.is_author, false) END,
                a.is_editor         = CASE WHEN $is_editor = true THEN true ELSE coalesce(a.is_editor, false) END,
                a.updated           = $now
        """, uid=uid, name=name[:200], platform=platform_name,
             type=actor_type, first_seen=first_seen,
             confidence=confidence, inv_uid=inv_uid,
             stance=stance, sc=stance_confidence,
             url=source_url[:500], is_author=is_author,
             is_editor=is_editor, now=_now_iso())

    def platform_spreads_narrative(self, platform_uid: str, narrative_uid: str) -> bool:
        """Platform spreads narrative – visible edge in visualization."""
        if not self._driver:
            return False
        try:
            with self._driver.session() as s:
                r = s.run("""
                    OPTIONAL MATCH (p:NF_Platform {uid: $puid})
                    OPTIONAL MATCH (n:NF_Narrative {uid: $nuid})
                    WITH p, n WHERE p IS NOT NULL AND n IS NOT NULL
                    MERGE (p)-[r:SPREADS]->(n)
                    ON CREATE SET r.created = $now
                    RETURN r.created = $now AS is_new,
                           p.name AS pname, n.text AS ntext
                """, puid=platform_uid, nuid=narrative_uid, now=_now_iso()).single()
                if r and r["is_new"]:
                    self.log(f"  🔗 SPREADS (new)  {(r['pname'] or platform_uid[:12]):20} → {(r['ntext'] or narrative_uid[:12])[:30]}")
            return True
        except Exception as e:
            self.log(f"DB error: {e}", "WARNING")
            return False

    def actor_spreads_narrative(self, actor_uid: str, narrative_uid: str,
                                 role: str, stance: str,
                                 confidence: float, date: str, url: str) -> bool:
        """Actor verbreitet Narrativ – Hauptkante mit Stance.
        Actor spreads narrative – primary edge with stance."""
        return self._run("""
            OPTIONAL MATCH (a:NF_Actor {uid: $auid})
            OPTIONAL MATCH (n:NF_Narrative {uid: $nuid})
            WITH a, n
            WHERE a IS NOT NULL AND n IS NOT NULL
            MERGE (a)-[r:SPREADS]->(n)
            SET r.role       = CASE
                    WHEN $role = 'ORIGIN' THEN 'ORIGIN'
                    WHEN coalesce(r.role,'') = 'ORIGIN' THEN 'ORIGIN'
                    ELSE $role END,
                r.stance     = $stance,
                r.confidence = CASE WHEN $confidence > coalesce(r.confidence,0) THEN $confidence ELSE r.confidence END,
                r.date       = CASE
                    WHEN $date <> '' AND ($date < coalesce(r.date,'9999') OR coalesce(r.date,'') = '')
                    THEN $date
                    ELSE coalesce(r.date, $date) END,
                r.url        = CASE WHEN $url <> '' THEN $url ELSE coalesce(r.url,'') END,
                r.updated    = $now
        """, auid=actor_uid, nuid=narrative_uid, role=role,
             stance=stance, confidence=confidence,
             date=date, url=url[:500], now=_now_iso())

    def actor_authored_article(self, actor_uid: str, article_uid: str) -> bool:
        return self._run("""
            OPTIONAL MATCH (a:NF_Actor {uid: $auid})
            OPTIONAL MATCH (art:NF_Article {uid: $artuid})
            WITH a, art WHERE a IS NOT NULL AND art IS NOT NULL
            MERGE (art)-[:AUTHORED_BY]->(a)
        """, auid=actor_uid, artuid=article_uid)

    def upsert_comment(self, uid: str, article_uid: str, actor_uid: str,
                        date: str, text: str, score: int,
                        inv_uid: str, stance: str = "neutral") -> bool:
        return self._run("""
            MERGE (c:NF_Comment {uid: $uid})
            SET c.date     = $date,
                c.text     = $text,
                c.score    = $score,
                c.inv_uid  = $inv_uid,
                c.stance   = $stance,
                c.updated  = $now
            WITH c
            OPTIONAL MATCH (art:NF_Article {uid: $artuid})
            OPTIONAL MATCH (a:NF_Actor {uid: $auid})
            FOREACH(_ IN CASE WHEN art IS NOT NULL THEN [1] ELSE [] END |
                MERGE (c)-[:PART_OF]->(art))
            FOREACH(_ IN CASE WHEN a IS NOT NULL THEN [1] ELSE [] END |
                MERGE (c)-[:COMMENTED_BY]->(a))
        """, uid=uid, artuid=article_uid, auid=actor_uid,
             date=date, text=text[:500], score=score,
             inv_uid=inv_uid, stance=stance, now=_now_iso())

    def actor_links_to_platform(self, actor_uid: str, platform_uid: str) -> bool:
        return self._run("""
            OPTIONAL MATCH (a:NF_Actor {uid: $auid})
            OPTIONAL MATCH (p:NF_Platform {uid: $puid})
            WITH a, p WHERE a IS NOT NULL AND p IS NOT NULL
            MERGE (a)-[:LINKS_TO]->(p)
        """, auid=actor_uid, puid=platform_uid)

    def link_actors(self, uid_a: str, uid_b: str,
                    evidence: str, confidence: float) -> bool:
        return self._run("""
            OPTIONAL MATCH (a:NF_Actor {uid: $a})
            OPTIONAL MATCH (b:NF_Actor {uid: $b})
            WITH a, b WHERE a IS NOT NULL AND b IS NOT NULL
            MERGE (a)-[r:COORDINATES_WITH]->(b)
            SET r.evidence   = $evidence,
                r.confidence = $confidence,
                r.updated    = $now
        """, a=uid_a, b=uid_b, evidence=evidence[:500],
             confidence=confidence, now=_now_iso())

    # ── Lese-Operationen / Read operations ───────────────────────────────────

    def get_graph_data(self, mode: str = "actor",
                       inv_uid: str = None,
                       max_nodes: int = 300) -> dict:
        """Graph-Daten für vis-network."""
        if not self._driver:
            return {"nodes": [], "edges": [], "origin_uid": None}

        nodes, edges = [], []
        seen_n, seen_e = set(), set()
        origin_uid = None

        color_map = {
            "NF_Narrative": "#00aaff",
            "NF_Platform":  "#44ff88",
            "NF_Article":   "#ffaa44",
            "NF_Actor":     "#ff4444",
            "NF_Comment":   "#aa44ff",
        }
        shape_map = {
            "NF_Narrative": "star",
            "NF_Platform":  "diamond",
            "NF_Article":   "square",
            "NF_Actor":     "dot",
            "NF_Comment":   "triangle",
        }

        def node_id(node):
            return node.get("uid") or node.element_id

        def add_node(node):
            nid = node_id(node)
            if nid in seen_n:
                return nid
            seen_n.add(nid)
            lbl = list(node.labels)[0] if node.labels else "Unknown"
            name = node.get("name") or node.get("title") or node.get("text") or str(nid)
            date = str(node.get("first_seen") or node.get("date") or "")
            stance = node.get("stance") or "neutral"
            nodes.append({
                "id": nid,
                "label": str(name)[:40],
                "group": lbl,
                "color": color_map.get(lbl, "#888"),
                "shape": shape_map.get(lbl, "dot"),
                "title": f"{lbl}\n{str(name)[:200]}\nStance: {stance}\n{date}",
                "date": date,
                "stance": stance,
                "is_author": bool(node.get("is_author", False)),
                "is_editor": bool(node.get("is_editor", False)),
                "full": dict(node),
            })
            return nid

        def add_edge(a, rel_type, b):
            sid = node_id(a)
            tid = node_id(b)
            eid = f"{sid}→{rel_type}→{tid}"
            if eid not in seen_e:
                seen_e.add(eid)
                edges.append({"from": sid, "to": tid, "label": rel_type, "arrows": "to"})

        try:
            with self._driver.session() as s:
                # Knoten laden
                if inv_uid:
                    result = s.run("""
                        MATCH (n)
                        WHERE any(l IN labels(n) WHERE l STARTS WITH 'NF_')
                        AND n.inv_uid = $inv_uid
                        RETURN n LIMIT $limit
                    """, inv_uid=inv_uid, limit=max_nodes * 2)
                else:
                    result = s.run("""
                        MATCH (n)
                        WHERE any(l IN labels(n) WHERE l STARTS WITH 'NF_')
                        RETURN n LIMIT $limit
                    """, limit=max_nodes * 2)

                # Origin finden
                if inv_uid:
                    origin_rec = s.run("""
                        MATCH (n:NF_Actor)
                        WHERE n.inv_uid = $inv_uid
                        AND n.first_seen IS NOT NULL AND n.first_seen <> ''
                        WITH n ORDER BY n.first_seen ASC LIMIT 1
                        RETURN n
                    """, inv_uid=inv_uid).single()
                else:
                    origin_rec = s.run("""
                        MATCH (n:NF_Actor)
                        WHERE n.first_seen IS NOT NULL AND n.first_seen <> ''
                        ORDER BY n.first_seen ASC LIMIT 1
                        RETURN n
                    """).single()

                if origin_rec:
                    origin_uid = node_id(origin_rec["n"])
                    add_node(origin_rec["n"])

                for rec in result:
                    add_node(rec["n"])

                # ============================================================
                # ALLE KANTEN LADEN - KEINE FILTERUNG!
                # ============================================================
                edge_queries = [
                    "MATCH (a:NF_Platform)-[r:SPREADS]->(b:NF_Narrative) RETURN a, r, b",
                    "MATCH (a:NF_Actor)-[r:SPREADS]->(b:NF_Narrative) RETURN a, r, b",
                    "MATCH (a:NF_Actor)-[r:LINKS_TO]->(b:NF_Platform) RETURN a, r, b",
                    "MATCH (a:NF_Actor)-[r:COORDINATES_WITH]->(b:NF_Actor) RETURN a, r, b",
                    "MATCH (a:NF_Article)-[r:AUTHORED_BY]->(b:NF_Actor) RETURN a, r, b",
                    "MATCH (a:NF_Article)-[r:PUBLISHED_ON]->(b:NF_Platform) RETURN a, r, b",
                    "MATCH (a:NF_Comment)-[r:PART_OF]->(b:NF_Article) RETURN a, r, b",
                    "MATCH (a:NF_Comment)-[r:COMMENTED_BY]->(b:NF_Actor) RETURN a, r, b",
                ]

                for q in edge_queries:
                    try:
                        for rec in s.run(q):
                            a_id = node_id(rec["a"])
                            b_id = node_id(rec["b"])
                            if a_id in seen_n and b_id in seen_n:
                                add_edge(rec["a"], rec["r"].type, rec["b"])
                    except Exception:
                        pass

        except Exception as e:
            self.log(f"Graph error: {e}", "WARNING")

        # Nur Nodes und Edges zurückgeben – keine Filterung mehr
        return {"nodes": nodes, "edges": edges, "origin_uid": origin_uid}

    def get_investigations_summary(self) -> list:
        """Alle Untersuchungen mit Knoten-Zählung."""
        if not self._driver:
            return []
        try:
            with self._driver.session() as s:
                result = s.run("""
                    MATCH (n:NF_Narrative)
                    RETURN n.uid AS uid, n.text AS text,
                           n.inv_uid AS inv_uid, n.first_seen AS first_seen
                    ORDER BY n.first_seen ASC
                """)
                return [dict(r) for r in result]
        except Exception:
            return []

    def get_stats(self) -> dict:
        empty = {"actors": 0, "narratives": 0, "articles": 0,
                 "platforms": 0, "comments": 0}
        if not self._driver:
            return empty
        try:
            with self._driver.session() as s:
                counts = {}
                for label, key in [
                    ("NF_Actor",    "actors"),
                    ("NF_Narrative","narratives"),
                    ("NF_Article",  "articles"),
                    ("NF_Platform", "platforms"),
                    ("NF_Comment",  "comments"),
                ]:
                    rec = s.run(f"MATCH (n:{label}) RETURN count(n) AS c").single()
                    counts[key] = rec["c"] if rec else 0
                return counts
        except Exception:
            return empty

    def search_actors_by_narrative_count(self, min_count: int = 2) -> list:
        if not self._driver:
            return []
        try:
            with self._driver.session() as s:
                result = s.run("""
                    MATCH (a:NF_Actor)-[:SPREADS]->(n:NF_Narrative)
                    WITH a, count(DISTINCT n) AS cnt
                    WHERE cnt >= $min
                    RETURN a.uid AS uid, a.name AS name,
                           a.platform AS platform, a.type AS type,
                           a.stance AS stance, cnt
                    ORDER BY cnt DESC
                """, min=min_count)
                return [dict(r) for r in result]
        except Exception:
            return []

    def get_actor_profile(self, actor_uid: str) -> dict:
        """Holt alle Narrative und Metadaten eines Akteurs."""
        if not self._driver:
            return {"name": "", "platform": "", "narratives": [], "error": "Keine DB"}
        try:
            with self._driver.session() as s:
                # Akteur-Daten
                actor = s.run("""
                    MATCH (a:NF_Actor {uid: $uid})
                    RETURN a.name AS name,
                           a.platform AS platform,
                           a.type AS type,
                           a.first_seen AS first_seen,
                           a.stance AS stance,
                           a.confidence AS confidence
                """, uid=actor_uid).single()
                if not actor:
                    return {"name": "", "platform": "", "narratives": []}
                
                # Narrative des Akteurs
                narratives = s.run("""
                    MATCH (a:NF_Actor {uid: $uid})-[r:SPREADS]->(n:NF_Narrative)
                    RETURN n.text AS text,
                           n.uid AS uid,
                           r.role AS role,
                           r.stance AS stance,
                           r.date AS date,
                           r.url AS url,
                           r.confidence AS confidence
                    ORDER BY r.date ASC
                """, uid=actor_uid).data()
                
                return {
                    "name": actor.get("name") or "",
                    "platform": actor.get("platform") or "",
                    "type": actor.get("type") or "",
                    "first_seen": actor.get("first_seen") or "",
                    "stance": actor.get("stance") or "neutral",
                    "confidence": actor.get("confidence") or 0.5,
                    "narratives": narratives,
                    "narrative_count": len(narratives)
                }
        except Exception as e:
            self.log(f"get_actor_profile error: {e}", "WARNING")
            return {"name": "", "platform": "", "narratives": [], "error": str(e)}

    def get_timeline_data(self, inv_uid: str) -> list:
        """Timeline: SPREADS-Kanten + Article AUTHORED_BY als Fallback."""
        if not self._driver:
            return []
        events = []
        seen = set()

        def normalize(d: dict):
            """Gibt normalisiertes dict oder None zurück."""
            date_raw = re.sub(r'[Xx]{2}', '01', str(d.get("date") or ""))
            if not re.match(r'\d{4}', date_raw):
                return None  # kein Jahr erkennbar (z.B. "October 19")
            if len(date_raw) >= 10:
                d["date"] = date_raw[:10]
            elif len(date_raw) >= 7:
                d["date"] = date_raw[:7] + "-01"
            elif len(date_raw) >= 4:
                d["date"] = date_raw[:4] + "-01-01"
            else:
                return None
            try:
                d["suspicious_date"] = int(d["date"][:4]) < 2000
            except Exception:
                d["suspicious_date"] = False
            url_raw   = str(d.get("url") or "")
            url_match = re.search(r'https?://[^\s\]\)]+', url_raw)
            d["url"]  = url_match.group(0) if url_match else ""
            d["platform"] = d.get("platform") or "unknown"
            return d

        try:
            with self._driver.session() as s:
                # Primär: SPREADS-Kanten mit Datum
                for rec in s.run("""
                    MATCH (a:NF_Actor)-[r:SPREADS]->(n:NF_Narrative {inv_uid: $inv_uid})
                    WHERE r.date IS NOT NULL AND r.date <> ''
                    RETURN a.name AS actor, a.platform AS platform,
                           r.date AS date, r.role AS type,
                           r.url AS url, r.stance AS stance,
                           r.confidence AS confidence
                    ORDER BY r.date ASC LIMIT 500
                """, inv_uid=inv_uid):
                    d = normalize(dict(rec))
                    if d:
                        key = f"{d['actor']}_{d['date']}"
                        if key not in seen:
                            seen.add(key)
                            events.append(d)

                # Sekundär: Article-Datum via AUTHORED_BY
                for rec in s.run("""
                    MATCH (art:NF_Article {inv_uid: $inv_uid})-[:AUTHORED_BY]->(a:NF_Actor)
                    WHERE art.date IS NOT NULL AND art.date <> ''
                    OPTIONAL MATCH (art)-[:PUBLISHED_ON]->(p:NF_Platform)
                    RETURN a.name AS actor,
                           coalesce(p.name, a.platform, 'unknown') AS platform,
                           art.date AS date, 'AUTHORED' AS type,
                           art.url AS url, art.stance AS stance,
                           art.stance_confidence AS confidence
                    ORDER BY art.date ASC LIMIT 500
                """, inv_uid=inv_uid):
                    d = normalize(dict(rec))
                    if d:
                        key = f"{d['actor']}_{d['date']}"
                        if key not in seen:
                            seen.add(key)
                            events.append(d)

        except Exception as e:
            self.log(f"Timeline error: {e}", "WARNING")

        events.sort(key=lambda x: x.get("date", ""))
        return events

    def delete_node(self, uid: str) -> int:
        """Deletes a node and all nodes below it in the hierarchy.
        Downward only: Actor→Comments, Article→Comments, Platform→Articles+Comments.
        Never deletes NF_Narrative nodes."""
        if not self._driver:
            return 0
        try:
            with self._driver.session() as s:
                chk = s.run("MATCH (n {uid:$uid}) RETURN labels(n) AS lbl LIMIT 1", uid=uid).single()
                if not chk or "NF_Narrative" in (chk["lbl"] or []):
                    return 0
                to_delete = {uid}
                for rec in s.run("MATCH (c:NF_Comment)-[:COMMENTED_BY|PART_OF]->(n {uid:$uid}) RETURN c.uid AS cuid", uid=uid):
                    if rec["cuid"]: to_delete.add(rec["cuid"])
                for rec in s.run("MATCH (a:NF_Article)-[:PUBLISHED_ON]->(n {uid:$uid}) RETURN a.uid AS auid", uid=uid):
                    if rec["auid"]:
                        to_delete.add(rec["auid"])
                        for r2 in s.run("MATCH (c:NF_Comment)-[:PART_OF]->(a:NF_Article {uid:$auid}) RETURN c.uid AS cuid", auid=rec["auid"]):
                            if r2["cuid"]: to_delete.add(r2["cuid"])
                r = s.run("MATCH (n) WHERE n.uid IN $uids DETACH DELETE n RETURN count(n) AS cnt", uids=list(to_delete)).single()
                return r["cnt"] if r else 0
        except Exception:
            return 0

    def cleanup_all(self) -> int:
        """Löscht alle NF_* Knoten.
        Deletes all NF_* nodes."""
        if not self._driver:
            return 0
        try:
            with self._driver.session() as s:
                r = s.run("""
                    MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'NF_')
                    DETACH DELETE n RETURN count(n) AS cnt
                """).single()
                return r["cnt"] if r else 0
        except Exception:
            return 0

    def delete_investigation(self, inv_uid: str) -> int:
        """Löscht alle Knoten einer Untersuchung.
        Deletes all nodes belonging to a single investigation."""
        if not self._driver:
            return 0
        try:
            with self._driver.session() as s:
                r = s.run("""
                    MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'NF_')
                      AND n.inv_uid = $inv_uid
                    DETACH DELETE n RETURN count(n) AS cnt
                """, inv_uid=inv_uid).single()
                return r["cnt"] if r else 0
        except Exception:
            return 0

    def export_all(self) -> dict:
        """Exportiert alle NF_* Daten.
        Exports all NF_* data."""
        if not self._driver:
            return {"nodes": [], "edges": []}
        try:
            with self._driver.session() as s:
                nodes = [{"labels": list(r["n"].labels), "props": dict(r["n"])}
                         for r in s.run("MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'NF_') RETURN n")]
                edges = [{"type": r["type"], "from_uid": r["from_uid"],
                          "to_uid": r["to_uid"], "props": r["props"]}
                         for r in s.run("""
                    MATCH (a)-[r]->(b)
                    WHERE any(l IN labels(a) WHERE l STARTS WITH 'NF_')
                    RETURN type(r) AS type, properties(r) AS props,
                           a.uid AS from_uid, b.uid AS to_uid
                """)]
                return {"nodes": nodes, "edges": edges}
        except Exception:
            return {"nodes": [], "edges": []}


def _platform_from_url(url: str) -> str:
    """Leitet Plattform-Namen aus URL ab. Nur echte Plattformen – keine Organisationen.
    Derives platform name from URL. Only real platforms – not organisations."""
    url_lower = url.lower()
    platforms = {
        # Social Media Plattformen
        "twitter.com":    "Twitter",     "x.com":           "Twitter",
        "reddit.com":     "Reddit",      "t.me":            "Telegram",
        "telegram.org":   "Telegram",    "4chan.org":        "4chan",
        "8chan":           "8chan",        "facebook.com":    "Facebook",
        "youtube.com":    "YouTube",     "tiktok.com":       "TikTok",
        "instagram.com":  "Instagram",   "tumblr.com":       "Tumblr",
        "myspace.com":    "Myspace",     "gaiaonline.com":   "GaiaOnline",
        "discord.com":    "Discord",     "mastodon.social":  "Mastodon",
        # Archiv & Referenz
        "web.archive.org": "Wayback",    "archive.org":      "Wayback",
        "4plebs.org":      "4chan-Archiv","wikipedia.org":    "Wikipedia",
        "knowyourmeme.com":"KnowYourMeme","tenor.com":       "Tenor",
        # Medien (Plattformen, keine Akteure)
        "bbc.com":        "BBC",         "bbc.co.uk":        "BBC",
        "nytimes.com":    "NYTimes",     "theguardian.com":  "TheGuardian",
        "npr.org":        "NPR",         "pbs.org":          "PBS",
        "vice.com":       "VICE",        "buzzfeed.com":     "BuzzFeed",
        "vox.com":        "Vox",         "dailydot.com":     "DailyDot",
        "breitbart.com":  "Breitbart",
    }
    for domain, name in platforms.items():
        if domain in url_lower:
            return name
    # Fallback: zweitletztes Domain-Segment
    m = re.match(r'https?://(?:[^/]+\.)?([^./]+)\.[^./]+(?:/|$)', url_lower)
    name = m.group(1).capitalize() if m else "Web"
    invalid = {'co', 'doi', 'io', 'api', 'cdn', 'static', 'assets',
               'fonts', 'googleapis', 'bepress', 'semanticscholar',
               'scholaris', 'utoronto'}
    return name if name.lower() not in invalid else "Web"


# ── Artefakt-Importer ─────────────────────────────────────────────────────────

class ArtifactImporter:
    """
    Importiert manuelle Artefakte (Screenshots, HTML, PDF, Text)
    aus dem Corpus-Verzeichnis in die Datenbank.
    Imports manual artifacts (screenshots, HTML, PDF, text)
    from the corpus directory into the database.

    Forensische Archeologie: Alte Dokumente einlesen, datieren, vernetzen.
    Forensic archaeology: ingest old documents, date them, link them.
    """

    def __init__(self, db: NarrativeNeo4j, log_fn=None):
        self.db  = db
        self.log = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [IMPORT] {m}"))
        CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    def import_text(self, text: str, source_url: str, date_hint: str,
                    platform: str, notes: str = "") -> str:
        """
        Importiert einen Texte direkt (aus Clipboard, Screenshot-OCR etc.).
        Imports text directly (from clipboard, screenshot OCR, etc.).
        Gibt die narrative_uid zurück / Returns the narrative_uid.
        """
        fp    = _fingerprint(text)
        n_uid = f"narr_{fp}"
        a_uid = f"actor_manual_{_fingerprint(source_url or notes)}"
        art_uid = f"art_manual_{fp}"

        # Narrative
        self.db.upsert_narrative(
            uid=n_uid, 
            text=text, 
            inv_uid="manual_import",
            first_seen=date_hint or _now_iso()
        )

        # Platform
        p_uid = self.db.upsert_platform(platform, source_url or "", "manual_import")

        # Article
        self.db.upsert_article(
            uid=art_uid,
            title=(text[:100] + "...") if len(text) > 100 else text,
            url=source_url or "",
            platform_uid=p_uid,
            date=date_hint or _now_iso(),
            inv_uid="manual_import",
            stance="neutral",
            stance_confidence=0.5
        )

        # Actor
        self.db.upsert_actor(
            uid=a_uid,
            name=source_url or "Unbekannt",
            platform_name=platform,
            actor_type="Manual",
            first_seen=date_hint or _now_iso(),
            confidence=0.6,
            inv_uid="manual_import",
            stance="neutral"
        )

        # Verknüpfungen
        self.db.actor_authored_article(a_uid, art_uid)
        self.db.actor_spreads_narrative(
            actor_uid=a_uid,
            narrative_uid=n_uid,
            role="ORIGIN",
            stance="neutral",
            confidence=0.6,
            date=date_hint or _now_iso(),
            url=source_url or ""
        )

        self.log(f"Artefakt importiert: {n_uid}", "SUCCESS")
        return n_uid

    def scan_corpus(self) -> int:
        """Scannt CORPUS_DIR nach .txt/.html/.json Dateien und importiert sie.
        Scans CORPUS_DIR for .txt/.html/.json files and imports them."""
        imported = 0
        for f in CORPUS_DIR.glob("**/*"):
            if f.suffix.lower() not in (".txt", ".html", ".htm", ".json", ".md"):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                parts  = f.stem.split("_")
                date   = parts[0] if parts and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]) else ""
                plat   = parts[1] if len(parts) > 1 else "unknown"
                self.import_text(text, source_url=f.name, date_hint=date, platform=plat)
                imported += 1
            except Exception as e:
                self.log(f"Import error for {f.name}: {e}", "WARNING")
        return imported


# ── LLM-Interface ─────────────────────────────────────────────────────────────

class NarrativeLLM:
    """
    Ollama-Interface spezialisiert auf forensische Narrative-Analyse.
    Teilt sich den Ollama-Port mit lyra_network_builder.
    Ollama interface specialised for forensic narrative analysis.
    Shares the Ollama port with lyra_network_builder.
    """

    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [LLM] {m}"))
        self._lock = threading.Lock()

    def _get_model(self) -> str:
        cfg_path = Path.home() / ".openclaw" / "openclaw.json"
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("ollama", {}).get("model", "") or "qwen2.5:7b"
        except Exception:
            return "qwen2.5:7b"

    def _parse_json(self, raw: str) -> dict | None:
        """
        Robustes JSON-Parsing – toleriert erklärender Text vor/nach dem JSON.
        Ollama gibt manchmal Text vor dem eigentlichen JSON zurück.
        Robust JSON parsing – tolerates explanatory text before/after JSON.
        Ollama sometimes returns prose before the actual JSON object.
        """
        if not raw:
            return None
        # Versuch 1: direktes Parsen
        try:
            return json.loads(raw)
        except Exception:
            pass
        # Versuch 2: JSON-Objekt aus Text extrahieren (erklärender Text davor/danach)
        try:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        # Versuch 3: Markdown-Fences entfernen (```json ... ```)
        try:
            cleaned = re.sub(r'^```(?:json)?\s*', '', raw.strip(), flags=re.IGNORECASE)
            cleaned = re.sub(r'\s*```$', '', cleaned.strip())
            return json.loads(cleaned)
        except Exception:
            pass
        # Versuch 4: Trailing commas fixen (Ollama gibt manchmal ungültiges JSON)
        try:
            fixed = re.sub(r',\s*}', '}', raw)
            fixed = re.sub(r',\s*]', ']', fixed)
            match = re.search(r'\{.*\}', fixed, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass
        return None

    def query(self, system: str, prompt: str, max_tokens: int = 1500) -> str:
        """Sendet Prompt an Ollama, gibt Antwort zurück."""
        model = self._get_model()
        payload = {
            "model":    model,
            "messages": [
                {"role": "system",  "content": system},
                {"role": "user",    "content": prompt},
            ],
            "stream":  False,
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        try:
            with self._lock:
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                                 delete=False, encoding="utf-8") as tf:
                    json.dump(payload, tf, ensure_ascii=False)
                    tfname = tf.name
                creationflags = 0x08000000 if sys.platform == "win32" else 0
                result = subprocess.run(
                    ["curl", "-s", "-X", "POST", OLLAMA_URL,
                     "-H", "Content-Type: application/json",
                     "--data-binary", f"@{tfname}",
                     "--max-time", "600"],
                    capture_output=True, text=True, encoding="utf-8",
                    creationflags=creationflags
                )
                os.unlink(tfname)
                if result.returncode != 0:
                    return ""
                data = json.loads(result.stdout)
                return data.get("message", {}).get("content", "").strip()
        except Exception as e:
            self.log(f"LLM error: {e}", "WARNING")
            return ""

    def extract_actors_and_events(self, text: str, narrative_summary: str,
                                   source_url: str = "") -> dict:
        """Hybrid Actor Extraction: Maximal Hit, Zero Narrative.
        Stufe 1: Rein strukturelles Sammeln. Stufe 2: LLM-Filterung.
        """
        ACTOR_PATTERNS = [
            r'(?:^|\s|["\'])(@[\w][\w._-]{2,40})(?:\b|["\'$])',
            r'(?:^|\s|["\'])(u/[\w][\w._-]{2,40})(?:\b|["\'$])',
            r'(?:^|\s|["\'])(/u/[\w][\w._-]{2,40})(?:\b|["\'$])',
            r'href=["\'][^"\']*?/(?:u|user|profile)/([A-Za-z0-9_\-]{3,40})["\']',
            r'>>(\d{6,15})(?:\b|$)',
            r'/(?:user|profile|member|author|channel|people|c)/([\w][\w._-]{3,45})',
            r'/@([\w][\w._-]{3,45})(?:/|\?|$|\s)',
            r't\.me/([a-zA-Z0-9_]{5,40})(?:/|\?|$)',
        ]
        raw_candidates = []
        seen_raw = set()
        for pattern in ACTOR_PATTERNS:
            try:
                matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
                for m in matches:
                    val = (m[0] if isinstance(m, tuple) else m).strip()
                    if len(val) < 3 or len(val) > 80: continue
                    if val.lower() in seen_raw: continue
                    if re.match(r'^\d+$', val) or re.match(r'^[^a-zA-Z0-9@/_]+$', val): continue
                    seen_raw.add(val.lower())
                    idx = text.find(val)
                    ctx = text[max(0,idx-80):idx+len(val)+80].replace('\n',' ').strip()
                    raw_candidates.append({"handle": val, "context": ctx[:220]})
            except Exception:
                continue

        platform_hint = _platform_from_url(source_url) if source_url else ""
        system = (
            "Du bist ein neutraler forensischer Dokumentations-Assistent.\n"
            "Deine einzige Aufgabe ist es, Akteure zu dokumentieren, die sich zum angegebenen Narrativ geäußert haben.\n\n"
            "Regeln:\n"
            "- Nur Akteure erfassen, die das Narrativ erstellt, verbreitet, kommentiert oder kritisiert haben.\n"
            "- Ignoriere beiläufige Erwähnungen (Navigation, Werbung, unrelated Kontext).\n"
            "- Sei maximal inklusiv bei relevanter Beteiligung.\n"
            "- Keinerlei moralische, politische oder ideologische Bewertung.\n"
            "- Plattformen (Twitter, Reddit, YouTube etc.) sind KEINE Akteure.\n"
            "- Ungültige Namen: \"Unknown\", \"Anonymous\" (ohne ID), Platzhalter.\n"
            "- role: immer \"AMPLIFICATION\" – Ursprungs-Bestimmung erfolgt separat.\n"
            "- Antworte ausschließlich mit validem JSON."
        )

        candidates_text = "\n".join(
            f"- {c['handle']} | Kontext: {c['context']}"
            for c in raw_candidates[:130]
        ) or "(keine strukturellen Kandidaten gefunden)"

        ph = platform_hint or 'unbekannt'
        prompt = (
            f"Narrativ: {narrative_summary}\n"
            f"Quelle: {source_url}\n"
            f"Platform: {platform_hint}\n\n"
            f"Strukturell gefundene Kandidaten:\n{candidates_text}\n\n"
            f"Volltext (zur Ergänzung):\n{text[:6000]}\n\n"
            f"Antworte NUR mit validem JSON:\n"
            f'{{\n'
            f'  "actors": [\n'
            f'    {{\n'
            f'      "name": "Handle oder vollständiger Name",\n'
            f'      "platform": "{ph}",\n'
            f'      "type": "Person|Account|Medium|Organisation|Bot",\n'
            f'      "role": "ORIGIN|AMPLIFICATION",\n'
            f'      "date": "YYYY-MM-DD oder leer",\n'
            f'      "confidence": 0.0-1.0\n'
            f'    }}\n'
            f'  ],\n'
            f'  "earliest_date": "YYYY-MM-DD oder leer",\n'
            f'  "coordination_signals": ["kurze faktenbasierte Beobachtungen"]\n'
            f'}}'
        )

        raw = self.query(system, prompt, max_tokens=1500)
        result = self._parse_json(raw)
        if result is not None:
            result.setdefault("narrative_summary", narrative_summary)
            result.setdefault("platform_sequence", [])
            return result
        return {"actors": [], "narrative_summary": narrative_summary,
                "earliest_date": "", "coordination_signals": [],
                "platform_sequence": []}

    def analyze_author_fingerprint(self, texts: list) -> dict:
        """
        Analysiert Autorencharakteristik aus mehreren Texten desselben Akteurs.
        Erkennt: Tippfehler-Muster, Redewendungen, narrative Richtung, Stil.
        Gibt Fingerprint + Confidence zurück.
        Returns fingerprint + confidence.
        """
        if not texts:
            return {}
        combined = "\n\n---\n\n".join(t[:500] for t in texts[:5])
        system = """Du bist ein forensischer Linguist spezialisiert auf Autorenidentifikation.
Analysiere die Texte und erstelle einen Autoren-Fingerprint.
Antworte NUR mit JSON:
{
  "writing_patterns": ["charakteristische Formulierungen oder Redewendungen"],
  "typo_patterns": ["wiederkehrende Tippfehler oder Schreibweisen"],
  "narrative_direction": "unterstützend/ablehnend/neutral – welche Position wird eingenommen",
  "recurring_themes": ["wiederkehrende Themen oder Schlüsselbegriffe"],
  "style_features": ["Satzlänge", "Interpunktion", "Grossschreibung etc."],
  "confidence": 0.0-1.0,
  "summary": "Kurzzusammenfassung des Autoren-Profils max 200 Zeichen"
}"""
        prompt = f"Analysiere diese Texte auf gemeinsame Autorenmerkmale:\n\n{combined}"
        raw = self.query(system, prompt, max_tokens=600)
        result = self._parse_json(raw)
        if result is not None:
            return result
        return {}

    def match_author_fingerprints(self, fp_a: dict, fp_b: dict) -> dict:
        """
        Vergleicht zwei Autoren-Fingerprints.
        Gibt Übereinstimmungs-Score + Evidenz zurück – für COORDINATES_WITH Kante.
        Returns match score + evidence – for the COORDINATES_WITH edge.
        """
        if not fp_a or not fp_b:
            return {"score": 0.0, "evidence": "", "is_same_author": False}
        system = """Vergleiche zwei Autoren-Fingerprints forensisch.
Antworte NUR mit JSON:
{
  "score": 0.0-1.0,
  "matching_patterns": ["übereinstimmende Merkmale"],
  "evidence": "konkrete Begründung max 200 Zeichen",
  "is_same_author": true/false,
  "confidence": 0.0-1.0
}"""
        prompt = f"Fingerprint A:\n{json.dumps(fp_a, ensure_ascii=False)}\n\nFingerprint B:\n{json.dumps(fp_b, ensure_ascii=False)}"
        raw = self.query(system, prompt, max_tokens=400)
        result = self._parse_json(raw)
        if result is not None:
            return result
        return {"score": 0.0, "evidence": "", "is_same_author": False}

    def document_positioning(self, text: str, narrative: str) -> dict:
        """
        Dokumentiert die Positionierung eines Textes zum Narrativ.
        Rückgabe: supporting / opposing / neutral – keine Wertung.
        Returns: supporting / opposing / neutral – no evaluation.
        """
        system = """Analysiere den Text und dokumentiere die Positionierung zum Narrativ.
Antworte NUR mit JSON:
{
  "stance": "supporting|opposing|neutral",
  "confidence": 0.0-1.0,
  "evidence": "max 100 Zeichen faktische Beschreibung"
}
supporting = Text verbreitet/bestätigt das Narrativ
opposing   = Text widerspricht/hinterfragt das Narrativ
neutral    = Text berichtet ohne erkennbare Positionierung"""
        prompt = f"Narrativ: {narrative}\n\nText:\n{text[:2000]}"
        raw = self.query(system, prompt, max_tokens=200)
        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception:
            pass
        return {"stance": "neutral", "confidence": 0.5, "evidence": ""}

    def compare_narratives(self, text_a: str, text_b: str) -> dict:
        """
        Vergleicht zwei Texte semantisch.
        Gibt Ähnlichkeit, Beziehungstyp und Evidenz zurück.
        Returns similarity, relationship type and evidence.
        """
        system = """Vergleiche zwei Texte forensisch auf semantische Verwandtschaft.
Antworte NUR mit JSON, kein Markdown:
{
  "similarity": 0.0-1.0,
  "relationship": "QUOTES|INSPIRED_BY|PARALLEL_TO|UNRELATED",
  "direction": "A_CITES_B|B_CITES_A|MUTUAL|INDEPENDENT",
  "evidence": "konkrete Begründung max 200 Zeichen",
  "confidence": 0.0-1.0
}"""
        prompt = f"Text A:\n{text_a[:1000]}\n\nText B:\n{text_b[:1000]}"
        raw = self.query(system, prompt, max_tokens=300)
        result = self._parse_json(raw)
        if result is not None:
            return result
        return {"similarity": 0.0, "relationship": "UNRELATED",
                "direction": "INDEPENDENT", "evidence": "", "confidence": 0.0}

    def estimate_date_from_context(self, text: str, url: str) -> dict:
        """
        Versucht aus Text und URL ein Datum abzuleiten.
        Gibt Datum + Konfidenz zurück.
        Returns date + confidence.
        """
        system = """Extrahiere aus dem folgenden Text und der URL das Erscheinungsdatum.
Antworte NUR mit JSON:
{
  "date": "YYYY-MM-DD oder YYYY-MM oder YYYY oder leer",
  "confidence": "exact|estimated|unknown",
  "reasoning": "max 100 Zeichen"
}"""
        prompt = f"URL: {url}\n\nText-Anfang:\n{text[:1000]}"
        raw = self.query(system, prompt, max_tokens=200)
        result = self._parse_json(raw)
        if result is not None:
            return result
        return {"date": "", "confidence": "unknown", "reasoning": "No date determinable"}


# ── Web-Recherche ─────────────────────────────────────────────────────────────

class NarrativeSearcher:
    """
    Forensische Web-Recherche: SearXNG + Wayback-Browsing + Link-Verfolgung.
    Keine APIs. Alles via normales HTTP.
    """

    def __init__(self, log_fn=None):
        self.log = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [SEARCH] {m}"))

    def search_web(self, query: str, time_range: str = "",
                   engines: str = "", num_results: int = 10,
                   page: int = 1) -> List[dict]:
        """SearXNG-Suche mit Paginierung."""
        params = {"q": query, "format": "json", "lang": "all", "pageno": page}
        if time_range: params["time_range"] = time_range
        if engines:    params["engines"]    = engines
        try:
            r = requests.get(SEARXNG_URL, params=params, timeout=30)
            data = r.json()
            results = []
            for item in data.get("results", [])[:num_results]:
                results.append({
                    "url":     item.get("url", ""),
                    "title":   item.get("title", ""),
                    "content": item.get("content", ""),
                    "engine":  item.get("engine", ""),
                    "score":   item.get("score", 0),
                })
            return results
        except Exception as e:
            self.log(f"Search failed: {e}", "WARNING")
            return []

    def fetch_page(self, url: str, max_chars: int = 8000,
                   follow_links: bool = False,
                   link_depth: int = 1) -> dict:
        """
        Router: wählt den richtigen Fetcher je nach Platform.
        Router: picks the right fetcher per platform.
        Jede Platform hat eine eigene Extraktionsstrategie.
        """
        result = {
            "url":             url,
            "text":            "",
            "links":           [],
            "usernames":       [],
            "dates":           [],
            "shares":          None,
            "likes":           None,
            "pages":           [],
            "platform_actors": [],
        }
        url_lower = url.lower()
        # Platform-spezifische Fetcher – strukturierte Daten statt HTML-Scraping
        if "reddit.com" in url_lower and ("/comments/" in url_lower or re.search(r'reddit\.com/r/[^/]+/?(?:\?.*)?$', url_lower)):
            return self._fetch_reddit(url, result)
        if "4chan.org" in url_lower and re.search(r'/thread/\d+', url_lower):
            return self._fetch_4chan(url, result)
        if "wikipedia.org/wiki/" in url_lower and "special:" not in url_lower and "action=" not in url_lower:
            return self._fetch_wikipedia(url, result)
        if "youtube.com/watch" in url_lower or "youtu.be/" in url_lower:
            return self._fetch_youtube(url, result)
        if "youtube.com/@" in url_lower or "youtube.com/channel/" in url_lower or "youtube.com/c/" in url_lower or "music.youtube.com/@" in url_lower:
            return self._fetch_html(url, result, max_chars=max_chars, follow_links=True, link_depth=link_depth)
        # Alles andere: normales HTML
        return self._fetch_html(url, result, max_chars=max_chars,
                                follow_links=follow_links, link_depth=link_depth)

    def _fetch_reddit(self, url: str, result: dict) -> dict:
        """Reddit JSON API mit Retry-Backoff. Kommentartiefe via self.comment_pages."""
        comment_limit = getattr(self, 'comment_pages', 2) * 25  # ~25 Kommentare pro Seite
        json_url = url.rstrip('/') + f".json?limit={min(comment_limit, 500)}&depth=10"
        # Rotierender User-Agent – verhindert UA-basiertes Blocking
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:138.0) Gecko/20100101 Firefox/138.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        ]
        headers = {
            "User-Agent":      random.choice(user_agents),
            "Accept":          "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Sec-Fetch-Dest":  "empty",
            "Sec-Fetch-Mode":  "cors",
            "Sec-Fetch-Site":  "same-origin",
            "Sec-Ch-Ua":       '"Chromium";v="136", "Google Chrome";v="136"',
            "Sec-Ch-Ua-Mobile":"?0",
            "Referer":         "https://www.reddit.com/",
        }
        # Retry mit Backoff bei Rate Limiting
        for attempt in range(3):
            try:
                r = requests.get(json_url, headers=headers, timeout=20)

                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", 10)) + attempt * 5
                    self.log(f"  Reddit: Rate Limited – warte {wait}s (Versuch {attempt+1}/3)", "WARNING")
                    time.sleep(wait)
                    continue

                if r.status_code == 403:
                    wait = min(2 ** attempt * 5, 60)
                    self.log(f"  Reddit: HTTP 403 – wait {wait}s (attempt {attempt+1}/3)", "WARNING")
                    if attempt < 2:
                        time.sleep(wait)
                        continue
                    return self._fetch_reddit_html_fallback(url, result)

                if r.status_code != 200:
                    self.log(f"  Reddit: HTTP {r.status_code}", "WARNING")
                    return result

                if not r.text or len(r.text.strip()) < 10:
                    self.log(f"  Reddit: Leere Response", "WARNING")
                    return result

                if r.text.strip().startswith("<"):
                    self.log(f"  Reddit: HTML statt JSON (Captcha/Login erkannt)", "WARNING")
                    return self._fetch_reddit_html_fallback(url, result)

                try:
                    data = r.json()
                except json.JSONDecodeError as e:
                    self.log(f"  Reddit: JSON parse error: {e} – response starts with: {r.text[:100]}", "WARNING")
                    return self._fetch_reddit_html_fallback(url, result)

                break  # Erfolg – Retry-Loop verlassen

            except requests.exceptions.Timeout:
                self.log(f"  Reddit: Timeout (Versuch {attempt+1}/3)", "WARNING")
                if attempt < 2:
                    time.sleep(3)
                    continue
                return result
            except Exception as e:
                self.log(f"  Reddit: error: {e}", "WARNING")
                return result
        else:
            return self._fetch_reddit_html_fallback(url, result)

        # Erfolgreicher JSON-Response – Akteure extrahieren
        actors, dates, texts = [], [], []

        def walk(obj, d=0, parent_type=None):
            if d > 7:
                return
            if isinstance(obj, dict):
                d2 = obj.get("data", {}) if isinstance(obj.get("data"), dict) else {}
                author = d2.get("author") or obj.get("author", "")
                skip = {"AutoModerator", "[deleted]", "[removed]", "", "None", "null"}
                if author and author not in skip:
                    is_op   = obj.get("kind") == "t3"
                    # Kommentar-Text für Stance-Analyse
                    body = ""
                    for f in ["selftext", "body"]:
                        v = d2.get(f) or obj.get(f, "")
                        if v and v not in ("[deleted]", "[removed]", ""):
                            body = str(v)[:500]
                            break
                    actors.append({
                        "name":     f"u/{author}",
                        "type":     "ORIGIN" if is_op else "AMPLIFICATION",
                        "platform": "Reddit",
                        "text":     body,       # Kommentar-Text für Stance-Analyse
                        "depth":    d,          # 0=OP, 1=Hauptkommentar, 2+=Subkommentar
                    })
                    ts = d2.get("created_utc") or obj.get("created_utc")
                    if ts:
                        try:
                            from datetime import datetime, timezone as tz
                            dates.append(datetime.fromtimestamp(float(ts), tz=tz.utc).strftime("%Y-%m-%d"))
                        except Exception:
                            pass
                for f in ["selftext", "body", "title"]:
                    v = d2.get(f) or obj.get(f, "")
                    if v and v not in ("[deleted]", "[removed]", ""):
                        texts.append(str(v)[:200])
                for v in obj.values():
                    walk(v, d+1)
            elif isinstance(obj, list):
                for i in obj:
                    walk(i, d)

        walk(data)

        seen, unique = set(), []
        for a in actors:
            if a["name"] not in seen:
                seen.add(a["name"])
                unique.append(a)

        sub = re.findall(r'/r/([A-Za-z0-9_]+)/', url)
        for a in unique:
            if sub:
                a["subreddit"] = sub[0]

        result["platform_actors"] = unique[:comment_limit]
        result["dates"]           = sorted(set(dates))[:10]
        result["text"]            = " ".join(texts)[:8000] or f"Reddit: {url}"
        result["title"]           = url.split("/")[-2].replace("_", " ")[:100] if len(url.split("/")) > 2 else "Reddit Post"
        # If subreddit listing: extract thread links for depth crawling
        is_listing = bool(re.search(r'reddit\.com/r/[^/]+/?(?:\?.*)?$', url))
        if is_listing:
            thread_links = []
            def find_links(obj):
                if isinstance(obj, dict):
                    d2 = obj.get("data", {}) if isinstance(obj.get("data"), dict) else {}
                    permalink = d2.get("permalink") or obj.get("permalink", "")
                    if permalink and "/comments/" in permalink:
                        full = "https://www.reddit.com" + permalink if permalink.startswith("/") else permalink
                        thread_links.append(full)
                    for v in obj.values():
                        find_links(v)
                elif isinstance(obj, list):
                    for i in obj:
                        find_links(i)
            find_links(data)
            result["links"] = list(dict.fromkeys(thread_links))[:20]

        self.log(f"  Reddit: {len(unique)} User aus {url[:50]}")
        return result

    def _fetch_reddit_html_fallback(self, url: str, result: dict) -> dict:
        """
        Fallback: old.reddit.com liefert einfaches HTML ohne JS-Rendering.
        """
        try:
            old_url = url.replace("www.reddit.com", "old.reddit.com")\
                        .replace("reddit.com", "old.reddit.com")
            headers = {
                "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
                "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT":             "1",
                "Connection":      "keep-alive",
            }
            r = requests.get(old_url, headers=headers, timeout=20)
            html = r.text

            if "login" in html[:2000].lower() or "captcha" in html[:2000].lower():
                self.log(f"  Reddit HTML-fallback: Login/Captcha wall – skipping", "WARNING")
                return result

            user_patterns = [
                r'href="https://www\.reddit\.com/user/([A-Za-z0-9_\-]+)"',
                r'href="/user/([A-Za-z0-9_\-]{3,30})"',
                r'u/([A-Za-z0-9_\-]{3,30})',
            ]
            users = set()
            for pat in user_patterns:
                users.update(re.findall(pat, html))

            op_match = re.search(r'submitted by.*?u/([A-Za-z0-9_\-]+)', html, re.IGNORECASE)
            if op_match:
                users.discard(op_match.group(1))

            actors = []
            if op_match:
                actors.append({"name": f"u/{op_match.group(1)}", "type": "ORIGIN",        "platform": "Reddit"})
            for user in list(users)[:50]:
                actors.append({"name": f"u/{user}",              "type": "AMPLIFICATION", "platform": "Reddit"})

            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html)
            result["title"] = title_match.group(1)[:100] if title_match else "Reddit Post"
            text = re.sub(r'<[^>]+>', ' ', html)
            text = re.sub(r'\s+', ' ', text)
            result["text"]           = text[:5000]
            result["platform_actors"] = actors
            self.log(f"  Reddit (HTML-fallback): {len(actors)} users from {url[:50]}")

        except Exception as e:
            self.log(f"  Reddit HTML-fallback error: {e}", "WARNING")

        return result

    def _fetch_4chan(self, url: str, result: dict) -> dict:
        """4chan JSON API."""
        try:
            m = re.search(r'4chan\.org/([^/]+)/thread/(\d+)', url)
            if not m: return self._fetch_html(url, result)
            board, tid = m.group(1), m.group(2)
            r = requests.get(f"https://a.4cdn.org/{board}/thread/{tid}.json",
                             headers={"User-Agent":"LYRA/0.1"}, timeout=15)
            if r.status_code != 200: return result
            actors,dates,texts = [],[],[]
            for i,post in enumerate(r.json().get("posts",[])):
                pid  = post.get("no")
                ts   = post.get("time")
                name = post.get("name","Anonymous")
                trip = post.get("trip","")
                com  = re.sub(r'<[^>]+>',' ', post.get("com",""))
                aname = f"{name}{trip}#{pid}" if (name!="Anonymous" or trip) else f"Anonymous#{pid}"
                actors.append({"name":aname,"type":"ORIGIN" if i==0 else "AMPLIFICATION","platform":"4chan"})
                if ts:
                    from datetime import datetime,timezone as tz
                    dates.append(datetime.fromtimestamp(ts,tz=tz.utc).strftime("%Y-%m-%d"))
                if com: texts.append(com[:200])
            result["platform_actors"] = actors[:100]
            result["dates"] = sorted(set(dates))[:10]
            result["text"]  = " ".join(texts)[:8000]
            result["title"] = f"/{board}/ #{tid}"
            self.log(f"  4chan: {len(actors)} Posts")
        except Exception as e:
            self.log(f"4chan error: {e}", "WARNING")
        return result

    def _fetch_wikipedia(self, url: str, result: dict) -> dict:
        """Wikipedia MediaWiki API: Artikel-Text + Editoren + Talk-Page."""
        try:
            m = re.search(r'wikipedia\.org/wiki/([^?#]+)', url)
            if not m:
                return self._fetch_html(url, result)
            title = m.group(1).replace("_", " ")
            ml = re.match(r'https?://([a-z]{2})\.wikipedia', url)
            lang = ml.group(1) if ml else "en"
            api = f"https://{lang}.wikipedia.org/w/api.php"
            
            # WICHTIG: Wikipedia benötigt einen aussagekräftigen User-Agent
            headers = {
                "User-Agent": "LYRA-Narrative-Forensics/0.1 (https://github.com/lyra/forensics; forensic@example.com) Python-requests"
            }
            
            actors, dates, texts = [], [], []
            
            # Artikel-Text + Editoren
            params = {
                "action": "query",
                "titles": title,
                "prop": "revisions|extracts",
                "rvprop": "user|timestamp",
                "rvlimit": 20,
                "exintro": False,    # Volltext statt nur Einleitung
                "explaintext": True,
                "exsectionformat": "plain",
                "format": "json"
            }
            r = requests.get(api, params=params, headers=headers, timeout=15)
            
            # Prüfen Status-Code
            if r.status_code == 403:
                self.log(f"Wikipedia API 403 Forbidden – please check User-Agent: {title[:40]}", "WARNING")
                # Fallback: normales HTML scrappen
                return self._fetch_html(url, result)
            
            if r.status_code != 200:
                self.log(f"Wikipedia API HTTP {r.status_code} for {title[:40]}", "WARNING")
                return self._fetch_html(url, result)
            
            # JSON-Parsing mit Fehlerbehandlung
            try:
                data = r.json()
            except json.JSONDecodeError:
                self.log(f"Wikipedia API returned no JSON for {title[:40]}", "WARNING")
                return self._fetch_html(url, result)
            
            if "error" in data:
                self.log(f"Wikipedia API error: {data['error'].get('info', 'unknown')}", "WARNING")
                return self._fetch_html(url, result)
            
            pages = data.get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                if page_id == "-1":
                    self.log(f"Wikipedia-Seite existiert nicht: {title}", "WARNING")
                    continue

                ex = page.get("extract", "")
                if ex:
                    texts.append(ex[:5000])  # Mehr Text damit LLM Ersteller findet

                for rev in page.get("revisions", []):
                    user = rev.get("user", "")
                    ts = rev.get("timestamp", "")[:10]
                    if user and not user[:3].replace(".", "").isdigit() and "bot" not in user.lower():
                        actors.append({
                            "name": user,
                            "type": "EDITOR",   # Editoren – später zu ORIGIN/EDITOR aufgelöst
                            "platform": "Wikipedia",
                            "date": ts
                        })
                        if ts:
                            dates.append(ts)

            # Erstellungsdatum + Erstautor (älteste Revision)
            try:
                params_oldest = {
                    "action": "query", "titles": title,
                    "prop": "revisions", "rvprop": "user|timestamp",
                    "rvlimit": 1, "rvdir": "newer", "format": "json"
                }
                r_old = requests.get(api, params=params_oldest, headers=headers, timeout=10)
                if r_old.status_code == 200:
                    d_old = r_old.json()
                    for pg in d_old.get("query", {}).get("pages", {}).values():
                        revs = pg.get("revisions", [])
                        if revs:
                            first_author = revs[0].get("user", "")
                            created      = revs[0].get("timestamp", "")[:10]
                            if created:
                                result["date_hint"] = created
                                dates.insert(0, created)
                            if first_author:
                                import re as _re
                                # Nur IPs und sehr kurze/leere Namen filtern
                                is_ip = bool(_re.match(r'^\d{1,3}\.\d{1,3}', first_author))
                                if not is_ip and len(first_author) >= 3:
                                    result["wiki_first_author"] = first_author
                                    already = any(a["name"] == first_author for a in actors)
                                    if not already:
                                        actors.insert(0, {
                                            "name": first_author,
                                            "type": "ORIGIN",
                                            "platform": "Wikipedia",
                                            "date": created
                                        })
                                    else:
                                        for a in actors:
                                            if a["name"] == first_author:
                                                a["type"] = "ORIGIN"
                                    self.log(f"  Wikipedia: first author '{first_author}' ({created})")
                                else:
                                    self.log(f"  Wikipedia: first author skipped (IP or invalid: '{first_author[:20]}')")
            except Exception:
                pass
            
            # Talk-Page Diskutanten
            params2 = {
                "action": "query",
                "titles": f"Talk:{title}",
                "prop": "revisions",
                "rvprop": "user|timestamp",
                "rvlimit": 30,
                "format": "json"
            }
            try:
                r2 = requests.get(api, params=params2, headers=headers, timeout=10)
                if r2.status_code == 200:
                    data2 = r2.json()
                    for page in data2.get("query", {}).get("pages", {}).values():
                        for rev in page.get("revisions", []):
                            user = rev.get("user", "")
                            ts = rev.get("timestamp", "")[:10]
                            if user and not user[:3].replace(".", "").isdigit() and "bot" not in user.lower():
                                actors.append({
                                    "name": user,
                                    "type": "AMPLIFICATION",
                                    "platform": "Wikipedia"
                                })
                                if ts:
                                    dates.append(ts)
            except (json.JSONDecodeError, requests.exceptions.RequestException):
                pass  # Talk-Page ist optional
            
            seen, unique = set(), []
            for a in actors:
                if a["name"] not in seen:
                    seen.add(a["name"])
                    unique.append(a)
            
            result["platform_actors"] = unique[:80]
            result["dates"] = sorted(set(dates))[:10]
            result["text"] = " ".join(texts)[:8000] if texts else f"Wikipedia: {title}"
            result["title"] = title
            
            if unique:
                first = result.get("wiki_first_author", "")
                editors = len([a for a in unique if a.get("type") != "ORIGIN"])
                if first:
                    self.log(f"  Wikipedia: first author '{first}' + {editors} editors for '{title[:30]}'")
                else:
                    self.log(f"  Wikipedia: {len(unique)} editors for '{title[:40]}'")
            
        except requests.exceptions.Timeout:
            self.log(f"Wikipedia timeout for {url[:50]}", "WARNING")
            return self._fetch_html(url, result)
        except requests.exceptions.RequestException as e:
            self.log(f"Wikipedia request error: {e}", "WARNING")
            return self._fetch_html(url, result)
        except Exception as e:
            self.log(f"Wikipedia error: {e}", "WARNING")
        
        return result

    def _fetch_youtube(self, url: str, result: dict, max_comments: int = None) -> dict:
        """
        YouTube innertube API für Kommentare + Replies.
        YouTube Innertube API for comments and replies.
        Extrahiert Top-Level Kommentare UND deren Antworten via Reply-Tokens.
        Extracts top-level comments AND their replies via reply tokens.
        """
        if max_comments is None:
            max_comments = getattr(self, 'comment_pages', 2) * 20  # ~20 Kommentare pro Seite / ~20 comments per page
        import base64 as _b64
        import time
        
        try:
            vid_m = re.search(r'(?:v=|youtu\.be/)([A-Za-z0-9_\-]{11})', url)
            if not vid_m:
                return result
            video_id = vid_m.group(1)

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept-Language": "en-US,en;q=0.9",
                "Content-Type": "application/json",
            }

            r = requests.get(f"https://www.youtube.com/watch?v={video_id}", headers=headers, timeout=15)
            html = r.text

            api_key_m = re.search(r'"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"', html)
            client_m = re.search(r'"INNERTUBE_CLIENT_VERSION"\s*:\s*"([^"]+)"', html)
            api_key = api_key_m.group(1) if api_key_m else "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
            client_ver = client_m.group(1) if client_m else "2.20250101"

            # Metadaten
            title_m = re.search(r'"title"\s*:\s*\{"runs"\s*:\s*\[{"text"\s*:\s*"([^"]+)"', html)
            channel_m = re.search(r'"ownerChannelName"\s*:\s*"([^"]+)"', html)
            desc_m = re.search(r'"shortDescription"\s*:\s*"([^"\\]{10,300})', html)
            date_m = re.search(r'"publishDate"\s*:\s*"(\d{4}-\d{2}-\d{2})', html)

            title = title_m.group(1).strip() if title_m else ""
            channel = channel_m.group(1).strip() if channel_m else ""
            desc = desc_m.group(1).strip() if desc_m else ""
            if date_m:
                result["dates"] = [date_m.group(1)]

            result["title"] = title or url
            result["text"] = f"{title} {channel} {desc}".strip()

            api_url = f"https://www.youtube.com/youtubei/v1/next?key={api_key}"
            
            all_comments = []  # (author, text, is_reply, parent_id)
            processed_comment_ids = set()
            
            # Erster Token für Top-Level Kommentare
            first_token = f'\x12\r\x12\x0b{video_id}\x18\x062\'"\x11"\x0b{video_id}0\x00x\x020\x00B\x10comments-section'
            current_continuation = _b64.b64encode(first_token.encode()).decode()
            
            page = 0
            reply_tokens = []  # Liste von (token, parent_comment_id)
            
            # Extrahiere Kommentare aus mutations
            def extract_comments_from_mutations(mutations, is_reply=False, parent_id=""):
                extracted = []
                for mutation in mutations:
                    payload_data = mutation.get("payload", {})
                    
                    if "commentEntityPayload" in payload_data:
                        comment_payload = payload_data["commentEntityPayload"]
                        props = comment_payload.get("properties", {})
                        author_data = comment_payload.get("author", {})
                        
                        comment_id = props.get("commentId", "")
                        if comment_id in processed_comment_ids:
                            continue
                        
                        content_obj = props.get("content", {})
                        content = content_obj.get("content", "") if isinstance(content_obj, dict) else ""
                        
                        author = author_data.get("displayName", "")
                        if not author:
                            author = props.get("authorButtonA11y", "").lstrip("@")
                        
                        published = props.get("publishedTime", "")
                        reply_count = props.get("replyCount", "0")
                        
                        if author and author not in ("[deleted]", "[removed]", "", "Deleted user"):
                            processed_comment_ids.add(comment_id)
                            extracted.append({
                                "author": author,
                                "text": content[:500],
                                "published": published,
                                "comment_id": comment_id,
                                "is_reply": is_reply,
                                "parent_id": parent_id,
                                "reply_count": reply_count
                            })
                return extracted
            
            # Suche nach Reply-Tokens in continuationItems
            def find_reply_tokens(data, parent_comment_id=""):
                tokens = []
                for ep in data.get("onResponseReceivedEndpoints", []):
                    for action_key in ["appendContinuationItemsAction", "reloadContinuationItemsAction",
                                       "reloadContinuationItemsCommand"]:
                        items = ep.get(action_key, {}).get("continuationItems", [])
                        for item in items:
                            # Reply Continuation Token
                            if "continuationItemRenderer" in item:
                                cont = item["continuationItemRenderer"].get("continuationEndpoint", {})
                                token = cont.get("continuationCommand", {}).get("token")
                                if token:
                                    tokens.append({"token": token, "parent_id": parent_comment_id})
                            
                            # Auch in commentThreadRenderer nach reply tokens suchen
                            if "commentThreadRenderer" in item:
                                thread = item["commentThreadRenderer"]
                                if "replies" in thread:
                                    replies = thread["replies"].get("commentRepliesRenderer", {})
                                    for reply_item in replies.get("contents", []):
                                        if "continuationItemRenderer" in reply_item:
                                            cont = reply_item["continuationItemRenderer"].get("continuationEndpoint", {})
                                            token = cont.get("continuationCommand", {}).get("token")
                                            if token:
                                                # Parent comment ID aus dem Thread
                                                vm = thread.get("commentViewModel", {}).get("commentViewModel", {})
                                                parent_cid = vm.get("commentId", parent_comment_id)
                                                tokens.append({"token": token, "parent_id": parent_cid})
                return tokens
            
            # Schritt 1: Alle Top-Level Kommentare laden
            while len([c for c in all_comments if not c.get("is_reply")]) < max_comments:
                page += 1
                self.log(f"  YouTube: Lade Top-Level Seite {page}...")
                
                payload = {
                    "context": {"client": {"clientName": "WEB", "clientVersion": client_ver, "hl": "en", "gl": "US"}},
                    "continuation": current_continuation,
                }
                
                r2 = requests.post(api_url, json=payload, headers={
                    **headers,
                    "X-YouTube-Client-Name": "1",
                    "X-YouTube-Client-Version": client_ver,
                }, timeout=20)
                
                if r2.status_code != 200:
                    self.log(f"  YouTube API error: {r2.status_code}")
                    break
                
                data = r2.json()
                
                # Extrahiere Kommentare
                mutations = data.get("frameworkUpdates", {}).get("entityBatchUpdate", {}).get("mutations", [])
                new_comments = extract_comments_from_mutations(mutations, is_reply=False)
                
                # Reply-Tokens aus dieser Response extrahieren
                new_reply_tokens = find_reply_tokens(data)
                reply_tokens.extend(new_reply_tokens)
                
                # Kommentare speichern
                for c in new_comments:
                    if c.get("comment_id"):
                        all_comments.append(c)
                
                self.log(f"    Seite {page}: {len(new_comments)} Top-Level, {len(new_reply_tokens)} Reply-Token gefunden (total: {len(all_comments)})")
                
                # Nächsten Continuation Token für Top-Level
                next_continuation = None
                for ep in data.get("onResponseReceivedEndpoints", []):
                    for action_key in ["appendContinuationItemsAction", "reloadContinuationItemsAction",
                                       "reloadContinuationItemsCommand"]:
                        items = ep.get(action_key, {}).get("continuationItems", [])
                        for item in items:
                            if "continuationItemRenderer" in item:
                                cont = item["continuationItemRenderer"].get("continuationEndpoint", {})
                                next_continuation = cont.get("continuationCommand", {}).get("token")
                                if next_continuation:
                                    break
                        if next_continuation:
                            break
                    if next_continuation:
                        break
                
                if next_continuation and next_continuation != current_continuation:
                    current_continuation = next_continuation
                    time.sleep(0.2)
                else:
                    break
                
                if page > 30:  # Max 30 Seiten
                    break
            
            self.log(f"  YouTube: {len(all_comments)} Top-Level Kommentare, {len(reply_tokens)} Reply-Token gefunden")
            
            # Schritt 2: Replies für jeden Reply-Token laden
            reply_comments = []
            
            for idx, rt in enumerate(reply_tokens[:100]):  # Max 100 Reply-Threads
                token = rt.get("token") if isinstance(rt, dict) else rt
                parent_id = rt.get("parent_id", "") if isinstance(rt, dict) else ""
                
                if not token:
                    continue
                
                self.log(f"    Lade Replies {idx+1}/{len(reply_tokens[:50])} (parent: {parent_id[:20]})...")
                
                reply_payload = {
                    "context": {"client": {"clientName": "WEB", "clientVersion": client_ver, "hl": "en", "gl": "US"}},
                    "continuation": token,
                }
                
                r3 = requests.post(api_url, json=reply_payload, headers={
                    **headers,
                    "X-YouTube-Client-Name": "1",
                    "X-YouTube-Client-Version": client_ver,
                }, timeout=15)

                if r3.status_code in (403, 429):
                    wait = min(2 ** idx, 60)
                    self.log(f"  YouTube Rate Limit ({r3.status_code}) – warte {wait}s", "WARNING")
                    time.sleep(wait)
                    continue

                if r3.status_code != 200:
                    self.log(f"  YouTube Reply HTTP {r3.status_code}", "WARNING")
                    continue

                reply_data = r3.json()

                # Extrahiere Replies aus mutations
                reply_mutations = reply_data.get("frameworkUpdates", {}).get("entityBatchUpdate", {}).get("mutations", [])
                new_replies = extract_comments_from_mutations(reply_mutations, is_reply=True, parent_id=parent_id)

                for reply in new_replies:
                    if reply.get("comment_id"):
                        reply_comments.append(reply)

                # Auch weitere Reply-Tokens aus der Reply-Response
                deeper_tokens = find_reply_tokens(reply_data, parent_id)
                for dt in deeper_tokens:
                    if dt not in reply_tokens:
                        reply_tokens.append(dt)

                if new_replies:
                    self.log(f"      {len(new_replies)} Replies geladen")
                
                time.sleep(random.uniform(0.8, 1.5))  # Jitter – YouTube Rate Limiting
            
            # Alle Kommentare zusammenführen
            all_comments.extend(reply_comments)
            self.log(f"  YouTube: {len(all_comments)} Kommentare insgesamt ({len([c for c in all_comments if not c.get('is_reply')])} Top-Level, {len([c for c in all_comments if c.get('is_reply')])} Replies)")
            
            # Akteure sammeln
            seen = set()
            actors = []

            if channel:
                seen.add(channel)
                actors.append({"name": channel, "type": "ORIGIN", "platform": "YouTube",
                                "text": result.get("text","")[:500], "depth": 0})

            for c in all_comments[:max_comments]:
                if c.get("author") and c["author"] not in seen:
                    seen.add(c["author"])
                    actors.append({
                        "name":     c["author"],
                        "type":     "AMPLIFICATION",
                        "platform": "YouTube",
                        "text":     c.get("text","")[:500],   # Kommentar-Text
                        "depth":    1 if not c.get("is_reply") else 2,  # 1=Hauptkommentar, 2=Reply
                    })
            
            # Texte für LLM sammeln
            texts = [result.get("text", "")]
            for c in all_comments[:300]:
                if c.get("text"):
                    texts.append(c["text"])
            
            result["text"] = " ".join(t for t in texts if t)[:8000]
            result["platform_actors"] = actors
            result["comment_count"] = len(all_comments)
            result["top_level_count"] = len([c for c in all_comments if not c.get("is_reply")])
            result["reply_count"] = len([c for c in all_comments if c.get("is_reply")])
            self.log(f"  YouTube total: {len(actors)} Akteure (Kanal + {len(actors)-1 if channel else len(actors)} Kommentatoren) | {result['top_level_count']} Top-Level, {result['reply_count']} Replies")

        except Exception as e:
            self.log(f"YouTube Fehler: {e}", "WARNING")
            import traceback
            self.log(f"  Trace: {traceback.format_exc()[:300]}")
        
        return result

    def _fetch_html(self, url: str, result: dict, max_chars: int = 8000,
                    follow_links: bool = False, link_depth: int = 1) -> dict:
        """Standard HTML-Fetch für alle anderen Seiten."""
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
            html = r.text

            text = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>',  ' ', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            result["text"] = text[:max_chars]

            raw_links = re.findall(r'href=["\']([^"\']+)["\']', html)
            base = re.match(r'(https?://[^/]+)', url)
            base_url = base.group(1) if base else ""
            # Nur echte Seiten-Links – keine Assets/Bilder/Scripts
            skip_ext = ('.png','.jpg','.jpeg','.gif','.ico','.svg','.webp',
                        '.js','.css','.woff','.woff2','.ttf','.pdf',
                        '.mp4','.mp3','.zip','.json','.xml')
            skip_pat = ('javascript:','mailto:','tel:','#','data:',
                        'intent/','share?','login','signin','signup',
                        'cdn.','cdnassets','static.','assets.')
            links = []
            for lnk in raw_links:
                if any(lnk.lower().endswith(e) for e in skip_ext):
                    continue
                if any(p in lnk.lower() for p in skip_pat):
                    continue
                if lnk.startswith('http'):
                    links.append(lnk)
                elif lnk.startswith('/') and base_url:
                    links.append(base_url + lnk)
            result["links"] = list(set(links))[:50]

            uname_patterns = [
                r'/(?:user|u|profile|member|author|by|p)/([A-Za-z0-9_\-\.]{3,30})',
                r'/@([A-Za-z0-9_\.]{3,30})',
                r'(?:^|\s)@([A-Za-z0-9_\.]{3,30})',
            ]
            usernames = set()
            for pat in uname_patterns:
                usernames.update(re.findall(pat, html + " " + text[:2000]))

            url_lower = url.lower()
            platform_actors = []

            if "reddit.com" in url_lower:
                # Reddit ist SPA – Usernames aus URLs extrahieren (funktioniert auch ohne JS)
                op = re.findall(r'(?:submitted|posted)\s+by\s+u/([A-Za-z0-9_\-]{3,30})', html, re.IGNORECASE)
                # Alle /user/ und /u/ Links im HTML
                all_users = re.findall(r'href=["\'][^"\']*?/(?:u|user)/([A-Za-z0-9_\-]{3,30})["\']', html)
                # Auch im Text-Content
                all_users += re.findall(r'u/([A-Za-z0-9_\-]{3,30})', text[:5000])
                subreddit = re.findall(r'/r/([A-Za-z0-9_]{3,30})/', url)
                skip_users = {'wiki','mod','help','admin','reddit','AutoModerator',
                              'deleted','removed','u','r','comments','search'}
                op_set = set(op)
                seen_users = set()
                for u in op:
                    if u not in skip_users and u not in seen_users:
                        seen_users.add(u)
                        platform_actors.append({"name": f"u/{u}", "type": "ORIGIN",
                                                "platform": "Reddit",
                                                "subreddit": subreddit[0] if subreddit else ""})
                for u in all_users:
                    if u not in skip_users and u not in seen_users and u not in op_set:
                        seen_users.add(u)
                        platform_actors.append({"name": f"u/{u}", "type": "AMPLIFICATION",
                                                "platform": "Reddit",
                                                "subreddit": subreddit[0] if subreddit else ""})

            elif "twitter.com" in url_lower or "x.com" in url_lower:
                handles = re.findall(r'href=["\'][^"\']*?twitter\.com/([A-Za-z0-9_]{3,30})["\']', html)
                handles += re.findall(r'@([A-Za-z0-9_]{3,30})', text[:3000])
                for h in set(handles):
                    platform_actors.append({"name": f"@{h}", "type": "AMPLIFICATION", "platform": "Twitter"})

            elif "4chan.org" in url_lower or "4plebs" in url_lower:
                posts = re.findall(r'No\.(\d{6,12})', html)
                times = re.findall(r'(\d{2}/\d{2}/\d{2,4})', html)
                for pid in posts[:20]:
                    platform_actors.append({"name": f"Anonymous#{pid}", "type": "AMPLIFICATION",
                                             "platform": "4chan"})

            elif "telegram" in url_lower:
                channels = re.findall(r't\.me/([A-Za-z0-9_]{5,30})', html)
                forwarded = re.findall(r'Forwarded from[:\s]+([^\n<]{3,50})', html)
                for ch in set(channels):
                    platform_actors.append({"name": ch, "type": "AMPLIFICATION", "platform": "Telegram"})
                for fw in set(forwarded):
                    platform_actors.append({"name": fw.strip(), "type": "ORIGIN", "platform": "Telegram"})

            result["platform_actors"] = platform_actors

            stopwords = {'com','net','org','www','http','html','php','asp','jpg','png','css','js',
                         'edit','page','index','search','login','help','about','contact','home',
                         'wiki','static','cdn','api','media','img','image','thumb','file'}
            result["usernames"] = [u for u in usernames if u.lower() not in stopwords][:20]

            # Datum extrahieren – Meta-Tags, JSON-LD und Text
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',
                r'\d{2}\.\d{2}\.\d{4}',
                r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}',
                r'\d{4}/\d{2}/\d{2}',
            ]
            dates = []
            # Meta-Tags (publishedTime, datePublished etc.) aus rohem HTML
            meta_dates = re.findall(
                r'(?:datePublished|published_time|article:published|date)["\s:=]+["\']?(\d{4}-\d{2}-\d{2})',
                html[:5000], re.IGNORECASE)
            dates.extend(meta_dates)
            # JSON-LD structured data
            jsonld = re.findall(r'"datePublished"\s*:\s*"([^"]+)"', html)
            dates.extend(jsonld)
            # Text-basiert
            for pat in date_patterns:
                dates.extend(re.findall(pat, text[:5000]))
            # Sortieren – ältestes Datum zuerst
            valid_dates = []
            for d in set(dates):
                try:
                    yr = int(re.search(r'\d{4}', d).group())
                    if 1990 <= yr <= 2030:
                        valid_dates.append(d)
                except Exception:
                    pass
            valid_dates.sort()
            result["dates"] = valid_dates[:10]

            share_match = re.search(r'(\d[\d,\.]+)\s*(?:share|repost|retweet)', html, re.IGNORECASE)
            like_match  = re.search(r'(\d[\d,\.]+)\s*(?:like|heart|reaction)', html, re.IGNORECASE)
            if share_match: result["shares"] = share_match.group(1).replace(',','')
            if like_match:  result["likes"]  = like_match.group(1).replace(',','')

            if follow_links and link_depth > 1:
                followed = 0
                for lnk in result["links"][:5]:
                    if followed >= 3:
                        break
                    try:
                        sub = self.fetch_page(lnk, max_chars=3000,
                                              follow_links=link_depth > 2,
                                              link_depth=link_depth - 1)
                        result["pages"].append(sub)
                        result["usernames"].extend(sub.get("usernames", []))
                        followed += 1
                    except Exception:
                        pass
                result["usernames"] = list(set(result["usernames"]))[:30]

        except Exception as e:
            self.log(f"Fetch failed {url[:50]}: {e}", "WARNING")
        return result

    def search_wayback(self, query: str) -> List[dict]:
        """
        Sucht im Wayback Machine via normales Web-Browsing (kein API).
        Lädt https://web.archive.org/web/*/<query-url> und extrahiert Snapshots.
        """
        results = []
        wayback_search_url = f"https://web.archive.org/web/*/https://*.{query.replace(' ', '+')}"
        try:
            r = requests.get(
                f"https://web.archive.org/web/*/{query}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20
            )
            links = re.findall(r'https://web\.archive\.org/web/(\d{14})/([^\s"<]+)', r.text)
            seen = set()
            for ts, orig_url in links[:20]:
                if orig_url in seen:
                    continue
                seen.add(orig_url)
                date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                results.append({
                    "url":         orig_url,
                    "archive_url": f"https://web.archive.org/web/{ts}/{orig_url}",
                    "date":        date_str,
                    "timestamp":   ts,
                })
        except Exception as e:
            self.log(f"Wayback failed: {e}", "WARNING")
        return results


# ── Research Agent ─────────────────────────────────────────────────────────────

@dataclass
class Investigation:
    """Eine forensische Untersuchung – entspricht einem 'Seed' in lyra_network_builder."""
    uid:            str
    query:          str
    status:         str = "pending"
    created:        str = field(default_factory=_now_iso)
    findings:       int = 0
    actors_found:   int = 0
    depth:          int = 0
    max_depth:      int = 5
    search_breadth: int = 20
    search_depth:   int = 1
    comment_pages:  int = 2   # Kommentarseiten pro Thread (YouTube/Reddit Paginierung)
    notes:          List[str] = field(default_factory=list)


class NarrativeAgent:
    """
    Autonomer Recherche-Agent für forensische Narrativ-Analyse.

    Workflow pro Investigation:
    1. Web-Suche nach dem Narrativ (aktuell + historisch via Wayback)
    2. LLM extrahiert Akteure, Daten, Plattformen
    3. Für jeden gefundenen Akteur: suche weitere Narrative dieses Akteurs
    4. Vergleiche Narrative semantisch → SUPPORTS/INSPIRED_BY Kanten
    5. Identifiziere Koordinationssignale
    6. Schreibe Dossier + aktualisiere Datenbank
    """

    # Zentrale Liste technischer Domains – niemals als Sub-Seiten verfolgen
    SKIP_DOMAINS = {
        'fonts.googleapis.com', 'policies.google.com', 'consent.youtube.com',
        'accounts.google.com', 'support.google.com', 'play.google.com',
        'schema.org', 'w3.org', 'creativecommons.org', 'doi.org',
        'archive.org', 'web.archive.org', 'wikimedia.org', 'wikidata.org',
        'google-analytics.com', 'googletagmanager.com', 'googleadservices.com',
        'geolocation.onetrust.com', 'onetrust.com', 'cookielaw.org',
        'doubleclick.net', 'googlesyndication.com', 'facebook.net',
        'cdn.jsdelivr.net', 'cdnjs.cloudflare.com', 'unpkg.com',
    }

    SKIP_PATHS = (
        '/terms', '/privacy', '/login', '/signin', '/signup', '/register',
        '/fonts', '/css', '/js', '/static', '/cdn', '/assets',
        '/about/regional', '/take-action', '/glass-leadership',
        '/programm', '/wirtschaft', '/stellenabbau', '/klimawandel',
        '/nachrichten', '/hintergrund', '/consent', '/cookies',
        'action=edit', 'Special:', 'index.php?title=ISSN',
        'ISO_1', 'ISO_3', 'ISO_6', 'ISO_7', 'ISO_9',
    )

    def __init__(self, db: NarrativeNeo4j, log_fn=None):
        self.db         = db
        self.llm        = NarrativeLLM(log_fn=log_fn)
        self.searcher   = NarrativeSearcher(log_fn=log_fn)
        self.importer   = ArtifactImporter(db, log_fn=log_fn)
        self.log        = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [AGENT] {m}"))

        self.investigations: List[Investigation] = []
        self.activity:       List[dict]          = []
        self.running:        bool                = False
        self._stop:          threading.Event     = threading.Event()
        self._new_work:      threading.Event     = threading.Event()
        self._lock:          threading.RLock     = threading.RLock()
        self._thread:        Optional[threading.Thread] = None

        NARRATIVE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ── State-Persistenz ──────────────────────────────────────────────────────

    def _save_state(self):
        data = {
            "saved":          _now_iso(),
            "investigations": [
                {k: v for k, v in inv.__dict__.items()}
                for inv in self.investigations
            ]
        }
        try:
            NARRATIVE_DB_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            self.log(f"State save error: {e}", "WARNING")

    def _load_state(self):
        if not NARRATIVE_DB_FILE.exists():
            return
        try:
            data = json.loads(NARRATIVE_DB_FILE.read_text(encoding="utf-8"))
            seen_queries = set()
            for d in data.get("investigations", []):
                inv = Investigation(**{k: v for k, v in d.items()
                                       if k in Investigation.__dataclass_fields__})
                if inv.status == "active":
                    inv.status = "pending"
                key = inv.query.lower().strip()
                if key in seen_queries:
                    continue
                seen_queries.add(key)
                self.investigations.append(inv)
            self.log(f"State loaded: {len(self.investigations)} investigations", "SUCCESS")
        except Exception as e:
            self.log(f"State load error: {e}", "WARNING")

    def _add_activity(self, msg: str):
        ts = time.strftime("%H:%M")
        with self._lock:
            self.activity.insert(0, {"time": ts, "message": msg})
            self.activity = self.activity[:50]

    # ── Investigation-Management ──────────────────────────────────────────────

    def add_investigation(self, query: str,
                          search_breadth: int = 20,
                          search_depth: int = 1,
                          comment_pages: int = 2) -> Investigation:
        query = query.strip()
        with self._lock:
            for existing in self.investigations:
                if existing.query.lower() == query.lower() and existing.status != "done":
                    self.log(f"Duplicate ignored: {query[:50]}", "WARNING")
                    return existing
            inv = Investigation(
                uid=f"inv_{uuid.uuid4().hex[:12]}",
                query=query,
                status="pending",
                search_breadth=max(5, min(100, search_breadth)),
                search_depth=max(1, min(5, search_depth)),
                comment_pages=max(1, min(100, comment_pages)),
            )
            self.investigations.append(inv)
        self._add_activity(f"➕ New investigation: {query[:60]} (breadth:{inv.search_breadth} depth:{inv.search_depth})")
        self._new_work.set()
        self._save_state()
        return inv

    def start(self):
        if self.running:
            return
        self.running  = True
        self._stop.clear()
        self._thread  = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.log("Agent started", "SUCCESS")

    def stop(self):
        self.running = False
        self._stop.set()
        self._new_work.set()
        self._save_state()
        self.log("Agent stopped", "INFO")

    # ── Haupt-Loop ────────────────────────────────────────────────────────────

    def _loop(self):
        self.log("Research loop started")
        while not self._stop.is_set():
            inv = None
            with self._lock:
                for candidate in self.investigations:
                    if candidate.status == "pending":
                        inv = candidate
                        inv.status = "active"
                        break

            if inv is None:
                self._add_activity("⏳ Waiting for investigation")
                self._new_work.clear()
                self._new_work.wait(timeout=30)
                continue

            try:
                self._investigate(inv)
                with self._lock:
                    inv.status = "done"
                self._add_activity(f"✅ Completed: {inv.query[:50]} | {inv.findings} hits | {inv.actors_found} actors")
            except Exception as e:
                self.log(f"Error in {inv.uid}: {e}", "ERROR")
                with self._lock:
                    inv.status = "pending"
                self._add_activity(f"❌ Error: {str(e)[:80]}")

            self._save_state()
            time.sleep(2)

    # ── Kernlogik ─────────────────────────────────────────────────────────────

    def _investigate(self, inv: Investigation):
        """Forensische Untersuchung – orchestriert alle Phasen.
        Forensic investigation – orchestrates all phases."""
        self.log(f"Investigating: {inv.query[:60]} (breadth:{inv.search_breadth} depth:{inv.search_depth} comments:{inv.comment_pages})")
        self.searcher.comment_pages = inv.comment_pages
        self._add_activity(f"🔬 Untersuche: {inv.query[:60]}")

        fp    = _fingerprint(inv.query)
        n_uid = f"narr_{fp}"
        self.db.upsert_narrative(uid=n_uid, text=inv.query, inv_uid=inv.uid, first_seen=inv.created)

        # Phase 1: URLs sammeln (SearXNG + Wayback)
        all_urls = self._collect_urls(inv)

        # Phase 2: Seiten laden + LLM-Analyse / Load pages + LLM analysis
        all_pages, seen_page_urls, found_actors, inv_origin_set = self._load_and_process_pages(
            inv, all_urls, n_uid
        )

        # Phase 3: SearXNG Blind-Flecken-Check / Blind-spot check
        self._blind_spot_check(inv, all_pages, seen_page_urls, found_actors, n_uid, inv_origin_set)

        # Phase 4: Fingerprinting + Koordinationserkennung
        self._fingerprint_actors(inv, found_actors, all_pages)

        # Phase 5: Orphan-Check – alle Knoten ohne vollständige Kanten-Kette
        self._orphan_check(inv, n_uid)

        self._write_dossier(inv, found_actors, n_uid)

    def _collect_urls(self, inv: Investigation) -> list:
        """Phase 1: SearXNG Suche → deduplizierte URL-Liste.
        Phase 1: SearXNG search → deduplicated URL list."""
        q = inv.query
        search_queries = [
            q,
            f"{q} youtube.com",
            f"{q} forum OR reddit OR 4chan OR telegram",
            f'"{q}" site:reddit.com',
            f"{q} origin earliest 2000..2020",
            f"{q} blog OR article OR post",
        ]
        all_urls  = []
        seen_urls = set()
        per_q     = max(5, inv.search_breadth // 2)
        for sq in search_queries:
            results = self.searcher.search_web(sq, num_results=per_q)
            new = 0
            for item in results:
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                all_urls.append({
                    "url":     url,
                    "title":   item.get("title", ""),
                    "content": item.get("content", "").strip(),
                    "engine":  item.get("engine", ""),
                    "score":   item.get("score", 0),
                })
                new += 1
            self.log(f"  SearXNG '{sq[:50]}': {len(results)} Treffer ({new} neu)")
        for hit in self.searcher.search_wayback(inv.query)[:3]:
            if hit["archive_url"] not in seen_urls:
                seen_urls.add(hit["archive_url"])
                all_urls.append({"url": hit["archive_url"],
                                  "title": f"[Archiv {hit['date']}]",
                                  "content": "", "date_hint": hit["date"]})
        all_urls = all_urls[:inv.search_breadth]
        self.log(f"  {len(all_urls)} URLs gesammelt")
        return all_urls

    def _load_and_process_pages(self, inv: Investigation, all_urls: list,
                                 n_uid: str) -> tuple:
        """Phase 2: Seiten laden und LLM-Analyse.
        Phase 2: Load pages and LLM analysis.
        Nimmt die bereits gesammelten URLs aus _collect_urls entgegen.
        Receives the URL list already built by _collect_urls – no second search pass.
        Returns: (all_pages, seen_page_urls, found_actors)
        """
        # Seiten laden – collect_page via Factory (SKIP_DOMAINS/SKIP_PATHS aus Klassenkonstante)
        # Load pages – collect_page via factory (SKIP_DOMAINS/SKIP_PATHS from class constant)
        all_pages      = []
        seen_page_urls = set()
        narrative_keywords = [w.lower() for w in inv.query.split() if len(w) > 3]
        collect_page, page_contains_narrative = self._make_collect_page(
            inv, all_pages, seen_page_urls, narrative_keywords
        )
        for item in all_urls:
            try:
                from urllib.parse import urlparse
                base_dom = urlparse(item.get("url","")).netloc.lower()
            except Exception:
                base_dom = ""
            # Direkte Suchtreffer immer laden – kein Relevanz-Check
            collect_page(item, inv.search_depth, base_dom, is_direct=True)

        self.log(f"  {len(all_pages)} pages loaded (incl. sub-pages)")

        found_actors  = {}
        comment_limit = max(5, min(500, inv.comment_pages * 25))
        inv_origin_set = False  # True sobald Origin aus Wikipedia extrahiert

        for page in all_pages:
            url_lower = page["url"].lower()
            # Alle geladenen Seiten verarbeiten – collect_page hat bereits gefiltert

            plat_name = _platform_from_url(page["url"])
            p_uid     = self.db.upsert_platform(plat_name, page["url"], inv.uid)

            a_uid = f"art_{_fingerprint(page['url'])}"
            date  = page.get("date_hint") or (page.get("dates") or [""])[0]

            self.log(f"  LLM: {page['url'][:60]}")
            extracted = self.llm.extract_actors_and_events(
                page["text"], inv.query, source_url=page["url"]
            )

            # Origin direkt aus Referenztext extrahieren
            # Priorität: Wikipedia > KnowYourMeme > seriöse Medien > erste brauchbare Seite
            # Social/Video-Plattformen werden NICHT für Origin genutzt
            if not inv_origin_set and page.get("text") and len(page["text"]) > 500:
                url_lower = page["url"].lower()
                skip_for_origin = any(s in url_lower for s in [
                    "youtube.", "reddit.", "twitter.", "x.com", "facebook.",
                    "4chan.", "telegram", "instagram.", "tiktok.", "alamy.",
                    "tenor.", "imgur.", "tumblr."
                ])
                is_reference = (not skip_for_origin) and (
                    "wikipedia.org" in url_lower or
                    "knowyourmeme.com" in url_lower or
                    any(m in url_lower for m in ["bbc.", "nytimes.", "theguardian.",
                                                  "reuters.", "apnews.", "spiegel.",
                                                  "zeit.de", "faz.net"])
                )
                is_fallback = (not skip_for_origin and not is_reference and
                               len(page["text"]) > 1000)

                if is_reference or is_fallback:
                    origin_raw = self.llm.query(
                        "Du bist ein neutraler Dokumentations-Assistent. "
                        "Lies den Text und beantworte: Wer hat das beschriebene Narrativ/Konzept/Werk "
                        "ERSTMALS erschaffen oder in die Welt gebracht? "
                        "Nenne NUR den Namen und das Jahr (aus dem Text). "
                        "Keine Bewertung. Wenn nicht eindeutig erkennbar: name = null. "
                        'Antworte NUR mit JSON: {"name":"Name oder null","date":"YYYY oder YYYY-MM-DD oder null"}',
                        f"Narrativ: {inv.query}\n\nText:\n{page['text'][:4000]}",
                        max_tokens=100
                    )
                    origin_data = self.llm._parse_json(origin_raw)
                    if origin_data and origin_data.get("name"):
                        oname = origin_data["name"]
                        odate = str(origin_data.get("date") or "")
                        if odate and len(odate) == 4:
                            odate = f"{odate}-01-01"
                        o_uid = f"actor_{_fingerprint(oname.lower())}"
                        self.db.upsert_actor(
                            uid=o_uid, name=oname,
                            platform_name=_platform_from_url(page["url"]),
                            actor_type="Person", first_seen=odate,
                            confidence=0.95, inv_uid=inv.uid,
                            stance="neutral", is_author=True,
                            source_url=page["url"]
                        )
                        # Guard: direct session call only when DB is available
                        if self.db.get_driver():
                            with self.db.get_driver().session() as s_orig:
                                s_orig.run(
                                    "MATCH (a:NF_Actor {uid:$uid}) SET a.role='ORIGIN'",
                                    uid=o_uid
                                )
                        inv_origin_set = True
                        found_actors[o_uid] = oname
                        self.log(f"  🎯 Origin: {oname} ({odate}) via {_platform_from_url(page['url'])}")
            stance_data = self.llm.document_positioning(page["text"], inv.query)
            art_stance  = stance_data.get("stance", "neutral")
            art_sc      = stance_data.get("confidence", 0.5)

            # Datum: page-meta > LLM-Ergebnis > leer
            if not date:
                date = extracted.get("earliest_date", "") or ""
            date_clean = date[:10] if len(date) >= 10 else date

            self.db.upsert_article(
                uid=a_uid, title=page["title"][:200],
                url=page["url"], platform_uid=p_uid,
                date=date_clean,
                inv_uid=inv.uid,
                stance=art_stance, stance_confidence=art_sc
            )
            # Platform → SPREADS → Narrativ – guaranteed for every article saved
            self.db.platform_spreads_narrative(p_uid, n_uid)
            self.log(f"  🔗 PUBLISHED_ON     {page['title'][:30]:30} → {plat_name}")

            # ── Batch-Stance für alle Kommentare einer Seite ─────────────────
            # Ein LLM-Call für alle statt n einzelne Calls
            platform_actors_raw = page.get("platform_actors", [])
            batch_stances = {}
            comments_with_text = [
                pa for pa in platform_actors_raw
                if pa.get("text","").strip() and len(pa.get("text","").strip()) > 20
            ]
            if comments_with_text:
                batch_size = 15
                for i in range(0, len(comments_with_text), batch_size):
                    batch = comments_with_text[i:i+batch_size]
                    batch_prompt = (
                        f"Narrativ: {inv.query}\n\n"
                        f"Bewerte JEDEN Kommentar einzeln.\n\n"
                        f"Antworte NUR mit JSON:\n"
                        f'{{"stances": {{"AkteurName": {{"stance": "supporting|opposing|neutral", "confidence": 0.0-1.0, "evidence": "kurze Begründung"}}}}}}\n\n'
                        f"Kommentare:\n"
                        + "\n".join(
                            f"[{pa['name']}]: {pa['text'][:200]}"
                            for pa in batch
                        )
                    )
                    batch_raw = self.llm.query(
                        "Du bist ein neutraler forensischer Dokumentations-Assistent. "
                        "Bewerte Kommentare zum Narrativ. "
                        "supporting=unterstützt, opposing=widerspricht, neutral=sachlich/unklar. "
                        "Keine Wertung, nur Dokumentation.",
                        batch_prompt, max_tokens=600
                    )
                    batch_data = self.llm._parse_json(batch_raw)
                    if batch_data and "stances" in batch_data:
                        for name, val in batch_data["stances"].items():
                            if isinstance(val, dict):
                                batch_stances[name] = val
                            else:
                                batch_stances[name] = {"stance": str(val), "confidence": 0.5, "evidence": ""}

            wiki_first_author = page.get("wiki_first_author", "")

            for pa in platform_actors_raw:
                if not pa.get("name"):
                    continue
                pa_name = pa["name"].strip()
                if not pa_name or pa_name.lower() in {"u/deleted","u/removed","u/automoderator"}:
                    continue
                act_uid   = f"actor_{_fingerprint(pa_name.lower())}"
                role      = pa.get("type", "AMPLIFICATION")
                is_op     = (role == "ORIGIN")
                is_editor = (role == "EDITOR")
                pa_plat   = pa["platform"]

                # Wikipedia: Erstautor = is_author, alle anderen Editoren = is_editor
                if pa_plat == "Wikipedia":
                    is_author_wiki = (pa_name == wiki_first_author)
                    is_editor_wiki = not is_author_wiki
                else:
                    is_author_wiki = is_op
                    is_editor_wiki = is_editor

                # Stance aus Batch-Ergebnis oder Fallback
                if pa_name in batch_stances:
                    bs = batch_stances[pa_name]
                    if isinstance(bs, dict):
                        pa_stance     = bs.get("stance", art_stance)
                        pa_confidence = float(bs.get("confidence", 0.5))
                    else:
                        pa_stance     = str(bs)
                        pa_confidence = 0.5
                else:
                    pa_stance     = art_stance
                    pa_confidence = 0.5

                self.db.upsert_actor(
                    uid=act_uid, name=pa_name,
                    platform_name=pa_plat,
                    actor_type="Account", first_seen=date,
                    confidence=pa_confidence,
                    inv_uid=inv.uid,
                    stance=pa_stance,
                    source_url=page["url"],
                    is_author=is_author_wiki,
                    is_editor=is_editor_wiki
                )
                pa_plat_uid = self.db.upsert_platform(pa_plat, page["url"], inv.uid)
                # Fix 8: LINKS_TO für alle platform_actors
                self.db.actor_links_to_platform(act_uid, pa_plat_uid)

                if is_op:
                    # Autor → schrieb den Artikel + Comment-Knoten für Visualisierung
                    self.db.actor_authored_article(act_uid, a_uid)
                    self.db.actor_spreads_narrative(
                        actor_uid=act_uid, narrative_uid=n_uid,
                        role=role, stance="neutral", confidence=0.7,
                        date=date, url=page["url"]
                    )
                    _c_key = f"{act_uid}{a_uid}op"
                    c_uid  = f"comment_{_fingerprint(_c_key)}"
                    self.db.upsert_comment(
                        uid=c_uid, article_uid=a_uid, actor_uid=act_uid,
                        date=date, text="",
                        score=0, inv_uid=inv.uid, stance="neutral"
                    )
                else:
                    # Kommentator → NF_Comment → Artikel
                    _c_key = f"{act_uid}{a_uid}{pa.get('text','')[:80]}"
                    c_uid = f"comment_{_fingerprint(_c_key)}"
                    self.db.upsert_comment(
                        uid=c_uid, article_uid=a_uid, actor_uid=act_uid,
                        date=date, text=pa.get("text","")[:200],  # Fix 15: text statt name
                        score=0, inv_uid=inv.uid, stance="neutral"
                    )

                found_actors[act_uid] = pa_name

            actor_count_this_page = 0
            for actor_data in extracted.get("actors", []):
                name = actor_data.get("name", "").strip()

                # Invalide Namen überspringen
                invalid_names = {
                    "", "unknown", "unbekannt", "n/a", "none", "null",
                    "unknownuser", "unknownauthor", "anonymous user",
                    "anonymous", "unbekannter nutzer", "user", "users",
                    "deleted", "removed", "u/deleted", "u/removed",
                    "u/unknown", "u/anotheruser", "u/unknownuser",
                    "automoderator", "origin", "anotheruser",
                }
                name_lower = name.lower()
                if not name or name_lower in invalid_names:
                    continue
                # Generische Gruppen-Namen ohne Identität → überspringen
                generic_suffixes = (" community", " movement", " users", " group",
                                    " network", " collective", " team")
                if any(name_lower.endswith(s) for s in generic_suffixes):
                    continue
                # Nicht-ASCII Namen (Arabisch, Chinesisch etc.) → wahrscheinlich Duplikat
                if not all(ord(c) < 256 for c in name):
                    self.log(f"  ↷ Non-ASCII name skipped: {name[:30]}")
                    continue
                if float(actor_data.get("confidence", 0.5)) < 0.35:
                    continue
                if actor_count_this_page >= comment_limit:
                    break

                # Plattformen die als Akteure extrahiert werden → in NF_Platform umwandeln
                known_platforms = {
                    "twitter","x.com","reddit","4chan","8chan","tumblr","facebook",
                    "youtube","instagram","telegram","myspace","gaia online",
                    "gaiaonline","discord","tiktok","linkedin","pinterest",
                    "twitch","snapchat","whatsapp","signal","mastodon",
                }
                if name.lower() in known_platforms:
                    plat_uid = self.db.upsert_platform(name, page["url"], inv.uid)
                    self.db.platform_spreads_narrative(plat_uid, n_uid)
                    continue

                # Name normalisieren + Duplikate zusammenführen
                # Normalize name + merge duplicates
                name_norm = re.sub(r'\s+', ' ', name.strip())

                # Dynamische Alias-Tabelle: leitet Varianten des Query-Terms auf den Canonical-Namen.
                # Dynamic alias table: maps query-term variants to canonical names.
                # Hartcodierte Einträge nur für stabile Plattform-Abbreviaturen (kein Narrativ-Bezug).
                # Hard-coded entries only for stable platform abbreviations (no narrative-specific content).
                static_aliases = {
                    "vice": "VICE",
                    "@vice": "VICE",
                    "pbs (public broadcasting service)": "PBS",
                    "independentlens": "Independent Lens",
                    "boys club": "Boy's Club",
                    "boys' club": "Boy's Club",
                }
                # Narrative-spezifische Aliase dynamisch aus dem Query ableiten
                # Derive narrative-specific aliases dynamically from the query string
                dynamic_aliases: dict = {}
                q_words = [w.strip("'\".,!?") for w in inv.query.split() if len(w) >= 4]
                q_canonical = inv.query.strip()  # Canonical form = the query itself
                q_lower     = q_canonical.lower()
                for qw in q_words:
                    qw_lower = qw.lower()
                    # e.g. "Pepe (character)" → "Pepe the Frog"
                    dynamic_aliases[f"{qw_lower} (character)"] = q_canonical
                    dynamic_aliases[f"{qw_lower} (symbol)"]    = q_canonical
                    dynamic_aliases[f"@{qw_lower}"]             = q_canonical
                    # e.g. "pepe the frog" already covered by q_lower itself
                if q_lower not in dynamic_aliases:
                    dynamic_aliases[q_lower] = q_canonical

                name_aliases = {**static_aliases, **dynamic_aliases}
                name_norm = name_aliases.get(name_norm.lower(), name_norm)
                # UID: case-insensitive damit Duplikate zusammengeführt werden
                act_uid = f"actor_{_fingerprint(name_norm.lower())}"
                # Platform-Namen normalisieren – nur echte Platforms
                plat_normalise = {
                    "internet meme": "Web", "meme": "Web", "webcomic": "Web",
                    "image meme": "Web", "web": "Web", "online": "Web",
                    "subreddit": "Reddit", "forum": "Web",
                    "tweet": "Twitter", "microblog": "Twitter",
                    "website": "Web", "organisation": "Web",
                    "organization": "Web", "movement": "Web",
                    "protest movement": "Web", "unknown": "Web",
                    "person": "Web", "account": "Web",
                }
                # Ungültige Platform-Namen (generisch/sinnlos) → URL-Plattform nutzen
                invalid_plat_names = {
                    "web","website","organisation","organization","movement",
                    "protest movement","unknown","person","account","symbol",
                    "character","film","book","article","post","none","n/a",""
                }
                llm_plat = actor_data.get("platform", "").strip()
                llm_plat_norm = plat_normalise.get(llm_plat.lower(), llm_plat)
                if llm_plat_norm.lower() in invalid_plat_names:
                    plat_n = plat_name  # Fallback auf URL-Plattform
                elif '|' in llm_plat_norm or len(llm_plat_norm) > 40:
                    plat_n = plat_name  # Zu lang oder mehrere Plattformen → URL-Plattform
                else:
                    plat_n = llm_plat_norm or plat_name

                # Typ bereinigen – kein '|' erlaubt
                raw_type = actor_data.get("type", "Unknown")
                act_type = raw_type.split("|")[0].strip() if "|" in raw_type else raw_type
                role_raw = actor_data.get("role", "AMPLIFICATION")
                role     = role_raw[0] if isinstance(role_raw, list) else role_raw
                act_stance = actor_data.get("stance", "neutral")

                # Datum validieren – nur ISO-Format, kein Datum in der Zukunft
                actor_date = actor_data.get("date") or date
                if actor_date:
                    try:
                        from datetime import date as dt_date
                        d_str = str(actor_date).strip()[:10]
                        # Muss ISO-Format sein: YYYY-MM-DD oder YYYY
                        if not re.match(r'^\d{4}(-\d{2}-\d{2})?$', d_str):
                            actor_date = date  # Fallback: kein "April 01," etc.
                        else:
                            parsed = dt_date.fromisoformat(d_str if '-' in d_str else f"{d_str}-01-01")
                            if parsed.year > dt_date.today().year:
                                actor_date = date  # Kein Zukunftsdatum
                    except Exception:
                        actor_date = date

                self.db.upsert_actor(
                    uid=act_uid, name=name_norm, platform_name=plat_n,
                    actor_type=act_type,
                    first_seen=actor_date,
                    confidence=actor_data.get("confidence", 0.5),
                    inv_uid=inv.uid, stance=act_stance,
                    source_url=page["url"],
                    is_author=act_type == "Person"  # Nur echte Personen sind Autoren
                )

                # Platform-Knoten: LLM-Platform-Name + URL-Platform abgleichen
                # Wenn LLM "Twitter" sagt aber Quelle Reddit ist → URL-Platform nutzen
                url_plat = _platform_from_url(page["url"])
                if plat_n != url_plat and url_plat != "Web":
                    # Konflikt: LLM-Platform stimmt nicht mit Quell-URL überein
                    # Beide anlegen: Actor liegt auf Quell-Platform,
                    # LLM-Platform nur wenn sie eine echte bekannte Platform ist
                    actor_plat_uid = self.db.upsert_platform(url_plat, page["url"], inv.uid)
                else:
                    actor_plat_uid = self.db.upsert_platform(plat_n, page["url"], inv.uid)
                self.db.actor_links_to_platform(act_uid, actor_plat_uid)

                self.db.actor_spreads_narrative(
                    actor_uid=act_uid, narrative_uid=n_uid,
                    role=role, stance=act_stance,
                    confidence=actor_data.get("confidence", 0.5),
                    date=actor_data.get("date") or date,
                    url=page["url"]
                )
                if role == "ORIGIN":
                    self.db.actor_authored_article(act_uid, a_uid)
                    _c_key2 = f"{act_uid}{a_uid}origin"
                    c_uid = f"comment_{_fingerprint(_c_key2)}"
                    self.db.upsert_comment(
                        uid=c_uid, article_uid=a_uid, actor_uid=act_uid,
                        date=actor_data.get("date") or date,
                        text=actor_data.get("context","")[:200],
                        score=0, inv_uid=inv.uid, stance=act_stance
                    )
                else:
                    # Kommentator/Amplifier → NF_Comment Knoten → Artikel
                    # Das erzeugt den Cluster um den Artikel in der Visualisierung
                    # Include context snippet to prevent UID collision for multiple comments per actor+article
                    _c_key2 = f"{act_uid}{a_uid}{actor_data.get('context','')[:80]}"
                    c_uid = f"comment_{_fingerprint(_c_key2)}"
                    self.db.upsert_comment(
                        uid=c_uid, article_uid=a_uid, actor_uid=act_uid,
                        date=actor_data.get("date") or date,
                        text=actor_data.get("context","")[:200],
                        score=0, inv_uid=inv.uid, stance=act_stance
                    )

                # Zusätzlich: Links im Text → andere Platforms
                for link in page.get("links", [])[:5]:
                    linked_plat = _platform_from_url(link)
                    if linked_plat != plat_name and linked_plat != plat_n:
                        lp_uid = self.db.upsert_platform(linked_plat, link, inv.uid)
                        self.db.actor_links_to_platform(act_uid, lp_uid)
                        self.db.platform_spreads_narrative(lp_uid, n_uid)

                found_actors[act_uid] = name_norm
                actor_count_this_page += 1
                inv.findings    += 1
                inv.actors_found = len(found_actors)

            self._add_activity(
                f"  📍 {actor_count_this_page + len(page.get('platform_actors', []))} Akteure [{art_stance}] · {page['url'][:40]}"
            )

        return all_pages, seen_page_urls, found_actors, inv_origin_set

    def _make_collect_page(self, inv: Investigation, all_pages: list,
                            seen_page_urls: set, narrative_keywords: list):
        """Factory: gibt (collect_page, page_contains_narrative) zurück.
        Factory: returns (collect_page, page_contains_narrative) closures.
        Verwendet SKIP_DOMAINS/SKIP_PATHS Klassenkonstanten.
        Uses SKIP_DOMAINS/SKIP_PATHS class constants."""
        skip_domains = self.SKIP_DOMAINS
        skip_paths   = self.SKIP_PATHS

        def is_relevant_url(url: str, base_domain: str) -> bool:
            url_lower = url.lower()
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                path   = parsed.path.lower()
            except Exception:
                domain, path = "", url_lower
            if domain in skip_domains:
                return False
            if any(path.startswith(p) or p in path for p in skip_paths):
                return False
            if 'wikipedia.org' in domain and domain.split('.')[0] not in ('en', 'www', ''):
                return False
            return True

        def page_contains_narrative(text: str) -> bool:
            return bool(text and len(text) >= 50 and
                        any(kw in text[:5000].lower() for kw in narrative_keywords))

        def collect_page(item, depth_remaining, base_domain="", is_direct=False):
            url = item.get("url", "")
            if not url or url in seen_page_urls:
                return
            skip_ext = ('.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg',
                        '.js', '.css', '.woff', '.pdf', '.mp4', '.zip')
            if any(url.lower().split('?')[0].endswith(e) for e in skip_ext):
                return
            if base_domain and not is_relevant_url(url, base_domain):
                return
            forum_domains = ('reddit.com', '4chan.org', '4plebs.org', 'telegram',
                             't.me', 'twitter.com', 'x.com', 'facebook.com',
                             'discord.com', 'tumblr.com', 'quora.com',
                             'youtube.com', 'youtu.be')
            is_forum = any(f in url.lower() for f in forum_domains)
            seen_page_urls.add(url)
            page = self.searcher.fetch_page(url, max_chars=10000,
                                             follow_links=depth_remaining > 1,
                                             link_depth=depth_remaining)
            if not page["text"]:
                return
            if not is_direct and not is_forum and base_domain:
                if not page_contains_narrative(page["text"]):
                    self.log(f"  ↷ Irrelevant: {url[:60]}")
                    return
            page["date_hint"] = item.get("date_hint", "")
            page["title"]     = item.get("title", "")
            snippet = item.get("content", "").strip()
            if snippet and snippet not in page["text"]:
                page["text"] = snippet + "\n\n" + page["text"]
            all_pages.append(page)
            if depth_remaining > 1 and len(all_pages) < inv.search_breadth * 4:
                try:
                    from urllib.parse import urlparse
                    cur_domain = urlparse(url).netloc.lower()
                except Exception:
                    cur_domain = base_domain
                for sub in page.get("pages", []) + [{"url": l} for l in page.get("links", [])]:
                    sub_url = sub.get("url", "")
                    if sub_url and is_relevant_url(sub_url, cur_domain):
                        collect_page({"url": sub_url, "title": sub.get("title", "")},
                                     depth_remaining - 1, cur_domain, is_direct=True)
        return collect_page, page_contains_narrative

    def _blind_spot_check(self, inv: Investigation, all_pages: list,
                           seen_page_urls: set, found_actors: dict, n_uid: str,
                           inv_origin_set: bool = False):
        """Phase 3: SearXNG Blind-Flecken-Check – paginiert bis 20 neue URLs.
        Phase 3: SearXNG blind-spot check – paginates up to 20 new URLs.
        inv_origin_set: True wenn der Origin bereits in Phase 2 bestimmt wurde.
        inv_origin_set: True when the origin was already determined in phase 2.
        Führt Origin-Detection auch für neue Seiten aus, falls noch nicht gesetzt.
        Also runs origin detection for newly discovered pages if not yet set.
        """
        q           = inv.query
        narrative_keywords = [w.lower() for w in inv.query.split() if len(w) > 3]
        collect_page, page_contains_narrative = self._make_collect_page(
            inv, all_pages, seen_page_urls, narrative_keywords
        )
        self.log(f"  SearXNG blind-spot check…")
        target_new   = 20
        found_new    = 0
        page_no      = 2
        max_pages    = 10

        while found_new < target_new and page_no <= max_pages:
            results = self.searcher.search_web(q, num_results=10, page=page_no)
            if not results:
                break
            page_new = 0
            for item in results:
                url = item.get("url", "")
                if not url or url in seen_page_urls:
                    continue
                # NICHT vorher zu seen_page_urls hinzufügen – collect_page macht das selbst
                pages_before = len(all_pages)
                collect_page({
                    "url":     url,
                    "title":   item.get("title", ""),
                    "content": item.get("content", "").strip(),
                }, inv.search_depth, "", is_direct=True)

                # Neu geladene Seiten sofort LLM-analysieren
                for new_page in all_pages[pages_before:]:
                    url_lower2 = new_page["url"].lower()
                    is_forum2  = any(f in url_lower2 for f in
                                     ('reddit.com','4chan.org','twitter.com','x.com',
                                      'facebook.com','discord.com','tumblr.com'))
                    if not is_forum2 and not page_contains_narrative(new_page.get("text","")):
                        continue

                    # Origin-Detection für Blind-Spot-Seiten, falls noch nicht gesetzt
                    # Origin detection for blind-spot pages if not yet determined
                    if not inv_origin_set and new_page.get("text") and len(new_page["text"]) > 500:
                        np_lower = new_page["url"].lower()
                        skip_for_origin = any(s in np_lower for s in [
                            "youtube.", "reddit.", "twitter.", "x.com", "facebook.",
                            "4chan.", "telegram", "instagram.", "tiktok.",
                        ])
                        is_reference = (not skip_for_origin) and (
                            "wikipedia.org" in np_lower or
                            "knowyourmeme.com" in np_lower or
                            any(m in np_lower for m in ["bbc.", "nytimes.", "theguardian.",
                                                         "reuters.", "apnews."])
                        )
                        if is_reference:
                            origin_raw = self.llm.query(
                                "Du bist ein neutraler Dokumentations-Assistent. "
                                "Lies den Text und beantworte: Wer hat das beschriebene Narrativ/Konzept/Werk "
                                "ERSTMALS erschaffen oder in die Welt gebracht? "
                                "Nenne NUR den Namen und das Jahr (aus dem Text). "
                                "Keine Bewertung. Wenn nicht eindeutig erkennbar: name = null. "
                                'Antworte NUR mit JSON: {"name":"Name oder null","date":"YYYY oder YYYY-MM-DD oder null"}',
                                f"Narrativ: {inv.query}\n\nText:\n{new_page['text'][:4000]}",
                                max_tokens=100
                            )
                            origin_data = self.llm._parse_json(origin_raw)
                            if origin_data and origin_data.get("name"):
                                oname = origin_data["name"]
                                odate = str(origin_data.get("date") or "")
                                if odate and len(odate) == 4:
                                    odate = f"{odate}-01-01"
                                o_uid = f"actor_{_fingerprint(oname.lower())}"
                                self.db.upsert_actor(
                                    uid=o_uid, name=oname,
                                    platform_name=_platform_from_url(new_page["url"]),
                                    actor_type="Person", first_seen=odate,
                                    confidence=0.95, inv_uid=inv.uid,
                                    stance="neutral", is_author=True,
                                    source_url=new_page["url"]
                                )
                                if self.db.get_driver():
                                    with self.db.get_driver().session() as s_orig:
                                        s_orig.run(
                                            "MATCH (a:NF_Actor {uid:$uid}) SET a.role='ORIGIN'",
                                            uid=o_uid
                                        )
                                inv_origin_set = True
                                found_actors[o_uid] = oname
                                self.log(f"  🎯 Origin [BF]: {oname} ({odate}) via {_platform_from_url(new_page['url'])}")
                    self.log(f"  LLM [BF]: {new_page['url'][:60]}")
                    plat_name2  = _platform_from_url(new_page["url"])
                    p_uid2      = self.db.upsert_platform(plat_name2, new_page["url"], inv.uid)
                    a_uid2      = f"art_{_fingerprint(new_page['url'])}"
                    date2       = new_page.get("date_hint") or (new_page.get("dates") or [""])[0]
                    extracted2  = self.llm.extract_actors_and_events(
                        new_page["text"], inv.query, source_url=new_page["url"]
                    )
                    stance2     = self.llm.document_positioning(new_page["text"], inv.query)
                    self.db.upsert_article(
                        uid=a_uid2, title=new_page.get("title","")[:200],
                        url=new_page["url"], platform_uid=p_uid2,
                        date=(date2 or "")[:10], inv_uid=inv.uid,
                        stance=stance2.get("stance","neutral"),
                        stance_confidence=stance2.get("confidence",0.5)
                    )
                    self.db.platform_spreads_narrative(p_uid2, n_uid)
                    self.log(f"  🔗 PUBLISHED_ON     {new_page.get('title','')[:30]:30} → {plat_name2}")
                    for actor_data in extracted2.get("actors", []):
                        name = actor_data.get("name","").strip()
                        if not name or name.lower() in {
                            "","unknown","deleted","anonymous","user","users",
                            "u/deleted","automoderator","origin"
                        }:
                            continue
                        act_uid2 = f"actor_{_fingerprint(name.lower())}"
                        self.db.upsert_actor(
                            uid=act_uid2, name=name,
                            platform_name=plat_name2,
                            actor_type=actor_data.get("type","Account"),
                            first_seen=date2,
                            confidence=actor_data.get("confidence",0.5),
                            inv_uid=inv.uid, stance="neutral",
                            source_url=new_page["url"]
                        )
                        c_uid2 = f"comment_{_fingerprint(act_uid2+a_uid2)}"
                        self.db.upsert_comment(
                            uid=c_uid2, article_uid=a_uid2, actor_uid=act_uid2,
                            date=date2, text="", score=0,
                            inv_uid=inv.uid, stance="neutral"
                        )
                        found_actors[act_uid2] = name

                found_new += 1
                page_new  += 1
            self.log(f"  SearXNG Seite {page_no}: {page_new} neue URLs")
            if page_new == 0:
                break
            page_no += 1

        self.log(f"  Blind-spot check: {found_new} new URLs, {len(found_actors)} actors total")


    def _deep_scan_url(self, inv: Investigation, url: str, actor_uid: str) -> None:
        """Deep Scan: runs a single URL through the full fetch + LLM pipeline
        and writes results into the existing investigation."""
        self.log(f"🔍 Deep Scan: {url[:80]}")
        try:
            # Mirror _investigate: set comment_pages so _fetch_reddit uses correct limit
            self.searcher.comment_pages = inv.comment_pages
            n_uid = f"narr_{_fingerprint(inv.query)}"
            self.db.upsert_narrative(uid=n_uid, text=inv.query, inv_uid=inv.uid)
            url_list = [{"url": url, "title": "", "content": "", "engine": "", "score": 0}]
            _, _, found_actors, _ = self._load_and_process_pages(inv, url_list, n_uid)
            if found_actors:
                all_pages_tmp = []
                seen_tmp      = set()
                kws           = [w.lower() for w in inv.query.split() if len(w) > 3]
                collect_page, _ = self._make_collect_page(inv, all_pages_tmp, seen_tmp, kws)
                collect_page({"url": url, "title": "", "content": ""}, inv.search_depth, "", True)
                self._fingerprint_actors(inv, found_actors, all_pages_tmp or [{"url": url, "text": ""}])
            self.log(f"✅ Deep Scan complete: {len(found_actors)} actors found")
        except Exception as e:
            self.log(f"  Deep Scan error: {e}", "WARNING")

    def _fingerprint_actors(self, inv: Investigation, found_actors: dict, all_pages: list):
        """Phase 4: Fingerprinting und Koordinationserkennung aller gefundenen Akteure.
        Phase 4: Fingerprinting and coordination detection for all discovered actors."""
        if len(found_actors) < 2:
            return

        self.log(f"  Fingerprinting {len(found_actors)} actors…")

        # Akteur-spezifische Texte sammeln (Kommentare/Posts des jeweiligen Akteurs)
        actor_texts: dict[str, list] = {}
        for page in all_pages:
            for pa in page.get("platform_actors", []):
                name = pa.get("name","").strip()
                text = pa.get("text","").strip()
                if name and text:
                    uid = f"actor_{_fingerprint(name.lower())}"
                    actor_texts.setdefault(uid, []).append(text[:500])

        non_media_types = {"Person", "Account", "Bot"}
        coord_candidates = dict(found_actors)
        if self.db.get_driver():
            try:
                with self.db.get_driver().session() as s:
                    for uid in list(coord_candidates.keys()):
                        rec = s.run("MATCH (a:NF_Actor {uid:$uid}) RETURN a.type AS t",
                                    uid=uid).single()
                        if rec and rec["t"] not in non_media_types:
                            del coord_candidates[uid]
            except Exception:
                pass

        actor_uids = list(coord_candidates.keys())[:5]
        fingerprints = {}
        for act_uid in actor_uids:
            # Eigene Texte des Akteurs – fallback auf Seiten-Texte
            texts = actor_texts.get(act_uid, [])
            if not texts:
                texts = [p["text"][:300] for p in all_pages if p.get("text")][:3]
            if not texts:
                continue
            fp_data = self.llm.analyze_author_fingerprint(texts[:5])
            if fp_data:
                fingerprints[act_uid] = fp_data
                nd = fp_data.get("narrative_direction", "?")[:30]
                self._add_activity(f"  🖊️ {found_actors[act_uid][:20]} – {nd}")

        for i in range(len(actor_uids)):
            for j in range(i+1, len(actor_uids)):
                uid_a, uid_b = actor_uids[i], actor_uids[j]
                if uid_a not in fingerprints or uid_b not in fingerprints:
                    continue
                match_r = self.llm.match_author_fingerprints(
                    fingerprints[uid_a], fingerprints[uid_b]
                )
                score = match_r.get("score", 0.0)
                if score >= 0.6:
                    self.db.link_actors(uid_a, uid_b,
                                        evidence=match_r.get("evidence", ""),
                                        confidence=score)
                    inv.notes.append(
                        f"⚠️ {score:.0%}: {found_actors.get(uid_a,'?')[:20]} ↔ {found_actors.get(uid_b,'?')[:20]}"
                    )
                    self._add_activity(
                        f"  🔗 Koordination ({score:.0%}): {found_actors.get(uid_a,'?')[:15]} ↔ {found_actors.get(uid_b,'?')[:15]}"
                    )


    def _orphan_check(self, inv: Investigation, n_uid: str) -> None:
        """Phase 5: Orphan-Check via get_graph_data – identisch zum FF-Debugger.
        Phase 5: Orphan check via get_graph_data – identical to FF debugger."""
        self.log(f"  Orphan-Check…")
        orphans_found = 0
        try:
            # Exakt dieselben Daten wie der FF-Debugger via /api/graph
            data     = self.db.get_graph_data(mode="actor", inv_uid=inv.uid)
            nodes    = {n["id"]: n for n in data.get("nodes", [])}
            edges    = data.get("edges", [])

            # Gleiche Filter wie loadGraph JS
            platform_ids = {nid for nid, n in nodes.items()
                            if n.get("group") == "NF_Platform"}
            connected = set()
            edges_by_uid = {}
            for e in edges:
                lbl = e.get("label", "")
                for uid in (e["from"], e["to"]):
                    edges_by_uid.setdefault(uid, []).append(lbl)
                if lbl == "LINKS_TO":
                    continue
                connected.add(e["from"])
                connected.add(e["to"])

            self.log(f"  Orphan-Check: {len(nodes)} nodes, {len(edges)} edges")

            for uid, n in sorted(nodes.items(), key=lambda x: x[1].get("group","")):
                if uid not in connected:
                    diag_edges = edges_by_uid.get(uid, [])
                    diag = ", ".join(
                        f"{e}(filtered)" if e in ("LINKS_TO", "SPREADS") else f"{e}(present)"
                        for e in diag_edges
                    ) or "no edges at all"

                    # Extra: check for duplicate names and article mismatch in DB
                    extra = []
                    if n.get("group") == "NF_Actor":
                        try:
                            label = str(n.get("label",""))
                            with self.db.get_driver().session() as s2:
                                # Duplicate name check
                                dups = s2.run(
                                    "MATCH (a:NF_Actor) WHERE toLower(a.name)=toLower($name) "
                                    "RETURN a.uid AS uid, a.inv_uid AS inv",
                                    name=label
                                ).data()
                                if len(dups) > 1:
                                    extra.append(f"DUPLICATE name in DB: {len(dups)}x "
                                                 f"({', '.join(d['uid'][:12] for d in dups)})")

                                # Article mismatch check
                                url = str(n.get("full",{}).get("url","") or n.get("url",""))
                                if url:
                                    expected_auid = f"art_{_fingerprint(url)}"
                                    art = s2.run(
                                        "MATCH (a:NF_Article {uid:$uid}) RETURN a.url AS url",
                                        uid=expected_auid
                                    ).single()
                                    if art:
                                        extra.append(f"article EXISTS (uid={expected_auid[:16]})")
                                    else:
                                        extra.append(f"article MISSING (expected uid={expected_auid[:16]})")

                                    # Check if any comment links this actor to an article
                                    c_check = s2.run(
                                        "MATCH (c:NF_Comment)-[:COMMENTED_BY]->(a:NF_Actor {uid:$uid}) "
                                        "RETURN count(c) AS cnt",
                                        uid=uid
                                    ).single()
                                    if c_check and c_check["cnt"] > 0:
                                        extra.append(f"HAS {c_check['cnt']} comment(s) in DB but not in graph!")
                        except Exception as ex:
                            extra.append(f"check-error: {ex}")

                    extra_str = " | " + "; ".join(extra) if extra else ""
                    self.log(
                        f"  ⚠️  Orphan {n.get('group','?'):12} "
                        f"'{str(n.get('label',''))[:28]:28}' "
                        f"plat={str(n.get('full',{}).get('platform','') or '')[:14]:14} "
                        f"url={str(n.get('full',{}).get('url','') or '')[:50]}  "
                        f"[{diag}]{extra_str}",
                        "WARNING"
                    )
                    orphans_found += 1

        except Exception as e:
            self.log(f"  Orphan-Check error: {e}", "WARNING")

        if orphans_found == 0:
            self.log(f"  ✅ Orphan-Check: no orphans found")
        else:
            self.log(f"  ⚠️  Orphan-Check: {orphans_found} orphans found")

    def _write_dossier(self, inv: Investigation,
                       actors: dict, narrative_uid: str):
        """Schreibt ein Markdown-Dossier für die Untersuchung.
        Writes a Markdown dossier for the investigation."""
        stats = self.db.get_stats()
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M")

        multi_narrative = self.db.search_actors_by_narrative_count(min_count=2)

        lines = [
            f"# Forensik-Dossier: {inv.query[:80]}",
            f"",
            f"**Erstellt:** {ts}  ",
            f"**Untersuchungs-ID:** {inv.uid}  ",
            f"**Tiefe:** {inv.depth}/{inv.max_depth}  ",
            f"",
            f"## Gefundene Akteure ({len(actors)})",
        ]

        for a_uid, a_name in actors.items():
            lines.append(f"- **{a_name}**")

        if multi_narrative:
            lines += [
                f"",
                f"## ⚠️ Wiederkehrende Akteure (forensisch relevant)",
                f"Akteure die bei mehreren Narrativen auftauchen:",
            ]
            for a in multi_narrative[:10]:
                lines.append(
                    f"- **{a['name']}** ({a['platform']}) – {a['cnt']} Narrative"
                )

        if inv.notes:
            lines += [f"", f"## Koordinationshinweise"]
            lines += [f"- {n}" for n in inv.notes[:10]]

        lines += [
            f"",
            f"## Datenbank-Stand",
            f"- Akteure: {stats.get('actors', 0)}",
            f"- Narrative: {stats.get('narratives', 0)}",
            f"- Artikel: {stats.get('articles', 0)}",
            f"- Plattformen: {stats.get('platforms', 0)}",
        ]

        # ──────────────────────────────────────────────────────────────────────────
        # NEU: Struktureller Vergleich mit anderen Untersuchungen
        # ──────────────────────────────────────────────────────────────────────────
        if len(self.investigations) > 1:
            lines += ["", "## 🔍 Struktureller Vergleich"]
            lines += ["(Vergleich der Akteurs- und Positionsmuster – unabhängig vom Inhalt)"]
            
            for other in self.investigations:
                if other.uid == inv.uid:
                    continue
                
                try:
                    with self.db.get_driver().session() as s:
                        # Verteilung der Akteurs-Typen für dieses Narrativ
                        types_this = s.run("""
                            MATCH (a:NF_Actor)-[:SPREADS]->(:NF_Narrative {inv_uid: $uid})
                            RETURN a.type AS type, count(DISTINCT a) AS count
                        """, uid=inv.uid).data()
                        
                        # Verteilung der Akteurs-Typen für das andere Narrativ
                        types_other = s.run("""
                            MATCH (a:NF_Actor)-[:SPREADS]->(:NF_Narrative {inv_uid: $uid})
                            RETURN a.type AS type, count(DISTINCT a) AS count
                        """, uid=other.uid).data()
                        
                        # Haben beide institutionelle Akteure?
                        institution_types = ("Organisation", "Institution", "Medium", "Account")
                        has_institution_this = any(t["type"] in institution_types for t in types_this)
                        has_institution_other = any(t["type"] in institution_types for t in types_other)
                        
                        # Positionierungs-Verteilung
                        stance_this = s.run("""
                            MATCH (a:NF_Actor)-[r:SPREADS]->(:NF_Narrative {inv_uid: $uid})
                            WHERE r.stance IS NOT NULL
                            RETURN r.stance AS stance, count(DISTINCT a) AS count
                        """, uid=inv.uid).data()
                        
                        stance_other = s.run("""
                            MATCH (a:NF_Actor)-[r:SPREADS]->(:NF_Narrative {inv_uid: $uid})
                            WHERE r.stance IS NOT NULL
                            RETURN r.stance AS stance, count(DISTINCT a) AS count
                        """, uid=other.uid).data()
                        
                        if has_institution_this and has_institution_other:
                            lines.append(f"")
                            lines.append(f"**{other.query[:60]}**")
                            lines.append(f"- Enthält ebenfalls institutionelle Akteure")
                            lines.append(f"- Strukturell vergleichbares Muster")
                            
                            # Wenn beide ähnliche Positions-Verteilung haben
                            stances_this = {s["stance"]: s["count"] for s in stance_this}
                            stances_other = {s["stance"]: s["count"] for s in stance_other}
                            
                            if stances_this.get("opposing", 0) > 0 and stances_other.get("opposing", 0) > 0:
                                lines.append(f"- Beide weisen ablehnende Positionierungen auf ({stances_this.get('opposing', 0)} vs. {stances_other.get('opposing', 0)} Akteure)")
                except Exception as e:
                    self.log(f"Structural comparison failed: {e}", "WARNING")
        
        # ──────────────────────────────────────────────────────────────────────────
        # NEU: Neutraler Hinweis zur Dokumentation
        # ──────────────────────────────────────────────────────────────────────────
        lines += ["", "## 📋 Hinweis zur Dokumentation"]
        lines += ["Die in diesem Dossier dokumentierten Positionierungen (unterstützend/ablehnend/neutral)"]
        lines += ["basieren auf den Aussagen der Akteure im untersuchten Korpus."]
        lines += ["Das System bewertet nicht die Richtigkeit dieser Positionierungen."]
        lines += ["Es dokumentiert lediglich, welche Akteure sich wie positioniert haben."]
        lines += [""]
        lines += ["*LYRA Narrative Forensics – Dokumentation, nicht Bewertung.*"]

        slug  = re.sub(r'[^\w]', '_', inv.query[:50]).lower()
        path  = NARRATIVE_DIR / f"{slug}_{inv.uid[:8]}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        self.log(f"Dossier: {path.name}", "SUCCESS")
        self._add_activity(f"📄 Dossier: {path.name}")

    def get_status(self) -> dict:
        with self._lock:
            return {
                "running":         self.running,
                "investigations":  [
                    {k: v for k, v in inv.__dict__.items() if k != "notes"}
                    for inv in self.investigations
                ],
                "activity":        self.activity[:20],
                "db_stats":        self.db.get_stats(),
            }


# ── Web-Server ────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>LYRA Narrative Forensics</title>
<script src="/static/jquery.min.js"></script>
<script src="/static/vis-network.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Segoe UI',sans-serif; background:#0a0a14; color:#ccd; display:flex;
       flex-direction:column; height:100vh; overflow:hidden; }
header { background:rgba(20,20,40,0.97); padding:10px 18px;
         border-bottom:1px solid #223; flex-shrink:0;
         display:flex; align-items:center; justify-content:space-between; }
h1 { font-size:1.1em; color:#4af; }
.subtitle { font-size:0.75em; color:#556; }
.main { display:flex; flex:1; min-height:0; }
.sidebar { width:340px; min-width:200px; background:rgba(20,20,40,0.97);
           border-right:1px solid #223; display:flex; flex-direction:column;
           overflow:hidden; }
.sidebar-inner { padding:12px; overflow-y:auto; flex:1; min-height:0;
                 display:flex; flex-direction:column; gap:10px; }
.graph-area { flex:1; position:relative; min-height:0; }
#network { width:100%; height:100%; min-height:400px; background:#06060f; position:absolute; top:0; left:0; bottom:0; right:0; }
.section-title { font-size:0.7em; font-weight:bold; color:#556;
                 text-transform:uppercase; letter-spacing:0.5px;
                 border-bottom:1px solid #223; padding-bottom:3px; margin-bottom:6px; }
.query-box { display:flex; gap:6px; }
.query-box input { flex:1; background:#111; border:1px solid #334; border-radius:4px;
                   padding:6px 8px; color:#ccd; font-size:0.8em; }
.query-box input:focus { outline:none; border-color:#4488ff; }
.btn { background:#1a2a4a; border:1px solid #445; border-radius:4px;
       color:#8af; padding:5px 10px; cursor:pointer; font-size:0.78em;
       white-space:nowrap; }
.btn:hover { background:#2a3a5a; border-color:#4488ff; }
.btn.danger { border-color:#664; color:#c86; }
.inv-card { background:rgba(68,136,255,0.08); border:1px solid #2a4a8a;
            border-radius:5px; padding:6px 8px; font-size:0.75em; cursor:pointer; }
.inv-card.active { border-color:#44aaff; background:rgba(68,136,255,0.15); }
.inv-card.done   { border-color:#2a5a2a; background:rgba(68,255,68,0.05); }
.inv-badge { font-size:0.8em; font-weight:bold; color:#4488ff; }
.inv-text  { color:#ccd; margin-top:3px; line-height:1.3; }
.act-item  { font-size:0.72em; color:#668; padding:2px 0; border-bottom:1px solid #1a1a2e; }
.status-bar { border-top:1px solid #223; padding:6px 12px; font-size:0.72em;
              color:#668; flex-shrink:0; }
.stats-grid { display:grid; grid-template-columns:1fr 1fr; gap:4px; font-size:0.75em; }
.stat-box   { background:#111; border:1px solid #223; border-radius:4px;
              padding:5px 8px; text-align:center; }
.stat-val   { font-size:1.3em; color:#4af; font-weight:bold; }
.stat-lbl   { font-size:0.75em; color:#556; }
.resizer    { width:5px; background:rgba(100,100,150,0.3); cursor:col-resize; }
.resizer:hover { background:#4488ff; }
.mode-toggle { display:flex; gap:6px; align-items:center; font-size:0.75em; }
.mode-btn { padding:3px 10px; border-radius:3px; cursor:pointer; border:1px solid #334;
            background:#111; color:#668; }
.mode-btn.active { background:#1a2a4a; border-color:#4488ff; color:#4af; }
.hint { font-size:0.7em; color:#445; font-style:italic; padding:4px 0; }
</style>
</head>
<body>
<header>
  <div>
    <h1>🕵️ LYRA Narrative Forensics</h1>
    <div class="subtitle">Forensische Analyse von Informationskriegs-Narrativen · Forensic Analysis of Information-Warfare Narratives · v__VERSION__</div>
  </div>
  <div class="mode-toggle">
    <button class="mode-btn active" id="btnActorMode" onclick="setMode('actor')">👤 Actor Network</button>
    <button class="mode-btn" id="btnNarrMode" onclick="setMode('narrative')">💬 Narrative Network</button>
    <button class="mode-btn" id="btnTimeline" onclick="setMode('timeline')">📈 Timeline</button>
    <button class="btn" onclick="refreshGraph()">🔃</button>
  </div>
</header>
<div class="main">
  <div class="sidebar" id="sidebarEl">
    <div class="sidebar-inner">

      <!-- Neue Untersuchung / New Investigation -->
      <div>
        <div class="section-title">🔬 New Investigation</div>
        <div class="query-box">
          <input type="text" id="queryInput"
                 placeholder="Enter narrative or question…"
                 onkeypress="if(event.key==='Enter') addInvestigation()">
          <button class="btn" onclick="addInvestigation()">▶</button>
        </div>
        <div class="hint">Forensic questions: "Who first spread X?" · "Which actors are behind narrative Y?"</div>
        <div style="margin-top:8px;background:#0d0d1a;border:1px solid #223;border-radius:5px;padding:8px;">
          <div style="font-size:0.68em;color:#556;font-weight:bold;margin-bottom:6px;text-transform:uppercase;">⚙ Search Settings</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.72em;">
            <div>
              <div style="color:#778;margin-bottom:2px;">Breadth: <span id="lblBreadth" style="color:#4af;">20</span> pages</div>
              <input type="range" id="sliderBreadth" min="5" max="100" step="5" value="20"
                     style="width:100%;accent-color:#4488ff;" oninput="updateSettings()">
            </div>
            <div>
              <div style="color:#778;margin-bottom:2px;">Depth: <span id="lblDepth" style="color:#4af;">1</span></div>
              <input type="range" id="sliderDepth" min="1" max="5" step="1" value="1"
                     style="width:100%;accent-color:#4488ff;" oninput="updateSettings()">
            </div>
            <div style="grid-column:1/-1;">
              <div style="color:#778;margin-bottom:2px;">Comment depth: <span id="lblComments" style="color:#4af;">2</span> pages</div>
              <input type="range" id="sliderComments" min="1" max="100" step="1" value="2"
                     style="width:100%;accent-color:#44cc88;" oninput="updateSettings()">
            </div>
          </div>
          <div style="font-size:0.67em;color:#445;margin-top:4px;">
            Depth 1 = found page only · 2 = + linked pages · 3+ = link depth incl. user profiles · Comment depth = pages per thread
          </div>
        </div>
      </div>

      <!-- Artefakt-Import / Artifact Import -->
      <div>
        <div class="section-title">📥 Import Artifact</div>
        <textarea id="artifactText" rows="3"
                  style="width:100%;background:#111;border:1px solid #334;
                         border-radius:4px;padding:6px;color:#ccd;font-size:0.75em;resize:vertical;"
                  placeholder="Paste text (screenshot content, quote, HTML excerpt)…"></textarea>
        <div style="display:flex;gap:4px;margin-top:4px;">
          <input type="text" id="artifactUrl" placeholder="Source URL (optional)"
                 style="flex:1;background:#111;border:1px solid #334;border-radius:4px;
                        padding:4px 6px;color:#ccd;font-size:0.73em;">
          <input type="text" id="artifactDate" placeholder="YYYY-MM-DD"
                 style="width:90px;background:#111;border:1px solid #334;border-radius:4px;
                        padding:4px 6px;color:#ccd;font-size:0.73em;">
          <input type="text" id="artifactPlatform" placeholder="Platform"
                 style="width:80px;background:#111;border:1px solid #334;border-radius:4px;
                        padding:4px 6px;color:#ccd;font-size:0.73em;">
        </div>
        <button class="btn" style="margin-top:4px;width:100%;" onclick="importArtifact()">
          📥 Import
        </button>
      </div>

      <!-- Statistiken / Statistics -->
      <div>
        <div class="section-title">📊 Database</div>
        <div class="stats-grid">
          <div class="stat-box"><div class="stat-val" id="statActors">0</div>
               <div class="stat-lbl">Actors</div></div>
          <div class="stat-box"><div class="stat-val" id="statNarratives">0</div>
               <div class="stat-lbl">Narratives</div></div>
          <div class="stat-box"><div class="stat-val" id="statArticles">0</div>
               <div class="stat-lbl">Articles</div></div>
          <div class="stat-box"><div class="stat-val" id="statPlatforms">0</div>
               <div class="stat-lbl">Platforms</div></div>
        </div>
        <div style="font-size:0.65em;color:#334;margin-top:4px;padding:4px;background:#0d0d1a;border-radius:3px;">
          <span style="color:#00aaff;">★</span>Narrative
          <span style="color:#44ff88;">◆</span>Platform
          <span style="color:#ffaa44;">■</span>Article
          <span style="color:#ffcc00;">●</span>Origin author
          <span style="color:#4488ff;">●</span>Editor
          <span style="color:#ff4444;">●</span>Commenter &nbsp;|&nbsp;
          Border: <span style="color:#44ff44;">green</span>=supporting
          <span style="color:#ff4444;">red</span>=opposing
          <span style="color:#888;">grey</span>=neutral/documenting
        </div>
      </div>

      <!-- Wiederkehrende Akteure / Recurring Actors -->
      <div>
        <div class="section-title">⚠️ Recurring Actors</div>
        <div id="multiActorList" style="font-size:0.75em;color:#556;">
          No recurring actors found yet.
        </div>
      </div>

      <!-- Laufende Untersuchungen / Investigations -->
      <div>
        <div class="section-title">🕵️ Investigations</div>
        <div id="invList" style="display:flex;flex-direction:column;gap:4px;">
          <div style="color:#445;font-size:0.75em;">No investigations</div>
        </div>
        <div style="display:flex;gap:4px;margin-top:6px;">
          <button class="btn" onclick="toggleAgent()" id="btnToggle" style="flex:1;">▶ Start</button>
          <button class="btn" onclick="loadStatus()">🔃</button>
        </div>
        <div style="display:flex;gap:4px;margin-top:4px;">
          <button class="btn" onclick="exportInvestigations()" style="flex:1;" title="Export all investigations + Neo4j data">💾 Export</button>
          <button class="btn" onclick="document.getElementById('importFile').click()" style="flex:1;" title="Import archived investigation">📂 Import</button>
          <button class="btn" onclick="runOrphanCheck()" title="Run orphan check on current investigation">🔍 Orphans</button>
          <button class="btn danger" onclick="cleanupAll()" title="Delete all NF_ nodes from Neo4j">🧹</button>
          <input type="file" id="importFile" accept=".json" style="display:none;" onchange="importInvestigations(this)">
        </div>
      </div>

      <!-- Letzte Aktivität / Recent Activity -->
      <div>
        <div class="section-title">⚡ Activity</div>
        <div id="actList" style="max-height:140px;overflow-y:auto;"></div>
      </div>

    </div>
    <div id="nodeDetail" style="display:none;border-top:1px solid #223;padding:8px 12px;flex-shrink:0;">
      <div style="font-size:0.68em;font-weight:bold;color:#556;text-transform:uppercase;
                  letter-spacing:0.5px;margin-bottom:5px;">📍 Node Detail
        <span style="float:right;cursor:pointer;color:#446;font-size:1.1em;"
              onclick="document.getElementById('nodeDetail').style.display='none'">✕</span>
      </div>
      <div id="nodeDetailContent" style="font-size:0.72em;color:#aab;line-height:1.6;
           max-height:160px;overflow-y:auto;"></div>
    </div>
    <div class="status-bar">
      <span id="statusMsg">🟡 Initialising…</span>
    </div>
  </div>

  <div class="resizer" id="resizerEl"></div>

  <div class="graph-area">
    <div id="network"></div>
    <div id="timelinePanel" style="display:none;width:100%;height:100%;
         background:#06060f;overflow:auto;padding:20px;">
      <div id="timelineTitle" style="color:#4af;font-size:0.9em;margin-bottom:12px;">
        📈 Timeline – select an investigation
      </div>
      <canvas id="timelineCanvas" style="width:100%;max-width:1200px;display:block;"></canvas>
      <div id="timelineEvents" style="margin-top:20px;font-size:0.75em;color:#668;"></div>
    </div>
  </div>
</div>

<script>
// ── Globals ──────────────────────────────────────────────────────────────────
var network = null;
var graphMode = 'actor';
var agentRunning = false;

var searchSettings = { breadth: 20, depth: 1, comment_pages: 2 };
var selectedInvUid = null;
var userHasZoomed  = false;
var originUid      = null;  // Global – wird in loadGraph gesetzt

function updateSettings() {
    searchSettings.breadth        = parseInt(document.getElementById('sliderBreadth').value);
    searchSettings.depth          = parseInt(document.getElementById('sliderDepth').value);
    searchSettings.comment_pages  = parseInt(document.getElementById('sliderComments').value);
    document.getElementById('lblBreadth').textContent  = searchSettings.breadth;
    document.getElementById('lblDepth').textContent    = searchSettings.depth;
    document.getElementById('lblComments').textContent = searchSettings.comment_pages;
}

window.onload = function() {
    initNetwork();
    loadStatus();
    loadGraph();
    
    // Nur während der Agent läuft (aktiv sucht) den Graph refreshen
    setInterval(function() {
        if (agentRunning) {
            fetch('/api/status')
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    var hasActive = (data.investigations || []).some(function(inv) {
                        return inv.status === 'active';
                    });
                    if (hasActive) {
                        if (graphMode === 'timeline') loadTimeline();
                        else loadGraph();
                    } else {
                        // Scan fertig – finaler Status-Update
                        loadStatus();
                        loadGraph();
                    }
                })
                .catch(function() {});
        }
    }, 15000);
    
    initResizer();
};

function initNetwork() {
    var container = document.getElementById('network');
    var data = { nodes: new vis.DataSet([]), edges: new vis.DataSet([]) };
    var options = {
        physics: {
            enabled: true,
            stabilization: { iterations: 500, fit: false },
            barnesHut: {
                gravitationalConstant: -8000,
                centralGravity:        0.0,
                springLength:          120,
                springConstant:        0.08,
                damping:               0.25,
                avoidOverlap:          1.0
            }
        },
        layout: {
            improvedLayout: false,   // Deaktiviert – versagt bei >300 Knoten
        },
        nodes: { shape: 'dot', size: 14, font: { color: '#ccd', size: 11 } },
        edges: {
            arrows: 'to',
            font:   { color: '#55667788', size: 9, vadjust: -8 },
            smooth: { type: 'curvedCW', roundness: 0.2 },
            color:  { color: '#44aaff55', highlight: '#4af' },
        },
        interaction: { hover: true, tooltipDelay: 150, zoomView: true }
    };
    network = new vis.Network(container, data, options);

    // Zoom/Pan-Events setzen Flag – kein Auto-Fit mehr danach
    network.on('zoom',      function() { userHasZoomed = true; });
    network.on('dragStart', function(p) { if (p.nodes.length === 0) userHasZoomed = true; });

    network.on('dragEnd', function(p) {
        if (p.nodes.length > 0) {
            p.nodes.forEach(function(nodeId) {
                network.startSimulation();
            });
        }
    });

    network.on('doubleClick', function(params) {
        if (params.nodes.length > 0) {
            loadActorProfile(params.nodes[0]);
        }
    });

    network.on('click', function(params) {
        if (params.nodes.length === 0) return;
        var nodeId = params.nodes[0];
        fetch('/api/node/' + encodeURIComponent(nodeId))
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var panel   = document.getElementById('nodeDetail');
                var content = document.getElementById('nodeDetailContent');
                // Interne Felder ausblenden
                var skip = ['uid', 'inv_uid', 'updated', 'full'];
                // Priorität: URL zuerst zeigen
                var orderedKeys = ['url', 'archive_url', 'name', 'title', 'platform',
                                   'type', 'stance', 'stance_confidence', 'confidence',
                                   'first_seen', 'date', 'notes', 'sources'];
                var allKeys = orderedKeys.concat(Object.keys(d).filter(function(k) {
                    return orderedKeys.indexOf(k) < 0;
                }));
                var html = '';
                allKeys.forEach(function(k) {
                    if (d[k] === null || d[k] === undefined || d[k] === '' || skip.indexOf(k) >= 0) return;

                    // sources: strukturierte Liste {date, role, url}
                    if (k === 'sources' && Array.isArray(d[k])) {
                        if (d[k].length === 0) return;
                        var sHtml = d[k].map(function(s) {
                            if (!s || !s.url) return '';
                            var domain = '';
                            try { domain = new URL(s.url).hostname; } catch(e) { domain = s.url.substring(0,30); }
                            return '<div style="font-size:0.85em;margin:1px 0;">' +
                                   '<span style="color:#556;">' + escHtml(s.date||'?') + ' · ' + escHtml(s.role||'') + '</span> ' +
                                   '<a href="' + escHtml(s.url) + '" target="_blank" style="color:#4af;">' + escHtml(domain) + '</a></div>';
                        }).filter(Boolean).join('');
                        if (!sHtml) return;
                        html += '<div style="margin-bottom:4px;display:flex;gap:6px;">' +
                                '<span style="color:#668;min-width:90px;flex-shrink:0;font-size:0.85em;">sources</span>' +
                                '<span>' + sHtml + '</span></div>';
                        return;
                    }

                    var val = String(d[k]);
                    var display = '';
                    // URL-Erkennung: ^https sichert dass kein führender Text
                    var mdMatch  = val.match(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/);
                    var urlMatch = val.match(/^https?:\/\/[^\s,\]"<]+/);
                    var href = null, lbl = null;
                    if (mdMatch) {
                        href = mdMatch[2]; lbl = mdMatch[1];
                    } else if (urlMatch) {
                        href = urlMatch[0];
                        try { lbl = new URL(href).hostname; } catch(e) { lbl = href.substring(0,40); }
                    }
                    if (href) {
                        display = '<a href="' + escHtml(href) + '" target="_blank" ' +
                                  'style="color:#4af;text-decoration:underline;">' +
                                  escHtml(lbl || href) + '</a>';
                    } else {
                        if (val.length > 150) val = val.substring(0,150) + '…';
                        display = escHtml(val);
                    }
                    var kColor = (k === 'url' || k === 'archive_url') ? '#4af' :
                                 k === 'stance' ? (val==='pro'?'#44ff44':val==='contra'?'#ff4444':'#888') :
                                 '#668';
                    html += '<div style="margin-bottom:4px;display:flex;gap:6px;">' +
                            '<span style="color:' + kColor + ';min-width:90px;flex-shrink:0;font-size:0.85em;">' +
                            escHtml(k) + '</span>' +
                            '<span style="color:#ccd;">' + display + '</span></div>';
                });
                content.innerHTML = html || '<span style="color:#445;">Keine Details</span>';

                if (d.group === 'NF_Actor' && d.url) {
                    var b = document.createElement('button');
                    b.id = 'deepScanBtn';
                    b.textContent = '🔍 Deep Scan';
                    b.setAttribute('data-actor-uid', nodeId);
                    b.setAttribute('data-url', d.url);
                    b.style.cssText = 'margin-top:8px;width:100%;padding:5px 8px;background:#112233;' +
                        'border:1px solid #4488ff;border-radius:4px;color:#4af;font-size:0.75em;cursor:pointer;display:block;';
                    b.onclick = function() { startDeepScan(b.getAttribute('data-actor-uid'), b.getAttribute('data-url')); };
                    content.appendChild(b);
                }

                if (d.group !== 'NF_Narrative') {
                    var bd = document.createElement('button');
                    bd.textContent = '🗑 Delete Node';
                    bd.setAttribute('data-node-id', nodeId);
                    bd.style.cssText = 'margin-top:4px;width:100%;padding:5px 8px;background:#220000;' +
                        'border:1px solid #ff4444;border-radius:4px;color:#ff6666;font-size:0.75em;cursor:pointer;display:block;';
                    bd.onclick = function() { deleteNode(bd.getAttribute('data-node-id')); };
                    content.appendChild(bd);
                }

                panel.style.display = 'block';
            });
    });

    network.on('doubleClick', function(params) {
        if (params.nodes.length === 0) return;
        var nodeId = params.nodes[0];
        document.getElementById('statusMsg').textContent = '🔍 Lade Verbindungen...';
        fetch('/api/node-expand/' + encodeURIComponent(nodeId))
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.nodes || data.nodes.length === 0) return;

                var colorMap = {
                    NF_Actor:     function(n) {
                        if (n.id === originUid) return {background:'#ffcc00',border:'#ff8800'};
                        return n.is_author
                            ? {background:'#ffcc00',border:'#ff8800'}
                            : {background:'#440011',border:'#ff4444'};
                    },
                    NF_Narrative: function() { return {background:'#003388',border:'#0088ff'}; },
                    NF_Platform:  function() { return {background:'#004422',border:'#44ff88'}; },
                    NF_Article:   function() { return {background:'#553300',border:'#ffaa44'}; },
                    NF_Comment:   function() { return {background:'transparent',border:'transparent'}; },
                };
                var shapeMap = {
                    NF_Narrative:'star', NF_Platform:'diamond',
                    NF_Article:'square', NF_Actor:'dot', NF_Comment:'dot'
                };

                var ns2 = new vis.DataSet(data.nodes.map(function(n) {
                    var colFn = colorMap[n.group] || function(){ return {background:'#888',border:'#aaa'}; };
                    var col   = colFn(n);
                    var isC   = n.group === 'NF_Comment';
                    return {
                        id:    n.id,
                        label: isC ? '' : n.label,
                        title: n.title,
                        color: col,
                        shape: shapeMap[n.group] || 'dot',
                        size:  n.id === nodeId ? 30 : (isC ? 2 : 14),
                        font:  isC ? {color:'transparent',size:1} : {color:'#ccd',size:10},
                        borderWidth: n.id === nodeId ? 4 : 1,
                    };
                }));

                var lenMap = {COMMENTED_BY:50,PART_OF:80,AUTHORED_BY:80,
                              PUBLISHED_ON:200,LINKS_TO:180,SPREADS:350,COORDINATES_WITH:120};
                var es2 = new vis.DataSet(data.edges.map(function(e) {
                    return { from:e.from, to:e.to, title:e.label,
                             length: lenMap[e.label]||150,
                             arrows:'to', color:{color:'#44aaff66'},
                             font:{size:0} };
                }));

                network.setData({ nodes: ns2, edges: es2 });
                network.setOptions({ physics:{
                    enabled:true, solver:'barnesHut',
                    barnesHut:{gravitationalConstant:-3000,springLength:100,springConstant:0.05,damping:0.3,avoidOverlap:1},
                    stabilization:{iterations:300,fit:false}
                }});
                network.once('stabilized', function() {
                    network.setOptions({physics:{barnesHut:{gravitationalConstant:-500,springConstant:0.01,damping:0.9},stabilization:false}});
                    network.fit();
                });
                document.getElementById('statusMsg').textContent =
                    '🔍 ' + (data.nodes.length-1) + ' connections · Double-click to return to graph';
            });
    });
}

function loadGraph() {
    var url = '/api/graph?mode=' + graphMode;
    if (selectedInvUid) url += '&inv_uid=' + encodeURIComponent(selectedInvUid);
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (!network) return;
            var nd        = data.nodes || [];
            var ed        = data.edges || [];
            originUid = data.origin_uid;

            if (nd.length === 0) {
                // Graph leeren – wichtig nach Cleanup/Delete
                network.setData({ nodes: new vis.DataSet([]), edges: new vis.DataSet([]) });
                userHasZoomed = false;
                selectedInvUid = null;
                document.getElementById('statusMsg').textContent =
                    '🟡 No data – start an investigation';
                return;
            }

            var linkCount = {};
            ed.forEach(function(e) {
                linkCount[e.from] = (linkCount[e.from]||0) + 1;
                linkCount[e.to]   = (linkCount[e.to]||0)   + 1;
            });

            var vNodes = nd.map(function(n) {
                var isOrigin    = (n.id === originUid);
                var isNarrative = (n.group === 'NF_Narrative');
                var isPlatform  = (n.group === 'NF_Platform');
                var isArticle   = (n.group === 'NF_Article');
                var isActor     = (n.group === 'NF_Actor');
                var linkCnt     = linkCount[n.id] || 0;

                // Hierarchie-Level: bestimmt den Ring im radialen Layout
                // 0=Origin(Zentrum) 1=Narrativ 2=Platform 3=Artikel 4=Actor
                var level = isOrigin    ? 0
                          : isNarrative ? 1
                          : isPlatform  ? 2
                          : isArticle   ? 3
                          : (n.group === 'NF_Comment') ? 4
                          : 5;  // NF_Actor auf Ring 5 – ausserhalb von Comments

                var sz = isOrigin   ? 50
                       : isNarrative? 30
                       : isPlatform ? 22 + Math.min(linkCnt * 2, 14)
                       : isArticle  ? 14 + Math.min(linkCnt * 2, 10)
                       :              10 + Math.min(linkCnt * 2, 14);

                var shape = isOrigin    ? 'star'
                          : isNarrative ? 'star'
                          : isPlatform  ? 'diamond'
                          : isArticle   ? 'square'
                          : 'dot';

                var positionColors = {supporting:'#00ff88', opposing:'#ff3300', neutral:'#445566'};
                var borderCol      = positionColors[n.stance] || '#445566';
                var borderWidth    = (n.stance==='supporting'||n.stance==='opposing') ? 4 : 1;

                var col;
                if (isOrigin) {
                    col = {background:'#ffcc00', border:'#ff8800',
                           highlight:{background:'#ffdd44', border:'#ffaa00'}};
                } else if (isNarrative) {
                    col = {background:'#003388', border:'#0088ff',
                           highlight:{background:'#004499', border:'#44aaff'}};
                } else if (isPlatform) {
                    col = {background:'#004422', border:'#44ff88',
                           highlight:{background:'#006633', border:'#88ffaa'}};
                } else if (isArticle) {
                    // Artikel: Hintergrund zeigt Stance als Tint
                    var artBg = n.stance==='supporting' ? '#1a4422'
                              : n.stance==='opposing'   ? '#441111'
                              : '#553300';
                    col = {background: artBg, border: borderCol,
                           highlight:{background: artBg, border: borderCol}};
                } else if (n.group === 'NF_Actor') {
                    // Erstautor = goldgelb, Editor = blau, Kommentator = rot
                    var actBg = n.is_author ? '#ffcc00'
                              : n.is_editor ? '#003388'
                              : '#440011';
                    var actBorder = n.is_author ? '#ff8800'
                                  : n.is_editor ? '#4488ff'
                                  : borderCol;
                    col = {background: actBg, border: actBorder,
                           highlight:{background: actBg, border:'#ffffff'}};
                } else {
                    col = {background:'#440011', border: borderCol,
                           highlight:{background:'#660022', border:'#fff'}};
                }

                return {
                    id:          n.id,
                    label:       n.label,
                    title:       n.title + (n.stance && n.stance !== 'neutral' ? " ⚡ " + n.stance : ''),
                    color:       col,
                    size:        sz,
                    shape:       shape,
                    level:       level,
                    borderWidth: isOrigin ? 4 : (n.stance==='supporting'||n.stance==='opposing') ? 4 : isPlatform ? 2 : 1,
                    mass:        isOrigin ? 8 : isNarrative ? 2 : isPlatform ? 3 : 1,
                    font: isOrigin
                        ? {size:13, bold:true, color:'#ffcc00'}
                        : isNarrative ? {size:12, bold:true, color:'#44aaff'}
                        : isPlatform  ? {size:11, bold:true, color:'#88ffaa'}
                        : isArticle   ? {size:10, color:'#ffaa44'}
                        : {size:10, color: n.is_author ? '#000' : '#ffaaaa'},
                    fixed: isOrigin ? {x:true,y:true} : {x:false,y:false},
                    x:     isOrigin ? 0 : undefined,
                    y:     isOrigin ? 0 : undefined,
                    _full: n.full || {},
                };
            });

            // LINKS_TO (Actor→Platform) filtered – no orphans, cleaner clusters
            // SPREADS from Actors filtered – only Platform→Narrative remains visible
            var platformIds = new Set(nd.filter(function(n){
                return n.group === 'NF_Platform';
            }).map(function(n){ return n.id; }));

            var vEdges = ed.filter(function(e) {
                if (e.label === 'LINKS_TO') return false;
                if (e.label === 'SPREADS' && !platformIds.has(e.from)) return false;
                return true;
            }).map(function(e) {
                var lbl = e.label || '';
                // Kanten-Länge definiert die Cluster-Nähe:
                // Kurze Kante = enger Cluster, Lange Kante = weiter Abstand
                var lengthMap = {
                    'COMMENTED_BY':     60,   // Person dicht am Kommentar-Knoten
                    'PART_OF':          80,   // Kommentar dicht am Artikel
                    'AUTHORED_BY':      100,  // Autor etwas weiter vom Artikel
                    'PUBLISHED_ON':     160,  // Artikel zur Platform
                    'LINKS_TO':         200,  // Person zur Platform (Querverbindung)
                    'SPREADS':          280,  // Actor zum Narrativ
                    'COORDINATES_WITH': 120,  // Actor zu Actor (Koordination)
                };
                var edgeLength = lengthMap[lbl] || 150;

                var edgeStyle = {
                    'PUBLISHED_ON':    { color:'#44ff8855', from: e.to,   to: e.from },
                    'AUTHORED_BY':     { color:'#ffaa4466', from: e.to,   to: e.from },
                    'SPREADS':         { color:'#ff444488', from: e.from, to: e.to   },
                    'LINKS_TO':        { color:'#4488ff44', from: e.from, to: e.to   },
                    'COORDINATES_WITH':{ color:'#ff88ff88', from: e.from, to: e.to   },
                    'PART_OF':         { color:'#aaaaff55', from: e.to,   to: e.from },
                    'COMMENTED_BY':    { color:'#aa44ff55', from: e.to,   to: e.from },
                };
                var st = edgeStyle[lbl] || { color:'#44aaff33', from: e.from, to: e.to };
                return {
                    from:   st.from,
                    to:     st.to,
                    label:  '',
                    title:  lbl,
                    length: edgeLength,
                    arrows: { to: { enabled: true, scaleFactor: 0.5 } },
                    color:  { color: st.color, highlight: '#ffffff88' },
                    smooth: { type: 'curvedCW', roundness: 0.15 },
                    width:  lbl === 'COORDINATES_WITH' ? 2 : 1,
                    dashes: lbl === 'COORDINATES_WITH',
                };
            });

            // Physics mit barnesHut – respektiert edge.length für Cluster-Abstände
            // Kurze Kanten = enger Cluster, Lange Kanten = weiter Abstand
            var lenMap = {
                'COMMENTED_BY':     50,   // Actor direkt am Comment-Knoten
                'PART_OF':          70,   // Comment direkt am Artikel
                'AUTHORED_BY':      70,   // Autor am Artikel
                'PUBLISHED_ON':     350,  // Artikel zur Platform – grösser = weniger Überlapp
                'LINKS_TO':         300,  // Actor zur Platform
                'SPREADS':          700,  // Platform zum Narrativ – weit aussen, Abstossung
                'COORDINATES_WITH': 150,
            };

            // Comment-Knoten unsichtbar machen
            var vNodesMapped = vNodes.map(function(n) {
                if (n.group === 'NF_Comment') {
                    n.size  = 2;
                    n.label = '';
                    n.color = {background:'transparent',border:'transparent'};
                    n.font  = {color:'transparent',size:1};
                }
                return n;
            });
            var vEdgesMapped = vEdges.map(function(e) {
                return Object.assign({}, e, { length: lenMap[e.title] || 200, physics: true });
            });

            // Erstes Laden oder Untersuchungswechsel: volle Stabilisierung
            var networkNodes = network.body.data.nodes;
            var networkEdges = network.body.data.edges;
            var isFirstLoad  = (networkNodes.length === 0);

            if (isFirstLoad) {
                // Erster Aufbau: setData + starke Physics
                var nsVis = new vis.DataSet(vNodesMapped);
                var esVis = new vis.DataSet(vEdgesMapped);
                network.setData({ nodes: nsVis, edges: esVis });
                network.setOptions({
                    physics: {
                        enabled: true, solver: 'barnesHut',
                        barnesHut: {
                            gravitationalConstant: -8000,  // Stärker – Cluster stossen sich ab
                            centralGravity:        0.05,
                            springLength:          100,
                            springConstant:        0.04,
                            damping:               0.3,
                            avoidOverlap:          1.5,    // Höher – kein Überlapp
                        },
                        stabilization: { iterations: 1500, fit: false },
                    },
                });
                network.once('stabilized', function() {
                    network.setOptions({ physics: {
                        barnesHut: {
                            gravitationalConstant: -2000,  // Bleibt stark genug für Trennung
                            springConstant:        0.01,
                            damping:               0.9,
                            avoidOverlap:          1.5,
                        },
                        stabilization: false,
                    }});
                    if (!userHasZoomed) network.fit();
                });
            } else {
                // Refresh: nur neue/geänderte Knoten hinzufügen – kein Gewusel
                var existingNodeIds = new Set(networkNodes.getIds());
                var existingEdgeIds = new Set(networkEdges.getIds());

                var toAdd    = [], toUpdate = [];
                vNodesMapped.forEach(function(n) {
                    if (!existingNodeIds.has(n.id)) toAdd.push(n);
                    else toUpdate.push(n);  // Eigenschaften aktualisieren (Farbe, Stance etc.)
                });
                if (toAdd.length)    networkNodes.add(toAdd);
                if (toUpdate.length) networkNodes.update(toUpdate);

                vEdgesMapped.forEach(function(e) {
                    if (!existingEdgeIds.has(e.id || (e.from+'_'+e.to+'_'+e.title))) {
                        try { networkEdges.add(e); } catch(ex) {}
                    }
                });

                // Nur kurz nachstabilisieren wenn neue Knoten dazugekommen sind
                if (toAdd.length > 0) {
                    network.setOptions({ physics: {
                        barnesHut: { gravitationalConstant:-1000, springConstant:0.03, damping:0.6 },
                        stabilization: { iterations: 100, fit: false },
                    }});
                    network.once('stabilized', function() {
                        network.setOptions({ physics: {
                            barnesHut: { gravitationalConstant:-500, springConstant:0.01, damping:0.9 },
                            stabilization: false,
                        }});
                    });
                }
            }
            document.getElementById('statusMsg').textContent =
                '🟢 ' + vNodes.length + ' nodes · ' + vEdges.length + ' edges' +
                (originUid ? ' · 🔴 Origin: ' + (nd.find(function(n){return n.id===originUid;})||{label:''}).label : '');
        })
        .catch(function(e) {
            document.getElementById('statusMsg').textContent = '🔴 Graph load error: ' + e;
        });
}

function setMode(mode) {
    graphMode = mode;
    document.getElementById('btnActorMode').classList.toggle('active', mode === 'actor');
    document.getElementById('btnNarrMode').classList.toggle('active', mode === 'narrative');
    document.getElementById('btnTimeline').classList.toggle('active', mode === 'timeline');
    var net = document.getElementById('network');
    var tl  = document.getElementById('timelinePanel');
    if (mode === 'timeline') {
        net.style.display = 'none';
        tl.style.display  = 'block';
        loadTimeline();
    } else {
        net.style.display = 'block';
        tl.style.display  = 'none';
        loadGraph();
    }
}

function loadTimeline() {
    fetch('/api/narratives')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var narrs = data.narratives || [];
            if (narrs.length === 0) {
                document.getElementById('timelineTitle').textContent =
                    '📈 No data – start an investigation first';
                return;
            }
            var seed = narrs[0];
            if (selectedInvUid) {
                var found = narrs.find(function(n) { return n.inv_uid === selectedInvUid; });
                if (found) seed = found;
            }
            document.getElementById('timelineTitle').textContent =
                '📈 ' + seed.text.substring(0,80);
            fetch('/api/timeline/' + encodeURIComponent(seed.inv_uid))
                .then(function(r) { return r.json(); })
                .then(function(events) { renderTimeline(events, seed); });
        });
}

function renderTimeline(events, seed) {
    var canvas = document.getElementById('timelineCanvas');
    var evDiv  = document.getElementById('timelineEvents');

    if (!events || events.length === 0) {
        document.getElementById('timelineTitle').textContent =
            '📈 ' + seed.text.substring(0,80) + ' – no events yet';
        evDiv.innerHTML = '<div style="color:#446;padding:20px;">No time data available. Start the agent to collect data.</div>';
        return;
    }

    var dated = events.filter(function(e) { return e.date && e.date.length >= 4; });
    dated.sort(function(a,b) { return a.date < b.date ? -1 : 1; });

    var today = new Date().toISOString().substring(0,10);

    var minDate = new Date(dated[0].date.substring(0,10) || today);
    var maxDate = new Date(today);
    var totalMs = maxDate - minDate || 1;

    var W = canvas.parentElement.clientWidth - 40;
    var H = 220;
    canvas.width  = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    var PAD_L = 60, PAD_R = 20, PAD_T = 30, PAD_B = 50;
    var chartW = W - PAD_L - PAD_R;
    var chartH = H - PAD_T - PAD_B;

    ctx.fillStyle = '#06060f';
    ctx.fillRect(0, 0, W, H);

    ctx.strokeStyle = '#1a1a2e';
    ctx.lineWidth   = 1;
    for (var gi = 0; gi <= 4; gi++) {
        var gy = PAD_T + (chartH / 4) * gi;
        ctx.beginPath(); ctx.moveTo(PAD_L, gy); ctx.lineTo(PAD_L + chartW, gy); ctx.stroke();
    }

    ctx.strokeStyle = '#334';
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(PAD_L, PAD_T + chartH); ctx.lineTo(PAD_L + chartW, PAD_T + chartH); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(PAD_L, PAD_T); ctx.lineTo(PAD_L, PAD_T + chartH); ctx.stroke();

    ctx.fillStyle = '#446';
    ctx.font      = '11px monospace';
    ctx.textAlign = 'center';
    var minYear = minDate.getFullYear();
    var maxYear = maxDate.getFullYear();
    for (var yr = minYear; yr <= maxYear; yr++) {
        var xPos = PAD_L + ((new Date(yr + '-01-01') - minDate) / totalMs) * chartW;
        if (xPos >= PAD_L && xPos <= PAD_L + chartW) {
            ctx.fillText(yr, xPos, H - 10);
            ctx.strokeStyle = '#223';
            ctx.beginPath(); ctx.moveTo(xPos, PAD_T + chartH); ctx.lineTo(xPos, PAD_T + chartH + 5); ctx.stroke();
        }
    }

    var platColors = {
        'Twitter':    '#1da1f2', 'Reddit':  '#ff4500',
        '4chan':      '#117743', 'Telegram':'#0088cc',
        'Facebook':   '#1877f2', 'YouTube': '#ff0000',
        'Wayback':    '#888888', 'unknown': '#4488ff',
    };

    var byMonth = {};
    dated.forEach(function(e) {
        var mon = e.date.substring(0,7);
        byMonth[mon] = (byMonth[mon] || 0) + 1;
    });
    var months = Object.keys(byMonth).sort();
    var maxCount = Math.max.apply(null, months.map(function(m) { return byMonth[m]; })) || 1;

    if (months.length > 1) {
        ctx.beginPath();
        ctx.strokeStyle = '#4488ff';
        ctx.lineWidth   = 2.5;
        ctx.shadowColor = '#4488ff';
        ctx.shadowBlur  = 8;
        var first = true;
        months.forEach(function(mon) {
            var d    = new Date(mon + '-15');
            var x    = PAD_L + ((d - minDate) / totalMs) * chartW;
            var y    = PAD_T + chartH - (byMonth[mon] / maxCount) * chartH * 0.85;
            if (first) { ctx.moveTo(x, y); first = false; }
            else        { ctx.lineTo(x, y); }
        });
        ctx.stroke();
        ctx.shadowBlur = 0;

        ctx.beginPath();
        first = true;
        months.forEach(function(mon) {
            var d = new Date(mon + '-15');
            var x = PAD_L + ((d - minDate) / totalMs) * chartW;
            var y = PAD_T + chartH - (byMonth[mon] / maxCount) * chartH * 0.85;
            if (first) { ctx.moveTo(x, PAD_T + chartH); ctx.lineTo(x, y); first = false; }
            else        { ctx.lineTo(x, y); }
        });
        var lastMon = months[months.length - 1];
        var lx = PAD_L + ((new Date(lastMon + '-15') - minDate) / totalMs) * chartW;
        ctx.lineTo(lx, PAD_T + chartH);
        ctx.closePath();
        ctx.fillStyle = 'rgba(68,136,255,0.08)';
        ctx.fill();
    }

    dated.forEach(function(e) {
        var d   = new Date(e.date.substring(0,10));
        var x   = PAD_L + ((d - minDate) / totalMs) * chartW;
        var col = platColors[e.platform] || platColors['unknown'];
        ctx.beginPath();
        ctx.arc(x, PAD_T + chartH - 10, 5, 0, Math.PI * 2);
        ctx.fillStyle   = col;
        ctx.strokeStyle = '#fff';
        ctx.lineWidth   = 1;
        ctx.fill();
        ctx.stroke();
    });

    if (dated.length > 0) {
        var first_ev = dated[0];
        var fx = PAD_L + ((new Date(first_ev.date.substring(0,10)) - minDate) / totalMs) * chartW;
        ctx.beginPath();
        ctx.arc(fx, PAD_T + chartH - 10, 10, 0, Math.PI * 2);
        ctx.fillStyle   = '#ff2200';
        ctx.strokeStyle = '#ffaa00';
        ctx.lineWidth   = 2;
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = '#fff';
        ctx.font      = 'bold 10px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('⬤', fx, PAD_T + chartH - 6);
        ctx.fillStyle = '#ff6644';
        ctx.font      = '10px monospace';
        ctx.fillText('ORIGIN', fx, PAD_T + 14);
        ctx.strokeStyle = '#ff2200';
        ctx.setLineDash([3,3]);
        ctx.beginPath(); ctx.moveTo(fx, PAD_T + 18); ctx.lineTo(fx, PAD_T + chartH - 20); ctx.stroke();
        ctx.setLineDash([]);
    }

    var legX = PAD_L + 10;
    var legY = PAD_T + 10;
    ctx.font = '10px monospace';
    ctx.textAlign = 'left';
    var usedPlats = [...new Set(dated.map(function(e){return e.platform;}))].slice(0,6);
    usedPlats.forEach(function(plat, i) {
        ctx.fillStyle = platColors[plat] || platColors['unknown'];
        ctx.fillRect(legX + i * 80, legY, 10, 10);
        ctx.fillStyle = '#668';
        ctx.fillText(plat || 'unknown', legX + i * 80 + 13, legY + 9);
    });

    var html = '<table style="width:100%;border-collapse:collapse;">';
    html += '<tr style="color:#446;border-bottom:1px solid #1a1a2e;">';
    html += '<th style="text-align:left;padding:3px 8px;">Date</th>';
    html += '<th style="text-align:left;padding:3px 8px;">Actor</th>';
    html += '<th style="text-align:left;padding:3px 8px;">Platform</th>';
    html += '<th style="text-align:left;padding:3px 8px;">Type</th>';
    html += '<th style="text-align:left;padding:3px 8px;">Source</th>';
    html += '</tr>';
    dated.forEach(function(e) {
        var col = platColors[e.platform] || '#668';
        var domain = '';
        try { domain = new URL(e.url||'').hostname; } catch(ex) { domain = (e.url||'').substring(0,30); }
        var suspicious = e.suspicious_date;
        var rowStyle = suspicious ? 'border-bottom:1px solid #111;font-size:0.9em;opacity:0.55;' : 'border-bottom:1px solid #111;font-size:0.9em;';
        var dateCell = escHtml(e.date||'') + (suspicious ? ' <span title="Date before 2000 – possibly incorrectly extracted" style="color:#ff8800;">⚠</span>' : '');
        html += '<tr style="' + rowStyle + '">';
        html += '<td style="padding:3px 8px;color:#aab;">' + dateCell + '</td>';
        html += '<td style="padding:3px 8px;color:#ccd;">' + escHtml((e.actor||'').substring(0,30)) + '</td>';
        html += '<td style="padding:3px 8px;"><span style="color:' + col + ';">' + escHtml(e.platform||'') + '</span></td>';
        html += '<td style="padding:3px 8px;color:#668;">' + escHtml(e.type||'') + '</td>';
        html += '<td style="padding:3px 8px;">';
        if (e.url) html += '<a href="' + escHtml(e.url) + '" target="_blank" style="color:#446;">' + escHtml(domain) + '</a>';
        html += '</td></tr>';
    });
    html += '</table>';
    evDiv.innerHTML = html;
}

function deleteNode(nodeId) {
    if (!confirm('Delete this node and all nodes below it?')) return;
    fetch('/api/node/' + encodeURIComponent(nodeId) + '/delete', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            document.getElementById('nodeDetail').style.display = 'none';
            document.getElementById('statusMsg').textContent = '🗑 Deleted ' + d.deleted + ' node(s)';
            loadGraph();
        })
        .catch(function() { document.getElementById('statusMsg').textContent = '❌ Delete failed'; });
}

function startDeepScan(actorUid, url) {
    if (!selectedInvUid) { alert('No active investigation selected.'); return; }
    var btn = document.getElementById('deepScanBtn');
    if (btn) { btn.textContent = '⏳ Scanning…'; btn.disabled = true; }
    fetch('/api/deep_scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inv_uid: selectedInvUid, actor_uid: actorUid, url: url })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        if (d.error) { if (btn) { btn.textContent = '❌ ' + d.error; btn.disabled = false; } return; }
        var jobId = d.job_id;
        document.getElementById('statusMsg').textContent = '🔍 Deep Scan running…';
        var poll = setInterval(function() {
            fetch('/api/deep_scan/' + encodeURIComponent(jobId))
                .then(function(r) { return r.json(); })
                .then(function(s) {
                    if (s.status === 'done' || s.status === 'error') {
                        clearInterval(poll);
                        if (btn) { btn.textContent = s.status === 'done' ? '✅ Done' : '❌ Error'; btn.disabled = false; }
                        document.getElementById('statusMsg').textContent =
                            s.status === 'done' ? '✅ Deep Scan complete' : '❌ Deep Scan error: ' + (s.error||'');
                        loadGraph();
                    }
                });
        }, 3000);
    })
    .catch(function() { if (btn) { btn.textContent = '❌ Error'; btn.disabled = false; } });
}

function runOrphanCheck() {
    if (!selectedInvUid) { alert('No active investigation selected.'); return; }
    document.getElementById('statusMsg').textContent = '🔍 Running orphan check…';
    fetch('/api/orphan_check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inv_uid: selectedInvUid })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        document.getElementById('statusMsg').textContent =
            d.orphans === 0 ? '✅ No orphans found' : '⚠️ ' + d.orphans + ' orphans found – see log';
        loadStatus();
    })
    .catch(function() {
        document.getElementById('statusMsg').textContent = '❌ Orphan check failed';
    });
}

function refreshGraph() { loadGraph(); }

function showNodeInfo(nodeId) {
    fetch('/api/node/' + encodeURIComponent(nodeId))
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var info = d.name || d.text || nodeId;
            document.getElementById('statusMsg').textContent =
                '📍 ' + d.type + ': ' + info.substring(0,60);
        });
}

function loadActorProfile(nodeId) {
    fetch('/api/actor/' + encodeURIComponent(nodeId))
        .then(function(r) { return r.json(); })
        .then(function(d) {
            var names  = (d.narratives||[]).map(function(n){return n.summary||n.text||'';});
            var msg    = d.name + ' | ' + (d.platform||'?') + ' | ' + names.length + ' narratives';
            document.getElementById('statusMsg').textContent = '👤 ' + msg;
        });
}

function addInvestigation() {
    var q = document.getElementById('queryInput').value.trim();
    if (!q) return;
    fetch('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            query:         q,
            breadth:       searchSettings.breadth,
            depth:         searchSettings.depth,
            comment_pages: searchSettings.comment_pages
        })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        document.getElementById('queryInput').value = '';
        document.getElementById('statusMsg').textContent =
            '🔬 Investigation started: ' + q.substring(0,40);
        // Agent automatisch starten wenn er nicht läuft / Auto-start agent if not running
        if (!agentRunning) {
            fetch('/api/agent/start', { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function() { loadStatus(); });
        } else {
            loadStatus();
        }
    });
}

function importArtifact() {
    var text     = document.getElementById('artifactText').value.trim();
    var url      = document.getElementById('artifactUrl').value.trim();
    var date     = document.getElementById('artifactDate').value.trim();
    var platform = document.getElementById('artifactPlatform').value.trim() || 'unknown';
    if (!text) { alert('Please enter text'); return; }
    fetch('/api/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text, url: url, date: date, platform: platform })
    })
    .then(function(r) { return r.json(); })
    .then(function(d) {
        document.getElementById('artifactText').value = '';
        document.getElementById('statusMsg').textContent =
            '📥 Imported: ' + (d.narrative_uid || '');
        loadStatus(); loadGraph();
    });
}

function cleanupAll() {
    if (!confirm('Delete all NF_ nodes from Neo4j? Actors, narratives, platforms, events – everything. This cannot be undone.')) return;
    fetch('/api/cleanup', { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            selectedInvUid = null;
            userHasZoomed  = false;
            document.getElementById('statusMsg').textContent =
                '🧹 Cleaned: ' + (d.deleted || 0) + ' nodes deleted';
            document.getElementById('timelineTitle').textContent = '📈 Timeline – select an investigation';
            document.getElementById('timelineEvents').innerHTML = '';
            var canvas = document.getElementById('timelineCanvas');
            if (canvas) { var ctx = canvas.getContext('2d'); ctx.clearRect(0,0,canvas.width,canvas.height); }
            loadStatus();
            loadGraph();
        });
}

function deleteInvestigation(uid) {
    if (!confirm('Delete everything? Removes all actors, narratives, spread events and Neo4j data for this investigation. This cannot be undone.')) return;
    fetch('/api/investigate/delete/' + uid, { method: 'DELETE' })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (selectedInvUid === uid) {
                selectedInvUid = null;
                userHasZoomed  = false;
            }
            document.getElementById('statusMsg').textContent =
                '🗑 Deleted: ' + (d.deleted_nodes || 0) + ' nodes removed';
            loadStatus();
            loadGraph();
            if (graphMode === 'timeline') loadTimeline();
        });
}

function exportInvestigations() {
    fetch('/api/export')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var json   = JSON.stringify(data, null, 2);
            var blob   = new Blob([json], { type: 'application/json' });
            var url    = URL.createObjectURL(blob);
            var ts     = new Date().toISOString().replace(/[:.]/g,'-').substring(0,19);
            var a      = document.createElement('a');
            a.href     = url;
            a.download = 'lyra_narrative_export_' + ts + '.json';
            a.click();
            URL.revokeObjectURL(url);
            document.getElementById('statusMsg').textContent =
                '💾 Export: ' + (data.investigations || []).length + ' investigations';
        })
        .catch(function(e) {
            alert('Export failed: ' + e);
        });
}

function importInvestigations(input) {
    var file = input.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(e) {
        try {
            var data = JSON.parse(e.target.result);
        } catch(err) {
            alert('Invalid JSON file: ' + err);
            return;
        }
        fetch('/api/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            document.getElementById('statusMsg').textContent =
                '📂 Import: ' + (d.imported_investigations || 0) + ' investigations, ' +
                (d.imported_nodes || 0) + ' nodes';
            loadStatus();
            loadGraph();
        });
    };
    reader.readAsText(file);
    input.value = '';
}

function toggleAgent() {
    var ep = agentRunning ? '/api/agent/stop' : '/api/agent/start';
    fetch(ep, { method: 'POST' })
        .then(function(r) { return r.json(); })
        .then(function() { loadStatus(); });
}

function loadStatus() {
    fetch('/api/status')
        .then(function(r) { return r.json(); })
        .then(function(data) {
            agentRunning = data.running || false;
            document.getElementById('btnToggle').textContent =
                agentRunning ? '⏸ Pause' : '▶ Start';

            var s = data.db_stats || {};
            document.getElementById('statActors').textContent     = s.actors     || 0;
            document.getElementById('statNarratives').textContent = s.narratives  || 0;
            document.getElementById('statArticles').textContent   = s.articles    || 0;
            document.getElementById('statPlatforms').textContent  = s.platforms   || 0;

            var mac = document.getElementById('multiActorList');
            if (data.multi_actors && data.multi_actors.length > 0) {
                mac.innerHTML = data.multi_actors.slice(0,8).map(function(a) {
                    return '<div style="padding:2px 0;border-bottom:1px solid #1a1a2e;">' +
                           '<span style="color:#ff6644;">⚠️ ' + escHtml(a.name) + '</span>' +
                           ' <span style="color:#556;">' + (a.platform||'') + '</span>' +
                           ' <span style="color:#4af;float:right;">' + a.cnt + ' Narrative</span>' +
                           '</div>';
                }).join('');
            } else {
                mac.innerHTML = '<div style="color:#445;font-size:0.85em;">No recurring actors found yet.</div>';
            }

            var invs = data.investigations || [];
            var el   = document.getElementById('invList');
            if (invs.length === 0) {
                el.innerHTML = '<div style="color:#445;font-size:0.75em;">No investigations</div>';
            } else {
                var html = '';
                invs.forEach(function(inv) {
                    var icon = inv.status === 'active' ? '🔄' :
                               inv.status === 'done'   ? '✅' : '🕵️';
                    var isSelected = selectedInvUid === inv.uid;
                    var cardStyle = isSelected
                        ? 'position:relative;border-color:#4488ff;background:rgba(68,136,255,0.15);cursor:pointer;'
                        : 'position:relative;cursor:pointer;';
                    html += '<div class="inv-card ' + inv.status + '" style="' + cardStyle + '" data-inv-uid="' + escHtml(inv.uid) + '">';
                    html += '<div style="display:flex;justify-content:space-between;align-items:center;">';
                    html += '<span class="inv-badge">' + icon + ' ' + inv.status.toUpperCase() + (isSelected ? ' 👁' : '') + '</span>';
                    html += '<span style="color:#4af;font-size:0.85em;">' + inv.findings + ' hits · ' + inv.actors_found + ' actors</span>';
                    html += '<button class="inv-del-btn" data-uid="' + escHtml(inv.uid) + '" ';
                    html += 'style="background:none;border:1px solid #664;color:#c86;border-radius:3px;';
                    html += 'padding:1px 6px;cursor:pointer;font-size:0.8em;flex-shrink:0;" ';
                    html += 'title="Delete investigation">🗑</button>';
                    html += '</div>';
                    html += '<div class="inv-text">' + escHtml(inv.query.substring(0,80)) + '</div>';
                    html += '</div>';
                });
                el.innerHTML = html;
                el.querySelectorAll('.inv-card').forEach(function(card) {
                    card.addEventListener('click', function() {
                        var newUid = card.getAttribute('data-inv-uid');
                        if (newUid !== selectedInvUid) {
                            userHasZoomed  = false;
                            selectedInvUid = newUid;
                            // Clear network → forces fresh layout on next loadGraph
                            if (network) network.setData({ nodes: new vis.DataSet([]), edges: new vis.DataSet([]) });
                        }
                        if (graphMode === 'timeline') loadTimeline();
                        else loadGraph();
                        loadStatus();
                    });
                });
                el.querySelectorAll('.inv-del-btn').forEach(function(btn) {
                    btn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        deleteInvestigation(btn.getAttribute('data-uid'));
                    });
                });
            }

            if (!selectedInvUid && data.investigations && data.investigations.length === 1) {
                selectedInvUid = data.investigations[0].uid;
            }
            var acts = data.activity || [];
            document.getElementById('actList').innerHTML = acts.map(function(a) {
                return '<div class="act-item">' + a.time + ' ' + escHtml(a.message.substring(0,90)) + '</div>';
            }).join('');
        })
        .catch(function() {
            document.getElementById('statusMsg').textContent = '🔴 Connection lost';
        });
}

function escHtml(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
                    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function initResizer() {
    var res = document.getElementById('resizerEl');
    var sb  = document.getElementById('sidebarEl');
    if (!res || !sb) return;
    var drag = false;
    res.addEventListener('mousedown', function(e) {
        drag = true; document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none'; e.preventDefault();
    });
    document.addEventListener('mousemove', function(e) {
        if (!drag) return;
        var w = Math.min(Math.max(e.clientX, 200), window.innerWidth * 0.6);
        sb.style.width = w + 'px';
        if (network) network.redraw();
    });
    document.addEventListener('mouseup', function() {
        if (!drag) return;
        drag = false; document.body.style.cursor = '';
        document.body.style.userSelect = '';
        if (network) { network.redraw(); network.fit(); }
    });
}
</script>
</body>
</html>
""".replace("__VERSION__", VERSION)


class NarrativeServer:
    """Flask-Server für LYRA Narrative Forensics.
    Flask server for LYRA Narrative Forensics."""

    def __init__(self, db: NarrativeNeo4j, agent: NarrativeAgent, log_fn=None):
        self.db     = db
        self.agent  = agent
        self.log    = log_fn or (lambda m, l="INFO": print(f"[{_ts()}] [{l}] [WEB] {m}"))
        self.server = None
        self._setup_static()

    def _setup_static(self):
        import shutil, urllib.request
        static_dir = Path.home() / ".openclaw" / "static_narrative"
        static_dir.mkdir(parents=True, exist_ok=True)
        self._static_dir = static_dir

        libs = {
            "jquery.min.js":      "https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js",
            "vis-network.min.js": "https://unpkg.com/vis-network@9.1.2/dist/vis-network.min.js",
        }

        search_roots = [
            Path.home() / ".openclaw" / "static",
            Path("C:/Python/Projects/ClawBotInstaller/Tools"),
            Path("C:/Python/Projects"),
        ]

        for lib, cdn_url in libs.items():
            dest = static_dir / lib
            if dest.exists():
                continue

            copied = False
            for root in search_roots:
                if not root.exists():
                    continue
                found = list(root.rglob(lib))
                if found:
                    shutil.copy(found[0], dest)
                    self.log(f"Static: {lib} found locally", "INFO")
                    copied = True
                    break

            if not copied:
                try:
                    self.log(f"Static: downloading {lib}…", "INFO")
                    urllib.request.urlretrieve(cdn_url, dest)
                    self.log(f"Static: {lib} downloaded ✓", "SUCCESS")
                except Exception as e:
                    self.log(f"Static: {lib} download failed: {e}", "WARNING")

    def build_app(self):
        from flask import Flask, jsonify, request, send_from_directory
        app = Flask(__name__, static_folder=None)

        @app.route("/")
        def index():
            return HTML_TEMPLATE, 200, {"Content-Type": "text/html; charset=utf-8"}

        @app.route("/static/<path:filename>")
        def static_files(filename):
            return send_from_directory(str(self._static_dir), filename)

        @app.route("/api/health")
        def health():
            stats = self.db.get_stats()
            return jsonify({"status": "ok", "version": VERSION, **stats})

        @app.route("/api/status")
        def status():
            s = self.agent.get_status()
            s["multi_actors"] = self.db.search_actors_by_narrative_count(min_count=2)
            return jsonify(s)

        @app.route("/api/graph")
        def graph():
            mode    = request.args.get("mode", "actor")
            inv_uid = request.args.get("inv_uid") or None
            return jsonify(self.db.get_graph_data(mode=mode, inv_uid=inv_uid))

        @app.route("/api/investigate", methods=["POST"])
        def investigate():
            data          = request.get_json(silent=True) or {}
            q             = data.get("query", "").strip()
            breadth       = int(data.get("breadth", 20))
            depth         = int(data.get("depth", 1))
            comment_pages = int(data.get("comment_pages", 2))
            if not q:
                return jsonify({"error": "query fehlt"}), 400
            inv = self.agent.add_investigation(q, search_breadth=breadth,
                                               search_depth=depth,
                                               comment_pages=comment_pages)
            return jsonify({"uid": inv.uid, "query": inv.query,
                            "status": inv.status,
                            "search_breadth": inv.search_breadth,
                            "search_depth": inv.search_depth,
                            "comment_pages": inv.comment_pages})

        @app.route("/api/import", methods=["POST"])
        def import_artifact():
            data     = request.get_json(silent=True) or {}
            text     = data.get("text", "").strip()
            url      = data.get("url", "")
            date     = data.get("date", "")
            platform = data.get("platform", "unknown")
            if not text:
                return jsonify({"error": "text fehlt"}), 400
            n_uid = self.agent.importer.import_text(text, url, date, platform)
            return jsonify({"narrative_uid": n_uid, "status": "imported"})

        @app.route("/api/import/corpus", methods=["POST"])
        def import_corpus():
            n = self.agent.importer.scan_corpus()
            return jsonify({"imported": n})

        @app.route("/api/actor/<path:actor_id>")
        def actor_profile(actor_id):
            return jsonify(self.db.get_actor_profile(actor_id))

        @app.route("/api/investigate/delete/<inv_uid>", methods=["DELETE"])
        def delete_investigation(inv_uid):
            inv_query = None
            with self.agent._lock:
                for inv in self.agent.investigations:
                    if inv.uid == inv_uid:
                        inv_query = inv.query
                        break
                self.agent.investigations = [
                    i for i in self.agent.investigations if i.uid != inv_uid
                ]
            self.agent._save_state()
            if inv_query:
                slug = re.sub(r'[^\w]', '_', inv_query[:50]).lower()
                for f in NARRATIVE_DIR.glob(f"{slug}_*.md"):
                    try: f.unlink()
                    except Exception: pass
            deleted = self.db.delete_investigation(inv_uid)
            return jsonify({"deleted": inv_uid, "deleted_nodes": deleted, "status": "ok"})

        @app.route("/api/export")
        def export_all():
            export = {
                "version": VERSION, "exported_at": _now_iso(),
                "investigations": [{k: v for k, v in inv.__dict__.items()}
                                   for inv in self.agent.investigations],
                "activity": self.agent.activity[:100],
            }
            export.update(self.db.export_all())
            return jsonify(export)

        @app.route("/api/import", methods=["POST"])
        def import_archive():
            data = request.get_json(silent=True) or {}

            if "text" in data:
                text     = data.get("text", "").strip()
                url      = data.get("url", "")
                date     = data.get("date", "")
                platform = data.get("platform", "unknown")
                if not text:
                    return jsonify({"error": "text fehlt"}), 400
                n_uid = self.agent.importer.import_text(text, url, date, platform)
                return jsonify({"narrative_uid": n_uid, "status": "imported"})

            imported_inv   = 0
            imported_nodes = 0
            errors         = []

            for inv_data in data.get("investigations", []):
                try:
                    existing_uids = {i.uid for i in self.agent.investigations}
                    if inv_data.get("uid") in existing_uids:
                        continue
                    inv = Investigation(**{
                        k: v for k, v in inv_data.items()
                        if k in Investigation.__dataclass_fields__
                    })
                    inv.status = "done"
                    with self.agent._lock:
                        self.agent.investigations.append(inv)
                    imported_inv += 1
                except Exception as e:
                    errors.append(f"Investigation: {e}")

            if self.db.get_driver() and data.get("nodes"):
                try:
                    with self.db.get_driver().session() as s:
                        for node_data in data["nodes"]:
                            labels = node_data.get("labels", [])
                            props  = node_data.get("props", {})
                            if not labels or not props.get("uid"):
                                continue
                            label_str = ":".join(labels)
                            s.run(f"""
                                MERGE (n:{label_str} {{uid: $uid}})
                                SET n += $props
                            """, uid=props["uid"], props=props)
                            imported_nodes += 1
                        for edge_data in data.get("edges", []):
                            if not edge_data.get("from_uid") or not edge_data.get("to_uid"):
                                continue
                            rel_type = edge_data.get("type", "RELATED")
                            s.run(f"""
                                MATCH (a {{uid: $from_uid}}), (b {{uid: $to_uid}})
                                MERGE (a)-[r:{rel_type}]->(b)
                                SET r += $props
                            """, from_uid=edge_data["from_uid"],
                                 to_uid=edge_data["to_uid"],
                                 props=edge_data.get("props", {}))
                except Exception as e:
                    errors.append(f"Neo4j: {e}")

            self.agent._save_state()
            return jsonify({
                "imported_investigations": imported_inv,
                "imported_nodes":          imported_nodes,
                "errors":                  errors[:5],
                "status": "ok"
            })

        @app.route("/api/node/<path:node_id>/delete", methods=["POST"])
        def node_delete(node_id):
            deleted = self.db.delete_node(node_id)
            return jsonify({"deleted": deleted, "status": "ok"})

        _deep_scan_jobs: dict = {}

        @app.route("/api/deep_scan", methods=["POST"])
        def deep_scan_start():
            data      = request.get_json(force=True) or {}
            inv_uid   = data.get("inv_uid", "").strip()
            url       = data.get("url", "").strip()
            actor_uid = data.get("actor_uid", "").strip()
            if not inv_uid or not url:
                return jsonify({"error": "inv_uid and url required"}), 400
            inv = next((i for i in self.agent.investigations if i.uid == inv_uid), None)
            if not inv:
                return jsonify({"error": "Investigation not found"}), 404
            import uuid
            job_id = str(uuid.uuid4())[:8]
            _deep_scan_jobs[job_id] = {"status": "running", "error": None}
            def run():
                try:
                    self.agent._deep_scan_url(inv, url, actor_uid)
                    _deep_scan_jobs[job_id]["status"] = "done"
                except Exception as e:
                    _deep_scan_jobs[job_id]["status"] = "error"
                    _deep_scan_jobs[job_id]["error"]  = str(e)
            import threading
            threading.Thread(target=run, daemon=True).start()
            return jsonify({"job_id": job_id, "status": "started"})

        @app.route("/api/deep_scan/<job_id>")
        def deep_scan_status(job_id):
            job = _deep_scan_jobs.get(job_id)
            if not job:
                return jsonify({"error": "Job not found"}), 404
            return jsonify(job)

        @app.route("/api/orphan_check", methods=["POST"])
        def orphan_check():
            data    = request.get_json(force=True) or {}
            inv_uid = data.get("inv_uid", "").strip()
            inv = next((i for i in self.agent.investigations if i.uid == inv_uid), None)
            if not inv:
                return jsonify({"error": "Investigation not found"}), 404
            n_uid = f"narr_{_fingerprint(inv.query)}"
            import threading
            def run():
                self.agent._orphan_check(inv, n_uid)
            threading.Thread(target=run, daemon=True).start()
            # Count synchronously for status response
            orphans = 0
            try:
                with self.db.get_driver().session() as s:
                    for q in [
                        "MATCH (a:NF_Actor {inv_uid:$i}) WHERE NOT (()-[:COMMENTED_BY]->(a)) AND NOT (()-[:AUTHORED_BY]->(a)) RETURN count(a) AS c",
                        "MATCH (p:NF_Platform {inv_uid:$i}) WHERE NOT (p)-[:SPREADS]->(:NF_Narrative) RETURN count(p) AS c",
                        "MATCH (a:NF_Article {inv_uid:$i}) WHERE NOT (a)-[:PUBLISHED_ON]->() RETURN count(a) AS c",
                        "MATCH (c:NF_Comment {inv_uid:$i}) WHERE NOT (c)-[:PART_OF]->() RETURN count(c) AS c",
                    ]:
                        orphans += s.run(q, i=inv_uid).single()["c"]
            except Exception:
                pass
            return jsonify({"orphans": orphans, "status": "running"})

        @app.route("/api/cleanup", methods=["POST"])
        def cleanup_all():
            deleted = self.db.cleanup_all()
            return jsonify({"deleted": deleted, "status": "ok"})

        if os.environ.get("LYRA_DEBUG", "false").lower() == "true":
            @app.route("/api/debug/graph")
            def debug_graph():
                if not self.db.get_driver():
                    return jsonify({"error": "Keine DB"})
                result = {}
                try:
                    with self.db.get_driver().session() as s:
                        # Kanten-Typen Übersicht
                        rels = s.run("""
                            MATCH (a)-[r]->(b)
                            WHERE any(l IN labels(a) WHERE l STARTS WITH 'NF_')
                            RETURN type(r) AS t,
                                   labels(a)[0] AS von,
                                   labels(b)[0] AS nach,
                                   count(r) AS anzahl
                            ORDER BY anzahl DESC
                        """).data()
                        result["kanten"] = rels

                        # Actors MIT Artikel-Verbindung (via Comment oder AUTHORED_BY)
                        with_article = s.run("""
                            MATCH (a:NF_Actor)-[*1..2]-(art:NF_Article)
                            RETURN count(DISTINCT a) AS actors_mit_artikel
                        """).single()
                        result["actors_mit_artikel"] = with_article["actors_mit_artikel"] if with_article else 0

                        # Actors OHNE Artikel-Verbindung
                        without_article = s.run("""
                            MATCH (a:NF_Actor)
                            WHERE NOT (a)-[*1..2]-(:NF_Article)
                            RETURN count(a) AS actors_ohne_artikel
                        """).single()
                        result["actors_ohne_artikel"] = without_article["actors_ohne_artikel"] if without_article else 0

                        # NF_Comment Knoten vorhanden?
                        comments = s.run("MATCH (c:NF_Comment) RETURN count(c) AS n").single()
                        result["nf_comment_count"] = comments["n"] if comments else 0

                        # Beispiel: ein Actor mit seinem Pfad zum Artikel
                        sample = s.run("""
                            MATCH (a:NF_Actor)-[r1]-(x)-[r2]-(art:NF_Article)
                            RETURN a.name AS actor, type(r1) AS rel1,
                                   labels(x)[0] AS via, type(r2) AS rel2,
                                   art.title AS artikel
                            LIMIT 5
                        """).data()
                        result["actor_artikel_pfade"] = sample

                        # Actors direkt → Artikel (AUTHORED_BY)
                        authored = s.run("""
                            MATCH (art:NF_Article)-[:AUTHORED_BY]->(a:NF_Actor)
                            RETURN a.name AS actor, art.title AS artikel
                            LIMIT 5
                        """).data()
                        result["authored_by_sample"] = authored

                except Exception as e:
                    result["error"] = str(e)
                return jsonify(result)

        @app.route("/api/node-expand/<path:node_uid>")
        def node_expand(node_uid):
            if not self.db.get_driver():
                return jsonify({"nodes": [], "edges": []})
            nodes, edges = [], []
            seen_n, seen_e = set(), set()
            try:
                with self.db.get_driver().session() as s:
                    # Alle direkten Verbindungen (1 Hop)
                    r1 = s.run("""
                        MATCH (c {uid: $uid})-[r]-(nb)
                        WHERE any(l IN labels(nb) WHERE l STARTS WITH 'NF_')
                        RETURN c, r, nb
                    """, uid=node_uid)

                    def add_n(node):
                        nid = node.get("uid") or node.element_id
                        if nid in seen_n: return nid
                        seen_n.add(nid)
                        lbl  = list(node.labels)[0] if node.labels else "Unknown"
                        name = node.get("name") or node.get("title") or node.get("text") or str(nid)[:20]
                        is_author = False
                        nodes.append({
                            "id":        nid,
                            "label":     str(name)[:40],
                            "group":     lbl,
                            "title":     f"{lbl}: {str(name)[:200]}",
                            "full":      dict(node),
                            "stance":    node.get("stance","neutral"),
                            "is_author": is_author,
                        })
                        return nid

                    def add_e(a, rel, b):
                        sid = a.get("uid") or a.element_id
                        tid = b.get("uid") or b.element_id
                        eid = f"{sid}→{rel.type}→{tid}"
                        if eid not in seen_e:
                            seen_e.add(eid)
                            edges.append({"from":sid,"to":tid,"label":rel.type})

                    for rec in r1:
                        add_n(rec["c"]); add_n(rec["nb"]); add_e(rec["c"], rec["r"], rec["nb"])

                    # 2-Hop via Comment-Knoten (Actor←Comment→Article←Comment→Actor)
                    r2 = s.run("""
                        MATCH (c {uid: $uid})-[r1]-(mid:NF_Comment)-[r2]-(nb)
                        WHERE any(l IN labels(nb) WHERE l STARTS WITH 'NF_')
                        RETURN mid, r1, r2, nb
                        LIMIT 200
                    """, uid=node_uid)
                    for rec in r2:
                        add_n(rec["mid"]); add_n(rec["nb"])
                        add_e(rec["mid"], rec["r1"], s.run("MATCH (n {uid:$uid}) RETURN n LIMIT 1",uid=node_uid).single()["n"] if False else rec["mid"])
                        edges.append({"from": rec["mid"].get("uid") or rec["mid"].element_id,
                                      "to":   rec["nb"].get("uid")  or rec["nb"].element_id,
                                      "label": rec["r2"].type})

                    # Autoren markieren
                    author_ids = {e["to"] for e in edges if e["label"] == "AUTHORED_BY"}
                    for n in nodes:
                        if n["id"] in author_ids:
                            n["is_author"] = True

            except Exception as e:
                pass
            return jsonify({"nodes": nodes, "edges": edges})

        @app.route("/api/node/<path:node_id>")
        def node_info(node_id):
            if not self.db.get_driver():
                return jsonify({"error": "DB not connected"})
            try:
                with self.db.get_driver().session() as s:
                    rec = s.run("""
                        MATCH (n) WHERE n.uid = $uid OR elementId(n) = $eid
                        RETURN n LIMIT 1
                    """, uid=node_id, eid=node_id).single()
                    if not rec:
                        return jsonify({})
                    data = dict(rec["n"])
                    lbl  = list(rec["n"].labels)[0] if rec["n"].labels else ""
                    data["group"] = lbl
                    if lbl == "NF_Actor":
                        urls = s.run("""
                            MATCH (a {uid: $uid})-[r:SPREADS]->()
                            WHERE r.url IS NOT NULL AND r.url <> ''
                            RETURN DISTINCT r.url AS url, r.date AS date, r.role AS role
                            ORDER BY r.date ASC LIMIT 10
                        """, uid=node_id).data()
                        art_urls = s.run("""
                            MATCH (art:NF_Article)-[:AUTHORED_BY]->(a {uid: $uid})
                            WHERE art.url IS NOT NULL AND art.url <> ''
                            RETURN DISTINCT art.url AS url, art.date AS date, 'AUTHORED' AS role
                            ORDER BY art.date ASC LIMIT 5
                        """, uid=node_id).data()
                        all_urls = urls + art_urls
                        if all_urls:
                            if not data.get("url"):
                                data["url"] = all_urls[0]["url"]
                            # Sauber strukturiert: kein Pipe-Separator der URL-Extraktion verwirrt
                            data["sources"] = [
                                {"date": u.get("date") or "?",
                                 "role": u.get("role") or "?",
                                 "url":  u.get("url") or ""}
                                for u in all_urls[:5]
                            ]

                    return jsonify(data)
            except Exception as e:
                return jsonify({"error": str(e)})

        @app.route("/api/agent/start", methods=["POST"])
        def agent_start():
            if not self.agent.running:
                self.agent.start()
            return jsonify({"status": "running"})

        @app.route("/api/agent/stop", methods=["POST"])
        def agent_stop():
            self.agent.stop()
            return jsonify({"status": "stopped"})

        @app.route("/api/narratives")
        def get_narratives():
            narrs = self.db.get_investigations_summary()
            return jsonify({"narratives": narrs})

        @app.route("/api/timeline/<inv_uid>")
        def timeline(inv_uid):
            events = self.db.get_timeline_data(inv_uid)
            return jsonify(events)

        return app

    def start(self):
        app = self.build_app()
        try:
            from waitress import serve
            self.log(f"Server started on http://127.0.0.1:{FLASK_PORT}", "SUCCESS")
            serve(app, host="127.0.0.1", port=FLASK_PORT, threads=8)
        except ImportError:
            from werkzeug.serving import make_server
            self.server = make_server("127.0.0.1", FLASK_PORT, app)
            self.log(f"Server started on http://127.0.0.1:{FLASK_PORT}", "SUCCESS")
            self.server.serve_forever()


# ── Einstiegspunkt / Entry point ─────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"LYRA Narrative Forensics  v{VERSION}")
    print(f"Forensische Analyse von Informationskriegs-Narrativen")
    print(f"Forensic Analysis of Information-Warfare Narratives")
    print(f"{'='*60}\n")

    log = lambda m, l="INFO": print(
        f"[{_ts()}] {'✅' if l=='SUCCESS' else '⚠️' if l=='WARNING' else '❌' if l=='ERROR' else '📌'} [NF] {m}"
    )

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    NARRATIVE_DIR.mkdir(parents=True, exist_ok=True)
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    log(f"Workspace: {WORKSPACE}")
    log(f"Corpus dir for manual artifacts / Corpus-Dir für manuelle Artefakte: {CORPUS_DIR}")
    log(f"Corpus dir: place files as YYYY-MM-DD_platform_title.txt")

    db = NarrativeNeo4j(log_fn=log)
    db_ok = db.connect()
    if db_ok:
        db.init_schema()
    else:
        log("Continuing without Neo4j – in-memory mode only / Weiter ohne Neo4j – nur In-Memory-Betrieb", "WARNING")
        log(f"Start Neo4j for narratives: port {NEO4J_PORT}, password: {NEO4J_PASSWORD}", "WARNING")

    agent = NarrativeAgent(db=db, log_fn=log)

    server = NarrativeServer(db=db, agent=agent, log_fn=log)
    log(f"Web-UI: http://127.0.0.1:{FLASK_PORT}")
    log("Minimise window, do not close / Fenster minimieren, nicht schliessen.")

    import threading, webbrowser
    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{FLASK_PORT}")
    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        server.start()
    except KeyboardInterrupt:
        log("Shutdown…")
        agent.stop()
        db.close()
        log("Done / Beendet.")


if __name__ == "__main__":
    main()
