# AICLI — Tracker de Trabajo Diario

> **Rutina de cada sesión:**
> - **Al abrir:** escribí la fecha y tus 3 tareas en "Foco de hoy"
> - **Al cerrar:** ejecutá `/cierre` — Claude revisa el proyecto, propone qué marcar y pedí tu confirmación antes de tocar nada

---

## Progreso general

| Fase | Nombre | Estado |
|------|--------|--------|
| 0 | Entorno base | ✅ Completada |
| 1 | Typer a fondo | ✅ Completada |
| 2 | Rich — presentación | ✅ Completada |
| 3 | SQLModel y base de datos | ✅ Completada |
| 4 | Capa de servicios | ✅ Completada |
| 5 | Anthropic SDK e IA | ✅ Completada |
| 6 | Comando `ctx claude` | ✅ Completada |
| 7 | CLI completa y robusta | ✅ Completada |
| 8 | Optimización IA — velocidad (`ctx init`) | ✅ Completada |
| 9 | Optimización IA — precisión (`ctx task`) | ✅ Completada |
| 10 | Agente orquestador por zonas | ✅ Completada |

---

## Foco de hoy

> Actualizá esto al inicio de cada sesión. Máximo 3 tareas. Si tenés más de 3, el resto va al backlog.

Fecha: 2026-06-14

- [x] Verificar `ctx init --arquitectura` en proyecto PHP de empresa
- [x] Verificar `ctx task --archivo` en proyecto PHP de empresa
- [ ] Empaquetar `.exe` nuevo con cambios de hoy

---

## Fase 0 — Entorno base

**Objetivo:** App corriendo con el primer comando funcional.

- [x] Entorno virtual creado en PyCharm
- [x] Repositorio Git inicializado y conectado a GitHub
- [x] Typer 0.26 instalado
- [x] Rich 15 instalado
- [x] Estructura de carpetas creada (`aicli/`, `commands/`, `db/`, `services/`)
- [x] `CLAUDE.md` con contexto del proyecto
- [x] `knowledge/` con decisions, patterns y progress
- [x] `.claude/commands/start.md` — comando `/project:start`
- [x] Instalar dependencias pendientes: `sqlmodel anthropic httpx python-dotenv`
- [x] Actualizar `requirements.txt` con versiones exactas (`pip freeze > requirements.txt`)
- [x] Crear `main.py` — app Typer + comando `hello` funcional
- [x] Verificar: `python main.py hello` corre sin errores

---

## Fase 1 — Typer a fondo

**Objetivo:** Entender cómo Typer construye una CLI desde type hints. Producto: `ctx status` con output hardcodeado.

- [x] Leer cómo funciona `@app.command()` como decorador
- [x] Entender Arguments vs Options vs Flags en Typer
- [x] Crear `aicli/commands/status.py` con comando `status` básico
- [x] Registrar `status` en `main.py` como sub-aplicación
- [x] Verificar: `python main.py status` corre y muestra algo

---

## Fase 2 — Rich como capa de presentación

**Objetivo:** Output visual profesional. Producto: `ctx status` con paneles y colores reales.

- [x] Entender `Console`, markup y estilos de Rich
- [x] Usar `Panel` para agrupar información en `status`
- [x] Usar `Table` para mostrar módulos documentados
- [x] Agregar `Spinner` en alguna operación que simule carga — pendiente: mover dentro de la función `status()`
- [x] Aplicar PAT-002 y PAT-003 de `knowledge/patterns.md` consistentemente

---

## Fase 3 — SQLModel y base de datos

**Objetivo:** Persistencia real. Producto: `ctx init` guarda proyecto en SQLite, `ctx status` lo lee.

