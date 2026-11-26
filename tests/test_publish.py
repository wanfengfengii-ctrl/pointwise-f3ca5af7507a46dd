from tests.support import WorkbenchTest, origins


class PublishTests(WorkbenchTest):
    def test_pcm_preview(self):
        a, b, c = self.story_segments()
        revision_id = self.proof([c, b, a])['revision_id']
        order_id = self.voice_order(revision_id, [2])['order_id']
        take = self.submit(order_id, 'middle', [[120, 121, 122]])
        voiced = take['parts'][0]['part_id']
        preview = self.preview(revision_id)
        self.assert_audio(preview, [30, 31, 120, 121, 122, 10, 11])
        self.assertEqual(preview['revision_id'], revision_id)
        self.assertEqual(preview['program_id'], 'G')
        self.assertEqual(preview['timeline'], [
            {'slot': 1, 'segment_id': c, 'frame_count': 2, 'start_frame': 0, 'end_frame': 2,
             'source_kind': 'source', 'source_id': c},
            {'slot': 2, 'segment_id': b, 'frame_count': 3, 'start_frame': 2, 'end_frame': 5,
             'source_kind': 'voice', 'source_id': voiced},
            {'slot': 3, 'segment_id': a, 'frame_count': 2, 'start_frame': 5, 'end_frame': 7,
             'source_kind': 'source', 'source_id': a},
        ])
        edition = self.edition(revision_id)
        self.assertEqual(edition, {**preview, 'edition_id': edition['edition_id']})

    def test_latest_per_slot(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        first_order = self.voice_order(revision_id, [1, 2])['order_id']
        first = self.submit(first_order, 'initial-pair', [[110, 111], [120, 121, 122]])
        inner_order = self.voice_order(revision_id, [1])['order_id']
        newer = self.submit(inner_order, 'replace-first', [[210, 211]])
        expected_origins = [('voice', newer['parts'][0]['part_id']), ('voice', first['parts'][1]['part_id'])]
        for product in (self.preview(revision_id), self.edition(revision_id)):
            self.assert_audio(product, [210, 211, 120, 121, 122])
            self.assertEqual(origins(product), expected_origins)

    def test_repeated_source(self):
        a, _, _ = self.story_segments()
        revision_id = self.proof([a, a])['revision_id']
        order_id = self.voice_order(revision_id, [2])['order_id']
        voiced = self.submit(order_id, 'second-use', [[230, 231]])['parts'][0]['part_id']
        for product in (self.preview(revision_id), self.edition(revision_id)):
            self.assert_audio(product, [10, 11, 230, 231])
            self.assertEqual(origins(product), [('source', a), ('voice', voiced)])
            self.assertEqual([entry['slot'] for entry in product['timeline']], [1, 2])

    def test_publish_reselect(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [1])['order_id']
        first = self.submit(order_id, 'before-preview', [[110, 111]])
        preview = self.preview(revision_id)
        self.assert_audio(preview, [110, 111, 20, 21, 22])
        self.assertEqual(origins(preview), [('voice', first['parts'][0]['part_id']), ('source', b)])
        second = self.submit(order_id, 'before-publish', [[210, 211]])
        edition = self.edition(revision_id)
        self.assert_audio(edition, [210, 211, 20, 21, 22])
        self.assertEqual(origins(edition), [('voice', second['parts'][0]['part_id']), ('source', b)])
        self.edition(9999, 404)
        self.api('GET', '/mix/9999', status=404)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(1,)])

    def test_failed_publish(self):
        a, b, _ = self.story_segments()
        revision_id = self.proof([a, b])['revision_id']
        order_id = self.voice_order(revision_id, [2])['order_id']
        voiced = self.submit(order_id, 'publishable', [[120, 121, 122]])['parts'][0]['part_id']
        preview = self.preview(revision_id)
        with self.fail_commit_on('editions'):
            failed = self.edition(revision_id, 500)
            self.assertEqual(failed, {'error': 'database_failure'})
            self.api('GET', '/editions/1', status=404)
            self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(0,)])
            self.assertEqual(self.stored('SELECT COUNT(*) FROM test_commit_child'), [(0,)])
        edition = self.edition(revision_id)
        fetched = self.api('GET', f"/editions/{edition['edition_id']}")
        self.assertEqual(fetched, {**preview, 'edition_id': edition['edition_id']})
        self.assertEqual(fetched, edition)
        self.assert_audio(fetched, [10, 11, 120, 121, 122])
        self.assertEqual(origins(fetched), [('source', a), ('voice', voiced)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM editions'), [(1,)])
