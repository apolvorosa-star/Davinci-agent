"""Interfaz gráfica profesional de DaVinci Agent usando CustomTkinter.

Características:
  * Diseño moderno (modo oscuro por defecto) con pestañas:
    - 🎬 Inicio  : Selección de archivos, drag & drop (windnd), procesar/watch
    - 📲 Redes   : Togglear plataformas a generar + tonos
    - 🤖 IA      : Configuración multi-proveedor (Ollama/OpenAI/Anthropic…)
    - 📜 Log     : Consola en vivo y progreso
    - 📊 Resultados: Vista rápida de jobs completados + abrir carpeta
  * Multi-threading: el procesamiento NUNCA congela la UI.
  * Integración con Worker y SocialMediaManager.
"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import yaml

try:
    import customtkinter as ctk
except ImportError as exc:  # pragma: no cover - handled at runtime
    raise SystemExit(
        "⚠️  CustomTkinter no está instalado.\n"
        "Ejecuta: pip install customtkinter>=5.2.2 windnd>=1.0.1\n"
        f"Error original: {exc}"
    ) from exc

try:
    import windnd  # type: ignore  # noqa: F401

    HAS_WINDND = True
except ImportError:
    HAS_WINDND = False

from core.media_io import (
    FFMPEG_INSTALL_HINT,
    SUPPORTED_MEDIA_EXTENSIONS,
    ffmpeg_available,
    is_media_extension,
)
from ui_utils import format_size, open_folder

# ---------------------------------------------------------------------------
# Helpers generales
# ---------------------------------------------------------------------------
PLATFORMS_ORDERED = [
    ("youtube", "YouTube", "🎥"),
    ("instagram", "Instagram", "📸"),
    ("tiktok", "TikTok", "🎵"),
    ("twitter_x", "X / Twitter", "🐦"),
    ("facebook", "Facebook", "👥"),
    ("linkedin", "LinkedIn", "💼"),
]


# ===========================================================================
# Clase principal
# ===========================================================================
class DavinciApp(ctk.CTk):
    """Ventana principal CustomTkinter de DaVinci Agent."""

    APP_TITLE = "DaVinci Agent — Suite Profesional Redes Sociales"
    APP_GEOMETRY = "1180x760"
    APP_MINSIZE = (980, 640)

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__()

        # ---------------------------------------------------------------
        # 1) Configuración global de CustomTkinter
        # ---------------------------------------------------------------
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(self.APP_TITLE)
        self.geometry(self.APP_GEOMETRY)
        self.minsize(*self.APP_MINSIZE)

        # ---------------------------------------------------------------
        # 2) Estado interno
        # ---------------------------------------------------------------
        from main import get_project_root, load_settings

        self.settings: dict = settings or load_settings()
        self.project_root = get_project_root()
        self.paths_cfg = self.settings.get("paths", {}) or {}
        self.social_cfg: dict = self.settings.get("social_media", {}) or {}
        self.platforms_defaults: dict = self.social_cfg.get("defaults", {}) or {}
        self.platforms_cfg: dict = self.social_cfg.get("platforms", {}) or {}

        self.selected_files: list[Path] = []
        self.message_queue: queue.Queue = queue.Queue()
        self.dnd_queue: queue.Queue = queue.Queue()  # files drag & drop (WndProc -> poll)
        self.worker_thread: threading.Thread | None = None
        self.watcher_thread: threading.Thread | None = None
        self.watcher_active: bool = False
        self.running: bool = False

        # Estado toggle de plataformas (tomado inicial de settings.yaml)
        self.platform_vars: dict[str, tk.BooleanVar] = {}
        for key, _name, _emoji in PLATFORMS_ORDERED:
            plat_block = self.platforms_cfg.get(key) or {}
            enabled_default = bool(plat_block.get("enabled", True))
            self.platform_vars[key] = tk.BooleanVar(value=enabled_default)

        # ---------------------------------------------------------------
        # 3) Layout raíz: header + Tabview + footer
        # ---------------------------------------------------------------
        self._build_header()
        self.tabview = ctk.CTkTabview(self, command=self._on_tab_change)
        self.tabview.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        for tab_name in (
            "🎬 Inicio",
            "📲 Redes Sociales",
            "🤖 IA",
            "⚙️ Config",
            "📜 Log",
            "📊 Resultados",
        ):
            self.tabview.add(tab_name)

        self._build_tab_home()
        self._build_tab_social()
        self._build_tab_ai()
        self._build_tab_config()
        self._build_tab_log()
        self._build_tab_results()
        self._build_footer()

        # Drag & drop vía windnd (solo Windows). Se retrasa para que la ventana
        # esté visible y el HWND sea completamente funcional.
        if HAS_WINDND:
            self.after(700, self._enable_drag_and_drop)

        # Loop de polling de la cola de mensajes (worker → GUI)
        self.after(140, self._poll_queue)

        # Carga inicial de resultados
        self._refresh_results()
        self._append_log("INFO", "🪄 DaVinci Agent inicializado.")
        self._append_log("INFO", "🎯 Arrastra archivos a la ventana o elígelos manualmente.")

    # =====================================================================
    # 🔩 UI build: header
    # =====================================================================
    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, height=66, corner_radius=10)
        header.pack(fill="x", padx=14, pady=(14, 8))
        header.pack_propagate(False)

        title_cfg = self.settings.get("app", {}) or {}
        app_name = title_cfg.get("name", "DaVinci Agent")
        app_ver = title_cfg.get("version", "1.0.0")

        title = ctk.CTkLabel(
            header,
            text=f"✨ {app_name}   v{app_ver}",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.pack(side="left", padx=20)

        # Banner FFmpeg status
        ffmpeg_ok, ffmpeg_ver, _, _ = ffmpeg_available()
        if ffmpeg_ok:
            ffmpeg_txt = f"🎞️ FFmpeg: ✅ ({(ffmpeg_ver.split(',')[0] if isinstance(ffmpeg_ver, str) else 'OK')[:55]})"
            ffmpeg_color = "#22c55e"
        else:
            ffmpeg_txt = (
                "🎞️ FFmpeg: ⚠️ NO instalado (instálalo para códecs raros / todos los formatos)."
            )
            ffmpeg_color = "#fbbf24"
        ffmpeg_lbl = ctk.CTkLabel(
            header,
            text=ffmpeg_txt,
            text_color=ffmpeg_color,
            font=ctk.CTkFont(size=11, weight="bold"),
        )
        ffmpeg_lbl.pack(side="left", padx=(16, 0))
        if not ffmpeg_ok:

            def _show_ffmpeg_hint(_e=None):
                from tkinter import messagebox as mb

                mb.showinfo(
                    "Instalar FFmpeg — DaVinci Agent",
                    FFMPEG_INSTALL_HINT,
                )

            ffmpeg_lbl.bind("<Button-1>", _show_ffmpeg_hint)
            ffmpeg_lbl.configure(
                cursor="hand2", font=ctk.CTkFont(size=11, weight="bold", underline=True)
            )

        self.btn_open_output = ctk.CTkButton(
            header,
            text="📂 Abrir carpeta salida",
            width=160,
            command=self._open_output_folder,
        )
        self.btn_open_output.pack(side="right", padx=10)

        self.btn_open_input = ctk.CTkButton(
            header,
            text="📁 Entrada",
            width=110,
            fg_color="transparent",
            border_width=1,
            command=self._open_input_folder,
        )
        self.btn_open_input.pack(side="right", padx=4)

    # =====================================================================
    # 🔩 Tab Home
    # =====================================================================
    def _build_tab_home(self) -> None:
        tab = self.tabview.tab("🎬 Inicio")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        # Selección archivos
        frame_sel = ctk.CTkFrame(tab)
        frame_sel.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        frame_sel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame_sel,
            text="📥 Archivos multimedia a procesar:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=4, padx=10, pady=(10, 4), sticky="w")

        self.entry_files = ctk.CTkEntry(
            frame_sel, placeholder_text="Arrastra archivos aquí o usa el botón Seleccionar…"
        )
        self.entry_files.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=6)

        ctk.CTkButton(frame_sel, text="Seleccionar…", width=130, command=self._choose_files).grid(
            row=1, column=3, padx=(0, 10), pady=6
        )

        self.lbl_file_count = ctk.CTkLabel(
            frame_sel, text="0 archivos seleccionados", text_color="gray70"
        )
        self.lbl_file_count.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))

        # Opciones procesamiento + acciones
        frame_opt = ctk.CTkFrame(tab)
        frame_opt.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for c in range(6):
            frame_opt.grid_columnconfigure(c, weight=1)

        ctk.CTkLabel(
            frame_opt, text="⚙️ Opciones rápidas:", font=ctk.CTkFont(size=12, weight="bold")
        ).grid(row=0, column=0, columnspan=6, padx=10, pady=(10, 6), sticky="w")

        paths = self.settings.get("paths", {}) or {}
        self.lbl_input_folder = ctk.CTkLabel(
            frame_opt, text=f"📥 Entrada: {paths.get('input', './input')}"
        )
        self.lbl_input_folder.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=4)
        self.lbl_output_folder = ctk.CTkLabel(
            frame_opt, text=f"📤 Salida : {paths.get('output', './output')}"
        )
        self.lbl_output_folder.grid(row=1, column=3, columnspan=3, sticky="w", padx=10, pady=4)

        self.btn_process = ctk.CTkButton(
            frame_opt,
            text="🚀 PROCESAR",
            height=44,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._on_click_process,
        )
        self.btn_process.grid(row=2, column=0, columnspan=2, padx=10, pady=(6, 12), sticky="ew")

        self.btn_watch = ctk.CTkButton(
            frame_opt,
            text="👀 INICIAR WATCHER",
            height=44,
            fg_color="#475569",
            hover_color="#334155",
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._toggle_watcher,
        )
        self.btn_watch.grid(row=2, column=2, columnspan=2, padx=10, pady=(6, 12), sticky="ew")

        self.btn_clear = ctk.CTkButton(
            frame_opt,
            text="🧹 Limpiar selección",
            height=44,
            fg_color="transparent",
            border_width=1,
            command=self._clear_selection,
        )
        self.btn_clear.grid(row=2, column=4, columnspan=2, padx=10, pady=(6, 12), sticky="ew")

        # Info panel
        frame_info = ctk.CTkFrame(tab)
        frame_info.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        for c in range(4):
            frame_info.grid_columnconfigure(c, weight=1)

        try:
            from core.ai_engine import AIEngine

            ai = AIEngine()
            ai_text = (
                f"Proveedor IA por defecto:  🔵 {ai.ai_cfg.get('default_provider', '-')}   |   "
                f"Modelo Whisper:  🟢 {(self.settings.get('models', {}).get('whisper', {}).get('name', 'base'))}"
            )
        except Exception as exc:
            ai_text = f"⚠️  AIEngine no disponible: {exc}"

        ctk.CTkLabel(frame_info, text=ai_text, font=ctk.CTkFont(size=12), text_color="gray85").pack(
            fill="x", padx=14, pady=12
        )

        # Lista de archivos seleccionados
        frame_files = ctk.CTkScrollableFrame(
            tab, label_text="🎞️  Cola de procesamiento (haz doble clic para quitar)"
        )
        frame_files.grid(row=3, column=0, sticky="nsew", pady=(0, 0))
        frame_files.grid_columnconfigure(0, weight=1)

        self.frame_file_list = frame_files
        self._render_file_list()

    # =====================================================================
    # 🔩 Tab Redes sociales
    # =====================================================================
    def _build_tab_social(self) -> None:
        tab = self.tabview.tab("📲 Redes Sociales")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            tab,
            text="🟢 Selecciona las plataformas a generar:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 8), sticky="w")

        self.frames_platforms: dict[str, ctk.CTkFrame] = {}
        for idx, (key, name, emoji) in enumerate(PLATFORMS_ORDERED):
            row, col = divmod(idx, 2)
            plat_frame = ctk.CTkFrame(tab)
            plat_frame.grid(
                row=row + 1, column=col, sticky="nsew", padx=8, pady=6, ipadx=6, ipady=6
            )
            plat_frame.grid_columnconfigure(0, weight=1)
            self.frames_platforms[key] = plat_frame

            chk = ctk.CTkCheckBox(
                plat_frame,
                text=f"{emoji}  {name}",
                variable=self.platform_vars[key],
                font=ctk.CTkFont(size=14, weight="bold"),
            )
            chk.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))

            plat_block = self.platforms_cfg.get(key) or {}
            tone = plat_block.get("tone", self.platforms_defaults.get("tone", "equilibrado"))
            ht = plat_block.get("max_hashtags", self.platforms_defaults.get("max_hashtags", 15))
            desc_lines = [
                f"Tono: {tone}",
                f"Máx. hashtags: {ht}",
            ]
            if key == "youtube":
                desc_lines.append("Título ≤100c + descripción SEO")
            elif key == "instagram":
                desc_lines.append("Feed + Stories (5-10) + Reel")
            elif key == "tiktok":
                desc_lines.append("Hook 3s + overlays + scene_cuts")
            elif key == "twitter_x":
                desc_lines.append("Hilo de tweets (≤280c cada uno)")
            elif key == "facebook":
                desc_lines.append("Post largo + summary_points + audiencia")
            elif key == "linkedin":
                desc_lines.append("Storytelling + lecciones accionables")

            info_lbl = ctk.CTkLabel(
                plat_frame,
                text="\n".join(f"• {ln}" for ln in desc_lines),
                font=ctk.CTkFont(size=11),
                text_color="gray70",
                justify="left",
            )
            info_lbl.grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))

    # =====================================================================
    # 🔩 Tab IA
    # =====================================================================
    def _build_tab_ai(self) -> None:
        tab = self.tabview.tab("🤖 IA")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text="🤖 Proveedores de Inteligencia Artificial disponibles:",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(10, 8), sticky="w")

        ai_cfg = self.settings.get("ai") or {}
        self.ai_status_label = ctk.CTkLabel(
            tab,
            text="Consultando disponibilidad de proveedores…",
            font=ctk.CTkFont(size=12),
            text_color="gray70",
            justify="left",
        )
        self.ai_status_label.grid(row=1, column=0, padx=10, pady=(0, 8), sticky="ew")

        self.ai_textbox = ctk.CTkTextbox(tab, wrap="word", font=ctk.CTkFont("Consolas", 12))
        self.ai_textbox.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 12))

        self.ai_textbox.insert("1.0", json.dumps(ai_cfg, indent=2, ensure_ascii=False))
        self.ai_textbox.configure(state="disabled")

        self.after(400, self._refresh_ai_status)

    def _refresh_ai_status(self) -> None:
        try:
            from core.ai_engine import AIEngine

            ai = AIEngine()
            avail = ai.available_providers()
            default = ai.ai_cfg.get("default_provider", "-")
            errors = (
                ai.get_provider_errors()
                if hasattr(ai, "get_provider_errors")
                else dict(ai._provider_errors)
            )
            lines = [
                f"✅ Proveedor IA por defecto:  {default}",
                f"✅ Proveedores disponibles :  {', '.join(avail) if avail else '(ninguno funcional)'}",
                f"ℹ️  Modelo Whisper configurado:  {(self.settings.get('models', {}).get('whisper', {}).get('name', 'base'))}",
            ]
            if errors:
                lines.append("")
                lines.append("⚠️  Proveedores NO disponibles:")
                for name, err in errors.items():
                    lines.append(f"  · {name:<22}  →  {err}")
            self.ai_status_label.configure(text="\n".join(lines), text_color="gray90")
        except Exception as exc:
            self.ai_status_label.configure(text=f"⚠️  Error AIEngine: {exc}", text_color="#f87171")

    # =====================================================================
    # ⚙️ Tab Configuración editable
    # =====================================================================
    def _build_tab_config(self) -> None:
        tab = self.tabview.tab("⚙️ Config")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text="⚙️ Configuración editable (se guarda en config/settings.user.yaml, no se distribuye):",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, padx=10, pady=(10, 8), sticky="w")

        ai_cfg = self.settings.get("ai", {}) or {}
        providers = ai_cfg.get("providers", {})

        default_row = ctk.CTkFrame(tab)
        default_row.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")
        ctk.CTkLabel(default_row, text="Proveedor por defecto:").pack(side="left", padx=(0, 10))
        self.cfg_default_provider = ctk.CTkOptionMenu(
            default_row,
            values=list(providers.keys()) if providers else ["openai_compatible"],
            command=lambda _: None,
        )
        self.cfg_default_provider.set(ai_cfg.get("default_provider", "openai_compatible"))
        self.cfg_default_provider.pack(side="left", fill="x", expand=True)

        self.provider_tabview = ctk.CTkTabview(tab)
        self.provider_tabview.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 6))

        self.cfg_widgets: dict[str, dict[str, Any]] = {}
        for provider_name, prov_cfg in providers.items():
            self.provider_tabview.add(provider_name)
            prov_tab = self.provider_tabview.tab(provider_name)
            prov_tab.grid_columnconfigure(1, weight=1)

            widgets: dict[str, Any] = {}
            row = 0

            ctk.CTkLabel(prov_tab, text="Habilitado:").grid(
                row=row, column=0, padx=10, pady=4, sticky="w"
            )
            widgets["enabled"] = ctk.CTkCheckBox(prov_tab, text="")
            if prov_cfg.get("enabled"):
                widgets["enabled"].select()
            widgets["enabled"].grid(row=row, column=1, padx=10, pady=4, sticky="w")
            row += 1

            ctk.CTkLabel(prov_tab, text="Modelo:").grid(
                row=row, column=0, padx=10, pady=4, sticky="w"
            )
            widgets["model"] = ctk.CTkEntry(prov_tab)
            widgets["model"].insert(0, str(prov_cfg.get("model", "")))
            widgets["model"].grid(row=row, column=1, padx=10, pady=4, sticky="ew")
            row += 1

            ctk.CTkLabel(prov_tab, text="API Key:").grid(
                row=row, column=0, padx=10, pady=4, sticky="w"
            )
            widgets["api_key"] = ctk.CTkEntry(prov_tab, show="*")
            widgets["api_key"].insert(0, str(prov_cfg.get("api_key", "")))
            widgets["api_key"].grid(row=row, column=1, padx=10, pady=4, sticky="ew")
            row += 1

            url_label = "URL:" if "url" in prov_cfg else "Base URL:"
            ctk.CTkLabel(prov_tab, text=url_label).grid(
                row=row, column=0, padx=10, pady=4, sticky="w"
            )
            widgets["base_url"] = ctk.CTkEntry(prov_tab)
            widgets["base_url"].insert(0, str(prov_cfg.get("base_url") or prov_cfg.get("url", "")))
            widgets["base_url"].grid(row=row, column=1, padx=10, pady=4, sticky="ew")
            row += 1

            ctk.CTkLabel(prov_tab, text="Guía / system prompt:").grid(
                row=row, column=0, padx=10, pady=4, sticky="nw"
            )
            widgets["system_prompt"] = ctk.CTkTextbox(prov_tab, wrap="word", height=80)
            widgets["system_prompt"].insert("1.0", str(prov_cfg.get("system_prompt", "")).strip())
            widgets["system_prompt"].grid(row=row, column=1, sticky="nsew", padx=10, pady=4)
            prov_tab.grid_rowconfigure(row, weight=1)
            row += 1

            self.cfg_widgets[provider_name] = widgets

        whisper_tab = self.provider_tabview.add("Whisper")
        whisper_tab.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(whisper_tab, text="Modelo Whisper:").grid(
            row=0, column=0, padx=10, pady=4, sticky="w"
        )
        self.cfg_whisper = ctk.CTkEntry(whisper_tab)
        self.cfg_whisper.insert(
            0, str((self.settings.get("models", {}).get("whisper") or {}).get("name", "base"))
        )
        self.cfg_whisper.grid(row=0, column=1, padx=10, pady=4, sticky="ew")

        ctk.CTkButton(
            tab,
            text="💾 Guardar configuración",
            command=self._on_save_config,
        ).grid(row=3, column=0, padx=10, pady=(0, 12), sticky="e")

    def _on_save_config(self) -> None:
        try:
            root = self.project_root
            user_cfg_path = root / "config" / "settings.user.yaml"
            source_path = (
                user_cfg_path if user_cfg_path.exists() else root / "config" / "settings.yaml"
            )
            with open(source_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            cfg.setdefault("ai", {})
            cfg["ai"].setdefault("providers", {})
            cfg.setdefault("models", {})
            cfg["models"].setdefault("whisper", {})

            cfg["ai"]["default_provider"] = self.cfg_default_provider.get()

            for provider_name, widgets in self.cfg_widgets.items():
                prov = cfg["ai"]["providers"].setdefault(provider_name, {})
                prov["enabled"] = bool(widgets["enabled"].get())
                prov["model"] = widgets["model"].get().strip()
                key = widgets["api_key"].get().strip()
                if key:
                    prov["api_key"] = key
                elif "api_key" in prov:
                    del prov["api_key"]
                url = widgets["base_url"].get().strip()
                if "url" in prov:
                    prov["url"] = url
                else:
                    prov["base_url"] = url
                prov["system_prompt"] = widgets["system_prompt"].get("1.0", "end-1c").strip()

            cfg["models"]["whisper"]["name"] = self.cfg_whisper.get().strip()
            with open(user_cfg_path, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, allow_unicode=True, sort_keys=False)
            self.settings = cfg
            self._append_log(
                "OK",
                "Configuración guardada en config/settings.user.yaml. Reinicia DaVinci para recargar proveedores.",
            )
        except Exception as exc:
            messagebox.showerror(
                "Error al guardar", f"No se pudo guardar la configuración:\n\n{exc}"
            )

    # =====================================================================
    # 🔩 Tab Log
    # =====================================================================
    def _build_tab_log(self) -> None:
        tab = self.tabview.tab("📜 Log")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_rowconfigure(3, weight=0)

        ctk.CTkLabel(
            tab, text="📜 Registro de actividad en vivo:", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, padx=10, pady=(10, 6), sticky="w")

        self.log_textbox = ctk.CTkTextbox(tab, wrap="word", font=ctk.CTkFont("Consolas", 12))
        self.log_textbox.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 8))

        self.progress_bar = ctk.CTkProgressBar(tab, width=400, height=18)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 6))
        self.progress_bar.set(0.0)
        self.progress_label = ctk.CTkLabel(tab, text="0%  —  en espera")
        self.progress_label.grid(row=3, column=0, sticky="w", padx=10, pady=(0, 12))

    # =====================================================================
    # 🔩 Tab Resultados
    # =====================================================================
    def _build_tab_results(self) -> None:
        tab = self.tabview.tab("📊 Resultados")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(tab)
        header.grid(row=0, column=0, sticky="ew", pady=(10, 8))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="📊 Últimos trabajos procesados:", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkButton(header, text="🔄 Actualizar", width=120, command=self._refresh_results).grid(
            row=0, column=1, padx=10, pady=10
        )

        self.results_scroll = ctk.CTkScrollableFrame(
            tab, label_text="Jobs (doble clic sobre una tarjeta para abrir su carpeta)"
        )
        self.results_scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 12))
        self.results_scroll.grid_columnconfigure(0, weight=1)
        self.result_cards: list[tuple[ctk.CTkFrame, Path]] = []

    def _refresh_results(self) -> None:
        for frame, _path in self.result_cards:
            try:
                frame.destroy()
            except tk.TclError:
                pass
        self.result_cards = []

        output_folder = self.project_root / self.paths_cfg.get("output", "output")
        jobs_file = output_folder / "jobs.json"
        jobs: list[dict] = []
        if jobs_file.exists():
            try:
                with open(jobs_file, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    jobs = list(reversed(loaded))[:50]
            except Exception:
                pass

        for i, job in enumerate(jobs):
            name = job.get("nombre") or "(sin nombre)"
            ts = job.get("timestamp") or ""
            status = job.get("status") or "?"
            job_folder = job.get("job_folder")
            folder_path = Path(job_folder) if job_folder else None
            color = {
                "completado": "#22c55e",
                "error": "#ef4444",
                "pendiente": "#eab308",
            }.get(str(status).lower(), "#64748b")

            card = ctk.CTkFrame(self.results_scroll, corner_radius=8)
            card.grid(row=i, column=0, sticky="ew", pady=4, padx=2, ipady=6)
            card.grid_columnconfigure(1, weight=1)

            pill = ctk.CTkLabel(
                card,
                text=str(status).upper(),
                fg_color=color,
                text_color="white",
                corner_radius=6,
                font=ctk.CTkFont(size=10, weight="bold"),
                width=90,
            )
            pill.grid(row=0, column=0, rowspan=3, padx=10, pady=6, sticky="n")

            ctk.CTkLabel(
                card, text=f"🎞️  {name}", font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
            ).grid(row=0, column=1, sticky="ew", padx=4, pady=(6, 0))
            ctk.CTkLabel(
                card, text=f"🕒 {ts}", font=ctk.CTkFont(size=11), text_color="gray70", anchor="w"
            ).grid(row=1, column=1, sticky="ew", padx=4)
            line3 = f"📂 {folder_path!s}" if folder_path else ""
            if status == "error":
                line3 += f"   ❌ {job.get('error', '')}"
            ctk.CTkLabel(
                card, text=line3, font=ctk.CTkFont(size=11), text_color="gray80", anchor="w"
            ).grid(row=2, column=1, sticky="ew", padx=4, pady=(0, 6))

            if folder_path and folder_path.exists():

                def _make_open(p: Path):
                    return lambda _e=None: open_folder(p)

                for w in (card, pill):
                    w.bind("<Double-Button-1>", _make_open(folder_path))

            self.result_cards.append((card, folder_path or Path(".")))

    # =====================================================================
    # 🔩 Footer
    # =====================================================================
    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, height=34, corner_radius=0, fg_color="transparent")
        footer.pack(fill="x", padx=14, pady=(0, 8))
        footer.pack_propagate(False)
        self.footer_status = ctk.CTkLabel(
            footer, text="Listo.", font=ctk.CTkFont(size=11), text_color="gray70", anchor="w"
        )
        self.footer_status.pack(side="left")
        social_count = sum(int(v.get()) for v in self.platform_vars.values())
        ctk.CTkLabel(
            footer,
            text=f"Redes activas: {social_count}/6",
            font=ctk.CTkFont(size=11),
            text_color="gray70",
        ).pack(side="right")

    # =====================================================================
    # 🎯 Callbacks varios
    # =====================================================================
    def _on_tab_change(self) -> None:
        current = self.tabview.get()
        if current == "📊 Resultados":
            self._refresh_results()

    def _enable_drag_and_drop(self) -> None:
        """Subclasifica el WndProc nativo para capturar WM_DROPFILES manualmente.

        ``windnd`` no funciona de forma estable con CustomTkinter; usamos ctypes
        directamente sobre ``GetWindowLongPtrW`` / ``SetWindowLongPtrW`` / ``CallWindowProcW``.
        """
        try:
            import ctypes
            from ctypes import wintypes

            WM_DROPFILES = 0x0233
            GWL_WNDPROC = -4
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            kernel32 = ctypes.windll.kernel32
            user32.GetWindowLongPtrW.restype = ctypes.c_void_p
            user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            user32.CallWindowProcW.restype = ctypes.c_longlong
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p,
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            shell32.DragAcceptFiles.restype = None
            shell32.DragAcceptFiles.argtypes = [wintypes.HWND, ctypes.c_int]
            shell32.DragQueryFileW.restype = wintypes.UINT
            shell32.DragQueryFileW.argtypes = [
                wintypes.WPARAM,
                wintypes.UINT,
                wintypes.LPWSTR,
                wintypes.UINT,
            ]
            shell32.DragFinish.restype = None
            shell32.DragFinish.argtypes = [wintypes.WPARAM]

            def _get_dropped_files(hdrop):
                count = shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                out = []
                for i in range(count):
                    length = shell32.DragQueryFileW(hdrop, i, None, 0) + 1
                    buf = ctypes.create_unicode_buffer(length)
                    shell32.DragQueryFileW(hdrop, i, buf, length)
                    out.append(buf.value)
                return out

            def _wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_DROPFILES:
                    try:
                        files = _get_dropped_files(wparam)
                        shell32.DragFinish(wparam)
                        self._dnd_queue.put(files)
                    except Exception:
                        pass
                    return 0
                return user32.CallWindowProcW(
                    self._old_wndproc_ptr,
                    hwnd,
                    msg,
                    wparam,
                    lparam,
                )

            hwnd = self.winfo_id()
            shell32.DragAcceptFiles(hwnd, 1)
            self._old_wndproc_ptr = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
            self._dnd_wndproc = WNDPROC(_wndproc)
            new_ptr = ctypes.cast(self._dnd_wndproc, ctypes.c_void_p)
            prev = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, new_ptr)
            if not prev:
                err = kernel32.GetLastError()
                self._append_log("WARN", f"⚠️ SetWindowLongPtrW falló (error {err}).")
            else:
                self._append_log(
                    "INFO", f"✅ Arrastrar y soltar activado (hwnd={hwnd}, prev={prev})."
                )
        except Exception as exc:
            self._append_log("WARN", f"⚠️ No se pudo activar drag & drop: {exc}")

    def _on_dropped_files(self, files: list) -> None:
        added = 0
        for raw in files:
            try:
                path = Path(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
                if path.is_dir():
                    for child in path.rglob("*"):
                        if (
                            child.is_file()
                            and is_media_extension(child)
                            and child not in self.selected_files
                        ):
                            self.selected_files.append(child)
                            added += 1
                elif (
                    path.is_file() and is_media_extension(path) and path not in self.selected_files
                ):
                    self.selected_files.append(path)
                    added += 1
                elif path.is_file() and path not in self.selected_files:
                    # Formato no en lista: lo aceptamos igualmente (puede que sea nuevo)
                    self.selected_files.append(path)
                    added += 1
                    self._append_log(
                        "WARN", f"Extensión no estándar '{path.suffix}'; procesando de todos modos."
                    )
            except Exception:
                continue
        self._render_file_list()
        if added:
            self._append_log("INFO", f"🖱️  Añadidos {added} archivo(s) mediante drag & drop.")

    def _choose_files(self) -> None:
        sorted_exts = sorted(SUPPORTED_MEDIA_EXTENSIONS)
        filetypes = [
            ("Multimedia soportado (60+ formatos)", " ".join(f"*{e}" for e in sorted_exts)),
            (
                "Vídeos",
                " ".join(
                    f"*{e}"
                    for e in sorted_exts
                    if e
                    in {
                        ".mp4",
                        ".m4v",
                        ".mov",
                        ".avi",
                        ".mkv",
                        ".webm",
                        ".wmv",
                        ".flv",
                        ".3gp",
                        ".mpeg",
                        ".mpg",
                        ".ts",
                        ".m2ts",
                        ".mxf",
                        ".vob",
                        ".ogv",
                        ".f4v",
                        ".rmvb",
                        ".mts",
                    }
                ),
            ),
            (
                "Audios",
                " ".join(
                    f"*{e}"
                    for e in sorted_exts
                    if e
                    in {
                        ".mp3",
                        ".wav",
                        ".m4a",
                        ".m4b",
                        ".flac",
                        ".ogg",
                        ".oga",
                        ".opus",
                        ".wma",
                        ".aac",
                        ".aiff",
                        ".aif",
                        ".alac",
                        ".amr",
                        ".ape",
                        ".au",
                        ".pcm",
                    }
                ),
            ),
            ("Todos los archivos", "*.*"),
        ]
        chosen = filedialog.askopenfilenames(
            title="Selecciona archivos multimedia", filetypes=filetypes
        )
        for f in chosen:
            p = Path(f)
            if p not in self.selected_files:
                self.selected_files.append(p)
        self._render_file_list()

    def _render_file_list(self) -> None:
        for w in self.frame_file_list.winfo_children():
            try:
                w.destroy()
            except tk.TclError:
                pass
        if not self.selected_files:
            ctk.CTkLabel(
                self.frame_file_list,
                text="(vacío) — selecciona archivos o arrástralos a la ventana.",
                text_color="gray60",
            ).grid(row=0, column=0, sticky="w", padx=10, pady=20)
        else:
            for i, p in enumerate(self.selected_files):
                try:
                    sz = format_size(p.stat().st_size)
                except OSError:
                    sz = "? B"
                row_frame = ctk.CTkFrame(self.frame_file_list, corner_radius=6)
                row_frame.grid(row=i, column=0, sticky="ew", pady=2, ipadx=4, ipady=4)
                row_frame.grid_columnconfigure(1, weight=1)

                ctk.CTkLabel(row_frame, text=f"{i+1:>2}.", width=28).grid(row=0, column=0, padx=6)
                ctk.CTkLabel(row_frame, text=p.name, anchor="w").grid(row=0, column=1, sticky="ew")
                ctk.CTkLabel(row_frame, text=sz, width=90, text_color="gray60").grid(
                    row=0, column=2, padx=8
                )

                def _rem(idx: int, rf: ctk.CTkFrame):
                    return lambda _e=None: self._remove_file(idx, rf)

                btn = ctk.CTkButton(
                    row_frame,
                    text="✕ Quitar",
                    width=90,
                    fg_color="#7f1d1d",
                    hover_color="#991b1b",
                    command=_rem(i, row_frame),
                )
                btn.grid(row=0, column=3, padx=6)
                row_frame.bind("<Double-Button-1>", _rem(i, row_frame))
        self.lbl_file_count.configure(text=f"{len(self.selected_files)} archivos seleccionados")

    def _remove_file(self, idx: int, _frame: ctk.CTkFrame) -> None:
        if 0 <= idx < len(self.selected_files):
            removed = self.selected_files.pop(idx)
            self._append_log("INFO", f"Quitado de la cola: {removed.name}")
            self._render_file_list()

    def _clear_selection(self) -> None:
        self.selected_files.clear()
        self._render_file_list()
        self._append_log("INFO", "Cola de procesamiento vaciada.")

    def _open_input_folder(self) -> None:
        path = self.project_root / self.paths_cfg.get("input", "input")
        path.mkdir(parents=True, exist_ok=True)
        open_folder(path)

    def _open_output_folder(self) -> None:
        path = self.project_root / self.paths_cfg.get("output", "output")
        path.mkdir(parents=True, exist_ok=True)
        open_folder(path)

    # =====================================================================
    # 🚀 Acción: Procesar archivos en cola
    # =====================================================================
    def _on_click_process(self) -> None:
        if self.running:
            messagebox.showinfo(
                self.APP_TITLE, "Ya hay una tarea en ejecución. Espera a que termine."
            )
            return
        if not self.selected_files:
            messagebox.showwarning(
                self.APP_TITLE, "Primero selecciona al menos 1 archivo multimedia."
            )
            return
        self.running = True
        self.btn_process.configure(state="disabled", text="⏳ PROCESANDO…")
        self.progress_bar.set(0.0)
        self.progress_label.configure(text="0%  —  iniciando…")
        self._append_log(
            "RUN", f"🚀 Iniciando procesamiento de {len(self.selected_files)} archivo(s)."
        )
        try:
            from worker import ProcessingWorker

            target_file = self.selected_files.pop(0)
            t = ProcessingWorker(
                target_file,
                self.message_queue,
                settings=self._build_effective_settings(),
                daemon=True,
            )
            self.worker_thread = t
            t.start()
        except Exception as exc:
            self._append_log("ERROR", f"Fallo al lanzar worker: {type(exc).__name__}: {exc}")
            self._reset_run_state()

    def _build_effective_settings(self) -> dict:
        """Clona settings.yaml pero actualiza habilitación de plataformas desde los toggles GUI."""
        import copy

        merged = copy.deepcopy(self.settings)
        if "social_media" not in merged or not isinstance(merged["social_media"], dict):
            merged["social_media"] = {}
        if "platforms" not in merged["social_media"] or not isinstance(
            merged["social_media"]["platforms"], dict
        ):
            merged["social_media"]["platforms"] = {}
        for key, var in self.platform_vars.items():
            merged["social_media"]["platforms"].setdefault(key, {})
            merged["social_media"]["platforms"][key]["enabled"] = bool(var.get())
        return merged

    # =====================================================================
    # 👀 Watcher toggle
    # =====================================================================
    def _toggle_watcher(self) -> None:
        if not self.watcher_active:
            if self.watcher_thread and self.watcher_thread.is_alive():
                return
            self.watcher_active = True
            self.btn_watch.configure(
                text="🛑 DETENER WATCHER", fg_color="#7f1d1d", hover_color="#991b1b"
            )
            t = threading.Thread(target=self._watcher_loop, daemon=True)
            self.watcher_thread = t
            t.start()
            self._append_log("RUN", "👀 Modo WATCHER activado. Vigilando ./input")
            self.footer_status.configure(text="👀 Watcher activo")
        else:
            self.watcher_active = False
            self.btn_watch.configure(
                text="👀 INICIAR WATCHER", fg_color="#475569", hover_color="#334155"
            )
            self._append_log("INFO", "🛑 Watcher detenido.")
            self.footer_status.configure(text="Listo.")

    def _watcher_loop(self) -> None:
        import time

        from main import find_media_files

        settings = self._build_effective_settings()
        paths_cfg = settings.get("paths", {}) or {}
        input_folder = self.project_root / paths_cfg.get("input", "input")
        output_folder = self.project_root / paths_cfg.get("output", "output")
        input_folder.mkdir(parents=True, exist_ok=True)
        output_folder.mkdir(parents=True, exist_ok=True)
        processed_log = output_folder / ".gui_processed.json"
        processed: set[str] = set()
        if processed_log.exists():
            try:
                with open(processed_log, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    processed = set(data)
            except Exception:
                processed = set()
        interval = (settings.get("watcher", {}) or {}).get("interval_seconds", 10)
        while self.watcher_active:
            for media in find_media_files(input_folder):
                key = str(media.resolve())
                if key in processed:
                    continue
                self.message_queue.put({"type": "watcher_new", "data": str(media)})
                try:
                    from core.ai_engine import AIEngine
                    from core.social_media import build_social_report
                    from core.transcriber import Transcriber
                    from main import (
                        _safe_write_json,
                        _safe_write_text,
                        _setup_logger,
                        build_report,
                        prepare_job_folder,
                        record_job,
                    )

                    logger = _setup_logger(output_folder)
                    models_cfg = settings.get("models", {}) or {}
                    whisper_cfg = models_cfg.get("whisper", {}) or {}
                    transcription_cfg = settings.get("transcription", {}) or {}
                    model_size = transcription_cfg.get("model_size") or whisper_cfg.get(
                        "name", "base"
                    )
                    language = transcription_cfg.get("language") or whisper_cfg.get(
                        "language", "es"
                    )
                    transcriber = Transcriber(model_name=model_size)
                    ai = AIEngine()

                    self.message_queue.put(
                        {"type": "status", "data": f"[Watcher] Transcribiendo {media.name}…"}
                    )
                    prompt_ctx = transcriber.prompt_from_filename(media.name)
                    transcription = transcriber.transcribe(
                        media, language=language, prompt=prompt_ctx
                    )
                    transcript_ai = transcriber.format_for_ai(transcription)

                    self.message_queue.put({"type": "progress", "data": 0.4})
                    self.message_queue.put(
                        {
                            "type": "status",
                            "data": f"[Watcher] Generando bundle social para {media.name}…",
                        }
                    )
                    social_bundle = ai.generate_social_media_bundle(
                        transcript_ai, filename=media.name, settings=settings
                    )
                    self.message_queue.put({"type": "progress", "data": 0.8})

                    yt_legacy = ai.generate_youtube_metadata(transcript_ai, filename=media.name)

                    job_folder = prepare_job_folder(output_folder, media.stem, media.stem)
                    _safe_write_text(job_folder / "resultado_youtube.txt", build_report(yt_legacy))
                    _safe_write_text(job_folder / "transcripcion.txt", transcript_ai)
                    _safe_write_text(
                        job_folder / "transcripcion_raw.txt", transcription.get("text", "")
                    )

                    payload = {
                        "archivo": str(media.resolve()),
                        "transcripcion": transcription,
                        "youtube_legacy": yt_legacy,
                        "social_media": social_bundle.to_dict(),
                    }
                    _safe_write_json(job_folder / "resultado_youtube.json", payload)
                    _safe_write_json(job_folder / "contenido_redes_sociales.json", payload)
                    reporte_social = build_social_report(social_bundle)
                    _safe_write_text(job_folder / "redes_sociales.txt", reporte_social)
                    record_job(output_folder, media, job_folder, status="completado", logger=logger)

                    processed.add(key)
                    try:
                        with open(processed_log, "w", encoding="utf-8") as f:
                            json.dump(sorted(processed), f, ensure_ascii=False, indent=2)
                    except OSError:
                        pass
                    self.message_queue.put(
                        {
                            "type": "done",
                            "data": {
                                "job_folder": str(job_folder),
                                "watcher": True,
                                "redes_sociales": social_bundle.enabled_platforms(),
                                "errores_redes": social_bundle.errors,
                            },
                        }
                    )
                except Exception as exc:
                    import traceback

                    self.message_queue.put(
                        {
                            "type": "error",
                            "data": {
                                "message": f"[Watcher] Falló {media.name}: {type(exc).__name__}: {exc}",
                                "traceback": traceback.format_exc(),
                            },
                        }
                    )
            for _ in range(interval):
                if not self.watcher_active:
                    break
                time.sleep(1)

    # =====================================================================
    # 📜 Log
    # =====================================================================
    def _append_log(self, level: str, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        color = {
            "INFO": "#38bdf8",
            "RUN": "#a78bfa",
            "ERROR": "#f87171",
            "OK": "#22c55e",
            "WARN": "#fbbf24",
        }.get(str(level).upper(), "gray90")
        tag = f"[{ts}] [{str(level).upper():<5}]"
        try:
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", f"{tag} ", f"level_{level}")
            self.log_textbox.insert("end", msg + "\n\n")
            try:
                self.log_textbox.tag_config(f"level_{level}", foreground=color)
            except tk.TclError:
                pass
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
        except Exception:
            pass

    # =====================================================================
    # 📬 Poll de mensajes worker → GUI
    # =====================================================================
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.message_queue.get_nowait()
                mtype = msg.get("type", "")
                data = msg.get("data")
                if mtype == "status":
                    self.footer_status.configure(text=str(data))
                    self._append_log("INFO", str(data))
                elif mtype == "progress":
                    try:
                        val = float(data)
                    except (TypeError, ValueError):
                        val = 0.0
                    self.progress_bar.set(min(1.0, max(0.0, val)))
                    self.progress_label.configure(
                        text=f"{int(val * 100)}%  —  {self.footer_status.cget('text')}"
                    )
                elif mtype == "warning":
                    self._append_log("WARN", str(data))
                elif mtype == "error":
                    if isinstance(data, dict):
                        self._append_log("ERROR", str(data.get("message", "")))
                        tb = data.get("traceback")
                        if tb:
                            for line in str(tb).splitlines()[:20]:
                                self._append_log("ERROR", "  | " + line)
                    else:
                        self._append_log("ERROR", str(data))
                    messagebox.showerror(
                        self.APP_TITLE,
                        str(data.get("message", data) if isinstance(data, dict) else data),
                    )
                    self._reset_run_state()
                elif mtype == "done":
                    self._append_log("OK", f"✅ Tarea completada → {data}")
                    try:
                        self.progress_bar.set(1.0)
                        self.progress_label.configure(text="100%  —  completado")
                    except Exception:
                        pass
                    self._reset_run_state()
                    # Continúa con el siguiente archivo si hay
                    if self.selected_files:
                        self.after(250, self._on_click_process)
                    self._refresh_results()
                elif mtype == "watcher_new":
                    self._append_log(
                        "RUN", f"👀 Watcher detectó nuevo archivo: {Path(str(data)).name}"
                    )
                    self.footer_status.configure(
                        text=f"[Watcher] Procesando {Path(str(data)).name}"
                    )
                else:
                    self._append_log("INFO", f"[{mtype}] {data}")
        except queue.Empty:
            pass

        # Archivos arrastrados capturados por el WndProc nativo
        try:
            while True:
                files = self.dnd_queue.get_nowait()
                self._on_dropped_files(files)
        except queue.Empty:
            pass

        self.after(140, self._poll_queue)

    def _reset_run_state(self) -> None:
        self.running = False
        self.worker_thread = None
        try:
            self.btn_process.configure(state="normal", text="🚀 PROCESAR")
        except tk.TclError:
            pass
        self.footer_status.configure(text="Listo.")


# ===========================================================================
# Lanzador
# ===========================================================================
def launch_gui(settings: dict | None = None) -> int:
    """Función de entrada pública para arrancar la GUI. Devuelve exit code."""
    try:
        app = DavinciApp(settings=settings)
    except Exception as exc:  # pragma: no cover - solo feedback fatal
        import traceback

        traceback.print_exc()
        try:
            messagebox.showerror(
                "DaVinci Agent — Error fatal",
                f"No se pudo iniciar la GUI.\n\n{type(exc).__name__}: {exc}",
            )
        except Exception:
            pass
        return 1
    app.mainloop()
    return 0
