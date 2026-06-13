from pathlib import Path
import anthropic
import os
import json
import time

IGNORAR = {".venv", "__pycache__", ".git", "node_modules", ".idea", "dist", "build", ".gitignore", "README.md", ".env.example"}

ARCHIVOS_PRIORITARIOS = {
    "main.py", "app.py", "index.js", "index.ts",
    "requirements.txt", "package.json", "pom.xml", "composer.json",
    "README.md", "README.rst", "CLAUDE.md"
}

EXTENSIONES_CODIGO = {".py", ".js", ".ts", ".java", ".php"}


def obtener_arbol(path: Path) -> list[str]:
    archivos = []
    for archivo in path.rglob("*"):
        if archivo.is_file():
            partes = archivo.parts
            if any(parte in IGNORAR for parte in partes):
                continue
            archivos.append(str(archivo.relative_to(path)))
    return sorted(archivos)


def leer_archivos_clave(path: Path, arbol: list[str]) -> str:
    seleccionados = []
    for ruta_relativa in arbol:
        archivo = Path(ruta_relativa)
        if archivo.name in ARCHIVOS_PRIORITARIOS or archivo.suffix in EXTENSIONES_CODIGO:
            seleccionados.append(ruta_relativa)

    fragmentos = []
    for ruta_relativa in seleccionados:
        ruta_completa = path / ruta_relativa
        try:
            lineas = ruta_completa.read_text(encoding="utf-8").splitlines()[:40]
            fragmentos.append(f"### {ruta_relativa}\n" + "\n".join(lineas))
        except Exception:
            continue
    return "\n\n".join(fragmentos)


def modulo_necesita_actualizacion(file_path: str, proyecto_path: Path, modulo_existente) -> bool:
    if modulo_existente is None or modulo_existente.last_updated_at is None:
        return True
    ruta = proyecto_path / file_path
    if not ruta.exists():
        return False
    return os.path.getmtime(ruta) > modulo_existente.last_updated_at


def analizar_con_claude(nombre: str, stack: str, arbol: list[str], contenido: str) -> list[dict]:
    arbol_texto = "\n".join(arbol)

    prompt = f"""Analiza este proyecto de software e identifica sus módulos principales.

Proyecto: {nombre}
Stack: {stack}

Árbol de archivos:
{arbol_texto}

Contenido de archivos clave:
{contenido}

Devolvé ÚNICAMENTE un JSON válido con esta estructura, sin texto adicional antes ni después:
[
  {{
    "name": "nombre_del_modulo",
    "description": "qué hace este módulo en una línea",
    "file_path": "ruta/del/archivo/principal.py",
    "category": "backend",
    "domain": null
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio.
domain es el área funcional (ej: autenticación, pagos) o null si no aplica."""

    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )

    texto = respuesta.content[0].text.strip()
    texto = texto.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(texto)


def generar_contenido_modulo(nombre: str, file_path: str, contenido_fuente: str) -> str:
    prompt = f"""Eres un asistente técnico. Genera documentación detallada en markdown para este módulo.

Módulo: {nombre}
Archivo: {file_path}

Código fuente:
{contenido_fuente}

Generá un documento markdown con exactamente estas secciones:
- Qué hace este módulo
- Funciones o clases principales (con descripción de cada una)
- Conexiones con otros módulos
- Convenciones o decisiones técnicas relevantes

Solo el markdown, sin texto adicional antes ni después."""

    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    return respuesta.content[0].text


def indexar_proyecto(path: Path, nombre: str, stack: str) -> list[dict]:
    arbol = obtener_arbol(path)
    contenido = leer_archivos_clave(path, arbol)
    modulos = analizar_con_claude(nombre, stack, arbol, contenido)

    for modulo in modulos:
        ruta_fuente = path / modulo["file_path"]
        try:
            fuente = ruta_fuente.read_text(encoding="utf-8")
        except FileNotFoundError:
            fuente = ""
        modulo["content_md"] = generar_contenido_modulo(modulo["name"], modulo["file_path"], fuente)
        modulo["last_updated_at"] = time.time()

    return modulos