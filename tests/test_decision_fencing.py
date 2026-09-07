"""Changed instructions retire old attempts; acknowledgements belong to their owner."""

from pathlib import Path
import tempfile
import unittest

import swarmctl as s


class DecisionFencingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-decisions-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Repair a pipeline", ["Verified recovery"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)
        self.task = s.add_task(
            self.conn,
            "Repair",
            "Inspect then repair",
            "implementation",
            ["Recovered"],
            [],
            50,
            "manager",
            True,
        )
        s.claim_task(self.conn, self.task, "first", 600)
        self.decision = s.block_task(
            self.conn,
            self.task,
            "first",
            "human_decision",
            "Pause ingestion?",
            "Pause",
            ["Pause", "Continue"],
        )
        s.resolve_decision(self.conn, self.decision, "Pause ingestion", "human", "Pause")
        s.claim_task(self.conn, self.task, "second", 600)

    def test_blank_question_preserves_current_attempt(self):
        with self.assertRaises(s.SwarmError):
            s.block_task(self.conn, self.task, "second", "human_decision", " ", "", [])
        self.assertEqual(s.task_row(self.conn, self.task)["owner"], "second")

    def test_blank_answers_cannot_clear_or_revise_a_decision(self):
        with self.assertRaises(s.SwarmError):
            s.revise_decision(self.conn, self.decision, " ", "human")
        decision = s.block_task(
            self.conn, self.task, "second", "human_decision", "Proceed?", "Wait", []
        )
        with self.assertRaises(s.SwarmError):
            s.resolve_decision(self.conn, decision, " ", "human")
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "OPEN")

    def test_withdrawn_question_cannot_gate_new_work(self):
        decision = s.block_task(
            self.conn, self.task, "second", "human_decision", "Proceed?", "Wait", []
        )
        s.cancel_task(self.conn, self.task, "human", "Withdrawn")
        other = s.add_task(
            self.conn, "Other", "Other work", "discovery", ["Checked"], [], 50, "manager", True
        )
        with self.assertRaises(s.SwarmError):
            s.link_decision(self.conn, decision, other, "manager")
        self.assertFalse(s.link_decision(self.conn, decision, self.task, "manager"))

    def test_another_agent_cannot_acknowledge_for_the_owner(self):
        with self.assertRaises(s.SwarmError):
            s.acknowledge_decision(self.conn, self.decision, self.task, "stranger")
        self.assertEqual(s.unresolved_ack_count(self.conn, self.task), 1)

    def test_new_attempt_must_acknowledge_even_an_unchanged_answer(self):
        s.acknowledge_decision(self.conn, self.decision, self.task, "second")
        self.conn.execute(
            "UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (self.task,)
        )
        self.conn.commit()
        s.reconcile_conn(self.conn)
        s.claim_task(self.conn, self.task, "third", 600)
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, self.task, "third", "Recovered", ["Checked"], [])
        s.acknowledge_decision(self.conn, self.decision, self.task, "third")
        s.complete_task(self.conn, self.task, "third", "Recovered", ["Checked"], [])

    def test_revised_decision_retires_attempt_and_marks_inflight_effect_uncertain(self):
        s.acknowledge_decision(self.conn, self.decision, self.task, "second")
        effect = s.prepare_effect(
            self.conn, self.task, "second", "repair-1", "pipeline", "revision-1", {}
        )
        s.transition_effect(self.conn, effect["id"], "start", "second")
        s.revise_decision(self.conn, self.decision, "Keep ingestion running", "human", "Continue")
        attempt = s.attempt_for_task(self.conn, self.task)
        self.assertEqual(attempt["state"], "INTERRUPTED")
        self.assertIsNotNone(attempt["ended_at"])
        self.assertEqual(
            self.conn.execute("SELECT state FROM effects WHERE id=?", (effect["id"],)).fetchone()[
                0
            ],
            "UNKNOWN",
        )
        with self.assertRaises(s.SwarmError):
            s.claim_task(self.conn, self.task, "third", 600)

    def test_revised_decision_closes_obsolete_wait_without_claiming_external_success(self):
        s.acknowledge_decision(self.conn, self.decision, self.task, "second")
        wait = s.start_external_wait(
            self.conn,
            self.task,
            "second",
            "Job is complete",
            "job-1",
            "2099-01-01T00:00:00Z",
            signal_expected=True,
        )
        s.revise_decision(self.conn, self.decision, "Keep ingestion running", "human", "Continue")
        self.assertEqual(s.external_wait_row(self.conn, wait["id"])["status"], "CANCELLED")
        self.assertIsNone(s.task_row(self.conn, self.task)["result"])
        s.claim_task(self.conn, self.task, "third", 600)
        with self.assertRaises(s.SwarmError):
            s.acknowledge_decision(self.conn, self.decision, self.task, "second")

    def test_linking_new_decision_retires_the_running_attempt(self):
        other = s.add_task(
            self.conn, "Other", "Other", "discovery", ["Checked"], [], 50, "manager", True
        )
        s.claim_task(self.conn, other, "other-worker", 600)
        s.link_decision(self.conn, self.decision, other, "manager")
        self.assertEqual(s.attempt_for_task(self.conn, other)["state"], "INTERRUPTED")
        self.assertIsNotNone(s.attempt_for_task(self.conn, other)["ended_at"])


if __name__ == "__main__":
    unittest.main()
