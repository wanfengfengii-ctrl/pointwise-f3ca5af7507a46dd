import json
from dataclasses import dataclass
from sqlite3 import Connection

from mix.preview import Preview
from mix.timeline import TimelineEntry


@dataclass(frozen=True)
class Edition:
    edition_id: int
    program_id: str
    revision_id: int
    sample_rate: int
    frame_count: int
    timeline: tuple[TimelineEntry, ...]
    wav: bytes


class UnknownEdition(LookupError):
    pass


def ensure_edition_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS editions (
            edition_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id),
            sample_rate INTEGER NOT NULL CHECK (sample_rate > 0),
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            timeline_json TEXT NOT NULL,
            wav BLOB NOT NULL CHECK (length(wav) > 44)
        )
    ''')


def store_edition(db: Connection, preview: Preview) -> Edition:
    timeline = preview.timeline
    cursor = db.execute('''
        INSERT INTO editions (program_id, revision_id, sample_rate, frame_count, timeline_json, wav)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        preview.program_id, preview.revision_id, preview.sample_rate, timeline.frame_count,
        json.dumps([entry.as_dict() for entry in timeline.entries], separators=(',', ':')), preview.wav,
    ))
    return Edition(cursor.lastrowid, preview.program_id, preview.revision_id,
                   preview.sample_rate, timeline.frame_count, timeline.entries, preview.wav)


def get_edition(db: Connection, edition_id: int) -> Edition:
    row = db.execute('''
        SELECT edition_id, program_id, revision_id, sample_rate, frame_count, timeline_json, wav
        FROM editions WHERE edition_id = ?
    ''', (str(edition_id),)).fetchone()
    if row is None:
        raise UnknownEdition(edition_id)
    stored_id, program_id, revision_id, sample_rate, frame_count, timeline_json, wav = row
    entries = tuple(TimelineEntry(**item) for item in json.loads(timeline_json))
    return Edition(stored_id, program_id, revision_id, sample_rate, frame_count, entries, wav)
