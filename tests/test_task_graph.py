"""
Tests unitarios para aicli.services.task_graph — grafo multi-agente que
reemplaza _detect_relevant_modules + _generate_task_brief.
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_task_graph.py -v

Mockea a nivel de BaseChatModel (_ScriptedChatModel), nunca anthropic.Anthropic
directamente — create_agent/ChatAnthropic parsean objetos del SDK ellos
mismos, así que mockear a nivel SDK forzaría reimplementar el parseo de
LangChain. Solo el Sintetizador sigue usando el SDK plano
(indexer._call_claude), mockeado vía @patch("aicli.services.task_graph._call_claude") —
Historiador y Vigía arman su listado crudo sin LLM propio.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatResult, ChatGeneration

from aicli.db.models import Module
from aicli.services import task_graph


def _make_module(id_: int, name: str, description: str = "desc", file_path: str = "path.py", project_id: int = 1, content_path: str = "") -> Module:
    return Module(
        id=id_,
        project_id=project_id,
        name=name,
        description=description,
        file_path=file_path,
        content_path=content_path,
        created_at="2026-01-01",
    )


class _ScriptedChatModel(BaseChatModel):
    """Test double a nivel BaseChatModel — cola de AIMessage a devolver,
    una por turno del loop ReAct. bind_tools() registra el `tool_choice`
    recibido en `bind_tools_calls` (mismo patrón de grabación que `calls`
    usa para los mensajes) y devuelve self."""

    responses: list[Any] = []
    calls: list[Any] = []
    bind_tools_calls: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bind_tools_calls.append(tool_choice)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        idx = min(len(self.calls) - 1, len(self.responses) - 1)
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


def _terminal_msg(names: list[str], cache_read: int = 0, cache_creation: int = 0, tool_id: str = "t1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "seleccionar_modulos", "args": {"modules": names}, "id": tool_id}],
        usage_metadata={
            "input_tokens": 500, "output_tokens": 20, "total_tokens": 520,
            "input_token_details": {"cache_read": cache_read, "cache_creation": cache_creation},
        },
    )


def _lookup_msg(tool_name: str = "leer_doc_modulo", args: dict | None = None, tool_id: str = "l1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": tool_name, "args": args or {"names": ["mod_a"]}, "id": tool_id}])


class ResetGraphMixin(unittest.TestCase):
    def setUp(self):
        task_graph._graph = None
        task_graph._detective_agent = None
        task_graph._escalation_agent = None

    def tearDown(self):
        task_graph._graph = None
        task_graph._detective_agent = None
        task_graph._escalation_agent = None


# ── Phase 1: Foundation ──────────────────────────────────────────────────────


class GetGraphSingletonTestCase(ResetGraphMixin):

    def test_get_graph_is_reused_across_calls(self):
        g1 = task_graph.get_graph()
        g2 = task_graph.get_graph()
        self.assertIs(g1, g2)


# ── Phase 2: Detective node ──────────────────────────────────────────────────


class DetectiveSystemMessageTestCase(ResetGraphMixin):

    def test_leading_system_message_matches_system_blocks_byte_for_byte(self):
        modules = [_make_module(1, "mod_a")]
        model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a"])])
        agent = task_graph._build_detective_agent(model)

        task_graph._detective({"task_desc": "hacer algo", "candidates": modules, "project_context": None}, agent=agent)

        first_message = model.calls[0][0]
        self.assertIsInstance(first_message, SystemMessage)
        expected = task_graph._system_blocks(modules, None)
        self.assertEqual(first_message.content, expected)


class DetectiveToolsTestCase(ResetGraphMixin):

    def test_tool_choice_forced_any_every_turn_now_reaches_model(self):
        """`ToolStrategy` forces `tool_choice="any"` on every `bind_tools`
        call it makes (`langchain/agents/factory.py`:
        `tool_choice = "any" if structured_output_tools else request.tool_choice`).
        Before the CRITICAL fix (removing `thinking` from the Detective's
        model), `langchain_anthropic` silently discarded that forcing
        whenever `thinking` was active — this test proves the forcing now
        genuinely reaches the model on every turn, not just that the loop
        doesn't raise."""
        modules = [_make_module(1, "mod_a")]
        model = _ScriptedChatModel(responses=[_lookup_msg(), _terminal_msg(["mod_a"])])
        agent = task_graph._build_detective_agent(model)

        result = task_graph._detective({"task_desc": "algo", "candidates": modules}, agent=agent)

        self.assertEqual([m.name for m in result["relevant"]], ["mod_a"])
        # Two turns occurred: one intermediate lookup, one terminal call.
        self.assertEqual(len(model.calls), 2)
        # tool_choice="any" must reach bind_tools on every single turn.
        self.assertEqual(model.bind_tools_calls, ["any", "any"])

    def test_leer_doc_modulo_reads_content_path_capped_at_2000_chars(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_path = Path(tmp) / "doc.md"
            doc_path.write_text("x" * 3000, encoding="utf-8")
            modules = [_make_module(1, "mod_a", content_path=str(doc_path))]
            token = task_graph._SCOPE.set({"candidates": modules, "repo_root": tmp})
            try:
                result = task_graph._leer_doc_modulo_impl(["mod_a"])
            finally:
                task_graph._SCOPE.reset(token)
            self.assertEqual(result.count("x"), 2000)

    def test_leer_doc_modulo_batches_multiple_names_in_one_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_a = Path(tmp) / "a.md"
            doc_a.write_text("contenido a", encoding="utf-8")
            doc_b = Path(tmp) / "b.md"
            doc_b.write_text("contenido b", encoding="utf-8")
            modules = [
                _make_module(1, "mod_a", content_path=str(doc_a)),
                _make_module(2, "mod_b", content_path=str(doc_b)),
            ]
            token = task_graph._SCOPE.set({"candidates": modules, "repo_root": tmp})
            try:
                result = task_graph._leer_doc_modulo_impl(["mod_a", "mod_b", "mod_inexistente"])
            finally:
                task_graph._SCOPE.reset(token)
            self.assertIn("contenido a", result)
            self.assertIn("contenido b", result)
            self.assertIn("Módulo no encontrado o sin documentación.", result)

    def test_buscar_en_codigo_bounded_to_40_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "big.py"
            f.write_text("\n".join(f"needle {i}" for i in range(100)), encoding="utf-8")
            token = task_graph._SCOPE.set({"candidates": [], "repo_root": tmp})
            try:
                result = task_graph._buscar_en_codigo_impl(["needle"])
            finally:
                task_graph._SCOPE.reset(token)
            self.assertEqual(len(result.splitlines()), 40)

    def test_buscar_en_codigo_skips_oversized_file_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            oversized = Path(tmp) / "oversized.py"
            # One line comfortably over _MAX_SCAN_FILE_BYTES, containing the pattern.
            oversized.write_text("needle " + ("x" * (task_graph._MAX_SCAN_FILE_BYTES + 1)), encoding="utf-8")
            small = Path(tmp) / "small.py"
            small.write_text("needle aqui\n", encoding="utf-8")

            token = task_graph._SCOPE.set({"candidates": [], "repo_root": tmp})
            try:
                result = task_graph._buscar_en_codigo_impl(["needle"])
            finally:
                task_graph._SCOPE.reset(token)

            self.assertNotIn("oversized.py", result)
            self.assertIn("small.py", result)

    def test_buscar_en_codigo_accepts_multiple_patterns_sharing_the_40_hit_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "big.py"
            f.write_text(
                "\n".join(f"alfa {i}" for i in range(25)) + "\n" + "\n".join(f"beta {i}" for i in range(25)),
                encoding="utf-8",
            )
            token = task_graph._SCOPE.set({"candidates": [], "repo_root": tmp})
            try:
                result = task_graph._buscar_en_codigo_impl(["alfa", "beta"])
            finally:
                task_graph._SCOPE.reset(token)
            self.assertEqual(len(result.splitlines()), 40)
            self.assertIn("[alfa]", result)


class DetectiveTerminationTestCase(ResetGraphMixin):

    def test_terminal_call_ends_loop_and_filters_by_candidates(self):
        modules = [_make_module(1, "mod_a"), _make_module(2, "mod_b")]
        model = _ScriptedChatModel(responses=[_terminal_msg(["mod_b", "mod_inexistente"])])
        agent = task_graph._build_detective_agent(model)
        # 2 names returned == 2 candidates, which the new ambiguity check
        # treats as "couldn't discriminate" and escalates once to Sonnet —
        # wire a fake escalation agent that resolves unambiguously so this
        # test still exercises straight-through filtering behavior.
        escalation_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_b"])])
        escalation_agent = task_graph._build_detective_agent(escalation_model)

        result = task_graph._detective(
            {"task_desc": "algo", "candidates": modules}, agent=agent, escalation_agent=escalation_agent
        )

        self.assertEqual([m.name for m in result["relevant"]], ["mod_b"])

    def test_recursion_limit_exhaustion_degrades_to_candidates_never_raises(self):
        modules = [_make_module(1, "mod_a")]
        # Never emits the terminal call — infinite intermediate loop.
        model = _ScriptedChatModel(responses=[_lookup_msg()])
        agent = task_graph._build_detective_agent(model)

        try:
            result = task_graph._detective({"task_desc": "algo", "candidates": modules}, agent=agent)
        except Exception:
            self.fail("_detective no debe propagar excepciones ante agotamiento de recursion_limit")

        self.assertEqual(result["relevant"], modules)

    def test_detective_recursion_limit_scales_with_candidate_count(self):
        few = [_make_module(i, f"mod_{i}") for i in range(3)]
        many = [_make_module(i, f"mod_{i}") for i in range(30)]

        self.assertEqual(task_graph._detective_recursion_limit([]), 12)
        self.assertEqual(task_graph._detective_recursion_limit(few), 12)
        self.assertEqual(task_graph._detective_recursion_limit(many), 24)


class DetectiveEscalationTestCase(ResetGraphMixin):
    """Cambio 3 — ambigüedad (sin nombres, o Haiku seleccionando literalmente
    todos los candidatos) dispara una escalación única a Sonnet antes de
    degradar a la lista completa de candidatos."""

    def test_all_candidates_selected_escalates_to_sonnet_and_uses_its_result(self):
        modules = [_make_module(1, "mod_a"), _make_module(2, "mod_b"), _make_module(3, "mod_c")]
        primary_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a", "mod_b", "mod_c"])])
        primary_agent = task_graph._build_detective_agent(primary_model)
        escalation_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_b"])])
        escalation_agent = task_graph._build_detective_agent(escalation_model)

        result = task_graph._detective(
            {"task_desc": "algo", "candidates": modules},
            agent=primary_agent,
            escalation_agent=escalation_agent,
        )

        # Escalation agent was actually invoked once...
        self.assertEqual(len(escalation_model.calls), 1)
        # ...and its (unambiguous) selection is what gets used, not the
        # primary's all-candidates answer.
        self.assertEqual([m.name for m in result["relevant"]], ["mod_b"])

    def test_both_primary_and_escalation_ambiguous_falls_back_to_all_candidates(self):
        modules = [_make_module(1, "mod_a"), _make_module(2, "mod_b")]
        primary_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a", "mod_b"])])
        primary_agent = task_graph._build_detective_agent(primary_model)
        # Escalation is also ambiguous: selects every candidate again.
        escalation_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a", "mod_b"])])
        escalation_agent = task_graph._build_detective_agent(escalation_model)

        result = task_graph._detective(
            {"task_desc": "algo", "candidates": modules},
            agent=primary_agent,
            escalation_agent=escalation_agent,
        )

        self.assertEqual(len(escalation_model.calls), 1)
        self.assertEqual(result["relevant"], modules)

    def test_no_names_extracted_escalates_and_uses_escalation_result(self):
        modules = [_make_module(1, "mod_a")]
        # Empty selection is ambiguous even with a single candidate (the
        # `len(candidates) <= 1` skip only applies to the all-selected
        # condition, not to the empty-names condition).
        primary_model = _ScriptedChatModel(responses=[_terminal_msg([])])
        primary_agent = task_graph._build_detective_agent(primary_model)
        escalation_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a"])])
        escalation_agent = task_graph._build_detective_agent(escalation_model)

        result = task_graph._detective(
            {"task_desc": "algo", "candidates": modules},
            agent=primary_agent,
            escalation_agent=escalation_agent,
        )

        self.assertEqual(len(escalation_model.calls), 1)
        self.assertEqual([m.name for m in result["relevant"]], ["mod_a"])

    def test_escalation_agent_failure_falls_back_to_all_candidates(self):
        modules = [_make_module(1, "mod_a"), _make_module(2, "mod_b")]
        primary_model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a", "mod_b"])])
        primary_agent = task_graph._build_detective_agent(primary_model)
        broken_escalation_agent = MagicMock()
        broken_escalation_agent.invoke.side_effect = RuntimeError("sonnet unavailable")

        try:
            result = task_graph._detective(
                {"task_desc": "algo", "candidates": modules},
                agent=primary_agent,
                escalation_agent=broken_escalation_agent,
            )
        except Exception:
            self.fail("_detective no debe propagar excepciones ante fallo de la escalación")

        self.assertEqual(result["relevant"], modules)


class DetectiveEmpiricalChecksTestCase(ResetGraphMixin):
    """Tasks 2.6-2.8 — verificación empírica de los 3 mecanismos marcados
    como riesgo en design.md. Los tres corrieron también en un script de
    sondeo manual antes de escribir esta suite; ver apply-progress."""

    def test_cache_read_tokens_positive_on_second_scripted_call(self):
        # NOTE (documented, accepted coverage limitation — see
        # test_cache_control_block_survives_real_chatanthropic_request_payload
        # below): this test only proves `_log_detective_usage` correctly
        # echoes hand-crafted `usage_metadata` fields off an already-built
        # `AIMessage` from `_ScriptedChatModel`. It never exercises
        # `ChatAnthropic`'s real message-formatting/request-building code
        # (`_format_messages`/`_get_request_payload`), so on its own it does
        # NOT prove the `cache_control` dict block set by `_system_blocks`
        # actually survives into what would become a real Anthropic API
        # request — only that logging correctly reflects whatever
        # usage_metadata the model returns.
        modules = [_make_module(1, "mod_a")]
        model = _ScriptedChatModel(responses=[
            _terminal_msg(["mod_a"], cache_read=0, cache_creation=100),
            _terminal_msg(["mod_a"], cache_read=42, cache_creation=0),
        ])
        agent = task_graph._build_detective_agent(model)

        task_graph._detective({"task_desc": "uno", "candidates": modules}, agent=agent)
        with self.assertLogs(level="INFO") as cm:
            task_graph._detective({"task_desc": "dos", "candidates": modules}, agent=agent)

        self.assertTrue(any("cache_read: 42" in line for line in cm.output))

    def test_cache_control_block_survives_real_chatanthropic_request_payload(self):
        """Closes (partially, honestly) the gap documented on the test
        above: never sends a real HTTP request (project convention — no
        real network calls or real API clients constructed in tests that
        actually fire), but DOES construct the REAL `ChatAnthropic` model
        (not `_ScriptedChatModel`) built the same way
        `_build_detective_agent` builds it, and calls its real
        `_get_request_payload` — the seam `langchain_anthropic` exposes to
        build the Anthropic request payload (message formatting, system
        block handling, cache_control breakpoint placement) WITHOUT sending
        it. Asserts the `cache_control` block from `_system_blocks` survives
        byte-for-byte into the constructed payload."""
        from langchain_anthropic import ChatAnthropic
        from langchain_core.messages import HumanMessage

        modules = [_make_module(1, "mod_a")]
        blocks = task_graph._system_blocks(modules, None)
        sys_msg = SystemMessage(content=blocks)

        real_model = ChatAnthropic(model="claude-sonnet-5", api_key="test-key-unused", max_tokens=4000)
        payload = real_model._get_request_payload([sys_msg, HumanMessage(content="hola")])

        self.assertEqual(payload["system"], blocks)
        self.assertEqual(payload["system"][0]["cache_control"], {"type": "ephemeral"})

    def test_structured_response_populated_after_terminal_call(self):
        modules = [_make_module(1, "mod_a")]
        model = _ScriptedChatModel(responses=[_terminal_msg(["mod_a"])])
        agent = task_graph._build_detective_agent(model)

        sys_msg = SystemMessage(content=task_graph._system_blocks(modules, None))
        from langchain_core.messages import HumanMessage
        result = agent.invoke({"messages": [sys_msg, HumanMessage(content="hola")]}, config={"recursion_limit": 12})

        self.assertIsNotNone(result.get("structured_response"))
        self.assertEqual(list(result["structured_response"].modules), ["mod_a"])

    def test_contextvar_scope_read_correctly_by_tool_mid_loop(self):
        modules = [_make_module(1, "mod_a")]
        seen_scope = {}

        real_impl = task_graph._leer_doc_modulo_impl

        def _spy(name):
            seen_scope["value"] = task_graph._SCOPE.get()
            return real_impl(name)

        model = _ScriptedChatModel(responses=[_lookup_msg(), _terminal_msg(["mod_a"])])
        agent = task_graph._build_detective_agent(model)

        with patch.object(task_graph, "_leer_doc_modulo_impl", side_effect=_spy):
            task_graph._detective({"task_desc": "algo", "candidates": modules}, agent=agent)

        self.assertIsNotNone(seen_scope.get("value"))
        self.assertEqual([m.name for m in seen_scope["value"]["candidates"]], ["mod_a"])
        # Scope must be cleared again after the node returns (finally/reset).
        self.assertIsNone(task_graph._SCOPE.get())


class DetectiveModelConstructionTestCase(ResetGraphMixin):
    """`thinking` habilitado junto al tool_choice="any" forzado por
    ToolStrategy es un conflicto documentado en langchain_anthropic (se
    descarta el forzado en silencio) — el Detective no debe usar `thinking`."""

    def test_default_model_construction_omits_thinking(self):
        scripted = _ScriptedChatModel(responses=[_terminal_msg([])])
        with patch("langchain_anthropic.ChatAnthropic", return_value=scripted) as mock_ctor:
            task_graph._build_detective_agent(None)

        _, kwargs = mock_ctor.call_args
        self.assertNotIn("thinking", kwargs)
        self.assertEqual(kwargs.get("model"), "claude-haiku-4-5")


class DetectiveIncrementalCachingTestCase(ResetGraphMixin):
    """Only the leading `SystemMessage` carried `cache_control` before this
    change — the growing tool_call/tool_result history within a single
    Detective run was never marked, so turns 2..N of the ReAct loop resent
    that prefix at full price. `AnthropicPromptCachingMiddleware` (official,
    shipped by `langchain_anthropic`, not hand-rolled) tags the moving tail
    of the conversation each turn instead."""

    def test_build_detective_agent_wires_prompt_caching_middleware(self):
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware

        scripted = _ScriptedChatModel(responses=[_terminal_msg(["mod_a"])])
        with patch("langchain.agents.create_agent") as mock_create_agent:
            task_graph._build_detective_agent(scripted)

        _, kwargs = mock_create_agent.call_args
        middlewares = kwargs.get("middleware") or []
        self.assertTrue(any(isinstance(mw, AnthropicPromptCachingMiddleware) for mw in middlewares))

    def test_prompt_caching_middleware_cache_control_reaches_real_request_payload(self):
        """Never sends a real HTTP request (project convention, same as the
        system-block payload test above). Manually forwards
        `ModelRequest.model_settings` into `_get_request_payload` the way
        `create_agent`'s compiled graph does internally, to honestly prove
        the plumbing this change depends on: `wrap_model_call` injecting a
        `cache_control` kwarg that a REAL `ChatAnthropic` instance carries
        through to the request payload sent to the (real, installed)
        `anthropic` SDK, which applies it to the last eligible content block
        server-request-side — confirmed via SDK introspection
        (`anthropic.resources.messages.Messages.create` accepts a native
        `cache_control` kwarg) before writing this test."""
        from langchain_anthropic import ChatAnthropic
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

        real_model = ChatAnthropic(model="claude-sonnet-5", api_key="test-key-unused", max_tokens=4000)
        mw = AnthropicPromptCachingMiddleware()

        # Simulates turn 3 of a growing ReAct loop.
        messages = [
            HumanMessage(content="tarea"),
            AIMessage(content="", tool_calls=[{"name": "leer_doc_modulo", "args": {"names": ["mod_a"]}, "id": "l1"}]),
            ToolMessage(content="doc de mod_a", tool_call_id="l1"),
        ]
        request = ModelRequest(
            model=real_model,
            messages=messages,
            system_message=SystemMessage(content=[{"type": "text", "text": "sys"}]),
            tools=[],
            model_settings={},
        )

        captured = {}

        def handler(req):
            captured["payload"] = req.model._get_request_payload(
                ([req.system_message] if req.system_message else []) + req.messages,
                **(req.model_settings or {}),
            )
            return None

        mw.wrap_model_call(request, handler)

        self.assertEqual(captured["payload"].get("cache_control"), {"type": "ephemeral", "ttl": "5m"})


# ── Phase 3: Historiador, Vigía, Sintetizador ────────────────────────────────


class HistoriadorTestCase(unittest.TestCase):

    @patch("aicli.services.embeddings.query_tickets")
    @patch("aicli.services.task_graph._call_claude")
    @patch("aicli.services.tickets.load_tickets")
    def test_returns_raw_listing_without_llm_call_when_precedent_found(self, mock_load, mock_call, mock_query):
        mock_load.return_value = {
            "TCK-1": {"descripcion": "sincronizacion de modulos rota", "rondas": []},
        }
        mock_query.return_value = [{"ticket_id": "TCK-1", "descripcion": "sincronizacion de modulos rota"}]

        result = task_graph._historiador({"task_desc": "arreglar sincronizacion de modulos"})

        mock_call.assert_not_called()
        self.assertEqual(result["precedent"], "- TCK-1: sincronizacion de modulos rota")

    @patch("aicli.services.embeddings.query_tickets")
    @patch("aicli.services.task_graph._call_claude")
    @patch("aicli.services.tickets.load_tickets")
    def test_empty_corpus_skips_llm_call(self, mock_load, mock_call, mock_query):
        mock_load.return_value = {}
        mock_query.return_value = []

        result = task_graph._historiador({"task_desc": "algo"})

        mock_call.assert_not_called()
        self.assertEqual(result["precedent"], "Sin precedentes en el historial de tickets.")

    @patch("aicli.services.embeddings.query_tickets")
    @patch("aicli.services.task_graph._call_claude")
    @patch("aicli.services.tickets.load_tickets")
    def test_load_tickets_exception_degrades_gracefully(self, mock_load, mock_call, mock_query):
        mock_load.side_effect = RuntimeError("disco lleno")

        try:
            result = task_graph._historiador({"task_desc": "algo"})
        except Exception:
            self.fail("_historiador no debe propagar excepciones")

        self.assertEqual(result["precedent"], "Sin precedentes en el historial de tickets.")
        mock_call.assert_not_called()


class DiscoverTestFilesAndCoverageTestCase(unittest.TestCase):

    def test_multi_module_test_file_maps_to_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            test_file = root / "tests" / "test_commands.py"
            test_file.write_text(
                "from aicli.commands.task import task\nfrom aicli.commands.init import init\n",
                encoding="utf-8",
            )
            modules = [
                _make_module(1, "task", file_path="aicli/commands/task.py"),
                _make_module(2, "init", file_path="aicli/commands/init.py"),
            ]
            test_files = task_graph._discover_test_files(root)
            coverage = task_graph._scan_coverage(test_files, modules)

            self.assertIn("task", coverage)
            self.assertIn("init", coverage)

    def test_generic_stem_rejected_without_multi_segment_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            test_file = root / "tests" / "test_x.py"
            test_file.write_text("import init\n", encoding="utf-8")
            # file_path's stem is "init", a GENERIC_STEMS entry, and the test
            # file never contains the multi-segment form "somepkg/init".
            modules = [_make_module(1, "init_mod", file_path="somepkg/init.py")]

            test_files = task_graph._discover_test_files(root)
            coverage = task_graph._scan_coverage(test_files, modules)

            self.assertNotIn("init_mod", coverage)

    def test_short_stem_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            test_file = root / "tests" / "test_y.py"
            test_file.write_text("import db\n", encoding="utf-8")
            modules = [_make_module(1, "db_mod", file_path="somepkg/db.py")]

            test_files = task_graph._discover_test_files(root)
            coverage = task_graph._scan_coverage(test_files, modules)

            self.assertNotIn("db_mod", coverage)

    def test_ignored_dirs_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            venv_dir = root / ".venv" / "tests"
            venv_dir.mkdir(parents=True)
            (venv_dir / "test_ignored.py").write_text("import task\n", encoding="utf-8")

            test_files = task_graph._discover_test_files(root)

            self.assertEqual(test_files, [])


class VigiaTestCase(unittest.TestCase):

    @patch("aicli.services.task_graph._call_claude")
    def test_coverage_found_returns_raw_listing_without_llm_call(self, mock_call):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_task.py").write_text("from aicli.commands import task\n", encoding="utf-8")
            modules = [_make_module(1, "task", file_path="aicli/commands/task.py")]

            result = task_graph._vigia({"candidates": modules, "repo_root": str(root)})

        mock_call.assert_not_called()
        self.assertIn("task:", result["coverage"])

    @patch("aicli.services.task_graph._call_claude")
    def test_no_coverage_skips_llm_call_advisory_only(self, mock_call):
        with tempfile.TemporaryDirectory() as tmp:
            modules = [_make_module(1, "mod_a", file_path="aicli/mod_a.py")]
            result = task_graph._vigia({"candidates": modules, "repo_root": tmp})

        mock_call.assert_not_called()
        self.assertEqual(result["coverage"], "Sin cobertura de tests detectada.")

    @patch("aicli.services.task_graph._call_claude")
    def test_exception_degrades_gracefully(self, mock_call):
        with patch.object(task_graph, "_discover_test_files", side_effect=RuntimeError("boom")):
            try:
                result = task_graph._vigia({"candidates": [], "repo_root": "/nonexistent"})
            except Exception:
                self.fail("_vigia no debe propagar excepciones")
        self.assertEqual(result["coverage"], "Sin cobertura de tests detectada.")
        mock_call.assert_not_called()


class SintetizadorTestCase(unittest.TestCase):

    @patch("aicli.services.task_graph._call_claude")
    def test_prompt_carries_all_three_sections_and_evidence(self, mock_call):
        mock_call.return_value = ("plan final", 10)
        modules = [_make_module(1, "mod_a")]
        state = {
            "task_desc": "hacer algo", "relevant": modules, "file": "x.py",
            "evidence": "EVIDENCIA_SENTINEL", "precedent": "PRECEDENTE_SENTINEL",
            "coverage": "COBERTURA_SENTINEL",
        }

        result = task_graph._sintetizador(state)

        prompt = mock_call.call_args.args[0]
        self.assertIn("EVIDENCIA_SENTINEL", prompt)
        self.assertIn("PRECEDENTE_SENTINEL", prompt)
        self.assertIn("COBERTURA_SENTINEL", prompt)
        self.assertEqual(result["brief"], "plan final")

    @patch("aicli.services.task_graph._call_claude")
    def test_llm_failure_falls_back_to_deterministic_brief(self, mock_call):
        mock_call.side_effect = RuntimeError("rate limited")
        modules = [_make_module(1, "mod_a")]
        state = {"task_desc": "hacer algo", "relevant": modules}

        result = task_graph._sintetizador(state)

        self.assertIn("hacer algo", result["brief"])
        self.assertTrue(result["brief"])


# ── Phase 4: Graph wiring & run_task_graph ───────────────────────────────────


class GraphWiringTestCase(ResetGraphMixin):

    def test_all_three_specialists_run_in_one_superstep_then_sintetizador(self):
        calls_order = []

        def _rec_detective(state, **kwargs):
            calls_order.append("detective")
            return {"relevant": []}

        def _rec_historiador(state, **kwargs):
            calls_order.append("historiador")
            return {"precedent": "p"}

        def _rec_vigia(state, **kwargs):
            calls_order.append("vigia")
            return {"coverage": "c"}

        def _rec_sintetizador(state, **kwargs):
            calls_order.append("sintetizador")
            # Sintetizador must see all 3 outputs merged into state.
            self.assertIn("relevant", state)
            self.assertEqual(state.get("precedent"), "p")
            self.assertEqual(state.get("coverage"), "c")
            return {"brief": "final"}

        with patch.object(task_graph, "_detective", side_effect=_rec_detective), \
             patch.object(task_graph, "_historiador", side_effect=_rec_historiador), \
             patch.object(task_graph, "_vigia", side_effect=_rec_vigia), \
             patch.object(task_graph, "_sintetizador", side_effect=_rec_sintetizador):
            graph = task_graph._build_graph()
            result = graph.invoke({"task_desc": "t", "candidates": []})

        self.assertEqual(calls_order[-1], "sintetizador")
        self.assertEqual(set(calls_order[:-1]), {"detective", "historiador", "vigia"})
        self.assertEqual(calls_order.count("sintetizador"), 1)
        self.assertEqual(result["brief"], "final")

    def test_one_specialist_raising_still_yields_brief(self):
        def _boom(state, **kwargs):
            raise RuntimeError("historiador crashed")

        def _ok_detective(state, **kwargs):
            return {"relevant": []}

        def _ok_vigia(state, **kwargs):
            return {"coverage": "c"}

        def _ok_sintetizador(state, **kwargs):
            return {"brief": "brief pese al fallo"}

        # Historiador itself degrades internally (never raises to the graph);
        # this test proves the graph-level contract holds even if a node's
        # own defenses were bypassed, by patching the *node* boundary too.
        with patch.object(task_graph, "_detective", side_effect=_ok_detective), \
             patch.object(task_graph, "_historiador", side_effect=lambda s, call_claude=None: {"precedent": "Sin precedentes en el historial de tickets."}), \
             patch.object(task_graph, "_vigia", side_effect=_ok_vigia), \
             patch.object(task_graph, "_sintetizador", side_effect=_ok_sintetizador):
            graph = task_graph._build_graph()
            result = graph.invoke({"task_desc": "t", "candidates": []})

        self.assertEqual(result["brief"], "brief pese al fallo")


class RunTaskGraphCandidatesTestCase(ResetGraphMixin):
    """Task 4.3 — migra las aserciones de test_module_prefilter.py:258-384
    (TaskWiringTestCase / CachedListingVariesWithTaskDescTestCase /
    ExistingFixtureNoOpRegressionTestCase) hacia run_task_graph, que ahora
    es dueño del prefiltro semántico + unión --file."""

    def _make_n_modules(self, n):
        return [_make_module(i, f"mod_{i}", f"desc {i}") for i in range(1, n + 1)]

    @patch("aicli.services.embeddings.query_modules")
    def test_calls_query_modules_before_building_candidates(self, mock_query):
        modules = [_make_module(i, f"mod_{i}") for i in range(1, 26)]
        mock_query.return_value = modules[:20]

        with patch.object(task_graph, "_build_graph") as mock_build_graph:
            fake_graph = MagicMock()
            fake_graph.invoke.return_value = {"relevant": modules[:20], "brief": "b"}
            mock_build_graph.return_value = fake_graph
            task_graph._graph = None
            task_graph.run_task_graph("tarea", modules)

        mock_query.assert_called_once_with(1, modules, "tarea")

    @patch("aicli.services.embeddings.query_modules")
    def test_file_pin_unioned_without_mutating_callers_modules_list(self, mock_query):
        modules = [_make_module(i, f"mod_{i}", file_path=f"f{i}.py") for i in range(1, 26)]
        pinned = modules[24]
        candidates = modules[:20]
        mock_query.return_value = candidates
        original_snapshot = list(modules)

        captured_state = {}

        def _fake_invoke(state):
            captured_state.update(state)
            return {"relevant": state["candidates"], "brief": "b"}

        with patch.object(task_graph, "_build_graph") as mock_build_graph:
            fake_graph = MagicMock()
            fake_graph.invoke.side_effect = _fake_invoke
            mock_build_graph.return_value = fake_graph
            task_graph._graph = None
            task_graph.run_task_graph("tarea", modules, file=pinned.file_path)

        self.assertEqual(modules, original_snapshot)
        self.assertIn(pinned, captured_state["candidates"])

    @patch("aicli.services.embeddings.query_modules")
    def test_module_listing_may_differ_across_task_desc_on_large_project(self, mock_query):
        modules = self._make_n_modules(25)
        subset_a = modules[0:20]
        subset_b = modules[5:25]
        mock_query.side_effect = [subset_a, subset_b]

        captured = []

        def _fake_invoke(state):
            captured.append(state["candidates"])
            return {"relevant": state["candidates"], "brief": "b"}

        with patch.object(task_graph, "_build_graph") as mock_build_graph:
            fake_graph = MagicMock()
            fake_graph.invoke.side_effect = _fake_invoke
            mock_build_graph.return_value = fake_graph
            task_graph._graph = None
            task_graph.run_task_graph("tarea uno", modules, project_context="PROYECTO_X")
            task_graph.run_task_graph("tarea numero dos completamente distinta", modules, project_context="PROYECTO_X")

        self.assertNotEqual([m.id for m in captured[0]], [m.id for m in captured[1]])

    @patch("aicli.services.embeddings.get_collection")
    def test_small_project_fixture_never_touches_chroma(self, mock_get_collection):
        # Uses the REAL query_modules — only Chroma's entry point is mocked,
        # to prove the <=20 fixture takes the no-op branch inside
        # query_modules itself.
        modules = [_make_module(1, "mod_a")]

        with patch.object(task_graph, "_build_graph") as mock_build_graph:
            fake_graph = MagicMock()
            fake_graph.invoke.return_value = {"relevant": modules, "brief": "b"}
            mock_build_graph.return_value = fake_graph
            task_graph._graph = None
            task_graph.run_task_graph("tarea", modules, project_context="PROYECTO_X")

        mock_get_collection.assert_not_called()

    def test_empty_modules_returns_empty_without_building_graph(self):
        with patch.object(task_graph, "_build_graph") as mock_build_graph:
            relevant, brief = task_graph.run_task_graph("tarea", [])

        self.assertEqual(relevant, [])
        self.assertEqual(brief, "")
        mock_build_graph.assert_not_called()


# ── Phase 5: task.py integration ─────────────────────────────────────────────


def _memory_engine():
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, create_engine
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(eng)
    return eng


class TaskIntegrationTestCase(unittest.TestCase):
    """Task 5.2 — one run_task_graph call replaces the old two-call pattern;
    the --file guarantee union still applies outside the graph;
    build_context receives the resolved `relevant` list."""

    def setUp(self):
        from sqlmodel import Session
        from aicli.db.models import Project

        self.engine = _memory_engine()
        with Session(self.engine) as session:
            project = Project(name="p", path=str(Path.cwd()), stack="python", created_at="2026-01-01")
            session.add(project)
            session.commit()
            session.refresh(project)
            self.project_id = project.id
            self.project_path = project.path

            m1 = _make_module(1, "mod_a", file_path="a.py", project_id=project.id)
            m2 = _make_module(2, "mod_b", file_path="pinned.py", project_id=project.id)
            session.add(m1)
            session.add(m2)
            session.commit()

    def test_single_run_task_graph_call_receives_evidence_and_file_union_preserved(self):
        from aicli.commands import task

        with patch.object(task, "engine", self.engine), \
             patch("pathlib.Path.cwd", return_value=Path(self.project_path)), \
             patch("aicli.commands.task.run_task_graph") as mock_run_graph, \
             patch("aicli.commands.task.build_context") as mock_build_context, \
             patch("aicli.commands.task.launch_claude") as mock_launch, \
             patch("aicli.commands.task.describe_image", return_value=("una imagen", 10)):

            mock_run_graph.return_value = ([_make_module(1, "mod_a", file_path="a.py")], "brief final")
            mock_build_context.return_value = ("contexto", [])

            task._execute_task("hacer algo", file="pinned.py", image="fake.png")

        mock_run_graph.assert_called_once()
        args, _ = mock_run_graph.call_args
        self.assertEqual(args[0], "hacer algo")
        self.assertEqual(args[2], "pinned.py")

        # --file guarantee union still applied outside the graph, even though
        # run_task_graph's stub result didn't include the pinned module.
        relevant_passed_to_build_context = mock_build_context.call_args.args[0]
        self.assertIn("pinned.py", [m.file_path for m in relevant_passed_to_build_context])

        mock_launch.assert_called_once()

    def test_relevant_falls_back_to_full_modules_when_graph_returns_empty(self):
        from aicli.commands import task

        with patch.object(task, "engine", self.engine), \
             patch("pathlib.Path.cwd", return_value=Path(self.project_path)), \
             patch("aicli.commands.task.run_task_graph") as mock_run_graph, \
             patch("aicli.commands.task.build_context") as mock_build_context, \
             patch("aicli.commands.task.launch_claude"):

            mock_run_graph.return_value = ([], "brief")
            mock_build_context.return_value = ("contexto", [])

            task._execute_task("hacer algo")

        relevant_passed = mock_build_context.call_args.args[0]
        self.assertEqual(len(relevant_passed), 2)  # both modules, the full set


# ── Phase 6: graph_selftest temp dir lifecycle ───────────────────────────────


class GraphSelftestTempCleanupTestCase(unittest.TestCase):
    """`graph_selftest._empty_repo_root()` used `tempfile.mkdtemp` and never
    removed the directory — every `graph-selftest` invocation (including
    every `scripts/verify_frozen.ps1` run) leaked one. Now the repo_root
    lives inside a `tempfile.TemporaryDirectory()` context scoped to
    `graph.invoke(state)` and is removed on exit."""

    def test_graph_selftest_removes_temp_repo_root_after_run(self):
        from aicli.commands import graph_selftest as gs

        real_tempdir_cls = tempfile.TemporaryDirectory
        captured: dict[str, str] = {}

        class _SpyTemporaryDirectory(real_tempdir_cls):
            def __enter__(self):
                path = super().__enter__()
                captured["path"] = path
                return path

        with patch("aicli.commands.graph_selftest.tempfile.TemporaryDirectory", _SpyTemporaryDirectory):
            gs.graph_selftest()

        self.assertIn("path", captured)
        self.assertFalse(Path(captured["path"]).exists())


if __name__ == "__main__":
    unittest.main()
