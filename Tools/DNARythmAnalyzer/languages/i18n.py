"""
Internationalisierungs-Modul für DNARhythmAnalyzer
Unterstützt dynamische Sprachumschaltung mit JSON-Sprachdateien.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
import logging

# Globale Sprach-Manager-Instanz
_language_manager = None


@dataclass
class LanguageConfig:
    """Konfiguration für eine Sprache"""
    code: str
    name: str
    native_name: str
    file: str
    is_rtl: bool = False
    
    def __str__(self):
        return self.native_name


# Verfügbare Sprachen
AVAILABLE_LANGUAGES = {
    "de": LanguageConfig("de", "German", "Deutsch", "de.json", False),
    "en": LanguageConfig("en", "English", "English", "en.json", False),
    "es": LanguageConfig("es", "Spanish", "Español", "es.json", False),
    "fr": LanguageConfig("fr", "French", "Français", "fr.json", False),
    "it": LanguageConfig("it", "Italian", "Italiano", "it.json", False),
    "zh": LanguageConfig("zh", "Chinese", "中文", "zh.json", False),
    "ja": LanguageConfig("ja", "Japanese", "日本語", "ja.json", False),
    "ru": LanguageConfig("ru", "Russian", "Русский", "ru.json", False),
    "pt": LanguageConfig("pt", "Portuguese", "Português", "pt.json", False),
    "ar": LanguageConfig("ar", "Arabic", "العربية", "ar.json", True),
}


class I18n:
    """
    Internationalisierungs-Manager.
    Lädt Sprachdateien und stellt Übersetzungsfunktionen bereit.
    """
    
    def __init__(self, languages_dir: Path, default_language: str = "de"):
        """
        Initialisiert den I18n-Manager.
        
        Args:
            languages_dir: Verzeichnis mit den JSON-Sprachdateien
            default_language: Standard-Sprachcode (z.B. "de", "en")
        """
        self.languages_dir = Path(languages_dir)
        self.default_language = default_language
        self.current_language = default_language
        self._translations: Dict[str, Dict] = {}
        self._callbacks: list = []
        
        # Stelle sicher, dass das Verzeichnis existiert
        self.languages_dir.mkdir(parents=True, exist_ok=True)
        
        # Lade Standard-Sprache
        self.load_language(default_language)
    
    def load_language(self, language_code: str) -> bool:
        """
        Lädt eine Sprachdatei.
        
        Args:
            language_code: Sprachcode (z.B. "de", "en")
            
        Returns:
            True bei Erfolg, False bei Fehler
        """
        if language_code not in AVAILABLE_LANGUAGES:
            logging.warning(f"Sprache {language_code} nicht verfügbar")
            return False
        
        lang_config = AVAILABLE_LANGUAGES[language_code]
        file_path = self.languages_dir / lang_config.file
        
        if not file_path.exists():
            logging.warning(f"Sprachdatei nicht gefunden: {file_path}")
            return False
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                translations = json.load(f)
            
            self._translations[language_code] = translations
            self.current_language = language_code
            
            # Benachrichtige Listener
            self._notify_callbacks()
            
            logging.info(f"Sprache geladen: {language_code} ({lang_config.native_name})")
            return True
            
        except Exception as e:
            logging.error(f"Fehler beim Laden der Sprachdatei {file_path}: {e}")
            return False
    
    def _notify_callbacks(self):
        """Benachrichtigt alle registrierten Callbacks über Sprachwechsel."""
        for callback in self._callbacks:
            try:
                callback(self.current_language)
            except Exception as e:
                logging.error(f"Fehler in Sprach-Callback: {e}")
    
    def register_callback(self, callback: Callable[[str], None]):
        """
        Registriert einen Callback für Sprachwechsel.
        
        Args:
            callback: Funktion, die bei Sprachwechsel aufgerufen wird
        """
        self._callbacks.append(callback)
    
    def unregister_callback(self, callback: Callable[[str], None]):
        """Entfernt einen registrierten Callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def get(self, key: str, default: str = None, **kwargs) -> str:
        """
        Holt eine Übersetzung für den aktuellen Sprachschlüssel.
        
        Args:
            key: Punkt-getrennter Schlüssel (z.B. "app.title")
            default: Standardwert falls Schlüssel nicht gefunden
            **kwargs: Formatierungs-Parameter
            
        Returns:
            Übersetzter String
        """
        # Hole aktuelle Übersetzungen
        trans = self._translations.get(self.current_language, {})
        
        # Navigiere durch verschachtelte Dictionaries
        parts = key.split('.')
        value = trans
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        
        # Fallback auf Standard-Sprache
        if value is None and self.current_language != self.default_language:
            default_trans = self._translations.get(self.default_language, {})
            value = default_trans
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
        
        # Letzter Fallback: Schlüssel oder default
        if value is None:
            result = default if default is not None else key
        else:
            result = value
        
        # Formatiere mit kwargs
        if kwargs and isinstance(result, str):
            try:
                result = result.format(**kwargs)
            except (KeyError, ValueError, TypeError):
                # TypeError: wrong type for format spec (e.g. str where float expected)
                # Try again with all numeric-looking values cast to float
                try:
                    safe_kwargs = {}
                    for k, v in kwargs.items():
                        if isinstance(v, str):
                            try:
                                safe_kwargs[k] = float(v)
                            except (ValueError, TypeError):
                                safe_kwargs[k] = v
                        else:
                            safe_kwargs[k] = v
                    result = result.format(**safe_kwargs)
                except Exception:
                    pass
        
        return result
    
    def get_all_languages(self) -> Dict[str, LanguageConfig]:
        """Gibt alle verfügbaren Sprachen zurück."""
        return AVAILABLE_LANGUAGES.copy()
    
    def get_current_language_info(self) -> Optional[LanguageConfig]:
        """Gibt Informationen zur aktuellen Sprache zurück."""
        return AVAILABLE_LANGUAGES.get(self.current_language)
    
    def set_language(self, language_code: str) -> bool:
        """Setzt die aktuelle Sprache."""
        if language_code in self._translations:
            self.current_language = language_code
            self._notify_callbacks()
            return True
        elif self.load_language(language_code):
            return True
        return False
    
    def create_template_file(self, language_code: str) -> bool:
        """
        Erstellt eine neue Sprachdatei aus dem Template.
        
        Args:
            language_code: Sprachcode für die neue Datei
            
        Returns:
            True bei Erfolg
        """
        if language_code not in AVAILABLE_LANGUAGES:
            return False
        
        lang_config = AVAILABLE_LANGUAGES[language_code]
        file_path = self.languages_dir / lang_config.file
        
        # Kopiere von Deutsch oder Englisch als Basis
        source_lang = "de" if self.default_language == "de" else "en"
        source_file = self.languages_dir / AVAILABLE_LANGUAGES[source_lang].file
        
        if not source_file.exists():
            logging.error(f"Quell-Sprachdatei nicht gefunden: {source_file}")
            return False
        
        try:
            import shutil
            shutil.copy(source_file, file_path)
            logging.info(f"Template-Sprachdatei erstellt: {file_path}")
            return True
        except Exception as e:
            logging.error(f"Fehler beim Erstellen der Sprachdatei: {e}")
            return False


