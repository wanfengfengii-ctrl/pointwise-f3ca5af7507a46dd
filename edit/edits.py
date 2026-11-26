import json
import uuid
from sqlite3 import Connection

from edit.revisions import Revision, get_revision
from edit.workspace import (
    create_revision,
    ensure_current_draft,
    next_insert_seq,
    resolve_slot_occurrence,
)
from source.segments import UnknownSegment


class UnknownCut(LookupError):
    pass


class InvalidRange(ValueError):
    pass


class CutConflict(ValueError):
    pass


class RequestConflict(ValueError):
    pass


def ensure_edit_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS edit_requests (
            request_id TEXT PRIMARY KEY,
            operation TEXT NOT NULL CHECK (operation IN ('cut', 'withdraw', 'insert')),
            target_id TEXT,
            payload_json TEXT NOT NULL,
            status_code INTEGER NOT NULL,
            response_json TEXT NOT NULL
        )
    ''')


def find_request(db: Connection, request_id: str):
    row = db.execute('''
        SELECT request_id, operation, target_id, payload_json, status_code, response_json
        FROM edit_requests WHERE request_id = ?
    ''', (request_id,)).fetchone()
    if row is None:
        return None
    return {
        'request_id': row[0], 'operation': row[1], 'target_id': row[2],
        'payload': json.loads(row[3]), 'status_code': row[4],
        'response': json.loads(row[5]),
    }


def record_request(db: Connection, request_id, operation, target_id, payload, status_code, response) -> None:
    db.execute('''
        INSERT INTO edit_requests
            (request_id, operation, target_id, payload_json, status_code, response_json)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        request_id, operation, target_id,
        json.dumps(payload, separators=(',', ':')), status_code,
        json.dumps(response, separators=(',', ':')),
    ))


def assert_same_request(stored, operation, target_id, payload) -> None:
    if stored['operation'] != operation or stored['target_id'] != target_id or stored['payload'] != payload:
        raise RequestConflict(stored['request_id'])


def _load_draft_state(db: Connection, draft_id: int):
    """Return base occurrences and insert children in the draft's structural state."""
    base_rows = db.execute('''
        SELECT occurrence_id, segment_id, base_slot
        FROM occurrences WHERE draft_id = ? AND kind = 'base' ORDER BY base_slot
    ''', (str(draft_id),)).fetchall()
    child_rows = db.execute('''
        SELECT occurrence_id, segment_id, parent_occurrence_id, insert_seq
        FROM occurrences WHERE draft_id = ? AND kind = 'insert'
        ORDER BY insert_seq
    ''', (str(draft_id),)).fetchall()
    children: dict[str, list] = {}
    for row in child_rows:
        children.setdefault(row[2], []).append(row)
    return base_rows, children


def _hidden_base(db: Connection, draft_id: int) -> set[str]:
    rows = db.execute('''
        SELECT link.occurrence_id
        FROM cuts AS cut
        JOIN cut_occurrences AS link ON link.cut_id = cut.cut_id
        WHERE cut.draft_id = ? AND cut.withdrawn = 0
    ''', (str(draft_id),)).fetchall()
    return {row[0] for row in rows}


def _frame_count(db: Connection, segment_id: int) -> int:
    row = db.execute('''
        SELECT end_frame - start_frame FROM segments WHERE segment_id = ?
    ''', (str(segment_id),)).fetchone()
    if row is None:
        raise LookupError(segment_id)
    return row[0]


def visible_occurrences(db: Connection, draft_id: int):
    """Depth-first structural walk; hidden base occurrences are skipped but their inserts stay."""
    base_rows, children = _load_draft_state(db, draft_id)
    hidden = _hidden_base(db, draft_id)

    def walk(occurrence_id, segment_id):
        ordered = children.get(occurrence_id, ())
        result = []
        for child_id, child_segment, _, _ in ordered:
            result.extend(walk(child_id, child_segment))
        if occurrence_id not in hidden:
            result.append((occurrence_id, segment_id, _frame_count(db, segment_id)))
        return result

    visible = []
    for occurrence_id, segment_id, _ in base_rows:
        visible.extend(walk(occurrence_id, segment_id))
    return visible


