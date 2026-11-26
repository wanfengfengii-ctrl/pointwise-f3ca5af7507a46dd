from dataclasses import dataclass
from sqlite3 import Connection

from source.catalog import get_source
from source.pcm import PCM_SAMPLE_BYTES


@dataclass(frozen=True)
class Segment:
    segment_id: int
    source_id: int
    program_id: str
    start_frame: int
    end_frame: int

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame


class UnknownSegment(LookupError):
    pass


class InvalidFrameRange(ValueError):
    pass


def ensure_segment_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS segments (
            segment_id INTEGER PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES sources(source_id),
            start_frame INTEGER NOT NULL CHECK (start_frame >= 0),
            end_frame INTEGER NOT NULL CHECK (end_frame > start_frame)
        )
    ''')


def create_segment(db: Connection, source_id: int, start_frame: int, end_frame: int) -> Segment:
    source = get_source(db, source_id)
    if type(start_frame) is not int or type(end_frame) is not int:
        raise InvalidFrameRange('frame bounds must be integers')
    if not 0 <= start_frame < end_frame <= source.frame_count:
        raise InvalidFrameRange('frame range is empty or outside the recording')
    cursor = db.execute('''
        INSERT INTO segments (source_id, start_frame, end_frame) VALUES (?, ?, ?)
    ''', (source.source_id, start_frame, end_frame))
    return Segment(cursor.lastrowid, source.source_id, source.program_id, start_frame, end_frame)


def get_segment(db: Connection, segment_id: int) -> Segment:
    row = db.execute('''
        SELECT segment.segment_id, segment.source_id, source.program_id,
               segment.start_frame, segment.end_frame
        FROM segments AS segment JOIN sources AS source USING (source_id)
        WHERE segment.segment_id = ?
    ''', (str(segment_id),)).fetchone()
    if row is None:
        raise UnknownSegment(segment_id)
    return Segment(*row)


def read_segment_pcm(db: Connection, segment_id: int) -> bytes:
    segment = get_segment(db, segment_id)
    first_byte = segment.start_frame * PCM_SAMPLE_BYTES + 1
    byte_count = segment.frame_count * PCM_SAMPLE_BYTES
    row = db.execute('''
        SELECT substr(pcm, ?, ?) FROM sources WHERE source_id = ?
    ''', (first_byte, byte_count, segment.source_id)).fetchone()
    return row[0]
