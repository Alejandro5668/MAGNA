# project_md

**Propósito:** Genera PROYECTO.md con conocimiento estructural inferido del código.
Usa árbol de archivos + módulos ya documentados + muestras de archivos clave.
Las secciones que requieren conocimiento humano quedan marcadas como "pendiente".

**Usado en:** `aicli/services/indexer.py` → `generate_project_md()`
**Comando:** `ctx proyecto`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 8000
**Versión:** 1.0

---

## Prompt

```
Analizá este proyecto de software y generá un documento PROYECTO.md con conocimiento estructural.

Proyecto: {name} | Stack: {stack}

Árbol de archivos:
{tree_text}

Módulos de negocio ya identificados:
{modules_text}

[Muestra de código SQL si existe]
[Muestra de infraestructura si existe]

Generá el siguiente documento markdown completando cada sección.
REGLA: Si podés inferirlo del código o el árbol → escribilo con precisión y ejemplos reales.
Si NO podés inferirlo (requiere conocimiento humano acumulado) → escribí exactamente esta línea:
> pendiente — enriquecé esta sección con tu conocimiento del proyecto

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

- `{prefijo}_querys.php` →
- `{prefijo}_lista.php` →
- `{prefijo}_ejecutar.php` →
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

> pendiente — enriquecé esta sección con tu conocimiento del proyecto

## 7. Reglas y restricciones no obvias

> pendiente — enriquecé esta sección con tu conocimiento del proyecto

## 8. Carpetas que JAMÁS son módulos de negocio

(Inferí desde el árbol: vendor, assets, libs, infraestructura)

```
[lista de carpetas a ignorar]
```

## 9. Señales para detectar el archivo principal de un módulo

(Inferí desde las convenciones de nombres que viste)

## 10. Decisiones técnicas acumuladas

> pendiente — enriquecé esta sección con tu conocimiento del proyecto
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-14 | Versión inicial con 10 secciones | — |
