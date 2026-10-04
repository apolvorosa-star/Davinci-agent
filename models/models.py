from llama_cpp import Llama
import os

class Modelo:
    def __init__(self, modelo_path):
        self.modelo_path = modelo_path
        # Inicializa el motor GGUF de forma local y eficiente
        self.modelo = Llama(model_path=self.modelo_path, n_ctx=2048, verbose=False)

    def generar_texto(self, prompt, max_tokens=512):
        # Ejecuta la inferencia nativa con los parámetros correctos
        respuesta = self.modelo(
            prompt,
            max_tokens=max_tokens,
            stop=["</s>"],
            echo=False
        )
        # Extrae limpiamente el texto de la respuesta de Llama
        return respuesta["choices"][0]["text"]