from dataclasses import dataclass
from sqlite3 import Connection

from source.segments import UnknownSegment, get_segment


@dataclass(frozen=True)
class RevisionSlot:
    slot: int
    segment_id: int
    frame_count: int


class InvalidSequence(ValueError):
    pass


def build_slots(db: Connection, program_id: str, segment_ids: object) -> tuple[RevisionSlot, ...]:
    if not isinstance(segment_ids, list) or not segment_ids:
        raise InvalidSequence('expected a nonempty list of segment IDs')
    slots = []
    for position, segment_id in enumerate(segment_ids, start=1):
        if type(segment_id) is not int or segment_id < 1:
            raise InvalidSequence('segment IDs must be positive integers')
        segment = get_segment(db, segment_id)
        if segment.program_id != program_id:
            raise UnknownSegment(segment_id)
        slots.append(RevisionSlot(position, segment.segment_id, segment.frame_count))
    return tuple(slots)
