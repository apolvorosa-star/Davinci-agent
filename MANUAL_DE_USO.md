# 📖 Manual de Uso — DaVinci Agent v1.0.0
### Sistema profesional de transcripción + generación de contenido multi-plataforma para 6 redes sociales

---

## 🚀 Formas rápidas de abrir DaVinci Agent

Tienes **3 vías de uso** elige la que más te guste:

| # | Método | Cómo hacerlo | Ideal para |
|---|---|---|---|
| 1 | **GUI de escritorio (doble clic)** | Abre el explorador → entra en la carpeta → doble clic en **`app.py`** | Uso diario visual, arrastrar archivos, ver progreso |
| 2 | **GUI desde terminal** | `cd "G:\mis proyectos de programacion\Davinci-agent"` → `python app.py` | Cuando quieres ver también los logs en consola |
| 3 | **Modo CLI (consola)** | `python main.py --help` | Automatización, scripts por lotes, servidores |

> 💡 **Recomendación**: empieza siempre por **la GUI de escritorio (app.py)**. Es la más intuitiva.

---

## 🖥️ Explicación de la Interfaz Gráfica (5 pestañas)

Abre `python app.py` y verás esta estructura:

### 🔹 Pestaña 1 — 🎬 INICIO (la más usada)
Aquí pasas el 90% del tiempo. Contiene:

1. **Panel superior:** Información rápida:
   - 📂 **Abrir carpeta entrada**: abre `./input` (coloca ahí archivos para que el watcher los procese).
   - 📂 **Abrir carpeta salida**: abre `./output` (aquí se guardan TODOS los resultados).

2. **Selección de archivos multimedia:**
   - Escribe en el cuadro o pulsa **Seleccionar…** para elegir 1 o más archivos (mp3, mp4, wav, m4a, flac, mov, mkv, webm…).
   - **Atajo PRO**: simplemente **arrastra y suelta archivos** (o carpetas enteras) desde el explorador a la ventana.

3. **Botones de acción:**
   | Botón | Acción |
   |---|---|
   | 🚀 **PROCESAR** | Procesa la cola de archivos seleccionados: 1) Whisper → 2) IA → 3) 6 redes sociales |
   | 👀 **INICIAR WATCHER** | Activa el modo vigilancia. A partir de ahora, CUALQUIER archivo nuevo que copies/muevas a `./input` se procesará **automáticamente**. Pulsa de nuevo para detener. |
   | 🧹 **Limpiar selección** | Vacía la cola |

4. **Panel de info (no tocable):** indica qué modelo Whisper está activo y qué proveedor IA usará por defecto.

5. **Cola de procesamiento:** lista los archivos. Haz clic en **✕ Quitar** para sacar uno, o **doble clic** sobre una fila.

---

### 🔹 Pestaña 2 — 📲 REDES SOCIALES
**Aquí eliges para qué plataformas quieres generar contenido.** Cada tarjeta trae un **checkbox de activación** + una mini-descripción con tono, hashtags máximos y tipo de salida:

| Plataforma | ¿Qué genera? |
|---|---|
| 🎥 **YouTube** | Título SEO (≤100c), descripción larga (≤5000c), tags (≤50), capítulos con marcas de tiempo, CTA final |
| 📸 **Instagram** | Feed post (≤2200c), 3-10 slides de **carrusel**, 5-10 **stories** con stickers y prompts visuales, 1 **reel** con hook + audio sugerido |
| 🎵 **TikTok** | Hook viral ≤3s, caption, 5-8 hashtags, sugerencia de tendencia, audio, overlays textuales (3-10), scene cuts (3-6) |
| 🐦 **X (Twitter)** | Tweet principal (≤280c hard), hilo ≤15 tweets (cada uno ≤280c), poll encuesta (2-4 opciones), hashtags por tweet, media hints |
| 👥 **Facebook** | Post largo 800-1800 palabras, summary_points 3-8 bullets, audience hints, link previews, primer comentario pinneado |
| 💼 **LinkedIn** | Headline B2B, opening storytelling, core_story + reflexión, 3-10 lecciones **accionables**, CTA con pregunta abierta, audiencia por seniority |

