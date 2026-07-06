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

Fecha: 2026-07-04

- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`
- [ ] Verificar Option B end-to-end (task, sync, archive, revision) en `.exe`

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

## Fase 12 — Reorganización de comandos, contexto enriquecido y limpieza *(2026-06-14, sesión 2)*

**Objetivo:** Rediseñar los comandos para que sean más precisos y enfocados, enriquecer
el contexto que recibe Claude Code con conocimiento estructural del proyecto, y eliminar
código muerto que acumuló la refactorización anterior.

- [x] `ctx init` simplificado — corre `documentar_arquitectura()` directo, sin flags, sin guía de proyecto grande (DEC-024)
- [x] `ctx file <carpeta>` — nuevo comando que reemplaza `--zona`: documenta zona en profundidad con 1000 chars × 5 archivos, prompt con sección SQL (DEC-021)
- [x] `ctx archive <ruta>` — renombrado de `ctx module`: lee hasta 3000 chars del archivo real, documentación con funciones, SQL, dependencias y patrones (DEC-022)
- [x] `ctx sync` — nuevo comando post-tarea: git diff → re-documenta archivos cambiados → documenta nuevos automáticamente → captura decisión técnica (DEC-023)
- [x] `ctx proyecto` — nuevo comando: genera PROYECTO.md con Claude a partir de árbol + módulos documentados + muestra de `*_querys.php` (DEC-025)
- [x] `rol.md` global — creado en `~/.mycontext/rol.md` al primer `ctx init`, prepended a todo `session_context.md`, rol PHP senior 10+ años (DEC-026)
- [x] `PROYECTO.md` en knowledge store — `builder.py` lo inyecta automáticamente desde `~/.mycontext/projects/<id>/PROYECTO.md` en cada sesión (DEC-029)
- [x] Fix encoding `latin-1` — reemplaza `utf-8, errors=ignore` en todas las lecturas de código PHP (DEC-028)
- [x] Fix `_guardar_modulos` — upsert por `(project_id, file_path)` en vez de insert siempre, elimina duplicados (DEC-027)
- [x] PHP detection sin `composer.json` — `detectar_stack()` cuenta archivos `.php` con rglob si hay más de 10 (DEC-031)
- [x] `documentar_arquitectura` mejorado — max_tokens 8000, top 15 carpetas por cantidad de archivos descendente, docs concisas 3 secciones (DEC-020)
- [x] `generar_proyecto_md()` — nueva función en indexer.py que genera PROYECTO.md estructurado con secciones pendiente para lo que no puede inferir (DEC-025)
- [x] Eliminación del orquestador y `zone_detector.py` — código muerto tras la refactorización; 6 funciones + 1 archivo borrados (DEC-030)
- [x] `prompt_proyecto.md` — prompt para extraer conocimiento del proyecto en otro Claude
- [x] `PROYECTO.md` de empresa Kawak — generado con el prompt y disponible en raíz de AICLI
- [x] Decisiones DEC-020 a DEC-031 documentadas en `knowledge/decisions.md`
- [x] `ctx task --imagen` — visión Claude API via base64, descripción inyectada en session_context.md (DEC-032)
- [x] Mensaje de Jira: ASCII puro, emojis 🌱🛠️, máx 6 líneas (DEC-033)
- [x] Errores no fatales usan `return` en vez de `raise typer.Exit` para mantener el loop de menú (DEC-034)
- [x] BD y log renombrados: `ctx_bd.db` y `aicli_log.log` con sufijo de tipo (DEC-035)
- [x] Corrección DEC-031: PHP detection usa `path.glob("*.php")` en raíz (no rglob — evita escanear 14k archivos)
- [ ] Verificar `ctx init` en proyecto PHP de empresa con los fixes aplicados
- [ ] Verificar `ctx file ce_control_equipos` sin error de JSON truncado
- [ ] Verificar `ctx proyecto` genera PROYECTO.md correcto en proyecto PHP
- [ ] Verificar `ctx sync` detecta cambios post-tarea correctamente
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`

---

## Fase 13 — Tickets reabiertos, QA agent y mejoras de robustez *(2026-06-20)*

**Objetivo:** Soporte completo para el ciclo real de trabajo con Jira: tickets reabiertos
por QA, historial de rondas persistente, verificación pre-sync y correcciones de encoding.

