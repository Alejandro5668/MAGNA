# task_detect_modules

**Propósito:** Dado el árbol del proyecto y la descripción de una tarea, identifica
cuáles módulos documentados son relevantes. Usa extended thinking para razonar antes
de seleccionar — mejora la precisión en proyectos con muchos módulos similares.

**Usado en:** `aicli/commands/task.py` → `_detect_relevant_modules()`
**Comando:** `ctx task`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 4000, thinking: enabled (budget: 2000 tokens)
**Versión:** 1.0

---

## Prompt

```
Tenés que identificar qué módulos de un proyecto de software son relevantes
para una tarea específica de desarrollo.

Tarea del desarrollador: {task_desc}
[Si se especificó archivo: El desarrollador indica que el problema ocurre específicamente en: {file}]

Módulos disponibles en el proyecto:
{listing}

Analizá la tarea, entendé qué partes del sistema necesita tocar, y devolvé ÚNICAMENTE
un JSON con los nombres de los módulos relevantes, sin texto adicional:
["nombre_modulo_1", "nombre_modulo_2"]

Seleccioná solo los módulos que realmente necesitarán ser leídos o modificados.
Si no podés filtrar con seguridad, devolvé todos los nombres.
```

**Formato del listing:**
```
- {m.name}: {m.description} | archivo: {m.file_path}
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-14 | Versión inicial con extended thinking | El modelo sin thinking seleccionaba módulos por nombre superficial, no por lógica de negocio |
