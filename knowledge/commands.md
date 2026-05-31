# Comandos de Claude Code — Referencia AICLI

Guía de uso de los comandos slash disponibles en este proyecto.
Cuándo usar cada uno, qué hace exactamente y qué esperar como respuesta.

---

## Comandos del proyecto (slash commands personalizados)

Estos comandos están definidos en `.claude/commands/` y son específicos de AICLI.
Se invocan escribiendo `/nombre` en el chat de Claude Code.

---

### `/start`

**Cuándo usarlo:** Al inicio de cada sesión de trabajo, antes de escribir código.

**Qué hace:**
1. Lee `CLAUDE.md`, `knowledge/decisions.md`, `knowledge/patterns.md`, `knowledge/progress.md`
2. Devuelve estado actual del proyecto en 3 líneas
3. Lista gaps de documentación detectados
4. Recomienda el siguiente paso concreto y accionable

**Qué esperar:** Un resumen estructurado que te ubica en contexto en menos de 30 segundos.
No hace cambios en ningún archivo.

**Ejemplo de uso:**
```
/start
```

---

### `/cierre`

**Cuándo usarlo:** Al terminar la sesión de trabajo del día, antes de cerrar PyCharm.

**Qué hace:**
1. Lee `TODO.md` e identifica la fase activa con tareas pendientes
2. Inspecciona los archivos reales del proyecto (¿existe `main.py`? ¿qué hay en `requirements.txt`?)
3. Para cada tarea pendiente, determina si está HECHO, PENDIENTE o PARCIAL con evidencia concreta
4. Presenta una tabla de verificación con propuesta de cambios
5. **Pide tu confirmación antes de tocar nada**
6. Solo si confirmás: marca tareas en `TODO.md` y agrega línea al log de sesiones

**Qué esperar:** Una tabla de verificación + pregunta de confirmación. Respondé "sí" para aplicar o pedí ajustes.

**Regla importante:** Nunca modifica archivos sin tu "sí" explícito.

**Ejemplo de uso:**
```
/cierre
```

---

## Comandos built-in de Claude Code

Estos comandos vienen con Claude Code y están disponibles en cualquier proyecto.

---

### `/help`

Muestra la lista completa de comandos disponibles y cómo usar Claude Code.

---

### `/clear`

Limpia el historial de la conversación actual. Útil cuando el contexto se llenó con
mensajes irrelevantes y querés empezar limpio sin perder el estado del proyecto.

**Cuándo usarlo:** Cuando la conversación se volvió larga y llena de pruebas o errores.
Después de `/clear`, ejecutá `/start` para re-cargar el contexto del proyecto.

---

### `/config`

Abre la configuración de Claude Code: tema, modelo, preferencias de display.

---

### `/code-review`

Revisa el diff actual del branch en busca de bugs, simplificaciones y mejoras.

**Niveles de profundidad:**
- `/code-review` — revisión estándar
- `/code-review high` — cobertura más amplia, puede incluir hallazgos inciertos
- `/code-review ultra` — revisión profunda multi-agente en la nube (tarda más, es la más completa)
- `/code-review --fix` — aplica los hallazgos directamente al código

**Cuándo usarlo en AICLI:** Antes de cada commit importante, especialmente al terminar
una fase completa del roadmap.

---

### `/run`

Lanza la app del proyecto y verifica que un cambio funciona en el entorno real.
Busca primero un script de arranque del proyecto; si no encuentra, usa patrones por tipo de proyecto.

**Cuándo usarlo:** Después de implementar un comando nuevo de AICLI para confirmar que corre.

---

## Flujo de trabajo recomendado con comandos

### Inicio de sesión
```
/start          → lee contexto, te dice dónde estás y qué sigue
```

### Durante la sesión
```
(escribís código normalmente)
/run            → si querés verificar que algo funciona en la app real
/code-review    → antes de un commit importante
```

### Cierre de sesión
```
/cierre         → verifica tareas completadas, propone cambios en TODO.md, pide confirmación
```

---

## Notas de uso

- Los comandos `/start` y `/cierre` se complementan: `/start` te ubica al abrir, `/cierre` te cierra al terminar.
- Podés pasar argumentos a `/code-review` pero no a `/start` ni `/cierre` — estos no aceptan argumentos.
- Si un comando no responde como esperás, revisá el archivo correspondiente en `.claude/commands/` — ahí está la instrucción exacta que sigue Claude.
- Los comandos personalizados del proyecto se pueden editar en cualquier momento para ajustar el comportamiento.
