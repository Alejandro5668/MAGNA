"""
Grafo multi-agente que reemplaza los dos llamados ciegos y secuenciales de
`ctx task` (`_detect_relevant_modules` → `_generate_task_brief`) por tres
nodos especialistas en paralelo (Detective de Módulos, Historiador de Jira,
Vigía de Tests) que se sintetizan en un único brief.

Solo el Detective usa LangChain (`create_agent`, loop ReAct con
`ChatAnthropic`). Historiador, Vigía y Sintetizador siguen en el SDK plano de
Anthropic vía `indexer._call_claude`, igual que los cambios 1-3.

El grafo y el agente del Detective son singletons perezosos a nivel de
módulo, detrás de imports diferidos — igual que `task.py:40` importa
`embeddings` de forma perezosa.
"""
import contextvars
import logging
from pathlib import Path, PurePosixPath
from typing import TypedDict

from pydantic import BaseModel, Field

from aicli.db.models import Module
from aicli.services.indexer import _call_claude, MODEL_BY_OPERATION

# ── Estado compartido ────────────────────────────────────────────────────────


class TaskGraphState(TypedDict, total=False):
    task_desc: str
    file: str | None
    evidence: str | None
    project_context: str | None
    project_id: int
    repo_root: str
    modules: list[Module]
    candidates: list[Module]
    relevant: list[Module]
    precedent: str
    coverage: str
    brief: str


# ContextVar que expone a las tools del Detective (fuera del `messages` del
# agente) el set de candidatos y la raíz del repo vigentes para la corrida
# actual — se fija al entrar al nodo y se resetea en el `finally`.
_SCOPE: contextvars.ContextVar[dict | None] = contextvars.ContextVar("_SCOPE", default=None)


# ── Detective de Módulos ─────────────────────────────────────────────────────


class seleccionar_modulos(BaseModel):
    """Selección final de los módulos relevantes para la tarea."""

    modules: list[str] = Field(
        ..., description="Nombres exactos de los módulos relevantes, tal como aparecen en el listado."
    )


def _system_blocks(candidates: list[Module], project_context: str | None) -> list[dict]:
    """Reproduce byte-a-byte el bloque de sistema cacheable de la vieja
    `_detect_relevant_modules` (task.py) — solo cambia el transporte."""
    listing_parts = []
    for m in candidates:
        listing_parts.append(f"- {m.name}: {m.description} | archivo: {m.file_path}")
        if m.content_path:
            md_path = Path(m.content_path)
            if md_path.exists():
                snippet = md_path.read_text(encoding="utf-8", errors="replace")[:300].replace("\n", " ")
                listing_parts.append(f"  Contexto: {snippet}")
    listing = "\n".join(listing_parts)

    project_ctx_block = (
        f"\nContexto del proyecto (convenciones, arquitectura, patrones):\n{project_context}\n"
        if project_context else ""
    )

    text = (
        "Tenés que identificar qué módulos de un proyecto de software son relevantes\n"
        "para una tarea específica de desarrollo.\n"
        f"{project_ctx_block}\n"
        f"Módulos disponibles en el proyecto:\n{listing}"
    )
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def _leer_doc_modulo_impl(name: str) -> str:
    scope = _SCOPE.get()
    if not scope:
        return "Módulo no encontrado o sin documentación."
    candidates = scope.get("candidates") or []
    modulo = next((m for m in candidates if m.name == name), None)
    if not modulo or not modulo.content_path:
        return "Módulo no encontrado o sin documentación."
    path = Path(modulo.content_path)
    if not path.exists():
        return "Módulo no encontrado o sin documentación."
    return path.read_text(encoding="utf-8", errors="replace")[:2000]


def _buscar_en_codigo_impl(pattern: str) -> str:
    scope = _SCOPE.get()
    if not scope:
        return "Sin resultados."
    root = scope.get("repo_root")
    if not root:
        return "Sin resultados."
    hits: list[str] = []
    try:
        for path in Path(root).rglob("*"):
            if not path.is_file():
                continue
            if any(part in _IGNORED_DIRS for part in path.parts):
                continue
            try:
                if path.stat().st_size > _MAX_SCAN_FILE_BYTES:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern in line:
                    hits.append(f"{path}:{i}: {line.strip()}")
                    if len(hits) >= 40:
                        break
            if len(hits) >= 40:
                break
    except Exception:
        return "Sin resultados."
    return "\n".join(hits) if hits else "Sin resultados."


def _make_detective_tools():
    """Import diferido de `langchain_core.tools` — mantiene LangChain fuera
    del import top-level del módulo (mirror del patrón perezoso del proyecto)."""
    from langchain_core.tools import tool

    @tool
    def leer_doc_modulo(name: str) -> str:
        """Lee la documentación completa (hasta 2000 caracteres) de un módulo, por su nombre exacto."""
        return _leer_doc_modulo_impl(name)

    @tool
    def buscar_en_codigo(pattern: str) -> str:
        """Busca un patrón literal en el código del repo objetivo (hasta 40 resultados)."""
        return _buscar_en_codigo_impl(pattern)

    return [leer_doc_modulo, buscar_en_codigo]


