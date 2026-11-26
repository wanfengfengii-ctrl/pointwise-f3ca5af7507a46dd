from dataclasses import dataclass
from sqlite3 import Connection

from source.pcm import PCM, PCMFormatError
from source.programs import ProgramSpec


@dataclass(frozen=True)
class Source:
    source_id: int
    program_id: str
    description: str
    frame_count: int
    pcm: bytes


class UnknownSource(LookupError):
    pass


def ensure_source_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS sources (
            source_id INTEGER PRIMARY KEY,
            program_id TEXT NOT NULL REFERENCES programs(program_id),
            description TEXT NOT NULL,
            frame_count INTEGER NOT NULL CHECK (frame_count > 0),
            pcm BLOB NOT NULL CHECK (length(pcm) = 2 * frame_count)
        )
    ''')


def register_source(db: Connection, spec: ProgramSpec, description: str, pcm: PCM) -> Source:
    if not isinstance(description, str) or not description.strip():
        raise PCMFormatError('source description is required')
    cursor = db.execute('''
        INSERT INTO sources (program_id, description, frame_count, pcm)
        VALUES (?, ?, ?, ?)
    ''', (spec.program_id, description, pcm.frame_count, pcm.data))
    return Source(cursor.lastrowid, spec.program_id, description, pcm.frame_count, pcm.data)


def get_source(db: Connection, source_id: int) -> Source:
    row = db.execute('''
        SELECT source_id, program_id, description, frame_count, pcm
        FROM sources WHERE source_id = ?
    ''', (str(source_id),)).fetchone()
    if row is None:
        raise UnknownSource(source_id)
    return Source(*row)
