from sqlite3 import Connection

from mix.preview import build_preview
from release.editions import Edition, store_edition


class EmptyRevision(ValueError):
    pass


def publish_revision(db: Connection, revision_id: int) -> Edition:
    preview = build_preview(db, revision_id)
    if preview.timeline.frame_count == 0:
        raise EmptyRevision(revision_id)
    return store_edition(db, preview)
