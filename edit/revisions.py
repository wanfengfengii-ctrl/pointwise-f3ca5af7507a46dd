from dataclasses import dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class RevisionSlot:
    slot: int
    segment_id: int
    frame_count: int
    occurrence_id: str


@dataclass(frozen=True)
class Revision:
    revision_id: int
    program_id: str
    draft_id: int
    slots: tuple[RevisionSlot, ...]


class UnknownRevision(LookupError):
    pass


def ensure_revision_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            revision_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            draft_id INTEGER
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


def get_revision(db: Connection, revision_id: int) -> Revision:
    row = db.execute('''
        SELECT revision_id, program_id, draft_id FROM revisions WHERE revision_id = ?
    ''', (str(revision_id),)).fetchone()
    if row is None:
        raise UnknownRevision(revision_id)
    stored_id, program_id, draft_id = row
    slots = db.execute('''
        SELECT slot.slot, slot.segment_id, slot.frame_count, link.occurrence_id
        FROM revision_slots AS slot
        JOIN revision_occurrences AS link
          ON link.revision_id = slot.revision_id AND link.slot = slot.slot
        WHERE slot.revision_id = ? ORDER BY slot.slot
    ''', (stored_id,))
    return Revision(stored_id, program_id, draft_id,
                    tuple(RevisionSlot(*item) for item in slots))
