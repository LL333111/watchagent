#!/usr/bin/env python3
"""Static final-submission readiness audit for WatchAgent."""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = (
    "README.md",
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
    "requirements.txt",
    "app/main.py",
    "app/routes.py",
    "app/event_detection.py",
    "tests/test_event_detection.py",
    "tests/test_api.py",
)
README_REQUIRED_PHRASES = (
    "System Overview",
    "Architecture",
    "Setup and Run",
    "API Reference",
    "Technology Choices",
    "Event Detection Design",
    "Cursor Setup",
    "Testing",
    "CI",
)
SECRET_PATTERNS = (
    re.compile(r"api[_-]?key\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"token\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"password\s*=\s*['\"][^'\"]+['\"]", re.IGNORECASE),
)
IGNORED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "data"}


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _source_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.relative_to(REPO_ROOT).parts):
            continue
        if path.suffix.lower() in {".py", ".md", ".mdc", ".yml", ".yaml", ".toml", ".txt"}:
            files.append(path)
    return files


def main() -> None:
    readme = _read("README.md")
    cursor_rules = sorted(path.name for path in (REPO_ROOT / ".cursor/rules").glob("*.mdc"))
    cursor_agents = sorted(path.name for path in (REPO_ROOT / ".cursor/agents").glob("*.md"))
    cursor_skills = sorted(path.name for path in (REPO_ROOT / ".cursor/skills").glob("*.py"))

    missing_files = [
        path for path in REQUIRED_FILES if not (REPO_ROOT / path).exists()
    ]
    missing_readme_sections = [
        phrase for phrase in README_REQUIRED_PHRASES if phrase not in readme
    ]
    suspicious_artifacts = [
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.rglob("*")
        if path.name in {"__pycache__", ".pytest_cache"}
    ]

    secret_hits: list[str] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                secret_hits.append(str(path.relative_to(REPO_ROOT)))
                break

    evidence = {
        "required_files_present": len(missing_files) == 0,
        "readme_required_sections_present": len(missing_readme_sections) == 0,
        "cursor_rule_count": len(cursor_rules),
        "cursor_agent_count": len(cursor_agents),
        "cursor_skill_count": len(cursor_skills),
        "docker_compose_mentions_healthcheck": "healthcheck" in _read("docker-compose.yml"),
        "dockerfile_uses_non_root_user": "USER watchagent" in _read("Dockerfile"),
        "ci_workflow_present": (REPO_ROOT / ".github/workflows/ci.yml").exists(),
    }
    output = {
        "ok": not (missing_files or missing_readme_sections or secret_hits),
        "evidence": evidence,
        "cursor_rules": cursor_rules,
        "cursor_agents": cursor_agents,
        "cursor_skills": cursor_skills,
        "missing_files": missing_files,
        "missing_readme_sections": missing_readme_sections,
        "secret_hits": sorted(set(secret_hits)),
        "suspicious_artifacts": suspicious_artifacts,
        "notes": [
            "This is a static audit; still run pytest and docker compose for runtime verification.",
            "Local data files under data/ are ignored because they are runtime persistence, not source.",
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
