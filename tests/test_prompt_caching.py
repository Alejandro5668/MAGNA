"""
Tests unitarios para aicli.commands.task — orden determinístico de la
consulta de módulos. La suite de cache_control (antes en este archivo) migró
a tests/test_task_graph.py cuando _detect_relevant_modules fue reemplazada
por el grafo multi-agente (aicli/services/task_graph.py).
Ejecutar: py -m pytest tests/test_prompt_caching.py -v
"""
import inspect
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import select

from aicli.commands import task
from aicli.db.models import Module
from aicli.services.indexer import _extract_tool_input


class ModuleQueryOrderingTestCase(unittest.TestCase):

    def test_execute_task_query_orders_by_module_id(self):
        # El literal ".order_by(Module.id)" debe existir en el código real de
        # _execute_task — si alguien lo revierte o lo cambia a Module.name,
        # este test falla.
        src = inspect.getsource(task._execute_task)
        self.assertIn(".order_by(Module.id)", src)
        self.assertNotIn(".order_by(Module.name)", src)

    def test_order_by_module_id_produces_ascending_sql(self):
        stmt = select(Module).order_by(Module.id)
        compiled = str(stmt)
        self.assertIn("ORDER BY", compiled)
        self.assertIn("module.id", compiled.lower())


class ExtractToolInputTestCase(unittest.TestCase):

    def test_skips_leading_thinking_and_text_blocks(self):
        blocks = [
            SimpleNamespace(type="thinking"),
            SimpleNamespace(type="text", text="ignorado"),
            SimpleNamespace(type="tool_use", name="mi_tool", input={"modules": ["mod_a"]}),
        ]

        result = _extract_tool_input(blocks, "mi_tool")

        self.assertEqual(result, {"modules": ["mod_a"]})

    def test_raises_when_no_matching_tool_block(self):
        blocks = [SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text="sin tool")]

        with self.assertRaises(RuntimeError):
            _extract_tool_input(blocks, "mi_tool")


if __name__ == "__main__":
    unittest.main()
