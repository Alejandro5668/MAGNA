from pathlib import Path
from typing import Callable
import anthropic
import subprocess
import os
import json
import time
import logging

OnProgreso = Callable[[str], None]

# Mínimo universal que siempre es ruido — independiente del stack
IGNORAR_UNIVERSAL = {".git", "node_modules", ".venv", "__pycache__"}

# Blocklist de extensiones que definitivamente NO son código fuente.
# Todo lo que no esté acá se considera potencialmente legible.
EXTENSIONES_NO_CODIGO = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".avif", ".bmp",
    ".ttf", ".woff", ".woff2", ".eot", ".otf",
    ".mp4", ".mp3", ".wav", ".avi", ".mov", ".webm",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".pyc",
    ".lock", ".log", ".map", ".min.js",
    ".csv", ".parquet", ".sqlite", ".db",
}

MAX_CHARS_ARCHIVO_RAIZ = 5_000
MAX_CHARS_ARCHIVO_NORMAL = 1_500
MAX_CHARS_CONTENIDO = 20_000
MAX_ARBOL_ENTRADAS = 300
MAX_REINTENTOS = 4
ESPERA_INICIAL = 60
UMBRAL_PROYECTO_ORQUESTADO = 80
UMBRAL_MODO_ARQUITECTURA = 500


def _cargar_ignorar(path: Path) -> set[str]:
    """
    Lee el .gitignore del proyecto y lo combina con el mínimo universal.
    El proyecto ya sabe qué es ruido — nosotros no.
    """
    ignorar = set(IGNORAR_UNIVERSAL)
    gitignore = path / ".gitignore"
    if not gitignore.exists():
        return ignorar
    for linea in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or linea.startswith("!"):
            continue
        nombre = linea.lstrip("/").rstrip("/")
        if "*" not in nombre and "?" not in nombre and "[" not in nombre:
            ignorar.add(nombre)
    return ignorar


def _ordenar_por_relevancia(archivos: list[str], path: Path) -> list[str]:
    """
    Archivos en la raíz y más pequeños primero.
    Los entry points y configs tienden a estar en la raíz y ser pequeños.
    """
    def clave(ruta_relativa: str) -> tuple[int, int]:
        p = Path(ruta_relativa)
        profundidad = len(p.parts)
        try:
            tamaño = (path / ruta_relativa).stat().st_size
        except OSError:
            tamaño = 999_999
        return (profundidad, tamaño)
    return sorted(archivos, key=clave)


def obtener_arbol(path: Path) -> list[str]:
    ignorar = _cargar_ignorar(path)
    archivos = []
    for archivo in path.rglob("*"):
        if archivo.is_file():
            if any(parte in ignorar for parte in archivo.parts):
                continue
            archivos.append(str(archivo.relative_to(path)))
    return sorted(archivos)


def leer_archivos_clave(path: Path, arbol: list[str]) -> str:
    candidatos = [r for r in arbol if Path(r).suffix not in EXTENSIONES_NO_CODIGO]
    ordenados = _ordenar_por_relevancia(candidatos, path)

    fragmentos = []
    total_chars = 0
    for ruta_relativa in ordenados:
        if total_chars >= MAX_CHARS_CONTENIDO:
            break
        profundidad = len(Path(ruta_relativa).parts)
        limite = MAX_CHARS_ARCHIVO_RAIZ if profundidad == 1 else MAX_CHARS_ARCHIVO_NORMAL
        try:
            texto = (path / ruta_relativa).read_text(encoding="utf-8", errors="ignore")[:limite]
            fragmento = f"### {ruta_relativa}\n{texto}"
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


def _reparar_json(texto: str) -> str:
    """
    Repara el caso más común de JSON inválido: saltos de línea literales
    dentro de strings. Recorre carácter a carácter y escapa los que aparecen
    dentro de comillas.
    """
    resultado = []
    en_string = False
    i = 0
    while i < len(texto):
        c = texto[i]
        if c == '"' and (i == 0 or texto[i - 1] != "\\"):
            en_string = not en_string
        if en_string and c == "\n":
            resultado.append("\\n")
        elif en_string and c == "\r":
            resultado.append("\\r")
        else:
            resultado.append(c)
        i += 1
    return "".join(resultado)


