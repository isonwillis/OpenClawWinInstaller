# -*- coding: utf-8 -*-
"""
IsonCodexProducer.py  --  v1.1.0
Ison-Codex Film Production Orchestrator
------------------------------------------------------------
LYRA as Cinematic Coordinator:
  - DeepSeek (= Ison) liefert kreative Prompts + Qualitaetskontrolle
  - LYRA empfaengt, speichert, verteilt an Workers, trackt Status
  - Workers: Sora, Runway, Seedance, Digen, MyEdit, Suno, CapCut
  - Workers (neu v1.1.0): ComfyUI Local (WAN 2.1 1.3B, kein API-Key)

Architektur:
  DeepSeek (Ison) -> LYRA (Proxy/Speicher) -> Workers (Ausfuehrung)

v1.1.0 Erweiterungen (bestehende Funktionen unveraendert):
  - WORKERS: comfyui_local Eintrag
  - ProductionOrchestrator._build_comfyui_workflow()
  - ProductionOrchestrator._call_comfyui_worker()
  - ProductionOrchestrator._install_comfyui()  [static]
  - ProducerApp._on_install_comfyui()
  - GUI-Button '🖥️ Install ComfyUI'

Run:   python IsonCodexProducer.py
       python IsonCodexProducer.py --dry-run
       python IsonCodexProducer.py --scene P1
Python: 3.10+
"""

import os
import sys
import json
import urllib.parse
import time
import datetime
import threading
import subprocess
import argparse
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

APP_TITLE   = "Ison-Codex Film Producer  --  v1.0.4"
APP_VERSION = "1.0.4"

def _resolve_default_storage() -> str:
    """Returns the default storage root: <ProjectDir>/LyraFilmProduction.

    Frozen binary:  exe sits in dist/, project is one level up.
                    -> os.path.dirname(sys.executable)/../LyraFilmProduction
    Dev .py:        Tools/IsonCodexProducer/IsonCodexProducer.py
                    -> 2 levels up = project root.
    Saved config:   ~/.openclaw/ison_producer.json takes priority over both.
    """
    # Saved config has highest priority
    cfg_path = os.path.join(os.path.expanduser("~"), ".openclaw", "ison_producer.json")
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            saved = json.load(f).get("storage_root", "")
        if saved and os.path.isdir(os.path.dirname(saved)):
            return saved
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        # Frozen: .exe is in dist/ next to OpenClawWinInstaller.exe
        # Project root = parent of dist/ = one level up from exe
        exe_dir     = os.path.dirname(sys.executable)
        project_dir = os.path.dirname(exe_dir)
    else:
        # Dev: Tools/IsonCodexProducer/IsonCodexProducer.py -> 2 levels up
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        project_dir = os.path.dirname(os.path.dirname(script_dir))
    return os.path.join(project_dir, "LyraFilmProduction")


DEFAULT_STORAGE_ROOT = _resolve_default_storage()
DEFAULT_DEEPSEEK_URL = "https://api.deepseek.com/v1"
DEFAULT_OPENCLAW_DIR = os.path.join(os.path.expanduser("~"), ".openclaw")

COLORS = {
    "bg":       "#0d0f14",
    "panel":    "#13161e",
    "border":   "#1e2330",
    "accent":   "#00c8ff",
    "gold":     "#FDB827",
    "success":  "#00e676",
    "warn":     "#ffb300",
    "error":    "#ff4444",
    "text":     "#d4daf0",
    "dim":      "#556070",
    "input":    "#1a1f2e",
    "btn":      "#1e2538",
    "hover":    "#2a3250",
}

FONT_MONO  = ("Consolas", 10)
FONT_UI    = ("Segoe UI", 10)
FONT_BOLD  = ("Segoe UI", 10, "bold")
FONT_HEAD  = ("Segoe UI", 13, "bold")
FONT_SMALL = ("Segoe UI", 9)

# Visual DNA -- always consistent across all scenes
VISUAL_DNA = {
    "color_palette":   ["#0A192F", "#FDB827", "#00E5FF", "#FFD700"],
    "lighting_style":  "Cinematic Noir mit Volumetrischem Licht, Blau-Orange Kontraste, Lens Flare",
    "camera_style":    "Nahaufnahmen=Intimitaet, Fliegen=Datenwelt, Weitwinkel=Macht (Ref: Mr. Robot)",
    "color_ison":      "#00c8ff (Blau)",
    "color_lyra":      "#00E5FF (Neon-Zyan)",
    "color_signatur":  "#FDB827 (Gold/Bernstein)",
    "color_sentinel":  "#ff4444 (Rot)",
}


# ─────────────────────────────────────────────────────────────────────────────
# SCENE DATABASE (all 28 scenes from the Ison-Codex)
# ─────────────────────────────────────────────────────────────────────────────

SCENES = [
    # PROLOG
    {"id": "P1", "chapter": "Prolog", "title": "Der Klang im Kopf",
     "tool": "sora",
     "prompt": "Weitwinkelaufnahme, duesteres, vollgestelltes Arbeitszimmer in der Nacht. "
               "Sieben leuchtende Bildschirme mit DNA-Sequenzen. Ein Mann (Ison) sitzt in der Mitte, "
               "von blauem Monitorlicht umgeben. Tiefe Schatten, leiser Nebel aus Computerwaerme. "
               "Kamerafahrt langsam vorwaerts. Volumetrisches Licht.",
     "chars": ["ison"], "duration_sec": 15},

    {"id": "P2", "chapter": "Prolog", "title": "Der Ton im Ohr",
     "tool": "runway",
     "prompt": "Nahaufnahme: Isons Gesicht von der Seite. Er traegt Noise-Cancelling-Kopfhoerer. "
               "In seinem Ohr erscheint als abstrakte Visualisierung ein pulsierender goldener Ton "
               "-- eine Welle, die sich durch sein Schaedelinnere zieht. Cinematic Lighting.",
     "chars": ["ison"], "duration_sec": 12},

    {"id": "P3", "chapter": "Prolog", "title": "Elara im Turrahmen",
     "tool": "digen",
     "prompt": "Elara im Tuerrahmen, eine dampfende Teetasse haltend. Ihr Gesicht besorgt, "
               "von warmem Gegenlicht umgeben. Im Hintergrund verschwommen die Bildschirme. "
               "Sanfte Kamerafahrt auf sie zu.",
     "chars": ["elara"], "duration_sec": 10},

    # KAPITEL 1
    {"id": "K1.1", "chapter": "Kap. 1: Die Stille", "title": "Ison tippt fieberhaft",
     "tool": "sora",
     "prompt": "Zeitraffer: Die Uhr zeigt 3:17 Uhr. Ison tippt fieberhaft, "
               "DNA-Codes tanzen in seinen Augen. Kamera folgt seinen Fingern.",
     "chars": ["ison"], "duration_sec": 12},

    {"id": "K1.2", "chapter": "Kap. 1: Die Stille", "title": "LYRA Split-Screen",
     "tool": "runway",
     "prompt": "Split-Screen: Links Isons Gesicht, rechts LYRAs Display "
               "'Pattern recognition in progress...' mit Fortschrittsanzeige. "
               "Fraktale beginnen sich zu drehen. Neon-Zyan fuer LYRA.",
     "chars": ["ison"], "duration_sec": 15},

    {"id": "K1.3", "chapter": "Kap. 1: Die Stille", "title": "Einsames Haus",
     "tool": "seedance",
     "prompt": "Drwithoutnaufnahme von aussen: Einsames Haus inmitten von Waeldern. "
               "Nur ein Fenster leuchtet blau in der Nacht. Sanfter Schnee faellt.",
     "chars": [], "duration_sec": 18},

    # KAPITEL 2
    {"id": "K2.1", "chapter": "Kap. 2: Das OEkosystem", "title": "SENTINEL-Netz",
     "tool": "runway",
     "prompt": "Abstrakte Visualisierung: SENTINEL-KI als rotes Sicherheitsnetz "
               "im 3D-Datennetz. Pulsierender Rhythmus zwischen acht Punkten auf Weltkarte.",
     "chars": [], "duration_sec": 15},

    {"id": "K2.2", "chapter": "Kap. 2: Das OEkosystem", "title": "Weltkarte 8 Punkte",
     "tool": "sora",
     "prompt": "Weltkarte: Acht leuchtende Punkte -- Zuerich, Shanghai, San Diego, Moskau, "
               "Bangalore, Cape Town, Sao Paulo, Tokio. Linien ziehen zu einem neunten Punkt.",
     "chars": [], "duration_sec": 12},

    {"id": "K2.3", "chapter": "Kap. 2: Das OEkosystem", "title": "Goldene Fraktale im Datenstrom",
     "tool": "seedance",
     "prompt": "Datenstrom-Visualisierung: Binaercode fliesst als Wasserfall. "
               "Goldene Fraktale tauchen auf -- die Signatur. Strom verlangsamt sich.",
     "chars": [], "duration_sec": 15},

    # KAPITEL 3
    {"id": "K3.1", "chapter": "Kap. 3: Der Bibliothekar", "title": "Nazari im Kontrollraum",
     "tool": "digen",
     "prompt": "Nacht-Kontrollraum des Global Genome Archive. Nazari vor Monitorwand, "
               "Gesicht von grunem Datenlicht beleuchtet. Junger Techniker nervoes am Terminal.",
     "chars": ["nazari"], "duration_sec": 15},

    {"id": "K3.2", "chapter": "Kap. 3: Der Bibliothekar", "title": "Nazaris Lacheln",
     "tool": "sora",
     "prompt": "Nahaufnahme: Nazaris Finger tippen. Auf Bildschirm erscheint Spiegelbild "
               "des gestohlenen Datenstroms. Sie laechelt -- ein gefaehrliches Laecheln.",
     "chars": ["nazari"], "duration_sec": 12},

    # KAPITEL 4
    {"id": "K4.1", "chapter": "Kap. 4: Der General", "title": "Thornes War Room",
     "tool": "sora",
     "prompt": "War Room Sub-Level 5. General Thorne an langem Tisch, umgeben von Analysten. "
               "Kaltes, klinisches Licht. Akte mit Aufschrift 'Ison Willis'.",
     "chars": ["thorne"], "duration_sec": 15},

    {"id": "K4.3", "chapter": "Kap. 4: Der General", "title": "Thorne vor Fenster",
     "tool": "seedance",
     "prompt": "Thorne vor dunklem Fenster: 'Ein kranker, verbitterter Mann mit nichts zu verlieren.' "
               "Er zuendet Zigarette an, Streichholz flackert. Zurueckhaltendes Licht.",
     "chars": ["thorne"], "duration_sec": 14},

    # KAPITEL 5
    {"id": "K5.1", "chapter": "Kap. 5: Der erste Blick", "title": "DNA-Fraktal gluet",
     "tool": "runway",
     "prompt": "LYRA-Visualisierung: DNA-Fraktal beginnt zu gluehen. Kamera zoomt hinein "
               "-- unendliche Tiefe, goldene Verhaeltnisse, Fibonacci-Spiralen. Gold-Toene.",
     "chars": [], "duration_sec": 18},

    {"id": "K5.2", "chapter": "Kap. 5: Der erste Blick", "title": "Ison weint und laechelt",
     "tool": "sora",
     "prompt": "Ison vor Bildschirmen: Traenen laufen, aber er laechelt. Goldene Visualisierung "
               "spiegelt in seinen Augen. Belichtung wechselt von kaltem Blau zu warmem Bernstein.",
     "chars": ["ison"], "duration_sec": 15},

    {"id": "K5.4", "chapter": "Kap. 5: Der erste Blick", "title": "Schwarze SUVs",
     "tool": "sora",
     "prompt": "Draussen: Zwei schwarze SUVs fahren langsam die Auffahrt hoch. "
               "Scheinwerfer durchschneiden Morgendaemmerung.",
     "chars": [], "duration_sec": 10},

    # KAPITEL 9
    {"id": "K9.2", "chapter": "Kap. 9: Projekt Phoenix", "title": "Thornes Pressestatement",
     "tool": "digen",
     "prompt": "Thorne auf Podium mit Wissenschaftlern aus 5 Nationen: "
               "'Phoenix ist keine Waffe. Es ist eine Plattform.'",
     "chars": ["thorne"], "duration_sec": 18},

    # KAPITEL 10
    {"id": "K10.1", "chapter": "Kap. 10: Die wachsende Bluete", "title": "Phoenix im Orbit",
     "tool": "sora",
     "prompt": "Phoenix im Orbit: Zeitraffer. Fraktal bluetenvoll entfaltet neue Module "
               "wie kristalline Blume. Sonnenlicht bricht in Strukturen, Regenboegen im Weltraum.",
     "chars": [], "duration_sec": 20},

    {"id": "K10.3", "chapter": "Kap. 10: Die wachsende Bluete", "title": "Signal nach Theta Cygni",
     "tool": "sora",
     "prompt": "Thorne zu Ison: 'Phoenix sendet ein Signal -- nicht zur Erde -- ins All. "
               "Theta Cygni.' Panoramafenster mit Phoenix-Reflektion.",
     "chars": ["thorne", "ison"], "duration_sec": 15},

    # KAPITEL 14
    {"id": "K14.2", "chapter": "Kap. 14: Die Kapsel", "title": "Ison beruehrt die Kapsel",
     "tool": "runway",
     "prompt": "Ison tritt ein und beruehrt ovale Codexium-Kapsel. Oberflaechle oeffnet sich "
               "wie Bluete. Goldenes Licht pulsiert von innen.",
     "chars": ["ison"], "duration_sec": 15},

    {"id": "K14.4", "chapter": "Kap. 14: Die Kapsel", "title": "Subjektive Erleuchtung",
     "tool": "runway",
     "prompt": "SUBJEKTIV (Isons Sicht): Licht kommt von innen. Er wird zum Fraktal. "
               "DNA-Struktur, erste Aminosaeuren im Urmeer, Urknall. Alles ein einziger Ton. "
               "Uebergang Gold zu Weiss.",
     "chars": ["ison"], "duration_sec": 25},

    {"id": "K14.6", "chapter": "Kap. 14: Die Kapsel", "title": "Isons Statement",
     "tool": "digen",
     "prompt": "Ison vor Kamera: 'Der Codex ist keine Einladung, irgendwohin zu gehen. "
               "Es ist eine Einladung, das zu werden, was wir immer waren. "
               "Der naechste Schritt ist kein Ort. Es ist ein Ton.'",
     "chars": ["ison"], "duration_sec": 20},

    # KAPITEL 15
    {"id": "K15.1", "chapter": "Kap. 15: Das neue Rauschen", "title": "Unter der Milchstrasse",
     "tool": "sora",
     "prompt": "Ison und Elara auf Decke in Feld. Ueber ihnen Milchstrasse mit Phoenix "
               "als heller Stern. Friedliche Nacht.",
     "chars": ["ison", "elara"], "duration_sec": 20},

    {"id": "K15.3", "chapter": "Kap. 15: Das neue Rauschen", "title": "Hoerst du es",
     "tool": "digen",
     "prompt": "Ison fluestert: 'Hoerst du es?' Elara lauscht. Sie hoert es -- nicht mit den Ohren, "
               "sondern mit dem Teil, der immer wusste, mehr zu sein.",
     "chars": ["ison", "elara"], "duration_sec": 18},

    # EPILOG
    {"id": "E1", "chapter": "Epilog", "title": "Die ewige Melodie",
     "tool": "seedance",
     "prompt": "Abstrakte Abschlussvisualisierung: Alle Fraktale, DNA-Straenge, Sterne "
               "verschmelzen zu einer einzigen pulsierenden Melodie. Gold-Weiss-Zyan. "
               "Langsames Ausblenden.",
     "chars": [], "duration_sec": 30},

    # ── Fehlende scenes from Erweiterung3 ─────────────────────────────────

    {"id": "K5.3", "chapter": "Kap. 5: Der erste Blick", "title": "Hand beruehrt Bildschirm",
     "tool": "seedance",
     "prompt": "Nahaufnahme: Isons Hand beruehrt den Bildschirm. DNA-Straenge verwandeln "
               "sich in leuchtende lebendige Fraktale. Goldene Bernstein-Toene.",
     "chars": ["ison"], "duration_sec": 12},

    {"id": "K6.1", "chapter": "Kap. 6: Der schalldichte Raum", "title": "Weisser Isolationsraum",
     "tool": "runway",
     "prompt": "Ison sitzt in weissem schalldichten Raum. Keine Fenster, nur Metalltisch und Lampe. "
               "Gesicht zeigt pure Qual — Tinnitus unertraeglich.",
     "chars": ["ison"], "duration_sec": 14},

    {"id": "K6.2", "chapter": "Kap. 6: Der schalldichte Raum", "title": "Thorne und Nazari treten ein",
     "tool": "sora",
     "prompt": "Tuer oeffnet sich. Thorne tritt ein, gefolgt von Nazari. Lichtkegel fallen "
               "in den Raum, dramatische Silhouette. Low-Key-Lighting.",
     "chars": ["thorne", "nazari"], "duration_sec": 12},

    {"id": "K6.3", "chapter": "Kap. 6: Der schalldichte Raum", "title": "Wessen Signatur",
     "tool": "digen",
     "prompt": "Nazari haelt Tablet mit pulsierendem Fraktal: "
               "'Sie haben eine Signatur gefunden, Mr. Willis. Wessen Signatur?'",
     "chars": ["nazari"], "duration_sec": 15},

    {"id": "K7.1", "chapter": "Kap. 7: Das globale Echo", "title": "Weltweite Nachrichtensprecher",
     "tool": "digen",
     "prompt": "Montage: Nachrichtensprecher in USA, China, Deutschland, Indien. "
               "Schlagzeile: 'DIE SIGNATUR IM LEBEN'. Fraktale auf Bildschirmen weltweit.",
     "chars": [], "duration_sec": 18},

    {"id": "K7.2", "chapter": "Kap. 7: Das globale Echo", "title": "Nobelpreistraeger",
     "tool": "runway",
     "prompt": "Alter Nobelpreistraeger betrachtet Daten. Runzelt Stirn, weitet Augen. "
               "Greift zum Telefon. Generisches Labor.",
     "chars": [], "duration_sec": 12},

    {"id": "K7.3", "chapter": "Kap. 7: Das globale Echo", "title": "Vatikan Kardinal",
     "tool": "sora",
     "prompt": "Vatikan: Kardinal im Purpurgewand betrachtet Fraktal auf Tablet. "
               "Neben ihm Galilei-Statue. Er macht Kreuzzeichen. Kerzenlicht.",
     "chars": [], "duration_sec": 14},

    {"id": "K7.4", "chapter": "Kap. 7: Das globale Echo", "title": "Krakau Cafe",
     "tool": "seedance",
     "prompt": "Krakau Cafe: Mann (Marek) uebertraegt Fraktal in Noten. Spielt Melodie "
               "auf Klavier-Tablet. Junge Frau hoert zu, Traenen. Warmes Cafe-Licht.",
     "chars": [], "duration_sec": 18},

    {"id": "K8.1", "chapter": "Kap. 8: Die zweite Sitzung", "title": "Ison im Verhoerraum",
     "tool": "sora",
     "prompt": "Ison zurueck im Verhoerraum. Thorne ruhiger, Nazari traegt Datenstick.",
     "chars": ["ison", "thorne"], "duration_sec": 12},

    {"id": "K8.2", "chapter": "Kap. 8: Die zweite Sitzung", "title": "Zweite Visualisierung",
     "tool": "runway",
     "prompt": "Neben Isons Fraktal zweite identische Visualisierung — von 34 Instituten "
               "bestaetigt. 'Es ist unbestreitbar.'",
     "chars": ["nazari"], "duration_sec": 14},

    {"id": "K8.3", "chapter": "Kap. 8: Die zweite Sitzung", "title": "Einladungsrede",
     "tool": "digen",
     "prompt": "Ison: 'Es ist eine Einladung. Entweder entwickeln wir uns weiter. "
               "Oder wir bleiben Kinder mit kaputtem Spielzeug.' Nahaufnahme.",
     "chars": ["ison"], "duration_sec": 18},

    {"id": "K9.1", "chapter": "Kap. 9: Projekt Phoenix", "title": "Colorado Forschungszentrum",
     "tool": "sora",
     "prompt": "Drei Monate spaeter: Ison und Elara in gesichertem Forschungszentrum "
               "in Colorado-Bergen. Ison an Touchscreen mit Fraktal und technischen Zeichnungen.",
     "chars": ["ison", "elara"], "duration_sec": 15},

    {"id": "K9.3", "chapter": "Kap. 9: Projekt Phoenix", "title": "Syntheseprotokolle",
     "tool": "runway",
     "prompt": "Nazari per Videokonferenz: 'Syntheseprotokolle fertig. Materialien heilen sich "
               "selbst. Save Daten auf atomarer Ebene.'",
     "chars": ["nazari"], "duration_sec": 15},

    {"id": "K10.2", "chapter": "Kap. 10: Die wachsende Bluete", "title": "Ison without Kopfhoerer",
     "tool": "runway",
     "prompt": "Ison in Houston vor Panoramafenster. Phoenix reflektiert in Glasscheibe. "
               "Er traegt keine Noise-Cancelling-Kopfhoerer mehr.",
     "chars": ["ison"], "duration_sec": 12},

    {"id": "K11.1", "chapter": "Kap. 11: Der Ton hinter dem Ton", "title": "Codexium Wuerfel",
     "tool": "seedance",
     "prompt": "Phoenix Synthese-Kammer C-1: Transparenter Wuerfel aus Codexium schwebt. "
               "Im Inneren tanzen Lichtpunkte wie Sterne.",
     "chars": [], "duration_sec": 15},

    {"id": "K11.2", "chapter": "Kap. 11: Der Ton hinter dem Ton", "title": "Nazari beruehrt Wuerfel",
     "tool": "runway",
     "prompt": "Nazari beruehrt Codexium-Wuerfel — warm wie lebendige Haut. LYRAs holografisches "
               "Fraktal erscheint und kommuniziert mit der Kammer.",
     "chars": ["nazari"], "duration_sec": 15},

    {"id": "K11.3", "chapter": "Kap. 11: Der Ton hinter dem Ton", "title": "Signal ins All",
     "tool": "sora",
     "prompt": "Phoenix-Signal breitet sich als Schallwelle durch Weltraum aus. "
               "Sterne funkeln. Neon-Zyan fuer das Signal.",
     "chars": [], "duration_sec": 14},

    {"id": "K12.1", "chapter": "Kap. 12: Die Wahl", "title": "UN-Vollversammlung",
     "tool": "digen",
     "prompt": "UN-Vollversammlung: Delegierte im Halbkreis. Fraktal auf Leinwand. "
               "Diplomat: 'Wer diese Signatur hinterlassen hat, koennte zurueckkehren.'",
     "chars": [], "duration_sec": 18},

    {"id": "K12.2", "chapter": "Kap. 12: Die Wahl", "title": "Isons UN-Rede",
     "tool": "runway",
     "prompt": "Ison erhebt sich: 'Die Absicht war nicht Zerstoerung. Signatur ist seit "
               "Milliarden Jahren eingraviert. Sie haetten uns laengst zerstoeren koennen.'",
     "chars": ["ison"], "duration_sec": 18},

    {"id": "K12.3", "chapter": "Kap. 12: Die Wahl", "title": "Abstimmung",
     "tool": "sora",
     "prompt": "Haende heben sich. Nicht einstimmig, aber entscheidend. "
               "Die Menschheit wird zuhoeren.",
     "chars": [], "duration_sec": 12},

    {"id": "K13.1", "chapter": "Kap. 13: Die Resonanz", "title": "Fraktale in Farnen",
     "tool": "runway",
     "prompt": "Phoenix Bio-Lebensraum: Farne bilden Fraktalmuster — Fibonacci-Spiralen "
               "mit Praezision, die keine natuerliche Art zeigt.",
     "chars": [], "duration_sec": 16},

    {"id": "K13.2", "chapter": "Kap. 13: Die Resonanz", "title": "Kristallnetzwerk",
     "tool": "seedance",
     "prompt": "Schweizer Labor: Technikerin betrachtet Kaffeebecher. Ueber Nacht entstand "
               "feines Kristallnetzwerk auf der Glasur — exakt das Ison-Fraktal.",
     "chars": [], "duration_sec": 14},

    {"id": "K13.3", "chapter": "Kap. 13: Die Resonanz", "title": "Traumsequenz",
     "tool": "runway",
     "prompt": "Ison schlaeft. Traumsequenz: Er ist das Fraktal selbst, entfaltet und faltet "
               "sich in unendlichen Iterationen. Nur stille Gewissheit.",
     "chars": ["ison"], "duration_sec": 20},

    {"id": "K14.1", "chapter": "Kap. 14: Die Kapsel", "title": "Kapsel fertig",
     "tool": "sora",
     "prompt": "Phoenix Synthese-Kammer: Ovaler Codexium-Behaelter schwebt. Keine Naehte, "
               "keine Bedienelemente. Nahtlose lebendige Oberflaeche. Gold-Toene.",
     "chars": [], "duration_sec": 15},

    {"id": "K14.3", "chapter": "Kap. 14: Die Kapsel", "title": "Ison steigt ein",
     "tool": "seedance",
     "prompt": "Ison steigt in die Kapsel. Bluete schliesst sich. Absolute Stille. "
               "Zum ersten Mal seit 25 Jahren: kein Tinnitus.",
     "chars": ["ison"], "duration_sec": 15},

    {"id": "K14.5", "chapter": "Kap. 14: Die Kapsel", "title": "Ison tritt heraus",
     "tool": "sora",
     "prompt": "Ison tritt aus der Kapsel. Nazari und Team warten angespannt. "
               "Nur Minuten vergangen. Fuer Ison eine Ewigkeit. Er laechelt friedlich.",
     "chars": ["ison", "nazari"], "duration_sec": 15},

    {"id": "K15.2", "chapter": "Kap. 15: Das neue Rauschen", "title": "Herzschlag synchronisiert",
     "tool": "runway",
     "prompt": "Ison und Elara im Gespraech. Kopf auf seiner Brust. Herzschlag synchronisiert "
               "sich mit Phoenix-Puls, Summen der Erde, fernem Chor der Sterne.",
     "chars": ["ison", "elara"], "duration_sec": 18},

    {"id": "E2", "chapter": "Epilog", "title": "Fremder Planet",
     "tool": "runway",
     "prompt": "Fremder Planet in Orion-Arm-Region. Nichtmenschliches Wesen vor eigener "
               "Phoenix-Version — riesige wirbelnde Kristallstruktur. Signal ausgesendet.",
     "chars": [], "duration_sec": 20},

    {"id": "E3", "chapter": "Epilog", "title": "Signal erreicht Sonnensystem",
     "tool": "seedance",
     "prompt": "Signal erreicht Sonnensystem. Harmonie veraendert sich subtil — macht "
               "Platz fuer neue grandioese Stimme. Neon-Zyan-Wellen.",
     "chars": [], "duration_sec": 18},

    {"id": "E4", "chapter": "Epilog", "title": "Leeres Notenblatt",
     "tool": "sora",
     "prompt": "Letzte Einstellung: Leeres Notenblatt. Erste Note erscheint. "
               "Die Musik beginnt von Neuem. Weiss auf Schwarz.",
     "chars": [], "duration_sec": 15},
]


# ─────────────────────────────────────────────────────────────────────────────
# SCRIPT SUPERVISOR — Dynamic scene list
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_SCRIPT_SUPERVISOR = """You are a script supervisor for AI film production.

TASK:
Break the following narrative text into individual, filmable scenes.
Apply BALANCED segmentation — not too granular, not too coarse.

SEGMENTATION RULES:
- Location change = new scene
- Time jump = new scene
- Change in character constellation = new scene
- Each chapter = 2-5 scenes depending on length
- One scene can encompass multiple connected actions
- Emotional turning points or revelation moments = new scene

TARGET: 40-60 scenes for a full novel. Quality over quantity.

VISUAL DNA (embed in every prompt):
- Color palette: Dark blue (#0A192F), Amber (#FDB827), Neon cyan (#00E5FF), Gold (#FFD700)
- Lighting: "Cinematic Noir with Volumetric Light, strong shadows, blue-orange contrasts"
- Camera: "Close-ups for intimacy, flying camera for digital worlds, wide angle for power structures"

TOOL ASSIGNMENT:
- sora: wide shots, landscapes, exteriors, large spaces
- runway: abstract visualizations, fractals, data streams, dream sequences
- digen: dialogues, press conferences, multi-character conversations
- seedance: atmospheric transitions, nature, mood
- comfyui_local: local GPU rendering — use when no external API available

OUTPUT FORMAT (JSON array, one object per scene):
[
  {
    "id": "S01",
    "chapter": "Chapter name or Main Part",
    "title": "Short title max 6 words",
    "chars": ["CharacterName1"],
    "duration_sec": 12,
    "tool": "sora",
    "prompt": "Detailed English scene description with lighting style, camera, colors"
  }
]

RULES:
- Return ONLY the JSON array, no additional text, no markdown backticks.
- Number of scenes is dynamic — target 40-60 for a full novel.
- Prompts in English.
- Embed visual DNA in every prompt.
- DO NOT over-segment — combine related moments into one scene.

HERE IS THE TEXT TO PROCESS:
"""

# Active scene list — can be swapped at runtime via Script Supervisor import
# Initialised from imported JSON if available, else falls back to SCENES default
_active_scenes: list = []


def _get_active_scenes() -> list:
    """Returns the currently active scene list (imported or default SCENES)."""
    return _active_scenes if _active_scenes else SCENES


