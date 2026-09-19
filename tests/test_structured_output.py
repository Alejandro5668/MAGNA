"""
Tests unitarios para aicli.services.indexer — migración a salida estructurada
forzada (tool_use) en generate_case_summary, document_zone y document_architecture,
más la extracción compartida del retry loop (_messages_create_retry, _call_claude_tool).

Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_structured_output.py -v

Usa unittest.mock.patch sobre anthropic.Anthropic — sin red real.
"""
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import anthropic

sys.path.insert(0, str(Path(__file__).parent.parent))

from aicli.services import indexer


def _tool_response(tool_name, payload, cache_read=0):
    """Respuesta con un bloque `thinking` líder antes del `tool_use` forzado —
    prueba que el extractor lo ignora (el mismo bug fijado para _extract_text en ba41364)."""
    usage = MagicMock(input_tokens=500, output_tokens=20,
                       cache_creation_input_tokens=100, cache_read_input_tokens=cache_read)
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking"),
                 SimpleNamespace(type="tool_use", name=tool_name, input=payload)],
        usage=usage)


def _text_response(text):
    usage = MagicMock(input_tokens=500, output_tokens=20,
                       cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking"),
                 SimpleNamespace(type="text", text=text)],
        usage=usage)


# ---------------------------------------------------------------------------
# B1 — baseline safety net: _call_claude's public contract survives the
# _messages_create_retry extraction byte-for-byte (guards generate_module_content,
# analyze_file_deep, generate_project_md — none of which are touched by this change).
# ---------------------------------------------------------------------------

class CallClaudeBaselineTestCase(unittest.TestCase):

    @patch("anthropic.Anthropic")
    def test_call_claude_returns_tuple_str_int(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.return_value = _text_response("hola mundo")

        text, tokens = indexer._call_claude("prompt", context="ctx", max_tokens=123, model="m")

        self.assertEqual(text, "hola mundo")
        self.assertEqual(tokens, 520)

    @patch("anthropic.Anthropic")
    def test_call_claude_sends_no_tools_kwarg(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.return_value = _text_response("hola")

        indexer._call_claude("prompt", context="ctx")

        kwargs = mock_create.call_args.kwargs
        self.assertNotIn("tools", kwargs)
        self.assertNotIn("tool_choice", kwargs)

    @patch("anthropic.Anthropic")
    def test_call_claude_sends_expected_model_and_max_tokens(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.return_value = _text_response("hola")

        indexer._call_claude("prompt", context="ctx", max_tokens=321, model="modelo-x")

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["model"], "modelo-x")
        self.assertEqual(kwargs["max_tokens"], 321)
        self.assertEqual(kwargs["messages"], [{"role": "user", "content": "prompt"}])


# ---------------------------------------------------------------------------
# B2 — the not-yet-existing retry helper: forwards arbitrary kwargs (tools/
# tool_choice included) untouched, retries on RateLimitError with backoff.
# ---------------------------------------------------------------------------

class MessagesCreateRetryTestCase(unittest.TestCase):

    @patch("aicli.services.indexer.time.sleep")
    @patch("anthropic.Anthropic")
    def test_forwards_tools_and_tool_choice(self, mock_anthropic_cls, mock_sleep):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.return_value = _tool_response("mi_tool", {"x": 1})

        response = indexer._messages_create_retry(
            "ctx", 10, model="m", max_tokens=99,
            tools=[{"name": "mi_tool"}], tool_choice={"type": "tool", "name": "mi_tool"},
            messages=[{"role": "user", "content": "p"}],
        )

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [{"name": "mi_tool"}])
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "mi_tool"})
        self.assertEqual(response.content[1].input, {"x": 1})

    @patch("aicli.services.indexer.time.sleep")
    @patch("anthropic.Anthropic")
    def test_retries_on_rate_limit_then_succeeds(self, mock_anthropic_cls, mock_sleep):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.side_effect = [
            anthropic.RateLimitError("rate limited", response=MagicMock(), body=None),
            _text_response("ok"),
        ]

        response = indexer._messages_create_retry(
            "ctx", 10, model="m", max_tokens=10,
            messages=[{"role": "user", "content": "p"}],
        )

        self.assertEqual(mock_create.call_count, 2)
        mock_sleep.assert_called_once_with(indexer.INITIAL_WAIT)
        self.assertEqual(response.content[1].text, "ok")

    @patch("aicli.services.indexer.time.sleep")
    @patch("anthropic.Anthropic")
    def test_raises_after_max_retries_exhausted(self, mock_anthropic_cls, mock_sleep):
        mock_create = mock_anthropic_cls.return_value.messages.create
        mock_create.side_effect = anthropic.RateLimitError("rate limited", response=MagicMock(), body=None)

        with self.assertRaises(anthropic.RateLimitError):
            indexer._messages_create_retry("ctx", 10, model="m", max_tokens=10,
                                            messages=[{"role": "user", "content": "p"}])

        self.assertEqual(mock_create.call_count, indexer.MAX_RETRIES)


