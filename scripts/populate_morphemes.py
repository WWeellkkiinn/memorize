"""Pre-compute morpheme splits for the word DB.

Strategy: curated prefix/suffix whitelist only — no auto-discovery.
Only stores a split when a real affix is matched AND the remaining
root is >= MIN_ROOT characters. NULL = no split (shown as full word).

Run locally, then upload DB to server:
  python scripts/populate_morphemes.py /path/to/words.db [--preview]
"""
from __future__ import annotations
import os
import sqlite3
import sys
from pathlib import Path

# ── NLTK word set (lazy-loaded on first use) ──────────────────────────────────

_WORD_SET: set[str] | None = None


def _get_word_set() -> set[str]:
    global _WORD_SET
    if _WORD_SET is None:
        try:
            import nltk
            nltk.download("words", quiet=True)
            from nltk.corpus import words as _nltk_words
            _WORD_SET = set(w.lower() for w in _nltk_words.words())
        except Exception as e:
            sys.exit(f"ERROR: Could not load NLTK words corpus: {e}\n"
                     "Run: pip install nltk && python -c \"import nltk; nltk.download('words')\"")
    return _WORD_SET


# ── Curated affix lists (longest-first for greedy matching) ──────────────────

PREFIXES = sorted([
    "circum", "pseudo", "hyper", "hypo", "macro", "micro",
    "inter", "multi", "extra", "super", "under", "proto",
    "trans", "anti", "semi", "mono", "para", "post", "fore",
    "meta", "bene", "peri", "equi", "ambi", "over", "auto",
    "non", "mid", "mis", "mal", "out", "pre", "pro", "sub",
    "sur", "uni", "neo", "dis", "per", "com", "con",
    "ob", "bi", "ad", "ab", "re", "en", "em", "un", "ex",
    "il", "im", "in", "ir", "de",
], key=lambda x: -len(x))

SUFFIXES = sorted(dict.fromkeys([   # dict.fromkeys preserves order and deduplicates
    "fication", "isation", "ization", "ational", "ication",
    "iveness", "fulness", "ingness", "ousness",
    "atorial", "ological",
    "ation", "ative", "itude", "atory", "ician", "ition",
    "ology", "itive", "ution", "ical", "ness", "ment", "less",
    "ious", "sion", "tion", "ence", "eous", "ency", "ance",
    "ancy", "ship", "ator", "ward", "hood", "ible", "able",
    "ful", "ian", "ism", "ist", "ity", "ive", "ize", "ise",
    "ify", "ing", "ion", "ary", "ory", "ial", "ous", "ate",
    "ent", "ant", "age", "ure", "dom", "ish", "ess",
    "ery", "tic", "acy", "ee", "ly", "al", "ic", "or",
    "ty", "en", "cy",
]), key=lambda x: -len(x))

MIN_ROOT = 4

# Known bound roots that don't appear in NLTK but are teachable morphemes
BOUND_ROOTS = {
    "struct", "rupt", "duct", "dict", "port", "tract", "ject",
    "spect", "scribe", "script", "vert", "vers", "mit", "miss",
    "cede", "ceed", "cess", "pend", "pens", "fect", "fic",
    "cap", "cept", "ceive", "clude", "clus", "fer", "lat",
    "solve", "solut", "pos", "pon", "pel", "puls", "sent",
    "sequ", "sect", "sist", "tain", "ten", "val", "ven", "vent",
    "voc", "vok", "vis", "vid",
    # Greek roots
    "logue",    # monologue, prologue — Greek logos (word)
    "phor",     # metaphor — Greek pherein (carry)
    "nomy",     # autonomy — Greek nomos (law)
    "tonous",   # monotonous — Greek tonos (tone)
    "biotic",   # antibiotic — Greek bios (life)
    # Latin roots (additional)
    "stant",    # constant, substantial — Latin stare (stand)
    "stitut",   # institution — Latin statuere (set up) — truncated form
    "stitute",  # substitute, constitute — full form (both needed: different endings)
    "flict",    # conflict, inflict — Latin fligere (strike)
    # Extended for IELTS words blocked by NLTK gap
    "pret",     # interpret — Latin pretium (worth)
    "ference",  # circumference — Latin ferre (to carry)
    "ficial",   # superficial — Latin facies (surface)
    "cend",     # transcend — Latin scandere (to climb)
    "gress",    # transgress — Latin gradi (to step)
    "cript",    # transcript — variant of script
    "cosm",     # microcosm — Greek kosmos (world)
    "rogate",   # interrogate — Latin rogare (to ask)
    "mitt",     # intermittent — Latin mittere (to send)
    "vagant",   # extravagant — Latin vagari (to wander)
}

# Manual splits for words with unusual morphology that rules can't handle cleanly
WORD_ALLOWLIST: dict[str, str] = {
    "multitude":    "multi:prefix|tude:root",       # multi (many) + -tude (state)
    "superfluous":  "super:prefix|fluous:root",     # super + fluere (to flow)
    "supersede":    "super:prefix|sede:root",       # super + sedere (to sit/yield)
    "superstition": "super:prefix|stition:root",    # super + stare (to stand)
    "transition":   "trans:prefix|ition:root",      # trans (across) + going
}

