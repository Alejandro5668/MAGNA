# Estado del Proyecto

Última actualización: 2026-06-14

---

## Resumen ejecutivo

CLI completamente funcional y distribuida como `.exe`. Probada en proyectos reales
(PHP puro con ~11.000 archivos, Next.js). El foco actual es validación en campo y
refinamiento de calidad de documentación generada.

---

## Completado — Infraestructura base

- [x] Entorno virtual, repositorio Git, dependencias instaladas
- [x] Estructura de carpetas (`aicli/commands/`, `db/`, `services/`)
- [x] `CLAUDE.md`, `knowledge/`, `.claude/commands/start.md`
- [x] `aicli/db/models.py` — modelos `Project` y `Module` con SQLModel
- [x] `aicli/db/__init__.py` — SQLite en `~/.mycontext/ctx.db` (migrado desde MySQL)
- [x] Sistema de logs en `~/.mycontext/aicli.log`
- [x] API key flow en primera ejecución (questionary)
- [x] Selector de proyecto con menú interactivo (pyfiglet + questionary)
- [x] Loop de menú — vuelve al menú después de cada comando
- [x] `.exe` generado con PyInstaller (`ctx.spec`)

---

## Completado — Comandos CLI

### `ctx init`
- [x] Detecta stack automáticamente (Python, Laravel, Next.js, PHP, Go, Rust, etc.)
- [x] Modo normal: una sola llamada Claude que identifica Y documenta módulos (DEC-010)
- [x] Modo `--zona <carpeta>`: documenta solo esa subcarpeta
- [x] Modo `--reciente N`: documenta archivos modificados en los últimos N días (git log)
- [x] Modo `--arquitectura`: lee código real de carpetas de nivel 1, identifica módulos reales
- [x] Proyecto grande (>500 archivos): muestra guía interactiva con questionary
- [x] Proyecto existente: actualización incremental con señal de frescura (`last_updated_at`)
- [x] Progreso en vivo: muestra cada módulo conforme se documenta con tokens usados
- [x] Documentación almacenada espejando estructura del proyecto (`modulo/archivo.md`)
- [x] Agente orquestador por zonas para proyectos >80 archivos de código (DEC paralela)
- [x] `analizar_y_documentar` con `_reparar_json` como safety net para JSON inválido

### `ctx task`
- [x] Extended thinking para detección de módulos relevantes (DEC-015)
- [x] Genera task brief técnico antes de lanzar Claude Code (DEC-016)
- [x] Acepta `--archivo modulo/archivo.php` para anclar el contexto al archivo exacto
- [x] Si se pasa `--archivo`, ese módulo siempre se incluye sin importar el filtrado
- [x] Muestra panel con módulos seleccionados y plan antes de abrir Claude Code
- [x] Menú pregunta tanto descripción como ruta del archivo

### `ctx module add`
- [x] Acepta solo la ruta `modulo/archivo.php` (nombre derivado del stem)
- [x] Almacena documentación en `~/.mycontext/projects/<id>/modulo/archivo.md`
- [x] Detecta si el módulo ya existe y lo actualiza si cambió

### `ctx claude`
- [x] Carga contexto completo de todos los módulos del proyecto
- [x] Lanza Claude Code con `session_context.md`

### `ctx snapshot`
- [x] Copia `~/.mycontext/projects/<id>/` a `~/.mycontext/snapshots/<id>/<timestamp>/`

### `ctx status`
- [x] Muestra tabla de módulos documentados con nombre, descripción y archivo

---

## Completado — Servicios

### `indexer.py`
- [x] `_cargar_ignorar()`: lee `.gitignore` + mínimo universal (DEC-014)
- [x] `EXTENSIONES_NO_CODIGO`: blocklist en vez de allowlist (DEC-013)
- [x] `_ordenar_por_relevancia()`: raíz primero, más pequeños primero
- [x] `analizar_y_documentar()`: análisis + documentación en una sola llamada
- [x] `_indexar_secuencial()`: fallback si JSON falla después de reparación
- [x] `documentar_arquitectura()`: lee código real de cada carpeta nivel 1 (DEC-012)
- [x] `indexar_proyecto_orquestado()`: agente por zona con paralelismo (ThreadPoolExecutor)
- [x] `obtener_arbol_zona()`: escanea subcarpeta específica
- [x] `obtener_archivos_recientes()`: usa git log para archivos activos
- [x] `MAX_ARBOL_ENTRADAS = 300`: previene prompts masivos en proyectos grandes
- [x] `ESPERA_INICIAL = 60`, `MAX_REINTENTOS = 4`: backoff robusto para rate limit

