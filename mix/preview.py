from dataclasses import dataclass
from sqlite3 import Connection

from edit.revisions import get_revision
from mix.selection import select_audio
from mix.timeline import Timeline, assemble_timeline
from mix.wav import encode_wav
from source.programs import get_program


@dataclass(frozen=True)
class Preview:
    program_id: str
    revision_id: int
    sample_rate: int
    timeline: Timeline
    wav: bytes


def build_preview(db: Connection, revision_id: int) -> Preview:
    """Render audio and provenance from the caller's single database snapshot."""
    revision = get_revision(db, revision_id)
    spec = get_program(db, revision.program_id)
    timeline = assemble_timeline(select_audio(db, revision))
    return Preview(spec.program_id, revision.revision_id, spec.sample_rate, timeline,
                   encode_wav(timeline.pcm, spec.sample_rate))