# Words whose surface morphology looks splittable but is etymologically
# wrong or would actively mislead learners — never split these.
WORD_DENYLIST = {
    "transparent",   # parent ≠ Latin paren(s)
    "intense",       # in- here = "into", not negation
    "refund",        # re+fund misleads into "fund again"
    "average",       # aver+age has no learning value
    "redundant",     # dund is not a teachable root
    "setting",       # sett is a badger burrow, not the root
    "nationalism",   # national should not be marked as root
    "nationality",   # same issue
    # ad- false positives (here/dress/just are coincidental)
    "adhere",        # ad+here misleads — not "to here"
    "address",       # ad+dress misleads — not "to dress"
    "adjust",        # ad+just misleads — not "to just"
    # ab- false positives
    "abridge",       # ab+ridge — ridge is coincidental
    "abrasion",      # ab+rasion — rasion not teachable
    # re- false positives
    "resort",        # re+sort misleads — not "sort again"
    "retail",        # re+tail misleads — not "tail again"
    "revenue",       # re+venue misleads — not "venue again"
    "revenge",       # re+venge — venge not teachable here
    "reptile",       # re+ptile — nonsense
    # other false positives
    "desert",        # de+sert — sert here is coincidental
    "missile",       # mis+sile — sile not a root
}


def _root_valid(root: str) -> bool:
    ws = _get_word_set()
    return (
        root in ws
        or root in BOUND_ROOTS
        or (root + "e") in ws
        or (root + "er") in ws
    )


def segment(word: str) -> str | None:
    original = word.lower()

    if original in WORD_DENYLIST:
        return None
    if original in WORD_ALLOWLIST:
        return WORD_ALLOWLIST[original]

    # MIN_ROOT=4 is intentionally uniform across prefix lengths.
    # Short prefixes (re/de/in) rely on WORD_DENYLIST to block false positives
    # rather than a higher threshold, which would break valid splits like re+fine.
    prefix = ""
    remaining = original
    for p in PREFIXES:
        if original.startswith(p) and len(original) - len(p) >= MIN_ROOT:
            prefix = p
            remaining = original[len(p):]
            break

    suffix = ""
    root = remaining
    for s in SUFFIXES:
        if remaining.endswith(s) and len(remaining) - len(s) >= MIN_ROOT:
            candidate = remaining[: -len(s)]
            if _root_valid(candidate):
                suffix = s
                root = candidate
                break

    if not _root_valid(root):
        # Fallback: if a prefix was matched but root is invalid, try suffix-only
        # on the original word. Handles cases where greedy longest prefix masks a
        # valid suffix-only split.
        # _root_valid only checks +e/+er variants; +ed/+ing/+s are intentionally
        # excluded to avoid false positives from over-broad NLTK matches.
        if prefix:
            for s in SUFFIXES:
                if original.endswith(s) and len(original) - len(s) >= MIN_ROOT:
                    cand = original[: -len(s)]
                    if _root_valid(cand):
                        return f"{cand}:root|{s}:bound"
        return None

    if not prefix and not suffix:
        return None

    parts = []
    if prefix:
        parts.append(f"{prefix}:prefix")
    parts.append(f"{root}:root")
    if suffix:
        parts.append(f"{suffix}:bound")
    return "|".join(parts)


def main() -> None:
    args = sys.argv[1:]
    preview = "--preview" in args
    args = [a for a in args if not a.startswith("--")]

    _default_db = Path(os.environ.get("APPDATA") or Path.home()) / "memorize" / "words.db"
    db_path = Path(args[0]) if args else _default_db

    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        words_rows = conn.execute("SELECT id, word FROM words").fetchall()

        print(f"Prefixes: {len(PREFIXES)}, Suffixes: {len(SUFFIXES)}")

        if preview:
            import random
            if not words_rows:
                print("No words in DB.")
                return

            # Compute once, reuse for both display and stats
            results = {r["word"]: segment(r["word"]) for r in words_rows}
            words = list(results)

            samples = [
                "unbelievable", "reconstruction", "independence", "misunderstand",
                "uncomfortable", "prehistoric", "international", "abbreviation",
                "abnormal", "accommodation", "unemployment", "disappear",
                "impossible", "advertisement", "nationalism", "distinguish",
                "applaud", "suffer", "mortal", "construct", "disorder",
                "amount", "rescue", "average", "schedule", "ancestor",
                "represent", "redundant", "transparent", "benevolent",
            ]
            word_set = set(results)
            print("\n=== Target samples ===")
            for w in samples:
                result = results[w] if w in word_set else segment(w)
                tag = "(not in list)" if w not in word_set else ""
                print(f"  {w:30s} -> {result or '(no split)'} {tag}")

            print("\n=== Random 30 from list ===")
            for w in sorted(random.sample(words, min(30, len(words)))):
                if results[w]:
                    print(f"  {w:30s} -> {results[w]}")

            multi = sum(1 for v in results.values() if v)
            total = len(words)
            pct = f"{multi/total*100:.1f}%" if total else "N/A"
            print(f"\nTotal: {total}, Would split: {multi} ({pct})")
            return

        updated = skipped = 0
        for row in words_rows:
            result = segment(row["word"])
            conn.execute("UPDATE words SET morphemes=? WHERE id=?", (result, row["id"]))
            if result:
                updated += 1
            else:
                skipped += 1

        conn.commit()
        print(f"Done: {updated} updated, {skipped} no split (NULL)")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
