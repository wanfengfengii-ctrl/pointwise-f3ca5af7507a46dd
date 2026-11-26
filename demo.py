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


def run_cut_demo(service):
    """Show the two withdrawal orders, takes landing between them, and the final current mix."""
    from cuts_fixture import LATE_PARTS, prepare
    from tests.support import pcm

    def call(method, path, body=None, status=None):
        expected = status if status is not None else (201 if method == 'POST' else 200)
        actual, payload = service.request(method, path, body)
        if actual != expected:
            raise RuntimeError(f'{method} {path} returned {actual}: {payload!r}')
        return payload

    r0, segments, order_id, edition = prepare(service)
    base = call('GET', f'/revisions/{r0}')
    occurrence_names = {}
    r0_occurrences = _revision_occurrence_ids(service.database, r0)
    for occurrence_id, name in zip(r0_occurrences, ('A', 'B', 'C', 'D', 'E'), strict=True):
        occurrence_names[occurrence_id] = name

    jia = call('POST', '/cuts', {
        'request_id': 'demo-cut-jia', 'revision_id': r0, 'first_slot': 2, 'last_slot': 3,
    })
    yi = call('POST', '/cuts', {
        'request_id': 'demo-cut-yi', 'revision_id': r0, 'first_slot': 3, 'last_slot': 4,
    })
    inserted = call('POST', '/inserts', {
        'request_id': 'demo-insert-x', 'revision_id': r0,
        'anchor_slot': 3, 'segment_id': segments['X'],
    })
    occurrence_names[inserted['occurrence_id']] = 'X'

    def names(mix):
        return [occurrence_names[entry['occurrence_id']] for entry in mix['timeline']]

    after_edits = call('GET', '/mix/current')
    # Withdraw Jia first; the late dubbing then arrives while C and D are still hidden.
    call('POST', f"/cuts/{jia['cut_id']}/withdraw", {'request_id': 'demo-undo-jia'})
    before_take = call('GET', '/mix/current')
    receipt = call('POST', f'/voice-orders/{order_id}/takes', {
        'request_id': 'demo-late-dub', 'parts': [pcm(part) for part in LATE_PARTS],
    })
    voiced = call('GET', '/mix/current')
    service.restart()
    call('POST', f"/cuts/{yi['cut_id']}/withdraw", {'request_id': 'demo-undo-yi'})
    restored = call('GET', '/mix/current')
    playback = call('GET', f"/editions/{edition['edition_id']}")

    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'cuts-withdraw-jia-first',
        'input': {
            'proof': [entry['segment_id'] for entry in base['slots']],
            'cuts': {'jia': [2, 3], 'yi': [3, 4]}, 'insert': {'anchor_slot': 3, 'segment': 'X'},
            'late_parts': [list(part) for part in LATE_PARTS],
        },
        'expected': {
            'after_edits': ['A', 'X', 'E'],
            'after_withdraw_jia': ['A', 'B', 'X', 'E'],
            'after_late_dub_frames': [1, 2, 31, 32, 9, 10, 3, 4],
            'restored': ['A', 'B', 'X', 'C', 'D', 'E'],
            'restored_frames': [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4],
        },
        'actual': {
            'after_edits': names(after_edits),
            'after_withdraw_jia': names(before_take),
            'after_late_dub_frames': read_wave(voiced)[2],
            'restored': names(restored),
            'restored_frames': read_wave(restored)[2],
            'restored_origins': origins(restored),
            'signed_edition_frames': read_wave(playback)[2],
            'receipt_parts': receipt['parts'],
        },
        'code_paths': ['edit/edits.py', 'edit/workspace.py', 'mix/selection.py', 'dubbing/takes.py'],
        'oracle': '按 CUTS.md 事故样例手算两种撤回顺序的可见出现、逐段出处与 PCM 帧，迟到配音按原出现恢复。',
    }, ensure_ascii=False))
    require_equal(names(restored), ['A', 'B', 'X', 'C', 'D', 'E'])
    require_equal(read_wave(restored)[2], [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4])
    require_equal(read_wave(playback)[2], [1, 2, 3, 4, 5, 6, 7, 8, 3, 4])


