# Patrones de Código

Patrones establecidos en este proyecto. Cada patrón incluye el código de referencia
y la razón por la que lo usamos así. Actualizar cuando un patrón evolucione.

---

## PAT-001 — Estructura de un comando Typer

Cada comando vive en su propio archivo dentro de `aicli/commands/`.
El comando se registra en `main.py` como sub-aplicación.

```python
# aicli/commands/status.py
import typer
from rich.console import Console

console = Console()
app = typer.Typer()

@app.command()
def status():
    """Muestra el estado actual del contexto y módulos documentados."""
    console.print("[bold green]Estado del contexto[/bold green]")
```

```python
# main.py — registro del comando
from aicli.commands import status
app.add_typer(status.app, name="status")
```

**Por qué así:** Mantiene cada comando aislado y testeable por separado. `main.py` solo
orquesta, no contiene lógica.

---

## PAT-002 — Output con Rich

Usamos Rich para todo el output visible al usuario. Nunca `print()` desnudo en comandos.

```python
from rich.console import Console
from rich.panel import Panel

console = Console()

# Para mensajes simples con color
console.print("[bold green]✓[/bold green] Proyecto inicializado")

# Para información estructurada
console.print(Panel("Contenido del panel", title="Título", border_style="blue"))

# Para errores
console.print("[bold red]Error:[/bold red] No se encontró el proyecto", style="red")
```

**Por qué así:** Consistencia visual en toda la CLI. El usuario siempre recibe output
formateado de la misma manera.

---

## PAT-003 — Manejo de errores en comandos

Los comandos no lanzan excepciones al usuario directamente. Capturamos, mostramos
mensaje claro con Rich, y salimos con código de error apropiado.

```python
@app.command()
def init():
    try:
        resultado = alguna_operacion()
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(code=1)
```

**Por qué así:** Los stack traces de Python confunden a usuarios finales. Un mensaje
claro en rojo es suficiente. `raise typer.Exit(code=1)` permite que scripts detecten el fallo.

---

## PAT-004 — Configuración con python-dotenv

La API key de Anthropic se carga desde `.env` en el directorio de trabajo o desde
variables de entorno del sistema. Nunca hardcodeada, nunca en el knowledge store.

```python
# Al inicio de la aplicación (main.py o en el servicio que usa la API)
from dotenv import load_dotenv
import os

load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")

if not api_key:
    console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY no configurada")
    raise typer.Exit(code=1)
```

**Por qué así:** `.env` está en `.gitignore`. El usuario puede tener la key en su entorno
del sistema o en un `.env` local sin riesgo de commitearla accidentalmente.

---

## PAT-005 — Type hints en todas las funciones públicas

```python
# Correcto
def get_project(project_id: int) -> dict | None:
    ...

def save_module(name: str, content: str, project_id: int) -> bool:
    ...

# Incorrecto — sin type hints
def get_project(id):
    ...
```

**Por qué así:** Typer los usa para generar la CLI automáticamente. Los IDEs los usan
para autocompletion. Los errores de tipos se detectan antes en desarrollo.
