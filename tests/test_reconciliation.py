"""Bulk reconciliation preserves human gates and keeps idle polling inexpensive."""

from pathlib import Path
import sys
import tempfile
import unittest

import swarmctl as s

sys.path.insert(0, str(Path(s.__file__).parent / "scripts"))
from benchmark_service import active_case_fixture


class ReconciliationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-reconcile-")
        self.root = Path(self.temp.name) / ".swarm"
        self.conn = active_case_fixture(s, self.root, 2)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def test_idle_poll_read_count_does_not_scale_with_active_cases_or_tasks(self):
        def reads():
            statements = []
            self.conn.set_trace_callback(
                lambda sql: (
                    statements.append(sql)
                    if sql.lstrip().upper().startswith(("SELECT", "WITH"))
                    else None
                )
            )
            try:
                self.assertEqual(s.reconcile_conn(self.conn), [])
            finally:
                self.conn.set_trace_callback(None)
            return len(statements)

        small = reads()
        self.conn.close()
        self.root = Path(self.temp.name) / "large"
        self.conn = active_case_fixture(s, self.root, 200)
        self.addCleanup(self.conn.close)
        large = reads()
        self.assertEqual(small, large)
        self.assertLess(large, 15)

    def test_case_state_precedence_and_terminal_outcomes(self):
        # Direct fixture changes isolate case classification from task mutators.
        combinations = [
            (["DONE", "DONE", "DONE", "DONE", "DONE"], None, "DONE", "SUCCEEDED"),
            (["DONE", "CANCELLED", "DONE", "CANCELLED", "DONE"], None, "DONE", "PARTIAL"),
            (["CANCELLED"] * 5, None, "DONE", "CANCELLED"),
            (
                ["DONE", "DONE", "WAITING_EXTERNAL", "PROPOSED", "PROPOSED"],
                None,
                "WAITING_EXTERNAL",
                None,
            ),
            (["DONE", "DONE", "VERIFYING", "PROPOSED", "PROPOSED"], None, "VERIFYING", None),
            (
                ["DONE", "DONE", "WAITING_EXTERNAL", "PROPOSED", "PROPOSED"],
                "missing_access",
                "WAITING_HUMAN",
                None,
            ),
            (
                ["DONE", "DONE", "VERIFYING", "PROPOSED", "PROPOSED"],
                "external_dependency",
                "WAITING_EXTERNAL",
                None,
            ),
        ]
        for states, decision_kind, expected, outcome in combinations:
            with self.subTest(states=states, decision=decision_kind):
                self.conn.execute("UPDATE cases SET status='ACTIVE' WHERE id='case-0'")
                self.conn.execute("DELETE FROM decision_tasks")
                self.conn.execute("DELETE FROM decisions")
                for n, state in enumerate(states):
                    self.conn.execute(
                        "UPDATE tasks SET status=?,result=? WHERE id=?",
                        (state, "Result %s" % n, "task-0-%s" % n),
                    )
                if decision_kind:
                    self.conn.execute(
                        "INSERT INTO decisions(id,mission_id,kind,question,options_json,requested_by,created_at,updated_at) VALUES('question',?,?,?,'[]','fixture',?,?)",
                        (
                            s.mission(self.conn)["id"],
                            decision_kind,
                            "Question",
                            s.utcnow(),
                            s.utcnow(),
                        ),
                    )
                    self.conn.execute("INSERT INTO decision_tasks VALUES('question','task-0-2')")
                self.conn.commit()
                s.reconcile_cases(self.conn)
                case = s.case_row(self.conn, "case-0")
                self.assertEqual(case["status"], expected)
                self.assertEqual(case["completion_outcome"], outcome)
                if expected == "DONE" and outcome != "CANCELLED":
                    self.assertTrue(case["result_summary"].startswith("Result 4"))

    def test_dependency_clearance_and_human_gate_are_evaluated_together(self):
        task = "task-0-3"
        self.conn.execute("UPDATE tasks SET status='BLOCKED' WHERE id=?", (task,))
        self.conn.execute(
            "INSERT INTO decisions(id,mission_id,kind,question,options_json,requested_by,created_at,updated_at) VALUES('question',?,'human_decision','Proceed?','[]','fixture',?,?)",
            (s.mission(self.conn)["id"], s.utcnow(), s.utcnow()),
        )
        self.conn.execute("INSERT INTO decision_tasks VALUES('question',?)", (task,))
        self.conn.commit()
        s.reconcile_conn(self.conn)
        self.assertEqual(s.task_row(self.conn, task)["status"], "BLOCKED")
        s.resolve_decision(self.conn, "question", "Proceed", "human")
        self.assertEqual(s.task_row(self.conn, task)["status"], "PROPOSED")
        self.conn.execute("UPDATE tasks SET status='DONE' WHERE id='task-0-2'")
        self.conn.commit()
        s.reconcile_conn(self.conn)
        self.assertEqual(s.task_row(self.conn, task)["status"], "READY")


if __name__ == "__main__":
    unittest.main()