- [x] `aicli/services/tickets.py` — historial de tickets en `tickets.json`, purga automática 7 días, `ticket_activo.json` como puente entre retomar y sync
- [x] `ctx retomar` en menú — lista tickets activos, muestra historial de rondas, pide motivo de reapertura + imagen + archivo, lanza Claude con historial inyectado
- [x] `ctx task` refactorizado — lógica extraída a `_ejecutar_task()`, acepta `historial_ticket` opcional para flujo de retomar
- [x] `ctx sync` — captura ticket Jira al cerrar, pre-rellena si viene de retomar, guarda ronda con archivos + mensaje + motivo
- [x] `caller.py` — nuevo parámetro `historial_ticket`, inyectado en `session_context.md` entre contexto y plan
- [x] `ctx status` reescrito — arquitectura por carpeta nivel 1 filtrada por proyecto actual, fecha de última doc, footer de sugerencia
- [x] Fix encoding `builder.py` — `errors="replace"` en lectura de módulos .md
- [x] Fix encoding `caller.py` — mensaje de launch sin tarea en argumento subprocess (evita encoding issues Windows)
- [x] QA agent en `ctx sync` — `php -l` en archivos PHP + llamada Claude adversarial con diff + tarea, panel de reporte con veredicto ok/revisar/bloqueante, opción de cancelar sync si hay issues
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`
- [ ] Verificar `ctx retomar` en proyecto PHP de empresa con ticket real
- [ ] Verificar QA agent con un fix real antes de sync

---

## Fase 14 — Rebrand MAGNA, animación y limpieza visual *(2026-06-20)*

- [x] Rebrand completo a MAGNA — font `ansi_shadow` con efecto 3D de caracteres de caja
- [x] Animación de bienvenida — líneas caen una a una con 90ms de delay (~0.55s total)
- [x] Eliminación de `ctx snapshot` — comando, archivo, import y handler removidos
- [x] Fix `Rule` import restaurado — eliminado por error al limpiar, causaba NameError en .exe
- [x] `PORT2.png` agregada como portada del README y commiteada al repo
- [x] README reescrito — nombre MAGNA, tabla de comandos actualizada, arquitectura real sin snapshot, tickets.py incluido
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec` (bloqueado por PermissionError — cerrar ctx.exe antes)

---

## Fase 15 — Calidad de sync, memoria de casos y ctx revision *(2026-06-29)*

**Objetivo:** Mejorar la calidad de documentación de `ctx sync`, reemplazar el flujo
manual de descripción de tickets por memoria auto-generada, y agregar soporte para
el ciclo de revisión de PRs con críticos.

