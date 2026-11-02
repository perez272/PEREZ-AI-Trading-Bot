from __future__ import annotations
import sqlite3
import json
from datetime import datetime, timezone

DB = "data/runtime/active_positions.sqlite3"

def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_positions (
            contract TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            trade_id TEXT NOT NULL,
            opened_at TEXT NOT NULL
        )
    """)
    cols = {r[1] for r in c.execute("PRAGMA table_info(active_positions)")}
    if "claimed_at" not in cols:
        c.execute("ALTER TABLE active_positions ADD COLUMN claimed_at TEXT")
        c.execute("""
            UPDATE active_positions
            SET claimed_at=opened_at
            WHERE claimed_at IS NULL
        """)
        c.commit()
    if "status" not in cols:
        c.execute("ALTER TABLE active_positions ADD COLUMN status TEXT NOT NULL DEFAULT 'ACTIVE'")
    if "trade_payload" not in cols:
        c.execute("ALTER TABLE active_positions ADD COLUMN trade_payload TEXT")
    c.commit()
    return c

def claim_contract(contract, symbol, trade_id, trade_payload=None):
    contract = str(contract).strip()
    if not contract:
        return False, "EMPTY_CONTRACT"
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload = json.dumps(trade_payload or {}, separators=(",", ":"), default=str)
            db.execute(
                """INSERT INTO active_positions
                   (contract,symbol,trade_id,opened_at,claimed_at,status,trade_payload)
                   VALUES(?,?,?,?,?,'PENDING',?)""",
                (contract, str(symbol), str(trade_id), now, now, payload)
            )
            db.commit()
            return True, "CLAIMED"
        except sqlite3.IntegrityError:
            row = db.execute(
                "SELECT trade_id FROM active_positions WHERE contract=?",
                (contract,)
            ).fetchone()
            db.rollback()
            return False, f"ACTIVE_CONTRACT:{row[0] if row else 'UNKNOWN'}"
    finally:
        db.close()

def mark_claim_active(contract, trade_id, trade_payload):
    payload = json.dumps(trade_payload, separators=(",", ":"), default=str)
    db = _db()
    try:
        cur = db.execute(
            """UPDATE active_positions
               SET status='ACTIVE', trade_payload=?
               WHERE contract=? AND trade_id=?""",
            (payload, str(contract), str(trade_id)),
        )
        db.commit()
        if cur.rowcount != 1:
            raise RuntimeError("ACTIVE_POSITION_CLAIM_NOT_FOUND")
    finally:
        db.close()

def release_contract(contract, trade_id=None):
    db = _db()
    try:
        if trade_id:
            db.execute(
                "DELETE FROM active_positions WHERE contract=? AND trade_id=?",
                (str(contract), str(trade_id))
            )
        else:
            db.execute(
                "DELETE FROM active_positions WHERE contract=?",
                (str(contract),)
            )
        db.commit()
    finally:
        db.close()

def active_contracts():
    db = _db()
    try:
        return db.execute(
            "SELECT contract,symbol,trade_id,claimed_at,status,trade_payload "
            "FROM active_positions ORDER BY claimed_at"
        ).fetchall()
    finally:
        db.close()
