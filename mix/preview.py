from dataclasses import dataclass
from sqlite3 import Connection

from edit.drafts import get_current_revision
from edit.revisions import get_revision
from mix.selection import select_audio, select_current_audio
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


def build_current_preview(db: Connection, program_id: str) -> Preview:
    """Render the current work draft proof with cross-proof take selection per occurrence."""
    current_revision_id = get_current_revision(db, program_id)
    if current_revision_id is None:
        raise LookupError(program_id)
    revision = get_revision(db, current_revision_id)
    spec = get_program(db, revision.program_id)
    timeline = assemble_timeline(select_current_audio(db, revision), with_occurrence=True)
    return Preview(spec.program_id, revision.revision_id, spec.sample_rate, timeline,
                   encode_wav(timeline.pcm, spec.sample_rate))
