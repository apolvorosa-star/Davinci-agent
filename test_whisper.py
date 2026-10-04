from transformers import pipeline
import torch

print("Cargando Whisper Large V3 Turbo desde Hugging Face...")
# Inicializa el pipeline de transcripción optimizado
pipe = pipeline(
    "automatic-speech-recognition",
    model="openai/whisper-large-v3-turbo",
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device="cuda" if torch.cuda.is_available() else "cpu"
)

print("¡Modelo cargado con éxito! Probando transcripción...")

# Puedes usar el archivo .ogg que tienes en la carpeta principal de tu proyecto
audio_path = "WhatsApp Ptt 2026-07-26 at 22.04.22.ogg"
result = pipe(audio_path)

print("\n--- TRANSCRIPCIÓN OBTENIDA ---")
print(result["text"])