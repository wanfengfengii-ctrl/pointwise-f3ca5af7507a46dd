from dataclasses import dataclass
from sqlite3 import Connection

from dubbing.takes import Take, get_take


@dataclass(frozen=True)
class Receipt:
    receipt_id: int
    request_id: str
    take: Take


class RequestConflict(ValueError):
    pass


def ensure_receipt_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            receipt_id INTEGER PRIMARY KEY,
            request_id TEXT NOT NULL UNIQUE,
            take_id INTEGER NOT NULL UNIQUE REFERENCES takes(take_id)
        )
    ''')


def find_receipt(db: Connection, request_id: str) -> Receipt | None:
    row = db.execute('''
        SELECT receipt_id, take_id FROM receipts WHERE request_id = ?
    ''', (request_id,)).fetchone()
    if row is None:
        return None
    return Receipt(row[0], request_id, get_take(db, row[1]))


def record_receipt(db: Connection, request_id: str, take: Take) -> Receipt:
    cursor = db.execute('''
        INSERT INTO receipts (request_id, take_id) VALUES (?, ?)
    ''', (request_id, take.take_id))
    return Receipt(cursor.lastrowid, request_id, take)
