from dataclasses import dataclass
from sqlite3 import Connection

from dubbing.takes import latest_parts
from edit.revisions import Revision
from source.segments import read_segment_pcm


@dataclass(frozen=True)
class SelectedAudio:
    slot: int
    segment_id: int
    frame_count: int
    source_kind: str
    source_id: int
    pcm: bytes


def select_audio(db: Connection, revision: Revision) -> tuple[SelectedAudio, ...]:
    received = latest_parts(db, revision.revision_id)
    selection = []
    for slot in revision.slots:
        part = received.get(slot.slot)
        if part is None:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, 'source', slot.segment_id,
                read_segment_pcm(db, slot.segment_id),
            ))
        else:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, 'voice', part.part_id, part.pcm,
            ))
    return tuple(selection)
