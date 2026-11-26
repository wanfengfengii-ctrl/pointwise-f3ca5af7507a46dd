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

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Timeline:
    entries: tuple[TimelineEntry, ...]
    frame_count: int
    pcm: bytes


def assemble_timeline(selection: tuple[SelectedAudio, ...]) -> Timeline:
    if not selection:
        raise ValueError('an empty revision cannot be rendered')
    entries = []
    audio = []
    offset = 0
    for part in selection:
        if part.frame_count <= 0 or len(part.pcm) != part.frame_count * PCM_SAMPLE_BYTES:
            raise ValueError(f'invalid stored PCM length for slot {part.slot}')
        end = offset + part.frame_count
        entries.append(TimelineEntry(
            part.slot, part.segment_id, part.frame_count, offset, end, part.source_kind, part.source_id,
        ))
        audio.append(part.pcm)
        offset = end
    return Timeline(tuple(entries), offset, b''.join(audio))
