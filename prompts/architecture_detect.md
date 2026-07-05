# architecture_detect

**Propósito:** Analiza las carpetas de nivel 1 del proyecto, lee muestras de código real
y devuelve los módulos de negocio identificados como JSON. Discrimina entre módulos reales
y carpetas de infraestructura (config, assets, libs).

**Usado en:** `aicli/services/indexer.py` → `document_architecture()`
**Comando:** `ctx init`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 8000
**Versión:** 1.0

---

## Prompt

```
Analizá este proyecto y documentá sus módulos de negocio reales.

Proyecto: {name}  |  Stack: {stack}

El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser
un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).

Carpetas con archivos de código directamente adentro (las {n} con más archivos):
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

IMPORTANTE: "documentation" usa \n para saltos de línea. Sin backticks adentro.
Mantené "documentation" concisa: máximo 3 secciones cortas.

Devolvé ÚNICAMENTE este JSON:
[
  {
    "name": "nombre_snake_case",
    "description": "qué hace este módulo en una línea, basado en el código visto",
    "file_path": "modulo/ArchivoMain.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Módulo\n\n## Qué hace\nDescripción basada en el código real.\n\n## Archivos principales\nLista de archivos vistos con descripción breve.\n\n## Dependencias clave\nQué usa o qué lo usa."
  }
]

Valores válidos para category: backend, frontend, infraestructura, negocio.
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-14 | Versión inicial | — |
