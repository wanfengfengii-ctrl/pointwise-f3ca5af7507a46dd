from edit.drafts import StaleRevision
from edit.edits import (
    CutConflict,
    InvalidRange,
    RequestConflict,
    UnknownCut,
    apply_cut,
    assert_same_request,
    find_request,
    get_cut_draft,
    insert_segment,
    record_request,
    withdraw_cut,
)
from edit.revisions import Revision, UnknownRevision, get_revision
from edit.workspace import WorkspaceConflict as DraftConflict
from edit.workspace import current_draft_id, save_full_revision
from edit.sequence import InvalidSequence
from source.programs import UnknownProgram
from source.segments import UnknownSegment


def revision_payload(revision: Revision) -> dict:
    return {
        'revision_id': revision.revision_id,
        'program_id': revision.program_id,
        'slots': [
            {'slot': slot.slot, 'segment_id': slot.segment_id, 'frame_count': slot.frame_count}
            for slot in revision.slots
        ],
    }


def post_revisions(db, body):
    program_id = body.get('program_id')
    expected = body.get('expected_revision_id')
    if not isinstance(program_id, str) or not program_id:
        return 400, {'error': 'invalid_program_id'}
    if 'expected_revision_id' not in body or (
        expected is not None and (type(expected) is not int or expected < 1)
    ):
        return 400, {'error': 'invalid_expected_revision_id'}
    try:
        revision = save_full_revision(db, program_id, expected, body.get('segment_ids'))
    except UnknownProgram:
        return 404, {'error': 'unknown_program'}
    except UnknownSegment:
        return 404, {'error': 'unknown_segment'}
    except InvalidSequence as exc:
        return 400, {'error': 'invalid_sequence', 'detail': str(exc)}
    except StaleRevision as exc:
        return 409, {'error': 'stale_revision', 'current_revision_id': exc.current_revision_id}
    return 201, revision_payload(revision)


def get_revision_response(db, revision_id):
    try:
        revision = get_revision(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 200, revision_payload(revision)


def _is_positive_int(value) -> bool:
    return type(value) is int and value >= 1


def post_cuts(db, body):
    allowed = {'request_id', 'revision_id', 'first_slot', 'last_slot'}
    if body.keys() != allowed or not isinstance(body['request_id'], str) or not body['request_id'].strip():
        return 400, {'error': 'invalid_cut_request'}
    revision_id, first_slot, last_slot = body['revision_id'], body['first_slot'], body['last_slot']
    if not all(_is_positive_int(value) for value in (revision_id, first_slot, last_slot)):
        return 400, {'error': 'invalid_cut_request'}
    request_id = body['request_id']
    stored = find_request(db, request_id)
    if stored is not None:
        try:
            assert_same_request(stored, 'cut', None, body)
        except RequestConflict:
            return 409, {'error': 'request_conflict'}
        return 200, stored['response']
    try:
        cut_id, revision = apply_cut(db, revision_id, first_slot, last_slot)
    except DraftConflict:
        return 409, {'error': 'draft_conflict'}
    except (UnknownRevision, LookupError):
        return 404, {'error': 'unknown_revision'}
    except InvalidRange as exc:
        return 400, {'error': 'invalid_slot_range', 'detail': str(exc)}
    response = {'cut_id': cut_id, 'revision': revision_payload(revision)}
    record_request(db, request_id, 'cut', None, body, 201, response)
    return 201, response


def post_cut_withdraw(db, body, cut_id):
    if body.keys() != {'request_id'} or not isinstance(body['request_id'], str) or not body['request_id'].strip():
        return 400, {'error': 'invalid_withdraw_request'}
    request_id = body['request_id']
    stored = find_request(db, request_id)
    if stored is not None:
        try:
            assert_same_request(stored, 'withdraw', cut_id, body)
        except RequestConflict:
            return 409, {'error': 'request_conflict'}
        return 200, stored['response']
    try:
        draft_id = get_cut_draft(db, cut_id)
        current_revision_id = _draft_current(db, draft_id)
        program_id = get_revision(db, current_revision_id).program_id
        if current_draft_id(db, program_id) != draft_id:
            raise DraftConflict(cut_id)
        withdrawn_revision = withdraw_cut(db, cut_id)
    except UnknownCut:
        return 404, {'error': 'unknown_cut'}
    except DraftConflict:
        return 409, {'error': 'draft_conflict'}
    except CutConflict:
        return 409, {'error': 'cut_already_withdrawn'}
    response = {'cut_id': cut_id, 'revision': revision_payload(withdrawn_revision)}
    record_request(db, request_id, 'withdraw', cut_id, body, 201, response)
    return 201, response


def _draft_current(db, draft_id: int) -> int:
    row = db.execute('''
        SELECT current_revision_id FROM work_drafts WHERE draft_id = ?
    ''', (str(draft_id),)).fetchone()
    return row[0]


def post_inserts(db, body):
    allowed = {'request_id', 'revision_id', 'anchor_slot', 'segment_id'}
    if body.keys() != allowed or not isinstance(body['request_id'], str) or not body['request_id'].strip():
        return 400, {'error': 'invalid_insert_request'}
    revision_id, anchor_slot, segment_id = body['revision_id'], body['anchor_slot'], body['segment_id']
    if not all(_is_positive_int(value) for value in (revision_id, anchor_slot, segment_id)):
        return 400, {'error': 'invalid_insert_request'}
    request_id = body['request_id']
    stored = find_request(db, request_id)
    if stored is not None:
        try:
            assert_same_request(stored, 'insert', None, body)
        except RequestConflict:
            return 409, {'error': 'request_conflict'}
        return 200, stored['response']
    try:
        occurrence_id, revision = insert_segment(db, revision_id, anchor_slot, segment_id)
    except UnknownSegment:
        return 404, {'error': 'unknown_segment'}
    except DraftConflict:
        return 409, {'error': 'draft_conflict'}
    except (UnknownRevision, LookupError):
        return 404, {'error': 'unknown_revision'}
    except InvalidRange as exc:
        return 400, {'error': 'invalid_slot_range', 'detail': str(exc)}
    response = {'occurrence_id': occurrence_id, 'revision': revision_payload(revision)}
    record_request(db, request_id, 'insert', None, body, 201, response)
    return 201, response


EDIT_ROUTES = (
    ('POST', r'/revisions', post_revisions),
    ('GET', r'/revisions/(?P<revision_id>[0-9]{1,19})', get_revision_response),
    ('POST', r'/cuts', post_cuts),
    ('POST', r'/cuts/(?P<cut_id>[0-9A-Za-z]{1,64})/withdraw', post_cut_withdraw),
    ('POST', r'/inserts', post_inserts),
)
