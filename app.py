"""Launcher principal de DaVinci Agent.

Si ejecutas este archivo directamente (doble clic, o ``python app.py``)
se abre la **interfaz gráfica** de escritorio (CustomTkinter).

Si necesitas la consola / CLI usa ``python main.py [args]``.
"""

from __future__ import annotations

import sys


def _enable_crash_dump() -> None:
    """Activa faulthandler: si un fallo nativo (ctypes/Tk/CUDA) mata el proceso,
    vuelca el stack de todos los hilos a ``.tmp/crash.log`` para diagnóstico."""
    try:
        import faulthandler
        from pathlib import Path

        log_path = Path(__file__).resolve().parent / ".tmp" / "crash.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        faulthandler.enable(open(log_path, "a", encoding="utf-8"))
    except Exception:
        pass


def main_cli() -> int:
    """Redirige a main.main() por si alguien invoca app.py desde CLI con args."""
    from main import main

    return main()


def main() -> int:
    # Si se pasan argumentos explícitos (distintos del propio script) → modo CLI
    if len(sys.argv) > 1:
        return main_cli()

    # Default: arrancar GUI de escritorio (doble clic / python app.py)
    try:
        from core.gui.app_gui import launch_gui
        from main import load_settings

        return launch_gui(settings=load_settings())
    except KeyboardInterrupt:  # pragma: no cover
        return 130
    except Exception as exc:  # pragma: no cover - feedback último recurso
        import traceback

        traceback.print_exc()
        try:
            # Mostrar tanto por consola como en un popup si tkinter está disponible
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "DaVinci Agent — No se pudo abrir",
                "La interfaz gráfica falló al iniciarse.\n\n"
                f"{type(exc).__name__}: {exc}\n\n"
                "Revisa la consola para el detalle completo, o instala dependencias:\n"
                "  pip install customtkinter>=5.2.2 windnd>=1.0.1",
            )
            root.destroy()
        except Exception:
            pass
        print("\n💡 Alternativa: usa el modo CLI con  python main.py --help", file=sys.stderr)
        return 1


if __name__ == "__main__":
    _enable_crash_dump()
    raise SystemExit(main())
