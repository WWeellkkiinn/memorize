"""Test script: query local Qwen 3.6 27B for morpheme splits.

Usage:
  python scripts/test_morpheme_llm.py
"""
import json
import httpx

OLLAMA_URL = "http://10.12.210.20:13813"
MODEL = "qwen3.6-27b"

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

TEST_WORDS = [
    # should split
    "abandon",
    "accommodate",
    "deteriorate",
    "collaborate",
    "fluctuate",
    "legitimate",
    "vulnerable",
    "inevitable",
    "inaugurate",
    # should NOT split
    "craft",
    "frost",
    "glow",
    "swap",
    "fetch",
]


def query_batch(words: list[str]) -> dict[str, str | None]:
    word_list = "\n".join(words)
    user_msg = f"""/think
For each word below output exactly one line: word -> split_or_null
No explanation. No blank lines between words.

{word_list}"""

    resp = httpx.post(
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

    results = {}
    for line in raw.splitlines():
        line = line.strip()
        if " -> " not in line:
            continue
        word, split = line.split(" -> ", 1)
        word = word.strip().lower()
        split = split.strip()
        results[word] = None if split.lower() == "null" else split
    return results


def main():
    print(f"Endpoint : {OLLAMA_URL}")
    print(f"Model    : {MODEL}")
    print(f"Words    : {len(TEST_WORDS)}\n")

    results = query_batch(TEST_WORDS)

    print(f"{'Word':<20} {'Result'}")
    print("-" * 50)
    for word in TEST_WORDS:
        result = results.get(word, "(not returned)")
        print(f"{word:<20} {result}")

    found = sum(1 for v in results.values() if v)
    print(f"\nReturned splits: {found}/{len(TEST_WORDS)}")


if __name__ == "__main__":
    main()
