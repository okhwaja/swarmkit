"""Completion reports distinguish delivered work, partial work, and cancellation."""

from pathlib import Path
import tempfile
import unittest

import swarmctl as s


class CompletionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-completion-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Review changes", ["Useful reviewed result"], [], "SERVICE")
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def task(self, stream=None, depends_on=None):
        return s.add_task(
            self.conn,
            "Inspect",
            "Inspect safely",
            "discovery",
            ["Checked"],
            depends_on or [],
            50,
            "manager",
            True,
            stream,
        )

    def case(self):
        return s.open_case(
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

    def finish(self, task):
        s.claim_task(self.conn, task, "worker-" + task, 600)
        s.complete_task(self.conn, task, "worker-" + task, "Useful result", ["Checked"], [])

    def test_mixed_case_completion_is_partial(self):
        case = self.case()
        extra = self.task(case["workstream_id"])
        s.link_case_task(self.conn, case["id"], extra, "manager")
        s.cancel_task(self.conn, extra, "manager", "Could not complete this part")
        self.finish(case["tasks"][0]["id"])
        current = s.case_row(self.conn, case["id"])
        self.assertEqual(current["status"], "DONE")
        self.assertEqual(current["completion_outcome"], "PARTIAL")
        self.assertEqual(
            s.workstream_row(self.conn, case["workstream_id"])["completion_outcome"], "PARTIAL"
        )

    def test_cancelled_intake_can_be_replaced_with_a_policy_without_cancelling_case(self):
        case = self.case()
        s.cancel_task(
            self.conn, case["tasks"][0]["id"], "manager", "Replace intake with a structured plan"
        )
        s.reconcile_conn(self.conn)
        s.install_policy(
            self.conn, Path(s.__file__).parent / "examples/policy-packs/pipeline-repair", "manager"
        )
        updated = s.apply_policy_to_case(
            self.conn,
            case["id"],
            "pipeline-repair",
            ["goal=Recover import", "test_command=run-checks"],
            "manager",
            True,
        )
        self.assertEqual(updated["status"], "ACTIVE")
        self.assertIsNone(updated["completion_outcome"])
        self.assertIsNone(updated["closed_at"])

    def test_cancelled_work_withdraws_questions_that_no_longer_block_anything(self):
        task = self.task()
        s.claim_task(self.conn, task, "worker", 600)
        decision = s.block_task(self.conn, task, "worker", "human_decision", "Proceed?", "Wait", [])
        s.cancel_task(self.conn, task, "manager", "This approach is obsolete")
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "CANCELLED")

    def test_shared_question_stays_open_for_other_active_tasks(self):
        task, other = self.task(), self.task()
        s.claim_task(self.conn, task, "worker", 600)
        decision = s.block_task(self.conn, task, "worker", "human_decision", "Proceed?", "Wait", [])
        s.link_decision(self.conn, decision, other, "manager")
        s.cancel_task(self.conn, task, "manager", "This part is obsolete")
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "OPEN")

    def test_repeating_a_case_link_does_not_reopen_completed_work(self):
        case = self.case()
        task = case["tasks"][0]["id"]
        self.finish(task)
        before = dict(s.case_row(self.conn, case["id"]))
        self.assertFalse(s.link_case_task(self.conn, case["id"], task, "manager"))
        self.assertEqual(dict(s.case_row(self.conn, case["id"])), before)

    def test_followup_clears_previous_completion_summary(self):
        case = self.case()
        self.finish(case["tasks"][0]["id"])
        s.add_case_signal(
            self.root,
            self.conn,
            case["id"],
            "review",
            "new-revision",
            "revision",
            "author",
            "Inspect revision 2",
            "ingress",
            wake=True,
        )
        current = s.case_row(self.conn, case["id"])
        self.assertEqual(current["status"], "ACTIVE")
        self.assertIsNone(current["result_summary"])

    def test_mission_with_cancelled_work_defaults_to_partial_completion(self):
        done, cancelled = self.task(), self.task()
        self.finish(done)
        s.cancel_task(self.conn, cancelled, "manager", "Deliver the available result")
        s.complete_mission(self.conn, "One of two requested slices was delivered", "manager", True)
        self.assertEqual(s.runtime_state(self.conn)["outcome"], "PARTIAL")

    def test_partial_workstream_is_visible_in_operator_reports(self):
        stream = s.add_workstream(self.conn, "Investigation", "Find the cause", "manager", "ACTIVE")
        done, cancelled = self.task(stream), self.task(stream)
        self.finish(done)
        s.cancel_task(self.conn, cancelled, "manager", "Out of scope")
        s.update_workstream(
            self.conn, stream, "manager", status="DONE", summary="Delivered the useful slice"
        )
        self.assertEqual(s.workstream_row(self.conn, stream)["completion_outcome"], "PARTIAL")
        self.assertIn("DONE / PARTIAL", s.render_status_report(self.root).read_text())

    def test_manager_can_explicitly_accept_cancelled_obsolete_work(self):
        done, obsolete = self.task(), self.task()
        self.finish(done)
        s.cancel_task(self.conn, obsolete, "manager", "Replaced by a better approach")
        s.complete_mission(
            self.conn,
            "All success criteria met; the cancelled approach was unnecessary",
            "manager",
            True,
            outcome="SUCCEEDED",
        )
        self.assertEqual(s.runtime_state(self.conn)["outcome"], "SUCCEEDED")

    def test_late_reply_to_withdrawn_question_is_retained_without_reopening_it(self):
        case = self.case()
        task = case["tasks"][0]["id"]
        s.claim_task(self.conn, task, "worker", 600)
        decision = s.block_task(self.conn, task, "worker", "human_decision", "Proceed?", "Wait", [])
        s.cancel_task(self.conn, task, "manager", "This approach is obsolete")
        reply = s.add_case_signal(
            self.root,
            self.conn,
            case["id"],
            "review",
            "late-reply",
            "reply",
            "author",
            "No need to continue",
            "ingress",
            decision_id=decision,
        )
        self.assertTrue(reply["created"])
        self.assertEqual(s.decision_row(self.conn, decision)["status"], "CANCELLED")
        self.assertEqual(s.case_row(self.conn, case["id"])["status"], "DONE")

    def test_empty_result_or_verification_cannot_complete_a_task(self):
        task = self.task()
        s.claim_task(self.conn, task, "worker", 600)
        for result, verification in (("", ["Checked"]), ("Result", [" "])):
            with self.assertRaises(s.SwarmError):
                s.complete_task(self.conn, task, "worker", result, verification, [])
        self.assertEqual(s.task_row(self.conn, task)["status"], "CLAIMED")

    def test_case_cancellation_cancels_dependent_work_outside_the_case(self):
        case = self.case()
        downstream = self.task(depends_on=[case["tasks"][0]["id"]])
        s.cancel_case(self.conn, case["id"], "human", "Stop this review")
        self.assertEqual(s.task_row(self.conn, downstream)["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
