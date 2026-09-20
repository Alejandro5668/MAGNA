"""
Tests unitarios para las funciones puras de navegación/orden del dashboard
de tickets: unique_parent_keys, resolve_initial_board, build_board_rows,
move_focus, move_sub, target_ticket_id.
Ejecutar: .venv\\Scripts\\python.exe -m pytest tests/test_ticket_panel_nav.py -v

Sin Textual Pilot — llamadas directas, sin red, sin montar la app.
"""
import unittest

from aicli.tui.widgets import (
    unique_parent_keys,
    resolve_initial_board,
    build_board_rows,
    move_focus,
    move_sub,
    target_ticket_id,
    is_reopened_row,
    TicketPanel,
)


def _t(tid, board=None, bucket="en_curso", parent=None):
    return {
        "id": tid,
        "summary": f"resumen {tid}",
        "status": "En curso",
        "priority": "Media",
        "_bucket": bucket,
        "_board": board or (tid.split("-")[0] if "-" in tid else tid),
        "_rounds": 0,
        "_active": False,
        "parent": parent,
    }


# ─── unique_parent_keys ─────────────────────────────────────────────────────

class UniqueParentKeysTestCase(unittest.TestCase):

    def test_dedups_preserving_first_seen_order(self):
        tickets = [
            _t("SOL-2", parent={"key": "SOL-1", "summary": "Historia"}),
            _t("SOL-3", parent={"key": "SOL-4", "summary": "Otra"}),
            _t("SOL-5", parent={"key": "SOL-1", "summary": "Historia"}),
        ]
        self.assertEqual(unique_parent_keys(tickets), ["SOL-1", "SOL-4"])

    def test_skips_tickets_without_parent(self):
        tickets = [_t("SOL-1", parent=None), _t("SOL-2", parent={"key": "SOL-9", "summary": "s"})]
        self.assertEqual(unique_parent_keys(tickets), ["SOL-9"])

    def test_no_parents_returns_empty(self):
        tickets = [_t("SOL-1"), _t("SOL-2")]
        self.assertEqual(unique_parent_keys(tickets), [])


# ─── resolve_initial_board ──────────────────────────────────────────────────

class ResolveInitialBoardTestCase(unittest.TestCase):

    def test_active_ticket_determines_board(self):
        tickets = [_t("MAG-1", board="MAG"), _t("SOL-1", board="SOL")]
        self.assertEqual(resolve_initial_board(tickets, "SOL-1"), "SOL")

    def test_no_active_ticket_falls_back_alphabetical(self):
        tickets = [_t("SOL-1", board="SOL"), _t("MAG-1", board="MAG")]
        self.assertEqual(resolve_initial_board(tickets, None), "MAG")

    def test_active_ticket_not_in_list_falls_back_alphabetical(self):
        tickets = [_t("SOL-1", board="SOL"), _t("MAG-1", board="MAG")]
        self.assertEqual(resolve_initial_board(tickets, "OTHER-9"), "MAG")

    def test_no_tickets_returns_none(self):
        self.assertIsNone(resolve_initial_board([], "SOL-1"))
        self.assertIsNone(resolve_initial_board([], None))


# ─── build_board_rows ───────────────────────────────────────────────────────

class BuildBoardRowsTestCase(unittest.TestCase):

    def test_order_is_reopened_then_cards_then_loose(self):
        tickets = [
            _t("SOL-1", bucket="reabiertos"),
            _t("SOL-2", parent={"key": "SOL-9", "summary": "Historia"}),
            _t("SOL-3"),
        ]
        rows = build_board_rows(tickets, siblings={"SOL-9": []}, failed=set())
        self.assertEqual([r["_kind"] for r in rows], ["reopened", "card", "loose"])

    def test_reopened_ticket_never_duplicated_as_chip(self):
        tickets = [
            _t("SOL-1", bucket="reabiertos", parent={"key": "SOL-9", "summary": "Historia"}),
            _t("SOL-2", parent={"key": "SOL-9", "summary": "Historia"}),
        ]
        siblings = {
            "SOL-9": [
                {"id": "SOL-1", "summary": "s1", "status": "Reabierto", "tipo": "Sub-task"},
                {"id": "SOL-2", "summary": "s2", "status": "En curso", "tipo": "Sub-task"},
            ]
        }
        rows = build_board_rows(tickets, siblings=siblings, failed=set())
        card = next(r for r in rows if r["_kind"] == "card")
        chip_ids = [c["id"] for c in card["chips"]]
        self.assertNotIn("SOL-1", chip_ids)
        self.assertIn("SOL-2", chip_ids)

    def test_degraded_flag_when_parent_key_failed(self):
        tickets = [_t("SOL-2", parent={"key": "SOL-9", "summary": "Historia"})]
        rows = build_board_rows(tickets, siblings={}, failed={"SOL-9"})
        card = rows[0]
        self.assertTrue(card["degraded"])
        self.assertEqual(card["chips"], [])

    def test_non_degraded_card_has_no_flag(self):
        tickets = [_t("SOL-2", parent={"key": "SOL-9", "summary": "Historia"})]
        siblings = {"SOL-9": [{"id": "SOL-2", "summary": "s", "status": "En curso", "tipo": "Sub-task"}]}
        rows = build_board_rows(tickets, siblings=siblings, failed=set())
        self.assertFalse(rows[0]["degraded"])

    def test_empty_board_returns_empty_rows(self):
        self.assertEqual(build_board_rows([], siblings={}, failed=set()), [])

    def test_same_parent_collapses_to_one_card(self):
        tickets = [
            _t("SOL-2", parent={"key": "SOL-9", "summary": "Historia"}),
            _t("SOL-3", parent={"key": "SOL-9", "summary": "Historia"}),
        ]
        rows = build_board_rows(tickets, siblings={"SOL-9": []}, failed=set())
        cards = [r for r in rows if r["_kind"] == "card"]
        self.assertEqual(len(cards), 1)


