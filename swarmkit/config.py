"""Read and validate the local harness runner configuration."""

import json

from .core import SwarmError


def runner_config(root):
    path = root / "runner.json"
    if not path.exists():
        raise SwarmError("Missing runner config: %s" % path)
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise SwarmError("Runner config must be a JSON object: %s" % path)
    if (
        not isinstance(config.get("command"), list)
        or not config["command"]
        or not all(isinstance(part, str) and part for part in config["command"])
    ):
        raise SwarmError("Configure the non-empty argv array in %s" % path)
    if not isinstance(config.get("escalation_models", {}), dict):
        raise SwarmError("Runner escalation_models must be an object")
    if not isinstance(config.get("models", {}), dict):
        raise SwarmError("Runner models must be an object in %s" % path)
    if config.get("working_directory") is not None and not isinstance(
        config["working_directory"], str
    ):
        raise SwarmError("Runner working_directory must be a string in %s" % path)
    for key in ("timeout_seconds", "max_parallel"):
        value = config.get(key, 3600 if key == "timeout_seconds" else 3)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SwarmError("Runner %s must be a positive integer in %s" % (key, path))
    for key, default in (("scheduler_poll_seconds", 1), ("manager_review_debounce_seconds", 1)):
        value = config.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise SwarmError("Runner %s must be a non-negative number in %s" % (key, path))
    if config.get("scheduler_poll_seconds", 1) == 0:
        raise SwarmError("Runner scheduler_poll_seconds must be greater than zero")
    return config
