# Estado del Proyecto

Última actualización: 2026-06-07

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

---

## En progreso

- [ ] Verificar que `ctx init` funciona end-to-end contra la BD MySQL
- [ ] Verificar que `ctx status` muestra datos reales de la BD

---

## Siguiente paso

**Probar `ctx init` y `ctx status` contra la BD MySQL real.**

1. Asegurarse de que el `.env` tiene `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`
2. Ejecutar `python main.py init` desde un directorio de proyecto
3. Ejecutar `python main.py status` y verificar que el contador de proyectos sube

---

## Backlog (ordenado por prioridad)

1. **Comando `ctx module add`** — documenta módulo con IA (requiere Anthropic SDK)
2. **Comando `ctx task`** — detecta módulos afectados, lanza Claude con contexto
3. **Comando `ctx claude`** — inyecta contexto completo, lanza Claude Code
4. **Comando `ctx snapshot`** — guarda estado del contexto

---

## Decisiones resueltas

- BD: MySQL (no SQLite) — el desarrollador tiene servidor MySQL local disponible
- Schema `modules`: definido en `models.py` — id, project_id (FK), name, description, file_path, created_at
- Detección de stack: heurísticas de archivos en `init.py` — requirements.txt→python, composer.json→laravel, pom.xml→java

## Decisiones pendientes

- Definir el formato de un módulo atómico de conocimiento (contenido del campo `file_path`)
- Decidir cómo estructurar el contexto que se inyecta a Claude en `ctx task`
