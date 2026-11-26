from sqlite3 import Connection

from dubbing.orders import VoiceOrder, get_order
from dubbing.receipts import Receipt, RequestConflict, find_receipt, record_receipt
from dubbing.takes import record_take
from source.pcm import PCMFormatError, decode_pcm
from source.programs import ProgramSpec


class InvalidTake(ValueError):
    pass


def validate_parts(order: VoiceOrder, parts: object) -> tuple[bytes, ...]:
    if not isinstance(parts, list) or len(parts) != len(order.targets):
        raise InvalidTake('part count must match the original order')
    spec = ProgramSpec(order.program_id, order.sample_rate)
    recordings = []
    for target, value in zip(order.targets, parts, strict=True):
        try:
            pcm = decode_pcm(value, spec)
        except PCMFormatError as exc:
            raise InvalidTake(f'part {target.position}: {exc}') from exc
        if pcm.frame_count != target.frame_count:
            raise InvalidTake(f'part {target.position} must contain {target.frame_count} frames')
        recordings.append(pcm.data)
    return tuple(recordings)


def submit_take(
    db: Connection, order_id: int, request_id: str, parts: object
) -> tuple[Receipt, bool]:
    order = get_order(db, order_id)
    if not isinstance(request_id, str) or not request_id.strip():
        raise InvalidTake('a nonempty request ID is required')
    previous = find_receipt(db, request_id)
    if previous is not None and previous.take.order_id != order.order_id:
        raise RequestConflict(request_id)
    try:
        recordings = validate_parts(order, parts)
    except InvalidTake as exc:
        if previous is not None:
            raise RequestConflict(request_id) from exc
        raise
    if previous is not None:
        if recordings != tuple(part.pcm for part in previous.take.parts):
            raise RequestConflict(request_id)
        return previous, False
    take = record_take(db, order, recordings)
    return record_receipt(db, request_id, take), True
