"""Utilidad para cargar y expandir variables de entorno en configuraciones YAML.

Soporta sintaxis tipo ``docker-compose``:

* ``${MYVAR}``           → variable **obligatoria**. Lanza ``ValueError`` si falta.
* ``${MYVAR:-default}``  → variable **opcional**. Usa ``default`` si falta o está vacía.

La función :func:`expand_env_vars` opera de forma **recursiva** sobre strings,
diccionarios, listas y tuplas; cualquier otro tipo se devuelve tal cual.

Ejemplo::

    import os
    from core.providers.env_loader import expand_env_vars

    os.environ["API_KEY"] = "sk-secret"
    cfg = expand_env_vars({
        "provider": {
            "url": "${MY_URL:-http://localhost:11434}",
            "token": "${API_KEY}",
        }
    })
    # -> {"provider": {"url": "http://localhost:11434", "token": "sk-secret"}}
"""

from __future__ import annotations

import os
import re
from typing import Any

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env_vars(value: Any) -> Any:
    """Sustituye ${VAR} y ${VAR:-default} de forma **recursiva**.

    Args:
        value: Valor origen. Puede ser ``str``, ``dict``, ``list``, ``tuple``
            o cualquier otro tipo (se devuelve inalterado).

    Returns:
        El mismo tipo que la entrada, con variables expandidas en todos los
        niveles anidados.

    Raises:
        ValueError: Si aparece ``${VAR}`` (sin default) y la variable no está
            definida en ``os.environ`` o está vacía. El mensaje incluye el
            nombre de la variable para facilitar debugging en
            producción/distribución.
    """
    if isinstance(value, str):

        def _replace(match: re.Match[str]) -> str:
            name = match.group(1)
            default = match.group(2)
            env_val = os.environ.get(name, "")
            if env_val == "":
                if default is not None:
                    return default
                raise ValueError(
                    f"Falta la variable de entorno obligatoria '{name}'. "
                    "Defínela antes de ejecutar DaVinci Agent, o añada un "
                    "valor por defecto con la sintaxis ${VAR:-default} en "
                    "config/settings.yaml."
                )
            return env_val

        return _ENV_PATTERN.sub(_replace, value)

    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [expand_env_vars(item) for item in value]

    if isinstance(value, tuple):
        return tuple(expand_env_vars(item) for item in value)

    return value