def _build_detective_agent(model=None):
    from langchain.agents import create_agent
    from langchain.agents.structured_output import ToolStrategy

    if model is None:
        from langchain_anthropic import ChatAnthropic
        # Sin `thinking`: `ToolStrategy` fuerza tool_choice="any", y
        # `langchain_anthropic` descarta ese forzado en silencio (solo emite
        # un warning) cuando `thinking` está activo — rompía la garantía de
        # terminación del loop del Detective.
        model = ChatAnthropic(model="claude-sonnet-5", max_tokens=4000)

    return create_agent(
        model=model,
        tools=_make_detective_tools(),
        response_format=ToolStrategy(seleccionar_modulos),
    )


def _scan_last_tool_call(messages: list, tool_name: str) -> list[str] | None:
    """Fallback de extracción: recorre `messages` en reversa buscando la
    última llamada a `tool_name` — cubre el caso en que `structured_response`
    no se hubiera poblado (mecanismo B del design)."""
    for msg in reversed(messages):
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            continue
        for call in reversed(tool_calls):
            if call.get("name") == tool_name:
                return call.get("args", {}).get("modules")
    return None


def _log_detective_usage(messages: list) -> None:
    from langchain_core.messages import AIMessage

    last_ai = None
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            last_ai = m
            break
    if not last_ai or not last_ai.usage_metadata:
        return
    usage = last_ai.usage_metadata
    details = usage.get("input_token_details") or {}
    logging.info(
        "Claude OK [detective] — input: %d | cache_write: %d | cache_read: %d | output: %d tokens",
        usage.get("input_tokens", 0) or 0,
        details.get("cache_creation", 0) or 0,
        details.get("cache_read", 0) or 0,
        usage.get("output_tokens", 0) or 0,
    )


def _detective_recursion_limit(candidates: list[Module]) -> int:
    """Presupuesto de pasos del Detective escalado a la cantidad de
    candidatos — con tools de a un nombre/patrón por llamada, más
    candidatos necesitan más pasos para explorarlos antes de decidir."""
    return min(24, max(12, len(candidates) + 6))


def _detective(state: TaskGraphState, agent=None) -> dict:
    from langchain_core.messages import SystemMessage, HumanMessage

    candidates = state.get("candidates") or []
    token = _SCOPE.set({"candidates": candidates, "repo_root": state.get("repo_root")})
    try:
        agent = agent or _get_detective_agent()

        file = state.get("file")
        file_context = (
            f"\nEl desarrollador indica que el problema ocurre específicamente en: {file}"
            if file else ""
        )
        user_prompt = f"""Tarea del desarrollador: {state.get('task_desc', '')}{file_context}

Analizá la tarea, entendé qué partes del sistema necesita tocar. Podés usar
leer_doc_modulo para leer la documentación completa de un módulo, o
buscar_en_codigo para buscar un patrón en el código, tantas veces como
necesites. Cuando tengas suficiente información, llamá a la herramienta
terminal seleccionar_modulos con los nombres exactos de los módulos
relevantes.

Seleccioná solo los módulos que realmente necesitarán ser leídos o modificados.
Si no podés filtrar con seguridad, devolvé todos los nombres."""

        sys_msg = SystemMessage(content=_system_blocks(candidates, state.get("project_context")))
        result = agent.invoke(
            {"messages": [sys_msg, HumanMessage(content=user_prompt)]},
            config={"recursion_limit": _detective_recursion_limit(candidates)},
        )

        messages = result.get("messages", [])
        _log_detective_usage(messages)

        sel = result.get("structured_response")
        names = list(sel.modules) if sel else _scan_last_tool_call(messages, "seleccionar_modulos")

        if not names:
            return {"relevant": candidates}
        return {"relevant": [m for m in candidates if m.name in names]}
    except Exception as e:
        logging.warning("Detective de Módulos falló, degradando a candidatos: %s", e)
        return {"relevant": candidates}
    finally:
        _SCOPE.reset(token)


_detective_agent = None


def _get_detective_agent():
    global _detective_agent
    if _detective_agent is None:
        _detective_agent = _build_detective_agent(None)
    return _detective_agent


# ── Historiador de Jira ──────────────────────────────────────────────────────


