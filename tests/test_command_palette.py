"""
Tests unitarios para la paleta de comandos (`aicli.tui.modals.filter_entries`,
`PaletteEntry`) y el catálogo/dispatch de `aicli.tui.screens`
(`_PALETTE_ENTRIES`, `_cmd_desc`, `_setting_branch`).
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_command_palette.py -v
"""
import unittest

from aicli.tui.modals import PaletteEntry, filter_entries
from aicli.tui.screens import _PALETTE_ENTRIES, _cmd_desc, _setting_branch, _ENV_LABELS


_ENTRIES = (
    PaletteEntry("cmd", "resume", "COMANDO", "resume", "Resume ticket"),
    PaletteEntry("cmd", "status", "COMANDO", "status", "View architecture"),
    PaletteEntry("setting", "k:GEMINI_API_KEY", "CREDENCIAL", "GEMINI_API_KEY", "Gemini API Key", "GEMINI_API_KEY"),
    PaletteEntry("setting", "test:gemini", "SISTEMA", "Probar conexión Gemini", "Probar conexión Gemini"),
)


class FilterEntriesTestCase(unittest.TestCase):

    def test_empty_query_returns_all(self):
        self.assertEqual(filter_entries(_ENTRIES, ""), list(_ENTRIES))

    def test_none_query_returns_all(self):
        self.assertEqual(filter_entries(_ENTRIES, None), list(_ENTRIES))

    def test_whitespace_query_returns_all(self):
        self.assertEqual(filter_entries(_ENTRIES, "   "), list(_ENTRIES))

    def test_case_insensitive_name_hit(self):
        self.assertEqual(filter_entries(_ENTRIES, "RESUME"), [_ENTRIES[0]])

    def test_case_insensitive_desc_hit(self):
        # "gemini" no está en el name de test:gemini's name campo directamente
        # pero sí en desc de ambos — matchea los dos.
        result = filter_entries(_ENTRIES, "gemini")
        self.assertEqual(result, [_ENTRIES[2], _ENTRIES[3]])

    def test_no_match_returns_empty(self):
        self.assertEqual(filter_entries(_ENTRIES, "zzz"), [])

    def test_order_preserved(self):
        result = filter_entries(_ENTRIES, "e")
        self.assertEqual(result, [e for e in _ENTRIES if "e" in f"{e.name} {e.desc}".lower()])


class PaletteCatalogTestCase(unittest.TestCase):

    def test_catalog_has_exactly_sixteen_entries(self):
        self.assertEqual(len(_PALETTE_ENTRIES), 16)

    def test_catalog_ids_are_unique(self):
        ids = [e.id for e in _PALETTE_ENTRIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_catalog_entries_have_non_empty_name_and_desc(self):
        for entry in _PALETTE_ENTRIES:
            self.assertTrue(entry.name.strip(), f"{entry.id} sin name")
            self.assertTrue(entry.desc.strip(), f"{entry.id} sin desc")

    def test_credential_env_keys_are_known_labels(self):
        for entry in _PALETTE_ENTRIES:
            if entry.category == "CREDENCIAL":
                self.assertIn(entry.env_key, _ENV_LABELS)

    def test_cmd_ids_are_dispatched_by_worker_cmd(self):
        import inspect
        from aicli.tui import screens as screens_mod
        src = inspect.getsource(screens_mod._dispatch_tui) + inspect.getsource(screens_mod.MainScreen._worker_cmd)
        cmd_ids = [e.id for e in _PALETTE_ENTRIES if e.kind == "cmd"]
        self.assertEqual(sorted(cmd_ids), ["archive", "claude", "file", "resume", "status", "sync", "task"])
        for cmd_id in cmd_ids:
            self.assertIn(f'"{cmd_id}"', src)


class SettingBranchTestCase(unittest.TestCase):

    def test_every_setting_id_maps_to_a_non_empty_branch(self):
        for entry in _PALETTE_ENTRIES:
            if entry.kind == "setting":
                self.assertNotEqual(_setting_branch(entry.id), "", f"{entry.id} sin branch")

    def test_credential_branch(self):
        self.assertEqual(_setting_branch("k:GEMINI_API_KEY"), "cred")
        self.assertEqual(_setting_branch("k:JIRA_TOKEN"), "cred")

    def test_rules_and_system_branches(self):
        self.assertEqual(_setting_branch("rules:add"), "rules-add")
        self.assertEqual(_setting_branch("rules:del"), "rules-del")
        self.assertEqual(_setting_branch("test:gemini"), "test-gemini")
        self.assertEqual(_setting_branch("logs"), "logs")

    def test_unknown_id_returns_empty_string(self):
        self.assertEqual(_setting_branch("nope"), "")
        self.assertEqual(_setting_branch(""), "")


class CmdDescTestCase(unittest.TestCase):

    def test_resolves_all_seven_command_ids(self):
        expected = {
            "file": "Document folder",
            "archive": "Analyze file",
            "task": "Claude task context",
            "sync": "Sync docs post-task",
            "resume": "Resume ticket",
            "claude": "Claude full context",
            "status": "View architecture",
        }
        for cmd_id, desc in expected.items():
            self.assertEqual(_cmd_desc(cmd_id), desc)

    def test_unknown_command_returns_empty_string(self):
        self.assertEqual(_cmd_desc("nope"), "")


if __name__ == "__main__":
    unittest.main()
