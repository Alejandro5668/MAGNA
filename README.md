# AICLI

> Motor de contexto inteligente para Claude Code. Elimina el tiempo perdido re-explicando tu proyecto al inicio de cada sesión.

---

## El problema

Claude Code empieza cada sesión desde cero. Si trabajás en varios proyectos, cada vez que abrís una sesión nueva tenés que re-explicar la arquitectura, el stack, las convenciones del equipo y las decisiones técnicas que ya tomaste. Ese tiempo se pierde.

**AICLI lo resuelve.** Conoce cada proyecto que tenés activo, su estructura, sus módulos documentados y las decisiones técnicas acumuladas. Entrega a Claude exactamente el contexto que necesita, sin repetición manual.

---

## Cómo funciona

```
Tu proyecto activo
       │
       ▼
  ctx init          ← Escanea el proyecto, detecta el stack, registra en la BD
       │
       ▼
  ctx module add    ← Documenta un módulo con ayuda de Claude (descripción, responsabilidad)
       │
       ▼
  ctx status        ← Panel visual: proyectos registrados + módulos documentados
       │
       ▼
  ctx task "..."    ← [próximo] Claude detecta qué módulos afecta tu tarea
       │
       ▼
  ctx claude        ← [próximo] Lanza Claude Code con el contexto pre-cargado
```

El conocimiento de todos tus proyectos vive en `~/.mycontext/` — completamente fuera de cualquier repositorio de cliente. Nunca contamina repos externos.

---

## Comandos

| Comando | Estado | Descripción |
|---------|--------|-------------|
| `ctx init` | ✅ Funcional | Escanea el proyecto activo, detecta el stack, guarda en la BD |
| `ctx status` | ✅ Funcional | Panel Rich con proyectos registrados y módulos documentados |
| `ctx module add` | ✅ Funcional | Documenta un módulo nuevo con ayuda de Claude API |
| `ctx task <texto>` | 🔨 En desarrollo | Detecta módulos afectados con IA, prepara contexto específico |
| `ctx claude` | ⬜ Pendiente | Inyecta contexto completo y lanza Claude Code como subprocess |
| `ctx snapshot` | ⬜ Pendiente | Guarda el estado del contexto antes de grandes cambios |

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/Alejandro5668/AICLI.git
cd AICLI

# 2. Crear entorno virtual
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

---

## Configuración

Creá un archivo `.env` en la raíz del proyecto con estas variables:

```env
# API key de Anthropic (requerida para ctx module add y ctx task)
ANTHROPIC_API_KEY=sk-ant-...

# Conexión a MySQL
DB_USER=root
DB_PASSWORD=tu_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=aicli
```

> La base de datos se crea automáticamente al primer uso. No necesitás correr migraciones manualmente.

---

## Uso rápido

```bash
# Registrar el proyecto actual en el knowledge store
python main.py init

# Ver el estado del contexto
python main.py status

# Documentar un módulo del proyecto
python main.py module add
```

---

## Arquitectura

El sistema tiene tres capas:

```
┌─────────────────────────────────────────────────────┐
│  INDEXADOR                                          │
│  Escanea el proyecto activo                         │
│  Detecta: stack, estructura, archivos clave         │
│  Analiza con Claude API para extraer módulos        │
├─────────────────────────────────────────────────────┤
│  KNOWLEDGE STORE                                    │
│  Base de datos MySQL en localhost                   │
│  Tabla Projects + Tabla Modules                     │
│  Contenido .md guardado en ~/.mycontext/            │
├─────────────────────────────────────────────────────┤
│  OUTPUT LAYER  [en construcción]                    │
│  Ensambla CLAUDE.md optimizado por sesión           │
│  Entrega contexto dinámico según la tarea actual    │
└─────────────────────────────────────────────────────┘
```

**Detección de stack automática:** AICLI identifica el lenguaje/framework de un proyecto leyendo sus archivos de configuración (`requirements.txt` → Python, `package.json` → Node, `composer.json` → Laravel, `pom.xml` → Java, y más).

---

## Stack tecnológico

| Librería | Versión | Rol |
|----------|---------|-----|
| Python | 3.11 | Lenguaje base |
| Typer | 0.26 | Estructura de comandos CLI (type hints, `--help` automático) |
| Rich | 15 | Output visual en terminal (paneles, tablas, spinners) |
| SQLModel | 0.0.38 | ORM sobre MySQL (SQLAlchemy + Pydantic combinados) |
| Anthropic SDK | 0.107 | Llamadas a Claude API para análisis de módulos |
| python-dotenv | 1.2 | Manejo seguro de credenciales desde `.env` |
| httpx | 0.28 | HTTP client |

---

## Estructura del proyecto

```
AICLI/
├── aicli/
│   ├── commands/
│   │   ├── init.py          # ctx init — registra proyecto activo
│   │   ├── status.py        # ctx status — panel de estado
│   │   └── module.py        # ctx module add — documenta módulo con IA
│   ├── db/
│   │   ├── models.py        # Modelos Project y Module (SQLModel)
│   │   └── __init__.py      # Conexión a MySQL + init_db()
│   └── services/
│       └── indexer_service.py  # Detección de stack + análisis con Claude
├── knowledge/               # Documentación del propio proyecto AICLI
│   ├── decisions.md         # Decisiones técnicas y su justificación
│   ├── patterns.md          # Patrones de código establecidos
│   └── progress.md          # Estado actual
├── main.py                  # Entry point — app Typer registra todos los comandos
├── requirements.txt
└── CLAUDE.md                # Contexto del proyecto para sesiones Claude Code
```

---

## Estado del desarrollo

```
Fase 0 — Entorno base          ✅
Fase 1 — Typer (comandos CLI)  ✅
Fase 2 — Rich (presentación)   ✅
Fase 3 — SQLModel + BD         ✅
Fase 4 — Capa de servicios     ✅
Fase 5 — Anthropic SDK + IA    🔨  ← acá estamos
Fase 6 — ctx claude (E2E)      ⬜
```

Ver [TODO.md](TODO.md) para el roadmap detallado con tareas por fase.

---

## Licencia

Uso personal. Sin licencia de distribución por el momento.