<div align="center">
  <img src="images/logo.png" width="120" alt="AICLI logo" />
  <h1>AICLI</h1>
  <p><strong>Motor de contexto inteligente para Claude Code</strong></p>
  <p>Elimina el tiempo perdido re-explicando tu proyecto al inicio de cada sesión de IA.</p>
</div>

---

## El problema

Claude Code arranca cada sesión desde cero. Sin contexto, los primeros minutos se van en explorar el proyecto, entender la arquitectura y recordar las convenciones del equipo. En un proyecto de miles de archivos, ese costo se repite en cada ticket.

**AICLI lo resuelve.** Documenta tu proyecto una sola vez y entrega a Claude exactamente el contexto que necesita para la tarea actual — ni más ni menos.

---

## Flujo de trabajo

```
ctx init          →  Mapea la arquitectura del proyecto en ~30 segundos
ctx proyecto      →  Genera conocimiento estructural (SQL, convenciones, módulos)
ctx file <zona>   →  Profundiza en la carpeta que vas a tocar
                          ↓
ctx task "ticket" →  Detecta módulos relevantes + genera plan técnico
                          ↓
                   Claude Code abre con todo el contexto cargado
                          ↓
ctx sync          →  Actualiza la documentación con lo que cambió
```

El conocimiento de todos tus proyectos vive en `~/.mycontext/` — completamente fuera de cualquier repositorio. Nunca contamina repos externos.

---

## Comandos

| Comando | Descripción |
|---------|-------------|
| `ctx init` | Mapea la arquitectura del proyecto activo con IA |
| `ctx proyecto` | Genera `PROYECTO.md` con conocimiento estructural inferido del código |
| `ctx file <carpeta>` | Documenta en profundidad una zona específica del proyecto |
| `ctx archive <ruta>` | Analiza y documenta un archivo individual en detalle |
| `ctx task "descripción"` | Detecta módulos relevantes con extended thinking, genera plan técnico y lanza Claude Code |
| `ctx sync` | Detecta cambios con git y actualiza la documentación post-tarea |
| `ctx claude` | Lanza Claude Code con el contexto completo del proyecto |
| `ctx status` | Muestra los módulos documentados del proyecto activo |
| `ctx snapshot` | Guarda un punto de restauración del knowledge store |

---

## Contexto que recibe Claude en cada sesión

```
rol.md            ←  Rol de senior developer + reglas de comportamiento
PROYECTO.md       ←  Patrón SQL real, convenciones de archivos, módulos principales
Módulos           ←  Documentación específica de los módulos relevantes para la tarea
Plan técnico      ←  Pasos concretos generados antes de abrir Claude Code
Archivo de entrada ← El archivo exacto donde ocurre el problema
```

---

## Instalación

**Opción A — Ejecutable directo (recomendado)**

Descargá `ctx.exe` y ejecutalo. La primera vez te pedirá tu API key de Anthropic.

**Opción B — Desde el código fuente**

```bash
git clone https://github.com/Alejandro5668/AICLI.git
cd AICLI
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
python main.py
```

Necesitás una [API key de Anthropic](https://console.anthropic.com) para usar los comandos de IA.

---

## Stack

| | |
|---|---|
| **Python 3.11** | Lenguaje base |
| **Typer** | Estructura de comandos CLI |
| **Rich** | Output visual en terminal |
| **SQLModel + SQLite** | Knowledge store local en `~/.mycontext/ctx.db` |
| **Anthropic SDK** | Claude API — análisis, documentación y extended thinking |
| **questionary** | Menú interactivo con flechas |

---

## Arquitectura

```
aicli/
├── commands/
│   ├── init.py        # ctx init — mapea arquitectura
│   ├── file_cmd.py    # ctx file — documenta zona
│   ├── archive.py     # ctx archive — analiza archivo
│   ├── sync.py        # ctx sync — sincroniza post-tarea
│   ├── proyecto.py    # ctx proyecto — genera PROYECTO.md
│   ├── task.py        # ctx task — extended thinking + brief
│   ├── claude_cmd.py  # ctx claude — lanza Claude Code
│   ├── status.py      # ctx status — panel de estado
│   └── snapshot.py    # ctx snapshot — punto de restauración
├── db/
│   └── models.py      # Modelos Project y Module
└── services/
    ├── indexer.py     # Análisis con Claude API
    ├── builder.py     # Ensambla el contexto por sesión
    └── caller.py      # Lanza Claude Code como subprocess
```

---

<div align="center">
  <sub>Hecho por Alejandro Campo</sub>
</div>