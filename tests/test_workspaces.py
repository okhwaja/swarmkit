"""Workspace adapters must work in source directories with no Git metadata."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from swarmkit import workspaces

import swarmctl as s


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='swarm-workspaces-')
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / '.swarm'
        self.source = self.base / 'monorepo with spaces'
        self.source.mkdir()
        s.initialize(self.root, 'VCS-neutral work', ['Verified'], [])
        self.conn = s.connect(self.root)
        self.task = s.add_task(self.conn, 'Inspect', 'Inspect', 'discovery', ['Checked'], [], 50, 'manager', True)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def configure(self, workspace):
        path = self.root / 'runner.json'
        config = json.loads(path.read_text())
        config['workspace'] = workspace
        path.write_text(json.dumps(config))

    def adapter(self):
        script = self.base / 'internal checkout adapter.py'
        script.write_text('''import json,sys
from pathlib import Path
source, destination, base, task = sys.argv[1:]
path = Path(destination)
path.mkdir()
(path / 'request.json').write_text(json.dumps({'source':source,'base':base,'task':task}))
print(json.dumps({'path':str(path),'base_revision':'internal-revision:42','workspace_ref':'jj-workspace:'+task}))
''')
        self.configure({'provider':'command','command':[sys.executable, str(script), '{repository}', '{path}', '{base}', '{task_id}']})

    def test_no_implicit_git_and_manual_registration_dispatches_in_checkout(self):
        with mock.patch.object(workspaces.subprocess, 'Popen') as process, mock.patch.object(workspaces.subprocess, 'run') as run:
            with self.assertRaisesRegex(s.SwarmError, 'No workspace creation provider'):
                s.create_workspace(self.root, self.conn, self.task, self.source, 'trunk()')
            process.assert_not_called(); run.assert_not_called()
        checkout = self.base / 'internal checkout'; checkout.mkdir()
        row = s.register_workspace(self.conn, self.task, self.source, checkout, 'opaque-revision')
        self.assertEqual(row['provider'], 'manual')
        self.assertEqual(row['workspace_ref'], '')
        config_path = self.root / 'runner.json'; config = json.loads(config_path.read_text())
        config['command'] = [sys.executable, '-c', 'import os; print(os.getcwd())']
        config_path.write_text(json.dumps(config))
        s.claim_task(self.conn, self.task, 'agent', 600)
        result = s.dispatch(self.root, 'worker', 'agent', self.task)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(Path(result['stdout']).read_text().strip(), str(checkout))

    def test_command_receipt_and_opaque_revision_are_preserved_without_git(self):
        self.adapter()
        expression = 'trunk() & ancestors(@) $(touch never)'
        with mock.patch.object(workspaces.subprocess, 'run', side_effect=AssertionError('Git must not be invoked')):
            row = s.create_workspace(self.root, self.conn, self.task, self.source, expression)
        self.assertEqual(row['base_revision'], 'internal-revision:42')
        self.assertEqual(row['provider'], 'command')
        self.assertEqual(row['requested_base'], expression)
        recorded = json.loads((Path(row['path']) / 'request.json').read_text())
        self.assertEqual(recorded, {'source':str(self.source), 'base':expression, 'task':self.task})
        with mock.patch.object(workspaces.subprocess, 'Popen', side_effect=AssertionError('Retry must not create again')):
            self.assertEqual(s.create_workspace(self.root, self.conn, self.task, self.source, expression), row)
        with self.assertRaisesRegex(s.SwarmError, 'different base'):
            s.create_workspace(self.root, self.conn, self.task, self.source, 'other()')

    def test_bad_receipt_failure_timeout_and_unknown_placeholders_do_not_register(self):
        for code, expected in [('print("not json")', 'JSON'), ('print("{}")', 'absolute path'),
                               ('raise SystemExit(3)', 'failed'), ('import time; time.sleep(10)', 'timed out')]:
            with self.subTest(code=code):
                self.configure({'provider':'command','command':[sys.executable, '-c', code.replace('{','{{').replace('}','}}')], 'timeout_seconds':1})
                with self.assertRaisesRegex(s.SwarmError, expected):
                    s.create_workspace(self.root, self.conn, self.task, self.source, 'opaque')
                self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM workspaces').fetchone()[0], 0)
        self.configure({'provider':'command','command':['tool','{unknown}']})
        with mock.patch.object(workspaces.subprocess, 'Popen') as process:
            with self.assertRaisesRegex(s.SwarmError, 'placeholder'):
                s.create_workspace(self.root, self.conn, self.task, self.source, 'opaque')
            process.assert_not_called()

    def test_registration_checks_isolation_ownership_and_immutable_binding(self):
        checkout = self.base / 'checkout'; checkout.mkdir()
        with self.assertRaisesRegex(s.SwarmError, 'source directory'):
            s.register_workspace(self.conn, self.task, self.source, self.source, 'revision')
        s.claim_task(self.conn, self.task, 'owner', 600)
        with self.assertRaises(s.SwarmError):
            s.register_workspace(self.conn, self.task, self.source, checkout, 'revision', agent='stale')
        row = s.register_workspace(self.conn, self.task, self.source, checkout, 'revision', 'workspace-name', agent='owner')
        self.assertEqual(row, s.register_workspace(self.conn, self.task, self.source, checkout, 'revision', 'workspace-name', agent='owner'))
        with self.assertRaisesRegex(s.SwarmError, 'immutable'):
            s.register_workspace(self.conn, self.task, self.source, checkout, 'other-revision', agent='owner')
        other = s.add_task(self.conn, 'Other', 'Other', 'discovery', ['Checked'], [], 50, 'manager', True)
        with self.assertRaisesRegex(s.SwarmError, 'another task'):
            s.register_workspace(self.conn, other, self.source, checkout, 'revision')

    def test_migration_preserves_old_git_workspaces(self):
        self.conn.execute('DROP TABLE workspaces')
        self.conn.execute('CREATE TABLE workspaces (task_id TEXT PRIMARY KEY REFERENCES tasks(id),path TEXT NOT NULL UNIQUE,repository TEXT NOT NULL,base_revision TEXT NOT NULL,branch TEXT NOT NULL)')
        self.conn.execute('INSERT INTO workspaces VALUES(?,?,?,?,?)', (self.task,'/checkout','/source','sha','branch'))
        self.conn.execute("UPDATE meta SET value='7' WHERE key='schema_version'"); self.conn.commit()
        self.conn.close(); self.conn = s.connect(self.root)
        row = dict(self.conn.execute('SELECT * FROM workspaces').fetchone())
        self.assertEqual(row['provider'], 'git')
        self.assertEqual(row['base_revision'], 'sha')
        self.assertIsNone(row['requested_base'])
        self.assertEqual(self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0], s.SCHEMA_VERSION)

    def test_register_cli_and_missing_checkout_error(self):
        checkout = self.base / 'checkout'; checkout.mkdir()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(s.main(['--root',str(self.root),'workspace','register','--task',self.task,
                                    '--repository',str(self.source),'--path',str(checkout),'--base-revision','internal:42']), 0)
        self.assertEqual(json.loads(output.getvalue())['provider'], 'manual')
        checkout.rmdir()
        config_path = self.root / 'runner.json'; config = json.loads(config_path.read_text())
        config['command'] = [sys.executable, '-c', 'pass']; config_path.write_text(json.dumps(config))
        with self.assertRaisesRegex(s.SwarmError, 'workspace is missing'):
            s.dispatch(self.root, 'worker', 'worker', self.task, dry_run=True)


if __name__ == '__main__':
    unittest.main()
