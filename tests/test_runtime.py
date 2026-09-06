"""Adversarial runtime contracts: restart, races, fencing, and audit integrity."""
import concurrent.futures
import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
import zipfile

import swarmctl as s


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='swarm-runtime-')
        self.base = Path(self.temp.name)
        self.root = self.base / '.swarm'
        s.initialize(self.root, 'Recover safely', ['Verified result'], [])
        self.conn = s.connect(self.root)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def task(self, key=None):
        return s.add_task(self.conn, 'Inspect', 'Inspect safely', 'discovery', ['Checked'], [], 50, 'manager', True, idempotency_key=key)

    def claim(self, task, agent='worker'):
        return s.claim_task(self.conn, task, agent, 600)

    def config(self, command):
        path = self.root / 'runner.json'
        data = json.loads(path.read_text())
        data['command'] = command
        data['working_directory'] = str(self.base)
        data['manager_review_debounce_seconds'] = 0
        path.write_text(json.dumps(data))

    def expire(self, task):
        self.conn.execute("UPDATE tasks SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (task,))
        self.conn.commit()
        s.reconcile_conn(self.conn)

    def test_concurrent_claim_has_one_attempt_and_one_owner(self):
        task = self.task()
        def claim(agent):
            conn = s.connect(self.root)
            try:
                try:
                    s.claim_task(conn, task, agent, 600)
                    return True
                except s.SwarmError:
                    return False
            finally:
                conn.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(claim, ['a%d' % n for n in range(8)]))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 1)

    def test_pause_fences_old_attempt_resume_needs_new_identity(self):
        task = self.task()
        self.claim(task)
        s.control_mission(self.conn, 'pause', 'human', 'Change plans')
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, task, 'worker', 'late', ['Checked'], [])
        with self.assertRaises(s.SwarmError):
            self.claim(task, 'other')
        s.control_mission(self.conn, 'resume', 'human', 'Continue')
        with self.assertRaises(s.SwarmError):
            self.claim(task)
        self.assertEqual(self.claim(task, 'fresh'), 2)

    def test_drain_allows_completion_but_no_new_claims(self):
        task, other = self.task(), self.task()
        self.claim(task)
        s.control_mission(self.conn, 'drain', 'human', 'Finish current work')
        with self.assertRaises(s.SwarmError):
            self.claim(other)
        s.complete_task(self.conn, task, 'worker', 'done', ['Checked'], [])
        self.assertEqual(s.task_row(self.conn, task)['status'], 'DONE')

    def test_cancel_is_terminal_and_preserves_uncertain_actions(self):
        task = self.task(); self.claim(task)
        effect = s.prepare_effect(self.conn, task, 'worker', 'merge:abc', 'PR/1', 'abc', {'merge': True})
        s.transition_effect(self.conn, effect['id'], 'start', 'worker')
        s.control_mission(self.conn, 'cancel', 'human', 'Stop')
        self.assertEqual(s.task_row(self.conn, task)['status'], 'CANCELLED')
        self.assertEqual(s.uncertain_effects(self.conn)[0]['state'], 'UNKNOWN')
        with self.assertRaises(s.SwarmError):
            s.control_mission(self.conn, 'resume', 'human', 'Restart')
        with self.assertRaises(s.SwarmError):
            self.task()

    def test_effect_replay_is_deduplicated_and_uncertainty_blocks_reclaim(self):
        task = self.task(); self.claim(task)
        effect = s.prepare_effect(self.conn, task, 'worker', 'approve:abc', 'PR/1', 'abc', {})
        self.assertEqual(effect, s.prepare_effect(self.conn, task, 'worker', 'approve:abc', 'PR/1', 'abc', {}))
        with self.assertRaises(s.SwarmError):
            s.prepare_effect(self.conn, task, 'worker', 'approve:abc', 'PR/1', 'changed', {})
        s.transition_effect(self.conn, effect['id'], 'start', 'worker')
        with self.assertRaises(s.SwarmError):
            s.transition_effect(self.conn, effect['id'], 'start', 'worker')
        self.expire(task)
        with self.assertRaises(s.SwarmError):
            self.claim(task, 'fresh')
        s.transition_effect(self.conn, effect['id'], 'succeeded', 'human', 'Provider receipt 123 for abc')
        self.claim(task, 'fresh')
        self.assertEqual(s.prepare_effect(self.conn, task, 'fresh', 'approve:abc', 'PR/1', 'abc', {})['state'], 'SUCCEEDED')

    def test_inbox_expiry_redelivers_same_batch_and_fences_old_ack(self):
        self.task()
        first = s.lease_inbox(self.conn, 'recipient', limit=1)
        self.assertEqual(first, s.lease_inbox(self.conn, 'recipient', limit=1))
        self.conn.execute("UPDATE inbox_deliveries SET lease_until='2000-01-01T00:00:00Z'")
        self.conn.commit()
        second = s.lease_inbox(self.conn, 'recipient', limit=10)
        self.assertEqual(first['events'], second['events'])
        self.assertNotEqual(first['token'], second['token'])
        with self.assertRaises(s.SwarmError):
            s.ack_inbox(self.conn, first['token'], 'recipient')
        with self.assertRaises(s.SwarmError):
            s.ack_inbox(self.conn, second['token'], 'stranger')
        s.ack_inbox(self.conn, second['token'], 'recipient')
        self.assertTrue(s.ack_inbox(self.conn, second['token'], 'recipient')['duplicate'])
        self.assertGreater(s.lease_inbox(self.conn, 'recipient')['events'][0]['seq'], first['events'][-1]['seq'])

    def test_scoped_inbox_does_not_consume_other_task_events(self):
        a,b = self.task(), self.task()
        first = s.lease_inbox(self.conn, 'reader', task_id=a)
        s.ack_inbox(self.conn, first['token'], 'reader')
        other = s.lease_inbox(self.conn, 'reader', task_id=b)
        self.assertTrue(any(e['entity_id'] == b for e in other['events']))

    def test_resource_lease_conflict_and_stale_token(self):
        a,b = self.task(), self.task(); self.claim(a, 'a'); self.claim(b, 'b')
        first = s.acquire_resource(self.conn, 'pipeline/prod', a, 'a')
        with self.assertRaises(s.SwarmError):
            s.acquire_resource(self.conn, 'pipeline/prod', b, 'b')
        self.conn.execute("UPDATE resource_leases SET lease_until='2000-01-01T00:00:00Z'")
        self.conn.commit()
        second = s.acquire_resource(self.conn, 'pipeline/prod', b, 'b')
        self.assertNotEqual(first['token'], second['token'])
        with self.assertRaises(s.SwarmError):
            s.release_resource(self.conn, first['token'], 'a')
        s.release_resource(self.conn, second['token'], 'b')

    def test_current_evidence_rejects_wrong_revision_and_tampering(self):
        task = self.task()
        s.set_contract(self.conn, task, 'abc', 'linux', 'manager')
        self.claim(task)
        log = self.base / 'test.log'; log.write_text('passed')
        s.record_evidence(self.conn, task, 'worker', 'Checked', 'old', 'linux', 'test', 0, log)
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, task, 'worker', 'done', ['Checked'], [])
        s.record_evidence(self.conn, task, 'worker', 'Checked', 'abc', 'linux', 'test', 0, log)
        log.write_text('tampered')
        with self.assertRaises(s.SwarmError):
            s.complete_task(self.conn, task, 'worker', 'done', ['Checked'], [])
        log.write_text('passed')
        s.complete_task(self.conn, task, 'worker', 'done', ['Checked'], [])
        self.assertEqual(s.attempt_for_task(self.conn, task)['state'], 'SUCCEEDED')
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM artifacts WHERE task_id=? AND kind='verification'", (task,)).fetchone()[0], 2)

    def test_confirmation_survives_restart_and_requires_current_ack(self):
        task = self.task(); self.claim(task)
        decision = s.block_task(self.conn, task, 'worker', 'human_decision', 'Proceed?', 'Approve', ['yes','no'])
        self.assertEqual(s.attempt_for_task(self.conn, task)['state'], 'WAITING_HUMAN')
        self.conn.close(); self.conn = s.connect(self.root)
        s.resolve_decision(self.conn, decision, 'yes', 'human', 'yes')
        self.claim(task, 'fresh')
        with self.assertRaises(s.SwarmError):
            s.prepare_effect(self.conn, task, 'fresh', 'effect', 'prod', 'abc', {})
        s.acknowledge_decision(self.conn, decision, task, 'fresh')
        s.prepare_effect(self.conn, task, 'fresh', 'effect', 'prod', 'abc', {})

    def test_idempotent_planning_survives_reconnect_and_conflicting_retry(self):
        task = self.task('investigate')
        self.conn.close(); self.conn = s.connect(self.root)
        self.assertEqual(self.task('investigate'), task)
        with self.assertRaises(s.SwarmError):
            s.add_task(self.conn, 'Different', 'Inspect safely', 'discovery', ['Checked'], [], 50, 'manager', True, idempotency_key='investigate')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 1)

    def test_amendment_invalidates_old_plan_and_keeps_history(self):
        task = self.task(); self.claim(task)
        s.control_mission(self.conn, 'pause', 'human', 'New objective')
        s.amend_mission(self.conn, 'New objective', ['New criterion'], ['Bounded'], 'Changed plans', 'human')
        self.assertEqual(s.runtime_state(self.conn)['revision'], 2)
        self.assertEqual(s.task_row(self.conn, task)['authorized'], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM mission_amendments').fetchone()[0], 1)
        s.control_mission(self.conn, 'resume', 'human', 'Review plan')
        with self.assertRaises(s.SwarmError):
            self.claim(task, 'fresh')

    def test_failure_budget_persists_across_restart(self):
        task = self.task()
        for n in range(3):
            self.claim(task, 'worker-%d' % n); self.expire(task)
        self.conn.close(); self.conn = s.connect(self.root)
        with self.assertRaisesRegex(s.SwarmError, 'budget exhausted'):
            self.claim(task, 'last')
        s.configure_runtime(self.conn, {'max_attempts_per_task': 4})
        self.claim(task, 'last')

    def test_future_schema_rejected_without_relabeling(self):
        self.conn.execute("UPDATE meta SET value='99' WHERE key='schema_version'"); self.conn.commit()
        with self.assertRaises(s.SwarmError):
            s.connect(self.root)
        self.assertEqual(self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '99')

    def test_failed_migration_rolls_back_schema_and_version(self):
        self.conn.execute('DROP TABLE attempts')
        self.conn.execute("UPDATE meta SET value='6' WHERE key='schema_version'"); self.conn.commit()
        original = s.RUNTIME_SCHEMA
        with mock.patch.object(s, 'RUNTIME_SCHEMA', original + ';INVALID SQL;'):
            with self.assertRaises(sqlite3.Error):
                s.ensure_schema(self.conn)
        self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name='attempts'").fetchone())
        self.assertEqual(self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], '6')
        s.ensure_schema(self.conn)
        self.assertEqual(s.runtime_state(self.conn)['revision'], 1)

    def test_immutable_prompts_bounded_and_causally_stamped(self):
        task = self.task()
        for n in range(70):
            s.add_event(self.conn, s.mission(self.conn)['id'], 'task', task, 'LARGE', 'test', {'text': 'x' * 8000})
        self.conn.commit()
        first = s.write_prompt(self.root, 'worker', 'same', task)
        second = s.write_prompt(self.root, 'worker', 'same', task)
        self.assertNotEqual(first, second)
        self.assertLess(first.stat().st_size, 80000)
        self.assertIn('event_watermark', first.read_text())

    def test_launch_failure_is_closed_and_recoverable(self):
        task = self.task(); self.claim(task)
        self.config(['/definitely/missing/executable'])
        result = s.dispatch(self.root, 'worker', 'worker', task)
        self.assertEqual(result['exit_code'], 126)
        self.assertIsNotNone(self.conn.execute('SELECT ended_at FROM agent_runs').fetchone()[0])
        self.assertEqual(s.attempt_for_task(self.conn, task)['state'], 'INCOMPLETE')
        self.claim(task, 'fresh')

    def test_recovery_does_not_take_live_process_lock(self):
        task = self.task(); self.claim(task)
        path = self.root / 'runs' / 'R-test' / 'process.lock'
        with s.process_lock(path):
            self.conn.execute('INSERT INTO agent_runs(id,mission_id,role,task_id,agent_id,prompt_path,command_json,started_at) VALUES(?,?,?,?,?,?,?,?)',
                              ('R-test', s.mission(self.conn)['id'], 'worker', task, 'worker', 'prompt', '[]', s.utcnow()))
            self.conn.commit()
            self.assertEqual(len(s.recover_runs(self.root)['live_or_unverified']), 1)
            self.assertIsNone(self.conn.execute('SELECT ended_at FROM agent_runs').fetchone()[0])
        self.assertEqual(s.recover_runs(self.root)['recovered'], ['R-test'])
        self.claim(task, 'fresh')

    def test_controller_exclusion(self):
        self.config([sys.executable, '-c', 'pass'])
        with s.process_lock(self.root / 'controller.lock'):
            with self.assertRaises(s.SwarmError):
                s.run_loop(self.root, 1)

    def test_semantic_manager_commit_required_in_strict_mode(self):
        s.configure_runtime(self.conn, {}, strict_evidence=True)
        review_id, _ = s.request_manager_review(self.conn, 'Plan', 'mission', s.mission(self.conn)['id'])
        self.conn.commit()
        review = s.claim_manager_review(self.conn, 'manager', 600)
        s.finish_manager_review(self.conn, review_id, 'manager', True)
        self.assertEqual(self.conn.execute('SELECT status FROM manager_reviews').fetchone()[0], 'PENDING')
        s.claim_manager_review(self.conn, 'manager', 600)
        s.commit_review(self.conn, review_id, 'manager', [{'disposition':'no-change','rationale':'No eligible work'}], 'Reviewed every trigger')
        s.finish_manager_review(self.conn, review_id, 'manager', True)
        self.assertEqual(self.conn.execute('SELECT status FROM manager_reviews').fetchone()[0], 'DONE')

    def test_audit_database_and_views_match_and_privacy_allowlist(self):
        self.task()
        output = self.base / 'audit.zip'
        s.export_audit(self.root, output)
        self.assertTrue(s.verify_audit(output)['ok'])
        with zipfile.ZipFile(output) as archive:
            events = archive.read('swarm-audit/events.jsonl').decode().splitlines()
            manifest = json.loads(archive.read('swarm-audit/manifest.json'))
            self.assertEqual(json.loads(events[-1])['seq'], manifest['event_watermark'])
            raw_db = self.base / 'audit.sqlite3'; raw_db.write_bytes(archive.read('swarm-audit/state.sqlite3'))
        with sqlite3.connect(raw_db) as conn:
            self.assertEqual(conn.execute('SELECT MAX(seq) FROM events').fetchone()[0], manifest['event_watermark'])
        s.export_audit(self.root, output, share_safe=True)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(set(archive.namelist()), {'swarm-audit/manifest.json','swarm-audit/telemetry.json'})
            self.assertNotIn(str(self.root), ''.join(archive.read(n).decode() for n in archive.namelist()))
        with zipfile.ZipFile(output, 'a') as archive:
            archive.writestr('swarm-audit/unexpected.txt', 'tamper')
        self.assertFalse(s.verify_audit(output)['ok'])

    def test_workspace_isolated_from_original_checkout(self):
        repo = self.base / 'repo'; repo.mkdir()
        for command in (['git','init',str(repo)], ['git','-C',str(repo),'config','user.name','Test'],
                        ['git','-C',str(repo),'config','user.email','test@example.test']):
            subprocess.run(command, check=True, capture_output=True)
        (repo / 'file').write_text('original')
        subprocess.run(['git','-C',str(repo),'add','.'], check=True, capture_output=True)
        subprocess.run(['git','-C',str(repo),'commit','-m','initial'], check=True, capture_output=True)
        task = self.task()
        workspace = s.create_workspace(self.root, self.conn, task, repo, 'HEAD')
        (Path(workspace['path']) / 'file').write_text('changed')
        self.assertEqual((repo / 'file').read_text(), 'original')
        self.assertEqual(workspace, s.create_workspace(self.root, self.conn, task, repo, 'HEAD'))

    def test_controller_crash_preserves_child_lock_until_harness_exits(self):
        task = self.task(); self.claim(task)
        marker = self.base / 'started'
        self.config([sys.executable, '-c', 'from pathlib import Path; import time; Path(%r).touch(); time.sleep(1.5)' % str(marker)])
        controller = subprocess.Popen([sys.executable, '-B', str(Path(s.__file__)), '--root', str(self.root),
                                       'dispatch', '--role', 'worker', '--agent', 'worker', '--task', task],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists())
            controller.kill(); controller.wait(timeout=5)
            self.assertEqual(len(s.recover_runs(self.root)['live_or_unverified']), 1)
            recovered = []
            while not recovered and time.monotonic() < deadline:
                time.sleep(.05)
                recovered = s.recover_runs(self.root)['recovered']
            self.assertEqual(len(recovered), 1)
            self.claim(task, 'after-crash')
        finally:
            if controller.poll() is None:
                controller.kill(); controller.wait()
            controller.stderr.close()

    def test_manager_lease_expiration_does_not_touch_task_attempts(self):
        review_id, _ = s.request_manager_review(self.conn, 'Plan', 'mission', s.mission(self.conn)['id'])
        self.conn.commit()
        s.claim_manager_review(self.conn, 'manager', 600)
        self.conn.execute("UPDATE manager_reviews SET lease_until='2000-01-01T00:00:00Z'")
        self.conn.commit()
        s.reconcile_conn(self.conn)
        self.assertEqual(self.conn.execute('SELECT status FROM manager_reviews WHERE id=?', (review_id,)).fetchone()[0], 'PENDING')

    def test_prepared_effect_can_be_adopted_after_crash_before_request(self):
        task = self.task(); self.claim(task)
        effect = s.prepare_effect(self.conn, task, 'worker', 'key', 'PR/1', 'abc', {})
        self.expire(task); self.claim(task, 'fresh')
        adopted = s.prepare_effect(self.conn, task, 'fresh', 'key', 'PR/1', 'abc', {})
        self.assertEqual(adopted['id'], effect['id'])
        self.assertEqual(adopted['generation'], 2)
        s.transition_effect(self.conn, effect['id'], 'start', 'fresh')

    def test_fanin_waits_for_every_dependency(self):
        first, second = self.task(), self.task()
        reduce = s.add_task(self.conn, 'Integrate', 'Resolve all findings', 'verification', ['Checked'],
                            [first, second], 50, 'manager', True)
        self.claim(first, 'a'); self.claim(second, 'b')
        s.complete_task(self.conn, first, 'a', 'result', ['Checked'], [])
        self.assertEqual(s.task_row(self.conn, reduce)['status'], 'PROPOSED')
        s.complete_task(self.conn, second, 'b', 'result', ['Checked'], [])
        self.assertEqual(s.task_row(self.conn, reduce)['status'], 'READY')


    def test_orphaned_manager_reopens_review_without_waiting_for_lease(self):
        review_id, _ = s.request_manager_review(self.conn, 'Plan', 'mission', s.mission(self.conn)['id'])
        self.conn.commit(); s.claim_manager_review(self.conn, 'manager', 3600)
        self.conn.execute('INSERT INTO agent_runs(id,mission_id,role,agent_id,prompt_path,command_json,started_at) VALUES(?,?,?,?,?,?,?)',
                          ('R-manager', s.mission(self.conn)['id'], 'manager', 'manager', 'prompt', '[]', s.utcnow()))
        self.conn.commit()
        with s.process_lock(self.root / 'runs' / 'R-manager' / 'process.lock'):
            pass
        s.recover_runs(self.root)
        review = s.claim_manager_review(self.conn, 'new-manager', 600)
        self.assertEqual(review['id'], review_id)

    def test_policy_fanout_cannot_bypass_task_quota(self):
        source = Path(s.__file__).parent / 'examples' / 'policy-packs' / 'system-port'
        s.install_policy(self.conn, source, 'human')
        s.configure_runtime(self.conn, {'max_tasks': 2})
        with self.assertRaisesRegex(s.SwarmError, 'quota'):
            s.apply_policy(self.conn, 'system-port', ['goal=port','test_command=test'], None, 'manager', True)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM policy_applications').fetchone()[0], 0)

    def test_all_new_templates_apply_executable_dependency_graphs(self):
        for name in ('performance-investigation','pipeline-repair','system-port'):
            source = Path(s.__file__).parent / 'examples' / 'policy-packs' / name
            s.install_policy(self.conn, source, 'human')
            result = s.apply_policy(self.conn, name, ['goal=bounded goal','test_command=test'], None, 'manager', True)
            self.assertTrue(result)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM policy_applications').fetchone()[0], 3)
        self.assertTrue(s.doctor(self.conn)['ok'])

    def test_cancel_dependency_cancels_transitive_reducers(self):
        first = self.task()
        second = s.add_task(self.conn, 'Middle', 'Reduce', 'verification', ['Checked'], [first], 50, 'manager', True)
        last = s.add_task(self.conn, 'Last', 'Reduce', 'verification', ['Checked'], [second], 50, 'manager', True)
        s.cancel_task(self.conn, first, 'human', 'Obsolete')
        self.assertEqual(s.task_row(self.conn, last)['status'], 'CANCELLED')
        self.assertEqual(s.task_row(self.conn, second)['status'], 'CANCELLED')

    def test_amendment_deauthorizes_confirmation_waits(self):
        task = self.task(); self.claim(task)
        decision = s.block_task(self.conn, task, 'worker', 'human_decision', 'Proceed?', 'yes', ['yes','no'])
        s.control_mission(self.conn, 'pause', 'human', 'Revise')
        s.amend_mission(self.conn, 'Revised', ['Different'], [], 'New goal', 'human')
        s.resolve_decision(self.conn, decision, 'yes', 'human', 'yes')
        s.control_mission(self.conn, 'resume', 'human', 'Manager review')
        with self.assertRaises(s.SwarmError):
            self.claim(task, 'fresh')
        self.assertEqual(s.task_row(self.conn, task)['authorized'], 0)


    def test_audit_verify_cli_needs_no_mission_and_fails_for_corruption(self):
        output = self.base / 'audit.zip'; s.export_audit(self.root, output)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.main(['--root', str(self.base / 'absent'), 'audit-verify', str(output)]), 0)
        with zipfile.ZipFile(output, 'a') as archive:
            archive.writestr('extra', 'corrupt')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.main(['--root', str(self.base / 'absent'), 'audit-verify', str(output)]), 2)

    def test_exhausted_high_priority_task_does_not_starve_eligible_work(self):
        first, eligible = self.task(), self.task()
        for n in range(3):
            self.claim(first, 'failed-%d' % n); self.expire(first)
        self.config([sys.executable, '-c', 'pass'])
        path = self.root / 'runner.json'; config = json.loads(path.read_text()); config['max_parallel'] = 1; path.write_text(json.dumps(config))
        def dispatch(root, role, agent, task_id=None, dry_run=False):
            conn = s.connect(root)
            try:
                if task_id:
                    s.complete_task(conn, task_id, agent, 'result', ['Checked'], [])
            finally:
                conn.close()
            return {'exit_code':0}
        with mock.patch.object(s, 'dispatch', side_effect=dispatch):
            result = s.run_loop(self.root, 5)
        self.assertEqual(s.task_row(self.conn, eligible)['status'], 'DONE')
        self.assertEqual(result['state'], 'ESCALATED')


    def test_runtime_cli_end_to_end(self):
        task = self.task()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(['--root',str(self.root),'pause','--reason','CLI test']), 0)
        self.assertEqual(json.loads(output.getvalue())['desired_state'], 'PAUSED')
        for command in (['why'], ['inbox','--agent','reader','--lease'], ['configure','--limits','{"max_tasks":5}']):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(s.main(['--root',str(self.root)] + command), 0)


if __name__ == '__main__':
    unittest.main()
