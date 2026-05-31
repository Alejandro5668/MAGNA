# AICLI — Motor de Contexto Inteligente para Claude Code

## Qué es este proyecto

CLI personal en Python que actúa como capa de contexto entre el desarrollador y Claude Code.
Elimina el tiempo perdido re-explicando arquitectura, stack y convenciones en cada sesión nueva.

## El problema que resuelve

Cada sesión de Claude Code empieza desde cero. AICLI conoce cada proyecto activo, su
estructura modular, esquemas SQL, convenciones del equipo y decisiones técnicas acumuladas.
Entrega a Claude exactamente el contexto que necesita para la tarea actual, ni más ni menos.

## Stack tecnológico

| Librería | Versión | Rol |
|----------|---------|-----|
| Python | 3.11 | Lenguaje base |
| Typer | 0.26 | Estructura de comandos CLI (type hints, --help automático) |
| Rich | 15 | Output visual en terminal (paneles, tablas, colores, spinners) |
| SQLModel | pendiente | ORM sobre SQLite (SQLAlchemy + Pydantic combinados) |
| Anthropic SDK | pendiente | Llamadas a Claude API |
| httpx | pendiente | HTTP client (integraciones futuras) |
| python-dotenv | pendiente | Manejo seguro de ANTHROPIC_API_KEY |

## Arquitectura — 3 capas

```
┌──────────────────────────────────────────────┐
│  1. INDEXADOR                                │
│     Escanea el proyecto activo               │
│     Detecta: stack, estructura, dependencias │
├──────────────────────────────────────────────┤
│  2. KNOWLEDGE STORE                          │
│     SQLite en ~/.mycontext/                  │
│     Módulos atómicos por proyecto            │
│     Reutilización de patrones entre proyectos│
├──────────────────────────────────────────────┤
│  3. OUTPUT LAYER                             │
│     Genera CLAUDE.md optimizado por sesión   │
│     Ensambla contexto dinámico según tarea   │
└──────────────────────────────────────────────┘
```

## Comandos CLI

| Comando | Descripción |
|---------|-------------|
| `ctx init` | Escanea proyecto activo, detecta stack, genera CLAUDE.md inicial |
| `ctx claude` | Inyecta contexto completo y lanza Claude Code como subprocess |
| `ctx task <texto>` | Detecta módulos afectados con IA, lanza Claude con contexto específico |
| `ctx module add` | Documenta un módulo nuevo del proyecto con ayuda de IA |
| `ctx status` | Panel Rich: estado del contexto, módulos documentados, tokens estimados |
| `ctx snapshot` | Guarda estado actual del contexto antes de grandes cambios |

`ctx task` reemplaza la integración con Jira en las fases iniciales. El desarrollador
describe la tarea en texto libre y AICLI detecta los módulos relevantes.

## Estructura del proyecto

```
AICLI/
├── aicli/
│   ├── __init__.py          # Versión del paquete
│   ├── commands/            # Un archivo por comando CLI
│   │   └── __init__.py
│   ├── db/                  # Modelos SQLModel + conexión SQLite
│   │   └── __init__.py
│   └── services/            # Lógica de negocio (indexer, builder, caller)
│       └── __init__.py
├── knowledge/               # Documentación del proyecto para sesiones Claude
│   ├── decisions.md         # Decisiones técnicas y su justificación
│   ├── patterns.md          # Patrones de código establecidos en este proyecto
│   └── progress.md          # Estado actual: qué está hecho y qué sigue
├── .claude/
│   └── commands/
│       └── start.md         # Comando /project:start
├── main.py                  # Entry point — app Typer registra todos los comandos
├── requirements.txt         # Dependencias del proyecto
└── CLAUDE.md                # Este archivo
```

## Almacenamiento

Todo el conocimiento vive en `~/.mycontext/` — completamente fuera de cualquier repositorio
de cliente. La base de datos SQLite de AICLI nunca contamina repos externos.

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
- Strings en español cuando son mensajes para el usuario, inglés para código
- Type hints en todas las funciones públicas

## Para empezar una sesión de trabajo

Ejecuta `/project:start` para obtener el resumen del estado actual, los gaps de
documentación identificados y el siguiente paso concreto recomendado.