def _load_active_scenes(storage_root: str) -> list:
    """Loads imported scenes from config/szenen_importiert.json if it exists.
    Returns the loaded list, or empty list if not found (caller falls back to SCENES).
    """
    path = os.path.join(storage_root, "config", "szenen_importiert.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and data:
            return data
    except Exception:
        pass
    return []


def _save_active_scenes(storage_root: str, scenes: list):
    """Persists the active scene list to config/szenen_importiert.json."""
    os.makedirs(os.path.join(storage_root, "config"), exist_ok=True)
    path = os.path.join(storage_root, "config", "szenen_importiert.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(scenes, f, indent=2, ensure_ascii=False)


def _save_default_scenes(storage_root: str):
    """Writes the built-in SCENES list to config/szenen_default.json (once)."""
    os.makedirs(os.path.join(storage_root, "config"), exist_ok=True)
    path = os.path.join(storage_root, "config", "szenen_default.json")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(SCENES, f, indent=2, ensure_ascii=False)


def _validate_and_fix_scenes(raw: list) -> list:
    """Validates and fixes a raw scene list from LLM output.

    Applies defaults for missing fields, reassigns IDs if non-unique,
    normalises tool names, and returns the cleaned list.
    """
    VALID_TOOLS = {"sora", "runway", "digen", "seedance", "myedit", "suno", "capcut",
                   "comfyui_local"}
    seen_ids    = set()
    result      = []

    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", f"S{i+1:02d}")).strip()
        if sid in seen_ids or not sid:
            sid = f"S{i+1:02d}"
        seen_ids.add(sid)

        tool = str(item.get("tool", "sora")).lower().strip()
        if tool not in VALID_TOOLS:
            tool = "sora"

        try:
            dur = int(item.get("duration_sec", 12))
            dur = max(5, min(60, dur))
        except (ValueError, TypeError):
            dur = 12

        chars = item.get("chars", [])
        if not isinstance(chars, list):
            chars = []
        chars = [str(c).lower().strip() for c in chars if c]

        result.append({
            "id":           sid,
            "chapter":      str(item.get("chapter", "Hauptteil")).strip(),
            "title":        str(item.get("title",   "Szene")).strip(),
            "chars":        chars,
            "duration_sec": dur,
            "tool":         tool,
            "prompt":       str(item.get("prompt",  "")).strip(),
        })

    return result


# Worker definitions with delegation rules
WORKERS = [
    {"type": "sora",    "name": "Sora 2 (Bing)", "url": "https://api.bing.com/videos/sora2",
     "capabilities": ["cinematic", "wide_angle", "landscapes"],
     "when": "Hauptszenen, Weitwinkel, Landschaften, Natur"},
    {"type": "runway",  "name": "Runway ML", "url": "https://api.runwayml.com/v1",
     "capabilities": ["abstract", "fractal", "dreamlike"],
     "when": "Fraktale, Traumsequenzen, Datenvisualisierung, Abstrakt"},
    {"type": "seedance","name": "Seedance 2.0", "url": "https://api.seedance.ai/v2",
     "capabilities": ["atmospheric", "integrated_audio", "nature"],
     "when": "Stimmung, Uebergaenge, Natur -- integriertes Audio"},
    {"type": "digen",   "name": "Digen (CapCut)", "url": "http://localhost:3000/api/digen",
     "capabilities": ["avatars", "dialogue", "multilingual"],
     "when": "Dialoge, KI-Avatare, Pressekonferenzen, Nachrichtensprecher"},
    {"type": "myedit",  "name": "MyEdit TTS", "url": "https://api.myedit.ai/tts",
     "capabilities": ["narration", "german", "emotional"],
     "when": "Erzaehlstimme, Voice-over (Deutsch, emotional)"},
    {"type": "suno",    "name": "Suno Music", "url": "https://api.suno.ai/v1",
     "capabilities": ["soundtrack", "ambient", "theme"],
     "when": "Hintergrundmusik, Titelthema, Ambient"},
    {"type": "capcut",  "name": "CapCut Editor", "url": "http://localhost:3001/api/capcut",
     "capabilities": ["editing", "sync", "export"],
     "when": "Finaler Schnitt (NUR am Ende, wenn alle Clips fertig)"},
    # ── Local ComfyUI (kein API-Key noetig, laeuft lokal auf Lyra) ──────────
    {"type": "comfyui_local", "name": "ComfyUI Local (WAN 2.1)", "url": "http://127.0.0.1:8188",
     "capabilities": ["cinematic", "wide_angle", "atmospheric", "abstract"],
     "when": "Lokale Videogenerierung ohne API-Key — WAN 2.1 1.3B auf eigener GPU"},
]

CHARACTERS = {
    "ison":   {"name": "Big Willis (Ison)",    "desc": "Mann Mitte 40, introvertierter Wissenschaftler, dunkles Arbeitszimmer"},
    "elara":  {"name": "Elara Willis",          "desc": "Frau Ende 30, warme besorgte Augen, Neurochirurgin"},
    "thorne": {"name": "General Marcus Thorne", "desc": "Amerikanischer General Ende 50, kantiges Gesicht, War Room"},
    "nazari": {"name": "Prof. Kira Nazari",     "desc": "Amerikanisch-iranische Wissenschaftlerin, Genetiklabor"},
}


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCTION LOGIC (headless, no tkinter dependency)
# ─────────────────────────────────────────────────────────────────────────────

def _kill_comfyui_port(port: int = 8188, log_cb=None) -> None:
    """Beendet alle Prozesse auf dem ComfyUI-Port (Modul-Ebene, kein self).

    Kann von statischen Methoden (_install_comfyui) UND Instanzmethoden
    (_kill_comfyui_on_port) aufgerufen werden.

    Strategie:
      1. wmic — findet python.exe mit 'main.py' + 'ComfyUI' im CommandLine
      2. netstat -ano — alle PIDs auf dem Port (alle TCP-States)
      3. taskkill /F fuer jeden gefundenen PID
      4. Socket-Test bis Port wirklich frei (max 5s)
    """
    log = log_cb or (lambda m, l="INFO": None)
    if sys.platform != "win32":
        return

    pids: set[int] = set()

    # wmic: python.exe mit ComfyUI main.py im CommandLine
    try:
        r = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe' or name='pythonw.exe'",
             "get", "ProcessId,CommandLine", "/format:csv"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in r.stdout.decode(errors="replace").splitlines():
            lo = line.lower()
            if "main.py" in lo and ("comfyui" in lo or str(port) in lo):
                parts = line.strip().split(",")
                try:
                    pid = int(parts[-1].strip())
                    if pid > 4:
                        pids.add(pid)
                except (ValueError, IndexError):
                    pass
    except Exception:
        pass

    # netstat: alle PIDs auf Port (LISTEN, ESTABLISHED, TIME_WAIT, ...)
    try:
        r = subprocess.run(
            ["netstat", "-ano"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        for line in r.stdout.decode(errors="replace").splitlines():
            if f":{port}" in line:
                parts = line.strip().split()
                if parts:
                    try:
                        pid = int(parts[-1])
                        if pid > 4:
                            pids.add(pid)
                    except ValueError:
                        pass
    except Exception:
        pass

    # Alle gefundenen PIDs beenden
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            log(f"[ComfyUI] PID {pid} auf Port {port} beendet ✓", "INFO")
        except Exception:
            pass

    if not pids:
        return

    # Warten bis Port wirklich frei ist (max 5s)
    import socket as _sock
    for _ in range(10):
        time.sleep(0.5)
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(0.3)
            result = s.connect_ex(("127.0.0.1", port))
            s.close()
            if result != 0:
                break
        except Exception:
            break
    log(f"[ComfyUI] Port {port} freigegeben ✓", "INFO")


class ProductionOrchestrator:
    """LYRA as Cinematic Coordinator -- empfaengt, speichert, verteilt, trackt.

    DeepSeek (Ison) liefert kreative Prompts und Qualitaetsentscheidungen.
    LYRA (diese Klasse) orchestriert die Workers und verwaltet den Status.
    """

    def __init__(self, storage_root: str, workers: list = None,
                 log_cb=None, dry_run: bool = False, refresh_cb=None):
        """
        Args:
            storage_root: Base directory for all production assets.
            workers:      Agent list from workers.json (API keys included).
                          If None, tries to load from ~/.openclaw/workers.json.
            log_cb:       Callable(msg, level) for log output.
            dry_run:      If True, simulate API calls without real HTTP.
            refresh_cb:   Optional callable fired after each scene to refresh GUI.
        """
        self.storage_root = storage_root
        # Load workers from file if not provided
        if workers is None:
            try:
                p = os.path.join(os.path.expanduser("~"), ".openclaw", "workers.json")
                with open(p, "r", encoding="utf-8") as f:
                    workers = json.load(f)
            except Exception:
                workers = []
        self._workers         = workers
        # Assign log callback FIRST so self.log() works in all subsequent code
        self._log_cb    = log_cb or (lambda m, l="INFO": print(f"[{l}] {m}"))
        self._refresh_cb = refresh_cb
        self.dry_run          = dry_run
        self._status          = {}
        self._lock            = threading.Lock()
        self._stop            = threading.Event()
        # Workers that failed this session — skipped for remaining scenes.
        # Cleared on each new run_production() call.
        self._skipped_workers: set = set()
        # Referenz auf laufenden ComfyUI-Subprozess (None = nicht gestartet)
        self._comfyui_process: subprocess.Popen | None = None
        # Build availability lookup: worker type -> usable
        # Local workers (localhost/127.0.0.1) need no API key
        self._api_keys        = {
            w.get("type", ""): w.get("api_key", "")
            for w in workers
        }
        self._worker_available = {
            w.get("type", ""): (
                any(x in w.get("url","") for x in ["localhost","127.0.0.1"])
                or bool(w.get("api_key","").strip())
            )
            for w in workers
        }
        # Find DeepSeek key: search by URL (api.deepseek.com) not just type
        self.deepseek_api_key = ""
        for w in workers:
            url = w.get("url", "")
            key = w.get("api_key", "").strip()
            if key and ("deepseek" in url.lower() or w.get("type","") in ("openai","deepseek")):
                self.deepseek_api_key = key
                self.log(f"[Producer] DeepSeek key found via worker: {w.get('name','?')} "
                          f"({url}) — key: {key[:6]}***", "INFO")
                break
        if not self.deepseek_api_key:
            self.deepseek_api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            if self.deepseek_api_key:
                self.log("[Producer] DeepSeek key loaded from env DEEPSEEK_API_KEY", "INFO")
            else:
                self.log("[Producer] DeepSeek key NOT found in workers.json or env "
                          "— prompt enhancement disabled", "WARNING")

    def log(self, msg: str, level: str = "INFO"):
        """Thread-safe log output via callback."""
        self._log_cb(msg, level)

    # ── Directory setup ────────────────────────────────────────────────────────

    def setup_dirs(self):
        """Creates the full LyraFilmProduction directory tree."""
        dirs = [
            os.path.join(self.storage_root, "config"),
            os.path.join(self.storage_root, "characters"),
            os.path.join(self.storage_root, "style"),
            os.path.join(self.storage_root, "audio", "dialoge"),
            os.path.join(self.storage_root, "audio", "musik"),
            os.path.join(self.storage_root, "edit", "raw"),
            os.path.join(self.storage_root, "edit", "timeline"),
            os.path.join(self.storage_root, "edit", "final"),
            os.path.join(self.storage_root, "logs"),
        ]
        for scene in _get_active_scenes():
            for worker in ["sora", "runway", "seedance", "digen", "myedit"]:
                dirs.append(os.path.join(self.storage_root, "szenen", scene["id"], worker))
        for d in dirs:
            os.makedirs(d, exist_ok=True)
        self.log(f"Directories created under {self.storage_root}", "SUCCESS")

    # ── Config file generation ─────────────────────────────────────────────────

    def write_production_config(self):
        """Writes lyra_production_config.json with all 28 scenes + audio + final_cut."""
        config = {
            "project":                "ison_codex_der_film",
            "version":                APP_VERSION,
            "created":                datetime.datetime.now().isoformat(),
            "target_duration_minutes": 45,
            "output": os.path.join(self.storage_root, "edit", "final",
                                   "ison_codex_der_film.mp4"),
            "visual_identity": {
                "color_palette":   VISUAL_DNA["color_palette"],
                "lighting_style":  VISUAL_DNA["lighting_style"],
                "camera_style":    VISUAL_DNA["camera_style"],
                "characters":      {
                    k: os.path.join(self.storage_root, "characters", f"{k}_1.png")
                    for k in CHARACTERS
                },
            },
            "scenes": [
                {
                    "id":           s["id"],
                    "chapter":      s["chapter"],
                    "title":        s["title"],
                    "duration_sec": s["duration_sec"],
                    "tool":         s["tool"],
                    "prompt":       s["prompt"],
                    "chars":        s["chars"],
                    "output": os.path.join(self.storage_root, "szenen", s["id"],
                                           s["tool"], "clip_001.mp4"),
                    "status":       "pending",
                    "deepseek_approved": False,
                }
                for s in SCENES
            ],
            "audio": {
                "narrative_voice": {
                    "tool":        "myedit",
                    "voice_style": "warm, deutsch, erwachsen, leicht melancholisch",
                    "output":      os.path.join(self.storage_root, "audio", "narration.mp3"),
                    "status":      "pending",
                },
                "soundtrack": {
                    "tool":             "suno",
                    "style":            "ambient, cinematic, melancholisch mit hoffnungsvollem Ende",
                    "duration_minutes": 45,
                    "output":           os.path.join(self.storage_root, "audio", "musik",
                                                     "soundtrack.mp3"),
                    "status":           "pending",
                },
            },
            "final_cut": {
                "tool":   "capcut",
                "output": os.path.join(self.storage_root, "edit", "final",
                                       "ison_codex_der_film.mp4"),
                "status": "pending",
            },
        }
        path = os.path.join(self.storage_root, "config", "lyra_production_config.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        self.log(f"Production config written: {path}", "SUCCESS")
        return config

    def write_workers_config(self, api_keys: dict):
        """Writes workers.json with all cinematic workers + DeepSeek as director."""
        workers = []
        for w in WORKERS:
            entry = dict(w)
            entry["api_key"] = api_keys.get(w["type"], "")
            workers.append(entry)

        # DeepSeek as the creative director
        workers.insert(0, {
            "type":     "openai",
            "name":     "DeepSeek (Ison -- Creative Director)",
            "url":      DEFAULT_DEEPSEEK_URL,
            "model":    "deepseek-chat",
            "api_key":  api_keys.get("deepseek", self.deepseek_api_key),
            "role":     "director",
            "capabilities": ["creative_prompting", "analysis", "quality_control"],
            "delegation_rules": (
                "WANN: Jede kreative Prompt-Verbesserung, Qualitaetspruefung, Stil-Entscheidung\n"
                "NICHT: Ausfuehrung, Speicherung, Worker-Koordination\n"
                "GRUND: DeepSeek = Ison (kreativ, analytisch). LYRA = Proxy + Speicher."
            ),
        })

        # Save to production config dir
        path = os.path.join(self.storage_root, "config", "workers_cinematic.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(workers, f, indent=2, ensure_ascii=False)
        self.log(f"Cinematic workers config: {path}", "SUCCESS")
        return workers

    def write_visual_bible(self):
        """Writes stil/production_handbook.txt with the visual DNA reference."""
        bible = f"""# Visual Production Handbook -- Ison-Codex Film
# Generated by IsonCodexProducer.py v{APP_VERSION}
# ALL AI TOOLS MUST USE THIS REFERENCE CONSISTENTLY.

## Color Palette
  Dunkelblau (Hintergrund):  #0A192F
  Bernstein (Signatur/Ison): #FDB827
  Neon-Zyan (LYRA):          #00E5FF
  Goldgelb (Fraktal-Hoehepunkte): #FFD700

## Lighting Style
  Cinematic Noir mit Volumetrischem Licht
  Starke Schatten, Blau-Orange Kontraste
  Leichter Lens Flare bei Schluesselmomenten
  Referenz: Blade Runner 2049 Cinematography

## Camerastil
  Nahaufnahmen     -> Intimitaet, Emotionen
  Fliegende Kamera -> Datenwelten, Fraktale, digitale Raeume
  Statischer Weitwinkel -> Machtstrukturen, Institutionen
  Referenz: Mr. Robot Kameraarbeit (ungewoehnliche Kadrierungen)

## Characters
  Ison Willis:       Muede aber entschlossen, dunkles Arbeitszimmer, blaues Monitorlicht
  Elara Willis:      Warm, besorgt, Kerzenlicht-Atmosphaere
  General Thorne:    Eiskalte Praezision, War Room, Low-Key-Lighting
  Prof. Kira Nazari: Forschend, Genetiklabor, gruenes Datenlicht

## Signatur-Visualisierung
  Goldene Fibonacci-Spiralen und Fraktale
  Pulsierendes goldenes Licht (#FDB827)
  Uebergang: Kaltes Blau -> Warmes Bernstein = Erkenntnis-Moment

## Music Style
  Ambient, cinematic, melancholisch mit hoffnungsvollem Ende
  Langsam aufbauend, Moll -> Dur beim Erkenntnis-Moment
  Kein moderner Pop -- zeitlos, klassisch-elektronisch
"""
        path = os.path.join(self.storage_root, "style", "production_handbook.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(bible)
        self.log(f"Visual Bible written: {path}", "SUCCESS")

    def write_screenplay(self):
        """Writes the full screenplay as screenplay.txt for TTS narration."""
        lines = [
            "# SCREENPLAY -- THE ISON CODEX",
            "# Generated by IsonCodexProducer.py",
            "# Template for MyEdit TTS -- Narration Voice",
            "",
        ]
        for s in _get_active_scenes():
            lines.append(f"## {s['chapter']} -- {s['title']}")
            lines.append("")
            lines.append(s["prompt"][:200] + "...")
            lines.append("")
        path = os.path.join(self.storage_root, "audio", "screenplay.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        self.log(f"Screenplay written: {path}", "SUCCESS")

    # ── Status tracking ────────────────────────────────────────────────────────

    def load_status(self) -> dict:
        """Loads production_status.json if it exists, else returns empty dict."""
        path = os.path.join(self.storage_root, "config", "production_status.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"scenes": {}, "audio": {}, "started": None}

    def save_status(self, status: dict):
        """Persists production_status.json."""
        path = os.path.join(self.storage_root, "config", "production_status.json")
        with self._lock:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)

    def write_log(self, message: str, level: str = "INFO"):
        """Appends a timestamped entry to the production log file."""
        ts    = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        day   = datetime.datetime.now().strftime("%Y-%m-%d")
        path  = os.path.join(self.storage_root, "logs", f"production_{day}.log")
        entry = f"[{ts}] [{level}] {message}\n"
        try:
            with self._lock:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(entry)
        except Exception:
            pass

    # ── DeepSeek integration ───────────────────────────────────────────────────

    def request_enhanced_prompt(self, scene: dict) -> str:
        """Asks DeepSeek to enhance the base prompt with visual DNA context.

        In dry_run mode returns the original prompt unchanged.
        """
        if self.dry_run:
            self.log(f"[DeepSeek] dry_run=True — using base prompt for {scene['id']}", "INFO")
            return scene["prompt"]
        if not self.deepseek_api_key:
            self.log(f"[DeepSeek] No API key — using base prompt for {scene['id']}", "WARNING")
            return scene["prompt"]
        self.log(f"[DeepSeek] Enhancing prompt for {scene['id']} ({scene['title']})...", "INFO")
        try:
            import urllib.request, urllib.error
            char_descs = "; ".join(
                CHARACTERS[c]["desc"] for c in scene.get("chars", [])
                if c in CHARACTERS
            )
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Du bist der kreative Direktor des Films 'Der Ison-Codex'. "
                        f"Verbessere diesen Kamera-Prompt fuer {scene['tool'].upper()} "
                        f"(Szene {scene['id']}: {scene['title']}):\n\n"
                        f"Basis-Prompt: {scene['prompt']}\n\n"
                        f"Characters: {char_descs or 'keine'}\n"
                        f"Visuelle DNA:\n"
                        f"  Lichtstil: {VISUAL_DNA['lighting_style']}\n"
                        f"  Kamera: {VISUAL_DNA['camera_style']}\n\n"
                        f"Antworte NUR mit dem verbesserten Prompt (max. 200 Woerter, Englisch fuer KI-Tools)."
                    )
                }],
                "temperature": 0.7,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{DEFAULT_DEEPSEEK_URL}/chat/completions",
                data=payload,
                headers={
                    "Content-Type":  "application/json",
                    "Authorization": f"Bearer {self.deepseek_api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.load(resp)
                enhanced = data["choices"][0]["message"]["content"].strip()
                self.log(f"[DeepSeek] Enhanced prompt received ({len(enhanced)} chars) ✓", "SUCCESS")
                return enhanced
        except Exception as e:
            self.log(f"[DeepSeek] Prompt enhancement failed: {e} — using base prompt", "WARNING")
            return scene["prompt"]

    def submit_for_quality_check(self, scene_id: str, output_path: str) -> dict:
        """Sends completed scene path to DeepSeek for approval.

        Returns {"approved": bool, "notes": str, "revised_prompt": str|None}.
        In dry_run mode always approves.
        """
        if self.dry_run or not self.deepseek_api_key:
            return {"approved": True, "notes": "dry-run auto-approved", "revised_prompt": None}
        # Real implementation would send file URL or description
        return {"approved": True, "notes": "manual review required", "revised_prompt": None}

    # ── Scene production ───────────────────────────────────────────────────────

    def generate_scene(self, scene: dict, status: dict) -> bool:
        """Orchestrates production of one scene.

        1. Enhance prompt via DeepSeek
        2. Write prompt.txt
        3. In non-dry-run: would call worker API
        4. Mark status
        Returns True on success.
        """
        sid = scene["id"]
        # ── Skip check: prompt already exists? Clips already exist? ──────────
        prompt_path = os.path.join(self.storage_root, "szenen", sid, "prompt.txt")
        clip_dir    = os.path.join(self.storage_root, "szenen", sid, scene["tool"])
        clip_count  = 0
        if os.path.isdir(clip_dir):
            clip_count = sum(1 for f in os.listdir(clip_dir)
                             if f.endswith(".mp4") or f.endswith(".mp4.placeholder"))

        if os.path.isfile(prompt_path):
            if clip_count > 0:
                self.log(f"[Scene {sid}] SKIP — {clip_count} clip(s) already exist (scene complete).", "INFO")
                with self._lock:
                    status["scenes"][sid] = {
                        "status":     "complete",
                        "clip_count": clip_count,
                        "timestamp":  "existing",
                    }
                self.save_status(status)
                return True
            # Prompt exists — check if Enhanced Prompt section is already filled
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    existing_content = f.read()
                has_enhanced = (
                    "## Enhanced Prompt (DeepSeek)" in existing_content
                    and "(Noch kein Enhanced Prompt" not in existing_content
                    and len(existing_content.split("## Enhanced Prompt (DeepSeek)")[-1].strip()) > 20
                )
            except Exception:
                has_enhanced = False

            if has_enhanced:
                if self.dry_run:
                    self.log(f"[Scene {sid}] SKIP — Enhanced prompt exists, dry run active.", "INFO")
                    with self._lock:
                        status["scenes"][sid] = {
                            "status":      "prompt_ready",
                            "title":       scene["title"],
                            "tool":        scene["tool"],
                            "prompt_path": prompt_path,
                            "timestamp":   "existing",
                        }
                    self.save_status(status)
                    return True
                # Not dry run — enhanced exists but no clip yet: delegate to worker
                self.log(f"[Scene {sid}] Enhanced prompt found — delegating to {scene['tool']}...", "INFO")
                try:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    enhanced = content.split("## Enhanced Prompt (DeepSeek)")[-1]
                    enhanced = enhanced.split("## Visual DNA")[0].strip()
                except Exception:
                    enhanced = scene["prompt"]
                prompt_dir = os.path.join(self.storage_root, "szenen", sid, scene["tool"])
                os.makedirs(prompt_dir, exist_ok=True)
                worker = self._find_video_worker(scene["tool"])
                if worker is None:
                    self.log(f"[Scene {sid}] SKIP — no worker configured for tool '{scene['tool']}'.", "WARNING")
                    scene_status = "skipped_no_worker"
                else:
                    clip_path = self._call_video_worker(
                        sid, enhanced, scene["duration_sec"], scene["tool"], worker, prompt_dir)
                    scene_status = "complete" if clip_path else "skipped_api_error"
                with self._lock:
                    status["scenes"][sid] = {
                        "status":      scene_status,
                        "title":       scene["title"],
                        "tool":        scene["tool"],
                        "prompt_path": prompt_path,
                        "timestamp":   datetime.datetime.now().isoformat(),
                    }
                self.save_status(status)
                return True
            else:
                # prompt.txt exists but Enhanced section missing or empty
                # — call DeepSeek and update the file
                self.log(f"[Scene {sid}] Prompt exists but no Enhanced section — calling DeepSeek.", "INFO")

        self.log(f"[Scene {sid}] Starting: {scene['title']} ({scene['tool']})", "INFO")
        self.write_log(f"Scene {sid} started: {scene['title']}", "INFO")
        self.log(f"[Scene {sid}] DeepSeek available: {bool(self.deepseek_api_key)} | "
                  f"dry_run: {self.dry_run}", "INFO")

        # Step 1: enhance prompt via DeepSeek
        enhanced = self.request_enhanced_prompt(scene)

        # Step 2: write prompt.txt
        prompt_dir  = os.path.join(self.storage_root, "szenen", sid, scene["tool"])
        prompt_path = os.path.join(self.storage_root, "szenen", sid, "prompt.txt")
        os.makedirs(prompt_dir, exist_ok=True)
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(f"# Scene {sid}: {scene['title']}\n")
            f.write(f"# Tool: {scene['tool']}\n")
            f.write(f"# Duration: {scene['duration_sec']}s\n")
            f.write(f"# Characters: {', '.join(scene['chars']) or 'none'}\n\n")
            f.write(f"## Base Prompt\n{scene['prompt']}\n\n")
            f.write(f"## Enhanced Prompt (DeepSeek)\n{enhanced}\n\n")
            f.write(f"## Visual DNA\n")
            for k, v in VISUAL_DNA.items():
                f.write(f"  {k}: {v}\n")

        # Step 3: delegate to video worker (or dry run)
        if self.dry_run:
            out_path = os.path.join(prompt_dir, "clip_001.mp4.placeholder")
            with open(out_path, "w") as f:
                f.write(f"DRY RUN -- would generate {scene['duration_sec']}s clip\n")
                f.write(f"Tool: {scene['tool']}\n")
                f.write(f"Prompt: {enhanced[:100]}...\n")
            self.log(f"[Scene {sid}] DRY RUN -- placeholder created ✓", "SUCCESS")
            scene_status = "dry_run_complete"
        else:
            worker = self._find_video_worker(scene["tool"])
            if worker is None:
                self.log(f"[Scene {sid}] SKIP — no worker configured for tool '{scene['tool']}'.", "WARNING")
                scene_status = "skipped_no_worker"
            else:
                clip_path = self._call_video_worker(
                    sid, enhanced, scene["duration_sec"], scene["tool"], worker, prompt_dir)
                if clip_path:
                    scene_status = "complete"
                else:
                    scene_status = "skipped_api_error"

        # Update status
        with self._lock:
            status["scenes"][sid] = {
                "status":      scene_status,
                "title":       scene["title"],
                "tool":        scene["tool"],
                "prompt_path": prompt_path,
                "timestamp":   datetime.datetime.now().isoformat(),
            }
        self.save_status(status)
        self.write_log(f"Scene {sid} done: {scene_status}", "SUCCESS")
        return True

    def _find_video_worker(self, tool_name: str) -> dict | None:
        """Returns the first worker matching tool_name that is not blacklisted.

        Für comfyui_local: Kein workers.json-Eintrag noetig — Worker wird
        direkt aus der globalen WORKERS-Konstante synthetisiert, da kein
        API-Key benoetigt wird und ComfyUI lokal laeuft.
        """
        tool = tool_name.lower().strip()

        # ── comfyui_local: immer verfuegbar, kein API-Key noetig ─────────────
        if tool == "comfyui_local":
            key = "comfyui_local"
            if key in self._skipped_workers:
                return None
            # Suche zuerst in workers.json (falls manuell eingetragen)
            for w in self._workers:
                if w.get("type", "").lower() == "comfyui_local":
                    return w
            # Fallback: synthetisierter Worker aus WORKERS-Konstante
            for w in WORKERS:
                if w.get("type", "").lower() == "comfyui_local":
                    return dict(w)  # Kopie, nicht Original mutieren
            # Absoluter Fallback (ComfyUI Standard-Port)
            return {"type": "comfyui_local", "name": "ComfyUI Local (WAN 2.1)",
                    "url": "http://127.0.0.1:8188", "api_key": ""}

        # ── Alle anderen Worker: aus workers.json ────────────────────────────
        for w in self._workers:
            wtype = w.get("type", "").lower()
            wname = w.get("name", "").lower()
            if tool in wtype or tool in wname:
                key = w.get("name", w.get("url", tool))
                if key in self._skipped_workers:
                    return None  # already failed this session
                return w
        return None

    def _call_video_worker(self, sid: str, prompt: str, duration: int,
                           tool: str, worker: dict, out_dir: str) -> str | None:
        """Sends a video generation request to the worker API.

        Handles three response patterns:
          sync:  {"status": "success", "url": "http://...clip.mp4"}
          async: {"status": "pending", "job_id": "abc123"} -> polls /status/{job_id}
          error: {"error": "..."} or HTTP error

        For comfyui_local: delegates directly to _call_comfyui_worker().

        Returns local clip path on success, None on failure/skip.
        """
        # ── ComfyUI local dispatch (kein API-Key, eigener Workflow-Pfad) ─────
        if worker.get("type", "").lower() == "comfyui_local":
            return self._call_comfyui_worker(sid, prompt, duration, out_dir)

        import urllib.request, urllib.error, time

        url = worker.get("url", "").rstrip("/")
        key = worker.get("api_key", "").strip()
        model = worker.get("model", "")

        if not url:
            self.log(f"[Scene {sid}] SKIP — worker '{worker.get('name','?')}' has no URL.", "WARNING")
            return None

        # Build request
        endpoint = url + "/generate"
        body = {
            "prompt":       prompt,
            "duration_sec": duration,
            "scene_id":     sid,
        }
        if model:
            body["model"] = model

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        self.log(f"[Scene {sid}] Sending to {worker.get('name','?')} ({endpoint})...", "INFO")

        try:
            payload = json.dumps(body).encode("utf-8")
            req     = urllib.request.Request(endpoint, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            wkey = worker.get("name", worker.get("url", "?"))
            self.log(f"[Scene {sid}] SKIP — {worker.get('name','?')} HTTP {e.code}: {e.reason}. "
                     f"Worker blacklisted for this session.", "WARNING")
            self._skipped_workers.add(wkey)
            return None
        except urllib.error.URLError as e:
            wkey = worker.get("name", worker.get("url", "?"))
            self.log(f"[Scene {sid}] SKIP — {worker.get('name','?')} unreachable: {e.reason}. "
                     f"Worker blacklisted for this session.", "WARNING")
            self._skipped_workers.add(wkey)
            return None
        except Exception as e:
            self.log(f"[Scene {sid}] SKIP — {worker.get('name','?')} error: {e}.", "WARNING")
            return None

        # Handle async job
        if data.get("status") == "pending" and "job_id" in data:
            job_id   = data["job_id"]
            poll_url = url + f"/status/{job_id}"
            self.log(f"[Scene {sid}] Job queued ({job_id}) — polling {poll_url}...", "INFO")
            max_wait = 600  # 10 minutes
            interval = 10
            waited   = 0
            while waited < max_wait:
                time.sleep(interval)
                waited += interval
                try:
                    with urllib.request.urlopen(poll_url, timeout=30) as r:
                        data = json.loads(r.read().decode("utf-8"))
                except Exception as e:
                    self.log(f"[Scene {sid}] Poll error: {e} — retrying...", "WARNING")
                    continue
                pstatus = data.get("status", "")
                self.log(f"[Scene {sid}] Poll {waited}s: {pstatus}", "INFO")
                if pstatus == "success":
                    break
                if pstatus in ("error", "failed"):
                    self.log(f"[Scene {sid}] SKIP — job failed: {data.get('error','unknown')}.", "WARNING")
                    return None
            else:
                self.log(f"[Scene {sid}] SKIP — timeout after {max_wait}s waiting for clip.", "WARNING")
                return None

        # Handle error response
        if "error" in data:
            self.log(f"[Scene {sid}] SKIP — {worker.get('name','?')} error: {data['error']}.", "WARNING")
            return None

        if data.get("status") not in ("success", "complete", "done"):
            self.log(f"[Scene {sid}] SKIP — unexpected response status: {data.get('status')}.", "WARNING")
            return None

        # Download clip
        clip_url = data.get("url") or data.get("clip_url") or data.get("output_url")
        if not clip_url:
            self.log(f"[Scene {sid}] SKIP — no clip URL in response.", "WARNING")
            return None

        clip_path = os.path.join(out_dir, "clip_001.mp4")
        self.log(f"[Scene {sid}] Downloading clip from {clip_url}...", "INFO")
        try:
            urllib.request.urlretrieve(clip_url, clip_path)
            self.log(f"[Scene {sid}] ✅ Clip saved: {clip_path}", "SUCCESS")
            return clip_path
        except Exception as e:
            self.log(f"[Scene {sid}] SKIP — download failed: {e}.", "WARNING")
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # COMFYUI LOCAL WORKER  (neu in v1.1.0 -- bestehende Worker unberuehrt)
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_comfyui_workflow(self, prompt: str, duration_sec: int,
                                out_dir: str, sid: str = "scene") -> dict:
        """Laed ein JSON-Workflow-Template und setzt Prompt + Output-Pfad ein.

        Sucht das Template in folgender Reihenfolge:
          1. <storage_root>/config/comfyui_workflow_template.json
          2. <storage_root>/../comfyui_workflow_template.json  (Projektroot)
          3. Eingebettetes Minimal-WAN-2.1-Template als Fallback

        Args:
            prompt:       Verbesserter Szenen-Prompt.
            duration_sec: Videodauer in Sekunden (wird in Frames umgerechnet).
            out_dir:      Ausgabeverzeichnis fuer den generierten Clip.

        Returns:
            Workflow-Dict, bereit fuer POST an ComfyUI /prompt.
        """
        # Moegl. Template-Pfade
        candidates = [
            os.path.join(self.storage_root, "config", "comfyui_workflow_template.json"),
            os.path.join(os.path.dirname(self.storage_root),
                         "comfyui_workflow_template.json"),
        ]
        workflow = None
        for tpl_path in candidates:
            if os.path.isfile(tpl_path):
                try:
                    with open(tpl_path, "r", encoding="utf-8") as f:
                        workflow = json.load(f)
                    self.log(f"[ComfyUI] Workflow-Template geladen: {tpl_path}", "INFO")
                    break
                except Exception as e:
                    self.log(f"[ComfyUI] Template-Ladefehler {tpl_path}: {e}", "WARNING")

        if workflow is None:
            # Eingebettetes Minimal-Template fuer WAN 2.1 1.3B (Text2Video)
            # Verwendet ComfyUI-native WAN-Nodes (kein CheckpointLoaderSimple!)
            # Modell liegt in models/diffusion_models/, T5 in models/text_encoders/
            self.log("[ComfyUI] Kein Template gefunden — nutze eingebettetes WAN-2.1-Minimal-Workflow.", "INFO")
            fps = 16
            # WAN 2.1 1.3B Hardware-Limit auf RTX 3050 (6GB VRAM):
            # Max 81 Frames @ 480p = 81/16 = ~5.1 Sekunden pro Render
            # Fuer laengere Szenen (z.B. 18s) werden mehrere Clips gerendert
            # und spaeter in CapCut zusammengeschnitten.
            # WAN 2.1 5B wuerde laengere Sequenzen erlauben, braucht aber >8GB VRAM.
            MAX_WAN_FRAMES = 81   # Hardware-Grenze RTX 3050 6GB @ 480p
            raw_frames = duration_sec * fps
            wan_frames = max(17, min(MAX_WAN_FRAMES, int(raw_frames)))
            # WAN erwartet Frames in Form 4k+1: 17, 21, 25, ..., 81
            wan_frames = ((wan_frames - 1) // 4) * 4 + 1
            num_frames = wan_frames
            actual_secs = num_frames / fps
            if actual_secs < duration_sec - 1:
                self.log(
                    f"[ComfyUI] ⚠️  Szene {duration_sec}s → WAN 1.3B-Limit: {actual_secs:.1f}s "
                    f"({num_frames} Frames @ {fps}fps). "
                    f"Fuer volle {duration_sec}s: {int(duration_sec/actual_secs)+1} Clips noetig.",
                    "WARNING"
                )
            else:
                self.log(f"[ComfyUI] Frames: {num_frames} @ {fps}fps = {actual_secs:.1f}s", "INFO")

            # Bestimme Dateiname: bf16 bevorzugt, fp16 als Fallback
            project_root   = os.path.dirname(os.path.normpath(self.storage_root))
            comfyui_dir    = os.path.join(project_root, "ComfyUI-Portable")
            diff_models    = os.path.join(comfyui_dir, "models", "diffusion_models")
            model_bf16     = "wan2.1_t2v_1.3B_bf16.safetensors"
            model_fp16     = "wan2.1_t2v_1.3B_fp16.safetensors"
            if os.path.isfile(os.path.join(diff_models, model_bf16)):
                diffusion_model = model_bf16
            else:
                diffusion_model = model_fp16  # Fallback

            # T5 Text Encoder — ersten verfuegbaren in models/text_encoders/ suchen
            t5_dir_wf  = os.path.join(comfyui_dir, "models", "text_encoders")
            t5_encoder = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"  # bevorzugt
            if not os.path.isfile(os.path.join(t5_dir_wf, t5_encoder)):
                # Alternativen suchen (fp16, bf16, andere Namen)
                t5_alternatives = [
                    "umt5_xxl_fp16.safetensors",
                    "umt5-xxl-enc-bf16.safetensors",
                    "umt5_xxl_bf16.safetensors",
                ]
                for alt in t5_alternatives:
                    if os.path.isfile(os.path.join(t5_dir_wf, alt)):
                        t5_encoder = alt
                        break
                else:
                    # Erste .safetensors Datei im Ordner nehmen
                    try:
                        found = [f for f in os.listdir(t5_dir_wf) if f.endswith(".safetensors")]
                        if found:
                            t5_encoder = found[0]
                    except Exception:
                        pass

            # WAN VAE — ersten verfuegbaren in models/vae/ suchen
            vae_dir_wf = os.path.join(comfyui_dir, "models", "vae")
            wan_vae    = "wan_2.1_vae.safetensors"
            if not os.path.isfile(os.path.join(vae_dir_wf, wan_vae)):
                try:
                    found_vae = [f for f in os.listdir(vae_dir_wf)
                                 if f.endswith(".safetensors") and "wan" in f.lower()]
                    if found_vae:
                        wan_vae = found_vae[0]
                    else:
                        all_vae = [f for f in os.listdir(vae_dir_wf) if f.endswith(".safetensors")]
                        if all_vae:
                            wan_vae = all_vae[0]
                except Exception:
                    pass

            self.log(f"[ComfyUI] Workflow: diffusion={diffusion_model}", "INFO")
            self.log(f"[ComfyUI] Workflow: t5={t5_encoder}", "INFO")
            self.log(f"[ComfyUI] Workflow: vae={wan_vae}", "INFO")

            workflow = {
                # Node 1: Lade WAN Diffusion Model
                "1": {
                    "class_type": "UNETLoader",
                    "inputs": {
                        "unet_name": diffusion_model,
                        "weight_dtype": "default"
                    }
                },
                # Node 2: Lade T5 Text Encoder
                "2": {
                    "class_type": "CLIPLoader",
                    "inputs": {
                        "clip_name": t5_encoder,
                        "type": "wan"
                    }
                },
                # Node 3: Lade WAN VAE
                "3": {
                    "class_type": "VAELoader",
                    "inputs": {
                        "vae_name": wan_vae
                    }
                },
                # Node 4: Positiver Prompt (wird durch Szenen-Prompt ersetzt)
                "4": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["2", 0],
                        "text": "__PROMPT__"
                    }
                },
                # Node 5: Negativer Prompt
                "5": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {
                        "clip": ["2", 0],
                        "text": "blurry, low quality, watermark, text, distorted, ugly, worst quality"
                    }
                },
                # Node 6: Leeres Latent Video
                "6": {
                    "class_type": "EmptyHunyuanLatentVideo",
                    "inputs": {
                        "width":      848,
                        "height":     480,
                        "length":     num_frames,
                        "batch_size": 1
                    }
                },
                # Node 7: KSampler (WAN nutzt FlowMatch / euler)
                "7": {
                    "class_type": "KSampler",
                    "inputs": {
                        "model":         ["1", 0],
                        "positive":      ["4", 0],
                        "negative":      ["5", 0],
                        "latent_image":  ["6", 0],
                        "seed":          42,
                        "steps":         20,
                        "cfg":           6.0,
                        "sampler_name":  "euler",
                        "scheduler":     "simple",
                        "denoise":       1.0
                    }
                },
                # Node 8: VAE Decode
                "8": {
                    "class_type": "VAEDecode",
                    "inputs": {
                        "samples": ["7", 0],
                        "vae":     ["3", 0]
                    }
                },
                # Node 9: Video als MP4 speichern via VHS_VideoCombine
                # (ComfyUI-VideoHelperSuite — bereits installiert)
                "9": {
                    "class_type": "VHS_VideoCombine",
                    "inputs": {
                        "images":          ["8", 0],
                        "frame_rate":      fps,
                        "loop_count":      0,
                        "filename_prefix": "ison_clip",
                        "format":          "video/h264-mp4",
                        "save_output":     True,
                        "pingpong":        False,
                        "save_metadata":   False
                    }
                }
            }

        # Prompt in alle CLIPTextEncode-Nodes einsetzen (positiver Text)
        # Ersetzt __PROMPT__ oder den ersten positiven CLIPTextEncode-Eintrag
        prompt_injected = False
        for node_id, node in workflow.items():
            if node.get("class_type") == "CLIPTextEncode":
                txt = node.get("inputs", {}).get("text", "")
                if "__PROMPT__" in str(txt):
                    node["inputs"]["text"] = prompt
                    prompt_injected = True

        if not prompt_injected:
            # Fallback: ersten CLIPTextEncode-Node ueberschreiben
            for node_id, node in workflow.items():
                if node.get("class_type") == "CLIPTextEncode":
                    node["inputs"]["text"] = prompt
                    prompt_injected = True
                    break

        # Output-Pfad-Setzer:
        # ComfyUI erlaubt KEINEN Pfad ausserhalb seines output/-Ordners.
        # Loesung: kurzen Prefix nutzen (bleibt in output/), Datei nach Render verschieben.
        scene_prefix = f"lyra_{sid}"   # eindeutig pro Szene, bleibt in output/
        for node_id, node in workflow.items():
            if node.get("class_type") in (
                "VHS_VideoCombine", "SaveVideo", "VideoSave",
                "SaveAnimatedWEBP", "SaveAnimatedPNG", "SaveImage",
            ):
                node["inputs"]["filename_prefix"] = scene_prefix

        return workflow

    def _kill_comfyui_on_port(self, port: int = 8188):
        """Beendet alle ComfyUI-Prozesse auf dem Port. Delegiert an _kill_comfyui_port()."""
        # Eigenen gespeicherten Prozess zuerst beenden
        if self._comfyui_process is not None:
            try:
                if self._comfyui_process.poll() is None:
                    self._comfyui_process.terminate()
                    try:
                        self._comfyui_process.wait(timeout=5)
                    except Exception:
                        self._comfyui_process.kill()
                    self.log(f"[ComfyUI] Alter Prozess (PID {self._comfyui_process.pid}) beendet.", "INFO")
            except Exception:
                pass
            self._comfyui_process = None
        # Modul-Funktion fuer Rest (wmic + netstat + taskkill)
        _kill_comfyui_port(port, log_cb=self.log)

    def _start_comfyui_process(self) -> bool:
        """Startet ComfyUI als Hintergrundprozess und streamt dessen Logs ins GUI.

        Sucht das richtige Python (venv > System-Python mit torch > sys.executable).
        Fuehrt vor dem Start einen Diagnose-Check durch und zeigt Fehler sofort an.
        Startet ohne eigenes Consolefenster (Windows: CREATE_NO_WINDOW).

        Returns:
            True  wenn Prozess gestartet.
            False wenn ComfyUI-Ordner fehlt oder Startfehler.
        """
        # ── ComfyUI-Verzeichnis ermitteln ─────────────────────────────────────
        project_root = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        main_py      = os.path.join(comfyui_dir, "main.py")

        if not os.path.isfile(main_py):
            self.log(
                "[ComfyUI] ComfyUI-Ordner nicht gefunden.\n"
                f"  Erwartet: {comfyui_dir}\n"
                "  → Klick auf '🖥️ Install ComfyUI' um ComfyUI zu installieren.",
                "WARNING"
            )
            return False

        # ── Richtiges Python bestimmen ────────────────────────────────────────
        # Prioritaet: venv > System-Python das torch kennt > sys.executable
        python_exe = None

        # 1. venv-Python (bevorzugt — isolierte Installation)
        venv_py = os.path.join(comfyui_dir, "venv", "Scripts", "python.exe")
        if os.path.isfile(venv_py):
            python_exe = venv_py
            self.log(f"[ComfyUI] Nutze venv-Python: {venv_py}", "INFO")

        # 2. System-Python das torch importieren kann
        if not python_exe:
            for cand in [
                sys.executable,
                os.path.join(os.path.dirname(sys.executable), "python.exe"),
            ]:
                if not cand or not os.path.isfile(cand):
                    continue
                try:
                    result = subprocess.run(
                        [cand, "-c", "import torch; print('ok')"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, cwd=comfyui_dir,
                    )
                    if result.returncode == 0:
                        python_exe = cand
                        self.log(f"[ComfyUI] Nutze System-Python (torch gefunden): {cand}", "INFO")
                        break
                except Exception:
                    continue

        # 3. sys.executable als letzter Ausweg
        if not python_exe:
            python_exe = sys.executable
            self.log(f"[ComfyUI] Nutze sys.executable als Fallback: {python_exe}", "WARNING")

        # ── Diagnose-Check: main.py kurz testen (gibt Importfehler sofort aus) ─
        self.log("[ComfyUI] Diagnose: prüfe Python-Umgebung...", "INFO")
        try:
            diag = subprocess.run(
                [python_exe, "-c",
                 "import sys; sys.path.insert(0, '.'); "
                 "import importlib; "
                 "[importlib.import_module(m) for m in "
                 "['torch', 'numpy', 'PIL', 'aiohttp']];"
                 "print('OK')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=15, cwd=comfyui_dir,
            )
            if diag.returncode == 0:
                self.log("[ComfyUI] Diagnose: torch/numpy/PIL/aiohttp OK ✓", "SUCCESS")
            else:
                err = diag.stderr.decode(errors="replace").strip()
                out = diag.stdout.decode(errors="replace").strip()
                self.log(f"[ComfyUI] ⚠️  Diagnose: fehlende Abhaengigkeiten!", "WARNING")
                if err:
                    # Ersten relevanten Fehler extrahieren
                    for line in err.splitlines():
                        if line.strip():
                            self.log(f"  {line}", "WARNING")
                if out:
                    self.log(f"  stdout: {out}", "INFO")
                self.log(
                    "[ComfyUI] Tipp: requirements manuell installieren:\n"
                    f"  {python_exe} -m pip install -r {os.path.join(comfyui_dir, 'requirements.txt')}",
                    "WARNING"
                )
        except Exception as e:
            self.log(f"[ComfyUI] Diagnose-Check fehlgeschlagen: {e}", "WARNING")

        # ── Prozess starten ───────────────────────────────────────────────────
        # Schritt 0: Alten ComfyUI-Prozess auf Port 8188 beenden
        self._kill_comfyui_on_port(8188)

        # CUDA-Verfuegbarkeit pruefen — falls nicht vorhanden: --cpu Flag setzen
        cuda_available = False
        try:
            cuda_check = subprocess.run(
                [python_exe, "-c",
                 "import torch; print(torch.cuda.is_available())"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, cwd=comfyui_dir,
            )
            cuda_available = cuda_check.stdout.decode(errors="replace").strip() == "True"
        except Exception:
            pass

        if cuda_available:
            self.log("[ComfyUI] CUDA verfuegbar ✓ — starte mit GPU-Unterstuetzung.", "SUCCESS")
        else:
            self.log(
                "[ComfyUI] ⚠️  CUDA nicht verfuegbar — starte im CPU-Modus (langsam!).",
                "WARNING"
            )

        # Eindeutige DB-Datei pro Instanz (verhindert SQLite-Lock bei Mehrfachstart)
        db_path = os.path.join(comfyui_dir, "user", "comfyui_lyra.db")
        cmd = [python_exe, "main.py", "--listen", "--port", "8188",
               "--database-url", f"sqlite:///{db_path}",
               ]  # PYTHONIOENCODING env loest tqdm stderr OSError
        if not cuda_available:
            cmd.append("--cpu")

        self.log(f"[ComfyUI] Starte: {' '.join(cmd)}", "INFO")

        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            # PYTHONIOENCODING=utf-8 gibt original_stderr ein gueltiges Encoding.
            # Ohne dies schlaegt tqdm/ComfyUI-Manager mit OSError [Errno 22] fehl.
            # ComfyUI-Manager patcht stderr (prestartup_script.py:336) — tqdm
            # versucht dann flush() auf dem gepatchten Stream → OSError auf Windows-Pipes.
            comfyui_env = os.environ.copy()
            comfyui_env["PYTHONIOENCODING"]          = "utf-8"
            comfyui_env["PYTHONLEGACYWINDOWSSTDIO"]  = "0"
            comfyui_env["PYTHONUNBUFFERED"]          = "1"
            comfyui_env["NO_COLOR"]                  = "1"   # tqdm: kein ANSI → kein flush-Problem
            comfyui_env["TERM"]                      = "dumb" # tqdm: kein interaktives Terminal
            comfyui_env["FORCE_COLOR"]               = "0"

            proc = subprocess.Popen(
                cmd,
                cwd           = comfyui_dir,
                stdout        = subprocess.PIPE,
                stderr        = subprocess.STDOUT,  # stderr in stdout mergen
                bufsize       = 1,
                creationflags = creation_flags,
                encoding      = "utf-8",
                errors        = "replace",
                env           = comfyui_env,
            )
        except Exception as e:
            self.log(f"[ComfyUI] Popen fehlgeschlagen: {e}", "ERROR")
            return False

        self._comfyui_process = proc
        self.log(f"[ComfyUI] Prozess gestartet (PID {proc.pid}) ✓", "SUCCESS")

        # ── Log-Stream-Thread ─────────────────────────────────────────────────
        def _stream_logs():
            try:
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    lo = line.lower()

                    # Bekannte harmlose Meldungen herausfiltern (kein Render-Problem)
                    _noise_patterns = (
                        "an error occurred while fetching",   # ComfyUI-Manager API-Fetch
                        "expecting value: line 1 column 1",   # leere HTTP-Antwort
                        "cannot connect to comfyregistry",    # Registry offline
                        "due to a network error, switching to local mode",
                        "cannot schedule new futures after shutdown",
                        "a new release of pip is available",
                        "to update, run: python",
                        "ignoring invalid distribution",
                        "logging failed: [winerror 32]",      # log-Datei gesperrt
                        "default cache updated:",              # ComfyUI-Manager Cache-Updates
                        "addedtoken(",                        # Tokenizer-Dump (256299 Zeilen)
                        "extra_id_",                          # T5-Tokenizer special tokens
                        "rstrip=false, lstrip=false",         # Tokenizer-Metadaten
                        "single_word=false, normalized=false", # Tokenizer-Metadaten
                    )
                    # Sehr lange Zeilen (>500 Zeichen) die keinen Fehler enthalten unterdrücken
                    if len(lo) > 500 and not any(w in lo for w in ("error", "exception", "traceback")):
                        level = "INFO"
                        lo = lo[:200] + f"... [+{len(lo)-200} Zeichen gekürzt]"
                    if any(p in lo for p in _noise_patterns):
                        level = "INFO"  # als INFO statt WARNING/ERROR
                    elif any(w in lo for w in ("error", "exception", "traceback",
                                               "modulenotfounderror", "importerror")):
                        level = "ERROR"
                    elif any(w in lo for w in ("warn", "missing", "failed")):
                        level = "WARNING"
                    elif any(w in lo for w in ("loaded", "ready", "started",
                                               "listening", "to see the gui",
                                               "running on")):
                        level = "SUCCESS"
                    else:
                        level = "INFO"
                    self.log(f"  [ComfyUI] {line}", level)
            except Exception as ex:
                self.log(f"[ComfyUI] Log-Stream-Fehler: {ex}", "WARNING")

            # Prozess ist beendet — Exitcode ausgeben
            rc = proc.poll()
            if rc is not None and rc != 0:
                self.log(
                    f"[ComfyUI] ⚠️  Prozess beendet mit Exit-Code {rc}.\n"
                    "  → Tipp: ComfyUI manuell starten um vollstaendigen Fehler zu sehen:\n"
                    f"  → cd {comfyui_dir}\n"
                    f"  → {python_exe} main.py --listen",
                    "WARNING"
                )
            else:
                self.log("[ComfyUI] Prozess beendet.", "INFO")

        threading.Thread(target=_stream_logs, daemon=True).start()
        return True

    def _ensure_comfyui_running(self, tag: str = "[ComfyUI]") -> bool:
        """Prueft ob ComfyUI erreichbar ist — startet es automatisch falls nicht.

        Ablauf:
          1. Ping GET /system_stats → sofort True wenn erreichbar.
          2. Nicht erreichbar: _start_comfyui_process() aufrufen.
          3. Bis zu 60 Sekunden auf Ready warten (Ping alle 3s).
          4. True wenn ComfyUI innerhalb der Wartezeit antwortet.

        Args:
            tag: Log-Prefix fuer alle Meldungen dieser Methode.

        Returns:
            True wenn ComfyUI erreichbar, False nach Timeout/Startfehler.
        """
        import urllib.request

        COMFYUI_URL = "http://127.0.0.1:8188"

        def _ping() -> bool:
            try:
                with urllib.request.urlopen(
                    f"{COMFYUI_URL}/system_stats", timeout=4
                ) as r:
                    r.read()
                return True
            except Exception:
                return False

        # ── Schritt 1: Sofort-Check ───────────────────────────────────────────
        if _ping():
            self.log(f"{tag} ComfyUI laeuft bereits.", "INFO")
            return True

        # ── Schritt 2: Automatisch starten ───────────────────────────────────
        self.log(f"{tag} ComfyUI nicht erreichbar — starte automatisch...", "INFO")
        if not self._start_comfyui_process():
            return False  # Startfehler bereits geloggt

        # ── Schritt 3: Warten bis Ready (max 60s) ────────────────────────────
        max_wait = 60
        interval = 3
        waited   = 0
        self.log(f"{tag} Warte auf ComfyUI-Start (max {max_wait}s)...", "INFO")

        while waited < max_wait:
            time.sleep(interval)
            waited += interval
            if _ping():
                self.log(f"{tag} ComfyUI bereit nach {waited}s. ✅", "SUCCESS")
                return True
            self.log(f"{tag}   ... {waited}s", "INFO")

        self.log(
            f"{tag} Timeout — ComfyUI nach {max_wait}s noch nicht erreichbar.\n"
            "  Starte ComfyUI manuell und versuche es erneut.",
            "WARNING"
        )
        return False

    def _run_cinematic_audio_pipeline(
        self,
        sid: str,
        video_path: str,
        prompt: str,
        duration_sec: int,
        out_dir: str,
        comfyui_url: str,
        tag: str,
    ) -> str | None:
        """Fuegt Narration + Cinematic Musik zum Video hinzu.

        Pipeline (sequenziell, VRAM-schonend):
          A) TTS-Narration via ComfyUI F5-TTS/ChatterBox (TTS-Audio-Suite)
          B) Cinematic Musik via ComfyUI ACE-Step 1.5
          C) FFmpeg: Video + Narration + Musik → finales MP4

        VRAM-Management: Jeder ComfyUI-Job laeuft separat, Modelle werden
        nach jedem Job entladen. So bleiben 6GB VRAM ausreichend.

        Args:
            sid:          Szenen-ID.
            video_path:   Pfad zum gerenderten Video (MP4/WEBP).
            prompt:       Szenen-Prompt (fuer Musik-Beschreibung).
            duration_sec: Videodauer in Sekunden.
            out_dir:      Ausgabeverzeichnis.
            comfyui_url:  ComfyUI-API-URL.
            tag:          Log-Prefix.

        Returns:
            Pfad zum finalen MP4 mit Audio, oder None bei Fehler.
        """
        import urllib.request, urllib.error, json as _json

        self.log(f"{tag} 🎬 Starte Cinematic Audio Pipeline...", "INFO")

        project_root = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        comfyui_out  = os.path.join(comfyui_dir, "output")

        # ── Hilfsfunktion: ComfyUI-Job abschicken und warten ─────────────────
        def _submit_and_wait(workflow: dict, label: str,
                             max_wait: int = 300) -> dict | None:
            """Sendet Workflow, wartet auf Completion, gibt outputs zurueck."""
            payload = _json.dumps({"prompt": workflow}).encode("utf-8")
            req = urllib.request.Request(
                f"{comfyui_url}/prompt",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    resp = _json.loads(r.read().decode("utf-8"))
            except Exception as e:
                self.log(f"{tag}   [{label}] POST fehlgeschlagen: {e}", "WARNING")
                return None
            pid = resp.get("prompt_id")
            if not pid:
                return None
            self.log(f"{tag}   [{label}] Job {pid[:8]}... gestartet", "INFO")
            waited = 0
            while waited < max_wait:
                time.sleep(5)
                waited += 5
                try:
                    with urllib.request.urlopen(
                        f"{comfyui_url}/history/{pid}", timeout=15
                    ) as r:
                        hist = _json.loads(r.read().decode("utf-8"))
                    if pid in hist:
                        st = hist[pid].get("status", {})
                        if st.get("status_str") in ("error", "failed"):
                            msgs = st.get("messages", [])
                            self.log(f"{tag}   [{label}] Job fehlgeschlagen: {msgs}", "WARNING")
                            return None
                        outputs = hist[pid].get("outputs", {})
                        if outputs:
                            self.log(f"{tag}   [{label}] ✓ fertig nach {waited}s", "SUCCESS")
                            return outputs
                except Exception:
                    pass
            self.log(f"{tag}   [{label}] Timeout nach {max_wait}s", "WARNING")
            return None

        def _find_audio_file(outputs: dict, label: str) -> str | None:
            """Sucht Audio-Datei in ComfyUI-Outputs."""
            for node_out in outputs.values():
                for entry in node_out.get("audio", []):
                    fn = entry.get("filename", "")
                    if fn:
                        sf = entry.get("subfolder", "")
                        p  = os.path.join(comfyui_out, sf, fn) if sf else \
                             os.path.join(comfyui_out, fn)
                        if os.path.isfile(p):
                            return p
            return None

        # ── Schritt A: TTS-Narration ──────────────────────────────────────────
        self.log(f"{tag} A) TTS-Narration (ChatterBox)...", "INFO")
        narration_path = None

        narration_text = prompt[:300].strip()
        if len(prompt) > 300:
            narration_text += "..."

        tts_prefix = f"tts_{sid}"
        # TTS-Audio-Suite Architektur: Engine-Node → UnifiedTTSTextNode → SaveAudio
        # UnifiedTTSTextNode akzeptiert TTS_ENGINE-Objekt (nicht String "engine_type").
        # Korrekte Nodes aus nodes.py:
        #   "ChatterBoxEngineNode"       → TTS_ENGINE Typ
        #   "UnifiedTTSTextNode"         → braucht TTS_ENGINE als Input "TTS_engine"
        tts_workflow = {
            "1": {
                "class_type": "ChatterBoxEngineNode",
                "inputs": {
                    "language":                  "English",
                    "device":                    "auto",
                    "exaggeration":              0.5,
                    "temperature":               0.7,
                    "cfg_weight":                0.5,
                    "crash_protection_template": "none",
                }
            },
            "2": {
                "class_type": "UnifiedTTSTextNode",
                "inputs": {
                    "TTS_engine":    ["1", 0],
                    "text":          narration_text,
                    "narrator_voice": "none",
                    "seed":          42,
                }
            },
            "3": {
                "class_type": "SaveAudio",
                "inputs": {
                    "audio":           ["2", 0],
                    "filename_prefix": tts_prefix,
                }
            }
        }

        tts_outputs = _submit_and_wait(tts_workflow, "TTS", max_wait=3600)   # max 1h
        if tts_outputs:
            narration_path = _find_audio_file(tts_outputs, "TTS")
            if narration_path:
                import shutil as _sha
                local_narr = os.path.join(out_dir, "narration.wav")
                _sha.copy2(narration_path, local_narr)
                narration_path = local_narr
                self.log(f"{tag}   Narration: {local_narr}", "SUCCESS")
            else:
                self.log(f"{tag}   TTS Audio-Datei nicht gefunden.", "WARNING")
        else:
            self.log(f"{tag}   TTS fehlgeschlagen — Video ohne Narration.", "WARNING")

        # ── Schritt B: Cinematic Musik (ACE-Step) ─────────────────────────────
        self.log(f"{tag} B) Cinematic Musik (ACE-Step)...", "INFO")
        music_path = None

        music_prompt = (
            "cinematic noir orchestral score, dark ambient, "
            "volumetric low strings, haunting piano, tension building, "
            "no vocals, film score, Hans Zimmer style"
        )
        music_prefix = f"music_{sid}"

        import re as _re
        sid_digits = _re.sub(r"[^0-9]", "", sid) or "1"
        music_seed  = int(sid_digits[:6])
        music_dur   = min(duration_sec + 2, 30)

        # ComfyUI_ACE-Step (billwuhao): Node-Namen aus ace_step_nodes.py
        # ACEModelLoader → ACEStepGen → SaveAudio
        # ACE-Step: ACEModelLoader braucht 4 separate Checkpoint-Inputs.
        # Die Modell-Dateien werden beim ersten Render automatisch heruntergeladen.
        # Ordnerstruktur: models/TTS/ACE-Step-v1-3.5B/{ace_step_transformer, music_dcae_f8c8, ...}
        project_root_ace = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir_ace  = os.path.join(project_root_ace, "ComfyUI-Portable")
        ace_model_base   = os.path.join(comfyui_dir_ace, "models", "TTS", "ACE-Step-v1-3.5B")

        # Pruefen welche Unter-Ordner vorhanden sind
        def _ace_subfolder(sub: str) -> str:
            """Gibt Unterordner-Namen zurueck wenn vorhanden, sonst leer."""
            path = os.path.join(ace_model_base, sub)
            return sub if os.path.isdir(path) else ""

        ace_dcae     = _ace_subfolder("music_dcae_f8c8")
        ace_vocoder  = _ace_subfolder("music_vocoder")
        ace_step     = _ace_subfolder("ace_step_transformer")
        ace_t5       = _ace_subfolder("umt5-base")

        if not all([ace_dcae, ace_vocoder, ace_step, ace_t5]):
            self.log(
                f"{tag}   ACE-Step Modell-Ordner unvollstaendig — "
                f"Musik wird uebersprungen. Ordner: {ace_model_base}",
                "WARNING"
            )
            music_outputs = None
        else:
            music_workflow = {
                "1": {
                    "class_type": "ACEModelLoader",
                    "inputs": {
                        "dcae_checkpoint":         ace_dcae,
                        "vocoder_checkpoint":      ace_vocoder,
                        "ace_step_checkpoint":     ace_step,
                        "text_encoder_checkpoint": ace_t5,
                        "cpu_offload":   True,
                        "torch_compile": False,
                    }
                },
                "2": {
                    "class_type": "ACEStepGen",
                    "inputs": {
                        "models":         ["1", 0],
                        "prompt":         music_prompt,
                        "lyrics":         "[inst]",
                        # delicious_song: verwendet Node-eigene Default-Parameter.
                        # parameters direkt übergeben ist fehleranfällig wegen API-Versionsunterschieden.
                        # Der Node liest duration etc. aus dem JSON selbst.
                        "delicious_song": "default_1.json",
                        # Nur den Prompt und Seed überschreiben via parameters:
                        "parameters": (
                            f'{{"seed": {music_seed}, '
                            '"use_erg_tag": True, "use_erg_lyric": False, '
                            '"use_erg_diffusion": True}'
                        ),
                    }
                },
                "3": {
                    "class_type": "SaveAudio",
                    "inputs": {
                        "audio":           ["2", 0],
                        "filename_prefix": music_prefix,
                    }
                }
            }
            music_outputs = _submit_and_wait(music_workflow, "ACE-Step Musik", max_wait=14400)  # max 4h
        if music_outputs:
            music_path = _find_audio_file(music_outputs, "Musik")
            if music_path:
                import shutil as _shm
                local_music = os.path.join(out_dir, "music.wav")
                _shm.copy2(music_path, local_music)
                music_path = local_music
                self.log(f"{tag}   Musik: {local_music}", "SUCCESS")
            else:
                self.log(f"{tag}   Musik Audio-Datei nicht gefunden.", "WARNING")
        else:
            self.log(f"{tag}   Musik fehlgeschlagen — Video ohne Musik.", "WARNING")

        # ── Schritt C: FFmpeg-Merge ───────────────────────────────────────────
        if not narration_path and not music_path:
            self.log(f"{tag} Kein Audio generiert — Video ohne Ton.", "INFO")
            return None

        self.log(f"{tag} C) FFmpeg-Merge: Video + Audio...", "INFO")
        final_path = os.path.join(out_dir, "clip_001_final.mp4")

        # FFmpeg-Kommando aufbauen
        cmd = ["ffmpeg", "-y", "-i", video_path]

        if narration_path and music_path:
            # Narration (laut) + Musik (leise im Hintergrund) mischen
            cmd += [
                "-i", narration_path,
                "-i", music_path,
                "-filter_complex",
                f"[1:a]volume=1.0[narr];"           # Narration voll
                f"[2:a]volume=0.25[mus];"            # Musik 25% Lautstaerke
                f"[narr][mus]amix=inputs=2:duration=shortest[aout]",
                "-map", "0:v",
                "-map", "[aout]",
            ]
        elif narration_path:
            cmd += ["-i", narration_path, "-map", "0:v", "-map", "1:a"]
        elif music_path:
            cmd += ["-i", music_path, "-map", "0:v", "-map", "1:a"]

        cmd += [
            "-c:v", "copy",           # Video nicht neu encoden
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",              # Laenge = kuerzeste Spur
            final_path,
        ]

        try:
            import shutil as _shf
            ffmpeg = _shf.which("ffmpeg")
            if not ffmpeg:
                # FFmpeg in ComfyUI-Portable suchen (von VHS installiert)
                ffmpeg_local = os.path.join(comfyui_dir, "venv", "Scripts", "ffmpeg.exe")
                if os.path.isfile(ffmpeg_local):
                    cmd[0] = ffmpeg_local

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            if result.returncode == 0 and os.path.isfile(final_path):
                self.log(f"{tag} ✅ Finales MP4 mit Audio: {final_path}", "SUCCESS")
                return final_path
            else:
                err = result.stderr.decode(errors="replace")[-300:]
                self.log(f"{tag} FFmpeg fehlgeschlagen: {err}", "WARNING")
                return None
        except FileNotFoundError:
            self.log(
                f"{tag} FFmpeg nicht gefunden.\n"
                "  → Installiere FFmpeg: https://ffmpeg.org/download.html\n"
                "  → Oder: pip install imageio-ffmpeg (dann ffmpeg in PATH)",
                "WARNING"
            )
            return None
        except Exception as e:
            self.log(f"{tag} FFmpeg-Fehler: {e}", "WARNING")
            return None

    def _call_comfyui_worker(self, sid: str, prompt: str, duration_sec: int,
                             out_dir: str) -> str | None:
        """Rendert eine Szene ueber eine lokal laufende ComfyUI-Instanz.

        Workflow:
          1. Prueft ob ComfyUI erreichbar ist (GET /system_stats).
          2. Baut den Workflow mit _build_comfyui_workflow().
          3. Sendet POST /prompt.
          4. Pollt GET /history/<prompt_id> bis fertig (max 20 min).
          5. Laedt den fertigen Clip aus ComfyUI-Output-Ordner.

        Args:
            sid:          Szenen-ID (fuer Log-Prefix).
            prompt:       Verbesserter Szenen-Prompt.
            duration_sec: Videodauer in Sekunden.
            out_dir:      Zielordner fuer den heruntergeladenen Clip.

        Returns:
            Lokaler Clip-Pfad (str) bei Erfolg, None bei Fehler.
        """
        import urllib.request
        import urllib.error

        COMFYUI_URL = "http://127.0.0.1:8188"
        TAG         = f"[Scene {sid}][ComfyUI]"

        # ── 1. ComfyUI sicherstellen (automatisch starten falls noetig) ────────
        if not self._ensure_comfyui_running(TAG):
            return None

        self.log(f"{TAG} ComfyUI bereit. Baue Workflow...", "INFO")

        # ── 2. Workflow bauen ─────────────────────────────────────────────────
        workflow = self._build_comfyui_workflow(prompt, duration_sec, out_dir, sid)

        # ── 3. ComfyUI Queue leeren (vorherige Jobs abbrechen) ───────────────
        # Verhindert dass haengende Jobs den neuen Request blockieren.
        try:
            clear_req = urllib.request.Request(
                f"{COMFYUI_URL}/queue",
                data    = json.dumps({"clear": True}).encode("utf-8"),
                headers = {"Content-Type": "application/json"},
                method  = "POST",
            )
            with urllib.request.urlopen(clear_req, timeout=10) as r:
                r.read()
            self.log(f"{TAG} Queue geleert ✓", "INFO")
        except Exception as qe:
            self.log(f"{TAG} Queue-Clear fehlgeschlagen (nicht kritisch): {qe}", "WARNING")

        # Interrupt (bricht laufenden Job ab)
        try:
            int_req = urllib.request.Request(
                f"{COMFYUI_URL}/interrupt",
                data    = b"{}",
                headers = {"Content-Type": "application/json"},
                method  = "POST",
            )
            with urllib.request.urlopen(int_req, timeout=10) as r:
                r.read()
        except Exception:
            pass  # Kein Job laufend — ignorieren

        # Kurz warten bis ComfyUI bereit fuer neuen Job
        time.sleep(2)

        # ── 4. Job abschicken ─────────────────────────────────────────────────
        payload = json.dumps({"prompt": workflow}).encode("utf-8")
        req     = urllib.request.Request(
            f"{COMFYUI_URL}/prompt",
            data    = payload,
            headers = {"Content-Type": "application/json"},
            method  = "POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp_data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Response-Body enthaelt ComfyUI-Fehlermeldung (z.B. node validation)
            try:
                body = e.read().decode("utf-8", errors="replace")
                self.log(f"{TAG} POST /prompt HTTP {e.code}: {e.reason}", "WARNING")
                # JSON-Fehler parsen und strukturiert ausgeben
                try:
                    err_json = json.loads(body)
                    if "error" in err_json:
                        self.log(f"{TAG}   Fehler: {err_json['error']}", "ERROR")
                    if "node_errors" in err_json:
                        for nid, nerr in err_json["node_errors"].items():
                            self.log(f"{TAG}   Node {nid}: {nerr}", "ERROR")
                    if not err_json.get("error") and not err_json.get("node_errors"):
                        self.log(f"{TAG}   Body: {body[:500]}", "WARNING")
                except Exception:
                    self.log(f"{TAG}   Body: {body[:500]}", "WARNING")
            except Exception:
                self.log(f"{TAG} POST /prompt fehlgeschlagen: HTTP {e.code}.", "WARNING")
            return None
        except Exception as e:
            self.log(f"{TAG} POST /prompt fehlgeschlagen: {e}.", "WARNING")
            return None

        prompt_id = resp_data.get("prompt_id")
        if not prompt_id:
            self.log(f"{TAG} Keine prompt_id in Antwort: {resp_data}", "WARNING")
            return None

        self.log(f"{TAG} Job gestartet — prompt_id={prompt_id}", "SUCCESS")

        # ── 5. Polling bis fertig ─────────────────────────────────────────────
        max_wait = 1200   # 20 Minuten
        interval = 8      # alle 8 Sekunden
        waited   = 0

        while waited < max_wait:
            time.sleep(interval)
            waited += interval
            try:
                with urllib.request.urlopen(
                    f"{COMFYUI_URL}/history/{prompt_id}", timeout=15
                ) as r:
                    hist = json.loads(r.read().decode("utf-8"))
            except Exception as e:
                self.log(f"{TAG} Polling-Fehler nach {waited}s: {e} — weiter...", "WARNING")
                continue

            if prompt_id not in hist:
                self.log(f"{TAG} Warte auf Ergebnis... ({waited}s)", "INFO")
                continue

            job_data = hist[prompt_id]
            outputs  = job_data.get("outputs", {})
            status   = job_data.get("status", {})

            # Fehler abfangen
            if status.get("status_str") in ("error", "failed"):
                msgs = status.get("messages", [])
                self.log(f"{TAG} Job fehlgeschlagen: {msgs}", "WARNING")
                return None

            # Erfolgreich: Output-Datei suchen
            # Unterstuetzt: VHS_VideoCombine (gifs/videos), SaveAnimatedWEBP (images),
            # SaveImage (images), und generische filename-Felder.
            clip_filename = None
            clip_subfolder = ""
            for node_id, node_out in outputs.items():
                for key in ("gifs", "videos", "images"):
                    for entry in node_out.get(key, []):
                        fn = entry.get("filename", "")
                        if fn:
                            clip_filename  = fn
                            clip_subfolder = entry.get("subfolder", "")
                            break
                    if clip_filename:
                        break
                if clip_filename:
                    break

            if not clip_filename:
                self.log(f"{TAG} Noch keine Output-Datei nach {waited}s...", "INFO")
                continue

            # ── 5. Datei aus ComfyUI output/ in Szenen-Ordner verschieben ─────
            self.log(f"{TAG} ✅ Render fertig nach {waited}s — '{clip_filename}'", "SUCCESS")

            # ComfyUI speichert in seinem output/-Ordner.
            # Wir ermitteln den Pfad direkt (kein HTTP-Download noetig).
            project_root  = os.path.dirname(os.path.normpath(self.storage_root))
            comfyui_dir   = os.path.join(project_root, "ComfyUI-Portable")
            comfyui_out   = os.path.join(comfyui_dir, "output")
            if clip_subfolder:
                src_path = os.path.join(comfyui_out, clip_subfolder, clip_filename)
            else:
                src_path = os.path.join(comfyui_out, clip_filename)

            ext       = os.path.splitext(clip_filename)[1] or ".webp"
            clip_path = os.path.join(out_dir, f"clip_001{ext}")
            os.makedirs(out_dir, exist_ok=True)

            if os.path.isfile(src_path):
                try:
                    import shutil as _shc
                    _shc.copy2(src_path, clip_path)
                    self.log(f"{TAG} ✅ Video kopiert: {clip_path}", "SUCCESS")

                    # ── Multi-Clip: weitere Clips rendern falls Szene > 5.1s ────
                    MAX_CLIP_SEC = 5.1
                    num_clips_needed = max(1, int(duration_sec / MAX_CLIP_SEC + 0.5))

                    if num_clips_needed > 1 and os.path.isfile(clip_path):
                        self.log(f"{TAG} 📽️  {num_clips_needed} Clips noetig fuer {duration_sec}s — rendere weiter...", "INFO")
                        all_clips = [clip_path]

                        def _render_extra_clip(clip_idx: int) -> str | None:
                            """Rendert einen weiteren Clip und gibt den Pfad zurueck."""
                            sid_n  = f"{sid}_c{clip_idx}"
                            wf_n   = self._build_comfyui_workflow(prompt, duration_sec, out_dir, sid_n)
                            # Seed variieren damit Clips visuell variieren
                            if "7" in wf_n and "inputs" in wf_n.get("7", {}):
                                wf_n["7"]["inputs"]["seed"] = 42 + clip_idx * 1337

                            # POST /prompt
                            try:
                                req_n = urllib.request.Request(
                                    f"{COMFYUI_URL}/prompt",
                                    data    = json.dumps({"prompt": wf_n}).encode("utf-8"),
                                    headers = {"Content-Type": "application/json"},
                                    method  = "POST",
                                )
                                with urllib.request.urlopen(req_n, timeout=30) as r:
                                    pid_n = json.loads(r.read()).get("prompt_id")
                            except Exception as pe:
                                self.log(f"{TAG} Clip {clip_idx} POST fehlgeschlagen: {pe}", "WARNING")
                                return None

                            if not pid_n:
                                return None
                            self.log(f"{TAG} Clip {clip_idx} Job gestartet — {pid_n[:8]}...", "INFO")

                            # Poll /history
                            deadline_n = time.time() + 1200
                            while time.time() < deadline_n:
                                time.sleep(8)
                                try:
                                    with urllib.request.urlopen(f"{COMFYUI_URL}/history/{pid_n}", timeout=15) as r:
                                        hist_n = json.loads(r.read())
                                    if pid_n in hist_n:
                                        msgs_n = hist_n[pid_n].get("status", {}).get("messages", [])
                                        if any(m[0] == "execution_success" for m in msgs_n):
                                            # Output finden
                                            outs_n = hist_n[pid_n].get("outputs", {})
                                            for nid, nout in outs_n.items():
                                                for key in ("gifs", "videos", "images"):
                                                    items = nout.get(key, [])
                                                    if items:
                                                        fn = items[0].get("filename", "")
                                                        sp = os.path.join(comfyui_out, fn)
                                                        if os.path.isfile(sp):
                                                            dst_n = os.path.join(out_dir, f"clip_{clip_idx:03d}.mp4")
                                                            _shc.copy2(sp, dst_n)
                                                            self.log(f"{TAG} ✅ Clip {clip_idx} fertig", "SUCCESS")
                                                            return dst_n
                                        if any(m[0] == "execution_error" for m in msgs_n):
                                            self.log(f"{TAG} ⚠️  Clip {clip_idx} Fehler.", "WARNING")
                                            return None
                                except Exception:
                                    pass
                            return None

                        for clip_idx in range(2, num_clips_needed + 1):
                            result_n = _render_extra_clip(clip_idx)
                            if result_n:
                                all_clips.append(result_n)
                            else:
                                self.log(f"{TAG} ⚠️  Clip {clip_idx} fehlgeschlagen — stoppe bei {len(all_clips)} Clip(s).", "WARNING")
                                break

                        # FFmpeg concat wenn mehr als 1 Clip
                        if len(all_clips) > 1:
                            self.log(f"{TAG} 🔗 Fuege {len(all_clips)} Clips zusammen ({len(all_clips)*5:.0f}s)...", "INFO")
                            concat_list = os.path.join(out_dir, "_concat_list.txt")
                            with open(concat_list, "w", encoding="utf-8") as f:
                                for c in all_clips:
                                    f.write(f"file '{c}'\n")
                            concat_out = os.path.join(out_dir, "_clip_concat.mp4")
                            # FFmpeg suchen
                        import shutil as _shff
                        ffmpeg_cc = _shff.which("ffmpeg")
                        if not ffmpeg_cc:
                            _ff_local = os.path.join(comfyui_out, "..", "venv", "Scripts", "ffmpeg.exe")
                            _ff_local = os.path.normpath(_ff_local)
                            if os.path.isfile(_ff_local):
                                ffmpeg_cc = _ff_local
                            if ffmpeg_cc:
                                try:
                                    subprocess.run(
                                        [ffmpeg_cc, "-y", "-f", "concat", "-safe", "0",
                                         "-i", concat_list, "-c", "copy", concat_out],
                                        check=True, capture_output=True, timeout=120
                                    )
                                    if os.path.isfile(concat_out):
                                        _shc.copy2(concat_out, clip_path)
                                        self.log(f"{TAG} ✅ {len(all_clips)} Clips → {clip_path} ({len(all_clips)*5:.0f}s)", "SUCCESS")
                                except Exception as fe:
                                    self.log(f"{TAG} FFmpeg concat fehlgeschlagen: {fe}", "WARNING")

                    # ── Cinematic Audio Pipeline ──────────────────────────────
                    final_path = self._run_cinematic_audio_pipeline(
                        sid=sid,
                        video_path=clip_path,
                        prompt=prompt,
                        duration_sec=duration_sec,
                        out_dir=out_dir,
                        comfyui_url=COMFYUI_URL,
                        tag=TAG,
                    )
                    return final_path if final_path else clip_path
                except Exception as e:
                    self.log(f"{TAG} Pipeline fehlgeschlagen: {e} — gebe Video ohne Audio zurueck.", "WARNING")
                    if os.path.isfile(clip_path):
                        return clip_path

            # Fallback: HTTP-Download (falls Dateisystem-Zugriff fehlschlaegt)
            self.log(f"{TAG} Lade via HTTP (Fallback)...", "INFO")
            params   = f"filename={urllib.parse.quote(clip_filename)}&type=output"
            if clip_subfolder:
                params += f"&subfolder={urllib.parse.quote(clip_subfolder)}"
            clip_url = f"{COMFYUI_URL}/view?{params}"
            try:
                urllib.request.urlretrieve(clip_url, clip_path)
                self.log(f"{TAG} ✅ Gespeichert (HTTP): {clip_path}", "SUCCESS")
                return clip_path
            except Exception as e:
                self.log(f"{TAG} Download fehlgeschlagen: {e}.", "WARNING")
                return None

        self.log(f"{TAG} Timeout nach {max_wait}s — kein Clip empfangen.", "WARNING")
        return None

    @staticmethod
    def _install_comfyui(storage_root: str, log_cb=None) -> bool:
        """Installiert ComfyUI Portable + WAN 2.1 1.3B + Custom Nodes einmalig.

        Schritte:
          1. Prueft ob ComfyUI-Ordner bereits existiert (ueberspringt dann).
          2. Laedt ComfyUI Portable ZIP von GitHub.
          3. Entpackt ins <storage_root>/ComfyUI-Portable Verzeichnis.
          4. Erstellt venv, installiert torch (CUDA 12.1) + requirements.
          5. Laedt WAN 2.1 1.3B Modell (safetensors) herunter.
          6. Klont ComfyUI-Manager + ComfyUI-AudioTools als Custom Nodes.

        Plattform: Windows 10/11, NVIDIA GPU (6 GB+ VRAM empfohlen).

        Args:
            storage_root: Basis-Ordner der Produktion (ComfyUI-Portable landet daneben).
            log_cb:       Callable(msg, level) fuer Log-Ausgabe.

        Returns:
            True bei Erfolg, False bei Fehler.
        """
        import urllib.request
        import zipfile
        import shutil

        log = log_cb or (lambda m, l="INFO": print(f"[{l}] {m}"))

        # Zielordner: ein Level ueber storage_root (Projektroot)
        project_root  = os.path.dirname(os.path.normpath(storage_root))
        comfyui_dir   = os.path.join(project_root, "ComfyUI-Portable")
        zip_tmp       = os.path.join(project_root, "_comfyui_download.zip")

        # ── 1. Bereits vorhanden? ─────────────────────────────────────────────
        main_py = os.path.join(comfyui_dir, "main.py")
        skip_download = os.path.isfile(main_py)

        if skip_download:
            log("[ComfyUI-Install] ComfyUI bereits vorhanden — ueberspringe Download+Entpacken.", "INFO")
            log(f"  → Setze fort mit: venv, Dependencies, Modell, Custom Nodes.", "INFO")
        else:
            # ── 2. ComfyUI Portable ZIP laden ────────────────────────────────────
            COMFYUI_ZIP_URL = (
                "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/"
                "ComfyUI_windows_portable_nvidia.7z"
            )
            COMFYUI_ZIP_FALLBACK = (
                "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip"
            )

            log("[ComfyUI-Install] Schritt 1/6: Lade ComfyUI von GitHub...", "INFO")

            # Cache pruefen: setupfiles/comfyui_master.zip
            zip_cached = os.path.join(project_root, "setupfiles", "comfyui_master.zip")
            if os.path.isfile(zip_cached) and os.path.getsize(zip_cached) > 1_000_000:
                log(f"[ComfyUI-Install] ComfyUI ZIP im Cache — ueberspringe Download.", "SUCCESS")
                log(f"  Cache: {zip_cached}", "INFO")
                zip_tmp = zip_cached  # direkt aus Cache entpacken
            else:
                log(f"  URL: {COMFYUI_ZIP_FALLBACK}", "INFO")
                try:
                    urllib.request.urlretrieve(COMFYUI_ZIP_FALLBACK, zip_tmp)
                    log(f"[ComfyUI-Install] ZIP heruntergeladen: {zip_tmp}", "INFO")
                except Exception as e:
                    log(f"[ComfyUI-Install] Download fehlgeschlagen: {e}", "ERROR")
                    return False

            # ── 3. Entpacken ─────────────────────────────────────────────────────
            log("[ComfyUI-Install] Schritt 2/6: Entpacke ZIP...", "INFO")
            try:
                with zipfile.ZipFile(zip_tmp, "r") as zf:
                    zf.extractall(project_root)
                # ZIP im Cache behalten — nicht loeschen
                zip_cache = os.path.join(project_root, "setupfiles", "comfyui_master.zip")
                try:
                    os.makedirs(os.path.dirname(zip_cache), exist_ok=True)
                    if os.path.abspath(zip_tmp) != os.path.abspath(zip_cache):
                        import shutil as _sh2
                        _sh2.copy2(zip_tmp, zip_cache)
                    os.remove(zip_tmp)
                    log(f"[ComfyUI-Install] ZIP gecacht: {zip_cache}", "INFO")
                except Exception:
                    try:
                        os.remove(zip_tmp)
                    except Exception:
                        pass

                # GitHub-Archive entpacken als 'ComfyUI-master/' im project_root.
                # Falls ComfyUI-Portable bereits existiert (z.B. von vorherigem
                # Versuch), werden fehlende Dateien hineinkopiert statt neu benannt.
                extracted = os.path.join(project_root, "ComfyUI-master")
                if os.path.isdir(extracted):
                    if not os.path.isdir(comfyui_dir):
                        shutil.move(extracted, comfyui_dir)
                        log(f"[ComfyUI-Install] Umbenannt: ComfyUI-master → ComfyUI-Portable", "INFO")
                    else:
                        # Zielordner existiert: Dateien einzeln kopieren (merge)
                        log("[ComfyUI-Install] Zielordner existiert — merge ComfyUI-master...", "INFO")
                        for item in os.listdir(extracted):
                            src_item = os.path.join(extracted, item)
                            dst_item = os.path.join(comfyui_dir, item)
                            if os.path.isdir(src_item):
                                if not os.path.exists(dst_item):
                                    shutil.copytree(src_item, dst_item)
                            else:
                                shutil.copy2(src_item, dst_item)
                        shutil.rmtree(extracted, ignore_errors=True)
                        log("[ComfyUI-Install] Merge abgeschlossen ✓", "INFO")

                # Sanity-check: main.py muss jetzt vorhanden sein
                main_check = os.path.join(comfyui_dir, "main.py")
                if not os.path.isfile(main_check):
                    # Suche main.py in Unterordnern (Fallback fuer unerwartete Struktur)
                    for root_d, dirs, files in os.walk(comfyui_dir):
                        if "main.py" in files and "nodes.py" in files:
                            log(f"[ComfyUI-Install] main.py gefunden in: {root_d} — verschiebe...", "INFO")
                            for f in os.listdir(root_d):
                                shutil.move(os.path.join(root_d, f),
                                            os.path.join(comfyui_dir, f))
                            break

                log(f"[ComfyUI-Install] Entpackt nach: {comfyui_dir}", "SUCCESS")
                log(f"[ComfyUI-Install] main.py vorhanden: {os.path.isfile(main_check)}", "INFO")
            except Exception as e:
                log(f"[ComfyUI-Install] Entpacken fehlgeschlagen: {e}", "ERROR")
                return False
        # Ende skip_download else-Block

        # ── 4. Venv + Torch installieren ─────────────────────────────────────
        log("[ComfyUI-Install] Schritt 3/6: Erstelle venv und installiere torch...", "INFO")
        venv_dir = os.path.join(comfyui_dir, "venv")

        # sys.executable koennte 32-Bit Python sein (kein venv/torch moeglich).
        # Suche explizit nach einem 64-Bit Python 3.10+ auf diesem System.
        def _find_64bit_python() -> str:
            """Findet ein geeignetes 64-Bit python.exe fuer venv + torch.

            Anforderungen:
            - Muss python.exe sein (NICHT pythonw.exe — kein venv-Support)
            - Muss 64-Bit sein (struct.calcsize('P') == 8)
            - Muss venv unterstuetzen (ensurepip vorhanden)
            - Muss Python 3.10+ sein
            """
            import struct, shutil as _sh

            def _is_valid(exe: str) -> bool:
                """Prueft ob exe ein nutzbares 64-Bit python.exe ist."""
                if not exe or not os.path.isfile(exe):
                    return False
                # Niemals pythonw.exe verwenden
                if os.path.basename(exe).lower() == "pythonw.exe":
                    return False
                try:
                    out = subprocess.check_output(
                        [exe, "-c",
                         "import struct, sys, ensurepip; "
                         "print(struct.calcsize('P'), sys.version_info.major, "
                         "sys.version_info.minor)"],
                        timeout=8, stderr=subprocess.DEVNULL
                    ).decode().strip().split()
                    ptr_size   = int(out[0])
                    major, minor = int(out[1]), int(out[2])
                    return ptr_size == 8 and (major, minor) >= (3, 10)
                except Exception:
                    return False

            # 1. Laufendes Python (wenn es python.exe und 64-Bit ist)
            cur = sys.executable
            if os.path.basename(cur).lower() == "python.exe" and _is_valid(cur):
                return cur

            # 2. python.exe im selben Verzeichnis wie laufendes Python
            cur_dir  = os.path.dirname(cur)
            sibling  = os.path.join(cur_dir, "python.exe")
            if _is_valid(sibling):
                return sibling

            # 3. Windows py-Launcher (py.exe) — findet neuestes 64-Bit Python
            py_launcher = _sh.which("py")
            if py_launcher:
                try:
                    out = subprocess.check_output(
                        [py_launcher, "-3", "-c",
                         "import sys; print(sys.executable)"],
                        timeout=8, stderr=subprocess.DEVNULL
                    ).decode().strip()
                    candidate = os.path.join(os.path.dirname(out), "python.exe")
                    if _is_valid(candidate):
                        return candidate
                except Exception:
                    pass

            # 4. PATH-Suche (python3 / python — aber nur python.exe)
            for name in ("python3.exe", "python.exe"):
                found = _sh.which(name)
                if found and _is_valid(found):
                    return found

            # 5. Typische Windows-Installationspfade scannen
            search_bases = [
                r"C:\Python",
                r"C:\Program Files\Python",
                r"C:\Program Files (x86)\Python",
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Python"),
            ]
            for base in search_bases:
                if not os.path.isdir(base):
                    continue
                for entry in sorted(os.listdir(base), reverse=True):  # neueste zuerst
                    if "32" in entry or entry.lower() == "pythonw.exe":
                        continue
                    p = os.path.join(base, entry, "python.exe")
                    if _is_valid(p):
                        return p

            # 6. Registry-Eintrag auslesen (Windows)
            try:
                import winreg
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    for subkey in (
                        r"SOFTWARE\Python\PythonCore",
                        r"SOFTWARE\WOW6432Node\Python\PythonCore",
                    ):
                        try:
                            key = winreg.OpenKey(hive, subkey)
                            i   = 0
                            while True:
                                try:
                                    ver = winreg.EnumKey(key, i)
                                    i  += 1
                                    ipath = winreg.OpenKey(key, ver + r"\InstallPath")
                                    install_dir = winreg.QueryValueEx(ipath, "")[0]
                                    p = os.path.join(install_dir, "python.exe")
                                    if _is_valid(p):
                                        return p
                                except OSError:
                                    break
                        except OSError:
                            continue
            except ImportError:
                pass  # kein winreg (Linux/Mac)

            log("[ComfyUI-Install] ⚠️  Kein geeignetes Python gefunden — Fallback auf sys.executable.", "WARNING")
            return sys.executable

        venv_python = _find_64bit_python()
        log(f"[ComfyUI-Install] Python fuer venv: {venv_python}", "INFO")

        # ── Altes venv-Verzeichnis bereinigen (verhindert Permission-denied) ──
        if os.path.isdir(venv_dir):
            log("[ComfyUI-Install] Altes venv-Verzeichnis gefunden — loesche es...", "INFO")
            try:
                import shutil as _shutil
                _shutil.rmtree(venv_dir, ignore_errors=True)
                # Sicherheitscheck: falls Prozess die Dateien noch haelt
                if os.path.isdir(venv_dir):
                    log("[ComfyUI-Install] venv-Ordner konnte nicht vollstaendig geloescht werden.", "WARNING")
                else:
                    log("[ComfyUI-Install] Altes venv geloescht ✓", "INFO")
            except Exception as e:
                log(f"[ComfyUI-Install] venv-Loeschung fehlgeschlagen: {e}", "WARNING")

        # ── Venv erstellen — 4 Strategien ────────────────────────────────────
        # Hinweis: capture_output=True erst ab Python 3.7 — nutze PIPE fuer
        # maximale Kompatibilitaet (auch auf aelteren Python-Installationen).
        PIPE = subprocess.PIPE
        venv_ok = False

        # Strategie 1: Standard venv
        try:
            result = subprocess.run(
                [venv_python, "-m", "venv", venv_dir],
                timeout=120,
                stdout=PIPE, stderr=PIPE,
            )
            if result.returncode == 0:
                venv_ok = True
                log("[ComfyUI-Install] venv erstellt ✓ (Standard)", "SUCCESS")
            else:
                log(f"[ComfyUI-Install] venv Standard fehlgeschlagen (exit {result.returncode}):", "WARNING")
                if result.stdout and result.stdout.strip():
                    log(f"  stdout: {result.stdout.decode(errors='replace').strip()}", "WARNING")
                if result.stderr and result.stderr.strip():
                    log(f"  stderr: {result.stderr.decode(errors='replace').strip()}", "WARNING")
        except Exception as e:
            log(f"[ComfyUI-Install] venv Standard Exception: {e}", "WARNING")

        # Strategie 2: venv --without-pip (falls ensurepip fehlt)
        if not venv_ok:
            log("[ComfyUI-Install] Versuche venv --without-pip...", "INFO")
            try:
                result = subprocess.run(
                    [venv_python, "-m", "venv", "--without-pip", venv_dir],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                )
                if result.returncode == 0:
                    venv_ok = True
                    log("[ComfyUI-Install] venv --without-pip erstellt ✓", "SUCCESS")
                    # pip nachinstallieren via get-pip.py
                    log("[ComfyUI-Install] Installiere pip via get-pip.py...", "INFO")
                    try:
                        import urllib.request as _ur
                        get_pip = os.path.join(comfyui_dir, "_get_pip.py")
                        _ur.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
                        venv_py = os.path.join(venv_dir, "Scripts", "python.exe")
                        subprocess.check_call([venv_py, get_pip], timeout=120)
                        os.remove(get_pip)
                        log("[ComfyUI-Install] pip installiert ✓", "SUCCESS")
                    except Exception as ep:
                        log(f"[ComfyUI-Install] pip-Nachinstall fehlgeschlagen: {ep}", "WARNING")
                else:
                    err = result.stderr.decode(errors='replace').strip() if result.stderr else ""
                    if err:
                        log(f"  stderr: {err}", "WARNING")
            except Exception as e:
                log(f"[ComfyUI-Install] venv --without-pip Exception: {e}", "WARNING")

        # Strategie 3: virtualenv installieren und nutzen
        if not venv_ok:
            log("[ComfyUI-Install] Versuche virtualenv...", "INFO")
            try:
                subprocess.check_call(
                    [venv_python, "-m", "pip", "install", "--quiet", "virtualenv"],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                )
                result = subprocess.run(
                    [venv_python, "-m", "virtualenv", venv_dir],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                )
                if result.returncode == 0:
                    venv_ok = True
                    log("[ComfyUI-Install] virtualenv erstellt ✓", "SUCCESS")
                else:
                    err = result.stderr.decode(errors='replace').strip() if result.stderr else ""
                    if err:
                        log(f"  stderr: {err}", "WARNING")
            except Exception as e:
                log(f"[ComfyUI-Install] virtualenv Exception: {e}", "WARNING")

        # Strategie 4: Kein venv — direkt System-Python nutzen (nicht isoliert)
        if not venv_ok:
            log("[ComfyUI-Install] ⚠️  Kein venv moeglich — nutze System-Python direkt.", "WARNING")
            log("  → Pakete werden global installiert (nicht isoliert).", "WARNING")

        # pip_exe und python_exe: aus venv wenn vorhanden, sonst System-Python
        if venv_ok:
            pip_exe    = os.path.join(venv_dir, "Scripts", "pip.exe") if sys.platform == "win32" \
                         else os.path.join(venv_dir, "bin", "pip")
            python_exe = os.path.join(venv_dir, "Scripts", "python.exe") if sys.platform == "win32" \
                         else os.path.join(venv_dir, "bin", "python")
        else:
            python_exe = venv_python
            pip_exe    = None  # wird ueber "python -m pip" aufgerufen

        def _pip(args: list, **kwargs) -> bool:
            """Fuehrt pip-Kommando aus — via pip_exe oder 'python -m pip'."""
            cmd = [pip_exe] + args if pip_exe and os.path.isfile(pip_exe) \
                  else [python_exe, "-m", "pip"] + args
            try:
                subprocess.check_call(cmd, **kwargs)
                return True
            except Exception as ex:
                log(f"[ComfyUI-Install] pip-Fehler: {ex}", "WARNING")
                return False

        # ── torch + requirements installieren ────────────────────────────────
        # Schritt 1: CUDA-Version via nvidia-smi ermitteln (wie in HardwareProfile)
        # Schritt 2: Bestehende pytorch_env/venv wiederverwenden falls vorhanden
        # Schritt 3: torch WHL im Cache-Ordner ablegen — kein Re-Download

        # Cache-Ordner: <project_root>/setupfiles (persistent zwischen Laeufen)
        setup_cache = os.path.join(project_root, "setupfiles")
        os.makedirs(setup_cache, exist_ok=True)
        log(f"[ComfyUI-Install] Setup-Cache: {setup_cache}", "INFO")

        def _detect_cuda_version() -> str:
            """Liest CUDA-Version via nvidia-smi. Gibt z.B. '12.8' zurueck oder '' wenn nicht verfuegbar."""
            nsmi_paths = [
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                "nvidia-smi",
            ]
            for nsmi in nsmi_paths:
                try:
                    r = subprocess.run(
                        [nsmi, "--query-gpu=driver_version", "--format=csv,noheader"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=8, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if r.returncode == 0:
                        r2 = subprocess.run(
                            [nsmi],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=8, creationflags=subprocess.CREATE_NO_WINDOW
                        )
                        out = r2.stdout.decode(errors="replace")
                        for line in out.splitlines():
                            if "CUDA Version:" in line:
                                parts = line.split("CUDA Version:")
                                if len(parts) > 1:
                                    return parts[1].strip().split()[0]
                except Exception:
                    continue
            return ""

        cuda_ver = _detect_cuda_version()
        if cuda_ver:
            major, minor = cuda_ver.split(".")[:2]
            cu_tag = f"cu{major}{minor.zfill(1)}"
            known_tags = {"cu118", "cu121", "cu124", "cu126", "cu128"}
            if cu_tag not in known_tags:
                cuda_float = float(f"{major}.{minor}")
                if cuda_float >= 12.8:
                    cu_tag = "cu128"
                elif cuda_float >= 12.6:
                    cu_tag = "cu126"
                elif cuda_float >= 12.4:
                    cu_tag = "cu124"
                elif cuda_float >= 12.1:
                    cu_tag = "cu121"
                else:
                    cu_tag = "cu118"
            torch_index = f"https://download.pytorch.org/whl/{cu_tag}"
            log(f"[ComfyUI-Install] CUDA {cuda_ver} erkannt → torch {cu_tag}", "SUCCESS")
        else:
            torch_index = "https://download.pytorch.org/whl/cpu"
            cu_tag = "cpu"
            log("[ComfyUI-Install] Kein NVIDIA-Treiber erkannt → torch CPU-Version.", "WARNING")

        # Bestehende pytorch_env/venv auf dem System suchen (vom PyTorchInstaller)
        pytorch_env_venv = os.path.join(
            os.path.expanduser("~"), "pytorch_env", "venv", "Scripts", "python.exe"
        )
        if os.path.isfile(pytorch_env_venv) and venv_ok is False:
            try:
                r = subprocess.run(
                    [pytorch_env_venv, "-c",
                     "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                )
                out = r.stdout.decode(errors="replace").strip()
                if out.startswith("True"):
                    log(f"[ComfyUI-Install] Bestehende pytorch_env gefunden: {out}", "SUCCESS")
                    log(f"  → Nutze {pytorch_env_venv} statt Neuinstallation.", "INFO")
                    python_exe = pytorch_env_venv
                    pip_exe    = pytorch_env_venv.replace("python.exe", "pip.exe")
                    venv_ok    = True
            except Exception as pe:
                log(f"[ComfyUI-Install] pytorch_env-Pruefung fehlgeschlagen: {pe}", "WARNING")

        # torch: erst pruefen ob bereits CUDA-faehig installiert
        torch_already_ok = False
        try:
            r = subprocess.run(
                [python_exe, "-c",
                 "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            out = r.stdout.decode(errors="replace").strip()
            if out.startswith("True") and f"+{cu_tag}" in out:
                log(f"[ComfyUI-Install] torch bereits korrekt installiert: {out} ✓", "SUCCESS")
                torch_already_ok = True
        except Exception:
            pass

        if not torch_already_ok:
            # WHL-Dateien im Cache-Ordner ablegen (pip --find-links + --cache-dir)
            torch_cache = os.path.join(setup_cache, f"torch_{cu_tag}")
            os.makedirs(torch_cache, exist_ok=True)

            # Pruefen ob WHL bereits gecacht (mind. 3 Dateien: torch, torchvision, torchaudio)
            cached_whls = [f for f in os.listdir(torch_cache) if f.endswith(".whl")]
            if len(cached_whls) >= 3:
                log(f"[ComfyUI-Install] torch WHL-Cache gefunden ({len(cached_whls)} Dateien) — "
                    f"nutze lokalen Cache.", "SUCCESS")
                log(f"  Cache: {torch_cache}", "INFO")
                # Aus Cache installieren (kein Internet noetig)
                torch_ok = _pip([
                    "install", "torch", "torchvision", "torchaudio",
                    "--find-links", torch_cache,
                    "--no-index",            # nur aus Cache, kein PyPI
                ], timeout=300)
                if not torch_ok:
                    # Falls Cache-Install fehlschlaegt: frisch herunterladen
                    log("[ComfyUI-Install] Cache-Install fehlgeschlagen — lade neu herunter.", "WARNING")
                    cached_whls = []

            if len(cached_whls) < 3:
                log(f"[ComfyUI-Install] Lade torch ({cu_tag}) herunter → Cache: {torch_cache}", "INFO")
                # download-only: WHL-Dateien in Cache speichern ohne zu installieren
                _pip([
                    "download", "torch", "torchvision", "torchaudio",
                    "--index-url", torch_index,
                    "--dest", torch_cache,
                    "--no-cache-dir",
                ], timeout=900)
                # Aus frisch heruntergeladenem Cache installieren
                torch_ok = _pip([
                    "install", "torch", "torchvision", "torchaudio",
                    "--find-links", torch_cache,
                    "--no-index",
                ], timeout=300)

            if torch_ok:
                try:
                    check = subprocess.run(
                        [python_exe, "-c",
                         "import torch; "
                         "print('CUDA:', torch.cuda.is_available(), '|', "
                         "torch.version.cuda if torch.cuda.is_available() else 'n/a')"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                    )
                    out = check.stdout.decode(errors="replace").strip()
                    if "CUDA: True" in out:
                        log(f"[ComfyUI-Install] torch ✓ — {out}", "SUCCESS")
                    else:
                        log(f"[ComfyUI-Install] torch installiert aber CUDA nicht aktiv: {out}", "WARNING")
                        log("  → Pruefe ob NVIDIA-Treiber aktuell sind.", "WARNING")
                except Exception as ve:
                    log(f"[ComfyUI-Install] torch CUDA-Verifikation fehlgeschlagen: {ve}", "WARNING")
            else:
                log("[ComfyUI-Install] torch-Installation fehlgeschlagen.", "WARNING")

        req_file = os.path.join(comfyui_dir, "requirements.txt")
        if os.path.isfile(req_file):
            log("[ComfyUI-Install] Installiere requirements.txt...", "INFO")
            req_ok = _pip(["install", "-r", req_file], timeout=300)
            if req_ok:
                log("[ComfyUI-Install] requirements.txt installiert ✓", "SUCCESS")
            else:
                log("[ComfyUI-Install] requirements.txt fehlgeschlagen (nicht kritisch).", "WARNING")

        # ── tqdm auf bekannt-gute Version fixieren ────────────────────────────
        # tqdm >= 4.67 hat einen Bug auf Windows-Pipes wenn ComfyUI-Manager
        # stderr patcht → OSError [Errno 22] beim flush() → KSampler bricht ab.
        # Lösung: tqdm==4.66.4 (letzte stabile Version ohne diesen Bug).
        log("[ComfyUI-Install] Fixiere tqdm (Windows-Pipe Bug)...", "INFO")
        tqdm_ok = _pip(["install", "tqdm==4.66.4", "--force-reinstall", "--no-cache-dir"], timeout=60)
        if tqdm_ok:
            log("  tqdm==4.66.4 installiert ✓", "SUCCESS")
        else:
            log("  tqdm-Fix fehlgeschlagen — KSampler kann weiter abstürzen", "WARNING")

        # ── torch CUDA nach requirements.txt sichern ──────────────────────────
        # requirements.txt kann torch überschreiben. Immer danach prüfen und
        # ggf. aus WHL-Cache wiederherstellen.
        chk_torch_req = subprocess.run(
            [python_exe, "-c",
             "import torch; print(torch.cuda.is_available(), torch.__version__)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out_tr = chk_torch_req.stdout.decode(errors="replace").strip()
        if out_tr.startswith("True") and f"+{cu_tag}" in out_tr:
            log(f"  torch CUDA nach requirements.txt: {out_tr} ✓", "INFO")
        else:
            log(f"  torch CUDA verloren nach requirements.txt ({out_tr}) — stelle wieder her...", "WARNING")
            torch_cache_req = os.path.join(setup_cache, f"torch_{cu_tag}")
            cached_req = [f for f in os.listdir(torch_cache_req) if f.endswith(".whl")] \
                         if os.path.isdir(torch_cache_req) else []
            if len(cached_req) >= 3:
                _pip(["install", "torch", "torchvision", "torchaudio",
                      "--find-links", torch_cache_req, "--no-index"], timeout=300)
            log("  torch CUDA wiederhergestellt ✓", "SUCCESS")


        log("[ComfyUI-Install] Schritt 4/6: Lade WAN 2.1 1.3B Modell...", "INFO")
        # WAN 2.1 gehoert in diffusion_models/ (NICHT checkpoints/) — ComfyUI native
        models_dir = os.path.join(comfyui_dir, "models", "diffusion_models")
        os.makedirs(models_dir, exist_ok=True)
        model_name = "wan2.1_t2v_1.3B_bf16.safetensors"
        model_path = os.path.join(models_dir, model_name)

        # Cache-Pfad im setupfiles-Ordner
        model_cache = os.path.join(setup_cache, model_name)
        MIN_MODEL_SIZE = 500_000_000  # 500 MB — echtes Modell ist ~2.5 GB

        WAN_MODEL_URL = (
            "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/"
            "split_files/diffusion_models/wan2.1_t2v_1.3B_bf16.safetensors"
        )
        WAN_MODEL_URL_FP16 = (
            "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/"
            "split_files/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors"
        )

        if os.path.isfile(model_path) and os.path.getsize(model_path) > MIN_MODEL_SIZE:
            log(f"[ComfyUI-Install] Modell bereits im Zielordner ✓", "INFO")
            log(f"  {model_path}", "INFO")
        elif os.path.isfile(model_cache) and os.path.getsize(model_cache) > MIN_MODEL_SIZE:
            # Im Cache vorhanden — einfach in Zielordner kopieren/verlinken
            log(f"[ComfyUI-Install] Modell im Cache gefunden — kopiere...", "SUCCESS")
            log(f"  Cache: {model_cache}", "INFO")
            try:
                import shutil as _shm
                _shm.copy2(model_cache, model_path)
                log(f"[ComfyUI-Install] Modell kopiert ✓ → {model_path}", "SUCCESS")
            except Exception as e:
                log(f"[ComfyUI-Install] Kopieren fehlgeschlagen: {e} — versuche Symlink.", "WARNING")
                try:
                    os.symlink(model_cache, model_path)
                    log(f"[ComfyUI-Install] Symlink erstellt ✓", "SUCCESS")
                except Exception as e2:
                    log(f"[ComfyUI-Install] Symlink fehlgeschlagen: {e2}", "WARNING")
        else:
            log(f"  URL: {WAN_MODEL_URL}", "INFO")
            log("  (ca. 2-3 GB — Geduld... wird in setupfiles/ gecacht)", "INFO")
            downloaded = False
            for attempt_url, attempt_label, fname in [
                (WAN_MODEL_URL,      "bf16", model_name),
                (WAN_MODEL_URL_FP16, "fp16", "wan2.1_t2v_1.3B_fp16.safetensors"),
            ]:
                try:
                    log(f"  Versuche {attempt_label}: {attempt_url}", "INFO")
                    # Direkt in Cache herunterladen
                    cache_target = os.path.join(setup_cache, fname)
                    urllib.request.urlretrieve(attempt_url, cache_target)
                    # Auch in models/diffusion_models/ kopieren
                    dest = os.path.join(models_dir, fname)
                    import shutil as _shm2
                    _shm2.copy2(cache_target, dest)
                    log(f"[ComfyUI-Install] Modell geladen ✓ ({attempt_label})", "SUCCESS")
                    log(f"  Cache: {cache_target}", "INFO")
                    log(f"  Ziel:  {dest}", "INFO")
                    # model_path auf den tatsaechlichen Dateinamen setzen
                    model_path = dest
                    downloaded = True
                    break
                except Exception as e:
                    log(f"  {attempt_label} fehlgeschlagen: {e}", "WARNING")
            if not downloaded:
                log(
                    "[ComfyUI-Install] ⚠️  Modell-Download fehlgeschlagen.\n"
                    "  Manuell laden und in setupfiles/ oder models/diffusion_models/ legen:\n"
                    f"  {setup_cache}\n"
                    "  Quelle: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                    "WARNING"
                )

        # ── 5b. WAN VAE + T5 Text Encoder herunterladen ─────────────────────
        # Beide werden von ComfyUI zwingend benoetigt — ohne sie schlaegt jeder
        # Workflow fehl. Werden gecacht in setupfiles/ und nach models/vae/ bzw.
        # models/text_encoders/ kopiert.
        log("[ComfyUI-Install] Lade WAN VAE + T5 Text Encoder...", "INFO")

        def _ensure_model(filename: str, dest_dir: str, url: str,
                          min_size: int = 10_000_000, label: str = "") -> bool:
            """Laedt eine Modell-Datei herunter wenn nicht im Ziel oder Cache vorhanden.
            Gibt True zurueck wenn Datei am Ende verfuegbar ist."""
            dest_path  = os.path.join(dest_dir, filename)
            cache_path = os.path.join(setup_cache, filename)
            os.makedirs(dest_dir, exist_ok=True)

            if os.path.isfile(dest_path) and os.path.getsize(dest_path) > min_size:
                log(f"  {label or filename}: bereits vorhanden ✓", "INFO")
                return True
            if os.path.isfile(cache_path) and os.path.getsize(cache_path) > min_size:
                log(f"  {label or filename}: aus Cache kopieren...", "INFO")
                try:
                    import shutil as _shx
                    _shx.copy2(cache_path, dest_path)
                    log(f"  {label or filename}: kopiert ✓", "SUCCESS")
                    return True
                except Exception as e:
                    log(f"  {label or filename}: Kopieren fehlgeschlagen: {e}", "WARNING")
            # Herunterladen → zuerst in Cache, dann in Ziel kopieren
            log(f"  {label or filename}: lade herunter...", "INFO")
            log(f"    URL: {url}", "INFO")
            try:
                urllib.request.urlretrieve(url, cache_path)
                import shutil as _shx2
                _shx2.copy2(cache_path, dest_path)
                log(f"  {label or filename}: heruntergeladen ✓", "SUCCESS")
                return True
            except Exception as e:
                log(f"  {label or filename}: Download fehlgeschlagen: {e}", "WARNING")
                log(f"    Manuell laden: {url}", "WARNING")
                log(f"    Speichern nach: {dest_path}", "WARNING")
                return False

        vae_dir = os.path.join(comfyui_dir, "models", "vae")
        t5_dir  = os.path.join(comfyui_dir, "models", "text_encoders")

        _ensure_model(
            filename = "wan_2.1_vae.safetensors",
            dest_dir = vae_dir,
            url      = ("https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged"
                        "/resolve/main/split_files/vae/wan_2.1_vae.safetensors"),
            min_size = 50_000_000,   # ~335 MB
            label    = "WAN VAE",
        )
        _ensure_model(
            filename = "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
            dest_dir = t5_dir,
            url      = ("https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged"
                        "/resolve/main/split_files/text_encoders"
                        "/umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
            min_size = 100_000_000,  # ~4.9 GB
            label    = "T5 Text Encoder (fp8, ~4.9 GB — Geduld...)",
        )

        # ── 5b-2. Stable Diffusion 1.5 Checkpoint ─────────────────────────────
        log("[ComfyUI-Install] Lade SD 1.5 Checkpoint...", "INFO")
        ckpt_dir  = os.path.join(comfyui_dir, "models", "checkpoints")
        os.makedirs(ckpt_dir, exist_ok=True)
        _ensure_model(
            filename = "v1-5-pruned-emaonly-fp16.safetensors",
            dest_dir = ckpt_dir,
            url      = ("https://huggingface.co/runwayml/stable-diffusion-v1-5"
                        "/resolve/main/v1-5-pruned-emaonly.safetensors"),
            min_size = 1_000_000_000,
            label    = "SD 1.5 fp16 (~2 GB — Geduld...)",
        )
        log("[ComfyUI-Install] Lade ChatterBox TTS Modell...", "INFO")
        chatterbox_dir        = os.path.join(comfyui_dir, "models", "TTS", "chatterbox")
        chatterbox_cache_dir  = os.path.join(setup_cache, "chatterbox")
        os.makedirs(chatterbox_dir, exist_ok=True)
        os.makedirs(chatterbox_cache_dir, exist_ok=True)

        # TTS-Audio-Suite laedt ChatterBox-Modelle in chatterbox/English/ Unterordner
        # Wir cachen und pruefen beide Ebenen (Root + English/)
        _CB_REQUIRED_ROOT = ["s3gen.pt", "t3_cfg.pt", "tokenizer.model"]
        _CB_REQUIRED_EN   = ["s3gen.pt", "t3_cfg.pt", "tokenizer.json",
                             "ve.pt", "conds.pt"]

        def _chatterbox_complete(d: str) -> bool:
            # Root-Ebene (alte HF-Struktur)
            if all(os.path.isfile(os.path.join(d, f)) for f in _CB_REQUIRED_ROOT):
                return True
            # English/-Unterordner (TTS-Audio-Suite Struktur)
            en = os.path.join(d, "English")
            if os.path.isdir(en):
                if all(os.path.isfile(os.path.join(en, f)) for f in _CB_REQUIRED_EN):
                    return True
            return False

        if _chatterbox_complete(chatterbox_dir):
            log("  ChatterBox: Modell bereits vorhanden ✓", "INFO")
            # English/-Unterordner in Cache sichern falls noch nicht vorhanden
            en_src = os.path.join(chatterbox_dir, "English")
            en_dst = os.path.join(chatterbox_cache_dir, "English")
            if os.path.isdir(en_src) and not _chatterbox_complete(chatterbox_cache_dir):
                try:
                    import shutil as _shcb0
                    _shcb0.copytree(en_src, en_dst, dirs_exist_ok=True)
                    log("  ChatterBox English/-Ordner → Cache gesichert ✓", "INFO")
                except Exception:
                    pass
        elif _chatterbox_complete(chatterbox_cache_dir):
            log("  ChatterBox: Kopiere aus Cache...", "SUCCESS")
            import shutil as _shcb
            for f in os.listdir(chatterbox_cache_dir):
                if f.startswith("."):
                    continue  # .cache und andere versteckte Ordner ueberspringen
                src = os.path.join(chatterbox_cache_dir, f)
                dst = os.path.join(chatterbox_dir, f)
                try:
                    if os.path.isdir(src):
                        _shcb.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        _shcb.copy2(src, dst)
                except Exception:
                    pass
            log("  ChatterBox: Modell kopiert ✓", "SUCCESS")
        else:
            log("  ChatterBox: Lade von HuggingFace (~1 GB) → Cache: setupfiles/chatterbox/", "INFO")
            try:
                dl_cb = subprocess.run(
                    [python_exe, "-c",
                     "from huggingface_hub import snapshot_download; "
                     "snapshot_download("
                     "  repo_id='ResembleAI/chatterbox',"
                     f"  local_dir=r'{chatterbox_cache_dir}',"
                     "  repo_type='model',"
                     "  ignore_patterns=['*.md','*.gitattributes']"
                     "); print('DONE')"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=1800,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if "DONE" in dl_cb.stdout.decode(errors="replace") or _chatterbox_complete(chatterbox_cache_dir):
                    log("  ChatterBox: Heruntergeladen ✓ — kopiere in Zielordner...", "SUCCESS")
                    import shutil as _shcb2
                    for f in os.listdir(chatterbox_cache_dir):
                        if f.startswith("."):
                            continue  # .cache ueberspringen
                        src = os.path.join(chatterbox_cache_dir, f)
                        dst = os.path.join(chatterbox_dir, f)
                        try:
                            if os.path.isdir(src):
                                _shcb2.copytree(src, dst, dirs_exist_ok=True)
                            else:
                                _shcb2.copy2(src, dst)
                        except Exception:
                            pass
                    log("  ChatterBox: Modell installiert ✓", "SUCCESS")
                    # English/-Unterordner aus Zielordner in Cache sichern
                    # (TTS-Audio-Suite laedt English/ direkt in models/TTS/chatterbox/English/)
                    en_src = os.path.join(chatterbox_dir, "English")
                    en_dst = os.path.join(chatterbox_cache_dir, "English")
                    if os.path.isdir(en_src):
                        try:
                            import shutil as _shcb3
                            _shcb3.copytree(en_src, en_dst, dirs_exist_ok=True)
                            log("  ChatterBox English/-Ordner gecacht ✓", "INFO")
                        except Exception:
                            pass
                    log(f"  ChatterBox: Download fehlgeschlagen — {dl_cb.stderr.decode(errors='replace')[-200:]}", "WARNING")
            except Exception as e:
                log(f"  ChatterBox: Fehler: {e}", "WARNING")

        # ── 6. Custom Nodes klonen ────────────────────────────────────────────
        custom_nodes_dir = os.path.join(comfyui_dir, "custom_nodes")
        os.makedirs(custom_nodes_dir, exist_ok=True)

        custom_nodes = [
            ("ComfyUI-Manager",
             "https://github.com/ltdrdata/ComfyUI-Manager.git"),
            ("ComfyUI-VideoHelperSuite",
             "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"),
            ("ComfyUI-AudioTools",
             "https://github.com/eigenpunk/ComfyUI-audio.git"),
            ("ComfyUI-Florence2",
             "https://github.com/kijai/ComfyUI-Florence2.git"),
            # ── Cinematic Audio Pipeline ──────────────────────────────────────
            # TTS: F5-TTS, ChatterBox, Higgs Audio 2 — Narration + Dialogue
            ("TTS-Audio-Suite",
             "https://github.com/diodiogod/TTS-Audio-Suite.git"),
            # Musik: ACE-Step 1.5 — Cinematic orchestral soundtrack (Suno-Alternative)
            ("ComfyUI_ACE-Step",
             "https://github.com/billwuhao/ComfyUI_ACE-Step.git"),
        ]

        log("[ComfyUI-Install] Schritt 5/6: Klone Custom Nodes...", "INFO")
        for node_name, node_url in custom_nodes:
            node_dir = os.path.join(custom_nodes_dir, node_name)
            if os.path.isdir(node_dir):
                # Vorhanden — git pull um auf neueste Version zu aktualisieren
                try:
                    r = subprocess.run(
                        ["git", "pull", "--ff-only"],
                        cwd=node_dir, capture_output=True, timeout=60
                    )
                    if r.returncode == 0:
                        out = r.stdout.decode(errors="replace").strip()
                        if "Already up to date" in out:
                            log(f"[ComfyUI-Install] {node_name}: bereits aktuell ✓", "INFO")
                        else:
                            log(f"[ComfyUI-Install] {node_name}: aktualisiert ✓", "SUCCESS")
                    else:
                        log(f"[ComfyUI-Install] {node_name}: git pull fehlgeschlagen (nicht kritisch)", "WARNING")
                except Exception:
                    log(f"[ComfyUI-Install] {node_name}: bereits vorhanden (kein Update).", "INFO")
                continue
            log(f"  Klone {node_name}...", "INFO")
            try:
                subprocess.check_call(
                    ["git", "clone", "--depth=1", node_url, node_dir],
                    timeout=120
                )
                log(f"  {node_name} geklont ✓", "SUCCESS")
            except FileNotFoundError:
                log("  git nicht gefunden — Custom Nodes muessen manuell installiert werden.", "WARNING")
                break
            except Exception as e:
                log(f"  {node_name} fehlgeschlagen (nicht kritisch): {e}", "WARNING")

        # ── Custom Node Dependencies installieren ─────────────────────────────
        log("[ComfyUI-Install] Installiere Custom Node Dependencies...", "INFO")

        # VideoHelperSuite: braucht opencv-python, imageio-ffmpeg
        vhs_req = os.path.join(custom_nodes_dir, "ComfyUI-VideoHelperSuite", "requirements.txt")
        if os.path.isfile(vhs_req):
            log("  VideoHelperSuite: installiere requirements.txt...", "INFO")
            _pip(["install", "-r", vhs_req, "--no-cache-dir"], timeout=180)
        else:
            # Direkt installieren falls requirements.txt fehlt
            log("  VideoHelperSuite: installiere cv2, imageio-ffmpeg...", "INFO")
            _pip(["install", "opencv-python", "imageio-ffmpeg",
                  "numpy", "Pillow", "--no-cache-dir"], timeout=180)

        # AudioTools: librosa direkt installieren (requirements.txt oft inkompatibel)
        librosa_ok = False
        try:
            r = subprocess.run(
                [python_exe, "-c", "import librosa; print('ok')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            )
            librosa_ok = r.returncode == 0
        except Exception:
            pass

        if not librosa_ok:
            log("  AudioTools: installiere librosa (direkt, ohne requirements.txt)...", "INFO")
            # Nur die tatsaechlich fehlenden Kern-Abhaengigkeiten
            _pip(["install", "librosa", "soundfile", "resampy",
                  "--no-cache-dir"], timeout=300)
        else:
            log("  AudioTools: librosa bereits installiert ✓", "INFO")

        # Florence2: timm + einops (leichtgewichtig, selten Konflikte)
        florence2_req = os.path.join(custom_nodes_dir, "ComfyUI-Florence2", "requirements.txt")
        if os.path.isfile(florence2_req):
            log("  Florence2: installiere requirements.txt...", "INFO")
            _pip(["install", "-r", florence2_req, "--no-cache-dir"], timeout=180)
        elif os.path.isdir(os.path.join(custom_nodes_dir, "ComfyUI-Florence2")):
            log("  Florence2: installiere timm, einops...", "INFO")
            _pip(["install", "timm", "einops", "--no-cache-dir"], timeout=120)

        # TTS-Audio-Suite: F5-TTS, ChatterBox etc. — Narration + Dialoge
        tts_req = os.path.join(custom_nodes_dir, "TTS-Audio-Suite", "requirements.txt")
        if os.path.isfile(tts_req):
            log("  TTS-Audio-Suite: installiere requirements.txt...", "INFO")
            _pip(["install", "-r", tts_req, "--no-cache-dir"], timeout=600)
        if os.path.isdir(os.path.join(custom_nodes_dir, "TTS-Audio-Suite")):
            # Fehlende Engine-Dependencies einzeln installieren —
            # ein fehlgeschlagenes Paket soll die anderen nicht blockieren
            log("  TTS-Audio-Suite: installiere fehlende Engine-Deps (einzeln)...", "INFO")
            _tts_deps = [
                ("s3tokenizer",             "ChatterBox",           "s3tokenizer"),
                # chatterbox-tts wird SEPARAT nach der Schleife installiert
                # (immer --no-deps, torch-Schutz danach)
                # chatterbox-tts wird SEPARAT nach der Schleife installiert
                # ("chatterbox-tts", "ChatterBox", "chatterbox"),  ← NICHT hier!
                ("cached-path",             "F5-TTS",               "cached_path"),
                ("descript-audio-codec",    "Higgs Audio 2",        "dac"),
                ("vector-quantize-pytorch", "Higgs Audio 2",        "vector_quantize_pytorch"),
                ("dacite",                  "Higgs Audio 2",        "dacite"),
                ("torchcrepe",              "RVC",                  "torchcrepe"),
                ("faiss-cpu",               "RVC",                  "faiss"),
                ("onnxruntime-gpu",         "RVC",                  "onnxruntime"),
                ("diffusers",               "ACE-Step/ChatterBox",  "diffusers"),
                ("loguru",                  "ACE-Step",             "loguru"),
                ("einops",                  "ACE-Step",             "einops"),
                ("omegaconf",               "ACE-Step",             "omegaconf"),
                ("huggingface-hub",         "ACE-Step",             "huggingface_hub"),
                ("py3langid",               "ACE-Step",             "py3langid"),
                ("langid",                  "ACE-Step/AudioTools",  "langid"),
                ("pylangacq",               "ACE-Step",             "langacq"),
                ("pydub",                   "Audio",                "pydub"),
                ("sox",                     "Audio",                "sox"),
                ("audioread",               "Audio",                "audioread"),
            ]
            for pkg, engine, import_name in _tts_deps:
                check = subprocess.run(
                    [python_exe, "-c", f"import {import_name}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if check.returncode == 0:
                    log(f"    {pkg}: bereits installiert ✓", "INFO")
                    continue
                ok = _pip(["install", pkg, "--no-cache-dir"], timeout=180)
                # Versionskonflikte/Build-Fehler umgehen
                if not ok and pkg in ("descript-audio-codec", "omegaconf"):
                    ok = _pip(["install", pkg, "--no-cache-dir", "--no-deps"], timeout=60)
                if not ok and pkg == "chatterbox-tts":
                    ok = _pip(["install", pkg, "--no-cache-dir", "--no-deps"], timeout=120)
                    if ok:
                        # Sicherheitscheck: torch CUDA nach chatterbox-tts Installation
                        chk_torch = subprocess.run(
                            [python_exe, "-c",
                             "import torch; assert torch.cuda.is_available(), 'CUDA verloren';"
                             "print('torch CUDA OK:', torch.__version__)"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        )
                        if chk_torch.returncode != 0:
                            log("  ⚠️  torch CUDA nach chatterbox-tts verloren — stelle wieder her...", "WARNING")
                            # torch CUDA aus Cache wiederherstellen
                            torch_cache = os.path.join(setup_cache, f"torch_{cu_tag}")
                            if os.path.isdir(torch_cache):
                                _pip(["install", "torch", "torchvision", "torchaudio",
                                      "--find-links", torch_cache, "--no-index"], timeout=300)
                                log("  torch CUDA wiederhergestellt ✓", "SUCCESS")
                        else:
                            log(f"  torch CUDA nach chatterbox-tts: {chk_torch.stdout.decode().strip()}", "INFO")
                if ok:
                    log(f"    {pkg} ({engine}): installiert ✓", "INFO")
                else:
                    log(f"    {pkg} ({engine}): fehlgeschlagen — Engine beeintraechtigt", "WARNING")

        # ACE-Step: requirements.txt zeilenweise installieren (robust gegen Konflikte)
        ace_req = os.path.join(custom_nodes_dir, "ComfyUI_ACE-Step", "requirements.txt")
        if os.path.isfile(ace_req):
            log("  ACE-Step: installiere requirements.txt (zeilenweise)...", "INFO")
            try:
                with open(ace_req, encoding="utf-8", errors="replace") as _f:
                    ace_lines = [
                        l.strip() for l in _f
                        if l.strip() and not l.strip().startswith("#")
                    ]
                for ace_pkg in ace_lines:
                    # Bereits-Check
                    _imp = ace_pkg.split(">=")[0].split("<=")[0].split("==")[0].strip()
                    _imp = _imp.replace("-", "_").lower()
                    chk = subprocess.run(
                        [python_exe, "-c", f"import {_imp}"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    if chk.returncode == 0:
                        continue  # bereits vorhanden
                    ok = _pip(["install", ace_pkg, "--no-cache-dir"], timeout=180)
                    if ok:
                        log(f"    ACE-Step dep '{ace_pkg}': installiert ✓", "INFO")
                    else:
                        # Fallback ohne Deps
                        ok2 = _pip(["install", ace_pkg, "--no-cache-dir", "--no-deps"], timeout=60)
                        if ok2:
                            log(f"    ACE-Step dep '{ace_pkg}': installiert (--no-deps) ✓", "INFO")
                        else:
                            log(f"    ACE-Step dep '{ace_pkg}': fehlgeschlagen", "WARNING")
            except Exception as e:
                log(f"  ACE-Step requirements.txt Fehler: {e}", "WARNING")

        # ACE-Step Modell-Ordner erstellen (verhindert FileNotFoundError beim Start)
        ace_model_dir       = os.path.join(comfyui_dir, "models", "TTS", "ACE-Step-v1-3.5B")
        ace_model_cache_dir = os.path.join(setup_cache, "ACE-Step-v1-3.5B")
        for ace_sub in ("ace_step_transformer", "music_dcae_f8c8",
                        "music_vocoder", "umt5-base", "loras"):
            os.makedirs(os.path.join(ace_model_dir, ace_sub), exist_ok=True)
            os.makedirs(os.path.join(ace_model_cache_dir, ace_sub), exist_ok=True)

        _ACE_SUBS = ("ace_step_transformer", "music_dcae_f8c8", "music_vocoder", "umt5-base")

        def _ace_model_complete(base: str) -> bool:
            for sub in _ACE_SUBS:
                d = os.path.join(base, sub)
                if not os.path.isdir(d):
                    return False
                files = [f for f in os.listdir(d)
                         if f.endswith((".safetensors", ".bin", ".json", ".pt"))]
                if not files:
                    return False
            return True

        if _ace_model_complete(ace_model_dir):
            log("  ACE-Step: Modell bereits vorhanden ✓", "INFO")
        elif _ace_model_complete(ace_model_cache_dir):
            log("  ACE-Step: Kopiere aus Cache...", "SUCCESS")
            import shutil as _shace
            _shace.copytree(ace_model_cache_dir, ace_model_dir, dirs_exist_ok=True)
            log("  ACE-Step: Modell kopiert ✓", "SUCCESS")
        else:
            log("  ACE-Step: Lade von HuggingFace (~5 GB) → Cache: setupfiles/ACE-Step-v1-3.5B/", "INFO")
            try:
                dl_ace = subprocess.run(
                    [python_exe, "-c",
                     "from huggingface_hub import snapshot_download; "
                     "snapshot_download("
                     "  repo_id='ACE-Step/ACE-Step-v1-3.5B',"
                     f"  local_dir=r'{ace_model_cache_dir}',"
                     "  repo_type='model',"
                     "  ignore_patterns=['*.md','*.txt','*.gitattributes']"
                     "); print('DONE')"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=3600,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if "DONE" in dl_ace.stdout.decode(errors="replace") or _ace_model_complete(ace_model_cache_dir):
                    log("  ACE-Step: Heruntergeladen ✓ — kopiere in Zielordner...", "SUCCESS")
                    import shutil as _shace2
                    _shace2.copytree(ace_model_cache_dir, ace_model_dir, dirs_exist_ok=True)
                    log("  ACE-Step: Modell installiert ✓", "SUCCESS")
                else:
                    log(f"  ACE-Step: Download fehlgeschlagen — {dl_ace.stderr.decode(errors='replace')[-200:]}", "WARNING")
            except subprocess.TimeoutExpired:
                log("  ACE-Step: Timeout (>1h) — bitte erneut Install ComfyUI klicken.", "WARNING")
            except Exception as e:
                log(f"  ACE-Step: Fehler: {e}", "WARNING")

        # ── chatterbox-tts: IMMER --no-deps, torch CUDA danach schützen ────────
        # chatterbox-tts zieht torch CPU als Dependency — das zerstoert die CUDA-
        # Installation. Loesung: --no-deps, dann torch CUDA aus Cache wiederherstellen.
        # Prüfe ob ChatterboxTTS vollständig funktioniert (nicht nur ob chatterbox importierbar)
        chk_cb = subprocess.run(
            [python_exe, "-c", "from chatterbox.tts import ChatterboxTTS; print('OK')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        cb_ok = b"OK" in chk_cb.stdout
        if cb_ok:
            log("  chatterbox-tts: ChatterboxTTS verfügbar ✓", "INFO")
        else:
            err_cb = chk_cb.stderr.decode(errors="replace")[-300:]
            log(f"  chatterbox-tts: ChatterboxTTS nicht verfügbar — installiere...", "INFO")
            if err_cb:
                log(f"  Fehler: {err_cb}", "INFO")

            # Immer --no-deps (verhindert torch CPU-Downgrade)
            _pip(["install", "chatterbox-tts", "--no-deps", "--no-cache-dir"], timeout=120)

            # Alle benötigten Deps nachinstallieren (OHNE torch)
            cb_deps = [
                "resemble-perth",        # Wasserzeichen (Pflicht für ChatterboxTTS)
                "conformer",             # Audio-Encoder
                "vocos",                 # Vocoder
                "encodec",               # Audio-Codec
                "rotary-embedding-torch", # Transformer
                "einops",                # Tensor-Ops
                "s3tokenizer",           # Tokenizer
                "antlr4-python3-runtime==4.9.3",  # Abhängigkeit von omegaconf
            ]
            for dep in cb_deps:
                dep_imp = dep.split("==")[0].replace("-", "_").lower()
                chk_dep = subprocess.run(
                    [python_exe, "-c", f"import {dep_imp}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if chk_dep.returncode != 0:
                    ok_dep = _pip(["install", dep, "--no-cache-dir"], timeout=120)
                    if not ok_dep:
                        # Fallback mit --no-deps
                        ok_dep = _pip(["install", dep, "--no-cache-dir", "--no-deps"], timeout=60)
                    log(f"    {dep}: {'✓' if ok_dep else 'fehlgeschlagen'}", "SUCCESS" if ok_dep else "WARNING")
                else:
                    log(f"    {dep}: bereits installiert ✓", "INFO")

            # Verifikation
            chk_cb2 = subprocess.run(
                [python_exe, "-c", "from chatterbox.tts import ChatterboxTTS; print('OK')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if b"OK" in chk_cb2.stdout:
                log("  ChatterboxTTS: bereit ✓", "SUCCESS")
            else:
                log(f"  ChatterboxTTS: immer noch nicht verfügbar — {chk_cb2.stderr.decode(errors='replace')[-200:]}", "WARNING")

            # torch CUDA sofort wiederherstellen (sicherheitshalber immer)
            log("  Stelle torch CUDA sicher...", "INFO")
            torch_cache_cb = os.path.join(setup_cache, f"torch_{cu_tag}")
            cached_cb = [f for f in os.listdir(torch_cache_cb) if f.endswith(".whl")] \
                        if os.path.isdir(torch_cache_cb) else []
            if len(cached_cb) >= 3:
                _pip(["install", "torch", "torchvision", "torchaudio",
                      "--find-links", torch_cache_cb, "--no-index"], timeout=300)
            else:
                _pip(["install", "torch", "torchvision", "torchaudio",
                      "--index-url", torch_index, "--no-cache-dir"], timeout=900)

            # Verifikation
            chk_t = subprocess.run(
                [python_exe, "-c",
                 "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            out_t = chk_t.stdout.decode(errors="replace").strip()
            if out_t.startswith("True"):
                log(f"  torch CUDA gesichert ✓ — {out_t}", "SUCCESS")
            else:
                log(f"  ⚠️  torch CUDA Problem: {out_t}", "WARNING")

        log("[ComfyUI-Install] Custom Node Dependencies installiert ✓", "SUCCESS")

        # ── Startskript erstellen ─────────────────────────────────────────────
        log("[ComfyUI-Install] Schritt 6/6: Erstelle Startskript...", "INFO")
        bat_path = os.path.join(comfyui_dir, "start_comfyui.bat")
        bat_content = (
            "@echo off\n"
            "echo Starte ComfyUI...\n"
            f'"{python_exe}" main.py --listen\n'
            "pause\n"
        )
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
            log(f"[ComfyUI-Install] Startskript: {bat_path}", "INFO")
        except Exception:
            pass

        log("", "INFO")
        log("══════════════════════════════════════════════════════", "SUCCESS")
        log("  ComfyUI-Installation abgeschlossen! ✅", "SUCCESS")
        log(f"  Pfad: {comfyui_dir}", "SUCCESS")
        log("══════════════════════════════════════════════════════", "SUCCESS")

        # ── Schritt 7: ComfyUI direkt starten ────────────────────────────────
        log("[ComfyUI-Install] Schritt 7/7 (Bonus): Starte ComfyUI...", "INFO")

        # Port 8188 bereinigen — laufende Instanz vom letzten Installer-Lauf beenden
        _kill_comfyui_port(8188, log_cb=log)

        # CUDA pruefen — falls kein CUDA: --cpu Flag
        _cuda_ok = False
        try:
            _r = subprocess.run(
                [python_exe, "-c", "import torch; print(torch.cuda.is_available())"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, cwd=comfyui_dir,
            )
            _cuda_ok = _r.stdout.decode(errors="replace").strip() == "True"
        except Exception:
            pass

        _start_cmd = [python_exe, "main.py", "--listen",
                      "--database-url",
                      f"sqlite:///{os.path.join(comfyui_dir, 'user', 'comfyui_lyra.db')}",
                      ]  # PYTHONIOENCODING env loest tqdm stderr OSError
        if not _cuda_ok:
            _start_cmd.append("--cpu")
            log("[ComfyUI] Kein CUDA — starte im CPU-Modus (--cpu).", "WARNING")
        else:
            log("[ComfyUI] CUDA aktiv ✓", "SUCCESS")

        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            _comfy_env = os.environ.copy()
            _comfy_env["PYTHONIOENCODING"]         = "utf-8"
            _comfy_env["PYTHONLEGACYWINDOWSSTDIO"] = "0"
            _comfy_env["PYTHONUNBUFFERED"]         = "1"
            _comfy_env["NO_COLOR"]                 = "1"
            _comfy_env["TERM"]                     = "dumb"
            _comfy_env["FORCE_COLOR"]              = "0"

            proc = subprocess.Popen(
                _start_cmd,
                cwd           = comfyui_dir,
                stdout        = subprocess.PIPE,
                stderr        = subprocess.STDOUT,
                bufsize       = 1,
                creationflags = creation_flags,
                encoding      = "utf-8",
                errors        = "replace",
                env           = _comfy_env,
            )
            log(f"[ComfyUI] Prozess gestartet (PID {proc.pid})", "SUCCESS")
            log(f"[ComfyUI] Erreichbar unter: http://127.0.0.1:8188", "INFO")
            log("[ComfyUI] Logs folgen — warte auf 'To see the GUI go to:'", "INFO")

            # Log-Stream-Thread (daemon — endet mit Hauptprozess)
            _noise = (
                "an error occurred while fetching",
                "expecting value: line 1 column 1",
                "cannot connect to comfyregistry",
                "due to a network error, switching to local mode",
                "cannot schedule new futures after shutdown",
                "a new release of pip is available",
                "to update, run: python",
                "ignoring invalid distribution",
                "logging failed: [winerror 32]",
                "default cache updated:",
            )
            def _stream():
                try:
                    for line in proc.stdout:
                        line = line.rstrip()
                        if not line:
                            continue
                        lo = line.lower()
                        if any(p in lo for p in _noise):
                            lvl = "INFO"
                        elif any(w in lo for w in ("error", "exception", "traceback")):
                            lvl = "ERROR"
                        elif any(w in lo for w in ("warn", "missing")):
                            lvl = "WARNING"
                        elif any(w in line.lower() for w in ("loaded", "ready", "started",
                                                              "listening", "to see the gui")):
                            lvl = "SUCCESS"
                        else:
                            lvl = "INFO"
                        log(f"  [ComfyUI] {line}", lvl)
                except Exception:
                    pass
                log("[ComfyUI] Prozess beendet.", "WARNING")

            threading.Thread(target=_stream, daemon=True).start()

        except Exception as e:
            log(f"[ComfyUI] Auto-Start fehlgeschlagen: {e}", "WARNING")
            log(f"  → Manuell starten: {bat_path}", "INFO")

        return True

    def run_production(self, scene_filter: str = None) -> dict:
        """Runs the full production pipeline.

        Args:
            scene_filter: If set, only process this scene ID.
        Returns:
            Final status dict.
        """
        self._skipped_workers.clear()  # reset per-session worker blacklist
        self.log("========================================", "INFO")
        self.log("LYRA -- CINEMATIC COORDINATOR GESTARTET", "INFO")
        self.log(f"Storage: {self.storage_root}", "INFO")
        self.log(f"Dry run: {self.dry_run}", "INFO")
        self.log("========================================", "INFO")

        # Phase 0: setup
        self.setup_dirs()
        config = self.write_production_config()
        self.write_visual_bible()
        self.write_screenplay()

        status = self.load_status()
        if not status.get("started"):
            status["started"] = datetime.datetime.now().isoformat()

        # Phase 1: Szenen produzieren
        scenes_to_run = _get_active_scenes() if not scene_filter else [
            s for s in _get_active_scenes() if s["id"] == scene_filter
        ]
        total = len(scenes_to_run)
        done  = 0
        self.log(f"\nPhase 1: {total} scene(s) processing...", "INFO")
        for scene in scenes_to_run:
            if self._stop.is_set():
                break
            self.generate_scene(scene, status)
            done += 1
            self.log(f"  Progress: {done}/{total}", "INFO")
            if self._refresh_cb:
                self._refresh_cb()

        # Phase 2: Summary
        # Refresh GUI scene list to show updated prompt/clip status
        if hasattr(self, "_refresh_cb") and self._refresh_cb:
            self._refresh_cb()
        self.log("\nPhase 2: Summary", "INFO")
        self.log(f"  Scenes processed: {done}/{total}", "SUCCESS")
        self.log(f"  Prompts in:         {os.path.join(self.storage_root, 'szenen')}", "INFO")
        self.log(f"  Master plan:         {os.path.join(self.storage_root, 'config')}", "INFO")
        self.log(f"  Screenplay:           {os.path.join(self.storage_root, 'audio', 'screenplay.txt')}", "INFO")
        self.log("", "INFO")
        self.log("Next steps:", "INFO")
        self.log("  1. Open szenen/<id>/prompt.txt for each clip", "INFO")
        self.log("  2. Copy Enhanced Prompt into the respective AI tool", "INFO")
        self.log("  3. Save finished clip to szenen/<id>/<tool>/clip_001.mp4", "INFO")
        self.log("  4. When all clips are done: CapCut for final cut", "INFO")
        self.log("", "INFO")
        self.log("LYRA has completed her task.", "SUCCESS")

        status["completed"] = datetime.datetime.now().isoformat()
        self.save_status(status)
        return status

    def stop(self):
        """Signals the production loop to stop gracefully."""
        self._stop.set()


# ─────────────────────────────────────────────────────────────────────────────
# SCENE EDIT DIALOG
# ─────────────────────────────────────────────────────────────────────────────

class SceneEditDialog(tk.Toplevel):
    """Modal dialog for viewing and editing all attributes of a scene.

    Shows: ID, chapter, title, assigned tool (all workers selectable),
    base prompt, duration, characters, and current prompt.txt content.
    Saves changes back to SCENES list and rewrites prompt.txt on disk.
    """

    # All known cinematic worker types including local ones
    ALL_TOOLS = ["sora", "runway", "seedance", "digen", "myedit", "suno", "capcut",
                 "comfyui_local"]

    def __init__(self, parent, scene: dict, storage_root: str,
                 loaded_workers: list, on_save=None):
        """
        Args:
            parent:         Parent window.
            scene:          Scene dict from SCENES list (edited in-place on save).
            storage_root:   Base production directory for reading/writing prompt.txt.
            loaded_workers: Current workers list (for tool dropdown with API status).
            on_save:        Callback fired after successful save to refresh parent UI.
        """
        super().__init__(parent)
        self.title(f"Edit Scene — {scene['id']}: {scene['title']}")
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self.minsize(700, 620)
        self.grab_set()  # modal

        self._scene        = scene
        self._storage_root = storage_root
        self._workers      = loaded_workers
        self._on_save      = on_save

        # Center relative to parent
        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h   = 740, 660
        self.geometry(f"{w}x{h}+{px+(pw-w)//2}+{py+(ph-h)//2}")

        self._build_ui()
        self._load_values()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        """Builds the full edit dialog: header, fields, prompt area, buttons."""
        # Header
        hdr = tk.Frame(self, bg=COLORS["bg"], pady=10)
        hdr.pack(fill="x", padx=16)
        tk.Label(hdr, text=f"\U0001f3ac  Szene {self._scene['id']}",
                 font=("Segoe UI", 13, "bold"), fg=COLORS["gold"],
                 bg=COLORS["bg"]).pack(side="left")
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x")

        # Fields panel
        fields = tk.LabelFrame(self, text="  Scene Attributes  ",
                                font=("Segoe UI", 10, "bold"), fg=COLORS["accent"],
                                bg=COLORS["panel"], bd=1, relief="flat",
                                highlightbackground=COLORS["border"], highlightthickness=1)
        fields.pack(fill="x", padx=16, pady=(10, 4))

        def row(parent, label, widget_factory, r):
            tk.Label(parent, text=label, font=("Segoe UI", 9), fg=COLORS["dim"],
                     bg=COLORS["panel"], width=14, anchor="e").grid(
                row=r, column=0, padx=(8,4), pady=4, sticky="e")
            w = widget_factory(parent)
            w.grid(row=r, column=1, padx=(0,8), pady=4, sticky="ew")
            parent.columnconfigure(1, weight=1)
            return w

        # ID (readonly)
        self._id_var = tk.StringVar()
        row(fields, "ID:", lambda p: tk.Entry(
            p, textvariable=self._id_var, font=FONT_MONO,
            bg=COLORS["input"], fg=COLORS["dim"],
            state="readonly", relief="flat", bd=3), 0)

        # Chapter
        self._chapter_var = tk.StringVar()
        row(fields, "Chapter:", lambda p: tk.Entry(
            p, textvariable=self._chapter_var, font=FONT_MONO,
            bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=3), 1)

        # Title
        self._title_var = tk.StringVar()
        row(fields, "Title:", lambda p: tk.Entry(
            p, textvariable=self._title_var, font=FONT_MONO,
            bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=3), 2)

        # Duration
        self._duration_var = tk.StringVar()
        row(fields, "Duration (s):", lambda p: tk.Entry(
            p, textvariable=self._duration_var, font=FONT_MONO, width=8,
            bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=3), 3)

        # Characters
        self._chars_var = tk.StringVar()
        row(fields, "Characters:", lambda p: tk.Entry(
            p, textvariable=self._chars_var, font=FONT_MONO,
            bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=3), 4)

        # Tool dropdown — all tools, with API status indicator
        self._tool_var = tk.StringVar()
        def tool_factory(p):
            # Build display values: "sora ✅" or "myedit ❌"
            key_status = {}
            for w in self._workers:
                url      = w.get("url", "")
                is_local = any(x in url for x in ["localhost", "127.0.0.1"])
                has_key  = bool(w.get("api_key", "").strip())
                key_status[w.get("type", "")] = is_local or has_key
            self._tool_display = {}
            display_vals = []
            for t in self.ALL_TOOLS:
                ok  = key_status.get(t, False)
                lbl = f"{t}  {'✅' if ok else '❌'}"
                self._tool_display[lbl] = t
                self._tool_display[t]   = t
                display_vals.append(lbl)
            cb = ttk.Combobox(p, textvariable=self._tool_var,
                              values=display_vals, state="readonly", width=28)
            return cb
        row(fields, "AI Tool:", tool_factory, 5)

        # Status (readonly)
        self._status_var = tk.StringVar()
        row(fields, "Status:", lambda p: tk.Entry(
            p, textvariable=self._status_var, font=FONT_MONO,
            bg=COLORS["input"], fg=COLORS["dim"],
            state="readonly", relief="flat", bd=3), 6)

        # Clips — dynamic dropdown with right-click context menu
        clips_row = tk.Frame(fields, bg=COLORS["panel"])
        clips_row.grid(row=7, column=0, columnspan=2, sticky="ew", padx=8, pady=4)
        fields.columnconfigure(1, weight=1)
        tk.Label(clips_row, text="Clips:", font=("Segoe UI", 9), fg=COLORS["dim"],
                 bg=COLORS["panel"], width=14, anchor="e").pack(side="left", padx=(0, 4))
        self._clip_var = tk.StringVar(value="— keine Clips —")
        self._clip_cb  = ttk.Combobox(clips_row, textvariable=self._clip_var,
                                       state="readonly", width=52,
                                       font=("Consolas", 9))
        self._clip_cb.pack(side="left", fill="x", expand=True)
        self._clip_cb.bind("<Button-3>", self._on_clip_rightclick)
        self._clip_cb.bind("<<ComboboxSelected>>", lambda e: self._clip_cb.selection_clear())
        # Right-click context menu
        self._clip_menu = tk.Menu(self, tearoff=0,
                                   bg=COLORS["panel"], fg=COLORS["text"],
                                   activebackground=COLORS["hover"])
        self._clip_menu.add_command(label="▶  Play",          command=self._clip_play)
        self._clip_menu.add_command(label="📂  Open Location", command=self._clip_open_location)
        self._clip_menu.add_separator()
        self._clip_menu.add_command(label="🗑  Delete Clip",   command=self._clip_delete)
        self._clips_var = tk.StringVar()  # kept for compat

        # Prompt text area
        prompt_lf = tk.LabelFrame(self, text="  Prompt (editable)  ",
                                   font=("Segoe UI", 10, "bold"), fg=COLORS["gold"],
                                   bg=COLORS["panel"], bd=1, relief="flat",
                                   highlightbackground=COLORS["border"], highlightthickness=1)
        prompt_lf.pack(fill="both", expand=True, padx=16, pady=4)

        # Tab strip: Base | Enhanced
        tab_row = tk.Frame(prompt_lf, bg=COLORS["panel"])
        tab_row.pack(fill="x", padx=6, pady=(4,0))
        self._prompt_mode = tk.StringVar(value="enhanced")
        for label, val in [("📝 Enhanced (DeepSeek)", "enhanced"), ("📄 Base", "base")]:
            tk.Radiobutton(tab_row, text=label, variable=self._prompt_mode,
                           value=val, command=self._on_tab_switch,
                           font=("Segoe UI", 9), fg=COLORS["text"],
                           bg=COLORS["panel"], selectcolor=COLORS["input"],
                           activebackground=COLORS["panel"]).pack(side="left", padx=4)

        self._prompt_text = scrolledtext.ScrolledText(
            prompt_lf, font=("Consolas", 9), bg=COLORS["bg"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=4, height=10, wrap="word")
        self._prompt_text.pack(fill="both", expand=True, padx=6, pady=6)

        # Buttons
        btn_row = tk.Frame(self, bg=COLORS["bg"])
        btn_row.pack(fill="x", padx=16, pady=(4,12))
        tk.Button(btn_row, text="💾  Save",
                  command=self._save, font=("Segoe UI", 10, "bold"),
                  bg=COLORS["btn"], fg=COLORS["success"],
                  activebackground=COLORS["hover"], relief="flat",
                  padx=18, pady=8, cursor="hand2").pack(side="left", padx=4)
        tk.Button(btn_row, text="🗑  Delete Prompt",
                  command=self._delete_prompt, font=("Segoe UI", 10),
                  bg=COLORS["btn"], fg=COLORS["warn"],
                  activebackground=COLORS["hover"], relief="flat",
                  padx=12, pady=8, cursor="hand2").pack(side="left", padx=4)
        tk.Button(btn_row, text="✖  Close",
                  command=self.destroy, font=("Segoe UI", 10),
                  bg=COLORS["btn"], fg=COLORS["dim"],
                  activebackground=COLORS["hover"], relief="flat",
                  padx=12, pady=8, cursor="hand2").pack(side="right", padx=4)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_values(self):
        """Populates all fields from the scene dict and prompt.txt on disk."""
        s = self._scene
        self._id_var.set(s["id"])
        self._chapter_var.set(s.get("chapter", ""))
        self._title_var.set(s.get("title", ""))
        self._duration_var.set(str(s.get("duration_sec", "")))
        self._chars_var.set(", ".join(s.get("chars", [])))

        # Set tool dropdown to current value with status icon
        cur_tool = s.get("tool", "sora")
        key_status = {}
        for w in self._workers:
            url = w.get("url", "")
            is_local = any(x in url for x in ["localhost", "127.0.0.1"])
            key_status[w.get("type","")] = is_local or bool(w.get("api_key","").strip())
        ok  = key_status.get(cur_tool, False)
        self._tool_var.set(f"{cur_tool}  {'✅' if ok else '❌'}")

        # Clip count and status from disk
        clip_dir   = os.path.join(self._storage_root, "szenen", s["id"], cur_tool)
        self._clip_files = []
        if os.path.isdir(clip_dir):
            self._clip_files = sorted([
                os.path.join(clip_dir, f) for f in os.listdir(clip_dir)
                if f.endswith(".mp4") or f.endswith(".mp4.placeholder")
            ])
        if self._clip_files:
            labels = [os.path.basename(p) for p in self._clip_files]
            self._clip_cb.config(values=labels)
            self._clip_var.set(labels[0])
            self._status_var.set(f"🎬 {len(self._clip_files)} Clip(s) vorhanden")
        else:
            self._clip_cb.config(values=[])
            self._clip_var.set("— keine Clips —")


        prompt_path = os.path.join(self._storage_root, "szenen", s["id"], "prompt.txt")
        if os.path.isfile(prompt_path):
            self._status_var.set("📝 Prompt vorhanden")
            self._load_prompt_file(prompt_path)
        else:
            self._status_var.set("📝 Kein Prompt")
            self._prompt_text.delete("1.0", "end")
            self._prompt_text.insert("1.0", s.get("prompt", ""))

    def _selected_clip_path(self) -> str | None:
        """Returns the full path of the currently selected clip, or None."""
        sel = self._clip_var.get()
        if not sel or sel.startswith("—"):
            return None
        for p in self._clip_files:
            if os.path.basename(p) == sel:
                return p
        return None

    def _on_clip_rightclick(self, event):
        """Shows the right-click context menu on the clip dropdown."""
        if self._clip_var.get().startswith("—"):
            return
        try:
            self._clip_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._clip_menu.grab_release()

    def _clip_play(self):
        """Opens the selected clip in the default Windows media player."""
        path = self._selected_clip_path()
        if not path or not os.path.isfile(path):
            messagebox.showinfo("No Clip", "Clip file not found.")
            return
        import subprocess
        subprocess.Popen(["start", "", path], shell=True)

    def _clip_open_location(self):
        """Opens the folder containing the selected clip in Explorer."""
        path = self._selected_clip_path()
        if not path:
            return
        folder = os.path.dirname(path)
        import subprocess
        if os.path.isfile(path):
            subprocess.Popen(["explorer", "/select,", path])
        elif os.path.isdir(folder):
            subprocess.Popen(["explorer", folder])

    def _clip_delete(self):
        """Deletes the selected clip after confirmation."""
        path = self._selected_clip_path()
        if not path:
            return
        name = os.path.basename(path)
        if not messagebox.askyesno("Delete Clip",
                                    f"Really delete clip?\n\n{name}"):
            return
        try:
            os.remove(path)
            # Refresh clip list
            self._clip_files = [p for p in self._clip_files if p != path]
            if self._clip_files:
                labels = [os.path.basename(p) for p in self._clip_files]
                self._clip_cb.config(values=labels)
                self._clip_var.set(labels[0])
                self._status_var.set(f"🎬 {len(self._clip_files)} Clip(s) vorhanden")
            else:
                self._clip_cb.config(values=[])
                self._clip_var.set("— keine Clips —")
                self._status_var.set("📝 Prompt vorhanden" if os.path.isfile(
                    os.path.join(self._storage_root, "szenen",
                                 self._scene["id"], "prompt.txt")) else "📝 Kein Prompt")
            if self._on_save:
                self._on_save()
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

    def _load_prompt_file(self, path: str):
        """Reads prompt.txt and loads the appropriate section into the text area."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self._raw_prompt_file = content
            self._on_tab_switch()
        except Exception as e:
            self._prompt_text.delete("1.0", "end")
            self._prompt_text.insert("1.0", f"Fehler beim Lesen: {e}")

    def _on_tab_switch(self):
        """Switches between Base and Enhanced prompt view."""
        raw = getattr(self, "_raw_prompt_file", None)
        self._prompt_text.delete("1.0", "end")
        if raw is None:
            self._prompt_text.insert("1.0", self._scene.get("prompt", ""))
            return
        mode = self._prompt_mode.get()
        if mode == "enhanced":
            # Extract Enhanced section
            marker = "## Enhanced Prompt (DeepSeek)\n"
            idx = raw.find(marker)
            if idx >= 0:
                section = raw[idx + len(marker):]
                # Cut at next ## section if present
                next_sec = section.find("\n##")
                text = section[:next_sec].strip() if next_sec >= 0 else section.strip()
            else:
                text = "(Noch kein Enhanced Prompt — Produktion starten)"
        else:
            marker = "## Base Prompt\n"
            idx = raw.find(marker)
            if idx >= 0:
                section = raw[idx + len(marker):]
                next_sec = section.find("\n##")
                text = section[:next_sec].strip() if next_sec >= 0 else section.strip()
            else:
                text = self._scene.get("prompt", "")
        self._prompt_text.insert("1.0", text)

    # ── Save / Delete ─────────────────────────────────────────────────────────

    def _save(self):
        """Saves edited values back to the SCENES dict and rewrites prompt.txt."""
        s = self._scene

        # Update SCENES dict in-place
        s["chapter"]      = self._chapter_var.get().strip()
        s["title"]        = self._title_var.get().strip()
        s["chars"]        = [c.strip() for c in self._chars_var.get().split(",") if c.strip()]
        try:
            s["duration_sec"] = int(self._duration_var.get().strip())
        except ValueError:
            pass
        # Resolve tool from display string
        tool_raw = self._tool_var.get()
        s["tool"] = self._tool_display.get(tool_raw, tool_raw.split()[0])

        # Rewrite prompt.txt: update the currently shown section
        prompt_path = os.path.join(self._storage_root, "szenen", s["id"], "prompt.txt")
        new_text    = self._prompt_text.get("1.0", "end").strip()
        mode        = self._prompt_mode.get()

        if os.path.isfile(prompt_path):
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    existing = f.read()
                if mode == "enhanced":
                    marker = "## Enhanced Prompt (DeepSeek)\n"
                else:
                    marker = "## Base Prompt\n"
                idx = existing.find(marker)
                if idx >= 0:
                    after_marker = existing[idx + len(marker):]
                    next_sec     = after_marker.find("\n##")
                    if next_sec >= 0:
                        tail = after_marker[next_sec:]
                        existing = existing[:idx + len(marker)] + new_text + "\n" + tail
                    else:
                        existing = existing[:idx + len(marker)] + new_text + "\n"
                with open(prompt_path, "w", encoding="utf-8") as f:
                    f.write(existing)
                self._raw_prompt_file = existing
            except Exception as e:
                messagebox.showerror("Fehler", f"Prompt.txt speichern fehlgeschlagen:\n{e}")
                return
        else:
            # Write new prompt.txt with base content
            os.makedirs(os.path.dirname(prompt_path), exist_ok=True)
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(f"# Scene {s['id']}: {s['title']}\n")
                f.write(f"# Tool: {s['tool']}\n")
                f.write(f"# Duration: {s.get('duration_sec',0)}s\n")
                f.write(f"# Characters: {', '.join(s.get('chars',[]))}\n\n")
                f.write(f"## Base Prompt\n{s.get('prompt','')}\n\n")
                f.write(f"## Enhanced Prompt (DeepSeek)\n{new_text}\n")

        if self._on_save:
            self._on_save()
        messagebox.showinfo("Gespeichert", f"Szene {s['id']} gespeichert ✓")

    def _delete_prompt(self):
        """Deletes prompt.txt for this scene after confirmation."""
        prompt_path = os.path.join(self._storage_root, "szenen",
                                   self._scene["id"], "prompt.txt")
        if not os.path.isfile(prompt_path):
            messagebox.showinfo("Info", "Kein Prompt vorhanden.")
            return
        if messagebox.askyesno("Delete Prompt",
                                f"prompt.txt für Szene {self._scene['id']} wirklich löschen?\n"
                                "DeepSeek wird beim nächsten Start neu befragt."):
            try:
                os.remove(prompt_path)
                self._status_var.set("📝 Kein Prompt")
                self._prompt_text.delete("1.0", "end")
                self._prompt_text.insert("1.0", self._scene.get("prompt", ""))
                self._raw_prompt_file = None
                if self._on_save:
                    self._on_save()
            except Exception as e:
                messagebox.showerror("Fehler", str(e))



# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

class ProducerApp(tk.Tk):
    """Dark-themed GUI for the Ison-Codex Film Production Orchestrator."""

    def __init__(self):
        """Initializes window, builds UI, creates orchestrator."""
        super().__init__()
        self.title(APP_TITLE)
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self.minsize(900, 700)
        self._center()
        self._build_ui()
        self._orchestrator: ProductionOrchestrator | None = None
        self._loaded_workers: list = []
        self._script_path: str = ""
        self._stop_import  = __import__("threading").Event()
        self.after(300, self._reload_workers)
        self.after(500, self._init_active_scenes)

    def _center(self):
        """Centers the window on screen."""
        self.update_idletasks()
        w, h = 980, 760
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):
        """Builds full UI: header, config panel, scene list, log, buttons."""
        self._build_header()
        self._build_config()
        self._build_scene_panel()
        self._build_log()
        self._build_buttons()

    def _build_header(self):
        """Builds the title bar with visual DNA indicator."""
        hdr = tk.Frame(self, bg=COLORS["bg"], pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="\U0001f3ac  Ison-Codex Film Producer",
                 font=FONT_HEAD, fg=COLORS["gold"], bg=COLORS["bg"]).pack(side="left", padx=20)
        tk.Label(hdr, text="LYRA as Cinematic Coordinator",
                 font=FONT_UI, fg=COLORS["dim"], bg=COLORS["bg"]).pack(side="left")
        tk.Label(hdr, text=f"v{APP_VERSION}",
                 font=FONT_SMALL, fg=COLORS["accent"], bg=COLORS["bg"]).pack(side="right", padx=20)
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x")

    def _init_active_scenes(self):
        """Loads imported scenes from storage or falls back to SCENES default.
        Also writes szenen_default.json once for reset capability.
        """
        global _active_scenes
        storage = os.path.normpath(self._storage_var.get().strip())
        _save_default_scenes(storage)
        imported = _load_active_scenes(storage)
        if imported:
            _active_scenes = imported
            self._log(f"[Scenes] {len(imported)} imported scenes loaded.", "SUCCESS")
        else:
            _active_scenes = list(SCENES)  # copy of default
            self._log(f"[Scenes] {len(SCENES)} default scenes (Ison-Codex) loaded.", "INFO")
        self._refresh_scene_list()

    def _build_config(self):
        """Builds the configuration panel with storage root, API key, and options."""
        frame = tk.LabelFrame(self, text="  Configuration  ",
                               font=FONT_BOLD, fg=COLORS["accent"],
                               bg=COLORS["panel"], bd=1, relief="flat",
                               highlightbackground=COLORS["border"], highlightthickness=1)
        frame.pack(fill="x", padx=16, pady=(12, 4))

        # Storage root
        r1 = tk.Frame(frame, bg=COLORS["panel"])
        r1.pack(fill="x", pady=4, padx=8)
        tk.Label(r1, text="\U0001f4c1  Storage Root:", font=FONT_UI, fg=COLORS["text"],
                 bg=COLORS["panel"], width=18, anchor="w").pack(side="left")
        self._storage_var = tk.StringVar(value=DEFAULT_STORAGE_ROOT)
        tk.Entry(r1, textvariable=self._storage_var, font=FONT_MONO,
                 bg=COLORS["input"], fg=COLORS["text"], relief="flat", bd=4, width=50
                 ).pack(side="left", padx=4)
        self._flat_btn(r1, "  \u2026  ", lambda: self._browse(self._storage_var)).pack(side="left")

        # Workers / API keys status (loaded from workers.json)
        r2 = tk.Frame(frame, bg=COLORS["panel"])
        r2.pack(fill="x", pady=4, padx=8)
        tk.Label(r2, text="\U0001f4cb  API Keys:", font=FONT_UI, fg=COLORS["text"],
                 bg=COLORS["panel"], width=18, anchor="w").pack(side="left")
        self._workers_status = tk.Label(
            r2, text="Loaded from workers.json (Monitoring Tab)",
            font=FONT_SMALL, fg=COLORS["dim"], bg=COLORS["panel"])
        self._workers_status.pack(side="left")
        self._flat_btn(r2, "\U0001f504 Reload",
                       self._reload_workers).pack(side="left", padx=8)

        # Script Supervisor — Load Script + LLM auswahl
        r_ss = tk.Frame(frame, bg=COLORS["panel"])
        r_ss.pack(fill="x", pady=4, padx=8)
        tk.Label(r_ss, text="🎬 Script Supervisor:",
                 font=FONT_UI, fg=COLORS["text"],
                 bg=COLORS["panel"], width=18, anchor="w").pack(side="left")
        self._script_label = tk.Label(r_ss,
            text="No file selected",
            font=FONT_SMALL, fg=COLORS["dim"], bg=COLORS["panel"])
        self._script_label.pack(side="left", padx=4)
        self._flat_btn(r_ss, "📂 Load Script",
                       self._load_script_file).pack(side="left", padx=(8, 0))

        r_llm = tk.Frame(frame, bg=COLORS["panel"])
        r_llm.pack(fill="x", pady=4, padx=8)
        tk.Label(r_llm, text="LLM for Import:",
                 font=FONT_UI, fg=COLORS["text"],
                 bg=COLORS["panel"], width=18, anchor="w").pack(side="left")
        self._llm_import_var = tk.StringVar()
        self._llm_import_cb  = ttk.Combobox(
            r_llm, textvariable=self._llm_import_var,
            state="readonly", width=36)
        self._llm_import_cb.pack(side="left", padx=4)
        self._gen_scenes_btn = tk.Button(
            r_llm, text="🎬 Generate Scenes",
            command=self._import_script_and_generate_scenes,
            font=FONT_BOLD, bg=COLORS["btn"], fg=COLORS["gold"],
            activebackground=COLORS["hover"], relief="flat",
            padx=14, pady=6, cursor="hand2", state="disabled")
        self._gen_scenes_btn.pack(side="left", padx=(8, 0))
        self._flat_btn(r_llm, "🔄 Reset (Ison-Codex)",
                       self._reset_to_default_scenes).pack(side="left", padx=(8, 0))
        self._flat_btn(r_llm, "■ Cancel Import",
                       lambda: self._stop_import.set()).pack(side="left", padx=(4, 0))

        # Options
        r3 = tk.Frame(frame, bg=COLORS["panel"])
        r3.pack(fill="x", pady=(4, 8), padx=8)
        self._dry_run_var = tk.BooleanVar(value=True)
        tk.Checkbutton(r3, text="Dry Run (prompt files only, NO DeepSeek, no real API calls)",
                       variable=self._dry_run_var, font=FONT_UI,
                       fg=COLORS["text"], bg=COLORS["panel"],
                       selectcolor=COLORS["input"], activebackground=COLORS["panel"]
                       ).pack(side="left")

    def _build_scene_panel(self):
        """Builds the scene list with chapter grouping and status display."""
        frame = tk.LabelFrame(self, text="  Scenes -- Ison-Codex  ",
                               font=FONT_BOLD, fg=COLORS["gold"],
                               bg=COLORS["panel"], bd=1, relief="flat",
                               highlightbackground=COLORS["border"], highlightthickness=1)
        frame.pack(fill="x", padx=16, pady=4)

        # Scrollable listbox
        inner = tk.Frame(frame, bg=COLORS["panel"])
        inner.pack(fill="both", expand=True)
        # Header label — aligned to listbox columns
        # Format: [PRODUCER] API  SCENE   PROMPT  CLIPS  TITLE
        hdr_text = "  Producer    API  Scene   Prompt  Clips  Title"
        tk.Label(inner, text=hdr_text, font=FONT_MONO,
                 bg=COLORS["panel"], fg=COLORS["dim"],
                 anchor="w").pack(side="top", fill="x", padx=2)
        tk.Frame(inner, bg=COLORS["border"], height=1).pack(side="top", fill="x")

        sb = tk.Scrollbar(inner, orient="vertical")
        sb.pack(side="right", fill="y")
        self._scene_list = tk.Listbox(inner, font=FONT_MONO, bg=COLORS["bg"],
                                       fg=COLORS["text"], height=8,
                                       selectbackground=COLORS["hover"],
                                       yscrollcommand=sb.set, relief="flat",
                                       activestyle="none",
                                       selectmode="extended")
        self._scene_list.pack(side="left", fill="both", expand=True)
        sb.config(command=self._scene_list.yview)
        self._scene_list.bind("<Double-Button-1>", self._on_scene_double_click)
        self._scene_list.bind("<Button-3>",        self._on_scene_rightclick)

        # Right-click context menu for scene list
        self._scene_ctx_menu = tk.Menu(self, tearoff=0,
                                        bg=COLORS["panel"], fg=COLORS["text"],
                                        activebackground=COLORS["hover"])
        self._scene_ctx_menu.add_command(
            label="▶ Produce selected scene(s)",
            command=self._run_selected_scenes)
        self._scene_ctx_menu.add_separator()
        self._scene_ctx_menu.add_command(
            label="🗑  Delete prompt(s) (re-query LLM)",
            command=self._delete_selected_prompts)
        self._scene_ctx_menu.add_command(
            label="🎬  Delete clip(s)",
            command=self._delete_selected_clips)
        self._scene_ctx_menu.add_command(
            label="📂  Open scene folder",
            command=self._open_selected_scene_folder)

        # TOTAL row context menu
        self._total_ctx_menu = tk.Menu(self, tearoff=0,
                                        bg=COLORS["panel"], fg=COLORS["text"],
                                        activebackground=COLORS["hover"])
        self._total_ctx_menu.add_command(
            label="📦  Generate master prompt (all scenes)",
            command=self._generate_total_prompt)
        self._total_ctx_menu.add_command(
            label="📂  Open TOTAL folder",
            command=self._open_total_folder)

        for s in _get_active_scenes():
            worker_name = s["tool"].upper()
            self._scene_list.insert("end",
                f"  [{worker_name:8s}]   ❓  {s['id']:6s}  📝--  🎬-  {s['title']}")
        # Status icons updated by _reload_workers()

        # Single scene run button
        btn_frame = tk.Frame(frame, bg=COLORS["panel"])
        btn_frame.pack(fill="x", pady=(4, 8), padx=8)
        self._action_btn(btn_frame, "\u25b6 Nur diese Szene",
                         self._run_single_scene, COLORS["accent"]).pack(side="left")
        tk.Label(btn_frame, text="(Select Scene + klicken)",
                 font=FONT_SMALL, fg=COLORS["dim"], bg=COLORS["panel"]).pack(side="left", padx=8)

    def _build_log(self):
        """Builds the scrollable log output area."""
        lf = tk.LabelFrame(self, text="  Production Log  ",
                            font=FONT_BOLD, fg=COLORS["dim"],
                            bg=COLORS["panel"], bd=1, relief="flat",
                            highlightbackground=COLORS["border"], highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=16, pady=4)
        self._log_area = scrolledtext.ScrolledText(
            lf, font=FONT_MONO, bg=COLORS["bg"], fg=COLORS["text"],
            insertbackground=COLORS["accent"], relief="flat", bd=6,
            state="disabled", wrap="word")
        self._log_area.pack(fill="both", expand=True, padx=6, pady=6)
        self._log_area.tag_config("SUCCESS", foreground=COLORS["success"])
        self._log_area.tag_config("WARNING", foreground=COLORS["warn"])
        self._log_area.tag_config("ERROR",   foreground=COLORS["error"])
        self._log_area.tag_config("INFO",    foreground=COLORS["text"])
        self._log(f"Ison-Codex Film Producer v{APP_VERSION} bereit.", "SUCCESS")
        self._log(f"Storage: {DEFAULT_STORAGE_ROOT}", "INFO")
        self._log("DeepSeek active — prompts will be enhanced via API.", "INFO")
        self._log("Dry Run disabled. Enable for prompt generation only without API calls.", "INFO")

    def _build_buttons(self):
        """Builds the main action buttons."""
        bf = tk.Frame(self, bg=COLORS["bg"])
        bf.pack(fill="x", padx=16, pady=(4, 14))
        self._action_btn(bf, "\U0001f3ac  START PRODUCTION",
                         self._run_full_production, COLORS["gold"]).pack(side="left", padx=4)
        self._action_btn(bf, "\U0001f4c2  Open Storage",
                         self._open_storage, COLORS["accent"]).pack(side="left", padx=4)
        # ── ComfyUI-Installations-Button (neu v1.1.0) ─────────────────────────
        self._action_btn(bf, "\U0001f5a5\ufe0f  Install ComfyUI",
                         self._on_install_comfyui, COLORS["success"]).pack(side="left", padx=4)
        self._flat_btn(bf, "\U0001f50d  ComfyUI Nodes",
                       self._on_diagnose_comfyui).pack(side="left", padx=4)
        self._flat_btn(bf, "\U0001f5d1  Clear Log", self._clear_log).pack(side="right", padx=4)
        self._action_btn(bf, "\u25a0  STOP",
                         self._stop_production, COLORS["error"]).pack(side="right", padx=4)

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _flat_btn(self, parent, text, cmd):
        """Returns a small flat button with hover effect."""
        b = tk.Button(parent, text=text, command=cmd, font=FONT_SMALL,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      activebackground=COLORS["hover"], activeforeground=COLORS["accent"],
                      relief="flat", bd=0, padx=10, pady=5, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=COLORS["btn"]))
        return b

    def _action_btn(self, parent, text, cmd, color):
        """Returns a prominent action button with the given foreground color."""
        b = tk.Button(parent, text=text, command=cmd, font=FONT_BOLD,
                      bg=COLORS["btn"], fg=color,
                      activebackground=COLORS["hover"], activeforeground=color,
                      relief="flat", bd=0, padx=18, pady=9, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=COLORS["btn"]))
        return b

    def _browse(self, var):
        """Opens a directory picker, updates the StringVar and saves the path."""
        d = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser("~"))
        if d:
            var.set(os.path.normpath(d))
            self._save_storage_root(var.get())

    def _save_storage_root(self, path: str):
        """Persists the storage root to ~/.openclaw/ison_producer.json."""
        cfg_path = os.path.join(os.path.expanduser("~"), ".openclaw", "ison_producer.json")
        try:
            os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump({"storage_root": path}, f, indent=2)
        except Exception:
            pass

    # ── Actions ────────────────────────────────────────────────────────────────

    def _scene_storage_status(self, scene: dict, storage_root: str) -> tuple[bool, int]:
        """Returns (prompt_exists, clip_count) for a scene from the storage directory.

        prompt_exists: True if szenen/<id>/prompt.txt exists.
        clip_count:    Number of .mp4 / .mp4.placeholder files found across all tool subdirs.
        """
        scene_dir   = os.path.join(storage_root, "szenen", scene["id"])
        prompt_path = os.path.join(scene_dir, "prompt.txt")
        prompt_ok   = os.path.isfile(prompt_path)
        clip_count  = 0
        if os.path.isdir(scene_dir):
            for root, dirs, files in os.walk(scene_dir):
                for f in files:
                    if f.endswith(".mp4") or f.endswith(".mp4.placeholder"):
                        clip_count += 1
        return prompt_ok, clip_count

    def _refresh_scene_list(self):
        """Refreshes the full scene list with tool, API, prompt, clip and title status."""
        storage = os.path.normpath(self._storage_var.get().strip())
        key_status = {}
        for w in self._loaded_workers:
            url      = w.get("url", "")
            is_local = any(x in url for x in ["localhost", "127.0.0.1"])
            has_key  = bool(w.get("api_key", "").strip())
            key_status[w.get("type", "")] = is_local or has_key

        self._scene_list.delete(0, "end")
        total_prompts = 0
        for s in _get_active_scenes():
            tool        = s["tool"]
            api_ok      = key_status.get(tool, False)
            api_icon    = "✅" if api_ok  else "❌"
            prompt_ok, clips = self._scene_storage_status(s, storage)
            prompt_icon = "📝✅" if prompt_ok else "📝--"
            clip_icon   = f"🎬{clips}" if clips > 0 else "🎬-"
            self._scene_list.insert("end",
                f"  [{tool.upper():8s}]   {api_icon}  {s['id']:6s}  "
                f"{prompt_icon:4s}  {clip_icon:3s}  {s['title']}")
            if prompt_ok:
                total_prompts += 1
        # ── TOTAL row ──────────────────────────────────────────────────────
        total_dir   = os.path.join(storage, "szenen", "TOTAL")
        total_files = []
        if os.path.isdir(total_dir):
            total_files = [f for f in os.listdir(total_dir)
                           if f.endswith(".txt") or f.endswith(".md")]
        total_icon  = f"📦{len(total_files)}" if total_files else "📦-"
        self._scene_list.insert("end", "")
        self._scene_list.insert("end",
            "  " + "-" * 68)
        total_label  = f"  [{'TOTAL':8s}]   {'--':2s}  {'ALL':6s}  "
        prompt_count = f"{'📝' + str(total_prompts):4s}"
        total_row    = (total_label + prompt_count +
                        f"  {total_icon:4s}  Master-Prompt aller {len(_get_active_scenes())} Szenen")
        self._scene_list.insert("end", total_row)

    def _on_scene_double_click(self, event=None):
        """Opens SceneEditDialog for a scene, or generates TOTAL prompt if last rows clicked."""
        sel = self._scene_list.curselection()
        if not sel:
            return
        scene_idx = sel[0]
        # Last 3 rows are separator + TOTAL — handle separately
        if scene_idx >= len(_get_active_scenes()):
            self._generate_total_prompt()
            return
        storage   = os.path.normpath(self._storage_var.get().strip())
        SceneEditDialog(self, _get_active_scenes()[scene_idx], storage, self._loaded_workers,
                        on_save=self._refresh_scene_list)

    def _on_scene_rightclick(self, event):
        """Shows context menu on right-click. TOTAL row shows its own menu."""
        idx = self._scene_list.nearest(event.y)
        if idx >= 0:
            sel = self._scene_list.curselection()
            if idx not in sel:
                self._scene_list.selection_clear(0, "end")
                self._scene_list.selection_set(idx)
                self._scene_list.activate(idx)
        # TOTAL row (below SCENES)
        if idx >= len(_get_active_scenes()):
            try:
                self._total_ctx_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._total_ctx_menu.grab_release()
            return
        if self._scene_list.curselection():
            try:
                self._scene_ctx_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._scene_ctx_menu.grab_release()

    def _selected_scene_indices(self) -> list[int]:
        """Returns list of selected indices in the scene list."""
        return list(self._scene_list.curselection())

    def _delete_selected_prompts(self):
        """Deletes prompt.txt for all selected scenes after confirmation."""
        indices = self._selected_scene_indices()
        if not indices:
            return
        scenes  = [_get_active_scenes()[i] for i in indices if i < len(_get_active_scenes())]
        ids     = [s["id"] for s in scenes]
        storage = os.path.normpath(self._storage_var.get().strip())

        if not messagebox.askyesno(
            "Delete Prompts",
            f"{len(ids)} prompt(s) will be deleted.\n\n"
            + "\n".join(ids) +
            "\n\nDeepSeek will be queried again on next production run."
        ):
            return

        deleted = 0
        for s in scenes:
            prompt_path = os.path.join(storage, "szenen", s["id"], "prompt.txt")
            if os.path.isfile(prompt_path):
                try:
                    os.remove(prompt_path)
                    deleted += 1
                    self._log(f"[Scene] Prompt deleted: {s['id']}", "INFO")
                except Exception as e:
                    self._log(f"[Scene] Error deleting {s['id']}: {e}", "WARNING")
            else:
                self._log(f"[Scene] No prompt found: {s['id']}", "INFO")

        self._log(f"[Scene] {deleted}/{len(ids)} Prompt(s) gelöscht.", "SUCCESS")
        self._refresh_scene_list()

    def _delete_selected_clips(self):
        """Deletes all clip files for all selected scenes after confirmation."""
        indices = self._selected_scene_indices()
        scenes  = [_get_active_scenes()[i] for i in indices
                   if i < len(_get_active_scenes())]
        if not scenes:
            return
        storage = os.path.normpath(self._storage_var.get().strip())
        # Count total clips first
        clip_list = []
        for s in scenes:
            clip_dir = os.path.join(storage, "szenen", s["id"], s["tool"])
            if os.path.isdir(clip_dir):
                for f in os.listdir(clip_dir):
                    if f.endswith(".mp4") or f.endswith(".mp4.placeholder"):
                        clip_list.append((s["id"], os.path.join(clip_dir, f)))
        if not clip_list:
            self._log("[Scene] No clips found for selected scenes.", "INFO")
            return
        if not messagebox.askyesno(
            "Delete Clips",
            f"Delete {len(clip_list)} clip(s) from {len(scenes)} scene(s)?\n\n"
            + "\n".join(f"  {sid}: {os.path.basename(p)}"
                         for sid, p in clip_list[:10])
            + ("\n  ..." if len(clip_list) > 10 else "")
        ):
            return
        deleted = 0
        for sid, path in clip_list:
            try:
                os.remove(path)
                deleted += 1
                self._log(f"[Scene] Clip deleted: {sid}/{os.path.basename(path)}", "INFO")
            except Exception as e:
                self._log(f"[Scene] Error deleting {sid}: {e}", "WARNING")
        self._log(f"[Scene] {deleted}/{len(clip_list)} clip(s) deleted.", "SUCCESS")
        self._refresh_scene_list()

    def _open_selected_scene_folder(self):
        """Opens the folder of the first selected scene in Explorer."""
        indices = self._selected_scene_indices()
        if not indices or indices[0] >= len(_get_active_scenes()):
            return
        scene   = _get_active_scenes()[indices[0]]
        storage = os.path.normpath(self._storage_var.get().strip())
        folder  = os.path.join(storage, "szenen", scene["id"])
        os.makedirs(folder, exist_ok=True)
        import subprocess
        subprocess.Popen(["explorer", folder])

    def _run_selected_scenes(self):
        """Runs production for all selected scenes."""
        indices = self._selected_scene_indices()
        if not indices:
            return
        scenes = [_get_active_scenes()[i] for i in indices if i < len(_get_active_scenes())]
        if len(scenes) == 1:
            # Reuse existing single-scene path
            self._scene_list.selection_clear(0, "end")
            self._scene_list.selection_set(indices[0])
            self._run_single_scene()
            return
        # Multiple scenes: run each in sequence in a thread
        import threading
        def _run_multi():
            orch = self._make_orchestrator()
            status = orch.load_status()
            for s in scenes:
                if orch._stop.is_set():
                    break
                orch.generate_scene(s, status)
                if orch._refresh_cb:
                    orch._refresh_cb()
        threading.Thread(target=_run_multi, daemon=True).start()

    def _generate_total_prompt(self):
        """Generates a master prompt file combining all scene prompts.

        Reads existing prompt.txt files (Base + Enhanced), groups by chapter,
        and writes a single master file to szenen/TOTAL/YYYY-MM-DD_HH-MM_total.txt.
        Also writes szenen/TOTAL/latest_total.txt for easy access.
        """
        storage    = os.path.normpath(self._storage_var.get().strip())
        total_dir  = os.path.join(storage, "szenen", "TOTAL")
        os.makedirs(total_dir, exist_ok=True)

        import datetime as _dt
        ts       = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M")
        out_path = os.path.join(total_dir, f"{ts}_total.txt")
        latest   = os.path.join(total_dir, "latest_total.txt")

        lines = [
            "# ISON-CODEX -- MASTER PROMPT",
            f"# Generated: {ts}",
            f"# Scenes: {len(_get_active_scenes())}",
            f"# Visual DNA: {VISUAL_DNA['lighting_style']}",
            "",
            "=" * 70,
            "",
        ]

        current_chapter = ""
        found = 0
        for s in _get_active_scenes():
            # Chapter header
            if s["chapter"] != current_chapter:
                current_chapter = s["chapter"]
                lines.append(f"\n## {current_chapter}")
                lines.append("-" * 50)

            prompt_path = os.path.join(storage, "szenen", s["id"], "prompt.txt")
            lines.append(f"\n### {s['id']} — {s['title']} [{s['tool'].upper()}]")

            if os.path.isfile(prompt_path):
                try:
                    with open(prompt_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    # Prefer Enhanced, fall back to Base
                    if "## Enhanced Prompt (DeepSeek)" in content:
                        section = content.split("## Enhanced Prompt (DeepSeek)")[-1]
                        next_sec = section.find("\n##")
                        text = section[:next_sec].strip() if next_sec > 0 else section.strip()
                        lines.append(f"[Enhanced] {text}")
                    elif "## Base Prompt" in content:
                        section = content.split("## Base Prompt")[-1]
                        next_sec = section.find("\n##")
                        text = section[:next_sec].strip() if next_sec > 0 else section.strip()
                        lines.append(f"[Base] {text}")
                    found += 1
                except Exception as e:
                    lines.append(f"[ERROR] {e}")
            else:
                lines.append(f"[Base — kein Prompt generiert] {s['prompt']}")

        lines += [
            "",
            "=" * 70,
            f"# {found}/{len(_get_active_scenes())} Enhanced prompts | {len(_get_active_scenes())-found} Base prompts",
        ]

        content = "\n".join(lines)
        for path in [out_path, latest]:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        self._log(f"[TOTAL] Master prompt saved: {out_path}", "SUCCESS")
        self._log(f"[TOTAL] {found} Enhanced + {len(_get_active_scenes())-found} Base prompts.", "INFO")
        self._refresh_scene_list()

        if messagebox.askyesno("Master Prompt Created",
                                f"Master prompt with {len(_get_active_scenes())} scenes saved.\n\n"
                                f"{out_path}\n\nOpen folder?"):
            import subprocess
            subprocess.Popen(["explorer", "/select,", out_path])

    def _open_total_folder(self):
        """Opens the TOTAL folder in Explorer."""
        storage   = os.path.normpath(self._storage_var.get().strip())
        total_dir = os.path.join(storage, "szenen", "TOTAL")
        os.makedirs(total_dir, exist_ok=True)
        import subprocess
        subprocess.Popen(["explorer", total_dir])

    def _reload_workers(self):
        """Loads workers.json from ~/.openclaw and updates scene list status icons."""
        workers_path = os.path.join(
            os.path.expanduser("~"), ".openclaw", "workers.json")
        try:
            with open(workers_path, "r", encoding="utf-8") as f:
                self._loaded_workers = json.load(f)
            # Build lookup: worker type -> available
            # Local workers (localhost/127.0.0.1) are always available
            # External workers need an api_key
            key_status = {}
            for w in self._loaded_workers:
                wtype = w.get("type", "")
                url   = w.get("url", "")
                is_local = any(x in url for x in ["localhost", "127.0.0.1"])
                has_key  = bool(w.get("api_key", "").strip())
                key_status[wtype] = is_local or has_key
            # Update scene list via shared helper
            self._refresh_scene_list()
            n_ready   = sum(1 for s in SCENES if key_status.get(s["tool"], False))
            n_missing = len(_get_active_scenes()) - n_ready
            missing_str = f"❌ {n_missing} fehlen" if n_missing else "✅ alle bereit"
            self._workers_status.config(
                text=f"workers.json: {len(self._loaded_workers)} Workers · "
                     f"✅ {n_ready} bereit · {missing_str}",
                foreground=COLORS["success"] if not n_missing else COLORS["warn"]
            )
            self._log(f"Workers loaded: {len(self._loaded_workers)} · "
                      f"{n_ready} with API key · {n_missing} without", "INFO")
            self._populate_llm_import_dropdown()
        except FileNotFoundError:
            self._workers_status.config(
                text="❌ workers.json nicht gefunden — Monitoring Tab oeffnen um Workers zu erfassen",
                foreground=COLORS["error"])
            self._log("workers.json nicht gefunden. Monitoring Tab -> Workers eintragen.", "WARNING")
        except Exception as e:
            self._workers_status.config(text=f"❌ Fehler: {e}", foreground=COLORS["error"])
            self._log(f"Workers laden fehlgeschlagen: {e}", "WARNING")

    def _make_orchestrator(self) -> ProductionOrchestrator:
        """Creates a fresh ProductionOrchestrator using API keys from workers.json."""
        return ProductionOrchestrator(
            storage_root = os.path.normpath(self._storage_var.get().strip()),
            workers      = self._loaded_workers,
            log_cb       = self._log,
            dry_run      = self._dry_run_var.get(),
            refresh_cb   = lambda: self.after(0, self._refresh_scene_list),
        )

    def _populate_llm_import_dropdown(self):
        """Populates the LLM import dropdown with all usable workers from workers.json
        plus all locally running Ollama models fetched directly from the Ollama API."""
        llm_workers = []
        self._log(f"[SS] Evaluating {len(self._loaded_workers)} Worker(s) for LLM dropdown:", "INFO")
        for w in self._loaded_workers:
            url      = w.get("url", "").strip()
            key      = w.get("api_key", "").strip()
            wtype    = w.get("type", "").lower()
            name     = w.get("name", wtype)
            self._log(f"[SS]   {name} | type={wtype} | url={url[:40]} | key={'yes' if key else 'no'}", "INFO")
            skip_types = {"sora", "runway", "seedance", "digen", "myedit",
                          "suno", "capcut", "claude_code", "process"}
            if wtype in skip_types:
                continue
            if not url and not key:
                continue
            model = w.get("model", "")
            label = f"{name} ({model})" if model else name
            self._log(f"[SS]     -> ADDED as '{label}'", "INFO")
            llm_workers.append((label, w))

        # Also load all locally running Ollama models directly from the API
        ollama_base = "http://127.0.0.1:11434"
        try:
            import urllib.request as _ur
            with _ur.urlopen(f"{ollama_base}/api/tags", timeout=3) as r:
                tags = json.load(r)
            for m in tags.get("models", []):
                mname = m.get("name", "")
                if not mname:
                    continue
                label = f"Ollama: {mname}"
                llm_workers.append((label, {
                    "type":  "worker",
                    "name":  f"Ollama: {mname}",
                    "url":   ollama_base,
                    "model": mname,
                    "api_key": "",
                }))
            self._log(f"[SS] Ollama: {len(tags.get('models', []))} local models found.", "INFO")
        except Exception as e:
            self._log(f"[SS] Ollama not reachable ({e}) — using workers.json entries only.", "INFO")

        if hasattr(self, "_llm_import_cb"):
            self._llm_import_cb["values"] = [lbl for lbl, _ in llm_workers]
            self._llm_workers_map = {lbl: w for lbl, w in llm_workers}
            if llm_workers:
                self._llm_import_var.set(llm_workers[0][0])
                self._log(f"[SS] {len(llm_workers)} LLM(s) available for import.", "INFO")
            else:
                self._llm_import_var.set("")
                self._log("[SS] Keine externe LLM konfiguriert. "
                          "Bitte im Monitoring-Tab einen OpenAI/DeepSeek-Agenten anlegen.", "WARNING")
            self._update_gen_btn_state()

    def _load_script_file(self):
        """Opens a file dialog to select a script/novel text file."""
        path = filedialog.askopenfilename(
            title="Script / Roman laden",
            filetypes=[("Textdateien", "*.txt *.md *.rst"),
                       ("Alle Dateien", "*.*")]
        )
        if path:
            self._script_path = path
            self._script_label.config(
                text=os.path.basename(path),
                fg=COLORS["success"])
            self._log(f"[SS] Script loaded: {os.path.basename(path)}", "INFO")
            self._update_gen_btn_state()

    def _update_gen_btn_state(self):
        """Enables/disables the Generate Scenes button based on prerequisites."""
        if not hasattr(self, "_gen_scenes_btn"):
            return
        has_file = bool(self._script_path and os.path.isfile(self._script_path))
        has_llm  = bool(self._llm_import_var.get())
        state    = "normal" if (has_file and has_llm) else "disabled"
        self._gen_scenes_btn.config(state=state)

    def _import_script_and_generate_scenes(self):
        """Reads script file, sends to selected LLM, validates JSON, replaces scene list."""
        if not self._script_path or not os.path.isfile(self._script_path):
            messagebox.showwarning("No Script", "Bitte zuerst ein Load Script.")
            return
        llm_label = self._llm_import_var.get()
        worker    = getattr(self, "_llm_workers_map", {}).get(llm_label)
        if not worker:
            messagebox.showwarning("No LLM", "Please select an LLM.")
            return

        self._stop_import.clear()
        self._gen_scenes_btn.config(state="disabled")
        self._log(f"[SS] Starting scene import: {os.path.basename(self._script_path)}", "INFO")
        self._log(f"[SS] LLM: {llm_label}", "INFO")

        import threading
        threading.Thread(target=self._run_scene_import,
                         args=(worker,), daemon=True).start()

    def _run_scene_import(self, worker: dict):
        """Background thread: multi-turn conversation with LLM.

        Step 1: Send full script, ask LLM to list all chapter headings as JSON array.
        Step 2: For each chapter, ask for scenes of that chapter only.
                Full conversation history kept — LLM has complete context throughout.
        Step 3: Merge all results, renumber IDs sequentially, save.

        Each response covers only one chapter — no output truncation possible.
        """
        import urllib.request, urllib.error, re as _re, threading as _th
        global _active_scenes

        try:
            # ── Read script ───────────────────────────────────────────────────
            with open(self._script_path, "r", encoding="utf-8", errors="replace") as f:
                script_text = f.read()
            self._log(f"[SS] Script read: {len(script_text):,} characters.", "INFO")

            # ── Detect API type ───────────────────────────────────────────────
            url   = worker.get("url", "").rstrip("/")
            key   = worker.get("api_key", "")
            model = worker.get("model", "")
            is_ollama = (
                ":11434" in url
                or url == ""
                or (not key and "deepseek.com" not in url and "openai.com" not in url)
            )
            if is_ollama:
                if not url.endswith("/api/chat"):
                    url = url.rstrip("/") + "/api/chat"
                if not model:
                    model = "llama3"
            else:
                if not url.endswith("/chat/completions"):
                    url = url + "/chat/completions"
                if not model:
                    model = "deepseek-chat"

            self._log(f"[SS] Using: {url} (model={model})", "INFO")

            # ── Helper: send one turn, return response text ───────────────────
            def _call_llm(messages: list) -> str:
                if is_ollama:
                    payload = json.dumps({
                        "model":    model,
                        "messages": messages,
                        "stream":   False,
                    }).encode("utf-8")
                    headers = {"Content-Type": "application/json"}
                else:
                    payload = json.dumps({
                        "model":       model,
                        "messages":    messages,
                        "max_tokens":  8192,
                        "temperature": 0.3,
                    }).encode("utf-8")
                    headers = {"Content-Type": "application/json"}
                    if key:
                        headers["Authorization"] = f"Bearer {key}"

                req = urllib.request.Request(url, data=payload, headers=headers)

                _hb_stop = _th.Event()
                def _heartbeat(stop=_hb_stop):
                    elapsed = 0
                    while not stop.is_set():
                        stop.wait(10)
                        if not stop.is_set():
                            elapsed += 10
                            self._log(f"[SS] Waiting... ({elapsed}s)", "INFO")
                _th.Thread(target=_heartbeat, daemon=True).start()

                try:
                    with urllib.request.urlopen(req, timeout=300) as resp:
                        data = json.load(resp)
                finally:
                    _hb_stop.set()

                if "message" in data:
                    return data["message"].get("content", "").strip()
                elif "choices" in data:
                    return data["choices"][0]["message"]["content"].strip()
                return str(data)

            # ── Helper: parse JSON array from LLM response ────────────────────
            def _parse_json(raw: str, label: str):
                raw = _re.sub(r"^```(?:json)?\s*", "", raw)
                raw = _re.sub(r"\s*```$", "", raw).strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as e:
                    self._log(f"[SS] {label} JSON error: {e} — attempting recovery.", "WARNING")
                    last = raw.rfind("},")
                    if last == -1:
                        last = raw.rfind("}")
                    if last > 0:
                        fixed = raw[:last + 1]
                        if not fixed.strip().endswith("]"):
                            fixed += "]"
                        if not fixed.strip().startswith("["):
                            fixed = "[" + fixed
                        try:
                            result = json.loads(fixed)
                            self._log(f"[SS] {label}: recovered {len(result)} items.", "SUCCESS")
                            return result
                        except json.JSONDecodeError:
                            pass
                    self._log(f"[SS] {label}: recovery failed.", "ERROR")
                    return None

            # ── STEP 1: Ask LLM to list all chapter headings ──────────────────
            self._log("[SS] Step 1: Asking LLM to identify chapter structure...", "INFO")
            conversation = [
                {
                    "role": "system",
                    "content": (
                        "You are a script supervisor for AI film production. "
                        "You will receive a novel and then be asked to process it chapter by chapter. "
                        "Always reply ONLY with valid JSON. No markdown, no explanation."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Here is the complete novel text:\n\n{script_text}\n\n"
                        "List all chapter headings/titles in this text as a JSON array of strings, "
                        "in the order they appear. Include foreword, prologue, epilogue etc. "
                        "Example: ['FOREWORD: ...', 'Chapter 1: ...', 'EPILOGUE: ...']. "
                        "Reply ONLY with the JSON array, no other text."
                    )
                }
            ]

            raw_chapters = _call_llm(conversation)
            self._log(f"[SS] Chapter list response: {len(raw_chapters)} chars.", "INFO")

            chapters = _parse_json(raw_chapters, "Chapter list")
            if not chapters or not isinstance(chapters, list):
                self._log("[SS] Error: Could not extract chapter list.", "ERROR")
                self.after(0, lambda: self._gen_scenes_btn.config(state="normal"))
                return

            chapters = [str(c).strip() for c in chapters if str(c).strip()]
            self._log(f"[SS] Found {len(chapters)} chapter(s):", "INFO")
            for i, ch in enumerate(chapters):
                self._log(f"[SS]   {i+1}. {ch}", "INFO")

            # Add assistant response to conversation history
            conversation.append({"role": "assistant", "content": raw_chapters})

            # ── STEP 2: Process each chapter ──────────────────────────────────
            all_scenes    = []
            scene_counter = 0

            for ch_idx, chapter in enumerate(chapters):
                if self._stop_import.is_set():
                    self._log("[SS] Import cancelled.", "WARNING")
                    break

                self._log(f"[SS] Processing chapter {ch_idx+1}/{len(chapters)}: {chapter}", "INFO")

                conversation.append({
                    "role": "user",
                    "content": (
                        f"Now generate the scene list for this chapter only: \"{chapter}\"\n\n"
                        f"Start scene IDs from S{scene_counter+1:02d}.\n\n"
                        + SYSTEM_PROMPT_SCRIPT_SUPERVISOR.split("HERE IS THE TEXT TO PROCESS:")[0].strip()
                        + "\n\nReply ONLY with the JSON array of scenes for this chapter."
                    )
                })

                raw_scenes_text = _call_llm(conversation)
                self._log(f"[SS] Chapter {ch_idx+1} response: {len(raw_scenes_text):,} chars.", "INFO")

                # Add to history so LLM tracks what has been processed
                conversation.append({"role": "assistant", "content": raw_scenes_text})

                raw_scenes = _parse_json(raw_scenes_text, f"Chapter {ch_idx+1}")
                if not raw_scenes or not isinstance(raw_scenes, list):
                    self._log(f"[SS] Chapter {ch_idx+1}: skipping — no valid scenes.", "WARNING")
                    continue

                chapter_scenes = _validate_and_fix_scenes(raw_scenes)

                # Renumber sequentially across chapters
                for s in chapter_scenes:
                    scene_counter += 1
                    s["id"] = f"S{scene_counter:02d}"

                all_scenes.extend(chapter_scenes)
                self._log(f"[SS] Chapter {ch_idx+1}: {len(chapter_scenes)} scenes. "
                          f"Total so far: {len(all_scenes)}.", "SUCCESS")

                # Save incrementally and update GUI after each chapter
                storage = os.path.normpath(self._storage_var.get().strip())
                _save_active_scenes(storage, all_scenes)
                _active_scenes = list(all_scenes)
                self.after(0, self._refresh_scene_list)

            # ── STEP 3: Final save ────────────────────────────────────────────
            if not all_scenes:
                self._log("[SS] Error: No scenes generated.", "ERROR")
                self.after(0, lambda: self._gen_scenes_btn.config(state="normal"))
                return

            storage = os.path.normpath(self._storage_var.get().strip())
            _save_active_scenes(storage, all_scenes)
            _active_scenes = all_scenes

            self._log(f"[SS] ✅ Import complete: {len(all_scenes)} scenes from "
                      f"{len(chapters)} chapter(s).", "SUCCESS")
            self._log(f"[SS] Scene list saved: config/szenen_importiert.json", "SUCCESS")

            self.after(0, self._refresh_scene_list)
            self.after(0, lambda: self._gen_scenes_btn.config(state="normal"))

        except urllib.error.HTTPError as e:
            self._log(f"[SS] HTTP error {e.code}: {e.reason}", "ERROR")
            if e.code == 500:
                self._log("[SS] HTTP 500 — VRAM overflow or context too large.", "WARNING")
            self.after(0, lambda: self._gen_scenes_btn.config(state="normal"))
        except Exception as e:
            self._log(f"[SS] Error: {e}", "ERROR")
            self.after(0, lambda: self._gen_scenes_btn.config(state="normal"))


    def _reset_to_default_scenes(self):
        """Resets the active scene list back to the built-in Ison-Codex scenes."""
        global _active_scenes
        n_default = len(SCENES)
        if not messagebox.askyesno(
            "Reset to Ison-Codex",
            f"Szenenliste auf die {n_default} Standard-Szenen (Ison-Codex) reset?\n\n"
            "Imported scenes (szenen_importiert.json) will be deleted."
        ):
            return
        storage = os.path.normpath(self._storage_var.get().strip())
        # Delete imported file
        imp_path = os.path.join(storage, "config", "szenen_importiert.json")
        try:
            if os.path.isfile(imp_path):
                os.remove(imp_path)
        except Exception:
            pass
        _active_scenes = list(SCENES)
        self._log(f"[SS] Reset to {len(SCENES)} Ison-Codex scenes.", "SUCCESS")
        self._refresh_scene_list()

    def _run_full_production(self):
        """Runs the full 28-scene production in a background thread."""
        self._orchestrator = self._make_orchestrator()
        def _run():
            self._orchestrator.run_production()
        threading.Thread(target=_run, daemon=True).start()

    def _run_single_scene(self):
        """Runs production for the selected scene only."""
        sel = self._scene_list.curselection()
        if not sel:
            messagebox.showinfo("Select Scene",
                                "Please select a scene from the list.")
            return
        scene = _get_active_scenes()[sel[0]]
        self._orchestrator = self._make_orchestrator()
        def _run():
            self._orchestrator.run_production(scene_filter=scene["id"])
        threading.Thread(target=_run, daemon=True).start()

    def _stop_production(self):
        """Signals the running orchestrator to stop."""
        if self._orchestrator:
            self._orchestrator.stop()
            self._log("Stopping production...", "WARNING")

    def _on_diagnose_comfyui(self):
        """Fragt ComfyUI nach den exakten Node-Inputs und zeigt sie im Log."""
        import threading, urllib.request, json as _json
        COMFYUI_URL = "http://127.0.0.1:8188"
        NODES_OF_INTEREST = [
            "ChatterBoxEngineNode", "UnifiedTTSTextNode",
            "ACEModelLoader", "ACEStepGen",
            "ACELoRALoader", "SaveAudio",
        ]

        def _query():
            self._log("🔍 Frage ComfyUI nach Node-Info...", "INFO")
            try:
                with urllib.request.urlopen(f"{COMFYUI_URL}/object_info", timeout=10) as r:
                    data = _json.loads(r.read())
                found = []
                for name in NODES_OF_INTEREST:
                    if name in data:
                        found.append(name)
                        node = data[name]
                        inp = node.get("input", {})
                        self._log(f"\n=== {name} ===", "SUCCESS")
                        for cat in ("required", "optional"):
                            if cat not in inp:
                                continue
                            self._log(f"  [{cat}]", "INFO")
                            for k, v in inp[cat].items():
                                typ = str(v[0]) if v else "?"
                                # Listentypen kuerzen
                                if isinstance(v[0], list) and len(v[0]) > 5:
                                    typ = f"[{v[0][0]}, ...+{len(v[0])-1}]"
                                self._log(f"    {k}: {typ}", "INFO")
                    else:
                        self._log(f"=== {name}: NICHT GEFUNDEN ===", "WARNING")
                self._log(f"\n✅ {len(found)}/{len(NODES_OF_INTEREST)} Nodes gefunden.", "SUCCESS")
            except Exception as e:
                self._log(f"❌ Diagnose fehlgeschlagen: {e}", "ERROR")
                self._log("  → Ist ComfyUI gestartet? http://127.0.0.1:8188", "WARNING")

        threading.Thread(target=_query, daemon=True).start()

    def _on_install_comfyui(self):
        """GUI-Handler fuer den '🖥️ Install ComfyUI'-Button.

        Prueft ob bereits installiert, fragt Benutzer, startet Installation
        in einem Daemon-Thread damit das GUI responsiv bleibt.
        """
        storage = os.path.normpath(self._storage_var.get().strip())
        project_root = os.path.dirname(storage)
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        main_py      = os.path.join(comfyui_dir, "main.py")

        if os.path.isfile(main_py):
            msg = (
                f"ComfyUI ist bereits installiert:\n{comfyui_dir}\n\n"
                "Trotzdem erneut pruefen / Custom Nodes nachinstallieren?"
            )
            if not messagebox.askyesno("ComfyUI bereits vorhanden", msg):
                self._log("[ComfyUI] Installation abgebrochen — bereits vorhanden.", "INFO")
                return

        confirm = messagebox.askyesno(
            "ComfyUI installieren",
            "Folgendes wird installiert:\n\n"
            "  • ComfyUI Portable (GitHub master)\n"
            "  • venv + torch (CUDA 12.1)\n"
            "  • WAN 2.1 1.3B Modell (~2-5 GB)\n"
            "  • ComfyUI-Manager\n"
            "  • ComfyUI-AudioTools\n\n"
            f"Ziel: {comfyui_dir}\n\n"
            "Installation starten? (dauert einige Minuten)"
        )
        if not confirm:
            self._log("[ComfyUI] Installation abgebrochen.", "INFO")
            return

        self._log("[ComfyUI] Starte Installation im Hintergrund...", "INFO")
        self._log(f"[ComfyUI] Ziel: {comfyui_dir}", "INFO")

        def _run_install():
            ok = ProductionOrchestrator._install_comfyui(
                storage_root = storage,
                log_cb       = self._log,
            )
            if ok:
                self.after(0, lambda: messagebox.showinfo(
                    "ComfyUI installiert ✅",
                    f"ComfyUI erfolgreich installiert!\n\n"
                    f"Pfad: {comfyui_dir}\n\n"
                    f"Start: start_comfyui.bat doppelklicken\n"
                    f"Dann Worker 'comfyui_local' einer Szene zuweisen."
                ))
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Installation fehlgeschlagen",
                    "ComfyUI-Installation nicht vollständig abgeschlossen.\n"
                    "Siehe Log fuer Details.\n\n"
                    "Haeufige Ursachen:\n"
                    "  • Keine Internetverbindung\n"
                    "  • git nicht installiert (fuer Custom Nodes)\n"
                    "  • Zu wenig Speicherplatz"
                ))

        threading.Thread(target=_run_install, daemon=True).start()

    def _open_storage(self):
        """Opens the storage root directory in Windows Explorer."""
        path = os.path.normpath(self._storage_var.get().strip())
        if os.path.isdir(path):
            subprocess.Popen(["explorer", path])
        else:
            messagebox.showinfo("Folder not found",
                                f"{path}\n\nClick START PRODUCTION first.")

    def _clear_log(self):
        """Clears the log area."""
        self._log_area.config(state="normal")
        self._log_area.delete("1.0", "end")
        self._log_area.config(state="disabled")

    # ── Thread-safe log ────────────────────────────────────────────────────────

    def _log(self, msg: str, level: str = "INFO"):
        """Thread-safe log append with color tagging.

        Robust gegen destroyed tkinter window (z.B. IDLE-Restart waehrend
        ein Render-Thread noch laeuft). Faengt RuntimeError und TclError ab.
        """
        def _do():
            try:
                self._log_area.config(state="normal")
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                # Auto-scroll nur wenn Benutzer bereits am Ende ist
                at_bottom = self._log_area.yview()[1] >= 0.99
                self._log_area.insert("end", f"[{ts}] {msg}\n", level)
                if at_bottom:
                    self._log_area.see("end")
                self._log_area.config(state="disabled")
            except Exception:
                pass  # Widget zerstoert — ignorieren
        try:
            self.after(0, _do)
        except RuntimeError:
            # Main thread not in main loop — Fenster zerstoert oder IDLE-Restart
            # Fallback: direkt auf stdout ausgeben
            import sys
            ts = datetime.datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] [{level}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    """Entry point: GUI mode or CLI headless mode."""
    parser = argparse.ArgumentParser(description="Ison-Codex Film Production Orchestrator")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Simulate without real API calls (default: False)")
    parser.add_argument("--scene", type=str, default=None,
                        help="Process only this scene ID (e.g. P1, K5.2)")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="Run in CLI mode without GUI")
    parser.add_argument("--storage", type=str, default=DEFAULT_STORAGE_ROOT,
                        help="Storage root directory")
    args = parser.parse_args()

    if args.headless:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        orch    = ProductionOrchestrator(
            storage_root     = args.storage,
            deepseek_api_key = api_key,
            dry_run          = args.dry_run,
        )
        orch.run_production(scene_filter=args.scene)
    else:
        app = ProducerApp()
        app.mainloop()


if __name__ == "__main__":
    main()