### `zone_detector.py`
- [x] `detectar_zonas()`: Claude detecta zonas dinámicamente según estructura real
- [x] Sin listas hardcodeadas de carpetas — funciona para cualquier stack

### `builder.py`
- [x] `construir_contexto()`: lee `.md` de módulos relevantes y arma el contexto

### `caller.py`
- [x] `lanzar_claude()`: escribe `session_context.md` con Contexto → Plan → Archivo → Tarea
- [x] Búsqueda automática de `claude.cmd` en rutas conocidas de Windows (APPDATA/npm/)
- [x] Diagnóstico interactivo si Claude no se encuentra: found-but-PATH vs not-installed
- [x] Opción de reintentar sin re-correr la tarea

### `ctx retomar` (desde menú)
- [x] Lista tickets activos de los últimos 7 días
- [x] Muestra historial de rondas anteriores antes de arrancar
- [x] Pide motivo de reapertura (comentario de QA), imagen opcional, archivo opcional
- [x] Inyecta historial en `session_context.md` entre contexto y plan
- [x] Guarda `ticket_activo.json` para que `ctx sync` capture el motivo al cerrar

### `ctx sync` — captura de ticket
- [x] Pregunta número de ticket Jira al final del flujo
- [x] Pre-rellena con el ticket activo si viene de `ctx retomar`
- [x] Guarda ronda con archivos tocados + mensaje Jira + motivo de reapertura
- [x] Purga automática de tickets sin actividad en 7 días (`tickets.json`)

---

## Pendiente — Validación en campo

- [ ] Verificar `ctx init --arquitectura` en proyecto PHP de 11.000 archivos
- [ ] Verificar `ctx task --archivo modulo/archivo.php` en proyecto PHP
- [ ] Verificar que los módulos se almacenan en estructura `modulo/archivo.md` correctamente
- [ ] Empaquetar `.exe` nuevo con todos los cambios de la sesión 2026-06-14
- [ ] Verificar que `caller.py` encuentra `claude.cmd` en la PC del trabajo

---

## Pendiente — Mejoras identificadas

- [ ] `_guardar_modulos` no verifica duplicados — si se corre `ctx init --zona X` dos veces,
  se crean módulos duplicados en la BD para el mismo `file_path`
- [ ] `ctx status` muestra módulos de TODOS los proyectos, no solo el del directorio actual
- [ ] El stack "desconocido" en PHP puro hace que el agente orquestador tenga menos contexto;
  considerar heurística adicional para detectar PHP sin `composer.json`

---

## Backlog — Fase 2: Portal web

> No iniciar hasta que Fase 1 esté validada con uso real en el proyecto de la empresa.

1. Migrar BD de SQLite a MySQL/PostgreSQL para acceso multi-desarrollador
2. API REST con FastAPI (proyectos, módulos, contenido `.md`)
3. Frontend Next.js — Portal de documentación por módulos
4. Chatbot IA con RAG sobre la documentación generada
5. Sistema de roles: admin, desarrollador, consulta

---

## Decisiones resueltas

- BD: SQLite en `~/.mycontext/ctx.db` (DEC-001)
- Estructura docs: `~/.mycontext/projects/<id>/modulo/archivo.md` (DEC-009)
- Stack detection: heurísticas de archivos en `init.py`
- Señal de frescura: `last_updated_at` float Unix timestamp (DEC-007)
- Filtrado de archivos: blocklist `EXTENSIONES_NO_CODIGO` + `.gitignore` (DEC-013, DEC-014)
- Módulos funcionales vs archivos individuales: `analizar_y_documentar` decide (DEC-010)
- Extended thinking para `ctx task`: `budget_tokens=2000` (DEC-015)
- Frontend Fase 2: Next.js + chatbot RAG (DEC-008)
- Pattern consistente: `modulo/archivo.php` en toda la CLI (DEC-009)

## Decisiones pendientes

- Estrategia para duplicados en `_guardar_modulos`: upsert vs insert siempre
- Estrategia de búsqueda para chatbot RAG: keywords simples vs embeddings vectoriales
- Detección de PHP puro sin `composer.json` para mejorar contexto del agente
