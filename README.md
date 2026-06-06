# AICLI

Motor de contexto inteligente para Claude Code. Elimina el tiempo perdido re-explicando
arquitectura, stack y convenciones al inicio de cada sesion de trabajo.

---

## El problema que resuelve

Claude Code empieza cada sesion desde cero. AICLI conoce cada proyecto activo, su
estructura, esquemas de base de datos, decisiones tecnicas y convenciones del equipo.
Entrega a Claude exactamente el contexto que necesita para la tarea actual, sin repeticion manual.

---

## Comandos

| Comando | Descripcion |
|---------|-------------|
| `ctx init` | Escanea el proyecto activo, detecta stack y genera contexto inicial |
| `ctx status` | Muestra el estado del contexto y los modulos documentados |
| `ctx task <texto>` | Detecta modulos afectados con IA y lanza Claude con contexto especifico |
| `ctx module add` | Documenta un modulo nuevo del proyecto con ayuda de IA |
| `ctx claude` | Inyecta contexto completo y lanza Claude Code como subprocess |
| `ctx snapshot` | Guarda el estado actual del contexto antes de grandes cambios |

---

## Stack

| Libreria | Version | Rol |
|----------|---------|-----|
| Python | 3.11 | Lenguaje base |
| Typer | 0.26 | Estructura de comandos CLI |
| Rich | 15 | Output visual en terminal |
| SQLModel | pendiente | ORM sobre SQLite |
| Anthropic SDK | pendiente | Llamadas a Claude API |
| python-dotenv | pendiente | Manejo de ANTHROPIC_API_KEY |

---

## Instalacion

```bash
# Clonar el repositorio
git clone https://github.com/Alejandro5668/AICLI.git
cd AICLI

# Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar API key
cp ..env.example ..env
# Edita ..env y agrega tu ANTHROPIC_API_KEY
```

---

## Configuracion

Crea un archivo `.env` en la raiz del proyecto:

```
ANTHROPIC_API_KEY=sk-ant-...
```

El knowledge store se guarda en `~/.mycontext/` fuera de cualquier repositorio de cliente.

---

## Estado del proyecto

En desarrollo activo. Ver [TODO.md](TODO.md) para el roadmap detallado y el progreso actual.

---

## Licencia

Uso personal. Sin licencia de distribucion por el momento.