def _llamar_claude(prompt: str, contexto: str = "", max_tokens: int = 8192) -> tuple[str, int]:
    """
    Llama a la API de Claude y devuelve (texto, tokens_totales).
    Reintenta con backoff exponencial solo en rate limit.
    """
    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    espera = ESPERA_INICIAL
    chars = len(prompt)
    tokens_estimados = chars // 4

    for intento in range(MAX_REINTENTOS):
        try:
            respuesta = cliente.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}]
            )
            input_tokens = respuesta.usage.input_tokens
            output_tokens = respuesta.usage.output_tokens
            total = input_tokens + output_tokens
            logging.info(
                "Claude OK%s — input: %d | output: %d | total: %d tokens",
                f" [{contexto}]" if contexto else "",
                input_tokens, output_tokens, total
            )
            return respuesta.content[0].text, total
        except anthropic.RateLimitError as e:
            logging.error(
                "Rate limit%s — ~%d tokens estimados. Intento %d/%d. Esperando %ds.",
                f" [{contexto}]" if contexto else "",
                tokens_estimados, intento + 1, MAX_REINTENTOS, espera
            )
            if intento < MAX_REINTENTOS - 1:
                print(f"  Rate limit. Esperando {espera}s...")
                time.sleep(espera)
                espera *= 2
            else:
                raise


def analizar_con_claude(nombre: str, stack: str, arbol: list[str], contenido: str) -> list[dict]:
    # Limitar el árbol para evitar prompts de cientos de miles de tokens en proyectos grandes
    arbol_truncado = arbol[:MAX_ARBOL_ENTRADAS]
    sufijo = f"\n... y {len(arbol) - MAX_ARBOL_ENTRADAS} archivos más" if len(arbol) > MAX_ARBOL_ENTRADAS else ""
    arbol_texto = "\n".join(arbol_truncado) + sufijo

    prompt = f"""Analiza este proyecto de software e identifica sus módulos principales.

Proyecto: {nombre}
Stack: {stack}

Árbol de archivos:
{arbol_texto}

Contenido de archivos clave:
{contenido}

Devolvé ÚNICAMENTE un JSON válido con esta estructura, sin texto adicional:
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
        texto, _ = _llamar_claude(prompt, contexto=f"analizar_con_claude:{nombre}")
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(texto)
    except json.JSONDecodeError as e:
        logging.error("analizar_con_claude — JSON inválido para '%s': %s", nombre, e)
        raise
    except Exception as e:
        logging.error("analizar_con_claude falló para '%s': %s", nombre, e, exc_info=True)
        raise


def generar_contenido_modulo(nombre: str, file_path: str, contenido_fuente: str) -> tuple[str, int]:
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


def analizar_y_documentar(
    nombre: str, stack: str, arbol: list[str], contenido: str,
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """Una sola llamada que identifica módulos funcionales Y genera su documentación."""
    arbol_truncado = arbol[:MAX_ARBOL_ENTRADAS]
    sufijo = f"\n... y {len(arbol) - MAX_ARBOL_ENTRADAS} archivos más" if len(arbol) > MAX_ARBOL_ENTRADAS else ""
    arbol_texto = "\n".join(arbol_truncado) + sufijo

    prompt = f"""Analizá este proyecto de software. Tu tarea tiene dos partes en una sola respuesta.

Proyecto: {nombre}
Stack: {stack}

Árbol de archivos:
{arbol_texto}

Contenido de archivos clave:
{contenido}

PARTE 1: Identificá entre 6 y 12 módulos FUNCIONALES. Un módulo funcional representa
un área completa del sistema, no un archivo individual.
- BIEN: "sistema_autenticacion" (agrupa auth/, middleware/auth, hooks/useAuth)
- MAL: "Button" o "Header" (son archivos, no áreas funcionales)

PARTE 2: Para cada módulo, generá documentación técnica completa.

IMPORTANTE: el campo "documentation" debe ser un string con saltos de línea como \\n.
No uses backticks dentro de documentation.

IMPORTANTE sobre "file_path": debe ser la ruta del archivo principal del módulo
con su extensión real (.php, .js, .ts, .py, etc.), no una carpeta.
Correcto: "controllers/pagos/PagosController.php"
Incorrecto: "controllers/pagos/"

