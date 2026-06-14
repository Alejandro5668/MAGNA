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


def _cargar_ignorar(path: Path) -> set[str]:
    """
    Lee el .gitignore del proyecto y lo combina con el mínimo universal.
    El proyecto ya sabe qué es ruido — nosotros no.
    """
    ignorar = set(IGNORAR_UNIVERSAL)

    gitignore = path / ".gitignore"
    if not gitignore.exists():
        return ignorar
    for linea in gitignore.read_text(encoding="latin-1").splitlines():
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
            texto = (path / ruta_relativa).read_text(encoding="latin-1")[:limite]
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


def describir_imagen(ruta_imagen: str) -> tuple[str, int]:
    """
    Envía una imagen a Claude con visión y devuelve (descripción_técnica, tokens).
    Soporta PNG, JPG, WEBP, GIF.
    """
    import base64

    TIPOS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}

    ruta = Path(ruta_imagen)
    media_type = TIPOS.get(ruta.suffix.lower())
    if not media_type:
        raise ValueError(f"Formato no soportado: {ruta.suffix}. Usá PNG, JPG, WEBP o GIF.")

    imagen_b64 = base64.standard_b64encode(ruta.read_bytes()).decode("utf-8")

    cliente = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": imagen_b64},
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
    tokens = respuesta.usage.input_tokens + respuesta.usage.output_tokens
    logging.info("describir_imagen — %s · %d tokens", ruta.name, tokens)
    return respuesta.content[0].text.strip(), tokens


def analizar_archivo_profundo(path: Path, ruta: str, proyecto_name: str, stack: str) -> tuple[str, int]:
    """
    Genera documentación profunda de un archivo individual.
    Lee hasta 3000 chars del archivo real para contexto completo.
    """
    ruta_archivo = path / ruta
    try:
        contenido = ruta_archivo.read_text(encoding="latin-1")[:3000]
    except FileNotFoundError:
        contenido = ""

    nombre = Path(ruta).stem

    prompt = f"""Generá documentación técnica detallada para este archivo.

Proyecto: {proyecto_name} | Stack: {stack}
Archivo: {ruta}

Código fuente:
{contenido}

Generá un documento markdown con exactamente estas secciones:
- Qué hace este archivo (propósito y rol en el sistema)
- Funciones y clases principales (nombre, parámetros y qué hace cada una)
- Queries SQL y tablas involucradas (nombres exactos del código, si aplica)
- Dependencias (qué otros archivos o módulos usa directamente)
- Patrones y convenciones observados

Solo el markdown, sin texto adicional antes ni después."""

    return _llamar_claude(prompt, contexto=f"archivo:{nombre}", max_tokens=4000)


def documentar_zona(
    path: Path, zona_path: Path, stack: str,
    on_progreso: OnProgreso | None = None
) -> list[dict]:
    """
    Documenta en profundidad una zona/carpeta específica.
    Lee 1000 chars de los 5 archivos más relevantes de la zona.
    """
    ignorar = _cargar_ignorar(path)

    archivos = [
        af for af in zona_path.rglob("*")
        if af.is_file()
        and af.suffix not in EXTENSIONES_NO_CODIGO
        and not any(p in ignorar for p in af.parts)
    ]

    if not archivos:
        return []

    nombre_zona = zona_path.name.lower()
    archivos_ordenados = sorted(
        archivos,
        key=lambda f: (0 if nombre_zona in f.stem.lower() else 1, -f.stat().st_size)
    )

    arbol = [str(af.relative_to(path)) for af in archivos_ordenados]
    arbol_texto = "\n".join(arbol[:MAX_ARBOL_ENTRADAS])

    muestras = []
    for af in archivos_ordenados[:5]:
        try:
            contenido = af.read_text(encoding="latin-1")[:1000]
            muestras.append(f"### {af.relative_to(path)}\n{contenido}")
        except Exception:
            continue

    muestras_texto = "\n\n---\n\n".join(muestras)
    nombre_zona_display = zona_path.name

    prompt = f"""Analizá esta zona del proyecto y documentá cada componente relevante.

Stack: {stack}
Zona: {nombre_zona_display}/

Archivos en esta zona:
{arbol_texto}

Código real de los archivos principales:
{muestras_texto}

Tu tarea:
1. Identificá los componentes funcionales reales (controllers, models, helpers, etc.).
2. Documentá cada componente basándote en el código que ves, no en suposiciones.
3. "file_path" debe ser la ruta relativa al proyecto con extensión real.
   Correcto: "{nombre_zona_display}/PagosController.php"
4. Máximo 8 componentes. Si hay más, priorizá los de mayor relevancia funcional.

IMPORTANTE: "documentation" usa \\n para saltos de línea. Sin backticks adentro.
Cada sección de "documentation" debe ser concisa — 2 a 4 líneas por sección.

Devolvé ÚNICAMENTE este JSON:
[
  {{
    "name": "nombre_snake_case",
    "description": "qué hace este componente en una línea, basado en el código",
    "file_path": "{nombre_zona_display}/ArchivoReal.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Componente\\n\\n## Qué hace\\nBasado en el código real.\\n\\n## Funciones principales\\nNombre y descripción breve de cada función pública.\\n\\n## Queries SQL\\nTablas observadas (nombres exactos).\\n\\n## Dependencias\\nArchivos o módulos que usa directamente."
  }}
]

Valores válidos para category: backend, frontend, infraestructura, negocio."""

    texto, tokens = _llamar_claude(prompt, contexto=f"zona:{nombre_zona_display}", max_tokens=8192)
    texto = texto.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        modulos = json.loads(texto)
    except json.JSONDecodeError:
        logging.warning("documentar_zona — JSON con saltos de línea, intentando reparar")
        modulos = json.loads(_reparar_json(texto))

    if on_progreso:
        on_progreso(f"{len(modulos)} componentes documentados · {tokens:,} tokens")

    return modulos




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