- [x] Entender qué es un ORM y por qué SQLModel sobre SQLAlchemy puro
- [x] Definir modelo `Project` en `aicli/db/`
- [x] Definir modelo `Module` en `aicli/db/`
- [x] Crear conexión a SQLite en `~/.mycontext/ctx.db`
- [x] Crear tablas automáticamente al primer uso
- [x] Crear `aicli/commands/init.py` — guarda proyecto activo en la BD
- [x] Verificar: `ctx init` + `ctx status` muestran el proyecto guardado

> Decisiones de referencia: DEC-001, DEC-004, DEC-005 en `knowledge/decisions.md`

---

## Fase 4 — Capa de servicios

**Objetivo:** Separar lógica de los comandos. Producto: `indexer.py` detecta stack y documenta módulos con IA.

- [x] Entender el patrón Service Layer y por qué importa
- [x] Crear `aicli/services/indexer.py`
- [x] Implementar detección de stack por heurísticas de archivos (requirements.txt, package.json, etc.)
- [x] Conectar el servicio con `ctx init` — el comando solo llama al servicio
- [x] Verificar: el indexer detecta correctamente el stack de AICLI mismo

---

## Fase 5 — Anthropic SDK e IA real

**Objetivo:** Claude detecta módulos afectados para una tarea. Producto: `ctx task "texto"` funcional.

- [x] Configurar `ANTHROPIC_API_KEY` con `python-dotenv` (ver PAT-004)
- [x] Entender cómo funciona la API de Claude: mensajes, roles, tokens
- [x] Crear `aicli/services/builder.py` + `aicli/services/caller.py` (equivalente a `claude_service.py` — mejor separación)
- [x] Implementar llamada básica: enviar prompt, recibir respuesta
- [x] Implementar prompt para detección de módulos afectados
- [x] Crear `aicli/commands/task.py` — recibe texto libre, detecta módulos relevantes con IA, lanza Claude
- [x] Verificar: `ctx task` detecta módulos y lanza Claude (rate limit resuelto, shell=True en Windows)

---

## Fase 6 — Comando `ctx claude`

**Objetivo:** AICLI completo end-to-end. Producto: Claude Code lanzado con contexto inyectado.

- [x] Entender `subprocess` en Python — cómo lanzar procesos externos
- [x] Implementar ensamblado dinámico del contexto por sesión (`builder.py` + `session_context.md`)
- [x] Crear `aicli/commands/claude_cmd.py`
- [x] Lanzar Claude Code como subprocess con contexto pre-cargado
- [x] Verificar: `ctx claude` abre Claude Code con contexto completo del proyecto

---

## Fase 7 — CLI completa y robusta *(fase nueva — trabajo de esta sesión)*

**Objetivo:** CLI lista para distribuir como `.exe` a usuarios reales.

- [x] Migrar BD de MySQL a SQLite (`aicli/db/__init__.py`) — DEC-001
- [x] Señal de frescura: `last_updated_at`, `category`, `domain` en modelo `Module` — DEC-007 / DEC-008
- [x] `modulo_necesita_actualizacion()` en `indexer.py` — re-documenta solo archivos modificados
- [x] Refactor `init.py` — proyecto existente → actualizar en lugar de error
- [x] Refactor `module.py` — módulo existente → actualizar si cambió
- [x] Crear `aicli/commands/snapshot.py` — punto de restauración del knowledge store
- [x] Menú interactivo con logo ASCII (pyfiglet) + flechas (questionary)
- [x] Loop de menú — vuelve al menú después de cada comando en lugar de cerrar
- [x] Menú completo con los 6 comandos disponibles
- [x] Verificación y configuración de API key en primera ejecución
- [x] Selector de proyecto para usuarios que abren el `.exe` sin estar en un directorio registrado
- [x] Sistema de logs en `~/.mycontext/aicli.log` con niveles INFO y ERROR
- [x] Rate limit handling: reintentos con backoff (30s → 60s → 120s) en `indexer.py`
- [x] Límite de contenido (`MAX_CHARS_CONTENIDO`) para evitar prompts gigantes
- [x] Fix `.next/`, `dist/`, `build/` y directorios de build en `IGNORAR`
- [x] Fix `.tsx`, `.jsx` y extensiones de código ampliadas para soporte multi-stack
- [x] Detección de stack ampliada: Next.js, React, Vue, Angular, TypeScript, Go, Rust, Kotlin, Ruby, Flutter, Elixir
- [ ] Verificar `ctx task` y `ctx claude` end-to-end en otro PC con el `.exe`
- [ ] Empaquetar como `.exe`: `pyinstaller --onefile --collect-data pyfiglet main.py --name ctx`

