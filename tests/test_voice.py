from tests.support import WorkbenchTest, origins, pcm


class VoiceTests(WorkbenchTest):
    def test_fixed_order(self):
        a, b, _ = self.story_segments()
        r1 = self.proof([a, b])['revision_id']
        order = self.voice_order(r1, [2, 1])
        self.assertEqual(order['targets'], [
            {'position': 1, 'slot': 2, 'frame_count': 3},
            {'position': 2, 'slot': 1, 'frame_count': 2},
        ])
        r2 = self.proof([b, a], r1)['revision_id']
        order_id = order['order_id']
        receipt = self.submit(order_id, 'fixed', [[120, 121, 122], [110, 111]])
        self.assertEqual(receipt['revision_id'], r1)
        self.assertEqual([(p['position'], p['slot'], p['frame_count']) for p in receipt['parts']],
                         [(1, 2, 3), (2, 1, 2)])
        self.assertEqual(self.submit(order_id, 'fixed', [[120, 121, 122], [110, 111]], 200), receipt)
        mixed = self.preview(r1)
        self.assert_audio(mixed, [110, 111, 120, 121, 122])
        self.assertEqual(origins(mixed), [('voice', receipt['parts'][1]['part_id']),
                                         ('voice', receipt['parts'][0]['part_id'])])
        current = self.preview(r2)
        self.assert_audio(current, [20, 21, 22, 10, 11])
        self.assertEqual(origins(current), [('source', b), ('source', a)])

    def test_order_targets(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        for slots in ([], [1, 1], [True], [3], [0], '1'):
            with self.subTest(slots=slots):
                self.api('POST', '/voice-orders', {'revision_id': revision_id, 'slots': slots}, status=400)
        self.api('POST', '/voice-orders', {'revision_id': 9999, 'slots': [1]}, status=404)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM voice_orders'), [(0,)])
        order = self.voice_order(revision_id, [2])
        self.assertEqual(order['sample_rate'], 8000)
        self.assertEqual(order['targets'], [{'position': 1, 'slot': 2, 'frame_count': 3}])

    def test_changed_request(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [1, 2])['order_id']
        other_id = self.voice_order(revision_id, [1, 2])['order_id']
        receipt = self.submit(order_id, 'known', [[110, 111], [120, 121, 122]])
        self.submit(order_id, 'known', [[112, 113], [120, 121, 122]], 409)
        self.submit(order_id, 'known', [[120, 121, 122], [110, 111]], 409)
        self.submit(other_id, 'known', [[110, 111], [120, 121, 122]], 409)
        self.submit(9999, 'known', [[110, 111], [120, 121, 122]], 404)
        self.api('POST', f'/voice-orders/{order_id}/takes', {
            'request_id': 'known', 'parts': [pcm([110, 111], 16000), pcm([120, 121, 122])],
        }, status=409)
        self.assertEqual(self.submit(order_id, 'known', [[110, 111], [120, 121, 122]], 200), receipt)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM takes'), [(1,)])
        self.assert_audio(self.preview(revision_id), [110, 111, 120, 121, 122])

    def test_replay_keeps_latest(self):
        a, _, _ = self.story_segments()
        revision_id = self.proof([a])['revision_id']
        order_id = self.voice_order(revision_id, [1])['order_id']
        first = self.submit(order_id, 'first', [[110, 111]])
        second = self.submit(order_id, 'second', [[210, 211]])
        self.assertGreater(second['take_id'], first['take_id'])
        self.assertEqual(self.submit(order_id, 'first', [[110, 111]], 200), first)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM takes'), [(2,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM receipts'), [(2,)])
        mixed = self.preview(revision_id)
        self.assert_audio(mixed, [210, 211])
        self.assertEqual(origins(mixed), [('voice', second['parts'][0]['part_id'])])

    def test_atomic_take(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [1, 2])['order_id']
        self.submit(order_id, 'repair-last', [[110, 111], [120, 121]], 400)
        mixed = self.preview(revision_id)
        self.assert_audio(mixed, [10, 11, 20, 21, 22])
        self.assertEqual(origins(mixed), [('source', a), ('source', b)])
        for table in ('takes', 'take_parts', 'receipts'):
            self.assertEqual(self.stored(f'SELECT COUNT(*) FROM {table}'), [(0,)])
        accepted = self.submit(order_id, 'repair-last', [[110, 111], [120, 121, 122]])
        self.assertEqual(len(accepted['parts']), 2)
        self.assert_audio(self.preview(revision_id), [110, 111, 120, 121, 122])

    def test_invalid_batch(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [1, 2])['order_id']
        prior = self.submit(order_id, 'prior', [[110, 111], [120, 121, 122]])
        for parts in (
            [], [pcm([310, 311])], [pcm([310, 311]), pcm([320, 321, 322], 16000)],
            [pcm([310, 311]), {**pcm([320, 321, 322]), 'channels': 2}],
        ):
            self.api('POST', f'/voice-orders/{order_id}/takes', {
                'request_id': 'invalid', 'parts': parts,
            }, status=400)
        mixed = self.preview(revision_id)
        self.assert_audio(mixed, [110, 111, 120, 121, 122])
        self.assertEqual(origins(mixed), [('voice', part['part_id']) for part in prior['parts']])
        self.assertEqual(self.stored('SELECT request_id FROM receipts'), [('prior',)])

    def test_commit_rollback(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [2, 1])['order_id']
        parts = [[120, 121, 122], [110, 111]]
        before = self.preview(revision_id)
        with self.fail_commit_on('receipts'):
            error = self.submit(order_id, 'retryable', parts, 500)
            self.assertEqual(error, {'error': 'database_failure'})
            for table in ('takes', 'take_parts', 'receipts', 'test_commit_child'):
                self.assertEqual(self.stored(f'SELECT COUNT(*) FROM {table}'), [(0,)])
            self.assertEqual(self.preview(revision_id), before)
        receipt = self.submit(order_id, 'retryable', parts)
        self.assertEqual(self.submit(order_id, 'retryable', parts, 200), receipt)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM takes'), [(1,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM take_parts'), [(2,)])
        mixed = self.preview(revision_id)
        self.assert_audio(mixed, [110, 111, 120, 121, 122])
        self.assertEqual(origins(mixed), [('voice', receipt['parts'][1]['part_id']),
                                         ('voice', receipt['parts'][0]['part_id'])])