def _historiador(state: TaskGraphState, call_claude=None) -> dict:
    call_claude = call_claude or _call_claude
    try:
        from aicli.services.embeddings import query_tickets
        from aicli.services.tickets import load_tickets

        tickets = load_tickets()
        precedentes = query_tickets(state.get("project_id"), tickets, state.get("task_desc", ""))
        if not precedentes:
            return {"precedent": "Sin precedentes en el historial de tickets."}

        listado = "\n".join(f"- {p['ticket_id']}: {p['descripcion']}" for p in precedentes)
        prompt = f"""Tarea actual: {state.get('task_desc', '')}

Tickets con precedente similar en este proyecto:
{listado}

Resumí en máximo 3 líneas qué precedente es más relevante y por qué, citando
el ticket concreto."""
        text, _ = call_claude(prompt, context="historiador_precedentes", max_tokens=400, model=MODEL_BY_OPERATION["task_brief"])
        return {"precedent": text.strip()}
    except Exception as e:
        logging.warning("Historiador de Jira falló, degradando: %s", e)
        return {"precedent": "Sin precedentes en el historial de tickets."}


# ── Vigía de Tests ───────────────────────────────────────────────────────────

_IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", ".codegraph"}
_TEST_DIR_SEGMENTS = {"tests", "__tests__", "spec"}
_GENERIC_STEMS = {"index", "utils", "main", "app", "init", "types", "const", "helpers"}
_IMPORT_MARKERS = ("import", "from", "require(", "jest.mock(", 'patch("')
_MAX_TEST_FILES = 400
# Compartido con `_buscar_en_codigo_impl` (Detective) — mismo límite, mismo
# fallo silencioso: archivos sobredimensionados se saltean, nunca se leen.
_MAX_SCAN_FILE_BYTES = 200 * 1024


def _is_test_file(path: Path) -> bool:
    name = path.name
    if name.startswith("test_"):
        return True
    if "_test." in name:
        return True
    parts = name.split(".")
    if len(parts) >= 3 and parts[-2] in ("test", "spec"):
        return True
    if any(seg in _TEST_DIR_SEGMENTS for seg in path.parts):
        return True
    return False


def _discover_test_files(root: Path, limit: int = _MAX_TEST_FILES) -> list[Path]:
    found: list[Path] = []
    try:
        for path in root.rglob("*"):
            if any(part in _IGNORED_DIRS for part in path.parts):
                continue
            if not path.is_file():
                continue
            if not _is_test_file(path):
                continue
            found.append(path)
            if len(found) >= limit:
                break
    except Exception as e:
        logging.warning("Descubrimiento de tests falló: %s", e)
    return found


def _module_forms(file_path: str) -> tuple[list[str], str]:
    posix = PurePosixPath(file_path.replace("\\", "/"))
    no_ext = str(posix.with_suffix(""))
    parts = [p for p in no_ext.split("/") if p]
    stem = parts[-1] if parts else no_ext
    forms = {no_ext}
    if len(parts) >= 2:
        forms.add(".".join(parts))
        forms.add("/".join(parts[-2:]))
    return [f for f in forms if f], stem


def _scan_coverage(test_files: list[Path], modules: list[Module]) -> dict[str, list[tuple[str, int, str]]]:
    coverage: dict[str, list[tuple[str, int, str]]] = {}
    module_forms = {m.name: _module_forms(m.file_path) for m in modules}

    for tf in test_files:
        try:
            if tf.stat().st_size > _MAX_SCAN_FILE_BYTES:
                continue
            text = tf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = text.splitlines()
        for m in modules:
            forms, stem = module_forms[m.name]
            for i, line in enumerate(lines, start=1):
                if any(form in line for form in forms):
                    coverage.setdefault(m.name, []).append((str(tf), i, line.strip()))
                    break
                if (
                    stem and len(stem) >= 4 and stem not in _GENERIC_STEMS
                    and stem in line and any(marker in line for marker in _IMPORT_MARKERS)
                ):
                    coverage.setdefault(m.name, []).append((str(tf), i, line.strip()))
                    break
    return coverage


def _vigia(state: TaskGraphState, call_claude=None) -> dict:
    call_claude = call_claude or _call_claude
    try:
        candidates = state.get("candidates") or []
        repo_root = state.get("repo_root") or str(Path.cwd())
        test_files = _discover_test_files(Path(repo_root))
        coverage = _scan_coverage(test_files, candidates)
        if not coverage:
            return {"coverage": "Sin cobertura de tests detectada."}

        listado = "\n".join(
            f"- {name}: {len(hits)} referencia(s) en {', '.join(sorted({h[0] for h in hits}))}"
            for name, hits in coverage.items()
        )
        prompt = f"Resumí en máximo 3 líneas la cobertura de tests detectada para estos módulos:\n{listado}"
        text, _ = call_claude(prompt, context="vigia_cobertura", max_tokens=400, model=MODEL_BY_OPERATION["task_brief"])
        return {"coverage": text.strip()}
    except Exception as e:
        logging.warning("Vigía de Tests falló, degradando: %s", e)
        return {"coverage": "Sin cobertura de tests detectada."}


