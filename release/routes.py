from edit.revisions import UnknownRevision
from release.editions import UnknownEdition
from release.playback import edition_payload, read_playback
from release.publish import publish_revision


def post_editions(db, body):
    revision_id = body.get('revision_id')
    if type(revision_id) is not int or revision_id < 1:
        return 400, {'error': 'invalid_revision_id'}
    try:
        edition = publish_revision(db, revision_id)
    except UnknownRevision:
        return 404, {'error': 'unknown_revision'}
    return 201, edition_payload(edition)


def get_edition_response(db, edition_id):
    try:
        playback = read_playback(db, edition_id)
    except UnknownEdition:
        return 404, {'error': 'unknown_edition'}
    return 200, playback


def get_health(_db):
    return 200, {'status': 'ready'}


RELEASE_ROUTES = (
    ('GET', r'/health', get_health),
    ('POST', r'/editions', post_editions),
    ('GET', r'/editions/(?P<edition_id>[0-9]{1,19})', get_edition_response),
)
