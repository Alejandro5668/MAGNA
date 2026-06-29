from pathlib import Path
from typing import Callable
import anthropic
import subprocess
import os
import json
import time
import logging


# Mínimo universal que siempre es ruido — independiente del stack
IGNORE_UNIVERSAL = {".git", "node_modules", ".venv", "__pycache__"}

# Blocklist de extensiones que definitivamente NO son código fuente.
# Todo lo que no esté acá se considera potencialmente legible.
NON_CODE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif", ".bmp",
    ".ttf", ".woff", ".woff2", ".eot", ".otf",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc",
    ".lock", ".log", ".map", ".min.js",
    ".csv", ".parquet", ".sqlite", ".db",
}

MAX_CHARS_ROOT_FILE = 5_000
MAX_CHARS_NORMAL_FILE = 1_500
MAX_CHARS_CONTENT = 20_000
MAX_TREE_ENTRIES = 300
MAX_RETRIES = 4
INITIAL_WAIT = 60


def _load_ignore(path: Path) -> set[str]:
    """
    Lee el .gitignore del proyecto y lo combina con el mínimo universal.
    El proyecto ya sabe qué es ruido — nosotros no.
    """
    ignored = set(IGNORE_UNIVERSAL)

    gitignore = path / ".gitignore"
    if not gitignore.exists():
        return ignored
    for line in gitignore.read_text(encoding="latin-1").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("!"):
            continue
        name = line.lstrip("/").rstrip("/")
        if "*" not in name and "?" not in name and "[" not in name:
            ignored.add(name)
    return ignored


def _sort_by_relevance(files: list[str], path: Path) -> list[str]:
    """
    Archivos en la raíz y más pequeños primero.
    Los entry points y configs tienden a estar en la raíz y ser pequeños.
    """
    def key(relative_path: str) -> tuple[int, int]:
        p = Path(relative_path)
        depth = len(p.parts)
        try:
            size = (path / relative_path).stat().st_size
        except OSError:
            size = 999_999
        return (depth, size)
    return sorted(files, key=key)


def get_tree(path: Path) -> list[str]:
    ignored = _load_ignore(path)
    files = []
    for file in path.rglob("*"):
        if file.is_file():
            if any(part in ignored for part in file.parts):
                continue
            files.append(str(file.relative_to(path)))
    return sorted(files)


def read_key_files(path: Path, tree: list[str]) -> str:
    candidates = [r for r in tree if Path(r).suffix not in NON_CODE_EXTENSIONS]
    sorted_files = _sort_by_relevance(candidates, path)

    fragments = []
    total_chars = 0
    for relative_path in sorted_files:
        if total_chars >= MAX_CHARS_CONTENT:
            break
        depth = len(Path(relative_path).parts)
        limit = MAX_CHARS_ROOT_FILE if depth == 1 else MAX_CHARS_NORMAL_FILE
        try:
            text = (path / relative_path).read_text(encoding="latin-1")[:limit]
            fragment = f"### {relative_path}\n{text}"
            total_chars += len(fragment)
            fragments.append(fragment)
        except Exception:
            continue
    return "\n\n".join(fragments)


def module_needs_update(file_path: str, project_path: Path, existing_module) -> bool:
    if existing_module is None or existing_module.last_updated_at is None:
        return True
    file = project_path / file_path
    if not file.exists():
        return False
    return os.path.getmtime(file) > existing_module.last_updated_at


def _reparar_json(text: str) -> str:
    """
    Repara el caso más común de JSON inválido: saltos de línea literales
    dentro de strings. Recorre carácter a carácter y escapa los que aparecen
    dentro de comillas.
    """
    result = []
    in_string = False
    i = 0
    while i < len(text):
        c = text[i]
        if c == '"' and (i == 0 or text[i - 1] != "\\"):
            in_string = not in_string
        if in_string and c == "\n":
            result.append("\\n")
        elif in_string and c == "\r":
            result.append("\\r")
        else:
            result.append(c)
        i += 1
    return "".join(result)


