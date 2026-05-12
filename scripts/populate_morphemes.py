"""Pre-compute morpheme splits using MorphoLex via the morphemes library.

Only stores results for words with 2+ morphemes (single-morpheme words get NULL).
Run once after import: python scripts/populate_morphemes.py
"""
import sqlite3
import sys
from pathlib import Path

from morphemes import Morphemes

DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "memorize" / "words.db"


def extract_parts(tree: list) -> list[dict]:
    parts = []
    for node in (tree or []):
        if not node or not isinstance(node, dict):
            continue
        if "text" in node:
            parts.append({"text": node["text"], "type": node.get("type", "root")})
        if "children" in node:
            parts.extend(extract_parts(node["children"]))
    return parts


def main():
    mrp = Morphemes()
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 60000")

    words = conn.execute("SELECT id, word FROM words").fetchall()
    updated = skipped = 0

    for row in words:
        r = mrp.parse(row["word"])
        if r["status"] != "FOUND_IN_DATABASE" or r["morpheme_count"] < 2:
            skipped += 1
            continue

        parts = extract_parts(r["tree"])
        # store as "un:prefix|believe:root|able:bound"
        value = "|".join(p["text"] + ":" + p["type"] for p in parts)
        conn.execute("UPDATE words SET morphemes=? WHERE id=?", (value, row["id"]))
        updated += 1

    conn.commit()
    conn.close()
    print(f"Done: {updated} updated, {skipped} skipped (single morpheme or not found)")


if __name__ == "__main__":
    main()
