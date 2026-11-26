import base64
import json
import tempfile
from pathlib import Path

from tests.support import RunningService, origins, read_wave, wav_bytes

SAMPLES = Path(__file__).resolve().parent / 'samples'


def require_equal(actual, expected):
    if actual != expected:
        raise AssertionError(f'expected {expected!r}, got {actual!r}')


def run(service, sample, signed_wav):
    def call(method, path, body=None):
        status, payload = service.request(method, path, body)
        if status != (201 if method == 'POST' else 200):
            raise RuntimeError(f'{method} {path} returned {status}: {payload!r}')
        return payload

    source = call('POST', '/sources', sample['source'])
    require_equal(source['frame_count'], 7)
    slices = [call('POST', '/segments', {
        'source_id': source['source_id'], 'start_frame': start, 'end_frame': end,
    }) for start, end in sample['ranges']]
    require_equal([item['frame_count'] for item in slices], [2, 3, 2])
    a, b, c = (item['segment_id'] for item in slices)
    proof = call('POST', '/revisions', {
        'program_id': 'G', 'expected_revision_id': None, 'segment_ids': [c, b, a],
    })
    r1 = proof['revision_id']
    require_equal(call('GET', f'/revisions/{r1}'), proof)
    require_equal([entry['segment_id'] for entry in proof['slots']], [c, b, a])
    order = call('POST', '/voice-orders', {'revision_id': r1, 'slots': [2]})
    require_equal(order['targets'], [{'position': 1, 'slot': 2, 'frame_count': 3}])
    take_path = f"/voice-orders/{order['order_id']}/takes"
    receipt = call('POST', take_path, {'request_id': 'hall-narration', 'parts': [sample['voice']]})
    preview = call('GET', f'/mix/{r1}')
    edition = call('POST', '/editions', {'revision_id': r1})
    edition_path = f"/editions/{edition['edition_id']}"
    first_playback = call('GET', edition_path)
    expected_frames = [30, 31, 120, 121, 122, 10, 11]
    expected_origins = [('source', c), ('voice', receipt['parts'][0]['part_id']), ('source', a)]
    require_equal(read_wave(preview), (8000, 7, expected_frames))
    require_equal(origins(preview), expected_origins)
    require_equal([(part['start_frame'], part['end_frame']) for part in preview['timeline']],
                  [(0, 2), (2, 5), (5, 7)])
    require_equal(first_playback, {**preview, 'edition_id': edition['edition_id']})
    require_equal(first_playback, edition)
    require_equal(wav_bytes(first_playback), signed_wav)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v6',
        'input': {'recording': sample['source']['pcm'], 'ranges': sample['ranges'],
                  'ordered_segments': [c, b, a], 'take': sample['voice']},
        'expected': {'frames': expected_frames, 'origins': expected_origins},
        'actual': {'frames': read_wave(preview)[2], 'origins': origins(preview)},
        'downstream_expected': expected_frames,
        'downstream_actual': read_wave(first_playback)[2],
        'code_paths': ['source/segments.py', 'mix/selection.py', 'mix/timeline.py', 'release/publish.py'],
        'oracle': '手算 C、实收 B、A 三段的拼接及区间，再用标准库解码 WAV 并比较固定成品。',
    }, ensure_ascii=False))
    replacement = call('POST', take_path, {'request_id': 'hall-correction', 'parts': [sample['replacement']]})
    r2 = call('POST', '/revisions', {
        'program_id': 'G', 'expected_revision_id': r1, 'segment_ids': [b, c, a],
    })['revision_id']
    service.restart(sample_rate=16000)
    old_mix = call('GET', f'/mix/{r1}')
    new_mix = call('GET', f'/mix/{r2}')
    playback = call('GET', edition_path)
    old_mix_frames = [30, 31, 220, 221, 222, 10, 11]
    new_mix_frames = [20, 21, 22, 30, 31, 10, 11]
    require_equal(read_wave(old_mix), (8000, 7, old_mix_frames))
    require_equal(read_wave(new_mix), (8000, 7, new_mix_frames))
    require_equal(origins(old_mix), [('source', c), ('voice', replacement['parts'][0]['part_id']), ('source', a)])
    require_equal(origins(new_mix), [('source', b), ('source', c), ('source', a)])
    require_equal(playback, first_playback)
    require_equal(wav_bytes(playback), signed_wav)
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'v7',
        'input': {'edition_id': edition['edition_id'], 'revision_ids': [r1, r2],
                  'replacement': sample['replacement'], 'new_order': [b, c, a]},
        'expected': {'first_revision': old_mix_frames, 'second_revision': new_mix_frames},
        'actual': {'first_revision': read_wave(old_mix)[2], 'second_revision': read_wave(new_mix)[2]},
        'downstream_expected': expected_frames,
        'downstream_actual': read_wave(playback)[2],
        'code_paths': ['dubbing/takes.py', 'edit/revisions.py', 'mix/preview.py', 'release/playback.py'],
        'oracle': '两份校样手算选音，展厅结果与重开前的原出处及固定 WAV 字节比较。',
    }, ensure_ascii=False))


def main():
    sample = json.loads((SAMPLES / 'recording.json').read_text(encoding='utf-8'))
    edition_b64 = (SAMPLES / 'edition.wav.b64').read_text(encoding='ascii').strip()
    signed_wav = base64.b64decode(edition_b64, validate=True)
    with tempfile.TemporaryDirectory() as temporary:
        with RunningService(Path(temporary) / 'workbench.sqlite3') as service:
            run(service, sample, signed_wav)


if __name__ == '__main__':
    main()