# ─── move_focus / move_sub / target_ticket_id ──────────────────────────────

_ROWS = [
    {"_kind": "reopened", "label": "r1", "chips": [{"id": "R-1"}], "parent": None, "degraded": False},
    {
        "_kind": "card", "label": "Historia", "parent": {"key": "P-1", "summary": "h"}, "degraded": False,
        "chips": [{"id": "C-1"}, {"id": "C-2"}, {"id": "C-3"}],
    },
    {"_kind": "loose", "label": "l1", "chips": [{"id": "L-1"}], "parent": None, "degraded": False},
]

_DEGRADED_ROWS = [
    {"_kind": "card", "label": "Historia", "parent": {"key": "P-1", "summary": "h"}, "degraded": True, "chips": []},
]


class MoveFocusTestCase(unittest.TestCase):

    def test_clamped_no_wrap_at_top(self):
        self.assertEqual(move_focus(_ROWS, 0, -1), 0)

    def test_clamped_no_wrap_at_bottom(self):
        self.assertEqual(move_focus(_ROWS, len(_ROWS) - 1, 1), len(_ROWS) - 1)

    def test_moves_within_range(self):
        self.assertEqual(move_focus(_ROWS, 0, 1), 1)

    def test_empty_rows_returns_zero(self):
        self.assertEqual(move_focus([], 0, 1), 0)


class MoveSubTestCase(unittest.TestCase):

    _CASES = [
        # (rows, index, sub, delta, expected)
        (_ROWS, 1, 0, 1, 1),           # card: moves right
        (_ROWS, 1, 2, 1, 2),           # card: clamped at last chip, no wrap
        (_ROWS, 1, 0, -1, 0),          # card: clamped at first chip, no wrap
        (_ROWS, 0, 0, 1, 0),           # reopened row: no-op
        (_ROWS, 2, 0, 1, 0),           # loose row: no-op
        (_DEGRADED_ROWS, 0, 0, 1, 0),  # degraded card, no chips: no-op
    ]

    def test_table_driven(self):
        for rows, index, sub, delta, expected in self._CASES:
            with self.subTest(index=index, sub=sub, delta=delta):
                self.assertEqual(move_sub(rows, index, sub, delta), expected)


class TargetTicketIdTestCase(unittest.TestCase):

    def test_card_targets_sub_focused_chip(self):
        self.assertEqual(target_ticket_id(_ROWS, 1, 1), "C-2")

    def test_non_card_row_targets_its_only_chip(self):
        self.assertEqual(target_ticket_id(_ROWS, 0, 0), "R-1")
        self.assertEqual(target_ticket_id(_ROWS, 2, 0), "L-1")

    def test_degraded_card_with_no_chips_targets_parent_key(self):
        self.assertEqual(target_ticket_id(_DEGRADED_ROWS, 0, 0), "P-1")

    def test_out_of_range_index_returns_none(self):
        self.assertIsNone(target_ticket_id(_ROWS, 99, 0))
        self.assertIsNone(target_ticket_id([], 0, 0))


class IsReopenedRowTestCase(unittest.TestCase):

    def test_reopened_row_is_true(self):
        self.assertTrue(is_reopened_row(_ROWS, 0))

    def test_card_row_is_false(self):
        self.assertFalse(is_reopened_row(_ROWS, 1))

    def test_loose_row_is_false(self):
        self.assertFalse(is_reopened_row(_ROWS, 2))

    def test_out_of_range_index_returns_false(self):
        self.assertFalse(is_reopened_row(_ROWS, 99))
        self.assertFalse(is_reopened_row([], 0))


class TicketSelectedMessageTestCase(unittest.TestCase):
    """TicketPanel.TicketSelected debe llevar `reopened` seteado según el
    _kind de la fila enfocada al presionar Enter — sin necesidad de montar
    la app Textual."""

    def test_defaults_to_not_reopened(self):
        msg = TicketPanel.TicketSelected("SOL-1")
        self.assertEqual(msg.ticket_id, "SOL-1")
        self.assertFalse(msg.reopened)

    def test_reopened_row_produces_reopened_message(self):
        tid = target_ticket_id(_ROWS, 0, 0)
        reopened = is_reopened_row(_ROWS, 0)
        msg = TicketPanel.TicketSelected(tid, reopened=reopened)
        self.assertEqual(msg.ticket_id, "R-1")
        self.assertTrue(msg.reopened)

    def test_card_row_produces_non_reopened_message(self):
        tid = target_ticket_id(_ROWS, 1, 1)
        reopened = is_reopened_row(_ROWS, 1)
        msg = TicketPanel.TicketSelected(tid, reopened=reopened)
        self.assertEqual(msg.ticket_id, "C-2")
        self.assertFalse(msg.reopened)


if __name__ == "__main__":
    unittest.main()
