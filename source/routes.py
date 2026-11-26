from source.catalog import UnknownSource, register_source
from source.pcm import PCMFormatError, decode_pcm
from source.programs import UnknownProgram, get_program
from source.segments import InvalidFrameRange, create_segment


def post_sources(db, body):
    program_id = body.get('program_id')
    if not isinstance(program_id, str) or not program_id:
        return 400, {'error': 'invalid_program_id'}
    try:
        spec = get_program(db, program_id)
        pcm = decode_pcm(body.get('pcm'), spec)
        source = register_source(db, spec, body.get('description'), pcm)
    except UnknownProgram:
        return 404, {'error': 'unknown_program'}
    except PCMFormatError as exc:
        return 400, {'error': 'invalid_source', 'detail': str(exc)}
    return 201, {
        'source_id': source.source_id,
        'program_id': source.program_id,
        'description': source.description,
        'frame_count': source.frame_count,
    }


def post_segments(db, body):
    source_id = body.get('source_id')
    if type(source_id) is not int or source_id < 1:
        return 400, {'error': 'invalid_source_id'}
    try:
        segment = create_segment(db, source_id, body.get('start_frame'), body.get('end_frame'))
    except UnknownSource:
        return 404, {'error': 'unknown_source'}
    except InvalidFrameRange as exc:
        return 400, {'error': 'invalid_frame_range', 'detail': str(exc)}
    return 201, {
        'segment_id': segment.segment_id,
        'source_id': segment.source_id,
        'program_id': segment.program_id,
        'start_frame': segment.start_frame,
        'end_frame': segment.end_frame,
        'frame_count': segment.frame_count,
    }


SOURCE_ROUTES = (
    ('POST', r'/sources', post_sources),
    ('POST', r'/segments', post_segments),
)