# ---------------------------------------------------------------------------
# B7 — schemas/call sites not yet migrated: document_zone / document_architecture
# share one tool object, unwrap {"modules": [...]}; generate_case_summary indexes
# directly (KeyError on a missing key, no empty-string fallback); no manual
# JSON parsing remains anywhere in the 3 sites.
# ---------------------------------------------------------------------------

class CallClaudeToolTestCase(unittest.TestCase):

    @patch("anthropic.Anthropic")
    def test_sends_forced_tool_choice_and_returns_dict_and_tokens(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        tool = {"name": "mi_tool", "input_schema": {"type": "object", "properties": {}}}
        mock_create.return_value = _tool_response("mi_tool", {"a": 1})

        data, tokens = indexer._call_claude_tool("prompt", tool, context="ctx", max_tokens=50, model="m")

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [tool])
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "mi_tool"})
        self.assertEqual(data, {"a": 1})
        self.assertEqual(tokens, 520)


class DocumentZoneToolTestCase(unittest.TestCase):

    def _zone_setup(self, tmp_path):
        project = tmp_path / "proj"
        zone = project / "pagos"
        zone.mkdir(parents=True)
        (zone / "PagosController.php").write_text("<?php class PagosController {}", encoding="utf-8")
        return project, zone

    @patch("anthropic.Anthropic")
    def test_sends_document_modules_tool_and_unwraps_modules(self, mock_anthropic_cls):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project, zone = self._zone_setup(Path(tmp))
            mock_create = mock_anthropic_cls.return_value.messages.create
            payload = {"modules": [{
                "name": "pagos_controller", "description": "desc", "file_path": "pagos/PagosController.php",
                "category": "backend", "domain": None, "documentation": "# doc",
            }]}
            mock_create.return_value = _tool_response("documentar_modulos", payload)

            result = indexer.document_zone(project, zone, "PHP")

            kwargs = mock_create.call_args.kwargs
            self.assertEqual(kwargs["tools"], [indexer.DOCUMENT_MODULES_TOOL])
            self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "documentar_modulos"})
            self.assertEqual(result, payload["modules"])

    def test_no_manual_json_parsing_in_source(self):
        src = inspect.getsource(indexer.document_zone)
        self.assertNotIn("json.loads", src)
        self.assertNotIn("raw_decode", src)
        self.assertNotIn("_parse_json_claude", src)


class DocumentArchitectureToolTestCase(unittest.TestCase):

    def _project_setup(self, tmp_path):
        project = tmp_path / "proj"
        modulo = project / "pagos"
        modulo.mkdir(parents=True)
        (modulo / "PagosController.php").write_text("<?php class PagosController {}", encoding="utf-8")
        return project

    @patch("anthropic.Anthropic")
    def test_sends_same_document_modules_tool_object_as_document_zone(self, mock_anthropic_cls):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project_setup(Path(tmp))
            mock_create = mock_anthropic_cls.return_value.messages.create
            payload = {"modules": [{
                "name": "pagos_controller", "description": "desc", "file_path": "pagos/PagosController.php",
                "category": "backend", "domain": None, "documentation": "# doc",
            }]}
            mock_create.return_value = _tool_response("documentar_modulos", payload)

            result = indexer.document_architecture(project, "proj", "PHP", ["pagos/PagosController.php"])

            kwargs = mock_create.call_args.kwargs
            self.assertIs(kwargs["tools"][0], indexer.DOCUMENT_MODULES_TOOL)
            self.assertEqual(result, payload["modules"])

    def test_no_manual_json_parsing_in_source(self):
        src = inspect.getsource(indexer.document_architecture)
        self.assertNotIn("json.loads", src)
        self.assertNotIn("raw_decode", src)
        self.assertNotIn("_parse_json_claude", src)


