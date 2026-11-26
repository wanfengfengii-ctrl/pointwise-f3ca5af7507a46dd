from sqlite3 import Connection


class StaleRevision(ValueError):
    def __init__(self, current_revision_id: int | None):
        self.current_revision_id = current_revision_id
        super().__init__('expected revision is no longer current')


def ensure_draft_schema(db: Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS drafts (
            program_id TEXT PRIMARY KEY NOT NULL REFERENCES programs(program_id),
            revision_id INTEGER NOT NULL REFERENCES revisions(revision_id)
        )
    ''')


def get_current_revision(db: Connection, program_id: str) -> int | None:
    row = db.execute('SELECT revision_id FROM drafts WHERE program_id = ?', (program_id,)).fetchone()
    return row[0] if row is not None else None


def advance_current_revision(
    db: Connection, program_id: str, expected_revision_id: int | None, revision_id: int
) -> None:
    current_revision_id = get_current_revision(db, program_id)
    if current_revision_id != expected_revision_id:
        raise StaleRevision(current_revision_id)
    db.execute('''
        INSERT INTO drafts (program_id, revision_id) VALUES (?, ?)
        ON CONFLICT (program_id) DO UPDATE SET revision_id = excluded.revision_id
    ''', (program_id, revision_id))
