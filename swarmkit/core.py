"""Small shared utilities, identifiers, timestamps, and domain constants."""

from pathlib import Path
import contextlib
import datetime as dt
import fcntl
import functools
import hashlib
import json
import os
import secrets
import signal
import subprocess


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = PACKAGE_ROOT / "swarmctl.py"

VERSION = "0.12.0"


SCHEMA_VERSION = "12"


ACTIVE_TASK_STATES = {"CLAIMED", "RUNNING", "VERIFYING"}


TERMINAL_TASK_STATES = {"DONE", "CANCELLED"}


VALID_TASK_STATES = {
    "PROPOSED",
    "READY",
    "CLAIMED",
    "RUNNING",
    "VERIFYING",
    "BLOCKED",
    "WAITING_EXTERNAL",
    "DONE",
    "CANCELLED",
}


VALID_TASK_KINDS = {"discovery", "implementation", "verification", "briefing"}


VALID_WORKSTREAM_STATES = {"PLANNED", "ACTIVE", "BLOCKED", "VERIFYING", "DONE", "CANCELLED"}


VALID_FORECAST_CONFIDENCE = {"low", "medium", "high"}


VALID_BLOCKER_KINDS = {
    "human_decision",
    "missing_access",
    "external_dependency",
    "technical_failure",
    "safety_stop",
    "resource_conflict",
}


VALID_DELIVERY_STATES = {"PENDING", "CLAIMED", "SENT", "FAILED", "UNKNOWN", "CANCELLED"}


VALID_CASE_STATES = {
    "OPEN",
    "ACTIVE",
    "WAITING_HUMAN",
    "WAITING_EXTERNAL",
    "VERIFYING",
    "DONE",
    "CANCELLED",
}


VALID_MISSION_MODES = {"FINITE", "SERVICE"}


VALID_FINDING_SIGNIFICANCE = {"ROUTINE", "MATERIAL", "URGENT"}


VALID_FINDING_STATES = {"OPEN", "INCORPORATED", "DEFERRED", "DISMISSED"}


VALID_WAIT_STATES = {"WAITING", "WOKEN", "CANCELLED"}


VALID_WAKE_REASONS = {"SCHEDULED_CHECK", "EXTERNAL_SIGNAL", "DEADLINE"}


VALID_MANAGER_REVIEW_STATES = {"PENDING", "RUNNING", "DONE", "CANCELLED"}


class SwarmError(Exception):
    pass


@contextlib.contextmanager
def transaction(conn):
    """Commit one operation; nested operations roll back to their own savepoint.

    The caller owns any transaction already open on this connection. A domain
    helper must never commit that caller's partially constructed plan.
    """
    nested = conn.in_transaction
    savepoint = "swarm_" + secrets.token_hex(8)
    conn.execute("SAVEPOINT " + savepoint if nested else "BEGIN IMMEDIATE")
    try:
        yield conn
        if nested:
            conn.execute("RELEASE " + savepoint)
        else:
            conn.commit()
    except BaseException:
        if nested:
            conn.execute("ROLLBACK TO " + savepoint)
            conn.execute("RELEASE " + savepoint)
        else:
            conn.rollback()
        raise


def atomic_write(function):
    """Give a connection-first domain operation one durable transaction."""

    @functools.wraps(function)
    def wrapped(conn, *args, **kwargs):
        with transaction(conn):
            return function(conn, *args, **kwargs)

    return wrapped


@contextlib.contextmanager
def read_snapshot(conn):
    """Keep related reads at one database version without owning a caller's transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN")
    try:
        yield conn
    finally:
        conn.rollback()  # Release a read snapshot on success or failure.


def consistent_read(function):
    """Give a connection-first projection one stable read snapshot."""

    @functools.wraps(function)
    def wrapped(conn, *args, **kwargs):
        with read_snapshot(conn):
            return function(conn, *args, **kwargs)

    return wrapped


def utcnow():
    return (
        dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def parse_time(value):
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SwarmError("Timestamp must include a timezone: %s" % value)
    return parsed


def canonical_time(value):
    return (
        parse_time(value)
        .astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def make_id(prefix):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    return "%s-%s-%s" % (prefix, stamp, secrets.token_hex(4).upper())


def json_dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_load(value, default=None):
    if value is None or value == "":
        return default
    return json.loads(value)


def root_path(value):
    return Path(value or os.environ.get("SWARM_ROOT", ".swarm")).expanduser().resolve()


def db_path(root):
    return root / "state.sqlite3"


def delivery_content_intact(delivery):
    try:
        path = Path(delivery["content_path"])
        if not path.is_file():
            return False
        sha, size = hash_file(path)
    except OSError:
        return False
    return sha == delivery["content_sha256"] and size == delivery["content_size_bytes"]


def hash_file(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def case_payload_intact(path, expected_sha, expected_size):
    if not path:
        return True
    try:
        candidate = Path(path)
        if not candidate.is_file():
            return False
        sha, size = hash_file(candidate)
    except OSError:
        return False
    return sha == expected_sha and size == expected_size


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def future_time(seconds):
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
        raise SwarmError("Lease duration must be a positive integer")
    return (parse_time(utcnow()) + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


@contextlib.contextmanager
def process_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SwarmError("Another process owns %s" % path.name)
        # Closing, without LOCK_UN, lets an inherited child descriptor retain
        # the lock after a controller crash until the actual process exits.
        yield handle


def run_logged_process(command, workdir, timeout, stdout_path, stderr_path, lock_handle):
    """Run one owned process group with streaming logs and an inherited live lock.

    Return (exit_code, started). Only a failure before Popen succeeds proves that
    this invocation could not have performed an external action.
    """
    with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=str(workdir),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                pass_fds=(lock_handle.fileno(),),
            )
        except OSError as exc:
            stderr.write("Could not start process: %s\n" % exc)
            return 126, False
        try:
            return process.wait(timeout=timeout), True
        except subprocess.TimeoutExpired:
            stderr.write("\nProcess timed out after %s seconds.\n" % timeout)
            return 124, True
        finally:
            # Background children must not outlive the invocation recorded in SQLite.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()


def completion_outcome(statuses):
    """Summarize terminal work without treating cancelled slices as delivered."""
    states = set(statuses)
    if states - TERMINAL_TASK_STATES:
        return None
    if states == {"CANCELLED"}:
        return "CANCELLED"
    if "CANCELLED" in states:
        return "PARTIAL"
    return "SUCCEEDED"