class GenerateCaseSummaryToolTestCase(unittest.TestCase):

    @patch("anthropic.Anthropic")
    def test_returns_jira_four_key_memoria_and_tokens(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        payload = {
            "jira": "mensaje jira", "nota_contextual": "el total no reflejaba el descuento",
            "investigado": "causa x", "hecho": "cambio y", "tener_en_cuenta": "ojo con z",
        }
        mock_create.return_value = _tool_response("registrar_resumen_caso", payload)

        jira, memoria, tokens = indexer.generate_case_summary("tarea", "diff", ["a.py"])

        kwargs = mock_create.call_args.kwargs
        self.assertEqual(kwargs["tools"], [indexer.CASE_SUMMARY_TOOL])
        self.assertEqual(kwargs["tool_choice"], {"type": "tool", "name": "registrar_resumen_caso"})
        self.assertEqual(jira, "mensaje jira")
        self.assertEqual(memoria, {
            "investigado": "causa x", "hecho": "cambio y",
            "tener_en_cuenta": "ojo con z", "nota_contextual": "el total no reflejaba el descuento",
        })
        self.assertEqual(tokens, 520)

    @patch("anthropic.Anthropic")
    def test_missing_required_key_raises_keyerror_not_empty_fallback(self, mock_anthropic_cls):
        mock_create = mock_anthropic_cls.return_value.messages.create
        # "hecho" ausente — con tool_choice forzado esto no debería ocurrir en la
        # práctica, pero si ocurre debe fallar ruidosamente, no degradar en silencio.
        payload = {"jira": "j", "nota_contextual": "n", "investigado": "i", "tener_en_cuenta": "t"}
        mock_create.return_value = _tool_response("registrar_resumen_caso", payload)

        with self.assertRaises(KeyError):
            indexer.generate_case_summary("tarea", "diff", ["a.py"])

    def test_no_manual_json_parsing_in_source(self):
        src = inspect.getsource(indexer.generate_case_summary)
        self.assertNotIn("json.loads", src)
        self.assertNotIn("raw_decode", src)
        self.assertNotIn("_parse_json_claude", src)
        self.assertNotIn("try:", src)


# ---------------------------------------------------------------------------
# Extractor + dead-code deletion guards
# ---------------------------------------------------------------------------

class ExtractToolInputRobustnessTestCase(unittest.TestCase):

    def test_skips_leading_thinking_block(self):
        response = _tool_response("mi_tool", {"modules": ["mod_a"]})
        result = indexer._extract_tool_input(response.content, "mi_tool")
        self.assertEqual(result, {"modules": ["mod_a"]})

    def test_raises_runtime_error_when_tool_block_absent(self):
        blocks = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="sin tool")]
        with self.assertRaises(RuntimeError):
            indexer._extract_tool_input(blocks, "mi_tool")


class DeadCodeRemovedTestCase(unittest.TestCase):

    def test_no_json_module_used_anywhere_in_indexer(self):
        # No manual JSON parsing remains — the module docstring for
        # `_extract_tool_input` legitimately mentions "json.loads" in prose
        # (explaining what it replaces), so this checks for actual parsing
        # calls, not every substring occurrence of the word "json".
        src = inspect.getsource(indexer)
        self.assertNotIn("import json", src)
        self.assertNotIn("json.loads(", src)
        self.assertNotIn("json.JSONDecoder", src)
        self.assertFalse(hasattr(indexer, "json"))

    def test_reparar_json_and_parse_json_claude_are_gone(self):
        self.assertFalse(hasattr(indexer, "_reparar_json"))
        self.assertFalse(hasattr(indexer, "_parse_json_claude"))


# ---------------------------------------------------------------------------
# Cross-cutting (X1/X2) — change-1 (prompt-caching) caching survives Unit A +
# Unit B combined. Unit A's `_detect_relevant_modules` (task.py) is the ONLY
# call site with a cached `system` array; the cache-prefix-shift caveat there
# (`tools` sits before `system` in Anthropic's cache-prefix — the first
# post-deploy call is an expected cache *write*, not a defect) is scoped to
# that one function and is unaffected by anything Unit B touches. Unit B's 3
# migrated call sites (generate_case_summary, document_zone,
# document_architecture) never used `system`/`cache_control` before this
# change and still don't — they have no cache prefix to shift.
# ---------------------------------------------------------------------------

class Change1CachingSurvivesUnitBTestCase(unittest.TestCase):

    def test_unit_b_call_sites_never_touch_system_or_cache_control(self):
        for fn in (indexer.generate_case_summary, indexer.document_zone, indexer.document_architecture):
            src = inspect.getsource(fn)
            self.assertNotIn("cache_control", src)
            self.assertNotIn('"system"', src)
            self.assertNotIn("system=", src)

    def test_messages_create_retry_and_call_claude_tool_do_not_hardcode_system(self):
        # _messages_create_retry/_call_claude_tool forward **kwargs untouched — neither
        # injects or strips a `system` key, so Unit A's cache_control block (built entirely
        # in task.py) reaches messages.create exactly as task.py constructs it.
        for fn in (indexer._messages_create_retry, indexer._call_claude_tool):
            src = inspect.getsource(fn)
            self.assertNotIn('kwargs["system"]', src)
            self.assertNotIn("kwargs['system']", src)


if __name__ == "__main__":
    unittest.main()
