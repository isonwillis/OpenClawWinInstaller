# -*- coding: utf-8 -*-
"""
IsonCodexProducer.py  --  v1.0.4
Ison-Codex Film Production Orchestrator
------------------------------------------------------------
LYRA as Cinematic Coordinator:
  - DeepSeek (= Ison) liefert kreative Prompts + Qualitaetskontrolle
  - LYRA empfaengt, speichert, verteilt an Workers, trackt Status
  - Workers: Sora, Runway, Seedance, Digen, MyEdit, Suno, CapCut
  - Workers: ComfyUI Local (WAN 2.1 1.3B, kein API-Key)

Architektur:
  DeepSeek (Ison) -> LYRA (Proxy/Speicher) -> Workers (Ausfuehrung)

v1.0.4 Änderungen:
  - BugFix: Scene-Save persistiert jetzt korrekt via _save_active_scenes()
  - BugFix: pip-Aufrufe während ComfyUI-Install ohne CMD-Fenster-Popups
  - ComfyUI Installer-Status-GUI (analog pytorch_setup_gui)

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
            "title":        str(item.get("title",   "Scene")).strip(),
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
    # ── Local ComfyUI (no API key needed, runs locally on Lyra) ──────────
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
            log(f"[ComfyUI] PID {pid} on port {port} terminated ✓", "INFO")
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
        """Writes lyra_production_config.json with all scenes + audio + final_cut metadata."""
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
        """Writes style/production_handbook.txt with the visual DNA reference."""
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
                        f"(Scene {scene['id']}: {scene['title']}):\n\n"
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

    # ── Whitelist validation for scene package ────────────────────────────────

    # Valid ChatterBox language codes (TTS-Audio-Suite v4.x)
    _VALID_TTS_LANGUAGES = {
        "English", "German", "French", "Spanish", "Italian",
        "Portuguese", "Dutch", "Polish", "Russian", "Chinese",
        "Japanese", "Korean", "Arabic", "Turkish", "Hindi",
        "Czech", "Romanian", "Hungarian", "Swedish", "Norwegian",
        "Finnish", "Danish", "Ukrainian", "Croatian", "Slovak",
    }
    # Valid ChatterBox emotion tags
    _VALID_TTS_EMOTIONS = {
        "neutral", "calm", "dramatic", "intense", "sad",
        "mysterious", "hopeful", "tense", "warm", "cold",
        "urgent", "reflective", "ominous", "solemn",
    }
    # Valid ACE-Step genre/mood tags (verified against ACE-Step documentation)
    _VALID_MUSIC_TAGS = {
        "cinematic", "orchestral", "instrumental", "ambient", "dark",
        "noir", "epic", "tension", "dramatic", "atmospheric",
        "electronic", "piano", "strings", "brass", "percussion",
        "minimal", "sparse", "haunting", "melancholic", "hopeful",
        "action", "suspense", "emotional", "soft", "intense",
        "drone", "pad", "hybrid", "score", "soundtrack",
    }
    # Allowed ACE-Step language markers
    _VALID_MUSIC_LANG_MARKERS = {"[en]", "[inst]", "[de]", "[fr]", "[es]", "[zh]", "[ja]"}

    def _validate_scene_package(self, pkg: dict, scene: dict) -> dict:
        """Validates all LLM-generated parameters against whitelists.

        Invalid values are reset to verified defaults and logged.
        Always returns a complete, safe package.
        """
        sid = scene.get("id", "?")
        warnings = []

        # ── narration_text ────────────────────────────────────────────────────
        narration = pkg.get("narration_text", "")
        if not isinstance(narration, str) or len(narration.strip()) < 10:
            narration = f"{scene.get('title', sid)}: {scene.get('prompt', '')[:120]}"
            warnings.append("narration_text empty/invalid → falling back to title+prompt")
        else:
            # Clean markup: remove Markdown, hex colors, direction brackets
            import re as _re
            narration = _re.sub(r"\*{1,2}[^*]+\*{1,2}", "", narration)   # **bold**, *italic*
            narration = _re.sub(r"#[0-9A-Fa-f]{3,6}\b", "", narration)   # Hex-Farben
            narration = _re.sub(r"\([^)]{0,60}\)", "", narration)         # (Kamera-Anweisungen)
            narration = _re.sub(r"\[[^\]]{0,40}\]", "", narration)        # [Regie-Notizen]
            narration = _re.sub(r"\s{2,}", " ", narration).strip()
            if len(narration) < 10:
                narration = scene.get("title", sid)
                warnings.append("narration_text too short after cleanup → fallback")

        # Max 500 characters for TTS
        if len(narration) > 500:
            narration = narration[:497] + "..."

        # ── tts_language ──────────────────────────────────────────────────────
        tts_lang = pkg.get("tts_language", "English")
        if tts_lang not in self._VALID_TTS_LANGUAGES:
            warnings.append(f"tts_language '{tts_lang}' invalid → English")
            tts_lang = "English"

        # ── tts_emotion ───────────────────────────────────────────────────────
        tts_emotion = pkg.get("tts_emotion", "neutral")
        if tts_emotion not in self._VALID_TTS_EMOTIONS:
            warnings.append(f"tts_emotion '{tts_emotion}' invalid → neutral")
            tts_emotion = "neutral"

        # ── tts_exaggeration ─────────────────────────────────────────────────
        try:
            tts_exag = float(pkg.get("tts_exaggeration", 0.5))
            tts_exag = max(0.0, min(1.0, tts_exag))
        except (TypeError, ValueError):
            tts_exag = 0.5
            warnings.append("tts_exaggeration invalid → 0.5")

        # ── music_tags ────────────────────────────────────────────────────────
        raw_tags = pkg.get("music_tags", [])
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.replace(",", " ").split()]
        valid_tags = [t.lower() for t in raw_tags if t.lower() in self._VALID_MUSIC_TAGS]
        if not valid_tags:
            valid_tags = ["cinematic", "orchestral", "instrumental", "dark", "atmospheric"]
            warnings.append(f"music_tags '{raw_tags}' alle invalid → cinematic defaults")
        elif len(valid_tags) < len(raw_tags):
            dropped = [t for t in raw_tags if t.lower() not in self._VALID_MUSIC_TAGS]
            warnings.append(f"music_tags: invalid tags removed: {dropped}")

        # ── music_lang_marker ─────────────────────────────────────────────────
        music_lang = pkg.get("music_lang_marker", "[inst]")
        if music_lang not in self._VALID_MUSIC_LANG_MARKERS:
            warnings.append(f"music_lang_marker '{music_lang}' invalid → [inst]")
            music_lang = "[inst]"

        # ── music_duration_sec ────────────────────────────────────────────────
        try:
            music_dur = int(pkg.get("music_duration_sec", scene.get("duration_sec", 15)))
            # ACE-Step minimum 30s for audible output — model is trained on longer sequences
            music_dur = max(30, min(60, music_dur))
        except (TypeError, ValueError):
            music_dur = 30
            warnings.append("music_duration_sec invalid → 30s minimum")

        # ── music_num_steps ───────────────────────────────────────────────────
        try:
            music_steps = int(pkg.get("music_num_steps", 30))
            music_steps = max(20, min(60, music_steps))
        except (TypeError, ValueError):
            music_steps = 30
            warnings.append("music_num_steps invalid → 30")

        # ── Warnungen loggen ──────────────────────────────────────────────────
        for w in warnings:
            self.log(f"[ScenePackage/{sid}] ⚠️  {w}", "WARNING")
        if not warnings:
            self.log(f"[ScenePackage/{sid}] All parameters validated ✓", "SUCCESS")

        return {
            "narration_text":    narration,
            "tts_language":      tts_lang,
            "tts_emotion":       tts_emotion,
            "tts_exaggeration":  tts_exag,
            "music_tags":        valid_tags,
            "music_lang_marker": music_lang,
            "music_duration_sec": music_dur,
            "music_num_steps":   music_steps,
        }

    def request_scene_package(self, scene: dict, enhanced_prompt: str) -> dict:
        """Asks the LLM to generate a complete scene package with all subsystem parameters.

        Returns a validated dict with:
          narration_text, tts_language, tts_emotion, tts_exaggeration,
          music_tags, music_lang_marker, music_duration_sec, music_num_steps

        Falls back to safe defaults if LLM fails or returns invalid data.
        """
        sid = scene.get("id", "?")

        # ── Safe Default (wird immer als Fallback verwendet) ──────────────────
        def _safe_default() -> dict:
            """Returns a validated scene package with all-default values."""
            return self._validate_scene_package({}, scene)

        if self.dry_run or not self.deepseek_api_key:
            self.log(f"[ScenePackage/{sid}] dry_run/no-key — using defaults", "INFO")
            return _safe_default()

        self.log(f"[ScenePackage/{sid}] Generating scene package via LLM...", "INFO")

        char_descs = "; ".join(
            CHARACTERS[c]["desc"] for c in scene.get("chars", [])
            if c in CHARACTERS
        )

        # Valid values as context for the LLM to prevent hallucinated values
        valid_tags_str   = ", ".join(sorted(self._VALID_MUSIC_TAGS))
        valid_lang_str   = ", ".join(sorted(self._VALID_TTS_LANGUAGES))
        valid_emot_str   = ", ".join(sorted(self._VALID_TTS_EMOTIONS))
        valid_mmark_str  = ", ".join(sorted(self._VALID_MUSIC_LANG_MARKERS))

        system_prompt = (
            "You are the creative director of the film 'Der Ison-Codex'. "
            "You generate scene packages for an AI film production pipeline. "
            "IMPORTANT: Only use values from the provided lists. "
            "Return ONLY valid JSON, no markdown, no explanation."
        )

        user_prompt = (
            f"Scene ID: {sid} | Title: {scene.get('title', '')}\n"
            f"Chapter: {scene.get('chapter', '')}\n"
            f"Characters: {char_descs or 'none'}\n"
            f"Duration: {scene.get('duration_sec', 15)} seconds\n"
            f"Visual prompt: {enhanced_prompt[:300]}\n\n"
            f"Generate a JSON scene package with these exact keys:\n"
            f"- narration_text: (string, max 400 chars) A short, atmospheric narration "
            f"  for the VIEWER — what happens in the story, the mood, what it means. "
            f"  NO camera directions, NO hex colors, NO stage directions, NO asterisks. "
            f"  Write as a film narrator speaking to the audience.\n"
            f"- tts_language: one of: {valid_lang_str}\n"
            f"- tts_emotion: one of: {valid_emot_str}\n"
            f"- tts_exaggeration: float 0.0–1.0 (0.3=calm, 0.6=dramatic)\n"
            f"- music_tags: list of 3–6 tags from: {valid_tags_str}\n"
            f"- music_lang_marker: one of: {valid_mmark_str} (use [inst] for instrumental)\n"
            f"- music_duration_sec: integer, scene duration + 2 (max 60)\n"
            f"- music_num_steps: integer 20–40 (30 recommended)\n\n"
            f"Return ONLY the JSON object, nothing else."
        )

        import urllib.request, urllib.error, re as _re

        for _attempt in range(1, 3):   # up to 2 attempts
            try:
                payload = json.dumps({
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    "temperature": 0.4,   # low for consistent structured outputs
                    "max_tokens":  600,
                }).encode("utf-8")

                req = urllib.request.Request(
                    f"{DEFAULT_DEEPSEEK_URL}/chat/completions",
                    data=payload,
                    headers={
                        "Content-Type":  "application/json",
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                    },
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.load(resp)
                    raw = data["choices"][0]["message"]["content"].strip()

                # Extract JSON block (strip markdown fences if present)
                json_match = _re.search(r"\{.*\}", raw, _re.DOTALL)
                if not json_match:
                    self.log(f"[ScenePackage/{sid}] No JSON in LLM response (attempt {_attempt}) — using defaults", "WARNING")
                    return _safe_default()

                pkg_raw = json.loads(json_match.group(0))
                self.log(f"[ScenePackage/{sid}] LLM package received — validating...", "INFO")
                return self._validate_scene_package(pkg_raw, scene)

            except json.JSONDecodeError as e:
                self.log(f"[ScenePackage/{sid}] JSON parse error (attempt {_attempt}): {e} — Defaults", "WARNING")
                return _safe_default()
            except Exception as e:
                if _attempt < 2:
                    self.log(f"[ScenePackage/{sid}] LLM error (attempt {_attempt}): {e} — retrying...", "WARNING")
                else:
                    self.log(f"[ScenePackage/{sid}] LLM error (attempt {_attempt}): {e} — Defaults", "WARNING")
                    return _safe_default()

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
                    # Enhanced Prompt extrahieren — endet vor ## Narration, ## Scene Package oder ## Visual DNA
                    enhanced = content.split("## Enhanced Prompt (DeepSeek)")[-1]
                    for _stop in ("## Narration", "## Scene Package", "## Visual DNA"):
                        if _stop in enhanced:
                            enhanced = enhanced.split(_stop)[0]
                    enhanced = enhanced.strip()
                except Exception:
                    enhanced = scene["prompt"]

                # ── Scene-Package: aus prompt.txt lesen oder neu generieren ──
                scene_pkg = None
                try:
                    if "## Scene Package" in content:
                        pkg_raw = content.split("## Scene Package")[-1].strip()
                        import re as _re2
                        m = _re2.search(r"\{.*\}", pkg_raw, _re2.DOTALL)
                        if m:
                            scene_pkg = self._validate_scene_package(
                                json.loads(m.group(0)), scene
                            )
                            self.log(f"[Scene {sid}] Scene package loaded from prompt.txt ✓", "INFO")
                except Exception:
                    scene_pkg = None

                if scene_pkg is None:
                    # Older prompt.txt without scene package — appending now
                    self.log(f"[Scene {sid}] No scene package in prompt.txt — generating...", "INFO")
                    scene_pkg = self.request_scene_package(scene, enhanced)
                    try:
                        with open(prompt_path, "a", encoding="utf-8") as f:
                            f.write(f"\n## Narration\n{scene_pkg['narration_text']}\n\n")
                            f.write(f"## Scene Package\n{json.dumps(scene_pkg, indent=2, ensure_ascii=False)}\n")
                        self.log(f"[Scene {sid}] Scene package appended ✓", "INFO")
                    except Exception as _ce:
                        self.log(f"[Scene {sid}] Scene package write failed: {_ce}", "WARNING")

                prompt_dir = os.path.join(self.storage_root, "szenen", sid, scene["tool"])
                os.makedirs(prompt_dir, exist_ok=True)
                worker = self._find_video_worker(scene["tool"])
                if worker is None:
                    self.log(f"[Scene {sid}] SKIP — no worker configured for tool '{scene['tool']}'.", "WARNING")
                    scene_status = "skipped_no_worker"
                else:
                    clip_path = self._call_video_worker(
                        sid, enhanced, scene["duration_sec"], scene["tool"], worker, prompt_dir,
                        scene=scene, scene_pkg=scene_pkg)
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

        # Step 1: enhance prompt + scene package via DeepSeek (one step)
        enhanced  = self.request_enhanced_prompt(scene)
        scene_pkg = self.request_scene_package(scene, enhanced)

        # Step 2: write prompt.txt — alles auf einmal
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
            f.write(f"## Narration\n{scene_pkg['narration_text']}\n\n")
            f.write(f"## Scene Package\n{json.dumps(scene_pkg, indent=2, ensure_ascii=False)}\n\n")
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
                    sid, enhanced, scene["duration_sec"], scene["tool"], worker, prompt_dir,
                    scene=scene, scene_pkg=scene_pkg)
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

        # ── comfyui_local: always available, no API key needed ─────────────
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
                           tool: str, worker: dict, out_dir: str,
                           scene: dict | None = None,
                           scene_pkg: dict | None = None) -> str | None:
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
            return self._call_comfyui_worker(sid, prompt, duration, out_dir,
                                             scene=scene, scene_pkg=scene_pkg)

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
    # COMFYUI LOCAL WORKER  (neu in v1.0.4 -- bestehende Worker unberuehrt)
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_comfyui_workflow(self, prompt: str, duration_sec: int,
                                out_dir: str, sid: str = "scene") -> dict:
        """Laed ein JSON-Workflow-Template und setzt Prompt + Output-Pfad ein.

        Sucht das Template in folgender Reihenfolge:
          1. <storage_root>/config/comfyui_workflow_template.json
          2. <storage_root>/../comfyui_workflow_template.json  (Projektroot)
          3. Eingebettetes Minimal-WAN-2.1-Template als Fallback

        Args:
            prompt:       Verbesserter Scenen-Prompt.
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
                    self.log(f"[ComfyUI] Workflow template loaded: {tpl_path}", "INFO")
                    break
                except Exception as e:
                    self.log(f"[ComfyUI] Template load error {tpl_path}: {e}", "WARNING")

        if workflow is None:
            # Eingebettetes Minimal-Template fuer WAN 2.1 1.3B (Text2Video)
            # Verwendet ComfyUI-native WAN-Nodes (kein CheckpointLoaderSimple!)
            # Modell liegt in models/diffusion_models/, T5 in models/text_encoders/
            self.log("[ComfyUI] No template found — using embedded WAN-2.1 minimal workflow.", "INFO")

            # ── Model auto-detection: prefer 14B (GGUF/fp8) over 1.3B ───────────
            project_root   = os.path.dirname(os.path.normpath(self.storage_root))
            comfyui_dir    = os.path.join(project_root, "ComfyUI-Portable")
            diff_models    = os.path.join(comfyui_dir, "models", "diffusion_models")
            unet_dir       = os.path.join(comfyui_dir, "models", "unet")

            # Priority order: 14B GGUF > 14B fp8 > 14B bf16 > 1.3B bf16 > 1.3B fp16
            model_candidates_14b_gguf = [f for f in (os.listdir(unet_dir) if os.path.isdir(unet_dir) else [])
                                          if "14b" in f.lower() and f.lower().endswith(".gguf")]
            # Also check diffusion_models/ — some users place GGUF there
            if not model_candidates_14b_gguf and os.path.isdir(diff_models):
                gguf_in_diff = [f for f in os.listdir(diff_models)
                                if "14b" in f.lower() and f.lower().endswith(".gguf")]
                if gguf_in_diff:
                    os.makedirs(unet_dir, exist_ok=True)
                    import shutil as _shgguf
                    for _gf in gguf_in_diff:
                        _shgguf.move(os.path.join(diff_models, _gf), os.path.join(unet_dir, _gf))
                        self.log(f"[ComfyUI] Moved {_gf} → models/unet/ ✓", "INFO")
                    model_candidates_14b_gguf = [f for f in os.listdir(unet_dir)
                                                 if "14b" in f.lower() and f.lower().endswith(".gguf")]
            model_candidates_14b_diff = [f for f in (os.listdir(diff_models) if os.path.isdir(diff_models) else [])
                                          if "14b" in f.lower() and f.endswith(".safetensors")]

            use_14b_gguf = bool(model_candidates_14b_gguf)
            use_14b_diff = bool(model_candidates_14b_diff) and not use_14b_gguf

            self.log(f"[ComfyUI] Model scan — unet/: {model_candidates_14b_gguf} | diff/: {model_candidates_14b_diff}", "INFO")

            # Verify UnetLoaderGGUF is available in ComfyUI before using it
            if use_14b_gguf:
                try:
                    import urllib.request as _ur_chk
                    with _ur_chk.urlopen("http://127.0.0.1:8188/object_info/UnetLoaderGGUF", timeout=5) as _r:
                        _r.read()
                    self.log("[ComfyUI] UnetLoaderGGUF node available ✓", "SUCCESS")
                except Exception:
                    self.log("[ComfyUI] UnetLoaderGGUF node NOT available — gguf not installed in active Python.", "WARNING")
                    self.log("[ComfyUI] → Run 'Install ComfyUI' to install gguf package.", "INFO")
                    use_14b_gguf = False

            fps = 16
            # Frame limits depend on model + offloading strategy:
            # 1.3B @ 6GB VRAM only:   max 81 frames (5.1s) @ 480p
            # 14B GGUF + CPU offload: max 81 frames per job (VRAM holds active layers only)
            #   → quality is much higher, same render time constraint
            # Resolution tradeoff: lower res = more frames possible
            #   848×480 (16:9) = max 81 frames on 6GB
            #   480×480 (1:1)  = up to 121 frames possible on 6GB
            if use_14b_gguf or use_14b_diff:
                MAX_WAN_FRAMES = 81   # Same VRAM constraint, but quality is far superior
                width, height  = 848, 480
            else:
                MAX_WAN_FRAMES = 81
                width, height  = 848, 480

            raw_frames = duration_sec * fps
            wan_frames = max(17, min(MAX_WAN_FRAMES, int(raw_frames)))
            # WAN requires frames in form 4k+1: 17, 21, 25, ..., 81
            wan_frames = ((wan_frames - 1) // 4) * 4 + 1
            num_frames = wan_frames
            actual_secs = num_frames / fps
            model_label = "14B" if (use_14b_gguf or use_14b_diff) else "1.3B"
            if actual_secs < duration_sec - 1:
                clips_raw    = max(1, int(duration_sec / actual_secs + 0.5))
                clips_capped = min(clips_raw, 6)
                loop_note    = f" (capped at {clips_capped}, remainder looped)" if clips_raw > 6 else ""
                self.log(
                    f"[ComfyUI] ⚠️  Scene {duration_sec}s → WAN {model_label} limit: {actual_secs:.1f}s "
                    f"({num_frames} Frames @ {fps}fps). "
                    f"{clips_capped} clips will be rendered{loop_note}.",
                    "WARNING"
                )
            else:
                self.log(f"[ComfyUI] Frames: {num_frames} @ {fps}fps = {actual_secs:.1f}s [{model_label}]", "INFO")

            if use_14b_gguf:
                diffusion_model = sorted(model_candidates_14b_gguf)[0]
                model_dir_used  = unet_dir
                loader_class    = "UnetLoaderGGUF"
                self.log(f"[ComfyUI] Using WAN 2.1 14B GGUF: {diffusion_model}", "SUCCESS")
            elif use_14b_diff:
                diffusion_model = sorted(model_candidates_14b_diff)[0]
                # Prefer fp8 for VRAM efficiency
                fp8_candidates = [f for f in model_candidates_14b_diff if "fp8" in f.lower()]
                if fp8_candidates:
                    diffusion_model = sorted(fp8_candidates)[0]
                model_dir_used = diff_models
                loader_class   = "UNETLoader"
                self.log(f"[ComfyUI] Using WAN 2.1 14B: {diffusion_model}", "SUCCESS")
            else:
                # Fallback: 1.3B model
                model_bf16     = "wan2.1_t2v_1.3B_bf16.safetensors"
                model_fp16     = "wan2.1_t2v_1.3B_fp16.safetensors"
                if os.path.isfile(os.path.join(diff_models, model_bf16)):
                    diffusion_model = model_bf16
                else:
                    diffusion_model = model_fp16
                model_dir_used = diff_models
                loader_class   = "UNETLoader"
                self.log(f"[ComfyUI] WAN 2.1 14B not found — using 1.3B: {diffusion_model}", "WARNING")
                self.log("[ComfyUI] → Download 14B GGUF: place wan2.1_t2v_14B_Q4_K_M.gguf in models/unet/", "INFO")

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
                # Node 1: Load WAN diffusion model — GGUF or standard UNETLoader
                "1": {
                    "class_type": loader_class,
                    "inputs": {
                        "unet_name": diffusion_model,
                        **({"weight_dtype": "fp8_e4m3fn"} if loader_class == "UNETLoader" and use_14b_diff else
                           {"weight_dtype": "default"} if loader_class == "UNETLoader" else {})
                    }
                },
                # Node 2: Load T5 text encoder
                "2": {
                    "class_type": "CLIPLoader",
                    "inputs": {
                        "clip_name": t5_encoder,
                        "type": "wan"
                    }
                },
                # Node 3: Load WAN VAE
                "3": {
                    "class_type": "VAELoader",
                    "inputs": {
                        "vae_name": wan_vae
                    }
                },
                # Node 4: Positiver Prompt (wird durch Scenen-Prompt ersetzt)
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
                # Node 6: Empty latent video — EmptyHunyuanLatentVideo works for both 1.3B and 14B
                "6": {
                    "class_type": "EmptyHunyuanLatentVideo",
                    "inputs": {
                        "width":      width,
                        "height":     height,
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
                # (ComfyUI-VideoHelperSuite — already installed)
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
            # Fallback: overwrite first CLIPTextEncode node
            for node_id, node in workflow.items():
                if node.get("class_type") == "CLIPTextEncode":
                    node["inputs"]["text"] = prompt
                    prompt_injected = True
                    break

        # Output-Pfad-Setzer:
        # ComfyUI erlaubt KEINEN Pfad ausserhalb seines output/-Ordners.
        # Loesung: kurzen Prefix nutzen (bleibt in output/), Datei nach Render verschieben.
        scene_prefix = f"lyra_{sid}"   # eindeutig pro Scene, bleibt in output/
        for node_id, node in workflow.items():
            if node.get("class_type") in (
                "VHS_VideoCombine", "SaveVideo", "VideoSave",
                "SaveAnimatedWEBP", "SaveAnimatedPNG", "SaveImage",
            ):
                node["inputs"]["filename_prefix"] = scene_prefix

        return workflow

    def _kill_comfyui_on_port(self, port: int = 8188):
        """Terminates all ComfyUI processes on the port. Delegates to _kill_comfyui_port()."""
        # Eigenen gespeicherten Prozess zuerst beenden
        if self._comfyui_process is not None:
            try:
                if self._comfyui_process.poll() is None:
                    self._comfyui_process.terminate()
                    try:
                        self._comfyui_process.wait(timeout=5)
                    except Exception:
                        self._comfyui_process.kill()
                    self.log(f"[ComfyUI] Old process (PID {self._comfyui_process.pid}) terminated.", "INFO")
            except Exception:
                pass
            self._comfyui_process = None
        # Modul-Funktion fuer Rest (wmic + netstat + taskkill)
        _kill_comfyui_port(port, log_cb=self.log)

    def _start_comfyui_process(self) -> bool:
        """Starts ComfyUI as a background process and streams its logs to the GUI.

        Searches for the correct Python (venv > system Python with torch > sys.executable).
        Runs a diagnostic check before starting and shows errors immediately.
        Starts without its own console window (Windows: CREATE_NO_WINDOW).

        Returns:
            True  if process started.
            False if ComfyUI folder missing or startup error.
        """
        # ── ComfyUI-Verzeichnis ermitteln ─────────────────────────────────────
        project_root = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        main_py      = os.path.join(comfyui_dir, "main.py")

        if not os.path.isfile(main_py):
            self.log(
                "[ComfyUI] ComfyUI folder not found.\n"
                f"  Expected: {comfyui_dir}\n"
                "  → Click '🖥️ Install ComfyUI' to install ComfyUI.",
                "WARNING"
            )
            return False

        # ── Richtiges Python bestimmen ────────────────────────────────────────
        # Priority: ComfyUI's own venv (Scripts/python.exe or bin/python)
        # NEVER use pytorch_env — it has a different tqdm wrapper
        # that fails on Windows pipes with OSError [Errno 22].
        python_exe = None

        # 1. venv Python (preferred — isolated ComfyUI installation, Windows)
        venv_py_win = os.path.join(comfyui_dir, "venv", "Scripts", "python.exe")
        venv_py_nix = os.path.join(comfyui_dir, "venv", "bin", "python")
        for venv_candidate in (venv_py_win, venv_py_nix):
            if os.path.isfile(venv_candidate):
                python_exe = venv_candidate
                self.log(f"[ComfyUI] Using venv Python: {venv_candidate}", "INFO")
                break

        # 2. System Python that can import torch — EXPLICITLY exclude pytorch_env
        #    (pytorch_env has an incompatible tqdm stderr wrapper → Errno 22 on pipes)
        _pytorch_env_marker = os.path.normcase(
            os.path.join(os.path.expanduser("~"), "pytorch_env")
        )
        if not python_exe:
            for cand in [
                sys.executable,
                os.path.join(os.path.dirname(sys.executable), "python.exe"),
            ]:
                if not cand or not os.path.isfile(cand):
                    continue
                # Nie pytorch_env verwenden
                if os.path.normcase(cand).startswith(_pytorch_env_marker):
                    self.log(f"[ComfyUI] pytorch_env ignored (incompatible): {cand}", "WARNING")
                    continue
                try:
                    result = subprocess.run(
                        [cand, "-c", "import torch; print('ok')"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=10, cwd=comfyui_dir,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    if result.returncode == 0:
                        python_exe = cand
                        self.log(f"[ComfyUI] Using system Python (torch found): {cand}", "INFO")
                        break
                except Exception:
                    continue

        # 3. sys.executable as last resort — only if NOT pytorch_env
        if not python_exe:
            cand = sys.executable
            if os.path.normcase(cand).startswith(_pytorch_env_marker):
                self.log("[ComfyUI] sys.executable ist pytorch_env — suche Alternativen.", "WARNING")
                # python.exe im PATH suchen (ohne pytorch_env)
                import shutil as _shutil
                for name in ("python3.exe", "python.exe", "python3", "python"):
                    found = _shutil.which(name)
                    if found and not os.path.normcase(found).startswith(_pytorch_env_marker):
                        python_exe = found
                        self.log(f"[ComfyUI] PATH Python as fallback: {found}", "WARNING")
                        break
            if not python_exe:
                python_exe = cand
                self.log(f"[ComfyUI] Using sys.executable as fallback: {python_exe}", "WARNING")

        # ── Diagnose-Check: main.py kurz testen (gibt Importfehler sofort aus) ─
        self.log("[ComfyUI] Diagnostics: checking Python environment...", "INFO")
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
                self.log("[ComfyUI] Diagnostics: torch/numpy/PIL/aiohttp OK ✓", "SUCCESS")
            else:
                err = diag.stderr.decode(errors="replace").strip()
                out = diag.stdout.decode(errors="replace").strip()
                self.log(f"[ComfyUI] ⚠️  Diagnostics: missing dependencies!", "WARNING")
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
            self.log(f"[ComfyUI] Diagnose-Check failed: {e}", "WARNING")

        # ── Prozess starten ───────────────────────────────────────────────────
        # Step 0: Terminate old ComfyUI process on port 8188
        self._kill_comfyui_on_port(8188)

        # Check CUDA availability — set --cpu flag if not available
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
            self.log("[ComfyUI] CUDA available ✓ — starting with GPU support.", "SUCCESS")
        else:
            self.log(
                "[ComfyUI] ⚠️  CUDA not available — starting in CPU mode (slow!).",
                "WARNING"
            )

        # Eindeutige DB-Datei pro Instanz (verhindert SQLite-Lock bei Mehrfachstart)
        db_path = os.path.join(comfyui_dir, "user", "comfyui_lyra.db")
        cmd = [python_exe, "main.py", "--listen", "--port", "8188",
               "--database-url", f"sqlite:///{db_path}",
               ]  # PYTHONIOENCODING env loest tqdm stderr OSError
        if not cuda_available:
            cmd.append("--cpu")

        # Inject a tqdm pipe-safe monkey-patch via -W flag and sitecustomize.
        # The patch wraps tqdm's fp_write so flush() on a Windows pipe never raises.
        # This is injected as a -c snippet prepended to the Python call.
        tqdm_patch_code = (
            "import tqdm.utils as _tu; _orig = _tu.disp_len\n"
            "import io as _io, sys as _sys\n"
            "def _safe_fp_write(fp, s):\n"
            "    try:\n"
            "        if hasattr(fp, 'write'): fp.write(str(s))\n"
            "        try:\n"
            "            if hasattr(fp, 'flush'): fp.flush()\n"
            "        except (OSError, AttributeError): pass\n"
            "    except (OSError, AttributeError): pass\n"
            "import tqdm.std as _ts\n"
            "try: _ts.std_tqdm.fp_write = staticmethod(_safe_fp_write)\n"
            "except Exception: pass\n"
        )

        self.log(f"[ComfyUI] Starting: {' '.join(cmd)}", "INFO")

        try:
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = subprocess.CREATE_NO_WINDOW

            # PYTHONIOENCODING=utf-8 gives original_stderr a valid encoding.
            # Without this, tqdm/ComfyUI-Manager fails with OSError [Errno 22].
            # ComfyUI-Manager patches stderr (prestartup_script.py:336) — tqdm
            # then tries flush() on the patched stream → OSError on Windows pipes.
            # TQDM_DISABLE=1 prevents tqdm from writing to stderr at all —
            # this is the actual trigger for Errno 22 on Windows pipes.
            comfyui_env = os.environ.copy()
            comfyui_env["PYTHONIOENCODING"]          = "utf-8"
            comfyui_env["PYTHONLEGACYWINDOWSSTDIO"]  = "0"
            comfyui_env["PYTHONUNBUFFERED"]          = "1"
            comfyui_env["NO_COLOR"]                  = "1"
            comfyui_env["TERM"]                      = "dumb"
            comfyui_env["FORCE_COLOR"]               = "0"
            comfyui_env["TQDM_DISABLE"]              = "1"
            comfyui_env["TQDM_MININTERVAL"]          = "999"
            comfyui_env["COMFYUI_NO_PROGRESS"]       = "1"

            # Write tqdm patch to a sitecustomize.py in the venv so it loads
            # before any other code — this is the only reliable way to intercept
            # tqdm before ComfyUI-Manager patches stderr.
            venv_site = os.path.join(comfyui_dir, "venv", "Lib", "site-packages")
            if os.path.isdir(venv_site):
                patch_path = os.path.join(venv_site, "sitecustomize.py")
                try:
                    # Only write if not already patched
                    existing = ""
                    if os.path.isfile(patch_path):
                        with open(patch_path, "r", encoding="utf-8") as _f:
                            existing = _f.read()
                    if "_safe_fp_write" not in existing:
                        with open(patch_path, "a", encoding="utf-8") as _f:
                            _f.write("\n# tqdm pipe-safe patch — injected by IsonCodexProducer\n")
                            _f.write("try:\n")
                            _f.write("    import tqdm.std as _ts\n")
                            _f.write("    def _safe_fp_write(fp, s):\n")
                            _f.write("        try:\n")
                            _f.write("            if hasattr(fp, 'write'): fp.write(str(s))\n")
                            _f.write("            try:\n")
                            _f.write("                if hasattr(fp, 'flush'): fp.flush()\n")
                            _f.write("            except (OSError, AttributeError): pass\n")
                            _f.write("        except (OSError, AttributeError): pass\n")
                            _f.write("    _ts.std_tqdm.fp_write = staticmethod(_safe_fp_write)\n")
                            _f.write("except Exception: pass\n")
                        self.log("[ComfyUI] tqdm pipe-safe patch written to sitecustomize.py ✓", "INFO")
                except Exception as _pe:
                    self.log(f"[ComfyUI] sitecustomize patch write failed (non-critical): {_pe}", "WARNING")

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
            self.log(f"[ComfyUI] Popen failed: {e}", "ERROR")
            return False

        self._comfyui_process = proc
        self.log(f"[ComfyUI] Process started (PID {proc.pid}) ✓", "SUCCESS")

        # ── Log-Stream-Thread ─────────────────────────────────────────────────
        def _stream_logs():
            """Reads stdout from the ComfyUI process and forwards each line to the GUI log."""
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
                    # Suppress very long lines (>500 chars) that contain no error keywords
                    if len(lo) > 500 and not any(w in lo for w in ("error", "exception", "traceback")):
                        level = "INFO"
                        lo = lo[:200] + f"... [+{len(lo)-200} characters gekürzt]"
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
                self.log(f"[ComfyUI] Log-Stream-Error: {ex}", "WARNING")

            # Prozess ist beendet — Exitcode ausgeben
            rc = proc.poll()
            if rc is not None and rc != 0:
                self.log(
                    f"[ComfyUI] ⚠️  Process exited with code {rc}.\n"
                    "  → Tipp: ComfyUI manuell starten um vollstaendigen Fehler zu sehen:\n"
                    f"  → cd {comfyui_dir}\n"
                    f"  → {python_exe} main.py --listen",
                    "WARNING"
                )
            else:
                self.log("[ComfyUI] Process terminated.", "INFO")

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
            """Returns True if ComfyUI /system_stats responds within 4 seconds."""
            try:
                with urllib.request.urlopen(
                    f"{COMFYUI_URL}/system_stats", timeout=4
                ) as r:
                    r.read()
                return True
            except Exception:
                return False

        # ── Step 1: Immediate check ────────────────────────────────────────────
        if _ping():
            self.log(f"{tag} ComfyUI already running.", "INFO")
            return True

        # ── Step 2: Auto-start ─────────────────────────────────────────────────
        self.log(f"{tag} ComfyUI not reachable — starting automatically...", "INFO")
        if not self._start_comfyui_process():
            return False  # Start error already logged

        # ── Step 3: Wait until ready (max 60s) ──────────────────────────────
        max_wait = 60
        interval = 3
        waited   = 0
        self.log(f"{tag} Warte auf ComfyUI-Start (max {max_wait}s)...", "INFO")

        while waited < max_wait:
            time.sleep(interval)
            waited += interval
            if _ping():
                self.log(f"{tag} ComfyUI ready after {waited}s. ✅", "SUCCESS")
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
        scene_package: dict | None = None,
    ) -> str | None:
        """Adds narration + cinematic music to the video.

        Pipeline (sequential, VRAM-friendly):
          A) TTS narration via ComfyUI ChatterBox (TTS-Audio-Suite)
          B) Cinematic music via ComfyUI ACE-Step
          C) FFmpeg: video + narration + music → final MP4

        Args:
            scene_package: Validated package from request_scene_package().
                           If None: falls back to prompt-based defaults.
        """
        import urllib.request, urllib.error, json as _json

        self.log(f"{tag} 🎬 Starting cinematic audio pipeline...", "INFO")

        project_root = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        comfyui_out  = os.path.join(comfyui_dir, "output")

        # ── Scene package: use defaults if not provided ──────────────────────
        if not scene_package:
            scene_package = {
                "narration_text":    prompt[:300].strip(),
                "tts_language":      "English",
                "tts_emotion":       "neutral",
                "tts_exaggeration":  0.5,
                "music_tags":        ["cinematic", "orchestral", "instrumental", "dark", "atmospheric"],
                "music_lang_marker": "[inst]",
                "music_duration_sec": max(30, min(duration_sec + 2, 60)),
                "music_num_steps":   30,
            }

        # ── Hilfsfunktion: ComfyUI-Job abschicken und warten ─────────────────
        def _submit_and_wait(workflow: dict, label: str,
                             max_wait: int = 300) -> dict | None:
            """Submits workflow, waits for completion, returns outputs."""
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
                self.log(f"{tag}   [{label}] POST failed: {e}", "WARNING")
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
                            self.log(f"{tag}   [{label}] Job failed: {msgs}", "WARNING")
                            return None
                        outputs = hist[pid].get("outputs", {})
                        if outputs:
                            self.log(f"{tag}   [{label}] ✓ complete after {waited}s", "SUCCESS")
                            return outputs
                except Exception:
                    pass
            self.log(f"{tag}   [{label}] Timeout nach {max_wait}s", "WARNING")
            return None

        def _find_audio_file(outputs: dict, label: str) -> str | None:
            """Searches for audio file in ComfyUI outputs."""
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

        # ── Step A: TTS narration ──────────────────────────────────────────────
        self.log(f"{tag} A) TTS narration (ChatterBox)...", "INFO")
        narration_path = None

        narration_text   = scene_package["narration_text"]
        tts_language     = scene_package["tts_language"]
        tts_exaggeration = scene_package["tts_exaggeration"]
        # Map emotion → ChatterBox parameters
        _emotion_map = {
            "calm":        (0.3, 0.5, 0.6),   # (exag, temp, cfg)
            "neutral":     (0.5, 0.7, 0.5),
            "dramatic":    (0.7, 0.8, 0.4),
            "intense":     (0.8, 0.9, 0.35),
            "mysterious":  (0.5, 0.6, 0.5),
            "sad":         (0.4, 0.5, 0.55),
            "ominous":     (0.6, 0.6, 0.45),
            "solemn":      (0.45, 0.55, 0.55),
            "urgent":      (0.75, 0.85, 0.4),
            "tense":       (0.65, 0.75, 0.42),
            "warm":        (0.4, 0.6, 0.55),
            "reflective":  (0.35, 0.55, 0.6),
            "hopeful":     (0.5, 0.65, 0.5),
            "cold":        (0.4, 0.5, 0.6),
        }
        _exag, _temp, _cfg = _emotion_map.get(
            scene_package.get("tts_emotion", "neutral"),
            (tts_exaggeration, 0.7, 0.5)
        )
        self.log(
            f"{tag}   TTS: lang={tts_language}, emotion={scene_package.get('tts_emotion','neutral')}, "
            f"exag={_exag}, temp={_temp}", "INFO"
        )
        self.log(f"{tag}   Narration text ({len(narration_text)} characters): {narration_text[:80]}...", "INFO")

        tts_prefix = f"tts_{sid}"
        tts_workflow = {
            "1": {
                "class_type": "ChatterBoxEngineNode",
                "inputs": {
                    "language":                  tts_language,
                    "device":                    "auto",
                    "exaggeration":              _exag,
                    "temperature":               _temp,
                    "cfg_weight":                _cfg,
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
                self.log(f"{tag}   TTS audio file not found.", "WARNING")
        else:
            self.log(f"{tag}   TTS failed — video without narration.", "WARNING")

        # ── Step B: Cinematic music (ACE-Step) ──────────────────────────────
        self.log(f"{tag} B) Cinematic music (ACE-Step)...", "INFO")
        music_path = None

        # Music parameters from validated scene package
        music_tags     = scene_package["music_tags"]
        music_lang     = scene_package["music_lang_marker"]
        music_dur      = scene_package["music_duration_sec"]
        music_steps    = scene_package["music_num_steps"]
        # ACE-Step prompt: tags + language marker + no vocals
        music_prompt = ", ".join(music_tags) + f", no vocals, film score"
        self.log(
            f"{tag}   Music: tags={music_tags}, lang={music_lang}, "
            f"dur={music_dur}s, steps={music_steps}", "INFO"
        )

        music_prefix = f"music_{sid}"

        import re as _re
        sid_digits = _re.sub(r"[^0-9]", "", sid) or "1"
        music_seed  = int(sid_digits[:6])

        # ComfyUI_ACE-Step (billwuhao): Node-Namen aus ace_step_nodes.py
        # ACEModelLoader → ACEStepGen → SaveAudio
        # ACE-Step: ACEModelLoader braucht 4 separate Checkpoint-Inputs.
        # Model files are downloaded automatically on first render.
        # Ordnerstruktur: models/TTS/ACE-Step-v1-3.5B/{ace_step_transformer, music_dcae_f8c8, ...}
        project_root_ace = os.path.dirname(os.path.normpath(self.storage_root))
        comfyui_dir_ace  = os.path.join(project_root_ace, "ComfyUI-Portable")
        ace_model_base   = os.path.join(comfyui_dir_ace, "models", "TTS", "ACE-Step-v1-3.5B")

        # Check which subfolders are present
        def _ace_subfolder(sub: str) -> str:
            """Returns subfolder name if present, empty string otherwise."""
            path = os.path.join(ace_model_base, sub)
            return sub if os.path.isdir(path) else ""

        ace_dcae     = _ace_subfolder("music_dcae_f8c8")
        ace_vocoder  = _ace_subfolder("music_vocoder")
        ace_step     = _ace_subfolder("ace_step_transformer")
        ace_t5       = _ace_subfolder("umt5-base")

        if not all([ace_dcae, ace_vocoder, ace_step, ace_t5]):
            self.log(
                f"{tag}   ACE-Step model folder incomplete — "
                f"Music will be skipped. Folder: {ace_model_base}",
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
                        "models":     ["1", 0],
                        "prompt":     music_prompt,
                        "lyrics":     music_lang,   # [inst] = no vocals
                        # parameters: Python dict as string — node calls ast.literal_eval() then **parameters
                        # Exact parameter names verified from ace_step_nodes.py sample_data() function:
                        # audio_duration, infer_step, guidance_scale, scheduler_type, cfg_type,
                        # omega_scale, seed (→ manual_seeds internally), guidance_interval,
                        # guidance_interval_decay, min_guidance_scale, use_erg_tag, use_erg_lyric,
                        # use_erg_diffusion, oss_steps, guidance_scale_text, guidance_scale_lyric
                        "parameters": str({
                            "audio_duration":          float(music_dur),
                            "infer_step":              int(music_steps),
                            "guidance_scale":          7.0,
                            "scheduler_type":          "euler",
                            "cfg_type":                "apg",
                            "omega_scale":             10.0,
                            "manual_seeds":            int(music_seed),
                            "guidance_interval":       1.0,
                            "guidance_interval_decay": 0.0,
                            "min_guidance_scale":      3,
                            "use_erg_tag":             True,
                            "use_erg_lyric":           False,
                            "use_erg_diffusion":       True,
                            "oss_steps":               "",
                            "guidance_scale_text":     0.0,
                            "guidance_scale_lyric":    0.0,
                        }),
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
            # max_wait: music_dur * 120s Puffer
            music_max_wait = max(3600, music_dur * 120)
            music_outputs = _submit_and_wait(music_workflow, "ACE-Step Musik", max_wait=music_max_wait)
        if music_outputs:
            music_path = _find_audio_file(music_outputs, "Musik")
            if music_path:
                import shutil as _shm
                local_music = os.path.join(out_dir, "music.wav")
                _shm.copy2(music_path, local_music)
                music_path = local_music
                self.log(f"{tag}   Music: {local_music}", "SUCCESS")
            else:
                self.log(f"{tag}   Music audio file not found.", "WARNING")
        else:
            self.log(f"{tag}   Music failed — video without music.", "WARNING")

        # ── Step C: FFmpeg merge ───────────────────────────────────────────────
        if not narration_path and not music_path:
            self.log(f"{tag} No audio generated — video without sound.", "INFO")
            return None

        self.log(f"{tag} C) FFmpeg merge: video + audio...", "INFO")
        final_path = os.path.join(out_dir, "clip_001_final.mp4")

        # FFmpeg-Kommando aufbauen
        cmd = ["ffmpeg", "-y", "-i", video_path]

        if narration_path and music_path:
            # Narration (full volume) + music (background) with loudness normalization
            # loudnorm ensures music is audible even if ACE-Step output is quiet
            cmd += [
                "-i", narration_path,
                "-i", music_path,
                "-filter_complex",
                "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[narr];"   # Normalize narration
                "[2:a]loudnorm=I=-23:TP=-1.5:LRA=11,volume=0.4[mus];"  # Normalize + reduce music
                "[narr][mus]amix=inputs=2:duration=shortest:normalize=0[aout]",
                "-map", "0:v",
                "-map", "[aout]",
            ]
        elif narration_path:
            cmd += [
                "-i", narration_path,
                "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
                "-map", "0:v", "-map", "[aout]",
            ]
        elif music_path:
            cmd += [
                "-i", music_path,
                "-filter_complex", "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[aout]",
                "-map", "0:v", "-map", "[aout]",
            ]

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
                # Search for FFmpeg in ComfyUI-Portable (installed by VHS)
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
                self.log(f"{tag} ✅ Final MP4 with audio: {final_path}", "SUCCESS")
                return final_path
            else:
                err = result.stderr.decode(errors="replace")[-300:]
                self.log(f"{tag} FFmpeg failed: {err}", "WARNING")
                return None
        except FileNotFoundError:
            self.log(
                f"{tag} FFmpeg not found.\n"
                "  → Installiere FFmpeg: https://ffmpeg.org/download.html\n"
                "  → Oder: pip install imageio-ffmpeg (dann ffmpeg in PATH)",
                "WARNING"
            )
            return None
        except Exception as e:
            self.log(f"{tag} FFmpeg error: {e}", "WARNING")
            return None

    def _call_comfyui_worker(self, sid: str, prompt: str, duration_sec: int,
                             out_dir: str, scene: dict | None = None,
                             scene_pkg: dict | None = None) -> str | None:
        """Renders a scene via a locally running ComfyUI instance.

        Workflow:
          1. Prueft ob ComfyUI erreichbar ist (GET /system_stats).
          2. Baut den Workflow mit _build_comfyui_workflow().
          3. Sendet POST /prompt.
          4. Pollt GET /history/<prompt_id> bis fertig (max 20 min).
          5. Laedt den fertigen Clip aus ComfyUI-Output-Ordner.

        Args:
            sid:          Scenen-ID (fuer Log-Prefix).
            prompt:       Verbesserter Scenen-Prompt.
            duration_sec: Videodauer in Sekunden.
            out_dir:      Zielordner fuer den heruntergeladenen Clip.

        Returns:
            Lokaler Clip-Pfad (str) bei Erfolg, None bei Fehler.
        """
        import urllib.request
        import urllib.error

        COMFYUI_URL = "http://127.0.0.1:8188"
        TAG         = f"[Scene {sid}][ComfyUI]"

        # ── 1. Ensure ComfyUI is running (auto-start if needed) ────────────────
        if not self._ensure_comfyui_running(TAG):
            return None

        self.log(f"{TAG} ComfyUI ready. Building workflow...", "INFO")

        # ── 2. Workflow bauen ─────────────────────────────────────────────────
        workflow = self._build_comfyui_workflow(prompt, duration_sec, out_dir, sid)

        # ── 3. ComfyUI Queue leeren (nur hängende/pending Jobs, NICHT laufende) ─
        # IMPORTANT: Never send /interrupt — it would abort a running render.
        # Only clear the pending queue (items not yet started).
        try:
            # Check current queue state first
            with urllib.request.urlopen(f"{COMFYUI_URL}/queue", timeout=5) as _qr:
                _qdata = json.loads(_qr.read())
            _pending = _qdata.get("queue_pending", [])
            _running = _qdata.get("queue_running", [])

            if _pending:
                # Only clear pending items — leave running job untouched
                clear_req = urllib.request.Request(
                    f"{COMFYUI_URL}/queue",
                    data    = json.dumps({"clear": True}).encode("utf-8"),
                    headers = {"Content-Type": "application/json"},
                    method  = "POST",
                )
                with urllib.request.urlopen(clear_req, timeout=10) as r:
                    r.read()
                self.log(f"{TAG} Queue cleared ({len(_pending)} pending items) ✓", "INFO")
            elif _running:
                self.log(f"{TAG} Queue: {len(_running)} job(s) running — not interrupting.", "INFO")
            else:
                self.log(f"{TAG} Queue empty ✓", "INFO")
        except Exception as qe:
            self.log(f"{TAG} Queue check failed (non-critical): {qe}", "WARNING")

        # DO NOT send /interrupt here — it aborts any currently running render.
        # Interrupt is only sent by the STOP button explicitly.

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
                        self.log(f"{TAG}   Error: {err_json['error']}", "ERROR")
                    if "node_errors" in err_json:
                        for nid, nerr in err_json["node_errors"].items():
                            self.log(f"{TAG}   Node {nid}: {nerr}", "ERROR")
                    if not err_json.get("error") and not err_json.get("node_errors"):
                        self.log(f"{TAG}   Body: {body[:500]}", "WARNING")
                except Exception:
                    self.log(f"{TAG}   Body: {body[:500]}", "WARNING")
            except Exception:
                self.log(f"{TAG} POST /prompt failed: HTTP {e.code}.", "WARNING")
            return None
        except Exception as e:
            self.log(f"{TAG} POST /prompt failed: {e}.", "WARNING")
            return None

        prompt_id = resp_data.get("prompt_id")
        if not prompt_id:
            self.log(f"{TAG} Keine prompt_id in Antwort: {resp_data}", "WARNING")
            return None

        self.log(f"{TAG} Job started — prompt_id={prompt_id}", "SUCCESS")

        # ── 5. Polling bis fertig ─────────────────────────────────────────────
        # 14B GGUF: ~275s/step × 20 steps = ~5500s per clip.
        # Use 7200s (2h) as safe upper bound for a single clip.
        max_wait = 43200   # 12 hours — no practical timeout for large models
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
                if waited % 60 == 0:   # Log every 60s, not every 8s
                    self.log(f"{TAG} Waiting for result... ({waited}s)", "INFO")
                continue

            job_data = hist[prompt_id]
            outputs  = job_data.get("outputs", {})
            status   = job_data.get("status", {})

            # Fehler abfangen
            if status.get("status_str") in ("error", "failed"):
                msgs = status.get("messages", [])
                self.log(f"{TAG} Job failed: {msgs}", "WARNING")
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

            # ── 5. Datei aus ComfyUI output/ in Scenen-Ordner verschieben ─────
            self.log(f"{TAG} ✅ Render complete after {waited}s — '{clip_filename}'", "SUCCESS")

            # ComfyUI speichert in seinem output/-Ordner.
            # Determine path directly (no HTTP download needed).
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
                    self.log(f"{TAG} ✅ Video copied: {clip_path}", "SUCCESS")

                    # ── Multi-Clip: weitere Clips rendern falls Scene > 5.1s ────
                    MAX_CLIP_SEC   = 5.1
                    # Hard cap: max 6 clips regardless of scene duration.
                    # For very long scenes (60-90s), we render 6 clips (~30s total)
                    # and use FFmpeg to loop/extend to the target duration.
                    MAX_CLIPS      = 6
                    num_clips_raw  = max(1, int(duration_sec / MAX_CLIP_SEC + 0.5))
                    num_clips_needed = min(num_clips_raw, MAX_CLIPS)
                    use_loop       = num_clips_raw > MAX_CLIPS  # need to loop to reach target duration

                    if num_clips_needed > 1 and os.path.isfile(clip_path):
                        self.log(f"{TAG} 📽️  {num_clips_needed} clips needed for {duration_sec}s — rendering more...", "INFO")
                        all_clips = [clip_path]

                        def _render_extra_clip(clip_idx: int) -> str | None:
                            """Renders an additional clip and returns its path."""
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
                                self.log(f"{TAG} Clip {clip_idx} POST failed: {pe}", "WARNING")
                                return None

                            if not pid_n:
                                return None
                            self.log(f"{TAG} Clip {clip_idx} Job gestartet — {pid_n[:8]}...", "INFO")

                            # Poll /history
                            deadline_n = time.time() + 43200  # 12h per clip — no practical timeout
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
                                                            self.log(f"{TAG} ✅ Clip {clip_idx} complete", "SUCCESS")
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
                                self.log(f"{TAG} ⚠️  Clip {clip_idx} failed — stopping at {len(all_clips)} clip(s).", "WARNING")
                                break

                        # FFmpeg concat — with optional loop to reach target duration
                        if len(all_clips) > 1:
                            rendered_sec = len(all_clips) * MAX_CLIP_SEC
                            self.log(f"{TAG} 🔗 Merging {len(all_clips)} clips together ({rendered_sec:.0f}s)...", "INFO")
                            concat_list = os.path.join(out_dir, "_concat_list.txt")

                            # If we hit the MAX_CLIPS cap, loop the concat list to reach target duration
                            if use_loop and rendered_sec < duration_sec:
                                loops_needed = int(duration_sec / rendered_sec) + 1
                                self.log(f"{TAG} 🔁 Looping {len(all_clips)} clips ×{loops_needed} to reach {duration_sec}s target...", "INFO")
                                with open(concat_list, "w", encoding="utf-8") as f:
                                    for _ in range(loops_needed):
                                        for c in all_clips:
                                            f.write(f"file '{c}'\n")
                            else:
                                with open(concat_list, "w", encoding="utf-8") as f:
                                    for c in all_clips:
                                        f.write(f"file '{c}'\n")

                            concat_out = os.path.join(out_dir, "_clip_concat.mp4")
                            import shutil as _shff
                            ffmpeg_cc = _shff.which("ffmpeg")
                            if not ffmpeg_cc:
                                _ff_local = os.path.join(comfyui_out, "..", "venv", "Scripts", "ffmpeg.exe")
                                _ff_local = os.path.normpath(_ff_local)
                                if os.path.isfile(_ff_local):
                                    ffmpeg_cc = _ff_local
                            if ffmpeg_cc:
                                try:
                                    # Concat + trim to exact target duration
                                    ffmpeg_cmd = [ffmpeg_cc, "-y", "-f", "concat", "-safe", "0",
                                                  "-i", concat_list]
                                    if use_loop:
                                        # Trim to exact target duration
                                        ffmpeg_cmd += ["-t", str(duration_sec)]
                                    ffmpeg_cmd += ["-c", "copy", concat_out]
                                    subprocess.run(
                                        ffmpeg_cmd,
                                        check=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        timeout=300,
                                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                                    )
                                    if os.path.isfile(concat_out):
                                        import shutil as _shc2
                                        _shc2.copy2(concat_out, clip_path)
                                        final_dur = duration_sec if use_loop else rendered_sec
                                        self.log(f"{TAG} ✅ {len(all_clips)} clips → {clip_path} ({final_dur:.0f}s)", "SUCCESS")
                                    else:
                                        self.log(f"{TAG} ⚠️  Concat output not created — using clip_001.", "WARNING")
                                except Exception as fe:
                                    self.log(f"{TAG} FFmpeg concat failed: {fe}", "WARNING")
                            else:
                                self.log(f"{TAG} ⚠️  FFmpeg not found — concat skipped.", "WARNING")

                    # ── Scene-Package generieren (LLM + Validierung) ──────────
                    _scene_for_pkg = scene if scene else {
                        "id": sid, "prompt": prompt, "duration_sec": duration_sec,
                        "title": sid, "chapter": "", "chars": [],
                    }
                    if scene_pkg is None:
                        scene_pkg = self.request_scene_package(
                            scene           = _scene_for_pkg,
                            enhanced_prompt = prompt,
                        )
                    else:
                        self.log(f"{TAG} Scene package already present — skipping LLM call.", "INFO")

                    # ── Cinematic Audio Pipeline ──────────────────────────────
                    final_path = self._run_cinematic_audio_pipeline(
                        sid=sid,
                        video_path=clip_path,
                        prompt=prompt,
                        duration_sec=duration_sec,
                        out_dir=out_dir,
                        comfyui_url=COMFYUI_URL,
                        tag=TAG,
                        scene_package=scene_pkg,
                    )
                    return final_path if final_path else clip_path
                except Exception as e:
                    self.log(f"{TAG} Pipeline failed: {e} — returning video without audio.", "WARNING")
                    if os.path.isfile(clip_path):
                        return clip_path

            # Fallback: HTTP-Download (falls Dateisystem-Zugriff fehlschlaegt)
            self.log(f"{TAG} Downloading via HTTP (fallback)...", "INFO")
            params   = f"filename={urllib.parse.quote(clip_filename)}&type=output"
            if clip_subfolder:
                params += f"&subfolder={urllib.parse.quote(clip_subfolder)}"
            clip_url = f"{COMFYUI_URL}/view?{params}"
            try:
                urllib.request.urlretrieve(clip_url, clip_path)
                self.log(f"{TAG} ✅ Saved (HTTP): {clip_path}", "SUCCESS")
                return clip_path
            except Exception as e:
                self.log(f"{TAG} Download failed: {e}.", "WARNING")
                return None

        self.log(f"{TAG} Timeout nach {max_wait}s — kein Clip empfangen.", "WARNING")
        return None

    @staticmethod
    def _install_comfyui(storage_root: str, log_cb=None, tick_cb=None) -> bool:
        """Installs ComfyUI Portable + WAN 2.1 1.3B + custom nodes (once).

        Steps:
          1. Checks if ComfyUI folder already exists (skips if so).
          2. Downloads ComfyUI Portable ZIP from GitHub.
          3. Extracts to <storage_root>/ComfyUI-Portable directory.
          4. Creates venv, installs torch (CUDA) + requirements.
          5. Downloads WAN 2.1 1.3B model (safetensors).
          6. Clones ComfyUI-Manager + custom nodes.

        Platform: Windows 10/11, NVIDIA GPU (6 GB+ VRAM recommended).

        Args:
            storage_root: Base production folder (ComfyUI-Portable goes next to it).
            log_cb:       Callable(msg, level) for log output.

        Returns:
            True on success, False on error.
        """
        import urllib.request
        import zipfile
        import shutil

        log  = log_cb  or (lambda m, l="INFO": print(f"[{l}] {m}"))
        tick = tick_cb or (lambda key, state, txt="": None)

        # ── Hilfsfunktion: subprocess ohne CMD-Popup-Fenster ──────────────────
        _NO_WIN = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        def _run_hidden(cmd, **kw):
            """subprocess.run() wrapper — never opens a CMD window."""
            kw.setdefault("stdout", subprocess.PIPE)
            kw.setdefault("stderr", subprocess.PIPE)
            kw["creationflags"] = kw.get("creationflags", 0) | _NO_WIN
            return subprocess.run(cmd, **kw)

        # Target folder: one level above storage_root (project root)
        project_root  = os.path.dirname(os.path.normpath(storage_root))
        comfyui_dir   = os.path.join(project_root, "ComfyUI-Portable")
        zip_tmp       = os.path.join(project_root, "_comfyui_download.zip")

        # ── 1. Already present? ───────────────────────────────────────────────
        main_py = os.path.join(comfyui_dir, "main.py")
        skip_download = os.path.isfile(main_py)

        if skip_download:
            log("[ComfyUI-Install] ComfyUI already present — skipping download and extraction.", "INFO")
            log(f"  → Continuing with: venv, dependencies, model, custom nodes.", "INFO")
        else:
            # ── 2. ComfyUI Portable ZIP laden ────────────────────────────────────
            COMFYUI_ZIP_URL = (
                "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/"
                "ComfyUI_windows_portable_nvidia.7z"
            )
            COMFYUI_ZIP_FALLBACK = (
                "https://github.com/comfyanonymous/ComfyUI/archive/refs/heads/master.zip"
            )

            log("[ComfyUI-Install] Step 1/6: Downloading ComfyUI from GitHub...", "INFO")

            # Check cache: setupfiles/comfyui_master.zip
            zip_cached = os.path.join(project_root, "setupfiles", "comfyui_master.zip")
            if os.path.isfile(zip_cached) and os.path.getsize(zip_cached) > 1_000_000:
                log(f"[ComfyUI-Install] ComfyUI ZIP in cache — skipping download.", "SUCCESS")
                log(f"  Cache: {zip_cached}", "INFO")
                zip_tmp = zip_cached  # extract directly from cache
            else:
                log(f"  URL: {COMFYUI_ZIP_FALLBACK}", "INFO")
                try:
                    urllib.request.urlretrieve(COMFYUI_ZIP_FALLBACK, zip_tmp)
                    log(f"[ComfyUI-Install] ZIP downloaded: {zip_tmp}", "INFO")
                except Exception as e:
                    log(f"[ComfyUI-Install] Download failed: {e}", "ERROR")
                    return False

            # ── 3. Extract ───────────────────────────────────────────────────────
            log("[ComfyUI-Install] Step 2/6: Extracting ZIP...", "INFO")
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
                # If ComfyUI-Portable already exists (e.g. from a previous
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
                        log("[ComfyUI-Install] Merge complete ✓", "INFO")

                # Sanity check: main.py must now be present
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
                log(f"[ComfyUI-Install] main.py present: {os.path.isfile(main_check)}", "INFO")
            except Exception as e:
                log(f"[ComfyUI-Install] Extraction failed: {e}", "ERROR")
                return False
        # Ende skip_download else-Block

        # ── 4. Venv + Torch installieren ─────────────────────────────────────
        log("[ComfyUI-Install] Step 3/6: Creating venv and installing torch...", "INFO")
        tick("venv", "run", "venv + torch installieren...")
        venv_dir = os.path.join(comfyui_dir, "venv")

        # sys.executable koennte 32-Bit Python sein (kein venv/torch moeglich).
        # Suche explizit nach einem 64-Bit Python 3.10+ auf diesem System.
        def _find_64bit_python() -> str:
            """Finds a suitable 64-bit python.exe for venv + torch.

            Requirements:
            - Must be python.exe (NOT pythonw.exe — no venv support)
            - Must be 64-bit (struct.calcsize('P') == 8)
            - Must support venv (ensurepip present)
            - Must be Python 3.10+
            """
            import struct, shutil as _sh

            def _is_valid(exe: str) -> bool:
                """Checks if exe is a usable 64-bit python.exe."""
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
                        timeout=8, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
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
                        timeout=8, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
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
        log(f"[ComfyUI-Install] Python for venv: {venv_python}", "INFO")

        # Initialize — will be set by intact check or creation strategies
        venv_ok    = False
        python_exe = venv_python
        pip_exe    = None

        # ── Check if existing venv is already functional ──────────────────────
        venv_python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
        venv_intact = os.path.isfile(venv_python_exe)
        if venv_intact:
            # Quick check: can it import torch with CUDA?
            try:
                chk = _run_hidden(
                    [venv_python_exe, "-c",
                     "import torch; print('CUDA:', torch.cuda.is_available(), torch.__version__)"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                )
                chk_out = chk.stdout.decode(errors="replace").strip()
                if "CUDA: True" in chk_out:
                    log(f"[ComfyUI-Install] Existing venv is functional: {chk_out} — skipping rebuild.", "SUCCESS")
                    # Skip venv creation, go straight to pip installs
                    python_exe = venv_python_exe
                    pip_exe    = os.path.join(venv_dir, "Scripts", "pip.exe")
                    if not os.path.isfile(pip_exe):
                        pip_exe = None
                    # Jump to torch/requirements section by setting venv_ok
                    venv_ok = True
                else:
                    log(f"[ComfyUI-Install] Existing venv has no CUDA torch ({chk_out}) — rebuilding.", "WARNING")
                    venv_intact = False
            except Exception:
                venv_intact = False

        # ── Delete old venv only if rebuild needed ────────────────────────────
        if not venv_intact and os.path.isdir(venv_dir):
            log("[ComfyUI-Install] Existing venv directory found — deleting...", "INFO")
            # Kill any process holding venv files (ComfyUI python.exe)
            try:
                import psutil as _psu
                for _proc in _psu.process_iter(["pid", "name", "exe"]):
                    try:
                        _exe = (_proc.info.get("exe") or "").lower()
                        if "comfyui-portable" in _exe and "python" in _exe:
                            _proc.kill()
                            log(f"[ComfyUI-Install] Killed ComfyUI process PID {_proc.pid} to free venv.", "INFO")
                    except Exception:
                        pass
                import time as _t; _t.sleep(2)
            except ImportError:
                pass
            try:
                import shutil as _shutil
                _shutil.rmtree(venv_dir, ignore_errors=True)
                if os.path.isdir(venv_dir):
                    log("[ComfyUI-Install] venv folder could not be fully deleted.", "WARNING")
                else:
                    log("[ComfyUI-Install] Old venv deleted ✓", "INFO")
            except Exception as e:
                log(f"[ComfyUI-Install] venv deletion failed: {e}", "WARNING")

        # ── Create venv — 4 strategies ───────────────────────────────────────
        # Note: capture_output=True only from Python 3.7 — using PIPE for
        # maximum compatibility (also on older Python installations).
        PIPE   = subprocess.PIPE
        NO_WIN = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        if not venv_ok:
            # Strategy 1: Standard venv (only if venv not already intact)
            try:
                result = _run_hidden(
                    [venv_python, "-m", "venv", venv_dir],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                    creationflags=NO_WIN,
                )
                if result.returncode == 0:
                    venv_ok = True
                    log("[ComfyUI-Install] venv created ✓ (standard)", "SUCCESS")
                else:
                    log(f"[ComfyUI-Install] venv standard failed (exit {result.returncode}):", "WARNING")
                if result.stdout and result.stdout.strip():
                    log(f"  stdout: {result.stdout.decode(errors='replace').strip()}", "WARNING")
                if result.stderr and result.stderr.strip():
                    log(f"  stderr: {result.stderr.decode(errors='replace').strip()}", "WARNING")
            except Exception as e:
                log(f"[ComfyUI-Install] venv Standard Exception: {e}", "WARNING")

        # Strategy 2: venv --without-pip (if ensurepip is missing)
        if not venv_ok:
            log("[ComfyUI-Install] Trying venv --without-pip...", "INFO")
            try:
                result = _run_hidden(
                    [venv_python, "-m", "venv", "--without-pip", venv_dir],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                    creationflags=NO_WIN,
                )
                if result.returncode == 0:
                    venv_ok = True
                    log("[ComfyUI-Install] venv --without-pip created ✓", "SUCCESS")
                    # Install pip via get-pip.py
                    log("[ComfyUI-Install] Installiere pip via get-pip.py...", "INFO")
                    try:
                        import urllib.request as _ur
                        get_pip = os.path.join(comfyui_dir, "_get_pip.py")
                        _ur.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
                        venv_py = os.path.join(venv_dir, "Scripts", "python.exe")
                        _no_win_si = subprocess.STARTUPINFO()
                        _no_win_si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        _no_win_si.wShowWindow = 0
                        subprocess.check_call(
                            [venv_py, get_pip], timeout=120,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                            startupinfo=_no_win_si if sys.platform == "win32" else None,
                        )
                        os.remove(get_pip)
                        log("[ComfyUI-Install] pip installed ✓", "SUCCESS")
                    except Exception as ep:
                        log(f"[ComfyUI-Install] pip post-install failed: {ep}", "WARNING")
                else:
                    err = result.stderr.decode(errors='replace').strip() if result.stderr else ""
                    if err:
                        log(f"  stderr: {err}", "WARNING")
            except Exception as e:
                log(f"[ComfyUI-Install] venv --without-pip exception: {e}", "WARNING")

        # Strategy 3: install and use virtualenv
        if not venv_ok:
            log("[ComfyUI-Install] Trying virtualenv...", "INFO")
            try:
                subprocess.check_call(
                    [venv_python, "-m", "pip", "install", "--quiet", "virtualenv"],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                result = _run_hidden(
                    [venv_python, "-m", "virtualenv", venv_dir],
                    timeout=120,
                    stdout=PIPE, stderr=PIPE,
                    creationflags=NO_WIN,
                )
                if result.returncode == 0:
                    venv_ok = True
                    log("[ComfyUI-Install] virtualenv created ✓", "SUCCESS")
                else:
                    err = result.stderr.decode(errors='replace').strip() if result.stderr else ""
                    if err:
                        log(f"  stderr: {err}", "WARNING")
            except Exception as e:
                log(f"[ComfyUI-Install] virtualenv exception: {e}", "WARNING")

        # Strategy 4: No venv — use system Python directly (not isolated)
        if not venv_ok:
            log("[ComfyUI-Install] ⚠️  No venv possible — using system Python directly.", "WARNING")
            log("  → Packages will be installed globally (not isolated).", "WARNING")

        # pip_exe and python_exe: from venv if present, else system Python
        if venv_ok:
            pip_exe    = os.path.join(venv_dir, "Scripts", "pip.exe") if sys.platform == "win32" \
                         else os.path.join(venv_dir, "bin", "pip")
            python_exe = os.path.join(venv_dir, "Scripts", "python.exe") if sys.platform == "win32" \
                         else os.path.join(venv_dir, "bin", "python")
        else:
            python_exe = venv_python
            pip_exe    = None  # called via 'python -m pip'

        def _pip(args: list, **kwargs) -> bool:
            """Runs a pip command — without CMD popup windows (CREATE_NO_WINDOW)."""
            cmd = [pip_exe] + args if pip_exe and os.path.isfile(pip_exe) \
                  else [python_exe, "-m", "pip"] + args
            # Always capture stdout/stderr + never open its own window
            no_win = {}
            if sys.platform == "win32":
                no_win["creationflags"] = subprocess.CREATE_NO_WINDOW
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                si.wShowWindow = 0  # SW_HIDE
                no_win["startupinfo"] = si
            kwargs.setdefault("stdout", subprocess.PIPE)
            kwargs.setdefault("stderr", subprocess.STDOUT)
            kwargs.update(no_win)
            try:
                result = subprocess.run(cmd, **kwargs)
                if result.returncode != 0:
                    out = (result.stdout or b"").decode(errors="replace") if isinstance(result.stdout, bytes) \
                          else (result.stdout or "")
                    for line in out.splitlines()[-8:]:
                        if line.strip():
                            log(f"  pip> {line.strip()}", "WARNING")
                    log(f"[ComfyUI-Install] pip {args[1] if len(args)>1 else ''} exit={result.returncode}", "WARNING")
                    return False
                return True
            except Exception as ex:
                log(f"[ComfyUI-Install] pip: {args[1] if len(args)>1 else ''} failed: {ex}", "WARNING")
                return False

        # ── torch + requirements installieren ────────────────────────────────
        # Step 1: Detect CUDA version via nvidia-smi (as in HardwareProfile)
        # Step 2: Reuse existing pytorch_env/venv if present
        # Step 3: Store torch WHL in cache folder — no re-download

        # Cache folder: <project_root>/setupfiles (persistent across runs)
        setup_cache = os.path.join(project_root, "setupfiles")
        os.makedirs(setup_cache, exist_ok=True)
        log(f"[ComfyUI-Install] Setup cache: {setup_cache}", "INFO")

        def _detect_cuda_version() -> str:
            """Reads CUDA version via nvidia-smi. Returns e.g. '12.8' or '' if unavailable."""
            nsmi_paths = [
                r"C:\Windows\System32\nvidia-smi.exe",
                r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
                "nvidia-smi",
            ]
            for nsmi in nsmi_paths:
                try:
                    r = _run_hidden(
                        [nsmi, "--query-gpu=driver_version", "--format=csv,noheader"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=8, creationflags=subprocess.CREATE_NO_WINDOW
                    )
                    if r.returncode == 0:
                        r2 = _run_hidden(
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
            log("[ComfyUI-Install] No NVIDIA driver detected → torch CPU version.", "WARNING")

        # Search for existing pytorch_env/venv on the system (from PyTorchInstaller)
        pytorch_env_venv = os.path.join(
            os.path.expanduser("~"), "pytorch_env", "venv", "Scripts", "python.exe"
        )
        if os.path.isfile(pytorch_env_venv) and venv_ok is False:
            try:
                r = _run_hidden(
                    [pytorch_env_venv, "-c",
                     "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                )
                out = r.stdout.decode(errors="replace").strip()
                if out.startswith("True"):
                    log(f"[ComfyUI-Install] Existing pytorch_env found: {out}", "SUCCESS")
                    log(f"  → Using {pytorch_env_venv} instead of fresh install.", "INFO")
                    python_exe = pytorch_env_venv
                    pip_exe    = pytorch_env_venv.replace("python.exe", "pip.exe")
                    venv_ok    = True
            except Exception as pe:
                log(f"[ComfyUI-Install] pytorch_env check failed: {pe}", "WARNING")

        # torch: check first if already installed with CUDA support
        torch_already_ok = False
        try:
            r = _run_hidden(
                [python_exe, "-c",
                 "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            )
            out = r.stdout.decode(errors="replace").strip()
            if out.startswith("True") and f"+{cu_tag}" in out:
                log(f"[ComfyUI-Install] torch already correctly installed: {out} ✓", "SUCCESS")
                tick("venv", "ok", f"torch CUDA {out.split()[-1]}")
                torch_already_ok = True
        except Exception:
            pass

        if not torch_already_ok:
            # WHL-Dateien im Cache-Ordner ablegen (pip --find-links + --cache-dir)
            torch_cache = os.path.join(setup_cache, f"torch_{cu_tag}")
            os.makedirs(torch_cache, exist_ok=True)

            # Check if WHL already cached (min. 3 files: torch, torchvision, torchaudio)
            cached_whls = [f for f in os.listdir(torch_cache) if f.endswith(".whl")]
            if len(cached_whls) >= 3:
                log(f"[ComfyUI-Install] torch WHL cache found — using local cache. ({len(cached_whls)} Dateien) — "
                    f"using local cache.", "SUCCESS")
                log(f"  Cache: {torch_cache}", "INFO")
                # Install from cache (no internet needed)
                torch_ok = _pip([
                    "install", "torch", "torchvision", "torchaudio",
                    "--find-links", torch_cache,
                    "--no-index",            # nur aus Cache, kein PyPI
                ], timeout=300)
                if not torch_ok:
                    # Falls Cache-Install fehlschlaegt: frisch herunterladen
                    log("[ComfyUI-Install] Cache install failed — re-downloading.", "WARNING")
                    cached_whls = []

            if len(cached_whls) < 3:
                log(f"[ComfyUI-Install] Downloading torch ({cu_tag}) → cache: {torch_cache}", "INFO")
                # Download-only: save WHL files to cache without installing
                _pip([
                    "download", "torch", "torchvision", "torchaudio",
                    "--index-url", torch_index,
                    "--dest", torch_cache,
                    "--no-cache-dir",
                ], timeout=900)
                # Installing from freshly downloaded cache
                torch_ok = _pip([
                    "install", "torch", "torchvision", "torchaudio",
                    "--find-links", torch_cache,
                    "--no-index",
                ], timeout=300)

            if torch_ok:
                try:
                    check = _run_hidden(
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
                        log(f"[ComfyUI-Install] torch installed but CUDA not active: {out}", "WARNING")
                        log("  → Check if NVIDIA drivers are up to date.", "WARNING")
                except Exception as ve:
                    log(f"[ComfyUI-Install] torch CUDA verification failed: {ve}", "WARNING")
            else:
                log("[ComfyUI-Install] torch installation failed.", "WARNING")

        req_file = os.path.join(comfyui_dir, "requirements.txt")
        if os.path.isfile(req_file):
            log("[ComfyUI-Install] Installing requirements.txt...", "INFO")
            tick("deps", "run", "requirements.txt...")
            req_ok = _pip(["install", "-r", req_file], timeout=300)
            if req_ok:
                log("[ComfyUI-Install] requirements.txt installed ✓", "SUCCESS")
                tick("deps", "ok", "requirements.txt installiert")
            else:
                log("[ComfyUI-Install] requirements.txt failed (non-critical).", "WARNING")
                tick("deps", "fail")

        # tqdm==4.66.4 in ALLEN verfuegbaren Python-Umgebungen fixieren.
        # ComfyUI runs with venv OR pytorch_env depending on situation —
        # tqdm must be present in both, otherwise OSError [Errno 22].
        log("[ComfyUI-Install] Fixing tqdm (Windows pipe bug)...", "INFO")
        tick("tqdm", "run", "tqdm fixieren...")
        tqdm_cmd = ["install", "tqdm==4.66.4", "--force-reinstall", "--no-cache-dir"]
        tqdm_ok = _pip(tqdm_cmd, timeout=60)
        if tqdm_ok:
            log("  tqdm==4.66.4 installed ✓", "SUCCESS")
            tick("tqdm", "ok", "tqdm fixiert")
        else:
            log("  tqdm fix failed — KSampler may still crash", "WARNING")
        # Also install in pytorch_env if present and different from python_exe
        pytorch_env_pip = os.path.join(
            os.path.expanduser("~"), "pytorch_env", "venv", "Scripts", "pip.exe"
        )
        if os.path.isfile(pytorch_env_pip) and pytorch_env_pip != pip_exe:
            try:
                _run_hidden(
                    [pytorch_env_pip, "install", "tqdm==4.66.4",
                     "--force-reinstall", "--no-cache-dir"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                log("  tqdm==4.66.4 installed in pytorch_env ✓", "SUCCESS")
            except Exception as te:
                log(f"  tqdm in pytorch_env failed: {te}", "WARNING")

        # ── sqlalchemy upgraden — ComfyUI braucht sqlalchemy>=2.0 fuer 'select' ──
        log("[ComfyUI-Install] Upgrading sqlalchemy (fixes ImportError: cannot import 'select')...", "INFO")
        _pip(["install", "sqlalchemy>=2.0", "--upgrade", "--no-cache-dir"], timeout=120)

        # ── Write tqdm pipe-safe patch to sitecustomize.py ────────────────────
        # This must happen in the installer (not just at ComfyUI start) so that
        # a freshly created venv already has the patch before first launch.
        _tqdm_patch = (
            "\n# tqdm pipe-safe patch — injected by IsonCodexProducer\n"
            "try:\n"
            "    import tqdm.std as _ts\n"
            "    def _safe_fp_write(fp, s):\n"
            "        try:\n"
            "            if hasattr(fp, 'write'): fp.write(str(s))\n"
            "            try:\n"
            "                if hasattr(fp, 'flush'): fp.flush()\n"
            "            except (OSError, AttributeError): pass\n"
            "        except (OSError, AttributeError): pass\n"
            "    _ts.std_tqdm.fp_write = staticmethod(_safe_fp_write)\n"
            "except Exception: pass\n"
        )
        for _site_dir in [
            os.path.join(venv_dir, "Lib", "site-packages"),           # fresh venv
            os.path.join(venv_dir, "lib", "site-packages"),           # Linux/Mac
        ]:
            if os.path.isdir(_site_dir):
                _sc_path = os.path.join(_site_dir, "sitecustomize.py")
                try:
                    _existing = open(_sc_path, "r", encoding="utf-8").read() if os.path.isfile(_sc_path) else ""
                    if "_safe_fp_write" not in _existing:
                        with open(_sc_path, "a", encoding="utf-8") as _sc:
                            _sc.write(_tqdm_patch)
                        log("  tqdm sitecustomize.py patch written ✓", "SUCCESS")
                except Exception as _sce:
                    log(f"  tqdm sitecustomize.py patch failed: {_sce}", "WARNING")

        # ── Verify torch CUDA after requirements.txt ──────────────────────────
        # requirements.txt may overwrite torch. Always verify afterwards and
        # restore from WHL cache if needed.
        chk_torch_req = _run_hidden(
            [python_exe, "-c",
             "import torch; print(torch.cuda.is_available(), torch.__version__)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        out_tr = chk_torch_req.stdout.decode(errors="replace").strip()
        if out_tr.startswith("True") and f"+{cu_tag}" in out_tr:
            log(f"  torch CUDA after requirements.txt: {out_tr} ✓", "INFO")
        else:
            log(f"  torch CUDA lost after requirements.txt ({out_tr}) — restoring...", "WARNING")
            torch_cache_req = os.path.join(setup_cache, f"torch_{cu_tag}")
            cached_req = [f for f in os.listdir(torch_cache_req) if f.endswith(".whl")] \
                         if os.path.isdir(torch_cache_req) else []
            if len(cached_req) >= 3:
                _pip(["install", "torch", "torchvision", "torchaudio",
                      "--find-links", torch_cache_req, "--no-index"], timeout=300)
            log("  torch CUDA restored ✓", "SUCCESS")


        log("[ComfyUI-Install] Step 4/6: Downloading WAN 2.1 1.3B model...", "INFO")
        tick("models", "run", "Modelle laden...")
        # WAN 2.1 belongs in diffusion_models/ (NOT checkpoints/) — ComfyUI native
        models_dir = os.path.join(comfyui_dir, "models", "diffusion_models")
        os.makedirs(models_dir, exist_ok=True)
        model_name = "wan2.1_t2v_1.3B_bf16.safetensors"
        model_path = os.path.join(models_dir, model_name)

        # Cache path in the setupfiles folder
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
            log(f"[ComfyUI-Install] Model already in target folder ✓", "INFO")
            log(f"  {model_path}", "INFO")
        elif os.path.isfile(model_cache) and os.path.getsize(model_cache) > MIN_MODEL_SIZE:
            # Present in cache — simply copy/link to target folder
            log(f"[ComfyUI-Install] Modell im Cache gefunden — kopiere...", "SUCCESS")
            log(f"  Cache: {model_cache}", "INFO")
            try:
                import shutil as _shm
                _shm.copy2(model_cache, model_path)
                log(f"[ComfyUI-Install] Model copied ✓ → {model_path}", "SUCCESS")
            except Exception as e:
                log(f"[ComfyUI-Install] Kopieren failed: {e} — versuche Symlink.", "WARNING")
                try:
                    os.symlink(model_cache, model_path)
                    log(f"[ComfyUI-Install] Symlink created ✓", "SUCCESS")
                except Exception as e2:
                    log(f"[ComfyUI-Install] Symlink failed: {e2}", "WARNING")
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
                    log(f"[ComfyUI-Install] Model loaded ✓ ({attempt_label})", "SUCCESS")
                    log(f"  Cache: {cache_target}", "INFO")
                    log(f"  Ziel:  {dest}", "INFO")
                    # model_path auf den tatsaechlichen Dateinamen setzen
                    model_path = dest
                    downloaded = True
                    break
                except Exception as e:
                    log(f"  {attempt_label} failed: {e}", "WARNING")
            if not downloaded:
                log(
                    "[ComfyUI-Install] ⚠️  Modell-Download failed.\n"
                    "  Manuell laden und in setupfiles/ oder models/diffusion_models/ legen:\n"
                    f"  {setup_cache}\n"
                    "  Quelle: https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged",
                    "WARNING"
                )

        # ── 5a-2. WAN 2.1 14B GGUF — optional, much better quality ─────────────
        # Q4_K_M quantization: ~8.5 GB, runs via GPU/CPU offloading on RTX 3050
        # Place in models/unet/ — loaded via ComfyUI-GGUF node (UnetLoaderGGUF)
        unet_dir_inst = os.path.join(comfyui_dir, "models", "unet")
        os.makedirs(unet_dir_inst, exist_ok=True)

        WAN14B_GGUF_NAME  = "wan2.1_t2v_14B_Q4_K_M.gguf"
        WAN14B_GGUF_PATH  = os.path.join(unet_dir_inst, WAN14B_GGUF_NAME)
        WAN14B_GGUF_CACHE = os.path.join(setup_cache, WAN14B_GGUF_NAME)
        WAN14B_GGUF_URL   = (
            "https://huggingface.co/city96/Wan2.1-T2V-14B-gguf/resolve/main/"
            "wan2.1-t2v-14b-Q4_K_M.gguf?download=true"
        )
        WAN14B_MIN_SIZE   = 5_000_000_000  # 5 GB minimum (actual ~8.5 GB)

        _14b_exists = (
            (os.path.isfile(WAN14B_GGUF_PATH)  and os.path.getsize(WAN14B_GGUF_PATH)  > WAN14B_MIN_SIZE) or
            (os.path.isfile(WAN14B_GGUF_CACHE) and os.path.getsize(WAN14B_GGUF_CACHE) > WAN14B_MIN_SIZE)
        )

        if _14b_exists:
            log(f"[ComfyUI-Install] WAN 2.1 14B GGUF already present ✓", "INFO")
            # Copy from cache to unet dir if needed
            if not (os.path.isfile(WAN14B_GGUF_PATH) and os.path.getsize(WAN14B_GGUF_PATH) > WAN14B_MIN_SIZE):
                import shutil as _sh14
                _sh14.copy2(WAN14B_GGUF_CACHE, WAN14B_GGUF_PATH)
                log(f"[ComfyUI-Install] WAN 2.1 14B copied from cache ✓", "SUCCESS")
        else:
            log(
                f"[ComfyUI-Install] WAN 2.1 14B GGUF not found — skipping (optional).\n"
                f"  To download manually (~8.5 GB):\n"
                f"  URL: {WAN14B_GGUF_URL}\n"
                f"  Place in: {unet_dir_inst}\n"
                f"  Or cache at: {WAN14B_GGUF_CACHE}\n"
                f"  Then click 'Install ComfyUI' again — will auto-copy and use 14B.",
                "INFO"
            )
            # Attempt auto-download — skipped if file is large and connection is slow
            # User can always download manually and click Install again
            log("[ComfyUI-Install] WAN 2.1 14B: attempting auto-download (~8.5 GB) — this may take a long time.", "INFO")
            log("[ComfyUI-Install] WAN 2.1 14B: close and place file manually if too slow.", "INFO")
            try:
                urllib.request.urlretrieve(WAN14B_GGUF_URL, WAN14B_GGUF_CACHE)
                if os.path.isfile(WAN14B_GGUF_CACHE) and os.path.getsize(WAN14B_GGUF_CACHE) > WAN14B_MIN_SIZE:
                    import shutil as _sh14b
                    _sh14b.copy2(WAN14B_GGUF_CACHE, WAN14B_GGUF_PATH)
                    log(f"[ComfyUI-Install] WAN 2.1 14B GGUF downloaded and installed ✓", "SUCCESS")
                else:
                    log("[ComfyUI-Install] WAN 2.1 14B download incomplete — place file manually.", "WARNING")
            except Exception as _e14:
                log(f"[ComfyUI-Install] WAN 2.1 14B auto-download failed: {_e14}", "WARNING")
                log("[ComfyUI-Install] WAN 2.1 14B: download manually and click Install again.", "INFO")

        # ── 5b. WAN VAE + T5 Text Encoder herunterladen ─────────────────────
        # Both are required by ComfyUI — without them every
        # Workflow fehl. Werden gecacht in setupfiles/ und nach models/vae/ bzw.
        # models/text_encoders/ kopiert.
        log("[ComfyUI-Install] Downloading WAN VAE + T5 text encoder...", "INFO")
        tick("models", "run", "VAE + T5 laden...")

        def _ensure_model(filename: str, dest_dir: str, url: str,
                          min_size: int = 10_000_000, label: str = "") -> bool:
            """Downloads a model file if not already in target or cache.
            Returns True if file is available at the end."""
            dest_path  = os.path.join(dest_dir, filename)
            cache_path = os.path.join(setup_cache, filename)
            os.makedirs(dest_dir, exist_ok=True)

            if os.path.isfile(dest_path) and os.path.getsize(dest_path) > min_size:
                log(f"  {label or filename}: already present ✓", "INFO")
                return True
            if os.path.isfile(cache_path) and os.path.getsize(cache_path) > min_size:
                log(f"  {label or filename}: aus Cache kopieren...", "INFO")
                try:
                    import shutil as _shx
                    _shx.copy2(cache_path, dest_path)
                    log(f"  {label or filename}: copied ✓", "SUCCESS")
                    return True
                except Exception as e:
                    log(f"  {label or filename}: Kopieren failed: {e}", "WARNING")
            # Herunterladen → zuerst in Cache, dann in Ziel kopieren
            log(f"  {label or filename}: lade herunter...", "INFO")
            log(f"    URL: {url}", "INFO")
            try:
                urllib.request.urlretrieve(url, cache_path)
                import shutil as _shx2
                _shx2.copy2(cache_path, dest_path)
                log(f"  {label or filename}: downloaded ✓", "SUCCESS")
                return True
            except Exception as e:
                log(f"  {label or filename}: Download failed: {e}", "WARNING")
                log(f"    Load manually: {url}", "WARNING")
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
        log("[ComfyUI-Install] Downloading SD 1.5 checkpoint...", "INFO")
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
        log("[ComfyUI-Install] Downloading ChatterBox TTS model...", "INFO")
        tick("chatterbox", "run", "ChatterBox TTS Modell laden...")
        chatterbox_dir        = os.path.join(comfyui_dir, "models", "TTS", "chatterbox")
        chatterbox_cache_dir  = os.path.join(setup_cache, "chatterbox")
        os.makedirs(chatterbox_dir, exist_ok=True)
        os.makedirs(chatterbox_cache_dir, exist_ok=True)

        # TTS-Audio-Suite loads ChatterBox models into chatterbox/English/ subfolder.
        # Two formats exist: .pt (original HF) and .safetensors (TTS-Audio-Suite download).
        # We cache and check both levels (Root + English/) for both formats.
        _CB_REQUIRED_ROOT = ["s3gen.pt", "t3_cfg.pt", "tokenizer.model"]
        _CB_REQUIRED_EN_PT  = ["s3gen.pt", "t3_cfg.pt", "tokenizer.json", "ve.pt", "conds.pt"]
        _CB_REQUIRED_EN_SF  = ["s3gen.safetensors", "t3_cfg.safetensors", "tokenizer.json"]

        def _chatterbox_complete(d: str) -> bool:
            """Returns True if the ChatterBox model directory contains all required files (.pt or .safetensors)."""
            # Root-level (old HF structure, .pt)
            if all(os.path.isfile(os.path.join(d, f)) for f in _CB_REQUIRED_ROOT):
                return True
            # English/ subfolder — TTS-Audio-Suite structure (.pt or .safetensors)
            en = os.path.join(d, "English")
            if os.path.isdir(en):
                if all(os.path.isfile(os.path.join(en, f)) for f in _CB_REQUIRED_EN_PT):
                    return True
                if all(os.path.isfile(os.path.join(en, f)) for f in _CB_REQUIRED_EN_SF):
                    return True
            return False

        def _cache_chatterbox_english(src_base: str, dst_base: str):
            """Copies the English/ subfolder (with all model files) from src_base to dst_base cache."""
            en_src = os.path.join(src_base, "English")
            en_dst = os.path.join(dst_base, "English")
            if os.path.isdir(en_src):
                try:
                    import shutil as _shcb_bk
                    _shcb_bk.copytree(en_src, en_dst, dirs_exist_ok=True)
                    # Also copy any .safetensors at root level
                    for _fn in os.listdir(src_base):
                        if _fn.endswith(".safetensors") or _fn.endswith(".pt"):
                            _shcb_bk.copy2(
                                os.path.join(src_base, _fn),
                                os.path.join(dst_base, _fn)
                            )
                    log("  ChatterBox: model files backed up to setupfiles cache ✓", "INFO")
                except Exception as _bke:
                    log(f"  ChatterBox: cache backup failed (non-critical): {_bke}", "WARNING")

        if _chatterbox_complete(chatterbox_dir):
            log("  ChatterBox: model already present ✓", "INFO")
            tick("chatterbox", "ok", "ChatterBox already present")
            # Back up all model files (including .safetensors) to setupfiles cache
            if not _chatterbox_complete(chatterbox_cache_dir):
                _cache_chatterbox_english(chatterbox_dir, chatterbox_cache_dir)
        elif _chatterbox_complete(chatterbox_cache_dir):
            log("  ChatterBox: Copying from cache...", "SUCCESS")
            import shutil as _shcb
            for f in os.listdir(chatterbox_cache_dir):
                if f.startswith("."):
                    continue  # Skip .cache and other hidden folders
                src = os.path.join(chatterbox_cache_dir, f)
                dst = os.path.join(chatterbox_dir, f)
                try:
                    if os.path.isdir(src):
                        _shcb.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        _shcb.copy2(src, dst)
                except Exception:
                    pass
            log("  ChatterBox: model copied ✓", "SUCCESS")
        else:
            log("  ChatterBox: Downloading from HuggingFace (~1 GB) → Cache: setupfiles/chatterbox/", "INFO")
            try:
                dl_cb = _run_hidden(
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
                    log("  ChatterBox: downloaded ✓ — copying to target folder...", "SUCCESS")
                    import shutil as _shcb2
                    for f in os.listdir(chatterbox_cache_dir):
                        if f.startswith("."):
                            continue  # Skip .cache
                        src = os.path.join(chatterbox_cache_dir, f)
                        dst = os.path.join(chatterbox_dir, f)
                        try:
                            if os.path.isdir(src):
                                _shcb2.copytree(src, dst, dirs_exist_ok=True)
                            else:
                                _shcb2.copy2(src, dst)
                        except Exception:
                            pass
                    log("  ChatterBox: model installed ✓", "SUCCESS")
                    tick("chatterbox", "ok", "ChatterBox installed")
                else:
                    log(f"  ChatterBox: download failed — {dl_cb.stderr.decode(errors='replace')[-200:]}", "WARNING")
            except Exception as e:
                log(f"  ChatterBox: Error: {e}", "WARNING")

        # After installation: if the TTS-Audio-Suite has downloaded .safetensors files
        # into the model dir (during a previous TTS job), back them up to setupfiles now.
        if _chatterbox_complete(chatterbox_dir) and not _chatterbox_complete(chatterbox_cache_dir):
            log("  ChatterBox: Backing up model files to setupfiles cache...", "INFO")
            _cache_chatterbox_english(chatterbox_dir, chatterbox_cache_dir)

        # ── 6. Custom Nodes klonen ────────────────────────────────────────────
        custom_nodes_dir = os.path.join(comfyui_dir, "custom_nodes")
        os.makedirs(custom_nodes_dir, exist_ok=True)

        custom_nodes = [
            ("ComfyUI-Manager",
             "https://github.com/ltdrdata/ComfyUI-Manager.git"),
            ("ComfyUI-GGUF",
             "https://github.com/city96/ComfyUI-GGUF.git"),
            ("ComfyUI-VideoHelperSuite",
             "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git"),
            ("ComfyUI-AudioTools",
             "https://github.com/eigenpunk/ComfyUI-audio.git"),
            ("ComfyUI-Florence2",
             "https://github.com/kijai/ComfyUI-Florence2.git"),
            # GGUF loader — required for WAN 2.1 14B quantized models
            ("ComfyUI-GGUF",
             "https://github.com/city96/ComfyUI-GGUF.git"),
            # ── Cinematic Audio Pipeline ──────────────────────────────────────
            ("TTS-Audio-Suite",
             "https://github.com/diodiogod/TTS-Audio-Suite.git"),
            # Music: ACE-Step 1.5 — Cinematic orchestral soundtrack
            ("ComfyUI_ACE-Step",
             "https://github.com/billwuhao/ComfyUI_ACE-Step.git"),
        ]

        log("[ComfyUI-Install] Step 5/6: Cloning custom nodes...", "INFO")
        tick("nodes", "run", "Custom Nodes klonen...")
        for node_name, node_url in custom_nodes:
            node_dir = os.path.join(custom_nodes_dir, node_name)
            if os.path.isdir(node_dir):
                # Vorhanden — git pull um auf neueste Version zu aktualisieren
                try:
                    r = _run_hidden(
                        ["git", "pull", "--ff-only"],
                        cwd=node_dir, capture_output=True, timeout=60
                    )
                    if r.returncode == 0:
                        out = r.stdout.decode(errors="replace").strip()
                        if "Already up to date" in out:
                            log(f"[ComfyUI-Install] {node_name}: already up to date ✓", "INFO")
                        else:
                            log(f"[ComfyUI-Install] {node_name}: updated ✓", "SUCCESS")
                    else:
                        log(f"[ComfyUI-Install] {node_name}: git pull failed (non-critical)", "WARNING")
                except Exception:
                    log(f"[ComfyUI-Install] {node_name}: already present (no update).", "INFO")
                continue
            log(f"  Klone {node_name}...", "INFO")
            try:
                subprocess.check_call(
                    ["git", "clone", "--depth=1", node_url, node_dir],
                    timeout=120,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                log(f"  {node_name} cloned ✓", "SUCCESS")
            except FileNotFoundError:
                log("  git not found — custom nodes must be installed manually.", "WARNING")
                break
            except Exception as e:
                log(f"  {node_name} failed (non-critical): {e}", "WARNING")

        # ── Custom Node Dependencies installieren ─────────────────────────────
        log("[ComfyUI-Install] Installing custom node dependencies...", "INFO")
        tick("nodedeps", "run", "Node Dependencies installieren...")

        # ComfyUI-GGUF: requires gguf package for 14B model loading
        gguf_node_dir = os.path.join(custom_nodes_dir, "ComfyUI-GGUF")
        if os.path.isdir(gguf_node_dir):
            log("  ComfyUI-GGUF: installing gguf package...", "INFO")
            gguf_ok = _pip(["install", "gguf", "--no-cache-dir"], timeout=120)
            if gguf_ok:
                log("  ComfyUI-GGUF: gguf installed ✓", "SUCCESS")
            else:
                log("  ComfyUI-GGUF: gguf install failed — 14B GGUF loading unavailable", "WARNING")
            # Also install in pytorch_env if it exists — ComfyUI may run with that Python
            pytorch_env_pip = os.path.join(
                os.path.expanduser("~"), "pytorch_env", "venv", "Scripts", "pip.exe"
            )
            if os.path.isfile(pytorch_env_pip) and pytorch_env_pip != pip_exe:
                try:
                    _run_hidden(
                        [pytorch_env_pip, "install", "gguf", "--no-cache-dir"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    log("  ComfyUI-GGUF: gguf installed in pytorch_env ✓", "SUCCESS")
                except Exception as _ge:
                    log(f"  ComfyUI-GGUF: gguf in pytorch_env failed: {_ge}", "WARNING")

        # VideoHelperSuite: braucht opencv-python, imageio-ffmpeg
        vhs_req = os.path.join(custom_nodes_dir, "ComfyUI-VideoHelperSuite", "requirements.txt")
        if os.path.isfile(vhs_req):
            log("  VideoHelperSuite: installing requirements.txt...", "INFO")
            _pip(["install", "-r", vhs_req, "--no-cache-dir"], timeout=180)
        else:
            # Direkt installieren falls requirements.txt fehlt
            log("  VideoHelperSuite: installiere cv2, imageio-ffmpeg...", "INFO")
            _pip(["install", "opencv-python", "imageio-ffmpeg",
                  "numpy", "Pillow", "--no-cache-dir"], timeout=180)

        # AudioTools: librosa direkt installieren (requirements.txt oft inkompatibel)
        librosa_ok = False
        try:
            r = _run_hidden(
                [python_exe, "-c", "import librosa; print('ok')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
            )
            librosa_ok = r.returncode == 0
        except Exception:
            pass

        if not librosa_ok:
            log("  AudioTools: installing librosa (directly, without requirements.txt)...", "INFO")
            # Nur die tatsaechlich fehlenden Kern-Abhaengigkeiten
            _pip(["install", "librosa", "soundfile", "resampy",
                  "--no-cache-dir"], timeout=300)
        else:
            log("  AudioTools: librosa already installed ✓", "INFO")

        # Florence2: timm + einops (leichtgewichtig, selten Konflikte)
        florence2_req = os.path.join(custom_nodes_dir, "ComfyUI-Florence2", "requirements.txt")
        if os.path.isfile(florence2_req):
            log("  Florence2: installing requirements.txt...", "INFO")
            _pip(["install", "-r", florence2_req, "--no-cache-dir"], timeout=180)
        elif os.path.isdir(os.path.join(custom_nodes_dir, "ComfyUI-Florence2")):
            log("  Florence2: installiere timm, einops...", "INFO")
            _pip(["install", "timm", "einops", "--no-cache-dir"], timeout=120)

        # TTS-Audio-Suite: F5-TTS, ChatterBox etc. — Narration + Dialoge
        tts_req = os.path.join(custom_nodes_dir, "TTS-Audio-Suite", "requirements.txt")
        if os.path.isfile(tts_req):
            log("  TTS-Audio-Suite: installing requirements.txt...", "INFO")
            _pip(["install", "-r", tts_req, "--no-cache-dir"], timeout=600)
        if os.path.isdir(os.path.join(custom_nodes_dir, "TTS-Audio-Suite")):
            # Fehlende Engine-Dependencies einzeln installieren —
            # a failed package should not block the others
            log("  TTS-Audio-Suite: installing missing engine deps (individually)...", "INFO")
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
                check = _run_hidden(
                    [python_exe, "-c", f"import {import_name}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if check.returncode == 0:
                    log(f"    {pkg}: already installed ✓", "INFO")
                    continue
                ok = _pip(["install", pkg, "--no-cache-dir"], timeout=180)
                # Versionskonflikte/Build-Fehler umgehen
                if not ok and pkg in ("descript-audio-codec", "omegaconf"):
                    ok = _pip(["install", pkg, "--no-cache-dir", "--no-deps"], timeout=60)
                if not ok and pkg == "chatterbox-tts":
                    ok = _pip(["install", pkg, "--no-cache-dir", "--no-deps"], timeout=120)
                    if ok:
                        # Sicherheitscheck: torch CUDA nach chatterbox-tts Installation
                        chk_torch = _run_hidden(
                            [python_exe, "-c",
                             "import torch; assert torch.cuda.is_available(), 'CUDA verloren';"
                             "print('torch CUDA OK:', torch.__version__)"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                        )
                        if chk_torch.returncode != 0:
                            log("  ⚠️  torch CUDA nach chatterbox-tts verloren — restoring...", "WARNING")
                            # torch CUDA aus Cache wiederherstellen
                            torch_cache = os.path.join(setup_cache, f"torch_{cu_tag}")
                            if os.path.isdir(torch_cache):
                                _pip(["install", "torch", "torchvision", "torchaudio",
                                      "--find-links", torch_cache, "--no-index"], timeout=300)
                                log("  torch CUDA restored ✓", "SUCCESS")
                        else:
                            log(f"  torch CUDA nach chatterbox-tts: {chk_torch.stdout.decode().strip()}", "INFO")
                if ok:
                    log(f"    {pkg} ({engine}): installed ✓", "INFO")
                else:
                    log(f"    {pkg} ({engine}): failed — engine impaired", "WARNING")

        # ACE-Step: requirements.txt zeilenweise installieren (robust gegen Konflikte)
        ace_req = os.path.join(custom_nodes_dir, "ComfyUI_ACE-Step", "requirements.txt")
        if os.path.isfile(ace_req):
            log("  ACE-Step: installing requirements.txt (line by line)...", "INFO")
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
                    chk = _run_hidden(
                        [python_exe, "-c", f"import {_imp}"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
                        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    )
                    if chk.returncode == 0:
                        continue  # already present
                    ok = _pip(["install", ace_pkg, "--no-cache-dir"], timeout=180)
                    if ok:
                        log(f"    ACE-Step dep '{ace_pkg}': installed ✓", "INFO")
                    else:
                        # Fallback ohne Deps
                        ok2 = _pip(["install", ace_pkg, "--no-cache-dir", "--no-deps"], timeout=60)
                        if ok2:
                            log(f"    ACE-Step dep '{ace_pkg}': installed (--no-deps) ✓", "INFO")
                        else:
                            log(f"    ACE-Step dep '{ace_pkg}': failed", "WARNING")
            except Exception as e:
                log(f"  ACE-Step requirements.txt Error: {e}", "WARNING")

        # ACE-Step Modell-Ordner erstellen (verhindert FileNotFoundError beim Start)
        ace_model_dir       = os.path.join(comfyui_dir, "models", "TTS", "ACE-Step-v1-3.5B")
        ace_model_cache_dir = os.path.join(setup_cache, "ACE-Step-v1-3.5B")
        for ace_sub in ("ace_step_transformer", "music_dcae_f8c8",
                        "music_vocoder", "umt5-base", "loras"):
            os.makedirs(os.path.join(ace_model_dir, ace_sub), exist_ok=True)
            os.makedirs(os.path.join(ace_model_cache_dir, ace_sub), exist_ok=True)

        _ACE_SUBS = ("ace_step_transformer", "music_dcae_f8c8", "music_vocoder", "umt5-base")
        # Minimum file sizes to count as valid (not just a config stub)
        _ACE_MIN_BYTES = {
            "ace_step_transformer": 100_000_000,   # ~3.5 GB actual, 100 MB minimum
            "music_dcae_f8c8":       50_000_000,   # ~299 MB
            "music_vocoder":         50_000_000,   # ~196 MB
            "umt5-base":            500_000_000,   # ~1.07 GB
        }

        def _ace_model_complete(base: str) -> bool:
            """Returns True if all required ACE-Step model subfolders contain valid .safetensors files."""
            for sub in _ACE_SUBS:
                d = os.path.join(base, sub)
                if not os.path.isdir(d):
                    return False
                # Must have at least one .safetensors or .bin file above minimum size
                min_size = _ACE_MIN_BYTES.get(sub, 1_000_000)
                model_files = [
                    f for f in os.listdir(d)
                    if f.endswith((".safetensors", ".bin", ".pt"))
                    and os.path.getsize(os.path.join(d, f)) >= min_size
                ]
                if not model_files:
                    return False
            return True

        # Log which subfolders are missing/incomplete for debugging
        def _ace_status(base: str) -> str:
            """Returns a short status string showing which subfolders are complete."""
            parts = []
            for sub in _ACE_SUBS:
                d = os.path.join(base, sub)
                if not os.path.isdir(d):
                    parts.append(f"{sub}:MISSING")
                    continue
                min_size = _ACE_MIN_BYTES.get(sub, 1_000_000)
                model_files = [
                    f for f in os.listdir(d)
                    if f.endswith((".safetensors", ".bin", ".pt"))
                    and os.path.getsize(os.path.join(d, f)) >= min_size
                ]
                size_mb = sum(
                    os.path.getsize(os.path.join(d, f))
                    for f in os.listdir(d)
                    if f.endswith((".safetensors", ".bin", ".pt"))
                ) // 1_000_000
                parts.append(f"{sub}:{'✓' if model_files else f'✗({size_mb}MB)'}")
            return " | ".join(parts)

        log(f"  ACE-Step status (target):  {_ace_status(ace_model_dir)}", "INFO")
        log(f"  ACE-Step status (cache):   {_ace_status(ace_model_cache_dir)}", "INFO")

        if _ace_model_complete(ace_model_dir):
            log("  ACE-Step: model already present ✓", "INFO")
        elif _ace_model_complete(ace_model_cache_dir):
            log("  ACE-Step: Copying from cache...", "SUCCESS")
            import shutil as _shace
            _shace.copytree(ace_model_cache_dir, ace_model_dir, dirs_exist_ok=True)
            log("  ACE-Step: model copied ✓", "SUCCESS")
        else:
            log("  ACE-Step: Downloading from HuggingFace (~5 GB) → Cache: setupfiles/ACE-Step-v1-3.5B/", "INFO")
            log("  ACE-Step: This may take 10–30 minutes depending on connection speed.", "INFO")
            # Remove any .incomplete or .lock files that block re-download
            import glob as _glob
            for _stale in _glob.glob(os.path.join(ace_model_cache_dir, "**", "*.incomplete"), recursive=True) + \
                          _glob.glob(os.path.join(ace_model_cache_dir, "**", "*.lock"), recursive=True):
                try:
                    os.remove(_stale)
                    log(f"  ACE-Step: Removed stale lock: {os.path.basename(_stale)}", "INFO")
                except Exception:
                    pass
            try:
                # Run download with stdout visible so progress is logged
                dl_ace = subprocess.Popen(
                    [python_exe, "-c",
                     "import sys; sys.stderr = sys.stdout; "
                     "from huggingface_hub import snapshot_download; "
                     "snapshot_download("
                     "  repo_id='ACE-Step/ACE-Step-v1-3.5B',"
                     f"  local_dir=r'{ace_model_cache_dir}',"
                     "  repo_type='model',"
                     "  ignore_patterns=['*.md','*.txt','*.gitattributes']"
                     "); print('DONE')"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                # Stream download output so installer popup shows progress
                import time as _time
                last_log = _time.time()
                stdout_lines = []
                for _line in dl_ace.stdout:
                    _line = _line.rstrip()
                    stdout_lines.append(_line)
                    # Log progress lines (size info, file names) every 5s
                    if _line and _time.time() - last_log >= 5:
                        log(f"  ACE-Step: {_line[:120]}", "INFO")
                        last_log = _time.time()
                dl_ace.wait()
                full_out = "\n".join(stdout_lines)

                if "DONE" in full_out or _ace_model_complete(ace_model_cache_dir):
                    log(f"  ACE-Step status after download: {_ace_status(ace_model_cache_dir)}", "INFO")
                    log("  ACE-Step: downloaded ✓ — copying to target folder...", "SUCCESS")
                    tick("ace", "ok", "ACE-Step installed")
                    import shutil as _shace2
                    _shace2.copytree(ace_model_cache_dir, ace_model_dir, dirs_exist_ok=True)
                    log("  ACE-Step: model installed ✓", "SUCCESS")
                else:
                    log(f"  ACE-Step status after download: {_ace_status(ace_model_cache_dir)}", "WARNING")
                    log(f"  ACE-Step: download incomplete — last output: {full_out[-300:]}", "WARNING")
                    log("  ACE-Step: Click 'Install ComfyUI' again to resume download.", "WARNING")
            except Exception as e:
                log(f"  ACE-Step: Error: {e}", "WARNING")

        # ── chatterbox-tts: ALWAYS --no-deps, protect torch CUDA afterwards ────────
        # chatterbox-tts zieht torch CPU als Dependency — das zerstoert die CUDA-
        # Installation. Loesung: --no-deps, dann torch CUDA aus Cache wiederherstellen.
        # Check if ChatterboxTTS is fully functional (not just importable)
        chk_cb = _run_hidden(
            [python_exe, "-c", "from chatterbox.tts import ChatterboxTTS; print('OK')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        cb_ok = b"OK" in chk_cb.stdout
        if cb_ok:
            log("  chatterbox-tts: ChatterboxTTS available ✓", "INFO")
        else:
            err_cb = chk_cb.stderr.decode(errors="replace")[-300:]
            tick("chatterboxpkg", "run", "chatterbox-tts installieren...")
            log(f"  chatterbox-tts: ChatterboxTTS not available — installing...", "INFO")
            if err_cb:
                log(f"  Error: {err_cb}", "INFO")

            # Immer --no-deps (verhindert torch CPU-Downgrade)
            _pip(["install", "chatterbox-tts", "--no-deps", "--no-cache-dir"], timeout=120)

            # Install all required deps (WITHOUT torch)
            cb_deps = [
                "resemble-perth",        # Watermarking (required for ChatterboxTTS)
                "conformer",             # Audio-Encoder
                "vocos",                 # Vocoder
                "encodec",               # Audio-Codec
                "rotary-embedding-torch", # Transformer
                "einops",                # Tensor-Ops
                "s3tokenizer",           # Tokenizer
                "antlr4-python3-runtime==4.9.3",  # Dependency of omegaconf
            ]
            for dep in cb_deps:
                dep_imp = dep.split("==")[0].replace("-", "_").lower()
                chk_dep = _run_hidden(
                    [python_exe, "-c", f"import {dep_imp}"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                if chk_dep.returncode != 0:
                    ok_dep = _pip(["install", dep, "--no-cache-dir"], timeout=120)
                    if not ok_dep:
                        ok_dep = _pip(["install", dep, "--no-cache-dir", "--no-deps"], timeout=60)
                    # antlr4 Versions-Fallback: 4.9.3 schlaegt oft fehl → 4.13.2 versuchen
                    if not ok_dep and "antlr4" in dep:
                        ok_dep = _pip(["install", "antlr4-python3-runtime==4.13.2",
                                       "--no-cache-dir"], timeout=60)
                    log(f"    {dep}: {'✓' if ok_dep else 'failed'}", "SUCCESS" if ok_dep else "WARNING")
                else:
                    log(f"    {dep}: already installed ✓", "INFO")

            # Verifikation
            chk_cb2 = _run_hidden(
                [python_exe, "-c", "from chatterbox.tts import ChatterboxTTS; print('OK')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if b"OK" in chk_cb2.stdout:
                log("  ChatterboxTTS: ready ✓", "SUCCESS")
                tick("chatterboxpkg", "ok", "ChatterboxTTS bereit")
            else:
                log(f"  ChatterboxTTS: still not available — {chk_cb2.stderr.decode(errors='replace')[-200:]}", "WARNING")
                tick("chatterboxpkg", "fail")

            # torch CUDA sofort wiederherstellen (sicherheitshalber immer)
            log("  Verifying torch CUDA...", "INFO")
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
            chk_t = _run_hidden(
                [python_exe, "-c",
                 "import torch; print(torch.cuda.is_available(), torch.__version__)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            out_t = chk_t.stdout.decode(errors="replace").strip()
            if out_t.startswith("True"):
                log(f"  torch CUDA verified ✓ — {out_t}", "SUCCESS")
            else:
                log(f"  ⚠️  torch CUDA Problem: {out_t}", "WARNING")

        log("[ComfyUI-Install] Custom node dependencies installed ✓", "SUCCESS")
        tick("nodes", "ok")
        tick("nodedeps", "ok", "Dependencies installiert")

        # ── Startskript erstellen ─────────────────────────────────────────────
        log("[ComfyUI-Install] Step 6/6: Creating start script...", "INFO")
        tick("nodedeps", "ok")
        bat_path = os.path.join(comfyui_dir, "start_comfyui.bat")
        bat_content = (
            "@echo off\n"
            "echo Starting ComfyUI...\n"
            f'"{python_exe}" main.py --listen\n'
            "pause\n"
        )
        try:
            with open(bat_path, "w", encoding="utf-8") as f:
                f.write(bat_content)
            log(f"[ComfyUI-Install] Start script: {bat_path}", "INFO")
        except Exception:
            pass

        log("", "INFO")
        log("══════════════════════════════════════════════════════", "SUCCESS")
        log("  ComfyUI installation complete! ✅", "SUCCESS")
        tick("start", "ok", "Installation complete!")
        log(f"  Path: {comfyui_dir}", "SUCCESS")
        log("══════════════════════════════════════════════════════", "SUCCESS")

        # ── Step 7: Start ComfyUI directly ────────────────────────────────
        log("[ComfyUI-Install] Step 7/7 (Bonus): Starting ComfyUI...", "INFO")
        tick("start", "run", "Starting ComfyUI...")

        # Clean port 8188 — terminate any running instance from previous installer run
        _kill_comfyui_port(8188, log_cb=log)

        # Check CUDA — use --cpu flag if CUDA unavailable
        _cuda_ok = False
        try:
            _r = _run_hidden(
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
            log("[ComfyUI] No CUDA — starting in CPU mode (--cpu).", "WARNING")
        else:
            log("[ComfyUI] CUDA active ✓", "SUCCESS")

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
            log(f"[ComfyUI] Process started (PID {proc.pid})", "SUCCESS")
            log(f"[ComfyUI] Available at: http://127.0.0.1:8188", "INFO")
            log("[ComfyUI] Streaming logs — waiting for 'To see the GUI go to:'", "INFO")

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
                """Reads ComfyUI installer stdout and forwards lines to the GUI log."""
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
                log("[ComfyUI] Process terminated.", "WARNING")

            threading.Thread(target=_stream, daemon=True).start()

        except Exception as e:
            log(f"[ComfyUI] Auto-Start failed: {e}", "WARNING")
            log(f"  → Start manually: {bat_path}", "INFO")

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

        # Phase 1: Scenen produzieren
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
        """Builds the full edit dialog UI: header, fields, prompt area, action buttons."""
        # Header
        hdr = tk.Frame(self, bg=COLORS["bg"], pady=10)
        hdr.pack(fill="x", padx=16)
        tk.Label(hdr, text=f"\U0001f3ac  Scene {self._scene['id']}",
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
            """Creates a label + widget pair in a grid row inside the given parent frame."""
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
            """Builds the tool dropdown widget with API key status indicators."""
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
        """Returns the full filesystem path of the currently selected clip, or None if none selected."""
        sel = self._clip_var.get()
        if not sel or sel.startswith("—"):
            return None
        for p in self._clip_files:
            if os.path.basename(p) == sel:
                return p
        return None

    def _on_clip_rightclick(self, event):
        """Shows a right-click context menu on the clip dropdown widget."""
        if self._clip_var.get().startswith("—"):
            return
        try:
            self._clip_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._clip_menu.grab_release()

    def _clip_play(self):
        """Opens the selected clip file in the default Windows media player."""
        path = self._selected_clip_path()
        if not path or not os.path.isfile(path):
            messagebox.showinfo("No Clip", "Clip file not found.")
            return
        import subprocess
        subprocess.Popen(["start", "", path], shell=True)

    def _clip_open_location(self):
        """Opens the folder containing the selected clip in Windows Explorer."""
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
        """Deletes the selected clip file after user confirmation."""
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
        """Reads prompt.txt from disk and loads the appropriate section into the text area."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self._raw_prompt_file = content
            self._on_tab_switch()
        except Exception as e:
            self._prompt_text.delete("1.0", "end")
            self._prompt_text.insert("1.0", f"Fehler beim Lesen: {e}")

    def _on_tab_switch(self):
        """Switches the text area between Base Prompt and Enhanced Prompt view."""
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

        # Bug fix: update s['prompt'] in scene dict when base prompt is changed
        if mode == "base":
            s["prompt"] = new_text

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
                messagebox.showerror("Fehler", f"Prompt.txt speichern failed:\n{e}")
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

        # ── Persisting scene list (bug fix: cross-session) ──
        try:
            _save_active_scenes(self._storage_root, _get_active_scenes())
        except Exception as _e:
            print(f"[SceneEdit] _save_active_scenes failed: {_e}")

        if self._on_save:
            self._on_save()
        messagebox.showinfo("Gespeichert", f"Scene {s['id']} gespeichert ✓")

    def _delete_prompt(self):
        """Deletes prompt.txt for this scene after confirmation."""
        prompt_path = os.path.join(self._storage_root, "szenen",
                                   self._scene["id"], "prompt.txt")
        if not os.path.isfile(prompt_path):
            messagebox.showinfo("Info", "Kein Prompt vorhanden.")
            return
        if messagebox.askyesno("Delete Prompt",
                                f"prompt.txt für Scene {self._scene['id']} wirklich löschen?\n"
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
        """Initializes the main window, builds UI, sets up orchestrator."""
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
        """Centers the main window on the screen."""
        self.update_idletasks()
        w, h = 980, 760
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def _build_ui(self):
        """Builds the full UI: header, config panel, scene list, log area, buttons."""
        self._build_header()
        self._build_config()
        self._build_scene_panel()
        self._build_log()
        self._build_buttons()

    def _build_header(self):
        """Builds the title bar with the visual DNA color indicator."""
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
        """Builds the scrollable scene list with chapter grouping and status indicators."""
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
        self._action_btn(btn_frame, "\u25b6 Nur diese Scene",
                         self._run_single_scene, COLORS["accent"]).pack(side="left")
        tk.Label(btn_frame, text="(Select Scene + klicken)",
                 font=FONT_SMALL, fg=COLORS["dim"], bg=COLORS["panel"]).pack(side="left", padx=8)

    def _build_log(self):
        """Builds the scrollable log output area with color-coded levels."""
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


    def _open_installer_popup(self, steps: list) -> dict:
        """Opens a modal installer progress window in PyTorch-GUI style.

        Args:
            steps: List of (key, label) tuples for the checklist.
        Returns:
            dict with tick(key, state) and close() functions.
        """
        BG      = "#181825"
        BG_HDR  = "#1e1e2e"
        FG      = "#cdd6f4"
        FG_DIM  = "#6c7086"
        COL_PENDING = "#585b70"
        COL_RUN     = "#fab387"
        COL_OK      = "#a6e3a1"
        COL_FAIL    = "#f38ba8"
        PENDING = "  ···"
        RUNNING = "  ⏳"
        OK      = "  ✔"
        FAIL    = "  ✘"

        win = tk.Toplevel(self)
        win.title("ComfyUI Installation")
        win.resizable(False, False)
        win.grab_set()
        win.configure(bg=BG)

        w, h = 480, 80 + len(steps) * 34 + 80
        sx = self.winfo_x() + (self.winfo_width()  - w) // 2
        sy = self.winfo_y() + (self.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{sx}+{sy}")

        # Header
        hdr = tk.Frame(win, bg=BG_HDR, height=50)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="🖥️  ComfyUI Installation",
                 font=("Segoe UI", 12, "bold"),
                 bg=BG_HDR, fg=FG).pack(pady=12)

        # Checkliste
        list_frame = tk.Frame(win, bg=BG, padx=24, pady=10)
        list_frame.pack(fill="both", expand=True)

        row_widgets = {}
        for key, label_text in steps:
            row = tk.Frame(list_frame, bg=BG)
            row.pack(fill="x", pady=2)
            icon_var = tk.StringVar(value=PENDING)
            icon_lbl = tk.Label(row, textvariable=icon_var,
                                font=("Segoe UI", 11), bg=BG,
                                fg=COL_PENDING, width=5, anchor="w")
            icon_lbl.pack(side="left")
            tk.Label(row, text=label_text,
                     font=("Segoe UI", 10), bg=BG, fg=FG, anchor="w").pack(side="left")
            row_widgets[key] = (icon_var, icon_lbl)

        # Progressbar
        pb_frame = tk.Frame(win, bg=BG)
        pb_frame.pack(fill="x", padx=24, pady=(0, 4))
        pb = ttk.Progressbar(pb_frame, mode="determinate", maximum=len(steps))
        pb.pack(fill="x")

        # Status-Zeile
        status_var = tk.StringVar(value="Starting...")
        tk.Label(win, textvariable=status_var,
                 font=("Segoe UI", 9), fg=FG_DIM, bg=BG).pack(pady=(0, 10))

        def tick(key, state, status_text=""):
            """Updates a checklist row icon and optionally the status label (thread-safe)."""
            def _do():
                """Applies the icon/color update on the main thread."""
                if key in row_widgets:
                    icon_var, icon_lbl = row_widgets[key]
                    if state == "run":
                        icon_var.set(RUNNING); icon_lbl.config(fg=COL_RUN)
                    elif state == "ok":
                        icon_var.set(OK);      icon_lbl.config(fg=COL_OK);  pb.step(1)
                    elif state == "fail":
                        icon_var.set(FAIL);    icon_lbl.config(fg=COL_FAIL); pb.step(1)
                if status_text:
                    status_var.set(status_text)
            try:
                self.after(0, _do)
            except Exception:
                pass

        def close():
            """Destroys the installer popup window on the main thread."""
            try:
                self.after(0, win.destroy)
            except Exception:
                pass

        return {"tick": tick, "close": close, "status": status_var}

    def _build_buttons(self):
        """Builds the main action buttons."""
        bf = tk.Frame(self, bg=COLORS["bg"])
        bf.pack(fill="x", padx=16, pady=(4, 14))
        self._action_btn(bf, "\U0001f3ac  START PRODUCTION",
                         self._run_full_production, COLORS["gold"]).pack(side="left", padx=4)
        self._action_btn(bf, "\U0001f4c2  Open Storage",
                         self._open_storage, COLORS["accent"]).pack(side="left", padx=4)
        # ── ComfyUI-Installations-Button (neu v1.0.4) ─────────────────────────
        self._action_btn(bf, "\U0001f5a5\ufe0f  Install ComfyUI",
                         self._on_install_comfyui, COLORS["success"]).pack(side="left", padx=4)
        self._flat_btn(bf, "\U0001f50d  ComfyUI Nodes",
                       self._on_diagnose_comfyui).pack(side="left", padx=4)
        self._flat_btn(bf, "\U0001f5d1  Clear Log", self._clear_log).pack(side="right", padx=4)
        self._action_btn(bf, "\u25a0  STOP",
                         self._stop_production, COLORS["error"]).pack(side="right", padx=4)

    # ── Widget helpers ─────────────────────────────────────────────────────────

    def _flat_btn(self, parent, text, cmd):
        """Returns a small flat button widget with hover highlight effect."""
        b = tk.Button(parent, text=text, command=cmd, font=FONT_SMALL,
                      bg=COLORS["btn"], fg=COLORS["text"],
                      activebackground=COLORS["hover"], activeforeground=COLORS["accent"],
                      relief="flat", bd=0, padx=10, pady=5, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=COLORS["btn"]))
        return b

    def _action_btn(self, parent, text, cmd, color):
        """Returns a prominent action button widget with the given foreground color."""
        b = tk.Button(parent, text=text, command=cmd, font=FONT_BOLD,
                      bg=COLORS["btn"], fg=color,
                      activebackground=COLORS["hover"], activeforeground=color,
                      relief="flat", bd=0, padx=18, pady=9, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=COLORS["hover"]))
        b.bind("<Leave>", lambda e: b.config(bg=COLORS["btn"]))
        return b

    def _browse(self, var):
        """Opens a directory picker dialog, updates the StringVar, and saves the path."""
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
        """Refreshes the full scene list showing tool, API key, prompt, clip and title status."""
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
                        f"  {total_icon:4s}  Master-Prompt aller {len(_get_active_scenes())} Scenen")
        self._scene_list.insert("end", total_row)

    def _on_scene_double_click(self, event=None):
        """Opens SceneEditDialog for a scene, or generates the TOTAL master prompt if last row clicked."""
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
        """Shows a context menu on right-click. The TOTAL row shows its own menu."""
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
        """Returns the list of selected indices in the scene list widget."""
        return list(self._scene_list.curselection())

    def _delete_selected_prompts(self):
        """Deletes prompt.txt for all selected scenes after user confirmation."""
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

        self._log(f"[Scene] {deleted}/{len(ids)} prompt(s) deleted.", "SUCCESS")
        self._refresh_scene_list()

    def _delete_selected_clips(self):
        """Deletes all clip files for all selected scenes after user confirmation."""
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
        """Opens the output folder of the first selected scene in Windows Explorer."""
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
        """Runs production for all currently selected scenes in a background thread."""
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
            """Background thread: runs production for all selected scenes sequentially."""
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
        """Opens the TOTAL master prompt folder in Windows Explorer."""
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
            self._workers_status.config(text=f"❌ Error: {e}", foreground=COLORS["error"])
            self._log(f"Workers laden failed: {e}", "WARNING")

    def _make_orchestrator(self) -> ProductionOrchestrator:
        """Creates and returns a fresh ProductionOrchestrator using API keys from workers.json."""
        return ProductionOrchestrator(
            storage_root = os.path.normpath(self._storage_var.get().strip()),
            workers      = self._loaded_workers,
            log_cb       = self._log,
            dry_run      = self._dry_run_var.get(),
            refresh_cb   = lambda: self.after(0, self._refresh_scene_list),
        )

    def _populate_llm_import_dropdown(self):
        """Populates the LLM import dropdown with usable workers from workers.json
        plus locally running Ollama models fetched from the Ollama API."""
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
        """Opens a file dialog to select a script or novel text file for scene import."""
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
        """Enables or disables the Generate Scenes button based on prerequisites."""
        if not hasattr(self, "_gen_scenes_btn"):
            return
        has_file = bool(self._script_path and os.path.isfile(self._script_path))
        has_llm  = bool(self._llm_import_var.get())
        state    = "normal" if (has_file and has_llm) else "disabled"
        self._gen_scenes_btn.config(state=state)

    def _import_script_and_generate_scenes(self):
        """Reads script file, sends to selected LLM, validates JSON response, replaces scene list."""
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
                """Sends a message list to the selected LLM (Ollama or OpenAI-compatible) and returns the text response."""
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
                    """Logs a waiting message every 10 seconds while the LLM call is in progress."""
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
                """Strips markdown fences from raw LLM output and parses it as JSON. Returns the parsed object or None."""
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
        """Resets the active scene list back to the built-in Ison-Codex default scenes."""
        global _active_scenes
        n_default = len(SCENES)
        if not messagebox.askyesno(
            "Reset to Ison-Codex",
            f"Scenenliste auf die {n_default} Standard-Scenen (Ison-Codex) reset?\n\n"
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
        """Runs the full production (all scenes) in a background thread."""
        self._orchestrator = self._make_orchestrator()
        def _run():
            """Background thread target: runs the full production pipeline."""
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
            """Background thread target: runs production for a single scene."""
            self._orchestrator.run_production(scene_filter=scene["id"])
        threading.Thread(target=_run, daemon=True).start()

    def _stop_production(self):
        """Stops the running production and restarts ComfyUI."""
        if self._orchestrator:
            self._orchestrator.stop()
            self._log("■ Production stopped.", "WARNING")

        def _restart_comfyui():
            """Background thread: kills the current ComfyUI process and starts a fresh one."""
            import time
            # Wait briefly for running jobs to abort
            time.sleep(2)
            self._log("[ComfyUI] Restarting ComfyUI...", "INFO")
            orch = self._make_orchestrator()
            # ComfyUI beenden
            orch._kill_comfyui_on_port(8188)
            time.sleep(2)
            # ComfyUI neu starten
            ok = orch._start_comfyui_process()
            if ok:
                self.after(0, lambda: self._log(
                    "[ComfyUI] ✅ ComfyUI restarted.", "SUCCESS"))
            else:
                self.after(0, lambda: self._log(
                    "[ComfyUI] ⚠️  ComfyUI-Neustart fehlgeschlagen — "
                    "manuell starten via 'Install ComfyUI'.", "WARNING"))

        threading.Thread(target=_restart_comfyui, daemon=True).start()

    def _on_diagnose_comfyui(self):
        """Queries ComfyUI for exact node inputs and displays them in the log."""
        import threading, urllib.request, json as _json
        COMFYUI_URL = "http://127.0.0.1:8188"
        NODES_OF_INTEREST = [
            "ChatterBoxEngineNode", "UnifiedTTSTextNode",
            "ACEModelLoader", "ACEStepGen",
            "ACELoRALoader", "SaveAudio",
        ]

        def _query():
            """Background thread: fetches node input specs from ComfyUI and logs them."""
            self._log("🔍 Querying ComfyUI for node info...", "INFO")
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
                self._log(f"\n✅ {len(found)}/{len(NODES_OF_INTEREST)} nodes found.", "SUCCESS")
            except Exception as e:
                self._log(f"❌ Diagnostics failed: {e}", "ERROR")
                self._log("  → Ist ComfyUI gestartet? http://127.0.0.1:8188", "WARNING")

        threading.Thread(target=_query, daemon=True).start()

    def _on_install_comfyui(self):
        """GUI handler for the '🖥️ Install ComfyUI' button."""
        storage      = os.path.normpath(self._storage_var.get().strip())
        project_root = os.path.dirname(storage)
        comfyui_dir  = os.path.join(project_root, "ComfyUI-Portable")
        main_py      = os.path.join(comfyui_dir, "main.py")

        if os.path.isfile(main_py):
            if not messagebox.askyesno("ComfyUI bereits vorhanden",
                    f"ComfyUI ist bereits installiert:\n{comfyui_dir}\n\n"
                    "Trotzdem erneut pruefen / Custom Nodes nachinstallieren?"):
                return

        if not messagebox.askyesno("ComfyUI installieren",
                "Folgendes wird installiert:\n\n"
                "  • ComfyUI Portable\n"
                "  • venv + torch cu128\n"
                "  • WAN 2.1 1.3B · VAE · T5 · SD 1.5\n"
                "  • ChatterBox TTS · ACE-Step Musik\n"
                "  • Custom Nodes (6x)\n\n"
                f"Ziel: {comfyui_dir}\n\n"
                "Installation starten?"):
            return

        # Installer steps for the progress popup
        steps = [
            ("venv",        "venv + torch (CUDA)"),
            ("deps",        "requirements.txt"),
            ("tqdm",        "tqdm Fix (Windows-Pipe)"),
            ("models",      "WAN 2.1 · VAE · T5 · SD 1.5"),
            ("chatterbox",  "ChatterBox TTS Modell"),
            ("ace",         "ACE-Step Musik Modell"),
            ("nodes",       "Custom Nodes (6x)"),
            ("nodedeps",    "Node Dependencies"),
            ("chatterboxpkg","chatterbox-tts Paket"),
            ("start",       "ComfyUI starten"),
        ]

        popup = self._open_installer_popup(steps)
        tick  = popup["tick"]

        def _run_install():
            """Background thread: runs the full ComfyUI installer and closes the popup on completion."""
            ok = ProductionOrchestrator._install_comfyui(
                storage_root = storage,
                log_cb       = self._log,
                tick_cb      = tick,
            )
            popup["close"]()
            if ok:
                self.after(0, lambda: messagebox.showinfo(
                    "ComfyUI installiert ✅",
                    f"ComfyUI erfolgreich installiert!\n\nPath: {comfyui_dir}"
                ))
            else:
                self.after(0, lambda: messagebox.showerror(
                    "Installation fehlgeschlagen",
                    "Siehe Log fuer Details.\n\n"
                    "Haeufige Ursachen:\n"
                    "  • Keine Internetverbindung\n"
                    "  • git nicht installiert\n"
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

        Robust against a destroyed tkinter window (z.B. IDLE-Restart waehrend
        ein Render-Thread noch laeuft). Faengt RuntimeError und TclError ab.
        """
        def _do():
            """Applies the log append and color tag on the main tkinter thread."""
            try:
                self._log_area.config(state="normal")
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                # Auto-scroll only if user is already at the bottom
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
    """Entry point: starts in GUI mode or CLI headless mode depending on arguments."""
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
