# Estado del Proyecto

Última actualización: 2026-05-30

---

## Completado

- [x] Entorno virtual creado en PyCharm
- [x] Repositorio Git inicializado y conectado a GitHub
- [x] Typer 0.26 instalado
- [x] Rich 15 instalado
- [x] Estructura de carpetas del proyecto creada (`aicli/`, `commands/`, `db/`, `services/`)
- [x] `CLAUDE.md` con contexto completo del proyecto
- [x] `knowledge/` con decisions, patterns y progress
- [x] `.claude/commands/start.md` — comando `/project:start`

---

## En progreso

- [ ] Instalar dependencias pendientes: `sqlmodel`, `anthropic`, `httpx`, `python-dotenv`
- [ ] Crear `main.py` con app Typer y comando `hello` funcional

---

## Siguiente paso

**Instalar las 4 dependencias pendientes y crear main.py.**

Orden sugerido:
1. Instalar: `pip install sqlmodel anthropic httpx python-dotenv`
2. Actualizar `requirements.txt` con las versiones exactas
3. Crear `main.py` con la app Typer y un comando `hello` que use Rich
4. Verificar que `python main.py hello` funciona correctamente

---

## Backlog (ordenado por prioridad)

1. **Comando `ctx status`** — más simple de implementar, no requiere SQLite ni API
2. **Setup de SQLite** — modelos SQLModel, conexión, migración inicial
3. **Comando `ctx init`** — escanea proyecto activo, detecta stack
4. **Comando `ctx module add`** — documenta módulo con IA
5. **Comando `ctx task`** — detecta módulos afectados, lanza Claude con contexto
6. **Comando `ctx claude`** — inyecta contexto completo, lanza Claude Code
7. **Comando `ctx snapshot`** — guarda estado del contexto

---

## Decisiones pendientes

- Definir schema exacto de la tabla `modules` en SQLite
- Definir el formato de un módulo atómico de conocimiento
- Decidir cómo detectar el stack de un proyecto (heurísticas de archivos)