**Consejo de productividad**: deja las 6 activadas siempre. Generar las 6 tarda igual que 1 porque usa el mismo transcript de Whisper.

---

### 🔹 Pestaña 3 — 🤖 IA
Estado de salud de tu pipeline de inteligencia artificial (SOLO LECTURA):
- ✅ **Proveedor IA por defecto**: normalmente `ollama` (local, sin coste).
- ✅ **Proveedores disponibles**: Ollama + los que tengas con API key válida y `enabled:true` en settings.
- ⚠️ **Lista de proveedores deshabilitados** y por qué (enabled:false, missing API key, timeout…).

Más abajo tienes el bloque de configuración de IA (settings.yaml) en formato JSON — útil para diagnosticar.

---

### 🔹 Pestaña 4 — 📜 LOG
Consola en vivo. **NUNCA cierres esta pestaña si una tarea falla.** Tienes:
- Colores por nivel: 🔵 INFO 🟣 RUN 🟢 OK 🟡 WARN 🔴 ERROR
- **Barra de progreso** 0–100% del job actual.
- Porcentaje y estado actual.

Si algo falla, aquí aparecerá el error + traceback (las 20 líneas exactas del fallo).

---

### 🔹 Pestaña 5 — 📊 RESULTADOS
Historial visual de los últimos **50 trabajos**. Cada tarjeta lleva:
- **Píldora de color**: ✅ COMPLETADO / ❌ ERROR / ⏳ PENDIENTE
- Nombre del archivo, hora y ruta de la carpeta generada.
- **Doble clic en la tarjeta** → abre directamente la carpeta con los resultados en el explorador.

Actualiza con **🔄 Actualizar**.

---

## 🛠️ Paso a paso: tu PRIMER procesamiento

**Objetivo**: tomar un vídeo mp3 de una reunión/charla y generar para 6 redes en 3 clics.

```
PASO 1 ➡️  Abrir la GUI
   Doble clic en app.py

PASO 2 ➡️  Cargar tu audio/vídeo
   Opción A: arrástralo y suéltalo en la ventana.
   Opción B: Seleccionar… → elige tu archivo.
   ✔️ Verás el nombre + tamaño en la "Cola de procesamiento".

PASO 3 ➡️  (Opcional) Elige plataformas
   Ve a 📲 Redes Sociales → marca o desmarca lo que quieras.
   (si no tocas nada, se usan las 6 habilitadas por defecto).

PASO 4 ➡️  Lanzar
   Pulsa 🚀 PROCESAR.

PASO 5 ➡️  Mirar progreso
   La barra se mueve así:
     10%   → Cargando Whisper
     30%   → Transcribiendo audio (puede tardar 1-5min según duración)
     50-65%→ Conectando IA y generando contenido para redes
     80%   → Metadatos YouTube legacy
     90%   → Guardando ficheros
     100%  → ✅ Completado

PASO 6 ➡️  Recoger tus resultados
   Ve a 📊 Resultados → encuentra la fila del archivo → DOBLE CLIC
   Se abre la carpeta. Ahí tienes:
     📄 redes_sociales.txt            ← (MÁS ÚTIL) Informe legible de las 6 redes
     📄 resultado_youtube.txt         ← Título + descripción + capítulos
     📄 transcripcion_raw.txt         ← Texto plano íntegro de Whisper
     📄 contenido_redes_sociales.json ← (PROGRAMADORES) Payload estructurado
     📄 resultado_youtube.json        ← Payload legacy con todo
```

---

## 👀 MODO WATCHER (automatización total)

Perfecto para:
- Pipelines de estudio: tu editor de vídeo exporta mp4 a una carpeta sincronizada.
- Crea contenido por lotes sin tocar la app.

**Cómo usarlo:**
1. Crea/copia/mueve archivos a la carpeta `./input` (puedes abrirla con el botón 📁 Entrada).
2. Pulsa **👀 INICIAR WATCHER**. El botón se pone rojo.
3. A partir de ese instante, TODO archivo nuevo que aparezca en `./input` se procesa automáticamente.
4. Para de vigilar pulsando **🛑 DETENER WATCHER**.

