import unittest
from pathlib import Path

from aicli.db.models import Module
from aicli.services.builder import build_context


def _module(**overrides) -> Module:
    base = dict(
        id=1, project_id=1, name="mod", description="", file_path="a/b.py",
        content_path=str(Path(__file__)),  # cualquier archivo real, existe
        created_at="", last_updated_at=None,
    )
    base.update(overrides)
    return Module(**base)


class BuildContextProjectPathTypeTestCase(unittest.TestCase):
    """DEC: build_context normaliza project_path a Path — algún caller lo
    pasa como str en producción (str/str TypeError en el freshness check),
    el fix defiende el borde de la función en vez de perseguir cada caller."""

    def test_accepts_path_instance(self):
        context, warnings = build_context([_module()], project_path=Path.cwd())
        self.assertIsInstance(context, str)
        self.assertIsInstance(warnings, list)

    def test_accepts_string_without_raising(self):
        context, warnings = build_context([_module()], project_path=str(Path.cwd()))
        self.assertIsInstance(context, str)
        self.assertIsInstance(warnings, list)

    def test_accepts_none(self):
        context, warnings = build_context([_module()], project_path=None)
        self.assertIsInstance(context, str)
        self.assertIsInstance(warnings, list)


if __name__ == "__main__":
    unittest.main()
