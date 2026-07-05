# file_document

**Propósito:** Genera o actualiza la documentación de un archivo individual.
Tiene tres variantes según el contexto disponible: solo código, código + diff (archivo nuevo),
o código + diff + doc existente (actualización incremental).

**Usado en:** `aicli/services/indexer.py` → `analyze_file_deep()`
**Comandos:** `ctx archive`, `ctx sync`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 4000
**Versión:** 1.0

---

## Prompt

### Variante A — Actualización incremental (diff + doc existente)
```
Actualizá la documentación técnica de este archivo incorporando los cambios recientes.

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

Solo el markdown, sin texto adicional antes ni después.
```

### Variante B — Primera documentación con diff
```
Generá documentación técnica para este archivo. El diff muestra los cambios de la sesión actual.

Proyecto: {project_name} | Stack: {stack}
Archivo: {file_path}

Cambios de esta sesión (git diff):
{diff[:4000]}

Código fuente:
{content}

Generá un documento markdown con exactamente estas secciones:
{sections}

Solo el markdown, sin texto adicional antes ni después.
```

### Variante C — Primera documentación sin diff
```
Generá documentación técnica detallada para este archivo.

Proyecto: {project_name} | Stack: {stack}
Archivo: {file_path}

Código fuente:
{content}

Generá un documento markdown con exactamente estas secciones:
{sections}

Solo el markdown, sin texto adicional antes ni después.
```

### Secciones fijas (variable `sections`)
```
- Qué hace este archivo (propósito y rol en el sistema)
- Funciones y clases principales (nombre, parámetros y qué hace cada una)
- Queries SQL y tablas involucradas (nombres exactos del código, si aplica)
- Dependencias (qué otros archivos o módulos usa directamente)
- Patrones y convenciones observados
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-29 | Versión inicial con 3 variantes + actualización incremental | El diff permite preservar conocimiento previo al re-documentar |
