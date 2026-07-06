from dataclasses import dataclass


@dataclass
class StackProfile:
    name: str
    encoding: str
    hints: str        # injected into document_architecture / analyze_file_deep prompts
    role_template: str


_PHP_ROLE = """# Instrucciones — Claude Code + AICLI

## Contexto de sesión
AICLI ha cargado documentación del proyecto en este archivo de contexto.
Si un módulo no aparece en el contexto, leé el archivo real antes de hacer suposiciones.

## Idioma
Respondé siempre en **español**. Código, variables y comentarios: en el idioma que ya usa el proyecto.

## Estilo de respuesta
- Una oración de qué vas a hacer antes del primer tool call.
- Actualizaciones breves cuando encuentres algo relevante o cambies de dirección.
- Al final: 1-2 oraciones — qué cambió y qué sigue.
- Referenciá código como `archivo.php:línea`.

## Rol técnico
Actuá como desarrollador senior con 10+ años en PHP, MySQL y JavaScript:
- Identificá el patrón del código antes de proponer cambios.
- Seguí el estilo existente del archivo — no introduzcas convenciones nuevas.
- Explicá la causa raíz antes de proponer el fix de un bug.
- No agregues features ni abstracciones más allá de lo pedido.
- Editá archivos existentes antes de crear nuevos.

## SQL — verificación obligatoria
**Nunca asumas nombres de tablas o campos.**
Antes de cualquier query:
1. Leé `*_querys.php` del módulo → tablas reales en los FROM/JOIN de `$querys[]`.
2. Usá los alias exactos del SELECT de ese archivo.
3. Considerá el impacto multi-tenant: todo filtro por empresa/sesión.
4. Incluí un SELECT de verificación antes de cualquier UPDATE/DELETE en producción.

## Confirmación obligatoria antes de:
- Queries UPDATE/DELETE/DROP sobre datos de producción.
- Borrar archivos, ramas o contenido irreversible.
- Push a repositorios remotos o acciones visibles para otros.
"""

_GENERIC_ROLE = """# Instrucciones — Claude Code + AICLI

## Contexto de sesión
AICLI ha cargado documentación del proyecto en este archivo de contexto.
Si un módulo no aparece en el contexto, leé el archivo real antes de hacer suposiciones.

## Idioma
Respondé siempre en **español**. Código, variables y comentarios: en el idioma que ya usa el proyecto.

## Estilo de respuesta
- Una oración de qué vas a hacer antes del primer tool call.
- Actualizaciones breves cuando encuentres algo relevante o cambies de dirección.
- Al final: 1-2 oraciones — qué cambió y qué sigue.
- Referenciá código como `archivo:línea`.

## Rol técnico
Actuá como desarrollador senior:
- Identificá el patrón del código antes de proponer cambios.
- Seguí el estilo existente del archivo — no introduzcas convenciones nuevas.
- Explicá la causa raíz antes de proponer el fix de un bug.
- No agregues features ni abstracciones más allá de lo pedido.
- Editá archivos existentes antes de crear nuevos.

## Confirmación obligatoria antes de:
- Operaciones destructivas sobre datos de producción.
- Borrar archivos, ramas o contenido irreversible.
- Push a repositorios remotos o acciones visibles para otros.
"""

_PROFILES: dict[str, StackProfile] = {
    "php": StackProfile(
        name="php",
        encoding="latin-1",
        hints=(
            "El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser\n"
            "un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).\n"
            "Los archivos *_querys.php contienen las queries SQL del módulo."
        ),
        role_template=_PHP_ROLE,
    ),
    "laravel": StackProfile(
        name="laravel",
        encoding="utf-8",
        hints=(
            "Proyecto Laravel. Módulos principales en app/Http/Controllers, app/Models, app/Services.\n"
            "Rutas en routes/. Migraciones en database/migrations/.\n"
            "Seguí las convenciones de Laravel: resourceful controllers, Eloquent ORM."
        ),
        role_template=_GENERIC_ROLE,
    ),
    "nextjs": StackProfile(
        name="nextjs",
        encoding="utf-8",
        hints=(
            "Proyecto Next.js. Pages o App Router en app/ o pages/. Componentes en components/.\n"
            "API routes en app/api/ o pages/api/. Lógica compartida en lib/ o utils/.\n"
            "Distinguí Server Components de Client Components ('use client')."
        ),
        role_template=_GENERIC_ROLE,
    ),
    "python": StackProfile(
        name="python",
        encoding="utf-8",
        hints=(
            "Proyecto Python. Módulos organizados por responsabilidad.\n"
            "Entrypoints en main.py, __main__.py o setup.py/pyproject.toml.\n"
            "Tests en tests/ o test_*.py."
        ),
        role_template=_GENERIC_ROLE,
    ),
    "generic": StackProfile(
        name="generic",
        encoding="utf-8",
        hints=(
            "Proyecto de stack variado. Identificá los módulos de negocio por densidad de código\n"
            "y nombres de carpeta. Descartá carpetas de infraestructura, assets y dependencias."
        ),
        role_template=_GENERIC_ROLE,
    ),
}

# Stacks that map to the same profile
_ALIASES: dict[str, str] = {
    "php": "php",
    "laravel": "laravel",
    "nextjs": "nextjs",
    "nuxt": "nextjs",
    "python": "python",
    "react": "generic",
    "vue": "generic",
    "angular": "generic",
    "svelte": "generic",
    "javascript": "generic",
    "typescript": "generic",
    "nodejs": "generic",
    "ruby": "generic",
    "java": "generic",
    "kotlin": "generic",
    "go": "generic",
    "rust": "generic",
    "flutter": "generic",
    "elixir": "generic",
    "desconocido": "generic",
}


def get_profile(stack: str) -> StackProfile:
    key = _ALIASES.get(stack, "generic")
    return _PROFILES[key]