def _call_claude(prompt: str, context: str = "", max_tokens: int = 8192) -> tuple[str, int]:
    """
    Llama a la API de Claude y devuelve (texto, tokens_totales).
    Reintenta con backoff exponencial solo en rate limit.
    """
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    wait = INITIAL_WAIT
    chars = len(prompt)
    estimated_tokens = chars // 4

    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total = input_tokens + output_tokens
            logging.info(
                "Claude OK%s — input: %d | output: %d | total: %d tokens",
                f" [{context}]" if context else "",
                input_tokens, output_tokens, total
            )
            return response.content[0].text, total
        except anthropic.RateLimitError as e:
            logging.error(
                "Rate limit%s — ~%d tokens estimados. Intento %d/%d. Esperando %ds.",
                f" [{context}]" if context else "",
                estimated_tokens, attempt + 1, MAX_RETRIES, wait
            )
            if attempt < MAX_RETRIES - 1:
                print(f"  Rate limit. Esperando {wait}s...")
                time.sleep(wait)
                wait *= 2
            else:
                raise




def generate_module_content(name: str, file_path: str, source_content: str) -> tuple[str, int]:
    prompt = f"""Eres un asistente técnico. Genera documentación detallada en markdown para este módulo.

Módulo: {name}
Archivo: {file_path}

Código fuente:
{source_content}

Generá un documento markdown con exactamente estas secciones:
- Qué hace este módulo
- Funciones o clases principales (con descripción de cada una)
- Conexiones con otros módulos
- Convenciones o decisiones técnicas relevantes

Solo el markdown, sin texto adicional antes ni después."""

    try:
        return _call_claude(prompt, context=f"generar_contenido:{name}")
    except Exception as e:
        logging.error("generate_module_content failed for '%s' (%s): %s", name, file_path, e, exc_info=True)
        raise


def generate_case_summary(
    task: str,
    diff: str,
    files: list[str],
    previous_history: str = "",
) -> tuple[str, dict, int]:
    """
    Genera en una sola llamada: mensaje Jira + memoria del caso.
    Si previous_history tiene contenido, el mensaje Jira documenta solo esta ronda.
    Devuelve (jira_msg, memoria_dict, tokens).
    """
    files_str = "\n".join(f"- {a}" for a in files)

    round_context = (
        f"\nHistorial de rondas anteriores:\n{previous_history}\n"
        "Esta es una ronda de seguimiento. El mensaje Jira debe documentar SOLO los cambios "
        "de esta ronda, no repetir lo que ya esta en el historial.\n"
    ) if previous_history else ""

    prompt = f"""Sos un desarrollador senior cerrando un ticket de trabajo.
{round_context}
Tarea resuelta: {task}

Archivos modificados:
{files_str}

Cambios aplicados (git diff):
{diff[:5000]}

Genera un JSON con exactamente estas claves, sin texto adicional antes ni despues:

{{
  "jira": "mensaje para pegar en Jira. Formato: '🌱 Causa Raiz: [origen tecnico, archivo:linea o tabla:campo]\\n🛠️ Solucion Aplicada: [cambios concretos, maximo 4 puntos]'. SOLO ASCII puro sin tildes. Maximo 6 lineas totales.",
  "investigado": "que causa genero el problema — especifico con archivo/funcion/tabla si aplica — maximo 2 oraciones",
  "hecho": "que cambios se aplicaron exactamente — archivos y funciones modificadas — maximo 2 oraciones",
  "tener_en_cuenta": "gotchas, restricciones no obvias, edge cases a considerar en el futuro — maximo 2 oraciones"
}}"""

    text, tokens = _call_claude(prompt, context="resumen-caso", max_tokens=800)
    try:
        clean = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(clean)
        case_memory = {
            "investigado": data.get("investigado", ""),
            "hecho": data.get("hecho", ""),
            "tener_en_cuenta": data.get("tener_en_cuenta", ""),
        }
        return data.get("jira", ""), case_memory, tokens
    except Exception:
        return text, {"investigado": "", "hecho": "", "tener_en_cuenta": ""}, tokens