> 🧠 Truco: puedes dejar la GUI abierta 24h con el watcher activado. Los archivos procesados se recuerdan en `.output/.gui_processed.json` para no re-procesarse aunque cierres y abras la app.

---

## 📂 ¿Qué produce cada job? (archivos de salida)

Cada vez que procesas un archivo, se crea una carpeta ÚNICA en `./output/<NombreDelArchivo>_<sufijo>/` con:

| Archivo | Tipo | Para quién es | Contenido clave |
|---|---|---|---|
| `redes_sociales.txt` | 📝 Texto | ✅ **TÚ** (más útil) | Informe HUMANO leíble con TODO el contenido de las 6 redes ordenado por plataforma |
| `resultado_youtube.txt` | 📝 Texto | Editor de YouTube | Título, descripción, capítulos formateados listos para copiar/pegar |
| `transcripcion.txt` | 📝 Texto | Legibilidad humana | Reporte + metadata YouTube |
| `transcripcion_raw.txt` | 📝 Texto | Archivadores / LLMs | Únicamente el texto plano íntegro, sin adornos |
| `contenido_redes_sociales.json` | 📋 JSON | Desarrolladores / integraciones API | Payload estructurado de transcript + 6 redes + status IA |
| `resultado_youtube.json` | 📋 JSON | Compatibilidad legacy | Lo mismo + extra de legacy YouTube |

---

## ⚙️ Configuración avanzada (settings.yaml)

