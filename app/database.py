"""طبقة قاعدة البيانات — SQLite."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH, DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    unit_price REAL NOT NULL,
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES price_items(id) ON DELETE CASCADE,
    old_price REAL NOT NULL,
    new_price REAL NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    client TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'government',
    status TEXT NOT NULL DEFAULT 'draft',
    data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS content_library (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    tags TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )


def get_settings() -> dict:
    with get_db() as db:
        rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def update_settings(values: dict):
    with get_db() as db:
        for key, value in values.items():
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )


def list_price_items(search: str = "", category: str = "") -> list[dict]:
    query = "SELECT * FROM price_items WHERE 1=1"
    params: list = []
    if search:
        query += " AND (name LIKE ? OR code LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY category, code"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def upsert_price_item(item: dict) -> dict:
    ts = now_iso()
    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM price_items WHERE code = ?", (item["code"],)
        ).fetchone()
        if existing:
            if float(existing["unit_price"]) != float(item["unit_price"]):
                db.execute(
                    "INSERT INTO price_history (item_id, old_price, new_price, changed_at) "
                    "VALUES (?, ?, ?, ?)",
                    (existing["id"], existing["unit_price"], item["unit_price"], ts),
                )
            db.execute(
                "UPDATE price_items SET category=?, name=?, unit=?, unit_price=?, notes=?, updated_at=? "
                "WHERE code=?",
                (item["category"], item["name"], item["unit"], item["unit_price"],
                 item.get("notes", ""), ts, item["code"]),
            )
            row = db.execute("SELECT * FROM price_items WHERE code = ?", (item["code"],)).fetchone()
        else:
            cur = db.execute(
                "INSERT INTO price_items (code, category, name, unit, unit_price, notes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item["code"], item["category"], item["name"], item["unit"],
                 item["unit_price"], item.get("notes", ""), ts),
            )
            row = db.execute("SELECT * FROM price_items WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_price_item(item_id: int):
    with get_db() as db:
        db.execute("DELETE FROM price_items WHERE id = ?", (item_id,))


def get_price_history(item_id: int) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM price_history WHERE item_id = ? ORDER BY changed_at DESC",
            (item_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def next_ref_no() -> str:
    year = datetime.now().year
    prefix = f"AZM-{year}-"
    with get_db() as db:
        row = db.execute(
            "SELECT ref_no FROM proposals WHERE ref_no LIKE ? ORDER BY id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()
    seq = int(row["ref_no"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{prefix}{seq:03d}"


def create_proposal(title: str, client: str, entity_type: str, data: dict) -> dict:
    ts = now_iso()
    ref_no = next_ref_no()
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO proposals (ref_no, title, client, entity_type, status, data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (ref_no, title, client, entity_type, json.dumps(data, ensure_ascii=False), ts, ts),
        )
        row = db.execute("SELECT * FROM proposals WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _proposal_dict(row)


def update_proposal(pid: int, fields: dict) -> dict | None:
    allowed = {"title", "client", "entity_type", "status", "data"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = ?")
        params.append(json.dumps(v, ensure_ascii=False) if k == "data" else v)
    if not sets:
        return get_proposal(pid)
    sets.append("updated_at = ?")
    params += [now_iso(), pid]
    with get_db() as db:
        db.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE id = ?", params)
        row = db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
    return _proposal_dict(row) if row else None


def get_proposal(pid: int) -> dict | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone()
    return _proposal_dict(row) if row else None


def list_proposals() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            "SELECT id, ref_no, title, client, entity_type, status, created_at, updated_at "
            "FROM proposals ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_proposal(pid: int):
    with get_db() as db:
        db.execute("DELETE FROM proposals WHERE id = ?", (pid,))


def _proposal_dict(row) -> dict:
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    return d


def list_library(category: str = "") -> list[dict]:
    query = "SELECT * FROM content_library"
    params: list = []
    if category:
        query += " WHERE category = ?"
        params.append(category)
    query += " ORDER BY category, title"
    with get_db() as db:
        rows = db.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def upsert_library(entry: dict) -> dict:
    ts = now_iso()
    with get_db() as db:
        if entry.get("id"):
            db.execute(
                "UPDATE content_library SET category=?, title=?, body=?, tags=?, updated_at=? WHERE id=?",
                (entry["category"], entry["title"], entry["body"], entry.get("tags", ""), ts, entry["id"]),
            )
            row = db.execute("SELECT * FROM content_library WHERE id = ?", (entry["id"],)).fetchone()
        else:
            cur = db.execute(
                "INSERT INTO content_library (category, title, body, tags, updated_at) VALUES (?, ?, ?, ?, ?)",
                (entry["category"], entry["title"], entry["body"], entry.get("tags", ""), ts),
            )
            row = db.execute("SELECT * FROM content_library WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def delete_library(entry_id: int):
    with get_db() as db:
        db.execute("DELETE FROM content_library WHERE id = ?", (entry_id,))
