from pathlib import Path
import anthropic
import os
import json
import time
import logging

IGNORAR = {
    # Control de versiones y editores
    ".git", ".idea", ".vscode",
    # Dependencias
    "node_modules", ".venv", "vendor",
    # Builds y output generado — estos son los que inflan el árbol
    ".next", "out", "dist", "build", ".turbo", ".cache", ".parcel-cache",
    "coverage", ".nyc_output", "__pycache__", ".pytest_cache",
    # Archivos sueltos a ignorar
    ".gitignore", ".env.example",
}

ARCHIVOS_PRIORITARIOS = {
    # Python
    "main.py", "app.py", "requirements.txt", "pyproject.toml",
    # JavaScript / TypeScript / Next.js
    "index.js", "index.ts", "index.tsx",
    "package.json", "tsconfig.json", "next.config.js", "next.config.ts",
    "tailwind.config.js", "tailwind.config.ts",
    # Java / Kotlin
    "pom.xml", "build.gradle", "build.gradle.kts",
    # PHP / Laravel
    "composer.json",
    # Docs
    "README.md", "README.rst", "CLAUDE.md",
}

EXTENSIONES_CODIGO = {
    ".py",                        # Python
    ".js", ".jsx", ".ts", ".tsx", # JavaScript / TypeScript
    ".java",                       # Java
    ".php",                        # PHP / Laravel
    ".go",                         # Go
    ".rs",                         # Rust
    ".rb",                         # Ruby
    ".kt",                         # Kotlin
    ".cs",                         # C#
}

MAX_CHARS_CONTENIDO = 12_000
MAX_REINTENTOS = 3
ESPERA_INICIAL = 30


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
    total_chars = 0
    for ruta_relativa in seleccionados:
        if total_chars >= MAX_CHARS_CONTENIDO:
            break
        ruta_completa = path / ruta_relativa
        try:
            lineas = ruta_completa.read_text(encoding="utf-8").splitlines()[:30]
            fragmento = f"### {ruta_relativa}\n" + "\n".join(lineas)
            total_chars += len(fragmento)
            fragmentos.append(fragmento)
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


def _llamar_claude(prompt: str, contexto: str = "") -> str:
    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    espera = ESPERA_INICIAL
    chars = len(prompt)
    tokens_estimados = chars // 4

    for intento in range(MAX_REINTENTOS):
        try:
            respuesta = cliente.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}]
            )
            input_tokens = respuesta.usage.input_tokens
            output_tokens = respuesta.usage.output_tokens
            logging.info(
                "Claude OK%s — input: %d tokens | output: %d tokens | total: %d tokens",
                f" [{contexto}]" if contexto else "",
                input_tokens, output_tokens, input_tokens + output_tokens
            )
            return respuesta.content[0].text
        except anthropic.RateLimitError as e:
            logging.error(
                "Rate limit alcanzado%s — prompt: %d caracteres (~%d tokens estimados, límite: 30,000/min). "
                "Intento %d/%d. Error: %s",
                f" [{contexto}]" if contexto else "",
                chars, tokens_estimados, intento + 1, MAX_REINTENTOS, e
            )
            if intento < MAX_REINTENTOS - 1:
                print(f"  Rate limit alcanzado. Prompt: ~{tokens_estimados:,} tokens estimados. Esperando {espera}s antes de reintentar...")
                time.sleep(espera)
                espera *= 2
            else:
                raise


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

    try:
        texto = _llamar_claude(prompt, contexto=f"analizar_con_claude:{nombre}")
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(texto)
        except json.JSONDecodeError as e:
            logging.error(
                "analizar_con_claude — JSON inválido para '%s': %s\nRespuesta cruda de Claude:\n%s",
                nombre, e, texto
            )
            raise
    except anthropic.RateLimitError:
        raise
    except json.JSONDecodeError:
        raise
    except Exception as e:
        logging.error("analizar_con_claude falló para '%s': %s", nombre, e, exc_info=True)
        raise


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

    try:
        return _llamar_claude(prompt, contexto=f"generar_contenido:{nombre}")
    except Exception as e:
        logging.error("generar_contenido_modulo falló para '%s' (%s): %s", nombre, file_path, e, exc_info=True)
        raise


def indexar_proyecto(path: Path, nombre: str, stack: str) -> list[dict]:
    arbol = obtener_arbol(path)
    contenido = leer_archivos_clave(path, arbol)
    modulos = analizar_con_claude(nombre, stack, arbol, contenido)

    for i, modulo in enumerate(modulos):
        if i > 0:
            time.sleep(4)
        ruta_fuente = path / modulo["file_path"]
        try:
            fuente = ruta_fuente.read_text(encoding="utf-8")
        except FileNotFoundError:
            fuente = ""
        modulo["content_md"] = generar_contenido_modulo(modulo["name"], modulo["file_path"], fuente)
        modulo["last_updated_at"] = time.time()

    return modulos