"""Fresh invocation context stays useful when mission history grows."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import prompts


class PromptTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-prompts-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Review changes", ["Current evidence"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def task(self):
        return s.add_task(
            self.conn,
            "Inspect",
            "Inspect safely",
            "discovery",
            ["Checked"],
            [],
            50,
            "manager",
            True,
        )

    def context(self, task=None):
        prompt = s.build_prompt(self.root, "worker" if task else "manager", "reader", task)
        return json.loads(prompt.rsplit("```json\n", 1)[1].split("\n```", 1)[0])

    def test_worker_does_not_load_the_whole_mission(self):
        task = self.task()
        statements = []
        connect = prompts.connect

        def traced_connect(root):
            conn = connect(root)
            conn.set_trace_callback(statements.append)
            return conn

        with mock.patch.object(prompts, "connect", side_effect=traced_connect):
            self.context(task)
        self.assertFalse(any("SELECT * FROM tasks ORDER BY" in sql for sql in statements))

    def test_latest_signal_is_visible_after_many_old_signals(self):
        case = s.open_case(
            self.root,
            self.conn,
            "review",
            "change-1",
            "Review",
            "Inspect",
            50,
            "ingress",
            ["Checked"],
            ready=True,
        )
        for index in range(30):
            s.add_case_signal(
                self.root,
                self.conn,
                case["id"],
                "review",
                str(index),
                "comment",
                "author",
                "Comment %d" % index,
                "ingress",
            )
        s.add_case_signal(
            self.root,
            self.conn,
            case["id"],
            "review",
            "latest",
            "update",
            "author",
            "LATEST REVISION NEEDS REVIEW",
            "ingress",
        )
        context = self.context(case["tasks"][0]["id"])
        self.assertIn("LATEST REVISION NEEDS REVIEW", json.dumps(context))

    def test_checkout_and_evidence_contract_are_in_worker_context(self):
        task = self.task()
        checkout = Path(self.temp.name) / "isolated-checkout"
        checkout.mkdir()
        s.register_workspace(
            self.conn, task, Path(self.temp.name), checkout, "jj-revision", "internal-checkout"
        )
        s.set_contract(self.conn, task, "jj-revision", "benchmark-host", "manager")
        context = self.context(task)
        self.assertIn(str(checkout), json.dumps(context))
        self.assertIn("benchmark-host", json.dumps(context))

    def test_large_context_retains_mission_task_and_runtime(self):
        task = self.task()
        self.conn.execute(
            "UPDATE tasks SET acceptance_json=? WHERE id=?",
            (json.dumps(["criterion " + "x" * 5000] * 40), task),
        )
        self.conn.commit()
        context = self.context(task)
        self.assertEqual(context["mission"]["objective"], "Review changes")
        self.assertEqual(context["task"]["id"], task)
        self.assertEqual(context["runtime"]["desired_state"], "ACTIVE")
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode()), 64000)


if __name__ == "__main__":
    unittest.main()