def describe_image(image_path: str) -> tuple[str, int]:
    """
    Envía una imagen a Claude con visión y devuelve (descripción_técnica, tokens).
    Soporta PNG, JPG, WEBP, GIF.
    """
    import base64

    TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}

    path = Path(image_path)
    media_type = TIPOS.get(path.suffix.lower())
    if not media_type:
        raise ValueError(f"Formato no soportado: {path.suffix}. Usá PNG, JPG, WEBP o GIF.")

    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                },
                {
                    "type": "text",
                    "text": (
                        "Describí esta imagen con precisión técnica para un desarrollador.\n"
                        "Si es una interfaz web o app: identificá elementos visibles, mensajes de error, "
                        "texto en pantalla, comportamiento observable, clases CSS o IDs visibles.\n"
                        "Si es un diagrama o esquema: describí la estructura y relaciones.\n"
                        "Si es un bug visual: describí exactamente qué está mal y dónde.\n"
                        "Sé específico. No uses frases genéricas."
                    ),
                },
            ],
        }],
    )
    tokens = response.usage.input_tokens + response.usage.output_tokens
    logging.info("describe_image — %s · %d tokens", path.name, tokens)
    return response.content[0].text.strip(), tokens


def analyze_file_deep(
    path: Path,
    file_path: str,
    project_name: str,
    stack: str,
    diff: str = "",
    existing_doc: str = "",
) -> tuple[str, int]:
    """
    Genera o actualiza documentación de un archivo individual.
    Lee hasta 8000 chars. Si recibe diff y existing_doc, hace actualización incremental.
    """
    source_file = path / file_path
    try:
        content = source_file.read_text(encoding="latin-1")[:8000]
    except FileNotFoundError:
        content = ""

    name = Path(file_path).stem
    sections = (
        "- Qué hace este archivo (propósito y rol en el sistema)\n"
        "- Funciones y clases principales (nombre, parámetros y qué hace cada una)\n"
        "- Queries SQL y tablas involucradas (nombres exactos del código, si aplica)\n"
        "- Dependencias (qué otros archivos o módulos usa directamente)\n"
        "- Patrones y convenciones observados"
    )

    if existing_doc and diff:
        prompt = f"""Actualizá la documentación técnica de este archivo incorporando los cambios recientes.

Proyecto: {project_name} | Stack: {stack}
Archivo: {file_path}

Documentación actual:
{existing_doc}

Cambios aplicados (git diff):
{diff[:4000]}

Código fuente actualizado:
{content}

Conservá todo el conocimiento previo que siga siendo válido.
Actualizá las secciones afectadas por el diff: nuevas funciones, queries modificadas, dependencias cambiadas.
Eliminá referencias a código que el diff borra.

Generá el documento markdown completo con exactamente estas secciones:
{sections}

Solo el markdown, sin texto adicional antes ni después."""

    elif diff:
        prompt = f"""Generá documentación técnica para este archivo. El diff muestra los cambios de la sesión actual.

Proyecto: {project_name} | Stack: {stack}
Archivo: {file_path}

Cambios de esta sesión (git diff):
{diff[:4000]}

Código fuente:
{content}

Generá un documento markdown con exactamente estas secciones:
{sections}

Solo el markdown, sin texto adicional antes ni después."""

    else:
        prompt = f"""Generá documentación técnica detallada para este archivo.

Proyecto: {project_name} | Stack: {stack}
Archivo: {file_path}

Código fuente:
{content}

Generá un documento markdown con exactamente estas secciones:
{sections}

Solo el markdown, sin texto adicional antes ni después."""

    return _call_claude(prompt, context=f"archivo:{name}", max_tokens=4000)


