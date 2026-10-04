import os
import platform
import subprocess
from pathlib import Path


def format_size(size_bytes: int) -> str:
    """Convierte bytes a una cadena legible (KB, MB, GB...)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ["KB", "MB", "GB", "TB"]
    size = size_bytes / 1024.0
    for unit in units:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def open_folder(path: Path) -> None:
    """Abre una carpeta en el explorador del sistema."""
    if not path.exists():
        return
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(["explorer", str(path)])
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        os.startfile(str(path))


def read_text_file(path: Path) -> str:
    """Lee un archivo de texto devolviendo una cadena vacía si no existe."""
    if not path.exists():
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()
