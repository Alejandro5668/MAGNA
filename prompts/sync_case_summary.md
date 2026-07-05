# sync_case_summary

**Propósito:** En una sola llamada API genera el mensaje de Jira + la memoria del caso
(investigado, hecho, tener en cuenta). Si hay historial de rondas anteriores, el mensaje
de Jira documenta solo esta ronda para no repetir lo ya escrito.

**Usado en:** `aicli/services/indexer.py` → `generate_case_summary()`
**Comando:** `ctx sync`
**Modelo:** claude-sonnet-4-6
**Parámetros:** max_tokens: 800
**Versión:** 1.0

---

## Prompt

```
Sos un desarrollador senior cerrando un ticket de trabajo.
[Si hay historial anterior:]
Historial de rondas anteriores:
{previous_history}
Esta es una ronda de seguimiento. El mensaje Jira debe documentar SOLO los cambios
de esta ronda, no repetir lo que ya esta en el historial.

Tarea resuelta: {task}

Archivos modificados:
{files_str}

Cambios aplicados (git diff):
{diff[:5000]}

Genera un JSON con exactamente estas claves, sin texto adicional antes ni despues:

{
  "jira": "mensaje para pegar en Jira. Formato: '🌱 Causa Raiz: [origen tecnico, archivo:linea o tabla:campo]\n🛠️ Solucion Aplicada: [cambios concretos, maximo 4 puntos]'. SOLO ASCII puro sin tildes. Maximo 6 lineas totales.",
  "investigado": "que causa genero el problema — especifico con archivo/funcion/tabla si aplica — maximo 2 oraciones",
  "hecho": "que cambios se aplicaron exactamente — archivos y funciones modificadas — maximo 2 oraciones",
  "tener_en_cuenta": "gotchas, restricciones no obvias, edge cases a considerar en el futuro — maximo 2 oraciones"
}
```

---

## Changelog

| Versión | Fecha | Cambio | Por qué |
|---------|-------|--------|---------|
| 1.0 | 2026-06-29 | Versión inicial — una llamada reemplaza dos (Jira separado + memoria separada) | Reducir latencia y costos; el JSON unifica ambos outputs |
