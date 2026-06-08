from pathlib import Path
import anthropic
import os
import json

# Recorrer todo el directorio de archivos (o sea el path)

IGNORAR = {".venv", "__pycache__", ".git", "node_modules", ".idea", "dist", "build", ".gitignore", "README.md", ".env.example"}

def obtener_arbol(path: Path):
    archivos = []
    for archivo in path.rglob("*"):
        if archivo.is_file():
            partes = archivo.parts
            if any(parte in IGNORAR for parte in partes):
                continue
            archivos.append(str(archivo.relative_to(path)))
    return sorted(archivos)

# Archivos que siempre queremos leer si existen
ARCHIVOS_PRIORITARIOS = {
    "main.py", "app.py", "index.js", "index.ts",
    "requirements.txt", "package.json", "pom.xml", "composer.json",
    "README.md", "README.rst", "CLAUDE.md"
}

# Extensiones de código fuente que vale la pena incluir
EXTENSIONES_CODIGO = {".py", ".js", ".ts", ".java", ".php"}

def leer_archivos_clave(path: Path, arbol: list[str]):
    seleccionados = []

    for ruta_relativa in arbol:
        archivo = Path(ruta_relativa)
        nombre = archivo.name
        extension = archivo.suffix

        es_prioritario = nombre in ARCHIVOS_PRIORITARIOS
        es_codigo = extension in EXTENSIONES_CODIGO

        if es_prioritario or es_codigo:
            seleccionados.append(ruta_relativa)

    # Aqui se obtienen los fragmentos de textos, especificamente se leen los archivo seleccionados
    # Nos quedamos con las primeras 40 lineas de codigo para optimizar tokens
    fragmentos = []
    for ruta_relativa in seleccionados:
        ruta_completa = path / ruta_relativa
        try:
            lineas = ruta_completa.read_text(encoding="utf-8").splitlines()[:40]
            contenido = "\n".join(lineas)
            fragmentos.append(f"### {ruta_relativa}\n{contenido}")
        except Exception:
            continue
    return "\n\n".join(fragmentos)

def analizar_con_claude(nombre: str, stack: str, arbol: list[str], contenido: str) -> list[dict]:
    arbol_texto = "\n".join(arbol)

    prompt = f"""Analiza todo el siguiente proyecto de software e identifica sus modulos principales.
    
    Proyecto: {nombre}
    Stack: {stack}
    
    Arbol de archivos: {arbol_texto}
    
    Contenido de archivos clave: {contenido}
    
    Devolvé ÚNICAMENTE un JSON válido con esta estructura, sin texto adicional antes ni después:
    [
      {{
        "name": "nombre_del_modulo",
        "description": "qué hace este módulo en una línea",
        "file_path": "ruta/del/archivo/principal.py"
      }}
    ]"""

    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user","content": prompt}]
    )

    texto = respuesta.content[0].text
    texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    modulos = json.loads(texto)
    return modulos

def generar_contenido_modulo(nombre: str, file_path: str, contenido_fuente: str) -> str:
    prompt = f""" Eres un asistente tecnico. Genera documentacion detallada en markdown para este modulo.

    Modulo: {nombre}
    Archivo: {file_path}

    Codigo fuente: {contenido_fuente}

    Generá un documento markdown con exactamente estas secciones:
    - Qué hace este módulo
    - Funciones o clases principales (con descripción de cada una)
    - Conexiones con otros módulos
    - Convenciones o decisiones técnicas relevantes

    Solo el markdown, sin texto adicional antes ni después.
    """
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

    return modulos