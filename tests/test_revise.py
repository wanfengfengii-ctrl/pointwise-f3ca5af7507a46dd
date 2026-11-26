from tests.support import WorkbenchTest, origins, wav_bytes


class ReviseTests(WorkbenchTest):
    def test_stale_save(self):
        a, b, c = self.story_segments()
        r1 = self.proof([a, b])
        r2 = self.proof([b, a], r1['revision_id'])
        stale = self.api('POST', '/revisions', {
            'program_id': 'G', 'expected_revision_id': r1['revision_id'], 'segment_ids': [c],
        }, status=409)
        self.assertEqual(stale, {'error': 'stale_revision', 'current_revision_id': r2['revision_id']})
        self.assertEqual(self.stored('SELECT revision_id FROM drafts'), [(r2['revision_id'],)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM revisions'), [(2,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM revision_slots'), [(4,)])
        self.assertEqual(self.api('GET', f"/revisions/{r1['revision_id']}"), r1)
        self.assertEqual(self.api('GET', f"/revisions/{r2['revision_id']}"), r2)
        self.assert_audio(self.preview(r2['revision_id']), [20, 21, 22, 10, 11])
        r3 = self.proof([c], r2['revision_id'])
        self.assert_audio(self.preview(r3['revision_id']), [30, 31])

    def test_old_edition(self):
        a, b, c = self.story_segments()
        r1 = self.proof([c, b, a])['revision_id']
        order = self.voice_order(r1, [2])['order_id']
        first = self.submit(order, 'signed-voice', [[120, 121, 122]])
        edition = self.edition(r1)
        self.assert_audio(edition, [30, 31, 120, 121, 122, 10, 11])
        other = self.submit(order, 'replacement-voice', [[220, 221, 222]])
        r2 = self.proof([b, c, a], r1)['revision_id']
        self.service.restart()
        playback = self.api('GET', f"/editions/{edition['edition_id']}")
        self.assertEqual(playback, edition)
        self.assertEqual(wav_bytes(playback), wav_bytes(edition))
        self.assertEqual(origins(playback), [('source', c), ('voice', first['parts'][0]['part_id']), ('source', a)])
        older_preview = self.preview(r1)
        self.assert_audio(older_preview, [30, 31, 220, 221, 222, 10, 11])
        self.assertEqual(origins(older_preview), [('source', c), ('voice', other['parts'][0]['part_id']), ('source', a)])
        newer_preview = self.preview(r2)
        self.assert_audio(newer_preview, [20, 21, 22, 30, 31, 10, 11])
        self.assertEqual(origins(newer_preview), [('source', b), ('source', c), ('source', a)])
        new_order = self.voice_order(r2, [1])['order_id']
        new_receipt = self.submit(new_order, 'new-revision-voice', [[320, 321, 322]])
        latest = self.preview(r2)
        self.assert_audio(latest, [320, 321, 322, 30, 31, 10, 11])
        self.assertEqual(origins(latest), [('voice', new_receipt['parts'][0]['part_id']), ('source', c), ('source', a)])
        self.assertEqual(self.preview(r1), older_preview)
        self.assertEqual(self.api('GET', f"/editions/{edition['edition_id']}"), edition)

    def test_restart_preserves(self):
        source_id = self.source()['source_id']
        a = self.segment(source_id, 0, 2)['segment_id']
        b = self.segment(source_id, 2, 5)['segment_id']
        r1 = self.proof([a, b])['revision_id']
        order = self.voice_order(r1, [1])['order_id']
        first = self.submit(order, 'before-restart', [[110, 111]])
        edition = self.edition(r1)
        self.submit(order, 'kept-replacement', [[210, 211]])
        r2 = self.proof([b, a], r1)
        self.service.restart(sample_rate=16000)
        self.assertEqual(self.stored('SELECT program_id, sample_rate FROM programs'), [('G', 8000)])
        self.assertEqual(self.stored('SELECT revision_id FROM drafts'), [(r2['revision_id'],)])
        self.assertEqual(self.api('GET', f"/revisions/{r2['revision_id']}"), r2)
        self.assertEqual(self.submit(order, 'before-restart', [[110, 111]], 200), first)
        self.assert_audio(self.preview(r1), [210, 211, 20, 21, 22])
        self.assertEqual(self.api('GET', f"/editions/{edition['edition_id']}"), edition)
        self.api('POST', '/sources', {
            'program_id': 'G', 'description': '不同采样率',
            'pcm': {'sample_rate': 16000, 'channels': 1, 'encoding': 'pcm_s16le', 'data': 'AQACAA=='},
        }, status=400)
        self.source(samples=(1, 2))
        c = self.segment(source_id, 5, 7)['segment_id']
        r3 = self.proof([c], r2['revision_id'])['revision_id']
        self.assert_audio(self.preview(r3), [30, 31])

    def test_edition_lookup(self):
        self.api('GET', '/editions/9999', status=404)
        a, _, _ = self.story_segments()
        revision_id = self.proof([a])['revision_id']
        edition = self.edition(revision_id)
        ready = self.api('GET', f"/editions/{edition['edition_id']}")
        self.assertEqual(ready, edition)
        self.assertEqual(ready['revision_id'], revision_id)
        self.assertEqual(origins(ready), [('source', a)])
        self.assert_audio(ready, [10, 11])
