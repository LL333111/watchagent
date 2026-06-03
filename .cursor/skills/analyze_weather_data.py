#!/usr/bin/env python3
"""Answer question-driven weather analysis queries from the WatchAgent database.

Run from repository root:
    python .cursor/skills/analyze_weather_data.py --question "Which city is warmest right now?"
    python .cursor/skills/analyze_weather_data.py --question "Has Vancouver been getting windier?" --limit 12
    python .cursor/skills/analyze_weather_data.py --city Toronto --question "Give me a summary."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow direct execution from the repository root as documented in the README.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.data_analysis import analyze_weather_question


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze WatchAgent weather data by answering a concrete question."
    )
    parser.add_argument(
        "--database-url",
        default="sqlite:///./data/watchagent.db",
        help="SQLAlchemy-style SQLite URL. Default: sqlite:///./data/watchagent.db",
    )
    parser.add_argument(
        "--question",
        default=None,
        help="Natural-language question about readings/events stored in the database.",
    )
    parser.add_argument(
        "--city",
        default=None,
        help="Optional city override for trend/summary questions.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="How many recent readings to consider for trend analysis. Default: 50.",
    )
    args = parser.parse_args()

    output = analyze_weather_question(
        args.database_url,
        args.question,
        city=args.city,
        limit=args.limit,
    )
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