---

---

## Fase 8 — Optimización IA: velocidad en `ctx init`

**Objetivo:** Reducir el tiempo de `ctx init` de ~15 minutos a ~25 segundos entendiendo
por qué las llamadas secuenciales son el cuello de botella y cómo diseñar prompts que
hacen más trabajo en menos llamadas.

**Qué vas a aprender:**
- Cómo calcular el costo real de N llamadas secuenciales vs 1 llamada combinada
- Técnica de prompt "haz todo en una respuesta": análisis + documentación en un solo JSON
- Cuándo el rate limit es un síntoma de diseño malo, no un límite a aceptar
- La diferencia entre módulos por archivo vs módulos funcionales y por qué importa
- Cómo diseñar una blocklist vs allowlist y cuándo cada una tiene sentido

**Referencia:** `plan_optimizacion.md` — Eje 1

- [x] **1.1** Entender el problema: N+1 llamadas secuenciales con sleep(4) entre cada una.
- [x] **1.2** Implementar `analizar_y_documentar()` en `indexer.py` — una sola llamada que devuelve 6-12 módulos funcionales con documentación incrustada en el JSON. Incluye `_reparar_json()` como safety net para JSON con saltos de línea literales.
- [x] **1.3** Reemplazar `indexar_proyecto()`: usa `analizar_y_documentar()` como camino principal, `_indexar_secuencial()` como fallback si el JSON falla, y `indexar_proyecto_orquestado()` para proyectos >80 archivos de código. El sleep(4) desapareció como consecuencia.
- [x] **1.4** Reemplazar listas estáticas por lógica dinámica.
- [ ] **Verificar:** Correr `ctx init` en el proyecto Next.js donde tardaba 15 min y medir el tiempo real.

---

## Fase 9 — Optimización IA: precisión en `ctx task`

**Objetivo:** Hacer que `ctx task` seleccione módulos relevantes con precisión quirúrgica
y que Claude Code arranque con un plan técnico en lugar de desde cero.

**Qué vas a aprender:**
- Qué es extended thinking y cuándo activarlo (no en toda llamada — solo donde la
  calidad de razonamiento impacta directamente el resultado)
- Cómo extraer el bloque de texto de una respuesta con bloques `thinking` + `text`
- El concepto de "task brief" como contexto generado, no hardcodeado
- Por qué el orden en que Claude Code recibe información afecta cómo trabaja
- Cómo diseñar prompts de sistema que configuran el rol antes de la tarea

**Referencia:** `plan_optimizacion.md` — Eje 2 y Eje 3

- [x] **2.1** Extended thinking: `thinking={"type": "enabled", "budget_tokens": 2000}` en `_detectar_modulos_relevantes()`. El texto se extrae con `next(b.text for b in respuesta.content if b.type == "text")` porque la respuesta tiene bloques thinking + text mezclados.
- [x] **2.2** Implementar `_generar_task_brief()` en `task.py` — llamada rápida (max_tokens 512) que genera el plan técnico.
- [x] **2.3** Integrar el brief en el flujo de `task`: spinner, Panel con el plan antes de lanzar Claude Code, pasar al caller.
- [x] **2.4** `lanzar_claude()` recibe `brief` y lo escribe en el archivo de contexto entre los módulos y la tarea.
- [ ] **Verificar:** Correr `ctx task "agregar dark mode"` y observar la selección de módulos y el panel de plan generado.