Edita [config/settings.yaml](file:///G:/mis%20proyectos%20de%20programacion/Davinci-agent/config/settings.yaml) **solo si sabes lo que haces**. Bloques más útiles:

### Bloque `social_media.defaults` (heredado por TODAS las plataformas):
```yaml
social_media:
  defaults:
    language: "es"              # idioma del contenido
    tone: "equilibrado"         # tono general: profesional | cercano | viral | reflexivo
    max_hashtags: 15            # tope superior (cada plataforma puede reducirlo)
    cta: "¡Síguenos para más!"
    extra_rules:                # reglas que se inyectan SIEMPRE al prompt
      - "Nunca inventes datos"
```

### Bloque `social_media.platforms.<plataforma>` (por red):
Ejemplo — quiero TikTok más agresivo, LinkedIn desactivado temporalmente:
```yaml
    tiktok:
      enabled: true
      tone: "juvenil-directo"
      max_hashtags: 8
      extra_rules:
        - "Siempre pregunta polémica en el hook"
    linkedin:
      enabled: false            # ← se salta la generación aunque esté marcada en GUI
```

### Bloque `ai.providers.<provider>` (provedores IA):
Por defecto solo **Ollama** está activado (sin coste, local). Para activar otro:
```yaml
    openai:
      enabled: true                                  # ← cambia a true
      api_key: "sk-......tuApiKeyAquí...."           # o usa variable de entorno
      model: "gpt-4o-mini"
```
Luego pon `ai.default_provider: openai`.

---

## 🔧 Solución de problemas (FAQ)

### ❓ 1. Abro app.py y no pasa nada / aparece una ventana y se cierra
1. Abre un CMD, escribe `python app.py` y mira el error en consola.
2. Causa más frecuente: `whisper` / `torch` no instalados correctamente.
   - Corre en consola:
     ```bash
     pip install -r requirements.txt
     ```
3. Segunda causa frecuente: no tienes Ollama arrancado en local. Descárgalo de [ollama.com](https://ollama.com) y ejecuta `ollama run llama3` una vez.

### ❓ 2. "No se pudo inicializar provider [X]: enabled:false"
Es **NORMAL y no es un error**. Solo te informa de que esa plataforma IA está explícitamente deshabilitada en settings.yaml. Si no quieres usarla, ignóralo.

### ❓ 3. El procesamiento se queda en 30% mucho rato
Es la transcripción Whisper. Los modelos grandes (`large-v3`) pueden tardar 5–15 minutos en vídeos de 1h+ en CPU. Acelera cambiando en settings:
```yaml
models:
  whisper:
    name: "tiny"      # o "base", "small", "medium", "large-v3"
    language: "es"
```

### ❓ 4. Una plataforma devuelve contenido vacío
Entra en la pestaña **📜 Log**, busca la línea `WARNING` o `ERROR` — normalmente es que la IA no devolvió JSON bien formado, y la validación lo rellenó con defaults. Repite el procesamiento (la naturaleza probabilística de la IA suele solucionarlo).

### ❓ 5. El watcher no procesa un archivo
Asegúrate de:
1. Está guardado EN `./input` (no subcarpeta — el watcher busca recursivamente pero el log `.gui_processed.json` recuerda los ya procesados; borra ese archivo para forzar).
2. Extensión soportada: `.mp3 .wav .m4a .flac .ogg .opus .mp4 .mov .avi .webm .mkv .3gp`

### ❓ 6. Error `AIEngine: FallbackChain: todos los providers fallaron`
Significa que:
- Ollama no está arrancado (arráncalo: `ollama serve`)
- La API key del proveedor por defecto no es válida
- No hay internet para proveedores cloud

Solución rápida: **arranca Ollama local** + pulsa de nuevo PROCESAR.

---

## 🏗️ Estructura de carpetas del proyecto (para referirme rápidamente)

```
Davinci-agent/
├── 🚪 app.py                     ← ENTRADA GUI (doble clic)
├── 🖥️ main.py                    ← ENTRADA CLI (terminal)
├── 👀 watcher.py                 ← Modo vigilancia (consola standalone)
├── 🧵 worker.py                  ← Hilo de procesamiento (usado por GUI + CLI)
├── 🧰 ui_utils.py                ← Funciones UI utilitarias
├── 📦 requirements.txt           ← pip install -r requirements.txt
├── 📦 package.json               ← Meta + scripts Node (si necesitas server)
├── config/
│   ├── settings.yaml             ← ⚙️ Configuración maestra (¡tócalo con cuidado!)
│   └── config.json               ← Configuración de UI
├── core/
│   ├── ai_engine.py              ← Orquestador IA multi-proveedor (generate / generate_social_media_bundle)
│   ├── transcriber.py            ← Whisper + pre / post procesado
│   ├── gui/
│   │   └── app_gui.py            ← 🔧 CÓDIGO DE LA INTERFAZ GRÁFICA (5 pestañas)
│   ├── providers/                ← Ollama, OpenAI, Anthropic, Google, OpenRouter, Mistral…
│   └── social_media/             ← 🔧 SISTEMA PROFESIONAL DE REDES SOCIALES
│       ├── base.py               ← BaseSocialPlatform (clase abstracta)
│       ├── manager.py            ← SocialMediaManager (orquestador)
│       └── platforms/
│           ├── youtube.py
│           ├── instagram.py
│           ├── tiktok.py
│           ├── twitter_x.py
│           ├── facebook.py
│           └── linkedin.py
├── models/models.py              ← (Opcional) LlamaCpp local (requiere llama-cpp-python)
├── input/                        ← 📥 Coloca aquí archivos para el WATCHER
└── output/                       ← 📤 Resultados (1 carpeta por job). error.log aquí.
```

---

## ✅ Checklist: Antes de pedir soporte

1. [ ] He leído la sección **Solución de problemas (FAQ)** de este manual
2. [ ] He ejecutado `pip install -r requirements.txt` en el venv correcto
3. [ ] Si uso Ollama: `ollama list` muestra al menos un modelo (ej: `llama3`)
4. [ ] Si uso proveedor cloud: API key correcta y `enabled:true` en settings
5. [ ] He mirado la pestaña **📜 Log** y ahí aparece el error concreto

---

## 🎯 Próximos pasos recomendados

1. **Primer contacto**: procesa un audio corto (1–3 min) para familiarizarte.
2. **Perfecciona**: modifica `social_media.defaults.extra_rules` con tu estilo editorial.
3. **Acelera**: baja Whisper a `"tiny"` para pruebas, súbelo a `"large-v3"` solo para publicación final.
4. **Automatiza**: activa el WATCHER + carpeta sincronizada Google Drive/OneDrive → entra, exporta, listo.
5. **Producción**: activa 2 proveedores IA + fallback chain para nunca caerte.

---

**v1.0.0 · DaVinci Agent · Orizon Studio Suite** — *Sistema profesional de transcripción IA y contenido multi-plataforma para redes sociales.*
