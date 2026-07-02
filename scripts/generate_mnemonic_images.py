"""MVP test: generate chiikawa-style mnemonic images for a handful of words,
via an OpenAI-compatible image-generation API.

Setup: set IMAGE_API_KEY (required). IMAGE_API_BASE / IMAGE_API_MODEL have
defaults matching the currently configured proxy.

Run (defaults to the 10 MVP test words):
  IMAGE_API_KEY=sk-... python scripts/generate_mnemonic_images.py [/path/to/words.db]

Options:
  --words w1,w2,...   generate for these words instead of the MVP list
  --words-file path   read words from a file (comma or newline separated)
  --owner-id N        scope word lookup to this owner_id (default: legacy/shared, NULL)
  --force             regenerate even if mnemonic_image is already set
"""
from __future__ import annotations
import base64
import json
import os
import sqlite3
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent
IMAGE_DIR = REPO_DIR / "web" / "static" / "mnemonics"

API_BASE = os.environ.get("IMAGE_API_BASE", "https://gpt.welkin.best/v1")
API_KEY = os.environ.get("IMAGE_API_KEY")
API_MODEL = os.environ.get("IMAGE_API_MODEL", "gpt-image-2")

MVP_WORDS = [
    "abandon", "forehead", "applaud", "deceive", "stare",
    "glimpse", "swallow", "bind", "drag", "chase",
]

STYLE_PREFIX = (
    "Chiikawa-style kawaii illustration. Soft pastel pink background, "
    "simple thick black hand-drawn outlines, small round chubby mascot "
    "character(s) with tiny round eyes, small smiling mouth, pink blush "
    "marks on cheeks, minimalist flat shading, wholesome and gentle mood. "
    "No text, no watermark, no signature."
)


def build_prompt(word: str, definition: str) -> str:
    return (
        f"{STYLE_PREFIX} The scene acts out, in a literal and memorable way, "
        f'the meaning of the English word "{word}" ({definition}), so that '
        f"seeing the picture helps a learner recall the word's meaning "
        f"through visual association."
    )


def generate_image(prompt: str) -> bytes:
    req = urllib.request.Request(
        f"{API_BASE}/images/generations",
        data=json.dumps({
            "model": API_MODEL,
            "prompt": prompt,
            "n": 1,
            "size": "1024x768",
        }).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    return base64.b64decode(body["data"][0]["b64_json"])


def main() -> None:
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    words_arg = None
    if "--words" in args:
        i = args.index("--words")
        words_arg = [w.strip().lower() for w in args[i + 1].split(",")]
        del args[i:i + 2]
    if "--words-file" in args:
        i = args.index("--words-file")
        text = Path(args[i + 1]).read_text(encoding="utf-8")
        words_arg = [w.strip().lower() for w in text.replace("\n", ",").split(",") if w.strip()]
        del args[i:i + 2]

    owner_id = None
    if "--owner-id" in args:
        i = args.index("--owner-id")
        owner_id = int(args[i + 1])
        del args[i:i + 2]

    if not API_KEY:
        sys.exit("ERROR: set IMAGE_API_KEY env var")

    default_db = Path(os.environ.get("APPDATA") or Path.home()) / "memorize" / "words.db"
    db_path = Path(args[0]) if args else default_db
    target_words = words_arg or MVP_WORDS

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        skipped = failed = 0
        todo = []  # rows to actually generate for
        for word in target_words:
            row = conn.execute(
                "SELECT id, word, definition, mnemonic_image FROM words WHERE word=? AND owner_id IS ? LIMIT 1",
                (word, owner_id),
            ).fetchone()
            if not row:
                print(f"  {word:15s} -> SKIP (not found in DB)")
                skipped += 1
                continue
            if row["mnemonic_image"] and not force:
                print(f"  {word:15s} -> SKIP (already has image, use --force to redo)")
                skipped += 1
                continue
            todo.append(row)

        done = 0
        with ThreadPoolExecutor(max_workers=min(len(todo), 3) or 1) as pool:
            futures = {
                pool.submit(generate_image, build_prompt(row["word"], row["definition"])): row
                for row in todo
            }
            for fut in as_completed(futures):
                row = futures[fut]
                word = row["word"]
                try:
                    png_bytes = fut.result()
                except Exception as e:
                    print(f"  {word:15s} -> FAILED ({e})")
                    failed += 1
                    continue

                rel_path = f"mnemonics/{row['id']}.png"
                (IMAGE_DIR / f"{row['id']}.png").write_bytes(png_bytes)
                conn.execute("UPDATE words SET mnemonic_image=? WHERE id=?", (rel_path, row["id"]))
                conn.commit()
                print(f"  {word:15s} -> OK ({rel_path})")
                done += 1

        print(f"\nDone: {done} generated, {skipped} skipped, {failed} failed")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
