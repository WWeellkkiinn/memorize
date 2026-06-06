"""One-off: merge an exported user's library into this server's words.db as an
isolated, owned library. Run with the app container stopped.

Steps:
  1. Ensure words has owner_id + UNIQUE(owner_id, word) (FK-safe rebuild).
  2. Assign every existing (legacy/shared) word to the resident user (HIS_ID).
  3. Demote the resident user to a normal (non-admin) account.
  4. Create the imported user (preserving their argon2 hash) as admin.
  5. Import their words (owned by them), cards and review_logs, remapping word ids.

Usage: python3 migrate_merge_user.py <db_path> <export.json> <his_user_id>
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone

DB, EXPORT, HIS_ID = sys.argv[1], sys.argv[2], int(sys.argv[3])
data = json.load(open(EXPORT, encoding="utf-8"))

conn = sqlite3.connect(DB)
conn.isolation_level = None
conn.execute("PRAGMA foreign_keys = OFF")

# 1. schema: add owner_id + UNIQUE(owner_id, word), preserving ids -------------
cols = {r[1] for r in conn.execute("PRAGMA table_info(words)")}
if "owner_id" not in cols:
    conn.execute("BEGIN")
    conn.execute(
        "CREATE TABLE words_new ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " word TEXT NOT NULL,"
        " phonetic TEXT NOT NULL DEFAULT '',"
        " pos TEXT NOT NULL DEFAULT '',"
        " definition TEXT NOT NULL DEFAULT '',"
        " examples TEXT NOT NULL DEFAULT '[]',"
        " rank INTEGER NOT NULL DEFAULT 0,"
        " morphemes TEXT DEFAULT NULL,"
        " owner_id INTEGER,"
        " UNIQUE(owner_id, word))"
    )
    conn.execute(
        "INSERT INTO words_new(id, word, phonetic, pos, definition, examples, rank, morphemes, owner_id)"
        " SELECT id, word, phonetic, pos, definition, examples, rank, morphemes, NULL FROM words"
    )
    conn.execute("DROP TABLE words")
    conn.execute("ALTER TABLE words_new RENAME TO words")
    conn.execute("COMMIT")
    print("schema: owner_id added, uniqueness -> (owner_id, word)")
else:
    print("schema: owner_id already present, skipping rebuild")

conn.execute("BEGIN")
# 2. existing words -> resident user's library
n = conn.execute("UPDATE words SET owner_id=? WHERE owner_id IS NULL", (HIS_ID,)).rowcount
print(f"assigned {n} existing words to user {HIS_ID}")

# 3. demote resident user
conn.execute("UPDATE users SET is_admin=0 WHERE id=?", (HIS_ID,))

# 4. create imported user as admin (preserve hash)
u = data["user"]
email = u["email"].strip().lower()
exists = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
if exists:
    raise SystemExit(f"refuse: user {email} already exists (id={exists[0]})")
created = datetime.now(timezone.utc).isoformat()
cur = conn.execute(
    "INSERT INTO users(email, password_hash, display_name, is_admin, created_at)"
    " VALUES(?,?,?,1,?)",
    (email, u["password_hash"], u.get("display_name") or email.split("@")[0], created),
)
MINE = cur.lastrowid
print(f"created admin user {email} -> id {MINE}")

# 5. import words (owned by MINE), build old_word_id -> new_id map
wmap = {}
for w in data["words"]:
    cur = conn.execute(
        "INSERT INTO words(word, phonetic, pos, definition, examples, rank, morphemes, owner_id)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (w["word"], w["phonetic"], w["pos"], w["definition"], w["examples"],
         w["rank"], w["morphemes"], MINE),
    )
    wmap[w["id"]] = cur.lastrowid
print(f"imported {len(wmap)} words for user {MINE}")

# cards (remap word_id, set user_id=MINE)
for c in data["cards"]:
    conn.execute(
        "INSERT INTO cards(user_id, word_id, fsrs_card, due, stability, reps, introduced_date, last_seen_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (MINE, wmap[c["word_id"]], c["fsrs_card"], c["due"], c["stability"],
         c["reps"], c["introduced_date"], c["last_seen_at"]),
    )
print(f"imported {len(data['cards'])} cards")

# review_logs (remap word_id; card_id is the opaque FSRS card id, kept verbatim)
for l in data["logs"]:
    conn.execute(
        "INSERT INTO review_logs(user_id, word_id, card_id, rating, reviewed_at, stability, difficulty)"
        " VALUES(?,?,?,?,?,?,?)",
        (MINE, wmap[l["word_id"]], l["card_id"], l["rating"], l["reviewed_at"],
         l["stability"], l["difficulty"]),
    )
print(f"imported {len(data['logs'])} review_logs")

conn.execute("COMMIT")
conn.execute("PRAGMA foreign_keys = ON")
fk = conn.execute("PRAGMA foreign_key_check").fetchall()
print("foreign_key_check:", "OK" if not fk else fk)
conn.close()
print("DONE")
