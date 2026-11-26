from base64 import b64encode

from edit.revisions import UnknownRevision
from mix.preview import build_preview


def preview_response(preview):
    return {
        'program_id': preview.program_id,
        'revision_id': preview.revision_id,
        'sample_rate': preview.sample_rate,
        'frame_count': preview.timeline.frame_count,
        'timeline': [entry.as_dict() for entry in preview.timeline.entries],
        'wav': b64encode(preview.wav).decode('ascii'),
    }


def get_mix(db, revision_id):
    try:
        preview = build_preview(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 200, preview_response(preview)


MIX_ROUTES = (
    ('GET', r'/mix/(?P<revision_id>[0-9]{1,19})', get_mix),
)
