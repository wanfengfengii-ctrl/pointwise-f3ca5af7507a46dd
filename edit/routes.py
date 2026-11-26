from dataclasses import asdict

from edit.drafts import StaleRevision
from edit.revisions import UnknownRevision, get_revision, save_revision
from edit.sequence import InvalidSequence
from source.programs import UnknownProgram
from source.segments import UnknownSegment


def _revision_payload(revision):
    return {
        'revision_id': revision.revision_id,
        'program_id': revision.program_id,
        'slots': [asdict(slot) for slot in revision.slots],
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
        revision = save_revision(db, program_id, expected, body.get('segment_ids'))
    except UnknownProgram:
        return 404, {'error': 'unknown_program'}
    except UnknownSegment:
        return 404, {'error': 'unknown_segment'}
    except InvalidSequence as exc:
        return 400, {'error': 'invalid_sequence', 'detail': str(exc)}
    except StaleRevision as exc:
        return 409, {'error': 'stale_revision', 'current_revision_id': exc.current_revision_id}
    return 201, _revision_payload(revision)


def get_revision_response(db, revision_id):
    try:
        revision = get_revision(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 200, _revision_payload(revision)


EDIT_ROUTES = (
    ('POST', r'/revisions', post_revisions),
    ('GET', r'/revisions/(?P<revision_id>[0-9]{1,19})', get_revision_response),
)
