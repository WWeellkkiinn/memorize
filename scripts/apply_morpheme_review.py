"""Apply reviewed morpheme splits from TSV file into the words DB.

Usage:
  python scripts/apply_morpheme_review.py [/path/to/words.db] [--review /path/to/morphemes_review.tsv]

Reads morphemes_review.tsv (after human review), writes accepted splits to DB.
Lines with "null" or starting with "#" are skipped.
"""
from __future__ import annotations
import sqlite3
import sys
from pathlib import Path

DEFAULT_REVIEW = Path(__file__).parent.parent / "morphemes_review.tsv"


def main() -> None:
    args = sys.argv[1:]

    review_path = DEFAULT_REVIEW
    if "--review" in args:
        idx = args.index("--review")
        review_path = Path(args[idx + 1])
        args = [a for a in args if a not in ("--review", args[idx + 1])]

    import os
    _default_db = Path(os.environ.get("APPDATA", Path.home())) / "memorize" / "words.db"
    db_path = Path(args[0]) if args else _default_db

    if not review_path.exists():
        sys.exit(f"Review file not found: {review_path}")

    # Parse review file
    splits: dict[str, str] = {}
    for line in review_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "\t" not in line:
            continue
        word, split = line.split("\t", 1)
        word = word.strip().lower()
        split = split.strip()
        if split.lower() != "null" and split:
            splits[word] = split

    print(f"Accepted splits in review file: {len(splits)}")

    conn = sqlite3.connect(str(db_path), timeout=60)
    updated = 0
    not_found = 0
    for word, split in splits.items():
        rows = conn.execute("UPDATE words SET morphemes=? WHERE lower(word)=? AND morphemes IS NULL",
                            (split, word)).rowcount
        if rows:
            updated += 1
        else:
            not_found += 1

    conn.commit()
    conn.close()

    print(f"Updated : {updated}")
    if not_found:
        print(f"Skipped : {not_found} (word not found or already has morphemes)")


if __name__ == "__main__":
    main()