def document_zone(
    path: Path, zone_path: Path, stack: str,
    on_progreso: Callable[[str], None] | None = None
) -> list[dict]:
    """
    Documenta en profundidad una zona/carpeta específica.
    Lee 1000 chars de los 5 archivos más relevantes de la zona.
    """
    ignored = _load_ignore(path)

    files = [
        af for af in zone_path.rglob("*")
        if af.is_file()
        and af.suffix not in NON_CODE_EXTENSIONS
        and not any(p in ignored for p in af.parts)
    ]

    if not files:
        return []

    zone_name = zone_path.name.lower()
    sorted_files = sorted(
        files,
        key=lambda f: (0 if zone_name in f.stem.lower() else 1, -f.stat().st_size)
    )

    tree = [str(af.relative_to(path)) for af in sorted_files]
    tree_text = "\n".join(tree[:MAX_TREE_ENTRIES])

    samples = []
    for af in sorted_files[:5]:
        try:
            content = af.read_text(encoding="latin-1")[:1000]
            samples.append(f"### {af.relative_to(path)}\n{content}")
        except Exception:
            continue

    samples_text = "\n\n---\n\n".join(samples)
    zone_display = zone_path.name

    prompt = f"""Analizá esta zona del proyecto y documentá cada componente relevante.

Stack: {stack}
Zona: {zone_display}/

Archivos en esta zona:
{tree_text}

Código real de los archivos principales:
{samples_text}

Tu tarea:
1. Identificá los componentes funcionales reales (controllers, models, helpers, etc.).
2. Documentá cada componente basándote en el código que ves, no en suposiciones.
3. "file_path" debe ser la ruta relativa al proyecto con extensión real.
   Correcto: "{zone_display}/PagosController.php"
4. Máximo 8 componentes. Si hay más, priorizá los de mayor relevancia funcional.

IMPORTANTE: "documentation" usa \\n para saltos de línea. Sin backticks adentro.
Cada sección de "documentation" debe ser concisa — 2 a 4 líneas por sección.

Devolvé ÚNICAMENTE este JSON:
[
  {{
    "name": "nombre_snake_case",
    "description": "qué hace este componente en una línea, basado en el código",
    "file_path": "{zone_display}/ArchivoReal.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Componente\\n\\n## Qué hace\\nBasado en el código real.\\n\\n## Funciones principales\\nNombre y descripción breve de cada función pública.\\n\\n## Queries SQL\\nTablas observadas (nombres exactos).\\n\\n## Dependencias\\nArchivos o módulos que usa directamente."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    text, tokens = _call_claude(prompt, context=f"zona:{zone_display}", max_tokens=8192)
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        modules = json.loads(text)
    except json.JSONDecodeError:
        logging.warning("document_zone — JSON con saltos de línea, intentando reparar")
        modules = json.loads(_reparar_json(text))

    if on_progreso:
        on_progreso(f"{len(modules)} componentes documentados · {tokens:,} tokens")

    return modules




def get_zone_tree(path: Path, zone: str) -> list[str]:
    """
    Devuelve el árbol de archivos de una zona específica.
    Acepta ruta relativa ('controllers/pagos') o nombre de carpeta ('pagos').
    """
    ignored = _load_ignore(path)

    zone_path = path / zone
    if not zone_path.is_dir():
        matches = sorted(
            [d for d in path.rglob(zone) if d.is_dir()],
            key=lambda d: len(d.parts)
        )
        if not matches:
            raise ValueError(f"No se encontró la carpeta '{zone}' en el proyecto")
        zone_path = matches[0]

    files = []
    for file in zone_path.rglob("*"):
        if file.is_file():
            if any(part in ignored for part in file.parts):
                continue
            files.append(str(file.relative_to(path)))
    return sorted(files)


def get_recent_files(path: Path, days: int) -> list[str]:
    """
    Devuelve archivos de código modificados en los últimos N días usando git log.
    Retorna lista vacía si el directorio no es un repo git.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"--since={dias} days ago",
             "--name-only", "--pretty=format:", "--diff-filter=AM"],
            cwd=str(path), capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return []
        files = set()
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if Path(line).suffix not in NON_CODE_EXTENSIONS and (path / line).exists():
                files.add(line)
        return sorted(files)
    except Exception as e:
        logging.error("get_recent_files failed: %s", e)
        return []


def _read_pattern_sample(path: Path, tree: list[str], pattern: str, max_chars: int) -> str:
    """Lee el primer archivo del árbol que contenga el patrón en su ruta."""
    for file_path in tree:
        if pattern in file_path and Path(file_path).suffix not in NON_CODE_EXTENSIONS:
            try:
                content = (path / file_path).read_text(encoding="latin-1")[:max_chars]
                return f"### {file_path}\n{content}"
            except Exception:
                continue
    return ""


