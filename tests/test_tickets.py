"""
Tests unitarios para aicli.services.tickets — storage per-ticket, migracion
lazy desde tickets.json, merge-on-write, historial capado, cache de Jira y
cross-check de sesiones por PID.

Ejecutar: py -m unittest tests/test_tickets.py -v

Todos los tests usan MYCONTEXT_HOME apuntando a un tempdir — nunca tocan
~/.mycontext real.
"""
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TicketsStorageTestCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MYCONTEXT_HOME"] = self._tmp.name
        import aicli.services.tickets as tickets
        importlib.reload(tickets)
        self.tickets = tickets
        self.base = Path(self._tmp.name)

    def tearDown(self):
        os.environ.pop("MYCONTEXT_HOME", None)
        self._tmp.cleanup()

    # ── 1.2 ─────────────────────────────────────────────────────────────────

    def test_per_ticket_file_created_no_collision(self):
        self.tickets.save_round("PROJ-100", "desc A", [], "msg A")
        self.tickets.save_round("PROJ-200", "desc B", [], "msg B")

        path_a = self.base / "tickets" / "PROJ-100.json"
        path_b = self.base / "tickets" / "PROJ-200.json"
        self.assertTrue(path_a.exists())
        self.assertTrue(path_b.exists())

        data_a = json.loads(path_a.read_text(encoding="utf-8"))
        data_b = json.loads(path_b.read_text(encoding="utf-8"))
        self.assertEqual(len(data_a["rondas"]), 1)
        self.assertEqual(len(data_b["rondas"]), 1)
        self.assertEqual(data_a["rondas"][0]["mensaje_jira"], "msg A")
        self.assertEqual(data_b["rondas"][0]["mensaje_jira"], "msg B")

    # ── 1.3 ─────────────────────────────────────────────────────────────────

    def test_legacy_migration_additive_idempotent_readable(self):
        legacy_path = self.base / "tickets.json"
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_data = {
            "PROJ-50": {
                "descripcion": "Bug de login",
                "rondas": [
                    {"fecha": "2026-01-01", "archivos_tocados": ["a.py"], "mensaje_jira": "fix 1", "motivo_reapertura": None, "memoria": None},
                    {"fecha": "2026-01-02", "archivos_tocados": ["b.py"], "mensaje_jira": "fix 2", "motivo_reapertura": None, "memoria": None},
                    {"fecha": "2026-01-03", "archivos_tocados": ["c.py"], "mensaje_jira": "fix 3", "motivo_reapertura": None, "memoria": None},
                ],
                "branch": "PROJ-50-fix",
                "ultima_actividad": time.time(),
            }
        }
        original_bytes = json.dumps(legacy_data, ensure_ascii=False, indent=2)
        legacy_path.write_text(original_bytes, encoding="utf-8")

        tickets_loaded = self.tickets.load_tickets()
        self.assertIn("PROJ-50", tickets_loaded)
        self.assertEqual(len(tickets_loaded["PROJ-50"]["rondas"]), 3)
        self.assertEqual(tickets_loaded["PROJ-50"]["branch"], "PROJ-50-fix")

        # tickets.json nunca se toca
        self.assertEqual(legacy_path.read_text(encoding="utf-8"), original_bytes)

        migrated_path = self.tickets._ticket_path("PROJ-50")
        self.assertTrue(migrated_path.exists())
        migrated_before = migrated_path.read_text(encoding="utf-8")

        # segunda carga: no debe re-migrar ni duplicar
        tickets_loaded_2 = self.tickets.load_tickets()
        migrated_after = migrated_path.read_text(encoding="utf-8")
        self.assertEqual(len(tickets_loaded_2["PROJ-50"]["rondas"]), 3)
        self.assertEqual(migrated_before, migrated_after)
        self.assertEqual(legacy_path.read_text(encoding="utf-8"), original_bytes)

    # ── 1.4 ─────────────────────────────────────────────────────────────────

    def test_merge_on_write_round_and_branch_both_survive(self):
        self.tickets.save_round("PROJ-300", "desc", ["x.py"], "msg1")
        self.tickets.save_ticket_branch("PROJ-300", "feature/PROJ-300")
        self.tickets.save_round("PROJ-300", "desc", ["y.py"], "msg2")

        data = self.tickets._read_ticket("PROJ-300")
        self.assertEqual(data["branch"], "feature/PROJ-300")
        self.assertEqual(len(data["rondas"]), 2)

    # ── 1.5 ─────────────────────────────────────────────────────────────────

    def test_format_history_caps_at_5_plural_marker(self):
        for i in range(8):
            self.tickets.save_round("PROJ-400", "desc", [], f"msg {i + 1}")
        tickets_loaded = self.tickets.load_tickets()
        history = self.tickets.format_history("PROJ-400", tickets_loaded)

        self.assertIn("(3 rondas anteriores omitidas)", history)
        self.assertIn("Ronda 4", history)
        self.assertIn("Ronda 8", history)
        self.assertNotIn("Ronda 3 —", history)

    def test_format_history_singular_marker(self):
        for i in range(6):
            self.tickets.save_round("PROJ-401", "desc", [], f"msg {i + 1}")
        tickets_loaded = self.tickets.load_tickets()
        history = self.tickets.format_history("PROJ-401", tickets_loaded)

        self.assertIn("(1 ronda anterior omitida)", history)

    def test_format_history_no_marker_when_5_or_fewer(self):
        for i in range(4):
            self.tickets.save_round("PROJ-402", "desc", [], f"msg {i + 1}")
        tickets_loaded = self.tickets.load_tickets()
        history = self.tickets.format_history("PROJ-402", tickets_loaded)

        self.assertNotIn("omitida", history)
        self.assertIn("Ronda 1", history)
        self.assertIn("Ronda 4", history)

    # ── 1.6 ─────────────────────────────────────────────────────────────────

    def test_jira_cache_watermark_and_attachment_persist_across_reload(self):
        self.tickets.save_round("PROJ-500", "desc", [], "msg")
        self.tickets.save_comment_watermark("PROJ-500", "10042")
        self.tickets.save_processed_attachments(
            "PROJ-500", {"att-77": {"type": "image", "name": "qa.png", "text": "descripcion"}}
        )

        cache = self.tickets.get_jira_cache("PROJ-500")
        self.assertEqual(cache["last_comment_id"], "10042")
        self.assertIn("att-77", cache["processed_attachments"])

        importlib.reload(self.tickets)

        cache_reloaded = self.tickets.get_jira_cache("PROJ-500")
        self.assertEqual(cache_reloaded["last_comment_id"], "10042")
        self.assertIn("att-77", cache_reloaded["processed_attachments"])

    # ── 1.7 ─────────────────────────────────────────────────────────────────

    def test_save_active_ticket_keeps_motivo_on_empty_same_ticket(self):
        self.tickets.save_active_ticket("PROJ-600", "Reopen reason X")
        self.tickets.save_active_ticket("PROJ-600", "")

        active = self.tickets.read_active_ticket()
        self.assertEqual(active["ticket_id"], "PROJ-600")
        self.assertEqual(active["motivo_reapertura"], "Reopen reason X")

    def test_save_active_ticket_empty_does_not_leak_across_tickets(self):
        self.tickets.save_active_ticket("PROJ-601", "Reason for 601")
        self.tickets.save_active_ticket("PROJ-602", "")

        active = self.tickets.read_active_ticket()
        self.assertEqual(active["ticket_id"], "PROJ-602")
        self.assertEqual(active["motivo_reapertura"], "")

    # ── 1.8 ─────────────────────────────────────────────────────────────────

    def test_save_ticket_branch_new_ticket_sets_descripcion_and_actividad(self):
        self.tickets.save_ticket_branch("PROJ-700", "hotfix/PROJ-700")

        data = self.tickets._read_ticket("PROJ-700")
        self.assertEqual(data["branch"], "hotfix/PROJ-700")
        self.assertTrue(data.get("descripcion"))
        self.assertGreater(data["ultima_actividad"], 0)

        # no debe explotar con KeyError al formatear el historial inmediatamente
        tickets_loaded = self.tickets.load_tickets()
        history = self.tickets.format_history("PROJ-700", tickets_loaded)
        self.assertIsNotNone(history)

    # ── 1.9 ─────────────────────────────────────────────────────────────────

    def test_other_sessions_with_ticket_pid_crosscheck(self):
        own_pid = os.getpid()
        other_pid = own_pid + 1
        stale_pid = own_pid + 2
        malformed_pid = own_pid + 3

        own_path = self.base / f"ticket_activo_{own_pid}.json"
        own_path.write_text(
            json.dumps({"ticket_id": "PROJ-800", "motivo_reapertura": "x"}), encoding="utf-8"
        )

        other_path = self.base / f"ticket_activo_{other_pid}.json"
        other_path.write_text(
            json.dumps({"ticket_id": "PROJ-800", "motivo_reapertura": "y"}), encoding="utf-8"
        )

        stale_path = self.base / f"ticket_activo_{stale_pid}.json"
        stale_path.write_text(
            json.dumps({"ticket_id": "PROJ-800", "motivo_reapertura": "z"}), encoding="utf-8"
        )
        old_time = time.time() - (25 * 3600)
        os.utime(stale_path, (old_time, old_time))

        malformed_path = self.base / f"ticket_activo_{malformed_pid}.json"
        malformed_path.write_text("{not valid json", encoding="utf-8")

        result = self.tickets.other_sessions_with_ticket("PROJ-800")

        self.assertIn(other_pid, result)
        self.assertNotIn(own_pid, result)
        self.assertNotIn(stale_pid, result)
        self.assertNotIn(malformed_pid, result)


if __name__ == "__main__":
    unittest.main()
