# DaVinci Agent

Sistema de transcripcion (Whisper) + generacion automatica de contenido
multi-plataforma para redes sociales: YouTube, Instagram, TikTok, X,
Facebook y LinkedIn.

Suelta un video/audio en `./input` y la app transcribe, resume y genera
copys adaptados a cada red usando una cadena de proveedores de IA con
fallback automatico (Ollama, OpenAI, Anthropic, Google, OpenRouter,
Mistral o cualquier API compatible con OpenAI).

## Requisitos

- Python 3.11+
- [FFmpeg](https://ffmpeg.org/) en el PATH (necesario para Whisper/pydub)
- Un proveedor de IA operativo: Ollama en local, router de keys en
  `localhost:3001`, o una API key en `.env`

## Instalacion

```bash
pip install -r requirements.txt          # runtime
pip install -r requirements-dev.txt      # tests + lint + empaquetado
cp .env.example .env                     # rellena las API keys que uses
```

## Uso

| Modo | Comando |
|---|---|
| GUI de escritorio | `python app.py` (o doble clic en `INICIAR_DAVINCI.bat`) |
| CLI, un archivo | `python main.py video.mp4 -o ./output` |
| Watcher (carpeta caliente) | `python main.py --watch` |
| Listar entrada | `python main.py --list` |

Manual detallado de la GUI: [MANUAL_DE_USO.md](MANUAL_DE_USO.md).

## Configuracion

- `config/settings.yaml` — plantilla versionada (proveedores, prompts,
  reglas por plataforma).
- `config/settings.user.yaml` — tu config local (en `.gitignore`, nunca
  se sube). Sobrescribe lo que necesites.
- Las API keys **no** se escriben en el YAML: se referencian como
  `${OPENAI_API_KEY}` / `${VAR:-default}` y se expanden desde `.env` o
  variables de entorno (ver `.env.example`).

## Docker

```bash
cp .env.example .env          # rellena keys
docker compose up -d          # modo watcher sobre ./input
docker compose run --rm davinci-agent video.mp4   # archivo concreto
```

La GUI no corre en contenedor (CustomTkinter); la imagen usa la CLI.

## Desarrollo

```bash
pytest tests/        # tests unitarios (providers, fallback, env vars)
ruff check .         # lint
black --check .      # formato
```

CI en `.github/workflows/ci.yml`: ruff + black + pytest en cada push/PR.

## Estructura

```
core/
  providers/     # BaseProvider + Ollama, OpenAI-compatible, Anthropic, Google
                 # + FallbackChainExecutor y retry con respeto de Retry-After
  social_media/  # generadores por plataforma (youtube, instagram, tiktok, ...)
  tts.py         # voz en off (edge-tts, fallback SAPI) + SRT + video doblado
  gui/           # interfaz CustomTkinter
main.py          # CLI / watcher
app.py           # lanzador GUI
```

## Seguridad

- `.env`, `config/settings.user.yaml`, `output/`, `input/` estan en
  `.gitignore` — las claves y los datos no se versionan.
- Si una key se filtra por accidente, revocala y regenera.
