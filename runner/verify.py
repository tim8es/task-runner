"""Cheap, generic runtime check; never print private secret values or paths."""
import json
import os
import sys

from runner.execute import validate_repository


def verify(config):
    registry = config.get("TASK_RUNNER_REGISTRY", "")
    token = config.get("TASK_RUNNER_ACCESS_TOKEN", "")
    if not registry or not token:
        return "MISSING_BOOTSTRAP"
    try:
        validate_repository(registry)
        raw = config.get("TASK_RUNNER_ENV_JSON") or "{}"
        values = json.loads(raw)
        if not isinstance(values, dict):
            return "INVALID_BOOTSTRAP"
    except Exception:
        return "INVALID_BOOTSTRAP"
    if not values:
        return "EMPTY_PRIVATE_ENV_MAP"
    if any(not isinstance(value, str) or not value for value in values.values()):
        return "INVALID_BOOTSTRAP"
    return "READY"


def main():
    result = verify(os.environ)
    if result not in ("READY", "EMPTY_PRIVATE_ENV_MAP"):
        print("Generic runner configuration: " + result, file=sys.stderr)
        raise SystemExit(1)
    print("Generic runner configuration: READY")


if __name__ == "__main__":
    main()
