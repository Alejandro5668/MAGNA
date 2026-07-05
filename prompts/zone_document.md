# zone_document

**Propósito:** Documenta una zona/carpeta específica del proyecto. Lee 1000 chars de los
5 archivos más relevantes y devuelve los componentes funcionales como JSON.

**Usado en:** `aicli/services/indexer.py` → `document_zone()`
**Comando:** `ctx file <carpeta>`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 8192
**Versión:** 1.0

---

## Prompt

```
Analizá esta zona del proyecto y documentá cada componente relevante.

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

IMPORTANTE: "documentation" usa \n para saltos de línea. Sin backticks adentro.
Cada sección de "documentation" debe ser concisa — 2 a 4 líneas por sección.

Devolvé ÚNICAMENTE este JSON:
[
  {
    "name": "nombre_snake_case",
    "description": "qué hace este componente en una línea, basado en el código",
    "file_path": "{zone_display}/ArchivoReal.php",
    "category": "backend",
    "domain": null,
    "documentation": "# Componente\n\n## Qué hace\nBasado en el código real.\n\n## Funciones principales\nNombre y descripción breve de cada función pública.\n\n## Queries SQL\nTablas observadas (nombres exactos).\n\n## Dependencias\nArchivos o módulos que usa directamente."
  }
]

Valores válidos para category: backend, frontend, infraestructura, negocio.
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-14 | Versión inicial con sección SQL explícita | Los módulos PHP perdían contexto de queries sin esta sección |
