from abc import ABC, abstractmethod


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


class StackAdapter(ABC):
    """Behavior-per-stack: filter noise, detect domains, build context hints."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def encoding(self) -> str: ...

    @property
    def role_template(self) -> str:
        return _GENERIC_ROLE

    @property
    def hints(self) -> str:
        # ponytail: bridge for callers that still access .hints directly
        return self.build_architecture_hint()

    @abstractmethod
    def filter_files(self, tree: list[str]) -> list[str]: ...

    @abstractmethod
    def build_architecture_hint(self) -> str: ...

    def suggest_domains(self, tree: list[str]) -> list[str]:
        return []


class PHPAdapter(StackAdapter):
    _NOISE = {"vendor/", "storage/logs/", "bootstrap/cache/", "node_modules/"}

    @property
    def name(self) -> str: return "php"

    @property
    def encoding(self) -> str: return "latin-1"

    @property
    def role_template(self) -> str: return _PHP_ROLE

    def filter_files(self, tree: list[str]) -> list[str]:
        return [f for f in tree if not any(f.startswith(n) for n in self._NOISE)]

    def build_architecture_hint(self) -> str:
        return (
            "El proyecto sigue el patrón modulo/archivo.php — cada carpeta de nivel 1 puede ser\n"
            "un módulo del sistema o una carpeta de infraestructura (config, assets, libs, etc).\n"
            "Los archivos *_querys.php contienen las queries SQL del módulo."
        )


class LaravelAdapter(StackAdapter):
    _NOISE = {"vendor/", "storage/", "bootstrap/cache/", "node_modules/", "public/build/"}

    @property
    def name(self) -> str: return "laravel"

    @property
    def encoding(self) -> str: return "utf-8"

    def filter_files(self, tree: list[str]) -> list[str]:
        return [f for f in tree if not any(f.startswith(n) for n in self._NOISE)]

    def build_architecture_hint(self) -> str:
        return (
            "Proyecto Laravel. Módulos principales en app/Http/Controllers, app/Models, app/Services.\n"
            "Rutas en routes/. Migraciones en database/migrations/.\n"
            "Seguí las convenciones de Laravel: resourceful controllers, Eloquent ORM."
        )

    def suggest_domains(self, tree: list[str]) -> list[str]:
        domains = []
        if any("app/Http/Controllers" in f for f in tree): domains.append("api")
        if any("app/Models" in f for f in tree):           domains.append("data")
        if any("app/Services" in f for f in tree):         domains.append("services")
        return domains


class NextJSAdapter(StackAdapter):
    _NOISE = {"node_modules/", ".next/", "dist/", "build/", "coverage/", ".turbo/"}

    @property
    def name(self) -> str: return "nextjs"

    @property
    def encoding(self) -> str: return "utf-8"

    def filter_files(self, tree: list[str]) -> list[str]:
        return [f for f in tree if not any(f.startswith(n) for n in self._NOISE)]

    def build_architecture_hint(self) -> str:
        return (
            "Proyecto Next.js. Pages o App Router en app/ o pages/. Componentes en components/.\n"
            "API routes en app/api/ o pages/api/. Lógica compartida en lib/ o utils/.\n"
            "Distinguí Server Components de Client Components ('use client')."
        )

    def suggest_domains(self, tree: list[str]) -> list[str]:
        domains = []
        if any("app/api/" in f or "pages/api/" in f for f in tree): domains.append("api")
        if any("components/" in f for f in tree):                    domains.append("ui")
        if any("lib/" in f or "utils/" in f for f in tree):         domains.append("shared")
        return domains


class PythonAdapter(StackAdapter):
    _NOISE = {
        "__pycache__/", ".venv/", "venv/", ".mypy_cache/",
        ".pytest_cache/", "dist/", "build/", ".ruff_cache/",
    }

    @property
    def name(self) -> str: return "python"

    @property
    def encoding(self) -> str: return "utf-8"

    def filter_files(self, tree: list[str]) -> list[str]:
        return [
            f for f in tree
            if not any(f.startswith(n) for n in self._NOISE)
            and ".egg-info/" not in f
        ]

    def build_architecture_hint(self) -> str:
        return (
            "Proyecto Python. Módulos organizados por responsabilidad.\n"
            "Entrypoints en main.py, __main__.py o setup.py/pyproject.toml.\n"
            "Tests en tests/ o test_*.py."
        )


class GenericAdapter(StackAdapter):
    _NOISE = {"node_modules/", ".git/", "dist/", "build/", "coverage/"}

    @property
    def name(self) -> str: return "generic"

    @property
    def encoding(self) -> str: return "utf-8"

    def filter_files(self, tree: list[str]) -> list[str]:
        return [f for f in tree if not any(f.startswith(n) for n in self._NOISE)]

    def build_architecture_hint(self) -> str:
        return (
            "Proyecto de stack variado. Identificá los módulos de negocio por densidad de código\n"
            "y nombres de carpeta. Descartá carpetas de infraestructura, assets y dependencias."
        )


_REGISTRY: dict[str, type[StackAdapter]] = {
    "php":         PHPAdapter,
    "laravel":     LaravelAdapter,
    "nextjs":      NextJSAdapter,
    "nuxt":        NextJSAdapter,
    "python":      PythonAdapter,
    "react":       GenericAdapter,
    "vue":         GenericAdapter,
    "angular":     GenericAdapter,
    "svelte":      GenericAdapter,
    "javascript":  GenericAdapter,
    "typescript":  GenericAdapter,
    "nodejs":      GenericAdapter,
    "ruby":        GenericAdapter,
    "java":        GenericAdapter,
    "kotlin":      GenericAdapter,
    "go":          GenericAdapter,
    "rust":        GenericAdapter,
    "flutter":     GenericAdapter,
    "elixir":      GenericAdapter,
    "desconocido": GenericAdapter,
}


def get_adapter(stack: str) -> StackAdapter:
    return _REGISTRY.get(stack, GenericAdapter)()


# ponytail: alias — all callers use .encoding/.hints/.role_template which StackAdapter exposes
def get_profile(stack: str) -> StackAdapter:
    return get_adapter(stack)
