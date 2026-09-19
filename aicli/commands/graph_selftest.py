"""
Comando oculto — diagnóstico del grafo multi-agente dentro del binario
congelado (PyInstaller). No requiere ANTHROPIC_API_KEY, no red. Sirve como
sonda para `scripts/verify_frozen.ps1`: ejercita `create_agent`/`StateGraph`
(langchain/langchain-anthropic/langgraph) de punta a punta con un modelo
falso y llamadas SDK falsas — el único código path dentro de `MAGNA.exe`
que ejercita ese stack de punta a punta.
"""
import sys
import tempfile

import typer

app = typer.Typer()


@app.callback(invoke_without_command=True)
def graph_selftest():
    """Prueba fría del grafo multi-agente — diagnóstico oculto."""
    try:
        import langgraph
        from langchain_anthropic import ChatAnthropic
        from aicli.services import task_graph

        # Prueba el import/init del provider — el mecanismo exacto que se
        # rompe bajo PyInstaller si copy_metadata/collect_submodules faltan.
        ChatAnthropic(model="claude-sonnet-5", api_key="selftest-unused")

        model = _make_scripted_model()
        graph = task_graph._build_graph(model=model, single_shot=_stub_call_claude)

        # El repo_root es solo un stand-in para la corrida del grafo — vive
        # exactamente lo que dura `graph.invoke` y se limpia solo al salir
        # del `with` (antes se creaba con `mkdtemp` y quedaba huérfano).
        with tempfile.TemporaryDirectory(prefix="graph_selftest_") as repo_root:
            state = {
                "task_desc": "tarea de diagnostico",
                "file": None,
                "evidence": None,
                "project_context": None,
                "project_id": 0,
                "repo_root": repo_root,
                "modules": [],
                "candidates": [],
            }
            graph.invoke(state)

        version = _langgraph_version()
        print(f"langgraph version: {version}")
        print("nodes: detective,historiador,vigia,sintetizador")
        print("OK")
    except typer.Exit:
        raise
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise typer.Exit(code=1)


def _stub_call_claude(prompt: str, context: str = "", max_tokens: int = 8192, model: str | None = None):
    return ("stub", 0)


def _langgraph_version() -> str:
    """Vía importlib.metadata — ejercita el mismo path que `copy_metadata`
    debe garantizar dentro del binario congelado."""
    try:
        import importlib.metadata
        return importlib.metadata.version("langgraph")
    except Exception:
        return "desconocida"


def _make_scripted_model():
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatResult, ChatGeneration

    class _SelftestChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "selftest"

        def bind_tools(self, tools, *, tool_choice=None, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            msg = AIMessage(
                content="",
                tool_calls=[{"name": "seleccionar_modulos", "args": {"modules": []}, "id": "selftest-1"}],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

    return _SelftestChatModel()