- [x] Fix `_archivos_cambiados` — HEAD~1 solo como fallback, no siempre (DEC-041)
- [x] `analizar_archivo_profundo` — 8000 chars, actualización incremental con diff + doc existente (DEC-042)
- [x] `generar_resumen_caso` — reemplaza `generar_mensaje_jira`, JSON único con Jira + memoria del caso (DEC-043)
- [x] Case card UI — `_mostrar_case_card` con Rich: archivos, Investigado / Hecho / Tener en cuenta (DEC-044)
- [x] `guardar_ronda` con campo `memoria` estructurada (DEC-045)
- [x] `ctx retomar` — muestra solo ID y cantidad de rondas, sin descripción (DEC-046)
- [x] `ctx revision` — nuevo comando: parsea 🔴 de revisión de PR, lanza Claude con contexto del ticket (DEC-047)
- [x] QA agent eliminado de `ctx sync` — solo `php -l` queda (DEC-048)
- [x] DEC-041 a DEC-048 documentadas en `knowledge/decisions.md`
- [x] `evidencias/` — carpeta con captura desde portapapeles Windows, purga 7 días, `_ask_image()` como estándar (DEC-049)
- [x] Rename completo: todos los identificadores españoles → inglés en 15 archivos (DEC-050)
- [x] DEC-049 y DEC-050 documentadas en `knowledge/decisions.md`
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`

---

## Fase 16 — TUI Textual, paleta Noche Estrellada y Option B *(2026-07-04)*

**Objetivo:** Reemplazar el menú questionary por una TUI completa con Textual,
aplicar paleta Van Gogh, y redirigir el output de comandos al RichLog de Textual.

- [x] Reemplazo completo del menú questionary → Textual TUI (`aicli/tui/app.py`)
- [x] Paleta Noche Estrellada (#FFB703, #5B8DEF, #242C45, #AAB4D4, #5E6A94) — Van Gogh
- [x] Widgets nativos: Footer, Rule, TabbedContent + Sparkline (tabs PROJECT/SEMANA/ACTIVITY)
- [x] Widgets nativos: OptionList + Collapsible (menú izquierdo navegable con j/k)
- [x] Widgets nativos: RichLog en los 3 tabs del panel derecho (scrollable)
- [x] HelpScreen modal (tecla `?`) con tabla completa de keybindings
- [x] ConfirmModal nativo Yes/No — reemplaza `questionary.confirm` en contexto TUI
- [x] Vim motions: j/k navegar, g/G saltar top/bottom, h/l colapsar/expandir sección
- [x] Focus indicators: `:focus-within` en panel izquierdo y tabs (borde dorado activo)
- [x] **Option B**: `CommandOutputScreen` — output de comandos en RichLog sin suspend
- [x] **Option B**: `TuiConsole` — enruta `print`/`status` al RichLog vía `call_from_thread`
- [x] `TuiConsole.request_input/confirm` — InputModal/ConfirmModal vía `run_coroutine_threadsafe`
- [x] `TuiConsole.suspend_and_run` — suspend solo para lanzar Claude Code (subprocess)
- [x] `sync._sync_impl(ask_fn, confirm_fn)` — questionary sustituible por callbacks TUI
- [x] `task._execute_task(suspend_fn)` — Claude launch desacoplado vía bridge
- [x] Fix: `asyncio.run()` conflict con questionary → `ThreadPoolExecutor` en `_worker_cmd`
- [x] Fix: `CommandScreen.dismiss` desde `@work async`, no desde `set_timer` lambda
- [x] Fix: background bleeding en `CommandOutputScreen` → `background: #000000`
- [x] Fix: descripciones del menú no wrappean — `_DESC_MAX = 22` + acortadas
- [x] Fix: `Separator` no existe en Textual 8.2.8 → eliminado
- [x] `ctx.spec` — `collect_submodules('textual')` + `collect_data_files('textual')`
- [x] Suite de smoke tests `tests/test_commands.py` — 23/23 pasados
- [x] Fix bleeding: `CommandOutputScreen` → `ModalScreen[None]` + `Container(#co-frame) 100%×100%`
- [x] Fix bleeding: `CommandScreen` → `Container(#cs-frame) 100%×100%` con `align: center middle`
- [x] Logo MAGNA gradiente azul→dorado — `_gradient_logo()` aplicado en `MainScreen` y `ProjectScreen`
- [x] Hatch puntillismo en panel izquierdo (`hatch: "·" #5B8DEF 20%`)
- [x] Sparkline sinusoidal animada — `set_interval(0.25)` + `_spark_phase` en `MainScreen`
- [x] `magna_task_plan` — card visual con módulos + plan línea a línea + subtitle modelo
- [x] Pregunta de imagen eliminada del flow TUI de task — `_gather_image_async` removida
- [x] Footer `CommandOutputScreen` simplificado → `#co-done` con `esc` dorado visible
- [x] DEC-052 a DEC-055 documentadas en `knowledge/decisions.md`
- [x] `.gitignore` actualizado — patrones Claude Code (`.agents/`, `skills-lock.json`, etc.)
- [x] Animaciones de entrada en `ProjectScreen`: fade-in logo, typing tagline, fade-in lista
- [x] Fix `AnimationError`: offset → solo opacity (`textual.geometry.Offset` no es animable en Textual 8.x)
- [x] README actualizado: questionary → Textual 8.2.8, assets borradas, arquitectura con `tui/` y `tests/`
- [ ] Empaquetar `.exe` nuevo: `pyinstaller ctx.spec`
- [ ] Verificar Option B end-to-end: task, sync, archive, revision en `.exe` compilado

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
| 2026-06-14 (2) | Reorganización completa de comandos (ctx file/archive/sync/proyecto), rol.md global PHP-específico, PROYECTO.md automático con IA, fix encoding latin-1, fix duplicados _guardar_modulos, eliminación orquestador muerto, DEC-020 a DEC-031, PROYECTO.md Kawak generado | Verificar nuevos comandos en PHP empresa, empaquetar .exe |
| 2026-06-14 (3) | Documentadas DEC-032 a DEC-035 (imagen/Jira/return-vs-exit/nombres de archivos); corrección a DEC-031 (glob no rglob) | Verificar comandos nuevos en PHP empresa, empaquetar .exe nuevo |
| 2026-06-15 | Integración Ponytail (tip en sync + panel en init), limpieza por audit (6 fixes), images→assets, README profesional, DEC-036 multi-stack | Verificar comandos en PHP empresa, empaquetar .exe |
| 2026-06-20 | ctx retomar (historial de tickets reabiertos), QA agent en sync, ctx status reescrito por carpeta, fix encoding builder/caller | Empaquetar .exe, verificar retomar y QA con ticket real en PHP empresa |
| 2026-06-20 (2) | Rebrand MAGNA (ansi_shadow + animación), eliminación snapshot, README reescrito, PORT2.png commiteada, fix Rule import | Empaquetar .exe (cerrar instancia antes), verificar retomar y QA en PHP empresa |
| 2026-06-29 | Fix scope de diff en sync, documentación incremental con diff+doc existente, case card UI, generar_resumen_caso, ctx revision para críticos de PR, QA agent removido, DEC-041–048 | Empaquetar .exe nuevo |
| 2026-06-29 (2) | evidencias/ con portapapeles Windows, rename English identifiers (50+ en 15 archivos), DEC-049 y DEC-050 | Empaquetar .exe nuevo |
| 2026-07-04 | TUI Textual completa (questionary eliminado), paleta Noche Estrellada Van Gogh, Option B CommandOutputScreen+TuiConsole, 23 smoke tests | Empaquetar .exe, verificar Option B en .exe compilado |
| 2026-07-05 | Fix bleeding TUI (ModalScreen+Container 100%), gradiente logo, hatch puntillismo, Sparkline animada, magna_task_plan, DEC-052–055, .gitignore Claude Code, logo ProjectScreen con gradiente | Empaquetar .exe, verificar Option B en compilado |
| 2026-07-05 (2) | Animaciones ProjectScreen (fade-in logo, typing tagline, fade-in lista), fix AnimationError + ScalarOffset, test anti-regresión offset, README actualizado | Empaquetar .exe, verificar Option B en compilado |
| 2026-07-05 (3) | OS-1/2/3 completos y mergeados a main: StackProfile, generate_role_md con IA, ctx profile; prompts/ verificado genérico entre ramas | Empaquetar .exe nuevo, verificar Option B en compilado |