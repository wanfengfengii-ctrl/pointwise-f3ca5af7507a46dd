from dataclasses import asdict

from dubbing.orders import InvalidOrder, UnknownOrder, issue_order
from dubbing.receipts import RequestConflict
from dubbing.submissions import InvalidTake, submit_take
from edit.revisions import UnknownRevision


def post_voice_orders(db, body):
    revision_id = body.get('revision_id')
    if type(revision_id) is not int or revision_id < 1:
        return 400, {'error': 'invalid_revision_id'}
    try:
        order = issue_order(db, revision_id, body.get('slots'))
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    except InvalidOrder as exc:
        return 400, {'error': 'invalid_order', 'detail': str(exc)}
    return 201, {
        'order_id': order.order_id,
        'revision_id': order.revision_id,
        'program_id': order.program_id,
        'sample_rate': order.sample_rate,
        'targets': [asdict(target) for target in order.targets],
    }


def post_voice_order_take(db, body, order_id):
    try:
        receipt, created = submit_take(db, order_id, body.get('request_id'), body.get('parts'))
    except UnknownOrder:
        return 404, {'error': 'unknown_order'}
    except InvalidTake as exc:
        return 400, {'error': 'invalid_take', 'detail': str(exc)}
    except RequestConflict:
        return 409, {'error': 'request_conflict'}
    take = receipt.take
    return (201 if created else 200), {
        'receipt_id': receipt.receipt_id,
        'request_id': receipt.request_id,
        'take_id': take.take_id,
        'order_id': take.order_id,
        'revision_id': take.revision_id,
        'parts': [
            {'part_id': part.part_id, 'position': part.position, 'slot': part.slot, 'frame_count': part.frame_count}
            for part in take.parts
        ],
    }


DUBBING_ROUTES = (
    ('POST', r'/voice-orders', post_voice_orders),
    ('POST', r'/voice-orders/(?P<order_id>[0-9]{1,19})/takes', post_voice_order_take),
)
