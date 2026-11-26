from dataclasses import asdict, dataclass

from mix.selection import SelectedAudio
from source.pcm import PCM_SAMPLE_BYTES


@dataclass(frozen=True)
class TimelineEntry:
    slot: int
    segment_id: int
    frame_count: int
    start_frame: int
    end_frame: int
    source_kind: str
    source_id: int
    occurrence_id: str | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        if self.occurrence_id is None:
            data.pop('occurrence_id')
        return data


@dataclass(frozen=True)
class Timeline:
    entries: tuple[TimelineEntry, ...]
    frame_count: int
    pcm: bytes


def assemble_timeline(
    selection: tuple[SelectedAudio, ...], *, with_occurrence: bool = False
) -> Timeline:
    entries = []
    audio = []
    offset = 0
    for part in selection:
        if part.frame_count <= 0 or len(part.pcm) != part.frame_count * PCM_SAMPLE_BYTES:
            raise ValueError(f'invalid stored PCM length for slot {part.slot}')
        end = offset + part.frame_count
        entries.append(TimelineEntry(
            part.slot, part.segment_id, part.frame_count, offset, end,
            part.source_kind, part.source_id,
            part.occurrence_id if with_occurrence else None,
        ))
        audio.append(part.pcm)
        offset = end
    return Timeline(tuple(entries), offset, b''.join(audio))
