import sqlite3
from contextlib import closing

from cuts_fixture import LATE_PARTS, prepare
from tests.support import WorkbenchTest, origins, pcm, read_wave


class CutFixtureTest(WorkbenchTest):
    def setUp(self):
        super().setUp()
        self.r0, self.segments, self.order_id, self.edition = prepare(self.service)
        self.inverse = {value: key for key, value in self.segments.items()}
        # Map each base occurrence to its R0 name so same-segment B and E stay distinct.
        r0_proof = self.api('GET', f'/revisions/{self.r0}')
        base_ids = [row[0] for row in self.stored(f'''
            SELECT link.occurrence_id FROM revision_occurrences AS link
            WHERE link.revision_id = {self.r0} ORDER BY link.slot
        ''')]
        self.occ_name = dict(zip(base_ids, ('A', 'B', 'C', 'D', 'E'), strict=True))

    def cut(self, request_id, revision_id, first, last, status=201):
        return self.api('POST', '/cuts', {
            'request_id': request_id, 'revision_id': revision_id,
            'first_slot': first, 'last_slot': last,
        }, status)

    def insert(self, request_id, revision_id, anchor, segment_id, status=201):
        result = self.api('POST', '/inserts', {
            'request_id': request_id, 'revision_id': revision_id,
            'anchor_slot': anchor, 'segment_id': segment_id,
        }, status)
        if status == 201:
            self.occ_name[result['occurrence_id']] = self.inverse[segment_id]
        return result

    def withdraw(self, cut_id, request_id, status=201):
        return self.api('POST', f'/cuts/{cut_id}/withdraw',
                        {'request_id': request_id}, status)

    def take(self, request_id, parts, status=201):
        return self.api('POST', f'/voice-orders/{self.order_id}/takes', {
            'request_id': request_id, 'parts': [pcm(part) for part in parts],
        }, status)

    def current_names(self):
        mix = self.api('GET', '/mix/current')
        return [self.occ_name[entry['occurrence_id']] for entry in mix['timeline']], mix

    def test_accident_scenario_withdraw_jia_first(self):
        jia = self.cut('cut-jia', self.r0, 2, 3)
        yi = self.cut('cut-yi', self.r0, 3, 4)
        inserted = self.insert('insert-x', self.r0, 3, self.segments['X'])
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'X', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 9, 10, 3, 4])

        self.withdraw(jia['cut_id'], 'undo-jia')
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'B', 'X', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 3, 4, 9, 10, 3, 4])
        # Late dubbing arrives: B gets a new voice; C and D are still hidden.
        receipt = self.take('late-dub', LATE_PARTS)
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'B', 'X', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 31, 32, 9, 10, 3, 4])
        b_part = receipt['parts'][0]['part_id']
        self.assertEqual(origins(mix), [
            ('source', self.segments['A']), ('voice', b_part),
            ('source', self.segments['X']), ('source', self.segments['E']),
        ])
        # Reopen then withdraw Yi: C and D return with their own received dubs.
        self.service.restart()
        self.withdraw(yi['cut_id'], 'undo-yi')
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'B', 'X', 'C', 'D', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4])
        self.assertEqual([entry['source_kind'] for entry in mix['timeline']],
                         ['source', 'voice', 'source', 'voice', 'voice', 'source'])
        self.assertTrue(all(entry['occurrence_id'] for entry in mix['timeline']))
        # The insert stayed in front of C after C returned, with a stable occurrence id.
        x_entry = next(entry for entry in mix['timeline']
                       if entry['segment_id'] == self.segments['X'])
        self.assertEqual(x_entry['occurrence_id'], inserted['occurrence_id'])
        # The originally signed edition is untouched.
        playback = self.api('GET', f"/editions/{self.edition['edition_id']}")
        self.assertEqual(playback, self.edition)

    def test_accident_scenario_withdraw_yi_first(self):
        jia = self.cut('cut-jia', self.r0, 2, 3)
        yi = self.cut('cut-yi', self.r0, 3, 4)
        self.insert('insert-x', self.r0, 3, self.segments['X'])
        self.withdraw(yi['cut_id'], 'undo-yi')
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'X', 'D', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 9, 10, 7, 8, 3, 4])
        self.take('late-dub', LATE_PARTS)
        names, mix = self.current_names()
        self.assertEqual(read_wave(mix)[2], [1, 2, 9, 10, 71, 72, 3, 4])
        self.service.restart()
        self.withdraw(jia['cut_id'], 'undo-jia')
        names, mix = self.current_names()
        self.assertEqual(names, ['A', 'B', 'X', 'C', 'D', 'E'])
        self.assertEqual(read_wave(mix)[2], [1, 2, 31, 32, 9, 10, 51, 52, 71, 72, 3, 4])

    def test_cuts_overlap_and_independent_withdraw(self):
        jia = self.cut('jia', self.r0, 2, 3)
        yi = self.cut('yi', self.r0, 3, 4)
        names, _ = self.current_names()
        self.assertEqual(names, ['A', 'E'])
        # Withdrawing Yi only releases D; C stays hidden because Jia still covers it.
        self.withdraw(yi['cut_id'], 'undo-yi')
        names, _ = self.current_names()
        self.assertEqual(names, ['A', 'D', 'E'])
        self.withdraw(jia['cut_id'], 'undo-jia')
        names, _ = self.current_names()
        self.assertEqual(names, ['A', 'B', 'C', 'D', 'E'])

    def test_withdraw_replay_and_conflict(self):
        cut = self.cut('only', self.r0, 1, 1)
        body = {'request_id': 'undo'}
        first = self.api('POST', f"/cuts/{cut['cut_id']}/withdraw", body)
        replay = self.api('POST', f"/cuts/{cut['cut_id']}/withdraw", body, 200)
        self.assertEqual(replay, first)
        self.api('POST', f"/cuts/{cut['cut_id']}/withdraw",
                 {'request_id': 'undo-again'}, 409)

    def test_request_id_replay_and_conflicts(self):
        body = {'request_id': 'r1', 'revision_id': self.r0, 'first_slot': 1, 'last_slot': 1}
        first = self.api('POST', '/cuts', body)
        self.assertEqual(self.api('POST', '/cuts', body, 200), first)
        # Same request id, different parameters -> 409.
        self.api('POST', '/cuts', {**body, 'last_slot': 2}, 409)
        # Same request id reused on a different operation -> 409.
        self.api('POST', '/inserts', {
            'request_id': 'r1', 'revision_id': self.r0,
            'anchor_slot': 1, 'segment_id': self.segments['X'],
        }, 409)
        # Cut request ids are independent from take request ids.
        self.take('r1', LATE_PARTS)

    def test_invalid_cut_requests(self):
        for patch in (
            {'first_slot': 0}, {'last_slot': 2, 'first_slot': 3},
            {'last_slot': 99}, {'revision_id': 1.0}, {'first_slot': '1'},
            {'request_id': ''}, {'request_id': '   '},
        ):
            with self.subTest(patch=patch):
                self.api('POST', '/cuts', {
                    'request_id': 'bad', 'revision_id': self.r0,
                    'first_slot': 1, 'last_slot': 1, **patch,
                }, 400)
        # Unknown proof -> 404; extra field -> 400.
        self.api('POST', '/cuts', {
            'request_id': 'missing', 'revision_id': 9999, 'first_slot': 1, 'last_slot': 1,
        }, 404)
        self.api('POST', '/cuts', {
            'request_id': 'extra', 'revision_id': self.r0,
            'first_slot': 1, 'last_slot': 1, 'surprise': 1,
        }, 400)
        self.api('POST', '/cuts/does-not-exist/withdraw', {'request_id': 'w'}, 404)

    def test_cross_draft_references_conflict(self):
        self.cut('jia', self.r0, 2, 3)
        # An ordinary whole-proof save opens a new work draft.
        new_proof = self.api('POST', '/revisions', {
            'program_id': 'G', 'expected_revision_id': self.api(
                'GET', '/mix/current')['revision_id'],
            'segment_ids': [self.segments['A']],
        })
        new_revision = new_proof['revision_id']
        # Cuts may only reference proofs in the current work draft.
        self.api('POST', '/cuts', {
            'request_id': 'stale-cut', 'revision_id': self.r0,
            'first_slot': 1, 'last_slot': 1,
        }, 409)
        # A valid cut against the new draft still works.
        self.api('POST', '/cuts', {
            'request_id': 'fresh-cut', 'revision_id': new_revision,
            'first_slot': 1, 'last_slot': 1,
        })
        # Withdrawing a cut from the previous draft is rejected.
        old_cut_id = self.stored(
            "SELECT cut_id FROM cuts ORDER BY rowid LIMIT 1")[0][0]
        self.api('POST', f'/cuts/{old_cut_id}/withdraw',
                 {'request_id': 'old-undo'}, 409)

    def test_insert_ordering_and_hidden_anchor(self):
        first = self.insert('x1', self.r0, 3, self.segments['X'])
        second = self.insert('x2', self.r0, 3, self.segments['X'])
        names, _ = self.current_names()
        # Two direct inserts before C are ordered by acceptance.
        self.assertEqual(names, ['A', 'B', 'X', 'X', 'C', 'D', 'E'])
        self.cut('hide-c', self.r0, 3, 3)
        names, _ = self.current_names()
        # C hidden, but its inserts remain visible and keep their order.
        self.assertEqual(names, ['A', 'B', 'X', 'X', 'D', 'E'])
        # Both occurrence ids are stable opaque nonempty strings.
        self.assertTrue(first['occurrence_id'] and second['occurrence_id'])
        self.assertNotEqual(first['occurrence_id'], second['occurrence_id'])

    def test_proof_slot_renumbering_and_immutable_reads(self):
        created = self.cut('hide-b', self.r0, 2, 2)
        new_id = created['revision']['revision_id']
        self.assertEqual([slot['slot'] for slot in created['revision']['slots']],
                         [1, 2, 3, 4])
        # GET returns the stored proof exactly.
        self.assertEqual(self.api('GET', f'/revisions/{new_id}'), created['revision'])
        # The original proof is unchanged and still readable.
        original = self.api('GET', f'/revisions/{self.r0}')
        self.assertEqual(len(original['slots']), 5)

    def test_all_cut_returns_empty_timeline_and_zero_wav(self):
        self.cut('wipe', self.r0, 1, 5)
        mix = self.api('GET', '/mix/current')
        self.assertEqual(mix['timeline'], [])
        rate, frames, samples = read_wave(mix)
        self.assertEqual((rate, frames, samples), (8000, 0, []))
        # An empty proof cannot be signed as an edition.
        self.api('POST', '/editions',
                 {'revision_id': mix['revision_id']}, 400)

    def test_failed_take_leaves_nothing_and_malformed_batch_rejected(self):
        # Last part has only one frame but the target needs two -> whole order rejected.
        self.take('broken', [LATE_PARTS[0], LATE_PARTS[1], [71]], 400)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM takes'), [(0,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM receipts'), [(0,)])

    def test_ordinary_full_save_starts_fresh_occurrences(self):
        self.take('before-save', LATE_PARTS)
        current_id = self.api('GET', '/mix/current')['revision_id']
        saved = self.api('POST', '/revisions', {
            'program_id': 'G', 'expected_revision_id': current_id,
            'segment_ids': [self.segments[name] for name in ('A', 'B', 'C', 'D', 'E')],
        })
        mix = self.api('GET', f"/mix/{saved['revision_id']}")
        # The new draft starts from source audio; no voice carries over.
        self.assertEqual(read_wave(mix)[2], [1, 2, 3, 4, 5, 6, 7, 8, 3, 4])
        self.assertTrue(all(entry['source_kind'] == 'source' for entry in mix['timeline']))

    def test_edit_rollback_leaves_no_partial_change(self):
        before_revisions = self.stored('SELECT COUNT(*) FROM revisions')[0][0]
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('''
                CREATE TABLE tp (id INTEGER PRIMARY KEY);
                CREATE TABLE tc (pid INTEGER REFERENCES tp(id) DEFERRABLE INITIALLY DEFERRED);
                CREATE TRIGGER tg AFTER INSERT ON edit_requests
                BEGIN INSERT INTO tc VALUES (1); END;
            ''')
        self.api('POST', '/cuts', {
            'request_id': 'doomed', 'revision_id': self.r0,
            'first_slot': 1, 'last_slot': 1,
        }, 500)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM revisions')[0][0], before_revisions)
        self.assertEqual(self.stored('SELECT COUNT(*) FROM cuts'), [(0,)])
        self.assertEqual(self.stored('SELECT COUNT(*) FROM edit_requests'), [(0,)])
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('DROP TRIGGER tg; DROP TABLE tc; DROP TABLE tp;')
        # The request id can be handled for the first time once the fault clears.
        created = self.api('POST', '/cuts', {
            'request_id': 'doomed', 'revision_id': self.r0,
            'first_slot': 1, 'last_slot': 1,
        })
        self.assertTrue(created['cut_id'])
