from release.server import initialize_database
from source.programs import ProgramSpec
from tests.support import WorkbenchTest, origins, pcm


class PrepareTests(WorkbenchTest):
    def test_ordered_slices(self):
        source = self.source()
        self.assertEqual(source['frame_count'], 7)
        a = self.segment(source['source_id'], 0, 2)
        b = self.segment(source['source_id'], 2, 5)
        self.assertEqual((a['start_frame'], a['end_frame'], a['frame_count']), (0, 2, 2))
        self.assertEqual((b['start_frame'], b['end_frame'], b['frame_count']), (2, 5, 3))
        proof = self.proof([b['segment_id'], a['segment_id']])
        revision_id = proof['revision_id']
        self.assertEqual(proof['slots'], [
            {'slot': 1, 'segment_id': b['segment_id'], 'frame_count': 3},
            {'slot': 2, 'segment_id': a['segment_id'], 'frame_count': 2},
        ])
        self.assertEqual(self.api('GET', f'/revisions/{revision_id}'), proof)
        preview = self.preview(revision_id)
        self.assert_audio(preview, [20, 21, 22, 10, 11])
        self.assertEqual(origins(preview), [('source', b['segment_id']), ('source', a['segment_id'])])

    def test_slice_out_of_range(self):
        source_id = self.source()['source_id']
        a = self.segment(source_id, 0, 2)
        error = self.api('POST', '/segments', {
            'source_id': source_id, 'start_frame': 5, 'end_frame': 8,
        }, status=400)
        self.assertEqual(error['error'], 'invalid_frame_range')
        self.assertEqual(self.stored('SELECT COUNT(*) FROM segments'), [(1,)])
        c = self.segment(source_id, 5, 7)
        proof = self.proof([a['segment_id'], c['segment_id']])
        self.assert_audio(self.preview(proof['revision_id']), [10, 11, 30, 31])

    def test_pcm_contract(self):
        valid = pcm([-32768, 0, 32767])
        body = {'program_id': 'G', 'description': '上下限', 'pcm': valid}
        self.api('POST', '/sources', {**body, 'program_id': 'missing'}, status=404)
        for change in (
            {'sample_rate': 16000}, {'sample_rate': 8000.0}, {'channels': 2}, {'channels': True},
            {'encoding': 'pcm_s16be'}, {'data': ''}, {'data': '!?'}, {'data': 'AA=='},
        ):
            with self.subTest(change=change):
                self.api('POST', '/sources', {**body, 'pcm': {**valid, **change}}, status=400)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM sources'), [(0,)])
        source = self.api('POST', '/sources', body)
        segment = self.segment(source['source_id'], 0, 3)
        proof = self.proof([segment['segment_id']])
        self.assert_audio(self.preview(proof['revision_id']), [-32768, 0, 32767])

    def test_invalid_ranges(self):
        source_id = self.source()['source_id']
        for start, end in ((2, 2), (4, 3), (-1, 2), (0.0, 2), (False, 2), (0, '2')):
            with self.subTest(start=start, end=end):
                self.api('POST', '/segments', {
                    'source_id': source_id, 'start_frame': start, 'end_frame': end,
                }, status=400)
        self.api('POST', '/segments', {'source_id': 9999, 'start_frame': 0, 'end_frame': 1}, status=404)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM segments'), [(0,)])

    def test_duplicate_slots(self):
        a, _, _ = self.story_segments()
        proof = self.proof([a, a])
        self.assertEqual(proof['slots'], [
            {'slot': 1, 'segment_id': a, 'frame_count': 2},
            {'slot': 2, 'segment_id': a, 'frame_count': 2},
        ])
        self.assertEqual(self.api('GET', f"/revisions/{proof['revision_id']}"), proof)
        self.assert_audio(self.preview(proof['revision_id']), [10, 11, 10, 11])

    def test_revision_errors(self):
        a, _, _ = self.story_segments()
        initialize_database(self.database, (ProgramSpec('H', 16000),))
        foreign = self.source(program='H', rate=16000)
        other = self.segment(foreign['source_id'], 0, 2)['segment_id']
        body = {'program_id': 'G', 'expected_revision_id': None, 'segment_ids': [a]}
        for patch, status in (
            ({'segment_ids': []}, 400), ({'segment_ids': [True]}, 400),
            ({'program_id': 'missing'}, 404), ({'segment_ids': [9999]}, 404),
            ({'segment_ids': [a, other]}, 404),
        ):
            with self.subTest(patch=patch):
                self.api('POST', '/revisions', {**body, **patch}, status=status)
        self.api('GET', '/revisions/9999', status=404)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM revisions'), [(0,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM drafts'), [(0,)])
        proof = self.api('POST', '/revisions', body)
        self.assertEqual(proof['program_id'], 'G')
