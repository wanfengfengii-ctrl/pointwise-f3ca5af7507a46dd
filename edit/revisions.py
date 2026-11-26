from dataclasses import dataclass
from sqlite3 import Connection

from edit.drafts import advance_current_revision
from edit.sequence import RevisionSlot, build_slots
from source.programs import get_program


@dataclass(frozen=True)
class Revision:
    revision_id: int
    program_id: str
    slots: tuple[RevisionSlot, ...]


class UnknownRevision(LookupError):
    pass


def ensure_revision_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            revision_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS revision_slots (
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            slot INTEGER NOT NULL CHECK (slot > 0),
            segment_id INTEGER NOT NULL REFERENCES segments(segment_id),
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            PRIMARY KEY (revision_id, slot)
        )
    ''')


def save_revision(
    db: Connection, program_id: str, expected_revision_id: int | None, segment_ids: object
) -> Revision:
    """Save the immutable proof and advance its draft in the caller's write transaction."""
    spec = get_program(db, program_id)
    slots = build_slots(db, spec.program_id, segment_ids)
    cursor = db.execute('INSERT INTO revisions (program_id) VALUES (?)', (spec.program_id,))
    revision_id = cursor.lastrowid
    db.executemany('''
        INSERT INTO revision_slots (revision_id, slot, segment_id, frame_count)
        VALUES (?, ?, ?, ?)
    ''', ((revision_id, slot.slot, slot.segment_id, slot.frame_count) for slot in slots))
    advance_current_revision(db, spec.program_id, expected_revision_id, revision_id)
    return Revision(revision_id, spec.program_id, slots)


def get_revision(db: Connection, revision_id: int) -> Revision:
    row = db.execute('''
        SELECT revision_id, program_id FROM revisions WHERE revision_id = ?
    ''', (str(revision_id),)).fetchone()
    if row is None:
        raise UnknownRevision(revision_id)
    stored_id, program_id = row
    slots = db.execute('''
        SELECT slot, segment_id, frame_count FROM revision_slots
        WHERE revision_id = ? ORDER BY slot
    ''', (stored_id,))
    return Revision(stored_id, program_id, tuple(RevisionSlot(*slot) for slot in slots))
