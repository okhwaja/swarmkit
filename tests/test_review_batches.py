"""Manager bursts remain bounded and every trigger retains a semantic disposition."""

import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import swarmctl as s
from swarmkit import coordination


class ReviewBatchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="swarm-review-batches-")
        self.root = Path(self.temp.name) / ".swarm"
        s.initialize(self.root, "Review all important changes", ["Every trigger considered"], [])
        self.conn = s.connect(self.root)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.conn.close)

    def request(self, n, urgency="NORMAL"):
        return s.request_manager_review(self.conn, "task completed", "task", "task-%s" % n, urgency)

    def test_burst_is_bounded_and_duplicate_in_earlier_full_batch_is_not_requeued(self):
        total = coordination.MAX_REVIEW_TRIGGERS * 2 + 7
        identities = [self.request(n)[0] for n in range(total)]
        rows = self.conn.execute("SELECT * FROM manager_reviews ORDER BY rowid").fetchall()
        self.assertEqual([len(json.loads(row["triggers_json"])) for row in rows], [50, 50, 7])
        events = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(self.request(0), (identities[0], False))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], events)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM manager_review_trigger_keys").fetchone()[0],
            total,
        )

    def test_urgent_duplicate_promotes_its_original_batch_without_new_trigger(self):
        first = self.request(0)[0]
        for n in range(1, coordination.MAX_REVIEW_TRIGGERS + 1):
            self.request(n)
        self.assertEqual(self.request(0, "URGENT"), (first, True))
        review = s.claim_manager_review(self.conn, "manager", 600, debounce_seconds=3600)
        self.assertEqual(review["id"], first)
        self.assertEqual(len(review["triggers"]), coordination.MAX_REVIEW_TRIGGERS)
        self.assertIsNone(s.claim_manager_review(self.conn, "other-manager", 600))

    def test_each_batch_requires_all_dispositions_and_can_be_retried_after_expiry(self):
        s.configure_runtime(self.conn, {}, True, "human")
        for n in range(53):
            self.request(n)
        considered = []
        for index in range(2):
            owner = "manager-%s" % index
            review = s.claim_manager_review(self.conn, owner, 600)
            dispositions = [
                {
                    "disposition": "no-change",
                    "rationale": "Current plan already incorporates this result",
                }
                for _ in review["triggers"]
            ]
            with self.assertRaisesRegex(s.SwarmError, "one disposition"):
                s.commit_review(self.conn, review["id"], owner, dispositions[:-1], "Reviewed")
            s.commit_review(self.conn, review["id"], owner, dispositions, "Reviewed every trigger")
            s.finish_manager_review(self.conn, review["id"], owner, True)
            self.assertEqual(
                self.conn.execute(
                    "SELECT status FROM manager_reviews WHERE id=?", (review["id"],)
                ).fetchone()[0],
                "DONE",
            )
            considered += [trigger["entity_id"] for trigger in review["triggers"]]
        self.assertEqual(len(considered), 53)
        self.assertEqual(len(set(considered)), 53)
        repeat = self.request(0)[0]  # A new observation after review is a new trigger.
        leased = s.claim_manager_review(self.conn, "last-manager", 600)
        self.assertEqual(leased["id"], repeat)
        self.conn.execute(
            "UPDATE manager_reviews SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (repeat,)
        )
        self.conn.commit()
        s.reconcile_manager_reviews(self.conn)
        self.assertEqual(self.request(0), (repeat, False))

    def test_failed_request_rolls_back_trigger_index_and_payload_together(self):
        with mock.patch.object(coordination, "add_event", side_effect=RuntimeError("event failed")):
            with self.assertRaisesRegex(RuntimeError, "event failed"):
                self.request(0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM manager_reviews").fetchone()[0], 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM manager_review_trigger_keys").fetchone()[0], 0
        )
        self.assertTrue(self.request(0)[1])

    def test_review_cli_pages_summaries_and_retrieves_full_trigger_contract(self):
        for n in range(103):
            self.request(n)
        command = ["--root", str(self.root), "review"]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(command + ["list", "--limit", "2"]), 0)
        newest = json.loads(output.getvalue())
        self.assertEqual([row["trigger_count"] for row in newest], [3, 50])
        self.assertNotIn("triggers", newest[0])
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(command + ["list", "--before", newest[-1]["id"]]), 0)
        older = json.loads(output.getvalue())
        self.assertEqual(len(older), 1)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(command + ["show", older[0]["id"]]), 0)
        detail = json.loads(output.getvalue())
        self.assertEqual(len(detail["triggers"]), 50)
        self.assertEqual(detail["triggers"][0]["entity_id"], "task-0")
        self.assertIsNone(detail["commit"])

    def test_schema_ten_upgrade_preserves_large_legacy_review_and_indexes_identity(self):
        review = self.request(0)[0]
        triggers = [
            {
                "reason": "task completed",
                "entity_type": "task",
                "entity_id": "task-%s" % n,
                "requested_at": s.utcnow(),
            }
            for n in range(100)
        ]
        self.conn.execute(
            "UPDATE manager_reviews SET triggers_json=? WHERE id=?", (json.dumps(triggers), review)
        )
        self.conn.execute("DROP TABLE manager_review_trigger_keys")
        self.conn.execute("DROP INDEX idx_review_requested")
        self.conn.execute("UPDATE meta SET value='10' WHERE key='schema_version'")
        self.conn.commit()
        self.conn.close()
        self.conn = s.connect(self.root)
        self.addCleanup(self.conn.close)
        self.assertEqual(
            json.loads(
                self.conn.execute(
                    "SELECT triggers_json FROM manager_reviews WHERE id=?", (review,)
                ).fetchone()[0]
            ),
            triggers,
        )
        self.assertEqual(self.request(99), (review, False))
        new = self.request(100)[0]
        self.assertNotEqual(new, review)
        self.assertEqual(
            len(
                json.loads(
                    self.conn.execute(
                        "SELECT triggers_json FROM manager_reviews WHERE id=?", (new,)
                    ).fetchone()[0]
                )
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
