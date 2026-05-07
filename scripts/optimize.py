"""
Optimize FSRS parameters using your personal review history.

Usage:
    pip install torch pandas
    python scripts/optimize.py

Writes optimized parameters to %APPDATA%/memorize/fsrs_params.json.
Restart the app after running to apply the new parameters.

Requires at least 512 cross-day review records to produce meaningful results
(the optimizer falls back to defaults silently if the dataset is too small).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from memorize.config import DB_PATH, FSRS_PARAMS_PATH
from memorize.word_store import WordStore


def main() -> None:
    try:
        from fsrs import Optimizer
    except ImportError:
        print("ERROR: torch and pandas are required. Run: pip install torch pandas")
        sys.exit(1)

    store = WordStore(DB_PATH)
    review_logs = store.get_review_logs_for_optimizer()

    if not review_logs:
        print("No review logs found. Use the app first to build up review history.")
        sys.exit(0)

    print(f"Loaded {len(review_logs)} review log entries.")
    print("Optimizing FSRS parameters (this may take a minute)...")

    optimizer = Optimizer(review_logs)
    params = optimizer.compute_optimal_parameters()

    FSRS_PARAMS_PATH.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Done. Parameters saved to {FSRS_PARAMS_PATH}")
    print("Restart Memorize to apply the optimized parameters.")


if __name__ == "__main__":
    main()
