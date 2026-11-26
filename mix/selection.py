from dataclasses import dataclass
from sqlite3 import Connection

from dubbing.takes import latest_parts, latest_parts_for_occurrences
from edit.revisions import Revision
from source.segments import read_segment_pcm


@dataclass(frozen=True)
class SelectedAudio:
    slot: int
    segment_id: int
    frame_count: int
    occurrence_id: str
    source_kind: str
    source_id: int
    pcm: bytes


def select_audio(db: Connection, revision: Revision) -> tuple[SelectedAudio, ...]:
    """Per-proof preview: only receipts issued against this proof are considered."""
    received = latest_parts(db, revision.revision_id)
    selection = []
    for slot in revision.slots:
        part = received.get(slot.occurrence_id)
        if part is None:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, slot.occurrence_id,
                'source', slot.segment_id, read_segment_pcm(db, slot.segment_id),
            ))
        else:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, slot.occurrence_id,
                'voice', part.part_id, part.pcm,
            ))
    return tuple(selection)


def select_current_audio(db: Connection, revision: Revision) -> tuple[SelectedAudio, ...]:
    """Current mix: each visible occurrence uses its latest successful take across issuing proofs."""
    occurrence_ids = tuple(slot.occurrence_id for slot in revision.slots)
    received = latest_parts_for_occurrences(db, occurrence_ids)
    selection = []
    for slot in revision.slots:
        part = received.get(slot.occurrence_id)
        if part is None:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, slot.occurrence_id,
                'source', slot.segment_id, read_segment_pcm(db, slot.segment_id),
            ))
        else:
            selection.append(SelectedAudio(
                slot.slot, slot.segment_id, slot.frame_count, slot.occurrence_id,
                'voice', part.part_id, part.pcm,
            ))
    return tuple(selection)
