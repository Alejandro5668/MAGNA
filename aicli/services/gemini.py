import os
import time
import logging
from pathlib import Path

_VIDEO_PROMPT = (
    "Describí en español qué muestra este video de QA o evidencia. "
    "Enfocate en: qué hace el usuario paso a paso, qué comportamiento "
    "incorrecto o bug se observa, y cuál sería el comportamiento esperado. "
    "Sé concreto y técnico."
)

_MIME_MAP = {
    ".mp4":  "video/mp4",
    ".mov":  "video/quicktime",
    ".avi":  "video/x-msvideo",
    ".webm": "video/webm",
    ".mkv":  "video/x-matroska",
}


def analyze_video(path: str) -> tuple[str, int]:
    """
    Sube el video al Files API de Gemini y retorna (descripción, tokens_estimados).
    Elimina el archivo remoto al finalizar.
    """
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no configurada en ~/.mycontext/.env")

    genai.configure(api_key=api_key)

    mime = _MIME_MAP.get(Path(path).suffix.lower(), "video/mp4")
    video_file = genai.upload_file(path=path, mime_type=mime)

    while video_file.state.name == "PROCESSING":
        time.sleep(3)
        video_file = genai.get_file(video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"Gemini no pudo procesar el video: {video_file.name}")

    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content([video_file, _VIDEO_PROMPT])

    try:
        genai.delete_file(video_file.name)
    except Exception:
        pass

    description = response.text.strip()
    return description, len(description) // 4