# ── Sintetizador ─────────────────────────────────────────────────────────────


def _sintetizador(state: TaskGraphState, call_claude=None) -> dict:
    call_claude = call_claude or _call_claude

    task_desc = state.get("task_desc", "")
    relevant = state.get("relevant") or state.get("candidates") or []
    file = state.get("file")
    evidence = state.get("evidence")
    precedent = state.get("precedent") or "Sin precedentes en el historial de tickets."
    coverage = state.get("coverage") or "Sin cobertura de tests detectada."

    listing = "\n".join(f"- {m.name} ({m.file_path}): {m.description}" for m in relevant)
    file_context = f"\nPunto de entrada específico donde ocurre el problema: {file}" if file else ""
    evidence_block = f"\nEvidencia disponible (imágenes/video/Excel ya analizados):\n{evidence}\n" if evidence else ""

    prompt = f"""Sos un arquitecto de software senior. Un desarrollador va a trabajar en esta
tarea con Claude Code como asistente.

Tarea: {task_desc}{file_context}

Módulos del proyecto involucrados:
{listing}
{evidence_block}
Precedentes de tickets anteriores:
{precedent}

Cobertura de tests detectada:
{coverage}

Generá un plan técnico conciso de máximo 10 líneas que indique:
- Qué hay que revisar o cambiar, empezando por el archivo específico si se indicó uno
- En qué orden hacerlo
- Qué dependencias o efectos secundarios tener en cuenta
- Si hay evidencia disponible, básate en ella para ser específico sobre el bug o comportamiento a resolver
- Si una sección viene vacía, ignorala en silencio; no la menciones. Citá el ticket concreto cuando exista y nombrá los tests que cubren, o el hueco de cobertura.

El plan va a ser la primera cosa que lea Claude Code antes de empezar. Sé específico
y técnico. Solo el plan, sin introducción ni conclusión."""

    try:
        text, _ = call_claude(prompt, context="sintetizador_brief", max_tokens=700, model=MODEL_BY_OPERATION["task_brief"])
        return {"brief": text.strip()}
    except Exception as e:
        logging.warning("Sintetizador falló, usando fallback determinístico: %s", e)
        lines = [f"Plan técnico para: {task_desc}"]
        if file:
            lines.append(f"Punto de entrada: {file}")
        if listing:
            lines.append("Módulos involucrados:")
            lines.append(listing)
        if precedent and "Sin precedentes" not in precedent:
            lines.append(f"Precedente: {precedent}")
        if coverage and "Sin cobertura" not in coverage:
            lines.append(f"Cobertura: {coverage}")
        return {"brief": "\n".join(lines)}


# ── Grafo ─────────────────────────────────────────────────────────────────


def _build_graph(model=None, single_shot=None):
    """Construye un `StateGraph` nuevo cada vez — seam de inyección para
    tests unitarios y para `graph_selftest`. Producción usa `get_graph()`."""
    from langgraph.graph import StateGraph, START, END

    detective_agent = _build_detective_agent(model)

    def _detective_node(state):
        return _detective(state, agent=detective_agent)

    def _historiador_node(state):
        return _historiador(state, call_claude=single_shot)

    def _vigia_node(state):
        return _vigia(state, call_claude=single_shot)

    def _sintetizador_node(state):
        return _sintetizador(state, call_claude=single_shot)

    g = StateGraph(TaskGraphState)
    g.add_node("detective", _detective_node)
    g.add_node("historiador", _historiador_node)
    g.add_node("vigia", _vigia_node)
    g.add_node("sintetizador", _sintetizador_node)
    g.add_edge(START, "detective")
    g.add_edge(START, "historiador")
    g.add_edge(START, "vigia")
    g.add_edge("detective", "sintetizador")
    g.add_edge("historiador", "sintetizador")
    g.add_edge("vigia", "sintetizador")
    g.add_edge("sintetizador", END)
    return g.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_task_graph(
    task_desc: str,
    modules: list[Module],
    file: str | None = None,
    project_context: str | None = None,
    evidence: str | None = None,
) -> tuple[list[Module], str]:
    if not modules:
        return [], ""

    from aicli.services.embeddings import query_modules

    project_id = modules[0].project_id
    candidates = query_modules(project_id, modules, task_desc)
    if file:
        pinned = next((m for m in modules if m.file_path == file), None)
        if pinned and pinned not in candidates:
            candidates = [pinned] + candidates

    state: TaskGraphState = {
        "task_desc": task_desc,
        "file": file,
        "evidence": evidence,
        "project_context": project_context,
        "project_id": project_id,
        "repo_root": str(Path.cwd()),
        "modules": modules,
        "candidates": candidates,
    }

    result = get_graph().invoke(state)
    relevant = result.get("relevant") or candidates
    brief = result.get("brief") or ""
    return relevant, brief