def apply_cut(db: Connection, revision_id: int, first_slot: int, last_slot: int) -> tuple[str, Revision]:
    draft_id = ensure_current_draft(db, revision_id)
    proof = get_revision(db, revision_id)
    if first_slot < 1 or last_slot < first_slot or last_slot > len(proof.slots):
        raise InvalidRange('slot range must be a nonempty contiguous range on the referenced proof')
    targets = tuple(
        proof.slots[slot - 1].occurrence_id for slot in range(first_slot, last_slot + 1)
    )
    # A cut only hides original (base) occurrences; inserted occurrences are never covered.
    base_ids = {
        row[0] for row in db.execute('''
            SELECT occurrence_id FROM occurrences
            WHERE draft_id = ? AND kind = 'base'
        ''', (str(draft_id),))
    }
    targets = tuple(occurrence_id for occurrence_id in targets if occurrence_id in base_ids)
    cut_id = uuid.uuid4().hex
    db.execute('''
        INSERT INTO cuts (cut_id, draft_id, base_revision_id, first_slot, last_slot)
        VALUES (?, ?, ?, ?, ?)
    ''', (cut_id, draft_id, revision_id, first_slot, last_slot))
    db.executemany('''
        INSERT INTO cut_occurrences (cut_id, occurrence_id) VALUES (?, ?)
    ''', ((cut_id, occurrence_id) for occurrence_id in targets))
    visible = visible_occurrences(db, draft_id)
    new_revision = create_revision(db, draft_id, proof.program_id, visible)
    return cut_id, new_revision


def withdraw_cut(db: Connection, cut_id: str) -> Revision:
    row = db.execute('''
        SELECT cut_id, draft_id, withdrawn FROM cuts WHERE cut_id = ?
    ''', (cut_id,)).fetchone()
    if row is None:
        raise UnknownCut(cut_id)
    _, draft_id, withdrawn = row
    if withdrawn:
        raise CutConflict('cut already withdrawn')
    current_revision_id = _current_revision_id(db, draft_id)
    program_id = get_revision(db, current_revision_id).program_id
    db.execute('UPDATE cuts SET withdrawn = 1 WHERE cut_id = ?', (cut_id,))
    visible = visible_occurrences(db, draft_id)
    return create_revision(db, draft_id, program_id, visible)


def _current_revision_id(db: Connection, draft_id: int) -> int:
    row = db.execute('''
        SELECT current_revision_id FROM work_drafts WHERE draft_id = ?
    ''', (str(draft_id),)).fetchone()
    return row[0]


def insert_segment(
    db: Connection, revision_id: int, anchor_slot: int, segment_id: int
) -> tuple[str, Revision]:
    draft_id = ensure_current_draft(db, revision_id)
    proof = get_revision(db, revision_id)
    if anchor_slot < 1 or anchor_slot > len(proof.slots):
        raise InvalidRange('anchor slot must exist on the referenced proof')
    anchor_occurrence = resolve_slot_occurrence(db, revision_id, anchor_slot)
    # The segment must belong to the same program as the work draft.
    segment_row = db.execute('''
        SELECT segments.segment_id, sources.program_id
        FROM segments JOIN sources USING (source_id) WHERE segment_id = ?
    ''', (str(segment_id),)).fetchone()
    if segment_row is None:
        raise UnknownSegment(segment_id)
    if segment_row[1] != proof.program_id:
        raise UnknownSegment(segment_id)
    insert_seq = next_insert_seq(db, draft_id)
    occurrence_id = uuid.uuid4().hex
    db.execute('''
        INSERT INTO occurrences
            (occurrence_id, draft_id, kind, segment_id, parent_occurrence_id, insert_seq)
        VALUES (?, ?, 'insert', ?, ?, ?)
    ''', (occurrence_id, draft_id, segment_id, anchor_occurrence, insert_seq))
    visible = visible_occurrences(db, draft_id)
    new_revision = create_revision(db, draft_id, proof.program_id, visible)
    return occurrence_id, new_revision


def get_cut_draft(db: Connection, cut_id: str) -> int:
    row = db.execute('SELECT draft_id FROM cuts WHERE cut_id = ?', (cut_id,)).fetchone()
    if row is None:
        raise UnknownCut(cut_id)
    return row[0]