def run_cut_demo_yi_first(service):
    """The opposite withdrawal order: withdraw Yi, take delivery, then withdraw Jia."""
    from cuts_fixture import LATE_PARTS, prepare
    from tests.support import pcm

    def call(method, path, body=None, status=None):
        expected = status if status is not None else (201 if method == 'POST' else 200)
        actual, payload = service.request(method, path, body)
        if actual != expected:
            raise RuntimeError(f'{method} {path} returned {actual}: {payload!r}')
        return payload

    r0, segments, order_id, _ = prepare(service)
    occurrence_names = {}
    for occurrence_id, name in zip(_revision_occurrence_ids(service.database, r0),
                                   ('A', 'B', 'C', 'D', 'E'), strict=True):
        occurrence_names[occurrence_id] = name
    jia = call('POST', '/cuts', {
        'request_id': 'yf-cut-jia', 'revision_id': r0, 'first_slot': 2, 'last_slot': 3,
    })
    yi = call('POST', '/cuts', {
        'request_id': 'yf-cut-yi', 'revision_id': r0, 'first_slot': 3, 'last_slot': 4,
    })
    inserted = call('POST', '/inserts', {
        'request_id': 'yf-insert-x', 'revision_id': r0,
        'anchor_slot': 3, 'segment_id': segments['X'],
    })
    occurrence_names[inserted['occurrence_id']] = 'X'

    def names(mix):
        return [occurrence_names[entry['occurrence_id']] for entry in mix['timeline']]

    call('POST', f"/cuts/{yi['cut_id']}/withdraw", {'request_id': 'yf-undo-yi'})
    before_take = call('GET', '/mix/current')
    call('POST', f'/voice-orders/{order_id}/takes', {
        'request_id': 'yf-late-dub', 'parts': [pcm(part) for part in LATE_PARTS],
    })
    voiced = call('GET', '/mix/current')
    service.restart()
    call('POST', f"/cuts/{jia['cut_id']}/withdraw", {'request_id': 'yf-undo-jia'})
    restored = call('GET', '/mix/current')
    print('POINTWISE_SCENARIO ' + json.dumps({
        'case_id': 'cuts-withdraw-yi-first',
        'expected': {
            'after_withdraw_yi': ['A', 'X', 'D', 'E'],
            'after_late_dub_frames': [1, 2, 9, 10, 71, 72, 3, 4],
            'restored_frames': [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4],
        },
        'actual': {
            'after_withdraw_yi': names(before_take),
            'after_late_dub_frames': read_wave(voiced)[2],
            'restored': names(restored),
            'restored_frames': read_wave(restored)[2],
        },
        'oracle': '先撤乙只让 D 复归，交件后 D 用新配音；再撤甲 B、C 才用各自实收。',
    }, ensure_ascii=False))
    require_equal(names(before_take), ['A', 'X', 'D', 'E'])
    require_equal(read_wave(voiced)[2], [1, 2, 9, 10, 71, 72, 3, 4])
    require_equal(read_wave(restored)[2], [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4])


def _revision_occurrence_ids(database, revision_id):
    import sqlite3
    with sqlite3.connect(database) as db:
        return [row[0] for row in db.execute('''
            SELECT occurrence_id FROM revision_occurrences
            WHERE revision_id = ? ORDER BY slot
        ''', (revision_id,))]


def main():
    sample = json.loads((SAMPLES / 'recording.json').read_text(encoding='utf-8'))
    edition_b64 = (SAMPLES / 'edition.wav.b64').read_text(encoding='ascii').strip()
    signed_wav = base64.b64decode(edition_b64, validate=True)
    with tempfile.TemporaryDirectory() as temporary:
        with RunningService(Path(temporary) / 'workbench.sqlite3') as service:
            run(service, sample, signed_wav)
        with RunningService(Path(temporary) / 'cut_workbench.sqlite3') as service:
            run_cut_demo(service)
        with RunningService(Path(temporary) / 'cut_yi_first.sqlite3') as service:
            run_cut_demo_yi_first(service)


if __name__ == '__main__':
    main()
