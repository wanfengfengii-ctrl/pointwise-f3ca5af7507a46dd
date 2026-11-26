from dataclasses import dataclass
from sqlite3 import Connection, DatabaseError

from dubbing.orders import VoiceOrder


@dataclass(frozen=True)
class ReceivedPart:
    part_id: int
    position: int
    slot: int
    frame_count: int
    pcm: bytes


@dataclass(frozen=True)
class Take:
    take_id: int
    order_id: int
    revision_id: int
    parts: tuple[ReceivedPart, ...]


def ensure_take_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS takes (
            take_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL REFERENCES voice_orders(order_id)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS takes_order ON takes (order_id)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS take_parts (
            part_id INTEGER PRIMARY KEY,
            take_id INTEGER NOT NULL REFERENCES takes(take_id),
            position INTEGER NOT NULL CHECK (position > 0),
            pcm BLOB NOT NULL CHECK (length(pcm) > 0 AND length(pcm) % 2 = 0),
            UNIQUE (take_id, position)
        )
    ''')


def record_take(db: Connection, order: VoiceOrder, recordings: tuple[bytes, ...]) -> Take:
    """Record a validated batch in the same transaction as its receipt."""
    cursor = db.execute('INSERT INTO takes (order_id) VALUES (?)', (order.order_id,))
    take_id = cursor.lastrowid
    parts = []
    for target, pcm in zip(order.targets, recordings, strict=True):
        cursor = db.execute('''
            INSERT INTO take_parts (take_id, position, pcm) VALUES (?, ?, ?)
        ''', (take_id, target.position, pcm))
        parts.append(ReceivedPart(cursor.lastrowid, target.position, target.slot, target.frame_count, pcm))
    return Take(take_id, order.order_id, order.revision_id, tuple(parts))


def get_take(db: Connection, take_id: int) -> Take:
    row = db.execute('''
        SELECT takes.take_id, takes.order_id, voice_orders.revision_id
        FROM takes JOIN voice_orders USING (order_id) WHERE takes.take_id = ?
    ''', (str(take_id),)).fetchone()
    if row is None:
        raise DatabaseError('receipt refers to a missing take')
    parts = db.execute('''
        SELECT part.part_id, part.position, target.slot, target.frame_count, part.pcm
        FROM take_parts AS part
        JOIN order_targets AS target ON target.position = part.position AND target.order_id = ?
        WHERE part.take_id = ? ORDER BY part.position
    ''', (row[1], row[0]))
    return Take(*row, tuple(ReceivedPart(*part) for part in parts))


def latest_parts(db: Connection, revision_id: int) -> dict[int, ReceivedPart]:
    rows = db.execute('''
        WITH ranked_parts AS (
            SELECT part.part_id, part.position, target.slot, target.frame_count,
                   part.pcm, ROW_NUMBER() OVER (
                       PARTITION BY target.slot ORDER BY take.take_id DESC
                   ) AS rank_in_slot
            FROM voice_orders AS orders
            JOIN takes AS take ON take.order_id = orders.order_id
            JOIN take_parts AS part ON part.take_id = take.take_id
            JOIN order_targets AS target
              ON target.order_id = orders.order_id AND target.position = part.position
            WHERE orders.revision_id = ?
        )
        SELECT part_id, position, slot, frame_count, pcm
        FROM ranked_parts WHERE rank_in_slot = 1
    ''', (str(revision_id),))
    return {row[2]: ReceivedPart(*row) for row in rows}
