#!/usr/bin/env python3
"""Audit README/code/test alignment for WatchAgent event detection."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _event_types_from_code() -> set[str]:
    source = _read("app/event_detection.py")
    return set(re.findall(r'event_type="([a-z_]+)"', source))


def _event_types_from_readme() -> set[str]:
    readme = _read("README.md")
    return set(re.findall(r"^\d+\.\s+`([a-z_]+)`", readme, flags=re.MULTILINE))


def _event_test_evidence(event_type: str) -> dict[str, bool]:
    tests = _read("tests/test_event_detection.py")
    return {
        "has_trigger_or_presence_assertion": f'"{event_type}" in _event_types(events)' in tests,
        "has_non_trigger_or_suppression_assertion": (
            f'"{event_type}" not in _event_types(events)' in tests
            or "events == []" in tests
        ),
    }


def main() -> None:
    code_events = _event_types_from_code()
    readme_events = _event_types_from_readme()
    test_evidence = {
        event_type: _event_test_evidence(event_type)
        for event_type in sorted(code_events)
    }

    missing_from_readme = sorted(code_events - readme_events)
    documented_but_not_implemented = sorted(readme_events - code_events)
    missing_trigger_tests = sorted(
        event_type
        for event_type, evidence in test_evidence.items()
        if not evidence["has_trigger_or_presence_assertion"]
    )

    output = {
        "ok": not (
            missing_from_readme
            or documented_but_not_implemented
            or missing_trigger_tests
        ),
        "code_event_count": len(code_events),
        "readme_event_count": len(readme_events),
        "code_events": sorted(code_events),
        "readme_events": sorted(readme_events),
        "missing_from_readme": missing_from_readme,
        "documented_but_not_implemented": documented_but_not_implemented,
        "missing_trigger_tests": missing_trigger_tests,
        "test_evidence": test_evidence,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
