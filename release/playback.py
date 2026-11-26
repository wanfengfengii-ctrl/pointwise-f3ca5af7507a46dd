from base64 import b64encode
from sqlite3 import Connection

from release.editions import Edition, get_edition


def edition_payload(edition: Edition) -> dict:
    return {
        'edition_id': edition.edition_id,
        'program_id': edition.program_id,
        'revision_id': edition.revision_id,
        'sample_rate': edition.sample_rate,
        'frame_count': edition.frame_count,
        'timeline': [entry.as_dict() for entry in edition.timeline],
        'wav': b64encode(edition.wav).decode('ascii'),
    }


def read_playback(db: Connection, edition_id: int) -> dict:
    return edition_payload(get_edition(db, edition_id))
