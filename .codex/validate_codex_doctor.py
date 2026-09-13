"""Validate the redacted JSON report emitted by ``codex doctor``."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

REPORT_SCHEMA_VERSION = 1
EXTERNAL_FAILURES = frozenset({"auth.credentials"})
KNOWN_STATUSES = frozenset({"ok", "idle", "note", "warning", "fail"})
REQUIRED_CHECKS = frozenset(
    {
        "app_server.status",
        "auth.credentials",
        "config.load",
        "git.environment",
        "installation",
        "mcp.config",
        "network.env",
        "network.provider_reachability",
        "network.websocket_reachability",
        "runtime.provenance",
        "runtime.search",
        "sandbox.helpers",
        "security.endpoint",
        "state.paths",
        "state.rollout_db_parity",
        "system.disk",
        "system.environment",
        "terminal.env",
        "terminal.title",
        "updates.status",
    }
)


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def reject_constant(value: str) -> None:
    raise ValueError(f"nonstandard JSON constant: {value}")


def strict_loads(raw: str) -> object:
    return json.loads(raw, object_pairs_hook=strict_object, parse_constant=reject_constant)


def report_problems(report: object) -> tuple[list[str], list[str]]:
    """Return fatal problems and explicitly tolerated external conditions."""

    if not isinstance(report, Mapping):
        return ["report is not a JSON object"], []
    problems: list[str] = []
    external: list[str] = []
    if report.get("schemaVersion") != REPORT_SCHEMA_VERSION:
        problems.append("unsupported report schema")
    for field in ("generatedAt", "codexVersion"):
        if not isinstance(report.get(field), str) or not report[field]:
            problems.append(f"top-level field is malformed: {field}")
    checks = report.get("checks")
    if not isinstance(checks, Mapping) or not checks:
        problems.append("checks are missing")
        return problems, external
    missing = REQUIRED_CHECKS - set(checks)
    problems.extend(f"required Doctor check is missing: {check_id}" for check_id in sorted(missing))

    failed: set[str] = set()
    for check_id, value in checks.items():
        if not isinstance(check_id, str) or not isinstance(value, Mapping):
            problems.append("check record is malformed")
            continue
        if value.get("id") != check_id:
            problems.append(f"check identity differs: {check_id}")
        for field in ("category", "summary"):
            if not isinstance(value.get(field), str) or not value[field]:
                problems.append(f"check field is malformed: {check_id}.{field}")
        if not isinstance(value.get("details"), Mapping):
            problems.append(f"check field is malformed: {check_id}.details")
        if value.get("remediation") is not None and not isinstance(value.get("remediation"), str):
            problems.append(f"check field is malformed: {check_id}.remediation")
        duration = value.get("durationMs")
        if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
            problems.append(f"check field is malformed: {check_id}.durationMs")
        status = value.get("status")
        if status not in KNOWN_STATUSES:
            problems.append(f"check status is unsupported: {check_id}")
        elif status == "fail":
            failed.add(check_id)

    external.extend(sorted(failed & EXTERNAL_FAILURES))
    problems.extend(f"Codex Doctor check failed: {check_id}" for check_id in sorted(failed - EXTERNAL_FAILURES))
    overall = report.get("overallStatus")
    if failed and overall != "fail":
        problems.append("overall status does not report failed checks")
    elif not failed and overall not in {"ok", "warning"}:
        problems.append("overall status is inconsistent with checks")
    return problems, external


def validate(report: object) -> list[str]:
    problems, external = report_problems(report)
    if problems:
        raise ValueError("\n".join(problems))
    return external


def validate_execution(report: object, returncode: int) -> list[str]:
    external = validate(report)
    expected_exit = 1 if external else 0
    if returncode != expected_exit:
        raise ValueError(f"Doctor exit {returncode} differs from report status")
    return external


def self_test() -> None:
    def sample(*, overall: str = "ok", auth: str = "ok", config: str = "ok") -> dict[str, Any]:
        checks = {
            check_id: {
                "id": check_id,
                "category": check_id.split(".", 1)[0],
                "status": "ok",
                "summary": "healthy",
                "details": {},
                "remediation": None,
                "durationMs": 0,
            }
            for check_id in REQUIRED_CHECKS
        }
        checks["auth.credentials"]["status"] = auth
        checks["config.load"]["status"] = config
        return {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "generatedAt": "now",
            "overallStatus": overall,
            "codexVersion": "test",
            "checks": checks,
        }

    if validate_execution(sample(), 0):
        raise SystemExit("self-test rejected a healthy report")
    if validate_execution(sample(overall="fail", auth="fail"), 1) != ["auth.credentials"]:
        raise SystemExit("self-test rejected the isolated-auth exception")
    negatives: list[tuple[object, int]] = [
        ([], 0),
        ({}, 0),
        ({**sample(), "schemaVersion": 2}, 0),
        (sample(overall="fail", config="fail"), 1),
        (sample(overall="ok", auth="fail"), 1),
        (sample(overall="fail"), 0),
        (sample(), 1),
        (sample(overall="fail", auth="fail"), 0),
        ({**sample(), "checks": {"auth.credentials": sample()["checks"]["auth.credentials"]}}, 1),
        ({**sample(), "generatedAt": None}, 0),
    ]
    for report, returncode in negatives:
        try:
            validate_execution(report, returncode)
        except ValueError:
            continue
        raise SystemExit("self-test accepted an invalid Doctor report")
    try:
        strict_loads('{"schemaVersion":1,"schemaVersion":1}')
    except ValueError:
        pass
    else:
        raise SystemExit("self-test accepted a duplicate JSON key")
    for constant in ("NaN", "Infinity", "-Infinity"):
        try:
            strict_loads(f'{{"value":{constant}}}')
        except ValueError:
            continue
        raise SystemExit("self-test accepted a nonstandard JSON constant")
    print(f"validated {len(negatives)} Codex Doctor negative cases")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    if parser.parse_args().self_test:
        self_test()
        return
    try:
        completed = subprocess.run(
            ["codex", "--strict-config", "doctor", "--json"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="")
        report = strict_loads(completed.stdout)
        external = validate_execution(report, completed.returncode)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        raise SystemExit(f"Codex Doctor validation failed:\n{exc}") from exc
    if external:
        print("validated Codex Doctor; external authentication is absent in this environment")
    else:
        print("validated Codex Doctor")


if __name__ == "__main__":
    main()
