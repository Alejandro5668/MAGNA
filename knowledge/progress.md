# Estado del Proyecto

Última actualización: 2026-06-11

---

## Completado

- [x] Entorno virtual creado en PyCharm
- [x] Repositorio Git inicializado y conectado a GitHub
- [x] Todas las dependencias instaladas: `typer`, `rich`, `sqlmodel`, `anthropic`, `httpx`, `python-dotenv`, `PyMySQL`
- [x] Estructura de carpetas del proyecto creada (`aicli/`, `commands/`, `db/`, `services/`)
- [x] `CLAUDE.md` con contexto completo del proyecto
- [x] `knowledge/` con decisions, patterns, progress y commands
- [x] `.claude/commands/start.md` — comando `/start`
- [x] `main.py` — app Typer funcional con comandos `hello` y `bienvenido` (prueba)
- [x] `aicli/db/models.py` — modelos `Project` y `Module` con SQLModel
- [x] `aicli/db/__init__.py` — conexión MySQL con `create_engine` + `init_db()`
- [x] `aicli/commands/status.py` — muestra panel con count de proyectos y tabla de módulos
- [x] `aicli/commands/init.py` — registra proyecto activo en BD (detecta stack, guarda path)
- [x] `aicli/commands/module.py` — documenta módulo con IA (Anthropic SDK integrado)
- [x] `aicli/services/indexer.py` — analiza proyecto con Claude, genera contenido .md por módulo

---

## En progreso

- [ ] Verificar que `ctx init` y `ctx status` funcionan end-to-end contra la BD MySQL

---

## Siguiente paso — Señal de frescura (DEC-007)

Esta es la base de la filosofía de documentación viva del proyecto. Debe implementarse
antes de avanzar con `ctx task` o `ctx claude` porque todos esos comandos dependen de
que la documentación esté actualizada.

**Archivos a modificar:**

1. **`aicli/db/models.py`** — agregar campo al modelo `Module`:
   ```python
   last_updated_at: float | None = Field(default=None)
   ```

2. **`aicli/services/indexer.py`** — agregar función de comparación:
   ```python
   def modulo_necesita_actualizacion(file_path, proyecto_path, modulo_existente):
       if modulo_existente is None or modulo_existente.last_updated_at is None:
           return True
       ruta = proyecto_path / file_path
       if not ruta.exists():
           return False
       return os.path.getmtime(ruta) > modulo_existente.last_updated_at
   ```

3. **`aicli/commands/init.py`** — cambiar flujo de "proyecto ya existe → error" a:
   - Módulo sin cambios → skip, mostrar `✓ archivo.py — sin cambios`
   - Módulo modificado → re-documentar con Claude, actualizar `last_updated_at`
   - Archivo nuevo → documentar como módulo nuevo

4. **`aicli/commands/module.py`** — cambiar flujo de "módulo ya documentado → error" a:
   - Si cambió → re-documentar, actualizar `last_updated_at`
   - Si no cambió → informar "ya está al día, no hay cambios desde la última documentación"

5. **Migración de BD** — ejecutar `ALTER TABLE module ADD COLUMN last_updated_at DOUBLE NULL;`
   en MySQL, o recrear las tablas con `init_db()`.

---

## Backlog — Fase 1: CLI completa

> Completar esto antes de tocar el frontend. La calidad de la documentación generada
> determina la calidad de todo lo que viene después.

1. **Migrar BD de MySQL a SQLite** (DEC-001 corregida) ← PRIMERO
   - Actualizar `aicli/db/__init__.py`: reemplazar `mysql+pymysql://...` por
     `sqlite:///{Path.home()}/.mycontext/ctx.db`
   - Eliminar variables `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` del `.env`
   - Eliminar `PyMySQL` de `requirements.txt`
   - Verificar que `init_db()` crea el archivo SQLite correctamente al arrancar

2. **Señal de frescura** (DEC-007)
   - Agregar `last_updated_at: float | None` al modelo `Module` en `models.py`
   - Agregar `category: str` y `domain: str | None` al modelo `Module` (DEC-008)
   - Función `modulo_necesita_actualizacion()` en `indexer.py`
   - Refactorizar `init.py`: proyecto ya registrado → actualizar en lugar de error
   - Refactorizar `module.py`: módulo ya documentado → actualizar si cambió

2. **`services/builder.py`** — ensambla contexto desde los .md de módulos relevantes
   - Recibe lista de módulos, lee sus `.md`, devuelve bloque de texto para Claude

3. **`services/caller.py`** — lanza `claude` como subprocess con contexto inyectado

4. **Comando `ctx task <texto>`** — el comando más importante
   - Detecta módulos afectados con IA
   - Llama a `builder` con esos módulos
   - Lanza Claude Code con el contexto específico

5. **Comando `ctx claude`** — contexto completo + Claude Code
   - Igual que `ctx task` pero sin filtrado, inyecta todos los módulos

6. **Comando `ctx snapshot`** — punto de restauración del knowledge store
   - Copia `~/.mycontext/projects/<id>/` a `~/.mycontext/snapshots/<id>/<timestamp>/`

---

## Backlog — Fase 2: Portal web

> No iniciar hasta que Fase 1 esté validada con uso real.

1. **API REST con FastAPI**
   - Expone proyectos, módulos y contenido `.md` al frontend
   - Endpoint de búsqueda full-text sobre nombre y descripción de módulos
   - Endpoint para el chatbot: recibe pregunta, devuelve módulos relevantes + respuesta Claude

2. **Frontend Next.js — Portal de documentación**
   - Vista de proyectos registrados
   - Vista de módulos por proyecto, agrupados por `category` y `domain`
   - Buscador sobre toda la base de conocimiento
   - Diseño personalizable (colores, logo) por organización

3. **Chatbot IA con RAG**
   - El usuario pregunta en lenguaje natural
   - El sistema busca módulos relevantes en MySQL por similitud semántica o keywords
   - Lee los `.md` correspondientes y los pasa a Claude como contexto
   - Devuelve la respuesta en la interfaz web

4. **Sistema de roles y acceso**
   - No toda la documentación es pública para todos los usuarios de la organización
   - Roles básicos: admin, desarrollador, consulta

---

## Decisiones resueltas

- BD: SQLite (no MySQL) — sin servidor, archivo en ~/.mycontext/ctx.db (DEC-001)
- Schema `modules`: id, project_id (FK), name, description, file_path, content_path, created_at, last_updated_at, category, domain
- Detección de stack: heurísticas de archivos en `init.py`
- Señal de frescura: `last_updated_at` float Unix timestamp vs `os.path.getmtime()` (DEC-007)
- Política de actualización: ningún comando bloquea con "ya existe" — todos actualizan si hay cambios
- Frontend: Next.js con chatbot RAG sobre la documentación generada por CLI (DEC-008)
- Arquitectura: CLI → MySQL+.md → FastAPI → Next.js (las capas son independientes y reemplazables)

## Decisiones pendientes

- Definir cómo estructurar el contexto que se inyecta a Claude en `ctx task` (qué incluir, en qué orden, límite de tokens)
- Definir estrategia de búsqueda para el chatbot RAG: keywords simples vs embeddings vectoriales