---

## Fase 10 — Agente orquestador por zonas

**Objetivo:** Para proyectos grandes (monorepos, aplicaciones full-stack complejas),
usar múltiples agentes Claude especializados por zona del proyecto corriendo en paralelo.

**Qué vas a aprender:**
- El patrón orquestador/subagente: un coordinador que delega trabajo especializado
- Cómo diseñar prompts de agentes con roles específicos ("sos un agente especializado en la zona frontend")
- Por qué la especialización del contexto mejora la calidad: cada agente ve solo su parte, sin ruido
- Cuándo el patrón de agentes tiene sentido vs cuándo es sobreingeniería (criterio: tamaño del proyecto)
- Cómo ejecutar múltiples llamadas a la API al mismo tiempo en Python (solo cuando la Fase 8 lo requiera)

**Referencia:** `plan_optimizacion.md` — Eje 4, pasos 4.1 al 4.3

- [x] **4.1** Crear `aicli/services/zone_detector.py` con `detectar_zonas(path, stack, arbol)` — recibe el árbol ya calculado para no hacer doble scan. Claude detecta las zonas según la estructura real del proyecto, sin listas hardcodeadas.
- [x] **4.2** Implementar `_analizar_zona()` en `indexer.py` — agente especializado por zona con `_leer_archivos_zona()` para contexto filtrado.
- [x] **4.3** Implementar `indexar_proyecto_orquestado()` — lanza agentes en paralelo con `ThreadPoolExecutor(max_workers=3)`, consolida resultados, con fallback a `_indexar_secuencial()` si no se detectan zonas.
- [x] **4.4** `indexar_proyecto()` enruta automáticamente: ≤80 archivos → `analizar_y_documentar()`, >80 archivos → `indexar_proyecto_orquestado()`.
- [ ] **Verificar:** Correr `ctx init` en el proyecto Next.js grande y confirmar zonas detectadas en logs y tiempo total.

---

## Fase 11 — Escalabilidad, precisión y UX para proyectos grandes *(2026-06-14)*

**Objetivo:** Hacer que AICLI funcione correctamente en proyectos de cualquier escala,
incluyendo monolitos PHP de 11.000 archivos. Mejorar la precisión de ctx task y la
coherencia del patrón `modulo/archivo.php` en toda la CLI.

