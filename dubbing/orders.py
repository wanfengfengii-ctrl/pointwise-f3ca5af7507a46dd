from dataclasses import dataclass
from sqlite3 import Connection

from edit.revisions import get_revision
from source.programs import get_program


@dataclass(frozen=True)
class OrderTarget:
    position: int
    slot: int
    frame_count: int


@dataclass(frozen=True)
class VoiceOrder:
    order_id: int
    revision_id: int
    program_id: str
    sample_rate: int
    targets: tuple[OrderTarget, ...]


class UnknownOrder(LookupError):
    pass


class InvalidOrder(ValueError):
    pass


def ensure_order_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS voice_orders (
            order_id INTEGER PRIMARY KEY,
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            sample_rate INTEGER NOT NULL CHECK (sample_rate > 0)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS order_targets (
            order_id INTEGER NOT NULL REFERENCES voice_orders(order_id),
            position INTEGER NOT NULL CHECK (position > 0),
            slot INTEGER NOT NULL CHECK (slot > 0),
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            PRIMARY KEY (order_id, position),
            UNIQUE (order_id, slot)
        )
    ''')
    db.execute('CREATE INDEX IF NOT EXISTS voice_orders_revision ON voice_orders (revision_id)')


def issue_order(db: Connection, revision_id: int, slots: object) -> VoiceOrder:
    revision = get_revision(db, revision_id)
    if not isinstance(slots, list) or not slots:
        raise InvalidOrder('expected a nonempty list of slots')
    available = {entry.slot: entry for entry in revision.slots}
    seen = set()
    targets = []
    for position, slot in enumerate(slots, start=1):
        if type(slot) is not int or slot not in available or slot in seen:
            raise InvalidOrder('slots must be distinct positions on the specified revision')
        targets.append(OrderTarget(position, slot, available[slot].frame_count))
        seen.add(slot)
    spec = get_program(db, revision.program_id)
    cursor = db.execute('''
        INSERT INTO voice_orders (revision_id, sample_rate) VALUES (?, ?)
    ''', (revision.revision_id, spec.sample_rate))
    order_id = cursor.lastrowid
    db.executemany('''
        INSERT INTO order_targets (order_id, position, slot, frame_count) VALUES (?, ?, ?, ?)
    ''', ((order_id, item.position, item.slot, item.frame_count) for item in targets))
    return VoiceOrder(order_id, revision.revision_id, spec.program_id, spec.sample_rate, tuple(targets))


def get_order(db: Connection, order_id: int) -> VoiceOrder:
    row = db.execute('''
        SELECT orders.order_id, orders.revision_id, revisions.program_id, orders.sample_rate
        FROM voice_orders AS orders JOIN revisions USING (revision_id)
        WHERE orders.order_id = ?
    ''', (str(order_id),)).fetchone()
    if row is None:
        raise UnknownOrder(order_id)
    targets = db.execute('''
        SELECT position, slot, frame_count FROM order_targets
        WHERE order_id = ? ORDER BY position
    ''', (row[0],))
    return VoiceOrder(*row, tuple(OrderTarget(*item) for item in targets))
