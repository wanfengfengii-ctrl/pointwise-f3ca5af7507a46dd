from dataclasses import dataclass
from sqlite3 import Connection
from typing import ClassVar, Iterable


@dataclass(frozen=True)
class ProgramSpec:
    program_id: str
    sample_rate: int
    channels: ClassVar[int] = 1
    encoding: ClassVar[str] = 'pcm_s16le'


class UnknownProgram(LookupError):
    pass


def ensure_program_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS programs (
            program_id TEXT PRIMARY KEY NOT NULL,
            sample_rate INTEGER NOT NULL CHECK (sample_rate BETWEEN 1 AND 2147483647)
        )
    ''')


def seed_programs(db: Connection, programs: Iterable[ProgramSpec]) -> None:
    for spec in programs:
        if not isinstance(spec.program_id, str) or not spec.program_id:
            raise ValueError('program ID must be a nonempty string')
        if type(spec.sample_rate) is not int or not 1 <= spec.sample_rate <= 2147483647:
            raise ValueError('sample rate is outside the PCM16 WAV range')
        db.execute('''
            INSERT INTO programs (program_id, sample_rate) VALUES (?, ?)
            ON CONFLICT (program_id) DO NOTHING
        ''', (spec.program_id, spec.sample_rate))


def get_program(db: Connection, program_id: str) -> ProgramSpec:
    row = db.execute('''
        SELECT program_id, sample_rate FROM programs WHERE program_id = ?
    ''', (program_id,)).fetchone()
    if row is None:
        raise UnknownProgram(program_id)
    return ProgramSpec(*row)