- [x] `ctx init --zona <carpeta>` — documenta solo una subcarpeta específica
- [x] `ctx init --reciente N` — documenta archivos modificados en los últimos N días (git log)
- [x] `ctx init --arquitectura` — lee código real de carpetas de nivel 1, discrimina módulos de infraestructura
- [x] Guía interactiva con questionary cuando el proyecto supera 500 archivos de código
- [x] `documentar_arquitectura()` reescrito: lee código real (500 chars/archivo, prioriza archivo con nombre de la carpeta)
- [x] Documentación almacenada espejando estructura del proyecto: `modulo/archivo.md` (DEC-009)
- [x] `ctx task --archivo modulo/archivo.php` — ancla el contexto al archivo exacto del problema
- [x] El módulo del `--archivo` siempre se incluye en el contexto, sin importar el filtrado
- [x] `ctx module add modulo/archivo.php` — nombre derivado del stem, sin argumento separado (DEC-018)
- [x] Diagnóstico automático cuando Claude no se encuentra: busca en rutas conocidas de Windows, muestra fix exacto, ofrece reintentar (DEC-019)
- [x] `lanzar_claude()` lanza `claude.cmd` por ruta completa si lo encuentra aunque no esté en PATH
- [x] `MAX_ARBOL_ENTRADAS = 300`, backoff `ESPERA_INICIAL = 60`, `MAX_REINTENTOS = 4` (fix rate limit proyecto PHP)
- [x] Depuración: eliminados comentarios de historia en constantes, try/except redundantes, `OnProgreso` duplicado
- [x] Decisiones DEC-009 a DEC-019 documentadas en `knowledge/decisions.md`
- [x] `knowledge/progress.md` reescrito completo con estado real al 2026-06-14
- [ ] Verificar `ctx init --arquitectura` en proyecto PHP de empresa (11.000 archivos)
- [ ] Verificar `ctx task --archivo pagos/X.php` en proyecto PHP de empresa
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`

---

## Bloqueantes activos

> Registrá acá cualquier cosa que te frenó. Con fecha y contexto breve.

| Fecha | Bloqueante | Estado |
|-------|------------|--------|
| 2026-06-08 | Migrar MySQL → SQLite para habilitar distribución como .exe standalone | ✅ Resuelto 2026-06-13 |

---

## Log de sesiones

> Una línea por sesión. Fecha + qué avanzaste + qué dejaste pendiente.

| Fecha | Avance | Pendiente para próxima sesión |
|-------|--------|-------------------------------|
| 2026-05-30 | Setup inicial del proyecto, documentación base, TODO.md creado | Instalar dependencias, crear main.py |
| 2026-05-30 | main.py con Typer+Rich funcional, .gitignore, README, TODO.md, /cierre, fundamentos_python.md, fix encoding | Instalar 4 dependencias pendientes, actualizar requirements.txt |
| 2026-05-31 | Fase 1 completa + Fase 2 casi completa: status.py con Panel, Table, Spinner, markup Rich | Instalar 4 dependencias (Fase 0), mover spinner dentro de la función status() |
| 2026-06-06 | Instaladas 4 dependencias + PyMySQL, modelos Project y Module creados, conexión MySQL configurada con .env, tablas creadas en BD | Crear aicli/commands/init.py para guardar proyectos en la BD |
| 2026-06-06 | init.py creado con lógica de duplicados y detección de stack, decisión de no ignorar knowledge/ ni CLAUDE.md en .gitignore | Corregir bug en WHERE clause de init.py (Project.path vs proyecto.path), verificar ctx init funcionando |
| 2026-06-07 | Indexer completo con Claude API (obtener_arbol, leer_archivos_clave, analizar_con_claude, generar_contenido_modulo), ctx init guarda módulos + .md en ~/.mycontext/, fix DetachedInstanceError, fix where clause, knowledge/aprendizaje.md creado | Corregir extensión .md en archivo_md, implementar ctx status con datos reales de módulos, crear claude_service.py |
| 2026-06-08 | ctx module add funcional con validación de duplicados + Claude API, status.py con datos reales, mensajes estandarizados (green/red/yellow/Group+Panel) | Crear claude_service.py, crear task.py, verificar ctx task |
| 2026-06-11 | Sesión de planificación: DEC-007 señal de frescura, DEC-008 frontend Next.js, corrección DEC-001 SQLite, prompt para Lovable creado en design/lovable_prompt.md, progress.md reorganizado por fases | Implementar migración MySQL→SQLite en db/__init__.py, luego señal de frescura en models.py e indexer.py |
| 2026-06-13 | Migración SQLite completa, señal de frescura, todos los comandos CLI implementados (task, claude, snapshot), menú interactivo con pyfiglet+questionary, API key flow, selector de proyecto, sistema de logs, rate limit handling, soporte multi-stack | Verificar ctx task y ctx claude end-to-end en otro PC, empaquetar como .exe |
| 2026-06-14 | Optimización completa: ctx init con 3 modos nuevos (--zona/--reciente/--arquitectura), ctx task con extended thinking + brief + --archivo, ctx module add simplificado a ruta, docs en estructura modulo/archivo.md, diagnóstico Claude en Windows, documentar_arquitectura con código real, depuración de código, decisiones DEC-009 a DEC-019 | Verificar todo en proyecto PHP de empresa (11.000 archivos), empaquetar .exe nuevo |