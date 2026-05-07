"""One-time import script: match user word list against kajweb/dict CET6 JSON.

Usage:
    python scripts/import_words.py path/to/words.txt

The CET6 JSON file must exist at data/cet6.json (download from kajweb/dict on GitHub).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a script from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from memorize.config import DB_PATH
from memorize.word_store import WordStore


_DATA_DIR = Path(__file__).parent.parent / "data"
_CET6_JSON = _DATA_DIR / "cet6.json"


def _build_index(cet6_path: Path) -> dict[str, dict]:
    """Build a lowercase headWord → entry dict from kajweb/dict CET6 JSON."""
    raw = json.loads(cet6_path.read_text(encoding="utf-8"))
    # kajweb/dict structure: list of entries, each has "headWord", "content" with nested data
    index: dict[str, dict] = {}

    entries = raw if isinstance(raw, list) else raw.get("words", [])
    for entry in entries:
        # Support both flat and nested kajweb/dict formats
        word = (entry.get("headWord") or entry.get("word") or "").strip().lower()
        if not word:
            continue
        index[word] = entry
    return index


def _extract(entry: dict) -> dict:
    """Extract fields from a kajweb/dict entry.

    kajweb/dict nested structure:
      entry["content"]["word"]["content"] → has usphone, trans, sentence
      entry["content"]["word"]["content"]["sentence"]["sentences"] → list of examples

    Falls back to flat entry if nested keys are absent.
    """
    # Try the documented nested path first
    content_outer = entry.get("content") or {}
    word_obj = content_outer.get("word") or {}
    word_data = word_obj.get("content") or word_obj or entry

    phonetic = word_data.get("usphone") or word_data.get("ukphone") or ""

    trans_list = word_data.get("trans") or []
    pos = trans_list[0].get("pos", "") if trans_list else ""
    definition = "；".join(
        t.get("tranCn", "") for t in trans_list if t.get("tranCn")
    )

    # Sentence field may be an object {"sentences": [...]} or a list directly
    sentence_raw = word_data.get("sentence") or []
    if isinstance(sentence_raw, dict):
        sentence_list = sentence_raw.get("sentences") or []
    else:
        sentence_list = sentence_raw  # already a list

    examples = [
        {"en": s.get("sContent", ""), "zh": s.get("sCn", "")}
        for s in sentence_list[:2]
        if s.get("sContent")
    ]

    return {
        "phonetic": phonetic,
        "pos": pos,
        "definition": definition,
        "examples": examples,
    }


def run(words_txt: Path) -> None:
    if not _CET6_JSON.exists():
        print(f"ERROR: {_CET6_JSON} not found.")
        print("Download CET6 JSON from https://github.com/kajweb/dict and place it at data/cet6.json")
        sys.exit(1)

    if not words_txt.exists():
        print(f"ERROR: {words_txt} not found.")
        sys.exit(1)

    print(f"Loading CET6 index from {_CET6_JSON} ...")
    index = _build_index(_CET6_JSON)
    print(f"  {len(index)} entries indexed.")

    user_words = [
        line.strip().lower()
        for line in words_txt.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    user_words = list(dict.fromkeys(user_words))  # deduplicate, preserve order
    print(f"User word list: {len(user_words)} unique words.")

    store = WordStore(DB_PATH)
    matched = skipped = new_inserted = 0

    for word in user_words:
        entry = index.get(word)
        if entry:
            data = _extract(entry)
            matched += 1
        else:
            data = {"phonetic": "", "pos": "", "definition": "", "examples": []}

        word_id = store.insert_word(
            word=word,
            phonetic=data["phonetic"],
            pos=data["pos"],
            definition=data["definition"],
            examples=data["examples"],
        )
        if word_id is not None:
            store.init_card(word_id)
            new_inserted += 1
        else:
            skipped += 1

    print(
        f"\nDone. Total={len(user_words)}  "
        f"Matched={matched}  Unmatched={len(user_words)-matched}  "
        f"NewInserted={new_inserted}  AlreadyExisted={skipped}"
    )
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/import_words.py path/to/words.txt")
        sys.exit(1)
    run(Path(sys.argv[1]))