def get_i18n() -> I18n:
    """Gibt die globale I18n-Instanz zurück."""
    global _language_manager
    if _language_manager is None:
        # Bestimme das Sprachen-Verzeichnis relativ zum Skript
        script_dir = Path(__file__).parent
        languages_dir = script_dir / "languages"
        _language_manager = I18n(languages_dir)
    return _language_manager


def t(key: str, default: str = None, **kwargs) -> str:
    """
    Kurzfunktion für Übersetzungen.
    
    Args:
        key: Übersetzungsschlüssel
        default: Standardwert
        **kwargs: Formatierungsparameter
        
    Returns:
        Übersetzter String
    """
    return get_i18n().get(key, default, **kwargs)


# ============================================================
# TKINTER INTEGRATION - DYNAMISCHE SPRACHUMSCHALTUNG
# ============================================================

class Translatable:
    """
    Mixin-Klasse für Widgets mit dynamischer Sprachumschaltung.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._translation_keys = {}
        self._i18n = get_i18n()
        self._i18n.register_callback(self._on_language_changed)
    
    def bind_text(self, widget, text_key: str, **format_kwargs):
        """
        Bindet einen Text an ein Widget für automatische Übersetzung.
        
        Args:
            widget: Das Widget (z.B. ttk.Label, ttk.Button)
            text_key: Übersetzungsschlüssel
            **format_kwargs: Formatierungsparameter
        """
        self._translation_keys[id(widget)] = (widget, text_key, format_kwargs)
        self._update_widget_text(widget, text_key, format_kwargs)
    
    def _on_language_changed(self, language_code: str):
        """Wird bei Sprachwechsel aufgerufen."""
        for widget_id, (widget, text_key, format_kwargs) in self._translation_keys.items():
            try:
                self._update_widget_text(widget, text_key, format_kwargs)
            except Exception:
                # Widget existiert nicht mehr
                pass
    
    def _update_widget_text(self, widget, text_key: str, format_kwargs: dict):
        """Aktualisiert den Text eines Widgets."""
        translated = t(text_key, **format_kwargs)
        
        # Verschiedene Widget-Typen unterschiedlich behandeln
        widget_type = widget.__class__.__name__
        
        try:
            if hasattr(widget, 'config'):
                if 'text' in widget.keys():
                    widget.config(text=translated)
                elif 'textvariable' in widget.keys():
                    if hasattr(widget, 'set'):
                        widget.set(translated)
            
            if hasattr(widget, 'set') and not hasattr(widget, 'config'):
                widget.set(translated)
                
        except Exception:
            pass


class LanguageSelector:
    """
    Sprachauswahl-Widget für die GUI.
    """
    
    def __init__(self, parent, i18n: I18n, on_change: Callable = None):
        """
        Initialisiert den Sprachauswahl-Dialog/Combobox.
        
        Args:
            parent: Tkinter-Elternwidget
            i18n: I18n-Instanz
            on_change: Callback bei Sprachwechsel
        """
        self.parent = parent
        self.i18n = i18n
        self.on_change = on_change
        self.combobox = None
    
    def create_combobox(self, master, **kwargs):
        """
        Erstellt eine Combobox für Sprachauswahl.
        
        Args:
            master: Elternwidget
            **kwargs: Weitere Optionen für ttk.Combobox
            
        Returns:
            ttk.Combobox Instanz
        """
        from tkinter import ttk
        
        languages = self.i18n.get_all_languages()
        values = [f"{lang.native_name} ({lang.name})" for lang in languages.values()]
        language_map = {f"{lang.native_name} ({lang.name})": code 
                        for code, lang in languages.items()}
        
        self.combobox = ttk.Combobox(master, values=values, **kwargs)
        
        # Setze aktuelle Sprache
        current = self.i18n.get_current_language_info()
        if current:
            display = f"{current.native_name} ({current.name})"
            if display in language_map:
                self.combobox.set(display)
        
        def on_select(event):
            selected = self.combobox.get()
            if selected in language_map:
                code = language_map[selected]
                if self.i18n.set_language(code):
                    if self.on_change:
                        self.on_change(code)
        
        self.combobox.bind('<<ComboboxSelected>>', on_select)
        
        return self.combobox
    
    def create_dialog(self):
        """Erstellt einen Dialog zur Sprachauswahl (für Einstellungen)."""
        import tkinter as tk
        from tkinter import ttk
        
        dialog = tk.Toplevel(self.parent)
        dialog.title(t("settings.window_title"))
        dialog.geometry("400x300")
        dialog.transient(self.parent)
        dialog.grab_set()
        
        # Sprachauswahl
        ttk.Label(dialog, text=t("settings.language_select")).pack(pady=10)
        
        combo = self.create_combobox(dialog, width=30)
        combo.pack(pady=5)
        
        # Info-Text
        info_label = ttk.Label(dialog, text="", foreground="gray")
        info_label.pack(pady=10)
        
        def update_info(*args):
            info_label.config(text=t("settings.restart_required"))
        
        combo.bind('<<ComboboxSelected>>', update_info)
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=20)
        
        def save():
            dialog.destroy()
        
        def cancel():
            dialog.destroy()
        
        ttk.Button(button_frame, text=t("settings.button_save"), command=save).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text=t("settings.button_cancel"), command=cancel).pack(side=tk.LEFT, padx=5)
        
        dialog.wait_window()


# ============================================================
# INTEGRATION IN DEN HAUPTPROGRAMM-CODE
# ============================================================

def integrate_i18n_into_app(app_class):
    """
    Dekorator/Helper zur Integration von I18n in die App-Klasse.
    
    Beispiel:
        @integrate_i18n_into_app
        class DNARhythmAnalyzer:
            ...
    """
    original_init = app_class.__init__
    
    def new_init(self, root):
        self.i18n = get_i18n()
        self.i18n.register_callback(self._update_ui_language)
        original_init(self, root)
    
    app_class.__init__ = new_init
    
    # Füge Sprachumschaltungs-Methode hinzu
    def update_ui_language(self, language_code):
        """Aktualisiert alle UI-Texte bei Sprachwechsel."""
        # Aktualisiere Fenstertitel
        self.root.title(t("app.title"))
        
        # Aktualisiere Labels und Buttons (Beispiele)
        if hasattr(self, 'status_label'):
            self.status_label.config(text=t("app.status_ready"))
        
        if hasattr(self, 'species_info_label'):
            species = self.species_var.get() if hasattr(self, 'species_var') else ""
            if species in SPECIES_DB:
                info = SPECIES_DB[species]
                self.species_info_label.config(
                    text=t("species.info_label", 
                          accession=info["accession"], 
                          group=t(f"species.group_{info['group']}", info['group']))
                )
        
        # Aktualisiere Buttons
        button_updates = [
            ('single_btn', "buttons.single_analysis"),
            ('batch_btn', "buttons.batch_analysis"),
            ('stop_btn', "buttons.stop_analysis"),
            ('consolidate_btn', "buttons.generate_report"),
            ('settings_btn', "buttons.settings"),
            ('clear_btn', "buttons.clear_log"),
            ('reset_btn', "buttons.reset_analysis"),
            ('btn_3d_real', "buttons.reconstruct_3d_realistic"),
            ('btn_delta', "buttons.delta_optimization"),
        ]
        
        for attr, key in button_updates:
            if hasattr(self, attr):
                btn = getattr(self, attr)
                try:
                    btn.config(text=t(key))
                except Exception:
                    pass
        
        # Aktualisiere Methoden-Checkboxen
        method_labels = [
            ('two_thz', "methods.two_thz"),
            ('fibonacci', "methods.fibonacci"),
            ('golden_ratio', "methods.golden_ratio"),
            ('power_law', "methods.power_law"),
            ('cgr', "methods.cgr"),
            ('piano_roll', "methods.piano_roll"),
            ('autocorr', "methods.autocorr"),
            ('gc_content', "methods.gc_content"),
            ('dinucleotide', "methods.dinucleotide"),
        ]
        
        if hasattr(self, 'method_vars'):
            for idx, (method_id, key) in enumerate(method_labels):
                if idx < len(list(self.method_vars.keys())):
                    label = list(self.method_vars.keys())[idx]
                    # Leider können Checkbox-Labels nicht einfach geändert werden
                    # Daher müssten sie neu erstellt werden - aufwändig
                    # Alternative: Verwende Translatable-Mixin
    
    app_class._update_ui_language = update_ui_language
    
    # Füge Sprachauswahl zur Einstellungen hinzu
    original_show_settings = getattr(app_class, 'show_settings', None)
    
    def show_settings_with_language(self):
        """Erweiterte Einstellungen mit Sprachauswahl."""
        from tkinter import ttk, Toplevel
        
        dialog = Toplevel(self.root)
        dialog.title(t("settings.window_title"))
        dialog.geometry("500x500")
        dialog.transient(self.root)
        dialog.grab_set()
        
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Tab 1: Allgemein (Sprache)
        general_frame = ttk.Frame(notebook)
        notebook.add(general_frame, text=t("settings.language"))
        
        ttk.Label(general_frame, text=t("settings.language_select")).grid(row=0, column=0, sticky='w', padx=5, pady=5)
        
        # Sprachauswahl Combobox
        languages = self.i18n.get_all_languages()
        lang_values = [f"{lang.native_name} ({lang.name})" for lang in languages.values()]
        lang_map = {f"{lang.native_name} ({lang.name})": code 
                    for code, lang in languages.items()}
        
        lang_var = tk.StringVar()
        current = self.i18n.get_current_language_info()
        if current:
            lang_var.set(f"{current.native_name} ({current.name})")
        
        lang_combo = ttk.Combobox(general_frame, textvariable=lang_var, 
                                   values=lang_values, width=30)
        lang_combo.grid(row=0, column=1, padx=5, pady=5)
        
        # Tab 2: Analyse-Parameter (wie bisher)
        params_frame = ttk.Frame(notebook)
        notebook.add(params_frame, text=t("settings.param_analysis"))
        
        # Hier die bestehenden Parameter-Felder einfügen...
        # (Beispielhaft)
        row = 0
        ttk.Label(params_frame, text=t("settings.param_max_seq_length")).grid(row=row, column=0, sticky='w', padx=5, pady=2)
        max_seq_var = tk.StringVar(value=str(CONFIG.max_seq_length))
        ttk.Entry(params_frame, textvariable=max_seq_var, width=15).grid(row=row, column=1, padx=5)
        row += 1
        
        # ... weitere Parameter ...
        
        # Buttons
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        def save_settings():
            # Sprache speichern
            selected = lang_var.get()
            if selected in lang_map:
                code = lang_map[selected]
                self.i18n.set_language(code)
                self._update_ui_language(code)
            
            # Parameter speichern (wie bisher)
            try:
                CONFIG.max_seq_length = int(max_seq_var.get())
                # ... weitere Parameter ...
                self.log(t("settings.settings_updated"))
            except ValueError as e:
                messagebox.showerror(t("dialogs.error"), t("settings.invalid_value", error=str(e)))
            
            dialog.destroy()
        
        ttk.Button(button_frame, text=t("settings.button_save"), command=save_settings).pack(side='left', padx=5)
        ttk.Button(button_frame, text=t("settings.button_cancel"), command=dialog.destroy).pack(side='left', padx=5)
        
        dialog.wait_window()
    
    app_class.show_settings = show_settings_with_language
    
    return app_class


# ============================================================
# HILFSFUNKTION FÜR DIE LOG-AUSGABE
# ============================================================

class TranslatableLogger:
    """
    Logger mit Übersetzungsunterstützung für Log-Ausgaben.
    """
    
    def __init__(self, original_log_callback):
        self.original_callback = original_log_callback
        self.i18n = get_i18n()
    
    def __call__(self, message_key: str, **kwargs):
        """Loggt eine übersetzte Nachricht."""
        translated = t(message_key, **kwargs)
        if self.original_callback:
            self.original_callback(translated)
        return translated
    
    def log_raw(self, message: str):
        """Loggt eine rohe Nachricht (ohne Übersetzung)."""
        if self.original_callback:
            self.original_callback(message)


# ============================================================
# BEISPIEL FÜR DIE EN.JSON (BASIS FÜR WEITERE SPRACHEN)
# ============================================================

"""
Die en.json sollte analog zur de.json aufgebaut sein, aber mit englischen Texten.
Hier ein kurzes Beispiel für den Aufbau:

{
  "_metadata": {
    "language": "English",
    "code": "en",
    "version": "1.0.0"
  },
  "app": {
    "title": "DNA Rhythm Analyzer - Multi-Method Tool",
    "status_ready": "Ready",
    ...
  },
  ...
}
"""


if __name__ == "__main__":
    # Test der Internationalisierung
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        lang_dir = Path(tmpdir) / "languages"
        lang_dir.mkdir()
        
        # Kopiere die de.json ins temporäre Verzeichnis
        import shutil
        script_dir = Path(__file__).parent
        source_de = script_dir / "languages" / "de.json"
        
        if source_de.exists():
            shutil.copy(source_de, lang_dir / "de.json")
        
        # Teste I18n
        i18n = I18n(lang_dir, "de")
        
        print("Test der Übersetzungen:")
        print(f"  app.title = {i18n.get('app.title')}")
        print(f"  methods.two_thz = {i18n.get('methods.two_thz')}")
        print(f"  buttons.single_analysis = {i18n.get('buttons.single_analysis')}")
        print(f"  Mit Parametern: {i18n.get('analysis.completed', species='E. coli')}")
