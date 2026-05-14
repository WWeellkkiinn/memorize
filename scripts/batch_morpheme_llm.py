"""Batch morpheme splitting via local Qwen 3.6 27B.

Reads unsplit words from DB, queries model in batches, writes results to a
TSV review file. Does NOT touch the database — run apply_morpheme_review.py
after human review to merge accepted splits.

Usage:
  python scripts/batch_morpheme_llm.py [/path/to/words.db] [--batch-size N]

Output:
  morphemes_review.tsv  — one line per word: word TAB suggested_split
                          Edit/delete rows before applying.
                          Lines starting with # are comments (ignored).
"""
from __future__ import annotations
import sqlite3
import sys
import time
from pathlib import Path

import httpx

OLLAMA_URL = "http://10.12.210.20:13813"
MODEL = "qwen3.6-27b"
DEFAULT_BATCH = 30
OUTPUT_FILE = Path(__file__).parent.parent / "morphemes_review.tsv"

SYSTEM_PROMPT = """\
You are a conservative English morphology expert for vocabulary learners.

Your job: split words into Latin/Greek morphemes ONLY when the split is genuinely educational.

STRICT RULES:
1. The ROOT must be a real, recognizable Latin or Greek morpheme with a clear meaning (e.g. "labor" = work, "rupt" = break, "struct" = build). It must NOT be random leftover letters.
2. A prefix match alone is NOT enough. "abandon" starts with "ab-" but "andon" is meaningless — return null.
3. When in doubt, return null. It is better to show the full word than a misleading split.
4. Short Germanic words (craft, frost, glow, swap, grip) → always null.
5. Return ONLY: the split string OR the word null. No explanation. No extra text.

Format: morpheme:type joined by |
Types: prefix, root, bound (for suffixes), free (for compound nouns)

Good examples:
collaborate -> col:prefix|labor:root|ate:bound
deteriorate -> de:prefix|terio:root|ate:bound
inevitable -> in:prefix|evit:root|able:bound
inaugurate -> in:prefix|augur:root|ate:bound
thermometer -> thermo:root|meter:root
masterpiece -> master:free|piece:free
dispute -> dis:prefix|pute:root
vulnerable -> vulner:root|able:bound

Bad splits to AVOID (do NOT do these):
abandon -> null  (andon is not a real root)
account -> null  (count here is coincidental, not the Latin root)
commence -> null  (mence is not a teachable root)
address -> null  (dress is not the Latin root here)"""


def query_batch(words: list[str], client: httpx.Client) -> dict[str, str | None]:
    word_list = "\n".join(words)
    user_msg = f"""/think
For each word below output exactly one line: word -> split_or_null
No explanation. No blank lines between words.

{word_list}"""

    resp = client.post(
        f"{OLLAMA_URL}/v1/chat/completions",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "options": {"num_ctx": 65536, "temperature": 0},
        },
        timeout=300,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()

    results: dict[str, str | None] = {}
    for line in raw.splitlines():
        line = line.strip()
        if " -> " not in line:
            continue
        word, split = line.split(" -> ", 1)
        word = word.strip().lower()
        split = split.strip()
        results[word] = None if split.lower() == "null" else split
    return results


def main() -> None:
    args = sys.argv[1:]
    batch_size = DEFAULT_BATCH
    if "--batch-size" in args:
        idx = args.index("--batch-size")
        batch_size = int(args[idx + 1])
        args = [a for a in args if a not in ("--batch-size", args[idx + 1])]

    _default_db = Path(__file__).parent.parent.parent / "AppData/Local/Temp/words_server.db"
    import os
    _default_db = Path(os.environ.get("APPDATA", Path.home())) / "memorize" / "words.db"
    db_path = Path(args[0]) if args else _default_db

    conn = sqlite3.connect(str(db_path), timeout=60)
    words = [r[0] for r in conn.execute(
        "SELECT word FROM words WHERE morphemes IS NULL ORDER BY word"
    )]
    conn.close()

    print(f"Words to process : {len(words)}")
    print(f"Batch size       : {batch_size}")
    print(f"Output file      : {OUTPUT_FILE}")
    print()

    # Load already-processed words to allow resume
    done: set[str] = set()
    if OUTPUT_FILE.exists():
        for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "\t" not in line:
                continue
            done.add(line.split("\t")[0].strip().lower())

    remaining = [w for w in words if w.lower() not in done]
    print(f"Already done     : {len(done)}, remaining: {len(remaining)}")

    if not remaining:
        print("Nothing to do.")
        return

    batches = [remaining[i:i + batch_size] for i in range(0, len(remaining), batch_size)]
    total_batches = len(batches)

    with httpx.Client() as client:
        with OUTPUT_FILE.open("a", encoding="utf-8") as f:
            if not done:
                f.write("# word\tsuggested_split\n")
                f.write("# Review this file: delete bad rows, edit splits, then run apply_morpheme_review.py\n")

            for i, batch in enumerate(batches):
                t0 = time.time()
                print(f"[{i+1}/{total_batches}] Querying {len(batch)} words...", end=" ", flush=True)

                try:
                    results = query_batch(batch, client)
                except Exception as e:
                    print(f"ERROR: {e}")
                    continue

                wrote = 0
                for word in batch:
                    split = results.get(word.lower())
                    if split:
                        f.write(f"{word}\t{split}\n")
                        wrote += 1
                    else:
                        # Write null results too so resume works
                        f.write(f"{word}\tnull\n")

                elapsed = time.time() - t0
                print(f"got {wrote} splits in {elapsed:.0f}s")
                f.flush()

    # Summary
    splits = 0
    nulls = 0
    for line in OUTPUT_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        _, val = line.split("\t", 1)
        if val.strip().lower() == "null":
            nulls += 1
        else:
            splits += 1

    print(f"\nDone. Splits: {splits}, null: {nulls}")
    print(f"Review {OUTPUT_FILE} then run: python scripts/apply_morpheme_review.py")


if __name__ == "__main__":
    main()