def _leer_muestra_patron(path: Path, arbol: list[str], patron: str, max_chars: int) -> str:
    """Lee el primer archivo del árbol que contenga el patrón en su ruta."""
    for ruta in arbol:
        if patron in ruta and Path(ruta).suffix not in EXTENSIONES_NO_CODIGO:
            try:
                contenido = (path / ruta).read_text(encoding="latin-1")[:max_chars]
                return f"### {ruta}\n{contenido}"
            except Exception:
                continue
    return ""


def generar_proyecto_md(
    path: Path, nombre: str, stack: str, arbol: list[str],
    modulos: list[dict],
    on_progreso: OnProgreso | None = None
) -> tuple[str, int]:
    """
    Genera PROYECTO.md con conocimiento estructural inferido del código.
    Usa árbol + módulos documentados + muestras de archivos clave.
    Secciones que requieren conocimiento humano quedan como 'pendiente'.
    """
    arbol_texto = "\n".join(arbol[:MAX_ARBOL_ENTRADAS])

    modulos_texto = "\n".join([
        f"- {m['name']} ({m['file_path']}): {m['description']}"
        for m in modulos[:30]
    ])

    querys_muestra = _leer_muestra_patron(path, arbol, "_querys", 2000)
    conf_muestra = _leer_muestra_patron(path, arbol, "conf/", 1000)

    pendiente = "> pendiente — enriquecé esta sección con tu conocimiento del proyecto"

    prompt = f"""Analizá este proyecto de software y generá un documento PROYECTO.md con conocimiento estructural.

Proyecto: {nombre} | Stack: {stack}

Árbol de archivos:
{arbol_texto}

Módulos de negocio ya identificados:
{modulos_texto}

{f"Muestra de código SQL:{chr(10)}{querys_muestra}" if querys_muestra else ""}

{f"Muestra de infraestructura:{chr(10)}{conf_muestra}" if conf_muestra else ""}

Generá el siguiente documento markdown completando cada sección.
REGLA: Si podés inferirlo del código o el árbol → escribilo con precisión y ejemplos reales.
Si NO podés inferirlo (requiere conocimiento humano acumulado) → escribí exactamente esta línea:
{pendiente}

Generá SOLO el contenido del archivo, sin introducción ni texto adicional:

---

# PROYECTO.md — Conocimiento del proyecto para AICLI

## 1. Identidad del proyecto
- **Nombre**: {nombre}
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

    texto, tokens = _llamar_claude(prompt, contexto="generar_proyecto_md", max_tokens=8000)
    return texto.strip(), tokens


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
                contenido = af.read_text(encoding="latin-1")[:500]
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

    # Limitar a 15 candidatos para mantener el output dentro de 8000 tokens
    # En proyectos grandes (>15 carpetas) se priorizan las que tienen más archivos
    candidatos_top = sorted(candidatos, key=lambda c: c["n_archivos"], reverse=True)[:15]

    resumen = "\n".join([
        f"- {c['carpeta']}/  ({c['n_archivos']} archivos directos): "
        f"{', '.join(c['archivos'][:4])}"
        for c in candidatos_top
    ])

    muestras_codigo = "\n\n---\n\n".join([
        f"## {c['carpeta']}/\n{c['muestra']}"
        for c in candidatos_top
    ])

    prompt = f"""Analizá este proyecto y documentá sus módulos de negocio reales.

Proyecto: {nombre}  |  Stack: {stack}

El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser
un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).

Carpetas con archivos de código directamente adentro (las {len(candidatos_top)} con más archivos):
{resumen}

Código real de cada carpeta (archivos principales):
{muestras_codigo}

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
        texto, tokens = _llamar_claude(prompt, contexto=f"arquitectura:{nombre}", max_tokens=8000)
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
