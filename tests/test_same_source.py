from tests.support import WorkbenchTest, origins, pcm, read_wave


class SameSourceOccurrenceTest(WorkbenchTest):
    def _setup_p_p(self):
        source = self.api('POST', '/sources', {
            'program_id': 'G', 'description': '同源双现',
            'pcm': pcm([100]),
        })
        p_segment = self.api('POST', '/segments', {
            'source_id': source['source_id'], 'start_frame': 0, 'end_frame': 1,
        })['segment_id']
        proof = self.proof([p_segment, p_segment])
        revision_id = proof['revision_id']
        # Separate orders for the front and back occurrence.
        front_order = self.voice_order(revision_id, [1])['order_id']
        back_order = self.voice_order(revision_id, [2])['order_id']
        self.submit(front_order, 'front-11', [[11]])
        self.submit(back_order, 'back-22', [[22]])
        return revision_id, p_segment, front_order, back_order

    def test_each_occurrence_keeps_its_own_take(self):
        revision_id, p_segment, _, _ = self._setup_p_p()
        mix = self.preview(revision_id)
        self.assertEqual(read_wave(mix)[2], [11, 22])
        self.assertEqual(origins(mix), [
            ('voice', mix['timeline'][0]['source_id']),
            ('voice', mix['timeline'][1]['source_id']),
        ])
        self.assertNotEqual(mix['timeline'][0]['source_id'], mix['timeline'][1]['source_id'])

    def test_cutting_one_plays_the_other(self):
        revision_id, p_segment, _, _ = self._setup_p_p()
        # Cut the first occurrence -> only the back one plays, with its own take (22).
        first_cut = self.api('POST', '/cuts', {
            'request_id': 'cut-first', 'revision_id': revision_id,
            'first_slot': 1, 'last_slot': 1,
        })
        mix = self.api('GET', '/mix/current')
        self.assertEqual(read_wave(mix)[2], [22])
        self.assertEqual(origins(mix)[0], ('voice', mix['timeline'][0]['source_id']))
        # Cut the second (on the original proof) -> only the front one plays (11).
        self.api('POST', '/cuts', {
            'request_id': 'cut-second', 'revision_id': revision_id,
            'first_slot': 2, 'last_slot': 2,
        })
        # Both now hidden -> empty.
        empty = self.api('GET', '/mix/current')
        self.assertEqual(read_wave(empty)[2], [])
        # Withdraw the second cut -> front still hidden, back returns (22).
        # Re-establish by withdrawing the first cut instead to hear the front (11).
        self.api('POST', f"/cuts/{first_cut['cut_id']}/withdraw",
                 {'request_id': 'undo-first'})
        # First occurrence returns; second is still hidden by cut-second -> play 11.
        mix = self.api('GET', '/mix/current')
        self.assertEqual(read_wave(mix)[2], [11])

    def test_alternating_takes_and_replay_older_receipt(self):
        revision_id, p_segment, front_order, back_order = self._setup_p_p()
        # Record a newer take for the back occurrence from a later proof after a cut/restore cycle.
        cut = self.api('POST', '/cuts', {
            'request_id': 'hide-back', 'revision_id': revision_id,
            'first_slot': 2, 'last_slot': 2,
        })
        self.api('POST', f"/cuts/{cut['cut_id']}/withdraw", {'request_id': 'restore-back'})
        # The back occurrence accepts a replacement take after it returns.
        newer = self.submit(back_order, 'back-33', [[33]])
        mix = self.api('GET', '/mix/current')
        # Current mix chooses the later successful take for the back occurrence.
        self.assertEqual(read_wave(mix)[2], [11, 33])
        self.assertEqual(origins(mix)[1], ('voice', newer['parts'][0]['part_id']))
        # Replaying the older first receipt returns the original take unchanged.
        older = self.submit(back_order, 'back-22', [[22]], 200)
        self.assertEqual(older['parts'][0]['part_id'],
                         self.api('POST', f'/voice-orders/{back_order}/takes', {
                             'request_id': 'back-22', 'parts': [pcm([22])],
                         }, 200)['parts'][0]['part_id'])
        # Replay does not change recency: the newer take (33) still wins.
        mix = self.api('GET', '/mix/current')
        self.assertEqual(read_wave(mix)[2], [11, 33])

    def test_identical_full_save_starts_fresh_audio(self):
        revision_id, p_segment, _, _ = self._setup_p_p()
        current_id = self.api('GET', '/mix/current')['revision_id']
        saved = self.api('POST', '/revisions', {
            'program_id': 'G', 'expected_revision_id': current_id,
            'segment_ids': [p_segment, p_segment],
        })
        mix = self.api('GET', f"/mix/{saved['revision_id']}")
        # New work draft: both occurrences fall back to source audio.
        self.assertEqual(read_wave(mix)[2], [100, 100])
        self.assertTrue(all(entry['source_kind'] == 'source' for entry in mix['timeline']))
