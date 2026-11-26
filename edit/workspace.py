import uuid
from sqlite3 import Connection

from edit.drafts import advance_current_revision
from edit.revisions import Revision, RevisionSlot
from edit.sequence import build_slots
from source.programs import get_program
from source.segments import get_segment


class WorkspaceConflict(LookupError):
    """Raised when an edit references a proof outside the current work draft."""


def _table_columns(db: Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f'PRAGMA table_info({table})')}


def ensure_workspace_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS work_drafts (
            draft_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            current_revision_id INTEGER NOT NULL REFERENCES revisions(revision_id)
        )
    ''')
    columns = _table_columns(db, 'revisions')
    if columns and 'draft_id' not in columns:
        db.execute('ALTER TABLE revisions ADD COLUMN draft_id INTEGER REFERENCES work_drafts(draft_id)')
    db.execute('''
        CREATE TABLE IF NOT EXISTS occurrences (
            occurrence_id TEXT PRIMARY KEY,
            draft_id INTEGER NOT NULL REFERENCES work_drafts(draft_id),
            kind TEXT NOT NULL CHECK (kind IN ('base', 'insert')),
            segment_id INTEGER NOT NULL REFERENCES segments(segment_id),
            base_slot INTEGER,
            parent_occurrence_id TEXT REFERENCES occurrences(occurrence_id),
            insert_seq INTEGER
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS revision_occurrences (
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            slot INTEGER NOT NULL CHECK (slot > 0),
            occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
            PRIMARY KEY (revision_id, slot)
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS cuts (
            cut_id TEXT PRIMARY KEY,
            draft_id INTEGER NOT NULL REFERENCES work_drafts(draft_id),
            base_revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            first_slot INTEGER NOT NULL CHECK (first_slot > 0),
            last_slot INTEGER NOT NULL CHECK (last_slot >= first_slot),
            withdrawn INTEGER NOT NULL DEFAULT 0 CHECK (withdrawn IN (0, 1))
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS cut_occurrences (
            cut_id TEXT NOT NULL REFERENCES cuts(cut_id),
            occurrence_id TEXT NOT NULL REFERENCES occurrences(occurrence_id),
            PRIMARY KEY (cut_id, occurrence_id)
        )
    ''')
    _migrate_legacy(db, columns)


def _migrate_legacy(db: Connection, revision_columns: set[str]) -> None:
    """Backfill work drafts, occurrences and order targets for pre-existing databases."""
    if not revision_columns or 'draft_id' not in revision_columns:
        # A legacy revisions table: every pre-existing proof becomes its own work draft.
        legacy_rows = db.execute('''
            SELECT r.revision_id, r.program_id, rs.slot, rs.segment_id
            FROM revisions AS r JOIN revision_slots AS rs USING (revision_id)
            ORDER BY r.revision_id, rs.slot
        ''').fetchall()
        by_revision: dict[int, list[tuple]] = {}
        for row in legacy_rows:
            by_revision.setdefault(row[0], []).append(row)
        for revision_id, rows in by_revision.items():
            program_id = rows[0][1]
            cursor = db.execute('''
                INSERT INTO work_drafts (program_id, current_revision_id) VALUES (?, ?)
            ''', (program_id, revision_id))
            draft_id = cursor.lastrowid
            db.execute('UPDATE revisions SET draft_id = ? WHERE revision_id = ?',
                       (draft_id, revision_id))
            for _, _, slot, segment_id in rows:
                occurrence_id = uuid.uuid4().hex
                db.execute('''
                    INSERT INTO occurrences (occurrence_id, draft_id, kind, segment_id, base_slot)
                    VALUES (?, ?, 'base', ?, ?)
                ''', (occurrence_id, draft_id, segment_id, slot))
                db.execute('''
                    INSERT INTO revision_occurrences (revision_id, slot, occurrence_id)
                    VALUES (?, ?, ?)
                ''', (revision_id, slot, occurrence_id))
    else:
        orphan = db.execute('SELECT COUNT(*) FROM revisions WHERE draft_id IS NULL').fetchone()[0]
        if orphan:
            raise RuntimeError('revision rows without a work draft after migration')
    _migrate_order_targets(db)


def _migrate_order_targets(db: Connection) -> None:
    target_columns = _table_columns(db, 'order_targets')
    if not target_columns or 'occurrence_id' in target_columns:
        return
    db.execute('ALTER TABLE order_targets ADD COLUMN occurrence_id TEXT REFERENCES occurrences(occurrence_id)')
    db.execute('''
        UPDATE order_targets
           SET occurrence_id = (
                SELECT ro.occurrence_id FROM revision_occurrences AS ro
                WHERE ro.revision_id = (
                    SELECT vo.revision_id FROM voice_orders AS vo
                    WHERE vo.order_id = order_targets.order_id
                ) AND ro.slot = order_targets.slot
            )
    ''')


def current_draft_id(db: Connection, program_id: str) -> int | None:
    row = db.execute('SELECT revision_id FROM drafts WHERE program_id = ?', (program_id,)).fetchone()
    if row is None:
        return None
    proof = db.execute('SELECT draft_id FROM revisions WHERE revision_id = ?', (row[0],)).fetchone()
    return proof[0] if proof is not None else None


def ensure_current_draft(db: Connection, revision_id: int) -> int:
    """Return the draft id of a proof only while it belongs to the program's current draft."""
    row = db.execute('''
        SELECT revisions.draft_id, revisions.program_id
        FROM revisions WHERE revisions.revision_id = ?
    ''', (str(revision_id),)).fetchone()
    if row is None:
        raise LookupError(revision_id)
    draft_id, program_id = row
    current = current_draft_id(db, program_id)
    if current != draft_id:
        raise WorkspaceConflict(revision_id)
    return draft_id


def next_insert_seq(db: Connection, draft_id: int) -> int:
    row = db.execute('''
        SELECT COALESCE(MAX(insert_seq), 0) + 1 FROM occurrences
        WHERE draft_id = ? AND kind = 'insert'
    ''', (str(draft_id),)).fetchone()
    return row[0]


def save_full_revision(
    db: Connection, program_id: str, expected_revision_id: int | None, segment_ids: object
) -> Revision:
    """An ordinary whole-proof save opens a brand new work draft and fresh occurrence identities."""
    spec = get_program(db, program_id)
    slots = build_slots(db, spec.program_id, segment_ids)
    cursor = db.execute('INSERT INTO revisions (program_id) VALUES (?)', (spec.program_id,))
    revision_id = cursor.lastrowid
    db.executemany('''
        INSERT INTO revision_slots (revision_id, slot, segment_id, frame_count)
        VALUES (?, ?, ?, ?)
    ''', ((revision_id, slot.slot, slot.segment_id, slot.frame_count) for slot in slots))
    cursor = db.execute('''
        INSERT INTO work_drafts (program_id, current_revision_id) VALUES (?, ?)
    ''', (spec.program_id, revision_id))
    draft_id = cursor.lastrowid
    new_slots = []
    for slot in slots:
        occurrence_id = uuid.uuid4().hex
        db.execute('''
            INSERT INTO occurrences (occurrence_id, draft_id, kind, segment_id, base_slot)
            VALUES (?, ?, 'base', ?, ?)
        ''', (occurrence_id, draft_id, slot.segment_id, slot.slot))
        db.execute('''
            INSERT INTO revision_occurrences (revision_id, slot, occurrence_id)
            VALUES (?, ?, ?)
        ''', (revision_id, slot.slot, occurrence_id))
        new_slots.append(RevisionSlot(slot.slot, slot.segment_id, slot.frame_count, occurrence_id))
    db.execute('UPDATE revisions SET draft_id = ? WHERE revision_id = ?', (draft_id, revision_id))
    advance_current_revision(db, spec.program_id, expected_revision_id, revision_id)
    return Revision(revision_id, spec.program_id, draft_id, tuple(new_slots))


def create_revision(db: Connection, draft_id: int, program_id: str, visible) -> Revision:
    """Persist a new proof inside an existing draft from an ordered visible occurrence list."""
    cursor = db.execute('INSERT INTO revisions (program_id, draft_id) VALUES (?, ?)',
                        (program_id, draft_id))
    revision_id = cursor.lastrowid
    slots = []
    for slot, item in enumerate(visible, start=1):
        occurrence_id, segment_id, frame_count = item
        db.execute('''
            INSERT INTO revision_slots (revision_id, slot, segment_id, frame_count)
            VALUES (?, ?, ?, ?)
        ''', (revision_id, slot, segment_id, frame_count))
        db.execute('''
            INSERT INTO revision_occurrences (revision_id, slot, occurrence_id)
            VALUES (?, ?, ?)
        ''', (revision_id, slot, occurrence_id))
        slots.append(RevisionSlot(slot, segment_id, frame_count, occurrence_id))
    db.execute('UPDATE work_drafts SET current_revision_id = ? WHERE draft_id = ?',
               (revision_id, draft_id))
    # Keep the program-level current pointer (used by /mix/current) in lockstep.
    db.execute('UPDATE drafts SET revision_id = ? WHERE program_id = ?',
               (revision_id, program_id))
    return Revision(revision_id, program_id, draft_id, tuple(slots))


def resolve_slot_occurrence(db: Connection, revision_id: int, slot: int) -> str:
    row = db.execute('''
        SELECT occurrence_id FROM revision_occurrences WHERE revision_id = ? AND slot = ?
    ''', (str(revision_id), str(slot))).fetchone()
    if row is None:
        raise LookupError((revision_id, slot))
    return row[0]


def segment_frame_count(db: Connection, segment_id: int) -> int:
    return get_segment(db, segment_id).frame_count