Devolvé ÚNICAMENTE este JSON, sin texto adicional:
[
  {{
    "name": "nombre_en_snake_case",
    "description": "qué hace en una línea, específico y técnico",
    "file_path": "ruta/del/archivo/principal.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Nombre\\n\\n## Qué hace\\nDescripción.\\n\\n## Funciones principales\\n- fn_a: hace X\\n\\n## Conexiones\\nUsa módulo Z.\\n\\n## Decisiones técnicas\\nSe eligió este enfoque porque..."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    try:
        texto, tokens = _llamar_claude(prompt, contexto=f"analizar_y_documentar:{nombre}", max_tokens=8192)
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            modulos = json.loads(texto)
        except json.JSONDecodeError:
            logging.warning("analizar_y_documentar — JSON con saltos de línea, intentando reparar")
            modulos = json.loads(_reparar_json(texto))
        if on_progreso:
            on_progreso(f"{len(modulos)} módulos identificados · {tokens:,} tokens")
        return modulos
    except json.JSONDecodeError as e:
        logging.error("analizar_y_documentar — JSON inválido para '%s': %s", nombre, e)
        raise
    except Exception as e:
        logging.error("analizar_y_documentar falló para '%s': %s", nombre, e, exc_info=True)
        raise


def _indexar_secuencial(
    path: Path, nombre: str, stack: str, arbol: list[str], contenido: str,
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """Flujo de respaldo: análisis + documentación en llamadas separadas."""
    modulos = analizar_con_claude(nombre, stack, arbol, contenido)
    for modulo in modulos:
        ruta_fuente = path / modulo["file_path"]
        try:
            fuente = ruta_fuente.read_text(encoding="utf-8")
        except FileNotFoundError:
            fuente = ""
        contenido_md, tokens = generar_contenido_modulo(modulo["name"], modulo["file_path"], fuente)
        modulo["content_md"] = contenido_md
        modulo["last_updated_at"] = time.time()
        if on_progreso:
            on_progreso(f"{modulo['name']} · {tokens:,} tokens")
    return modulos


def _leer_archivos_zona(archivos_zona: list[str], path: Path) -> str:
    """Lee los archivos de una zona específica para el agente de esa zona."""
    candidatos = [r for r in archivos_zona if Path(r).suffix not in EXTENSIONES_NO_CODIGO]
    ordenados = _ordenar_por_relevancia(candidatos, path)

    fragmentos = []
    total_chars = 0
    for ruta_relativa in ordenados:
        if total_chars >= 8_000:
            break
        profundidad = len(Path(ruta_relativa).parts)
        limite = MAX_CHARS_ARCHIVO_RAIZ if profundidad <= 2 else MAX_CHARS_ARCHIVO_NORMAL
        try:
            texto = (path / ruta_relativa).read_text(encoding="utf-8", errors="ignore")[:limite]
            fragmento = f"### {ruta_relativa}\n{texto}"
            total_chars += len(fragmento)
            fragmentos.append(fragmento)
        except Exception:
            continue
    return "\n\n".join(fragmentos)


def _analizar_zona(
    nombre_proyecto: str, stack: str, zona: str, archivos: list[str], path: Path,
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """Agente especializado: analiza y documenta una sola zona del proyecto."""
    arbol_zona = "\n".join(archivos[:MAX_ARBOL_ENTRADAS])
    contenido_zona = _leer_archivos_zona(archivos, path)

    prompt = f"""Sos un agente especializado en analizar la zona "{zona}" de un proyecto de software.

Proyecto: {nombre_proyecto} ({stack})
Zona: {zona}

Archivos en esta zona:
{arbol_zona}

Código fuente de los archivos principales:
{contenido_zona}

Identificá entre 2 y 4 módulos FUNCIONALES de esta zona. No archivos individuales —
áreas funcionales completas.

IMPORTANTE: el campo "documentation" debe ser un string con saltos de línea como \\n.
No uses backticks dentro de documentation.

IMPORTANTE sobre "file_path": ruta del archivo principal con extensión real (.php, .js, etc.).
Correcto: "controllers/pagos/PagosController.php"
Incorrecto: "controllers/pagos/"

Devolvé ÚNICAMENTE este JSON:
[
  {{
    "name": "nombre_en_snake_case",
    "description": "qué hace en una línea",
    "file_path": "ruta/del/archivo/principal.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Nombre\\n\\n## Qué hace\\n...\\n\\n## Funciones principales\\n...\\n\\n## Conexiones\\n...\\n\\n## Decisiones técnicas\\n..."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    try:
        texto, tokens = _llamar_claude(prompt, contexto=f"zona:{zona}", max_tokens=6000)
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            modulos = json.loads(texto)
        except json.JSONDecodeError:
            modulos = json.loads(_reparar_json(texto))
        if on_progreso:
            on_progreso(f"Zona {zona} → {len(modulos)} módulos · {tokens:,} tokens")
        return modulos
    except Exception as e:
        logging.error("_analizar_zona falló para zona '%s': %s", zona, e, exc_info=True)
        return []


def indexar_proyecto_orquestado(
    path: Path, nombre: str, stack: str, arbol: list[str],
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """
    Para proyectos grandes (>80 archivos de código): detecta zonas con Claude
    y lanza un agente por zona en paralelo.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from aicli.services.zone_detector import detectar_zonas

    zonas = detectar_zonas(path, stack, arbol, on_progreso)
    if not zonas:
        logging.warning("No se detectaron zonas, usando flujo simple")
        contenido = leer_archivos_clave(path, arbol)
        return _indexar_secuencial(path, nombre, stack, arbol, contenido, on_progreso)

    todos_los_modulos: list[dict] = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_analizar_zona, nombre, stack, zona, archivos, path, on_progreso): zona
            for zona, archivos in zonas.items()
        }
        for future in as_completed(futures):
            zona = futures[future]
            try:
                modulos_zona = future.result()
                for m in modulos_zona:
                    m["content_md"] = m.pop("documentation", "")
                    m["last_updated_at"] = time.time()
                todos_los_modulos.extend(modulos_zona)
            except Exception as e:
                logging.error("Error consolidando zona '%s': %s", zona, e)

    return todos_los_modulos


def indexar_arbol(
    path: Path, nombre: str, stack: str, arbol: list[str],
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """Indexa un conjunto de archivos dado. Punto central para todos los modos de init."""
    contenido = leer_archivos_clave(path, arbol)
    archivos_codigo = [f for f in arbol if Path(f).suffix not in EXTENSIONES_NO_CODIGO]

    if len(archivos_codigo) > UMBRAL_PROYECTO_ORQUESTADO:
        return indexar_proyecto_orquestado(path, nombre, stack, arbol, on_progreso)

    try:
        modulos = analizar_y_documentar(nombre, stack, arbol, contenido, on_progreso)
        for modulo in modulos:
            modulo["content_md"] = modulo.pop("documentation")
            modulo["last_updated_at"] = time.time()
        return modulos
    except (json.JSONDecodeError, KeyError) as e:
        logging.warning("analizar_y_documentar no recuperable (%s), usando flujo de respaldo", e)
        return _indexar_secuencial(path, nombre, stack, arbol, contenido, on_progreso)


def indexar_proyecto(
    path: Path, nombre: str, stack: str,
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    arbol = obtener_arbol(path)
    return indexar_arbol(path, nombre, stack, arbol, on_progreso)


def obtener_arbol_zona(path: Path, zona: str) -> list[str]:
    """
    Devuelve el árbol de archivos de una zona específica.
    Acepta ruta relativa ('controllers/pagos') o nombre de carpeta ('pagos').
    """
    ignorar = _cargar_ignorar(path)

    zona_path = path / zona
    if not zona_path.is_dir():
        matches = sorted(
            [d for d in path.rglob(zona) if d.is_dir()],
            key=lambda d: len(d.parts)
        )
        if not matches:
            raise ValueError(f"No se encontró la carpeta '{zona}' en el proyecto")
        zona_path = matches[0]

    archivos = []
    for archivo in zona_path.rglob("*"):
        if archivo.is_file():
            if any(parte in ignorar for parte in archivo.parts):
                continue
            archivos.append(str(archivo.relative_to(path)))
    return sorted(archivos)


def obtener_archivos_recientes(path: Path, dias: int) -> list[str]:
    """
    Devuelve archivos de código modificados en los últimos N días usando git log.
    Retorna lista vacía si el directorio no es un repo git.
    """
    try:
        resultado = subprocess.run(
            ["git", "log", f"--since={dias} days ago",
             "--name-only", "--pretty=format:", "--diff-filter=AM"],
            cwd=str(path), capture_output=True, text=True, timeout=30
        )
        if resultado.returncode != 0:
            return []
        archivos = set()
        for linea in resultado.stdout.splitlines():
            linea = linea.strip()
            if not linea:
                continue
            if Path(linea).suffix not in EXTENSIONES_NO_CODIGO and (path / linea).exists():
                archivos.add(linea)
        return sorted(archivos)
    except Exception as e:
        logging.error("obtener_archivos_recientes falló: %s", e)
        return []


def documentar_arquitectura(
    path: Path, nombre: str, stack: str, arbol: list[str],
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """
    Detecta los módulos reales del proyecto leyendo código de cada carpeta de nivel 1.
    Sigue el patrón modulo/archivo.php — discrimina módulos de infraestructura/config.
    """
    ignorar = _cargar_ignorar(path)

    # Detectar carpetas de nivel 1 que tienen archivos de código directamente adentro.
    # Identifica el patrón modulo/archivo.php sin asumir nombres fijos.
    candidatos: list[dict] = []
    for item in sorted(path.iterdir()):
        if not item.is_dir() or item.name in ignorar:
            continue
        todos = [f for f in item.iterdir()
                 if f.is_file() and f.suffix not in EXTENSIONES_NO_CODIGO]
        if not todos:
            continue

        # Priorizar archivos cuyo nombre contiene el nombre de la carpeta (el archivo central del módulo)
        # Ej: en pagos/ → PagosController.php, PagosModel.php antes que helpers.php
        nombre_carpeta = item.name.lower()
        archivos_directos = sorted(
            todos,
            key=lambda f: (0 if nombre_carpeta in f.stem.lower() else 1, f.stat().st_size)
        )

        # 500 chars por archivo es suficiente para ver clase, imports y primer método
        # Mantiene los tokens bien por debajo del rate limit incluso con 100+ carpetas
        muestras = []
        for af in archivos_directos[:2]:
            try:
                contenido = af.read_text(encoding="utf-8", errors="ignore")[:500]
                muestras.append(f"### {af.relative_to(path)}\n{contenido}")
            except Exception:
                continue

        candidatos.append({
            "carpeta": item.name,
            "n_archivos": len(archivos_directos),
            "archivos": [str(f.relative_to(path)) for f in archivos_directos[:6]],
            "muestra": "\n\n".join(muestras),
        })

    if not candidatos:
        raiz = [f for f in arbol if len(Path(f).parts) == 1]
        candidatos = [{"carpeta": "raiz", "n_archivos": len(raiz),
                       "archivos": raiz[:6], "muestra": leer_archivos_clave(path, raiz)}]

    resumen = "\n".join([
        f"- {c['carpeta']}/  ({c['n_archivos']} archivos directos): "
        f"{', '.join(c['archivos'][:4])}"
        for c in candidatos
    ])

    muestras_codigo = "\n\n---\n\n".join([
        f"## {c['carpeta']}/\n{c['muestra']}"
        for c in candidatos[:20]
    ])

    prompt = f"""Analizá este proyecto y documentá sus módulos de negocio reales.

Proyecto: {nombre}  |  Stack: {stack}

El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser
un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).

Carpetas con archivos de código directamente adentro:
{resumen}

Código real de cada carpeta (archivos principales):
{muestras_codigo}

Tu tarea:
1. Identificá cuáles son MÓDULOS DE NEGOCIO reales. Descartá carpetas que sean
   configuración, assets, helpers genéricos, librerías externas, rutas de framework.
2. Documentá cada módulo real basándote en el código que ves, no en suposiciones.
3. "file_path" debe ser el archivo principal del módulo con extensión real.
   Correcto: "pagos/PagosController.php"  |  Incorrecto: "pagos/"

IMPORTANTE: "documentation" usa \\n para saltos de línea. Sin backticks adentro.

Devolvé ÚNICAMENTE este JSON:
[
  {{
    "name": "nombre_snake_case",
    "description": "qué hace este módulo en una línea, basado en el código visto",
    "file_path": "modulo/ArchivoMain.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Módulo\\n\\n## Qué hace\\nBasado en el código real.\\n\\n## Archivos principales\\nLista con descripción de cada archivo visto.\\n\\n## Conexiones con otros módulos\\nQué usa o qué lo usa.\\n\\n## Decisiones técnicas\\nPatrones observados en el código."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    try:
        texto, tokens = _llamar_claude(prompt, contexto=f"arquitectura:{nombre}", max_tokens=6000)
        texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            modulos = json.loads(texto)
        except json.JSONDecodeError:
            modulos = json.loads(_reparar_json(texto))
        if on_progreso:
            on_progreso(f"{len(modulos)} módulos identificados · {tokens:,} tokens")
        return modulos
    except Exception as e:
        logging.error("documentar_arquitectura falló para '%s': %s", nombre, e, exc_info=True)
        raise
