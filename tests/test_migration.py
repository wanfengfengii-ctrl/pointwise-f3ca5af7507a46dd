import base64
import sqlite3
import struct
from contextlib import closing
from pathlib import Path

from tests.support import WorkbenchTest, read_wave


LEGACY_SCHEMA = '''
    CREATE TABLE programs (program_id TEXT PRIMARY KEY, sample_rate INTEGER NOT NULL);
    CREATE TABLE sources (source_id INTEGER PRIMARY KEY, program_id TEXT NOT NULL,
        description TEXT NOT NULL, frame_count INTEGER NOT NULL, pcm BLOB NOT NULL);
    CREATE TABLE segments (segment_id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL,
        start_frame INTEGER NOT NULL, end_frame INTEGER NOT NULL);
    CREATE TABLE revisions (revision_id INTEGER PRIMARY KEY, program_id TEXT NOT NULL);
    CREATE TABLE revision_slots (revision_id INTEGER NOT NULL, slot INTEGER NOT NULL,
        segment_id INTEGER NOT NULL, frame_count INTEGER NOT NULL, PRIMARY KEY (revision_id, slot));
    CREATE TABLE drafts (program_id TEXT PRIMARY KEY NOT NULL, revision_id INTEGER NOT NULL);
    CREATE TABLE voice_orders (order_id INTEGER PRIMARY KEY, revision_id INTEGER NOT NULL,
        sample_rate INTEGER NOT NULL);
    CREATE TABLE order_targets (order_id INTEGER NOT NULL, position INTEGER NOT NULL,
        slot INTEGER NOT NULL, frame_count INTEGER NOT NULL,
        PRIMARY KEY (order_id, position), UNIQUE (order_id, slot));
    CREATE TABLE takes (take_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL);
    CREATE TABLE take_parts (part_id INTEGER PRIMARY KEY, take_id INTEGER NOT NULL,
        position INTEGER NOT NULL, pcm BLOB NOT NULL, UNIQUE (take_id, position));
    CREATE TABLE receipts (receipt_id INTEGER PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
        take_id INTEGER NOT NULL UNIQUE);
    CREATE TABLE editions (edition_id INTEGER PRIMARY KEY, program_id TEXT NOT NULL,
        revision_id INTEGER NOT NULL, sample_rate INTEGER NOT NULL, frame_count INTEGER NOT NULL,
        timeline_json TEXT NOT NULL, wav BLOB NOT NULL);
'''


class LegacyMigrationTest(WorkbenchTest):
    def _build_legacy_database(self):
        db = sqlite3.connect(self.database)
        try:
            db.executescript(LEGACY_SCHEMA)
            db.execute("INSERT INTO programs VALUES ('G', 8000)")
            db.execute("INSERT INTO sources VALUES (1, 'G', 'legacy', 3, ?)",
                       (struct.pack('<3h', 10, 11, 12),))
            db.execute('INSERT INTO segments VALUES (1, 1, 0, 2)')
            db.execute('INSERT INTO segments VALUES (2, 1, 2, 3)')
            db.execute("INSERT INTO revisions VALUES (1, 'G')")
            db.execute('INSERT INTO revision_slots VALUES (1, 1, 1, 2), (1, 2, 2, 1)')
            db.execute("INSERT INTO drafts VALUES ('G', 1)")
            db.execute('INSERT INTO voice_orders VALUES (1, 1, 8000)')
            db.execute('INSERT INTO order_targets VALUES (1, 1, 2, 1)')
            db.execute('INSERT INTO takes VALUES (1, 1)')
            db.execute('INSERT INTO take_parts VALUES (1, 1, 1, ?)', (struct.pack('<h', 99),))
            db.execute("INSERT INTO receipts VALUES (1, 'old-req', 1)")
            db.commit()
        finally:
            db.close()

    def test_reopen_migrates_and_keeps_legacy_data(self):
        self.service.stop()
        Path(self.database).unlink()
        self._build_legacy_database()
        # Reopen runs the schema migration against the pre-existing database.
        self.service.start()
        mix = self.api('GET', '/mix/1')
        self.assertEqual(read_wave(mix)[2], [10, 11, 99])
        self.assertEqual(
            [(entry['source_kind'], entry['source_id']) for entry in mix['timeline']],
            [('source', 1), ('voice', 1)],
        )
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(
                db.execute('SELECT draft_id, current_revision_id FROM work_drafts').fetchall(),
                [(1, 1)],
            )
            self.assertEqual(
                db.execute('SELECT COUNT(*) FROM occurrences WHERE kind = "base"').fetchone(),
                (2,),
            )
            linked = db.execute(
                'SELECT occurrence_id IS NOT NULL FROM order_targets').fetchall()
            self.assertEqual(linked, [(1,)])
        # The migrated draft accepts new cuts and the current mix follows them.
        self.api('POST', '/cuts', {
            'request_id': 'mig-cut', 'revision_id': 1, 'first_slot': 1, 'last_slot': 1,
        })
        current = self.api('GET', '/mix/current')
        self.assertEqual(read_wave(current)[2], [99])
        # The original take request id still replays to its first receipt.
        replay = self.api('POST', '/voice-orders/1/takes', {
            'request_id': 'old-req',
            'parts': [{
                'sample_rate': 8000, 'channels': 1, 'encoding': 'pcm_s16le',
                'data': base64.b64encode(struct.pack('<h', 99)).decode(),
            }],
        }, 200)
        self.assertEqual(replay['receipt_id'], 1)

    def test_multiple_legacy_revisions_each_form_a_draft(self):
        self.service.stop()
        Path(self.database).unlink()
        db = sqlite3.connect(self.database)
        try:
            db.executescript(LEGACY_SCHEMA)
            db.execute("INSERT INTO programs VALUES ('G', 8000)")
            db.execute("INSERT INTO sources VALUES (1, 'G', 'legacy', 2, ?)",
                       (struct.pack('<2h', 1, 2),))
            db.execute('INSERT INTO segments VALUES (1, 1, 0, 2)')
            db.execute("INSERT INTO revisions VALUES (1, 'G'), (2, 'G')")
            db.execute('INSERT INTO revision_slots VALUES (1, 1, 1, 2), (2, 1, 1, 2)')
            db.execute("INSERT INTO drafts VALUES ('G', 2)")
            db.commit()
        finally:
            db.close()
        self.service.start()
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(
                db.execute('SELECT draft_id, current_revision_id FROM work_drafts ORDER BY draft_id').fetchall(),
                [(1, 1), (2, 2)],
            )
            self.assertEqual(
                db.execute('SELECT revision_id, draft_id FROM revisions ORDER BY revision_id').fetchall(),
                [(1, 1), (2, 2)],
            )
        # The current mix follows the proof the legacy drafts table pointed at.
        current = self.api('GET', '/mix/current')
        self.assertEqual(current['revision_id'], 2)
        # Both old proofs remain readable with their own occurrence identities.
        self.assertEqual(len(self.api('GET', '/revisions/1')['slots']), 1)
        self.assertEqual(len(self.api('GET', '/revisions/2')['slots']), 1)
