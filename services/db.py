import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("SCHOLAR_DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "scholar.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        expires_at REAL NOT NULL,
        created_at REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS papers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id TEXT DEFAULT 'default',
        title TEXT NOT NULL,
        title_zh TEXT DEFAULT '',
        authors TEXT DEFAULT '',
        source TEXT DEFAULT '',
        lang TEXT NOT NULL,
        pdf_filename TEXT DEFAULT '',
        paragraphs_json TEXT NOT NULL,
        notes TEXT DEFAULT '',
        is_sample INTEGER DEFAULT 0,
        created_at REAL NOT NULL
    )
    """)
    _ensure_column(conn, "papers", "owner_id", "TEXT DEFAULT 'default'")
    conn.execute("UPDATE papers SET owner_id = 'sample' WHERE is_sample = 1")
    conn.execute("UPDATE papers SET owner_id = 'default' WHERE is_sample = 0 AND owner_id = 'sample'")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS vocab (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id TEXT DEFAULT 'default',
        word TEXT NOT NULL,
        lemma TEXT NOT NULL,
        lang TEXT NOT NULL,
        stressed_or_ipa TEXT DEFAULT '',
        pos_summary TEXT DEFAULT '',
        meaning_zh TEXT NOT NULL,
        bridge_meaning TEXT DEFAULT '',
        grammar_note TEXT DEFAULT '',
        context_sentence TEXT DEFAULT '',
        context_zh TEXT DEFAULT '',
        paper_id INTEGER,
        paper_title TEXT DEFAULT '',
        repetitions INTEGER DEFAULT 0,
        easiness REAL DEFAULT 2.5,
        interval_days REAL DEFAULT 0,
        next_review REAL DEFAULT 0,
        last_reviewed REAL DEFAULT 0,
        created_at REAL NOT NULL
    )
    """)
    _ensure_column(conn, "vocab", "owner_id", "TEXT DEFAULT 'default'")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_settings (
        owner_id TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (owner_id, key)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS paper_user_notes (
        owner_id TEXT NOT NULL,
        paper_id INTEGER NOT NULL,
        notes TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY (owner_id, paper_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS translation_cache (
        cache_key TEXT PRIMARY KEY,
        src_lang TEXT NOT NULL,
        tgt_lang TEXT NOT NULL,
        translated_text TEXT NOT NULL,
        engine TEXT DEFAULT 'gtx',
        created_at REAL NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stress_cache (
        word_lower TEXT PRIMARY KEY,
        stressed_word TEXT NOT NULL,
        syllables TEXT DEFAULT '',
        updated_at REAL NOT NULL
    )
    """)

    conn.commit()
    conn.close()


# ==================== AUTHENTICATION & MULTI-USER ====================

def _hash_password(password: str, salt_hex: Optional[str] = None) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, salt_hex, hash_hex = stored_hash.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        candidate = _hash_password(password, salt_hex)
        return hmac.compare_digest(candidate, stored_hash)
    except Exception:
        return False


def create_session(user_id: int, days: int = 30) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now + days * 86400.0, now),
    )
    conn.commit()
    conn.close()
    return token


def register_user(username: str, password: str, display_name: str = "", guest_owner_id: str = "") -> Dict[str, Any]:
    uname = username.strip().lower()
    if len(uname) < 3 or len(uname) > 50 or not re.match(r"^[a-z0-9_.@-]+$", uname):
        raise ValueError("账号请使用 3~50 位字母、数字、下划线或邮箱格式")
    if len(password) < 6:
        raise ValueError("密码长度至少为 6 位")

    dname = display_name.strip() or uname.split("@")[0]
    pw_hash = _hash_password(password)
    now = time.time()

    conn = get_conn()
    exists = conn.execute("SELECT id FROM users WHERE username = ?", (uname,)).fetchone()
    if exists:
        conn.close()
        raise ValueError("该账号已被注册，请直接登录或更换用户名")

    cur = conn.execute(
        "INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (uname, dname, pw_hash, now),
    )
    uid = int(cur.lastrowid)
    conn.commit()
    conn.close()

    new_owner = f"user_{uid}"
    if guest_owner_id and guest_owner_id.startswith("guest_"):
        migrate_guest_to_user(guest_owner_id, new_owner)

    token = create_session(uid)
    return {
        "token": token,
        "user": {"id": uid, "username": uname, "display_name": dname, "owner_id": new_owner},
    }


def login_user(username: str, password: str, guest_owner_id: str = "") -> Dict[str, Any]:
    uname = username.strip().lower()
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (uname,)).fetchone()
    conn.close()
    if not row or not _verify_password(password, row["password_hash"]):
        raise ValueError("账号或密码不正确")

    uid = int(row["id"])
    user_owner = f"user_{uid}"
    if guest_owner_id and guest_owner_id.startswith("guest_"):
        migrate_guest_to_user(guest_owner_id, user_owner)

    token = create_session(uid)
    return {
        "token": token,
        "user": {
            "id": uid,
            "username": row["username"],
            "display_name": row["display_name"],
            "owner_id": user_owner,
        },
    }


def get_user_by_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        """
        SELECT u.id, u.username, u.display_name
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ? AND s.expires_at > ?
        """,
        (token, now),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "display_name": row["display_name"],
        "owner_id": f"user_{row['id']}",
    }


def logout_token(token: str) -> None:
    if not token:
        return
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def migrate_guest_to_user(guest_owner: str, user_owner: str) -> None:
    """Seamlessly transfer any papers/vocab/notes created during guest trial into user's permanent account."""
    conn = get_conn()
    conn.execute("UPDATE papers SET owner_id = ? WHERE owner_id = ? AND is_sample = 0", (user_owner, guest_owner))
    # Merge non-duplicate vocab items from guest into user
    guest_vocab = conn.execute("SELECT * FROM vocab WHERE owner_id = ?", (guest_owner,)).fetchall()
    for gv in guest_vocab:
        dup = conn.execute(
            "SELECT id FROM vocab WHERE owner_id = ? AND LOWER(lemma) = LOWER(?) AND lang = ?",
            (user_owner, gv["lemma"], gv["lang"]),
        ).fetchone()
        if not dup:
            conn.execute("UPDATE vocab SET owner_id = ? WHERE id = ?", (user_owner, gv["id"]))
    # Merge notes & settings if user doesn't have them yet
    conn.execute(
        "INSERT OR IGNORE INTO paper_user_notes (owner_id, paper_id, notes, updated_at) "
        "SELECT ?, paper_id, notes, updated_at FROM paper_user_notes WHERE owner_id = ?",
        (user_owner, guest_owner),
    )
    conn.execute(
        "INSERT OR IGNORE INTO user_settings (owner_id, key, value) "
        "SELECT ?, key, value FROM user_settings WHERE owner_id = ?",
        (user_owner, guest_owner),
    )
    conn.commit()
    conn.close()


def get_owner_stats(owner_id: str) -> Dict[str, Any]:
    conn = get_conn()
    paper_cnt = conn.execute(
        "SELECT COUNT(*) AS c FROM papers WHERE owner_id = ? AND is_sample = 0", (owner_id,)
    ).fetchone()["c"]
    ru_vocab = conn.execute(
        "SELECT COUNT(*) AS c FROM vocab WHERE owner_id = ? AND lang = 'ru'", (owner_id,)
    ).fetchone()["c"]
    en_vocab = conn.execute(
        "SELECT COUNT(*) AS c FROM vocab WHERE owner_id = ? AND lang = 'en'", (owner_id,)
    ).fetchone()["c"]
    mastered = conn.execute(
        "SELECT COUNT(*) AS c FROM vocab WHERE owner_id = ? AND repetitions >= 3", (owner_id,)
    ).fetchone()["c"]
    conn.close()
    return {
        "custom_papers": int(paper_cnt),
        "ru_vocab": int(ru_vocab),
        "en_vocab": int(en_vocab),
        "total_vocab": int(ru_vocab + en_vocab),
        "mastered_vocab": int(mastered),
    }


# ==================== PER-USER SETTINGS ====================

DEFAULT_SETTINGS: Dict[str, Any] = {
    "llm_enabled": False,
    "llm_provider": "deepseek",
    "llm_base_url": "https://api.deepseek.com/v1",
    "llm_api_key": "",
    "llm_model": "deepseek-chat",
    "ru_voice": "ru-RU-SvetlanaNeural",
    "en_voice": "en-US-AriaNeural",
}


def mask_api_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****" if key else ""
    return f"{key[:4]}••••••••{key[-4:]}"


def get_settings(owner_id: str = "default", mask_secret: bool = False) -> Dict[str, Any]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT key, value FROM user_settings WHERE owner_id = ?", (owner_id,)
    ).fetchall()
    conn.close()
    result = dict(DEFAULT_SETTINGS)
    for row in rows:
        try:
            result[row["key"]] = json.loads(row["value"])
        except Exception:
            result[row["key"]] = row["value"]

    raw_key = str(result.get("llm_api_key") or "")
    result["has_api_key"] = bool(raw_key)
    if mask_secret and raw_key:
        result["llm_api_key"] = mask_api_key(raw_key)
    return result


def save_settings(updates: Dict[str, Any], owner_id: str = "default") -> Dict[str, Any]:
    current = get_settings(owner_id=owner_id, mask_secret=False)
    conn = get_conn()
    for k, v in updates.items():
        if k not in DEFAULT_SETTINGS:
            continue
        # If frontend submits masked placeholder back unchanged, keep existing stored secret!
        if k == "llm_api_key" and isinstance(v, str) and "••••" in v:
            v = current.get("llm_api_key", "")
        conn.execute(
            "INSERT OR REPLACE INTO user_settings (owner_id, key, value) VALUES (?, ?, ?)",
            (owner_id, k, json.dumps(v, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()
    return get_settings(owner_id=owner_id, mask_secret=True)


# ==================== SCOPED PAPERS ====================

def list_papers(owner_id: str = "default") -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, owner_id, title, title_zh, authors, source, lang, pdf_filename, is_sample, created_at, paragraphs_json "
        "FROM papers WHERE is_sample = 1 OR owner_id = ? "
        "ORDER BY is_sample ASC, CASE WHEN is_sample = 1 THEN id ELSE -id END ASC",
        (owner_id,),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        paras = json.loads(r["paragraphs_json"] or "[]")
        translated_count = sum(1 for p in paras if (p.get("zh_text") or "").strip())
        out.append({
            "id": r["id"],
            "title": r["title"],
            "title_zh": r["title_zh"],
            "authors": r["authors"],
            "source": r["source"],
            "lang": r["lang"],
            "pdf_filename": r["pdf_filename"],
            "is_sample": bool(r["is_sample"]),
            "can_delete": not bool(r["is_sample"]) and r["owner_id"] == owner_id,
            "created_at": r["created_at"],
            "paragraph_count": len(paras),
            "translated_count": translated_count,
        })
    return out


def get_paper(paper_id: int, owner_id: str = "default") -> Optional[Dict[str, Any]]:
    conn = get_conn()
    r = conn.execute(
        "SELECT * FROM papers WHERE id = ? AND (is_sample = 1 OR owner_id = ?)",
        (paper_id, owner_id),
    ).fetchone()
    if not r:
        conn.close()
        return None

    # Per-user notes override so every user has private notes even on shared sample papers!
    note_row = conn.execute(
        "SELECT notes FROM paper_user_notes WHERE owner_id = ? AND paper_id = ?",
        (owner_id, paper_id),
    ).fetchone()
    conn.close()

    notes_val = note_row["notes"] if note_row is not None else (r["notes"] or "")
    return {
        "id": r["id"],
        "title": r["title"],
        "title_zh": r["title_zh"],
        "authors": r["authors"],
        "source": r["source"],
        "lang": r["lang"],
        "pdf_filename": r["pdf_filename"],
        "paragraphs": json.loads(r["paragraphs_json"] or "[]"),
        "notes": notes_val,
        "is_sample": bool(r["is_sample"]),
        "can_delete": not bool(r["is_sample"]) and r["owner_id"] == owner_id,
        "created_at": r["created_at"],
    }


def create_paper(
    title: str,
    lang: str,
    paragraphs: List[Dict[str, Any]],
    owner_id: str = "sample",
    title_zh: str = "",
    authors: str = "",
    source: str = "",
    pdf_filename: str = "",
    notes: str = "",
    is_sample: bool = False,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO papers (owner_id, title, title_zh, authors, source, lang, pdf_filename, paragraphs_json, notes, is_sample, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "sample" if is_sample else owner_id,
            title,
            title_zh,
            authors,
            source,
            lang,
            pdf_filename,
            json.dumps(paragraphs, ensure_ascii=False),
            notes,
            1 if is_sample else 0,
            time.time(),
        ),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return int(pid)


def update_paper_paragraphs(paper_id: int, paragraphs: List[Dict[str, Any]], title_zh: Optional[str] = None) -> None:
    conn = get_conn()
    if title_zh is not None:
        conn.execute(
            "UPDATE papers SET paragraphs_json = ?, title_zh = ? WHERE id = ?",
            (json.dumps(paragraphs, ensure_ascii=False), title_zh, paper_id),
        )
    else:
        conn.execute(
            "UPDATE papers SET paragraphs_json = ? WHERE id = ?",
            (json.dumps(paragraphs, ensure_ascii=False), paper_id),
        )
    conn.commit()
    conn.close()


def update_paper_notes(paper_id: int, notes: str, owner_id: str = "default") -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO paper_user_notes (owner_id, paper_id, notes, updated_at) VALUES (?, ?, ?, ?)",
        (owner_id, paper_id, notes, time.time()),
    )
    conn.commit()
    conn.close()


def delete_paper(paper_id: int, owner_id: str = "default") -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT pdf_filename, is_sample FROM papers WHERE id = ? AND owner_id = ?",
        (paper_id, owner_id),
    ).fetchone()
    if not row or row["is_sample"]:
        conn.close()
        return False
    cur = conn.execute("DELETE FROM papers WHERE id = ? AND owner_id = ?", (paper_id, owner_id))
    conn.execute("DELETE FROM paper_user_notes WHERE paper_id = ? AND owner_id = ?", (paper_id, owner_id))
    conn.commit()
    conn.close()
    if row["pdf_filename"]:
        pdf_path = DATA_DIR / "uploads" / Path(row["pdf_filename"]).name
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except Exception:
                pass
    return cur.rowcount > 0


# ==================== SCOPED VOCABULARY & SM-2 ====================

def count_owner_vocab(owner_id: str) -> int:
    conn = get_conn()
    c = conn.execute("SELECT COUNT(*) AS c FROM vocab WHERE owner_id = ?", (owner_id,)).fetchone()["c"]
    conn.close()
    return int(c)


def list_vocab(owner_id: str = "default", lang: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_conn()
    sql = "SELECT * FROM vocab WHERE owner_id = ?"
    params: List[Any] = [owner_id]
    if lang and lang in ("ru", "en"):
        sql += " AND lang = ?"
        params.append(lang)
    if search:
        q = f"%{search.strip()}%"
        sql += " AND (word LIKE ? OR lemma LIKE ? OR meaning_zh LIKE ? OR bridge_meaning LIKE ?)"
        params.extend([q, q, q, q])
    sql += " ORDER BY id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_or_update_vocab(entry: Dict[str, Any], owner_id: str = "default") -> Dict[str, Any]:
    conn = get_conn()
    lemma = (entry.get("lemma") or entry.get("word") or "").strip()
    lang = entry.get("lang", "en")
    existing = conn.execute(
        "SELECT * FROM vocab WHERE owner_id = ? AND LOWER(lemma) = LOWER(?) AND lang = ?",
        (owner_id, lemma, lang),
    ).fetchone()
    now = time.time()
    if existing:
        vid = existing["id"]
        conn.execute(
            """
            UPDATE vocab SET
                word = ?, stressed_or_ipa = ?, pos_summary = ?,
                meaning_zh = ?, bridge_meaning = ?, grammar_note = ?,
                context_sentence = CASE WHEN ? != '' THEN ? ELSE context_sentence END,
                context_zh = CASE WHEN ? != '' THEN ? ELSE context_zh END,
                paper_id = COALESCE(?, paper_id),
                paper_title = CASE WHEN ? != '' THEN ? ELSE paper_title END
            WHERE id = ? AND owner_id = ?
            """,
            (
                entry.get("word", lemma),
                entry.get("stressed_or_ipa", ""),
                entry.get("pos_summary", ""),
                entry.get("meaning_zh", ""),
                entry.get("bridge_meaning", ""),
                entry.get("grammar_note", ""),
                entry.get("context_sentence", ""),
                entry.get("context_sentence", ""),
                entry.get("context_zh", ""),
                entry.get("context_zh", ""),
                entry.get("paper_id"),
                entry.get("paper_title", ""),
                entry.get("paper_title", ""),
                vid,
                owner_id,
            ),
        )
    else:
        cur = conn.execute(
            """
            INSERT INTO vocab (
                owner_id, word, lemma, lang, stressed_or_ipa, pos_summary,
                meaning_zh, bridge_meaning, grammar_note,
                context_sentence, context_zh, paper_id, paper_title,
                repetitions, easiness, interval_days, next_review, last_reviewed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 2.5, 0, ?, 0, ?)
            """,
            (
                owner_id,
                entry.get("word", lemma),
                lemma,
                lang,
                entry.get("stressed_or_ipa", ""),
                entry.get("pos_summary", ""),
                entry.get("meaning_zh", ""),
                entry.get("bridge_meaning", ""),
                entry.get("grammar_note", ""),
                entry.get("context_sentence", ""),
                entry.get("context_zh", ""),
                entry.get("paper_id"),
                entry.get("paper_title", ""),
                now,
                now,
            ),
        )
        vid = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM vocab WHERE id = ?", (vid,)).fetchone()
    conn.close()
    return dict(row)


def review_vocab_sm2(vocab_id: int, quality: int, owner_id: str = "default") -> Optional[Dict[str, Any]]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM vocab WHERE id = ? AND owner_id = ?", (vocab_id, owner_id)).fetchone()
    if not row:
        conn.close()
        return None

    reps = int(row["repetitions"] or 0)
    ef = float(row["easiness"] or 2.5)
    interval = float(row["interval_days"] or 0.0)
    now = time.time()

    if quality < 3:
        reps = 0
        interval = 0.007 if quality == 0 else 0.5
    else:
        if reps == 0:
            interval = 1.0 if quality == 4 else 3.0
        elif reps == 1:
            interval = 4.0 if quality == 4 else 7.0
        else:
            interval = round(interval * ef * (1.2 if quality == 5 else 1.0), 1)
        reps += 1

    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    if ef < 1.3:
        ef = 1.3

    next_rev = now + interval * 86400.0
    conn.execute(
        """
        UPDATE vocab
        SET repetitions = ?, easiness = ?, interval_days = ?, next_review = ?, last_reviewed = ?
        WHERE id = ? AND owner_id = ?
        """,
        (reps, round(ef, 2), round(interval, 2), next_rev, now, vocab_id, owner_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM vocab WHERE id = ?", (vocab_id,)).fetchone()
    conn.close()
    return dict(updated)


def delete_vocab(vocab_id: int, owner_id: str = "default") -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM vocab WHERE id = ? AND owner_id = ?", (vocab_id, owner_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0
