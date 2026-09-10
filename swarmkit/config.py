"""Read and validate the local harness runner configuration."""

import json
import math
import string

from .core import SwarmError


RUNNER_FIELDS = {"prompt_file", "role", "task_id", "agent_id", "root", "workdir", "model"}
WORKSPACE_FIELDS = {"root", "repository", "base", "path", "task_id"}
DELIVERY_FIELDS = {
    "envelope_file",
    "content_file",
    "delivery_id",
    "extension_id",
    "channel",
    "subject",
    "agent_id",
    "root",
    "workdir",
    "swarmctl",
    "prompt_file",
}


def validate_command(command, fields, label):
    """Check the documented argv template before allocating work or invoking a provider."""
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(part, str) and part for part in command)
    ):
        raise SwarmError(label + " requires a non-empty argv array of non-empty strings")
    for index, part in enumerate(command):
        try:
            if "\0" in part:
                raise ValueError("arguments cannot contain NUL characters")
            for _, field, spec, conversion in string.Formatter().parse(part):
                if field is not None and (field not in fields or spec or conversion):
                    raise ValueError("use plain named placeholders: " + ", ".join(sorted(fields)))
        except ValueError as exc:
            raise SwarmError("%s argument %s: %s" % (label, index + 1, exc)) from exc


def render_command(command, values, label):
    validate_command(command, values, label)
    rendered = [part.format(**values) for part in command]
    if not rendered[0] or any("\0" in part for part in rendered):
        raise SwarmError(label + " rendered an empty executable or a NUL character")
    return rendered


def runner_config(root, require_command=True):
    path = root / "runner.json"
    if not path.exists():
        raise SwarmError("Missing runner config: %s" % path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SwarmError("Runner config must be a JSON object: %s" % path)
    if require_command:
        validate_command(config.get("command"), RUNNER_FIELDS, "Runner command in %s" % path)
    for key in ("models", "escalation_models"):
        models = config.get(key, {})
        if not isinstance(models, dict) or not all(
            isinstance(model, str) for model in models.values()
        ):
            raise SwarmError("Runner %s must map role names to strings in %s" % (key, path))
    if config.get("working_directory") is not None and not isinstance(
        config["working_directory"], str
    ):
        raise SwarmError("Runner working_directory must be a string in %s" % path)
    for key in ("timeout_seconds", "max_parallel"):
        value = config.get(key, 3600 if key == "timeout_seconds" else 3)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SwarmError("Runner %s must be a positive integer in %s" % (key, path))
    from .notifications import validate_subscriptions

    validate_subscriptions(config.get("notifications", []))
    for key, default in (
        ("scheduler_poll_seconds", 1),
        ("manager_review_debounce_seconds", 1),
        ("manager_review_min_interval_seconds", 0),
        ("manager_review_max_delay_seconds", 60),
    ):
        value = config.get(key, default)
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise SwarmError("Runner %s must be a finite non-negative number in %s" % (key, path))
    if config.get("scheduler_poll_seconds", 1) == 0:
        raise SwarmError("Runner scheduler_poll_seconds must be greater than zero")
    return config
