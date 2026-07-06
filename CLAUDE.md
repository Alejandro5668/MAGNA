# MAGNA — Motor de Contexto Inteligente para Claude Code

## Qué es este proyecto

CLI en Python que actúa como capa de contexto entre el desarrollador y Claude Code.
Elimina el tiempo perdido re-explicando arquitectura, stack y convenciones en cada sesión nueva.
El knowledge store vive en `~/.mycontext/` — completamente fuera de cualquier repositorio de cliente.

## Stack tecnológico

| Librería | Versión | Rol |
|----------|---------|-----|
| Python | 3.11+ | Lenguaje base |
| Typer | 0.26 | Estructura de comandos CLI |
| Rich | 15 | Output visual — paneles, tablas, markup |
| Textual | 8.2.8 | TUI completa — dashboard, animaciones, paleta Noche Estrellada |
| SQLModel + SQLite | 0.0.38 | Knowledge store local en `~/.mycontext/` |
| Anthropic SDK | 0.107 | Claude API — análisis, documentación, extended thinking |
| python-dotenv | instalado | Manejo seguro de ANTHROPIC_API_KEY |

## Comandos CLI

| Comando | Descripción |
|---------|-------------|
| `ctx init` | Escanea proyecto activo, detecta stack, documenta arquitectura con IA |
| `ctx file <carpeta>` | Documenta en profundidad una zona específica del proyecto |
| `ctx archive <ruta>` | Analiza y documenta un archivo individual en detalle |
| `ctx task "texto"` | Detecta módulos relevantes con extended thinking, genera plan técnico, lanza Claude |
| `ctx sync` | Detecta cambios con git, actualiza docs, genera memoria del caso + mensaje Jira |
| `ctx proyecto` | Genera PROYECTO.md con conocimiento estructural inferido del código |
| `ctx retomar` | Retoma ticket reabierto por QA con historial de rondas anteriores |
| `ctx claude` | Lanza Claude Code con el contexto completo del proyecto |
| `ctx profile` | Muestra perfil de stack activo y gestiona rol.md |
| `ctx status` | Arquitectura documentada del proyecto agrupada por carpeta |

## Estructura del proyecto

```
MAGNA/
├── aicli/
│   ├── commands/
│   │   ├── init.py        # ctx init     — mapea arquitectura del proyecto
│   │   ├── file_cmd.py    # ctx file     — documenta una zona en profundidad
│   │   ├── archive.py     # ctx archive  — analiza un archivo individual
│   │   ├── sync.py        # ctx sync     — sincroniza docs post-tarea
│   │   ├── proyecto.py    # ctx proyecto — genera PROYECTO.md
│   │   ├── task.py        # ctx task     — extended thinking + brief técnico
│   │   ├── claude_cmd.py  # ctx claude   — lanza Claude Code con contexto completo
│   │   ├── profile.py     # ctx profile  — perfil de stack + gestión de rol.md
│   │   └── status.py      # ctx status   — arquitectura documentada por carpeta
│   ├── db/
│   │   ├── models.py      # Modelos Project, Module, Activity (SQLModel)
│   │   └── migrations.py  # Migraciones de esquema SQLite
│   ├── services/
│   │   ├── indexer.py     # Análisis e indexación con Claude API
│   │   ├── stack_profile.py # StackProfile dataclass — perfiles por stack
│   │   ├── builder.py     # Ensambla session_context.md por sesión
│   │   ├── caller.py      # Lanza Claude Code como subprocess
│   │   ├── activity.py    # Registro de actividad para el dashboard TUI
│   │   └── tickets.py     # Historial de tickets con purga automática
│   └── tui/
│       ├── app.py         # TUI Textual — MainScreen, ProjectScreen, modales
│       ├── theme.py       # Paleta Noche Estrellada + funciones de output Rich
│       └── output_screen.py # CommandOutputScreen + TuiConsole (Option B)
├── tests/
│   └── test_commands.py   # 23 smoke tests
├── prompts/               # Documentación de los prompts usados en indexer.py
├── knowledge/             # Decisiones técnicas y patrones del proyecto
│   ├── decisions.md       # DEC-001 a DEC-060 — decisiones con justificación
│   ├── patterns.md        # Patrones de código establecidos
│   └── commands.md        # Comandos disponibles y cuándo usarlos
├── .claude/
│   └── commands/
│       └── start.md       # Comando /project:start
├── main.py                # Entry point — lanza MagnaApp (Textual)
├── requirements.txt       # Dependencias de runtime
└── ctx.spec               # Configuración PyInstaller para .exe
```

## Almacenamiento

```
~/.mycontext/
├── ctx_bd.db              # Base de datos SQLite — proyectos y módulos
├── aicli_log.log          # Logs de operaciones
├── rol.md                 # Rol de senior developer inyectado en cada sesión
├── .env                   # ANTHROPIC_API_KEY (nunca se commitea)
├── evidencias/            # Capturas de pantalla temporales (purga 7 días)
├── tickets.json           # Historial de tickets reabiertos (purga 7 días)
└── projects/
    └── <id>/
        ├── PROYECTO.md    # Conocimiento estructural del proyecto
        └── modulo/
            └── archivo.md # Documentación de cada módulo
```

## Filosofía de desarrollo

- **Simplicidad primero.** Si algo puede ser simple, debe serlo.
- **Sin abstracciones prematuras.** Se abstrae cuando hay duplicación real, no hipotética.
- **Un archivo, una responsabilidad.** Cada módulo hace una cosa y la hace bien.
- **Comentarios solo para el "por qué".** El código explica el qué; los comentarios explican
  por qué se tomó una decisión no obvia.

## Lo que NO hacemos

- No instalamos dependencias sin razón clara y justificada
- No creamos comandos que nadie va a usar todavía
- No usamos async si sync es suficiente para el caso de uso
- No agregamos validaciones para casos que no pueden ocurrir en este contexto
- No usamos abstracciones antes de que haya dos implementaciones concretas

## Convenciones de código

- Nombres de variables y funciones en `snake_case`
- Nombres de clases en `PascalCase`
- Constantes en `UPPER_SNAKE_CASE`
- Mensajes para el usuario en español, código en inglés
- Type hints en todas las funciones públicas

## Para empezar una sesión de trabajo

Ejecutá `/project:start` para obtener el resumen del estado actual, los gaps de
documentación identificados y el siguiente paso concreto recomendado.