def generate_project_md(
    path: Path, name: str, stack: str, tree: list[str],
    modules: list[dict],
    on_progreso: Callable[[str], None] | None = None
) -> tuple[str, int]:
    """
    Genera PROYECTO.md con conocimiento estructural inferido del código.
    Usa árbol + módulos documentados + muestras de archivos clave.
    Secciones que requieren conocimiento humano quedan como 'pendiente'.
    """
    tree_text = "\n".join(tree[:MAX_TREE_ENTRIES])

    modules_text = "\n".join([
        f"- {m['name']} ({m['file_path']}): {m['description']}"
        for m in modules[:30]
    ])

    querys_sample = _read_pattern_sample(path, tree, "_querys", 2000)
    conf_sample = _read_pattern_sample(path, tree, "conf/", 1000)

    pendiente = "> pendiente — enriquecé esta sección con tu conocimiento del proyecto"

    prompt = f"""Analizá este proyecto de software y generá un documento PROYECTO.md con conocimiento estructural.

Proyecto: {name} | Stack: {stack}

Árbol de archivos:
{tree_text}

Módulos de negocio ya identificados:
{modules_text}

{f"Muestra de código SQL:{chr(10)}{querys_sample}" if querys_sample else ""}

{f"Muestra de infraestructura:{chr(10)}{conf_sample}" if conf_sample else ""}

Generá el siguiente documento markdown completando cada sección.
REGLA: Si podés inferirlo del código o el árbol → escribilo con precisión y ejemplos reales.
Si NO podés inferirlo (requiere conocimiento humano acumulado) → escribí exactamente esta línea:
{pendiente}

Generá SOLO el contenido del archivo, sin introducción ni texto adicional:

---

# PROYECTO.md — Conocimiento del proyecto para AICLI

## 1. Identidad del proyecto
- **Nombre**: {name}
- **Stack exacto** (versión PHP, motor de templates si tiene, frontend):
- **Base de datos**: motor, tablas más importantes del núcleo transversal:
- **Multi-tenant**: columna que filtra por empresa, variable de sesión, ejemplo real de una query:

## 2. Estructura de carpetas — módulos de negocio vs. infraestructura

(Clasificá TODAS las carpetas de nivel 1 visibles en el árbol)

| Carpeta | Tipo | Descripción |
|---------|------|-------------|
| ... | módulo_negocio / infraestructura / vendor / assets / utilidad | ... |

## 3. Convenciones de archivos — patrón real del proyecto

(Inferí desde el árbol: qué sufijos de archivo existen, qué hace cada uno)

- `{{prefijo}}_querys.php` →
- `{{prefijo}}_lista.php` →
- `{{prefijo}}_ejecutar.php` →
- (agregá todos los patrones que veas)

## 4. Patrón SQL exacto

(Usá la muestra de *_querys.php para describir el patrón real)

```php
[ejemplo real del $querys[] que viste]
```

Helper que ejecuta las queries y sus métodos principales:
Filtros siempre presentes (multi-tenant, activo, etc.):

## 5. Módulos de negocio principales

(Usá los módulos ya documentados)

| Carpeta | Qué hace | Archivo principal | Conecta con |
|---------|----------|-------------------|-------------|

## 6. Flujos críticos

{pendiente}

## 7. Reglas y restricciones no obvias

{pendiente}

## 8. Carpetas que JAMÁS son módulos de negocio

(Inferí desde el árbol: vendor, assets, libs, infraestructura)

```
[lista de carpetas a ignorar]
```

## 9. Señales para detectar el archivo principal de un módulo

(Inferí desde las convenciones de nombres que viste)

## 10. Decisiones técnicas acumuladas

{pendiente}"""

    if on_progreso:
        on_progreso("Generando PROYECTO.md...")

    text, tokens = _call_claude(prompt, context="generar_proyecto_md", max_tokens=8000)
    return text.strip(), tokens


def document_architecture(
    path: Path, name: str, stack: str, tree: list[str],
    on_progreso: Callable[[str], None] | None = None
) -> list[dict]:
    """
    Detecta los módulos reales del proyecto leyendo código de cada carpeta de nivel 1.
    Sigue el patrón modulo/archivo.php — discrimina módulos de infraestructura/config.
    """
    ignored = _load_ignore(path)

    # Detectar carpetas de nivel 1 que tienen archivos de código directamente adentro.
    # Identifica el patrón modulo/archivo.php sin asumir nombres fijos.
    candidates: list[dict] = []
    for item in sorted(path.iterdir()):
        if not item.is_dir() or item.name in ignored:
            continue
        all_files = [f for f in item.iterdir()
                     if f.is_file() and f.suffix not in NON_CODE_EXTENSIONS]
        if not all_files:
            continue

        # Priorizar archivos cuyo nombre contiene el nombre de la carpeta (el archivo central del módulo)
        # Ej: en pagos/ → PagosController.php, PagosModel.php antes que helpers.php
        folder_name = item.name.lower()
        direct_files = sorted(
            all_files,
            key=lambda f: (0 if folder_name in f.stem.lower() else 1, f.stat().st_size)
        )

        # 500 chars por archivo es suficiente para ver clase, imports y primer método
        # Mantiene los tokens bien por debajo del rate limit incluso con 100+ carpetas
        samples = []
        for af in direct_files[:2]:
            try:
                content = af.read_text(encoding="latin-1")[:500]
                samples.append(f"### {af.relative_to(path)}\n{content}")
            except Exception:
                continue

        candidates.append({
            "carpeta": item.name,
            "n_archivos": len(direct_files),
            "archivos": [str(f.relative_to(path)) for f in direct_files[:6]],
            "muestra": "\n\n".join(samples),
        })

    if not candidates:
        root = [f for f in tree if len(Path(f).parts) == 1]
        candidates = [{"carpeta": "raiz", "n_archivos": len(root),
                       "archivos": root[:6], "muestra": leer_archivos_clave(path, root)}]

    # Limitar a 15 candidatos para mantener el output dentro de 8000 tokens
    # En proyectos grandes (>15 carpetas) se priorizan las que tienen más archivos
    top_candidates = sorted(candidates, key=lambda c: c["n_archivos"], reverse=True)[:15]

    summary = "\n".join([
        f"- {c['carpeta']}/  ({c['n_archivos']} archivos directos): "
        f"{', '.join(c['archivos'][:4])}"
        for c in top_candidates
    ])

    code_samples = "\n\n---\n\n".join([
        f"## {c['carpeta']}/\n{c['muestra']}"
        for c in top_candidates
    ])

    prompt = f"""Analizá este proyecto y documentá sus módulos de negocio reales.

Proyecto: {name}  |  Stack: {stack}

El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser
un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).

Carpetas con archivos de código directamente adentro (las {len(top_candidates)} con más archivos):
{summary}

Código real de cada carpeta (archivos principales):
{code_samples}

Tu tarea:
1. Identificá cuáles son MÓDULOS DE NEGOCIO reales. Descartá carpetas que sean
   configuración, assets, helpers genéricos, librerías externas, rutas de framework.
2. Documentá cada módulo real basándote en el código que ves, no en suposiciones.
3. "file_path" debe ser el archivo principal del módulo con extensión real.
   Correcto: "pagos/PagosController.php"  |  Incorrecto: "pagos/"
4. Máximo 15 módulos. Si hay más, priorizá los de mayor relevancia de negocio.

IMPORTANTE: "documentation" usa \\n para saltos de línea. Sin backticks adentro.
Mantené "documentation" concisa: máximo 3 secciones cortas.

Devolvé ÚNICAMENTE este JSON:
[
  {{
    "name": "nombre_snake_case",
    "description": "qué hace este módulo en una línea, basado en el código visto",
    "file_path": "modulo/ArchivoMain.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Módulo\\n\\n## Qué hace\\nDescripción basada en el código real.\\n\\n## Archivos principales\\nLista de archivos vistos con descripción breve.\\n\\n## Dependencias clave\\nQué usa o qué lo usa."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    try:
        text, tokens = _call_claude(prompt, context=f"arquitectura:{name}", max_tokens=8000)
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            modules = json.loads(text)
        except json.JSONDecodeError:
            modules = json.loads(_reparar_json(text))
        if on_progreso:
            on_progreso(f"{len(modules)} módulos identificados · {tokens:,} tokens")
        return modules
    except Exception as e:
        logging.error("document_architecture falló para '%s': %s", name, e, exc_info=True)
        raise
