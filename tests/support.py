import base64
import http.client
import io
import json
import sqlite3
import struct
import tempfile
import threading
import unittest
import wave
from contextlib import closing, contextmanager
from pathlib import Path

from release.server import Application, initialize_database
from source.programs import ProgramSpec


def pcm(samples, rate=8000):
    data = struct.pack(f'<{len(samples)}h', *samples)
    return {
        'sample_rate': rate, 'channels': 1, 'encoding': 'pcm_s16le',
        'data': base64.b64encode(data).decode('ascii'),
    }


def wav_bytes(payload):
    return base64.b64decode(payload['wav'], validate=True)


def read_wave(payload):
    with wave.open(io.BytesIO(wav_bytes(payload)), 'rb') as recording:
        count = recording.getnframes()
        data = recording.readframes(count)
        if recording.getsampwidth() != 2 or recording.getnchannels() != 1:
            raise AssertionError('expected mono 16-bit WAV')
        if recording.getcomptype() != 'NONE' or len(data) != 2 * count:
            raise AssertionError('inconsistent PCM WAV')
        samples = [value for (value,) in struct.iter_unpack('<h', data)]
        return recording.getframerate(), count, samples


def origins(payload):
    return [(entry['source_kind'], entry['source_id']) for entry in payload['timeline']]


class RunningService:
    def __init__(self, database):
        self.database = database
        self.server = None
        self.thread = None

    def start(self, sample_rate=8000):
        initialize_database(self.database, (ProgramSpec('G', sample_rate),))
        self.server = Application(self.database).bind('127.0.0.1', 0)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True,
        )
        self.thread.start()

    def stop(self):
        if self.server is not None:
            self.server.shutdown()
            self.thread.join()
            self.server.server_close()
            self.server = None
            self.thread = None

    def restart(self, sample_rate=8000):
        self.stop()
        self.start(sample_rate)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def request(self, method, path, body=None):
        host, port = self.server.server_address
        data = None if body is None else json.dumps(body).encode('utf-8')
        headers = {} if data is None else {'Content-Type': 'application/json'}
        with closing(http.client.HTTPConnection(host, port, timeout=5)) as connection:
            connection.request(method, path, body=data, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())


class WorkbenchTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = Path(temporary.name) / 'workbench.sqlite3'
        self.service = RunningService(self.database)
        self.addCleanup(self.service.stop)
        self.service.start()

    def api(self, method, path, body=None, status=None):
        expected = status if status is not None else (201 if method == 'POST' else 200)
        actual, payload = self.service.request(method, path, body)
        self.assertEqual(actual, expected, (method, path, payload))
        return payload

    def source(self, samples=(10, 11, 20, 21, 22, 30, 31), program='G', rate=8000):
        return self.api('POST', '/sources', {
            'program_id': program, 'description': '渡口讲述', 'pcm': pcm(samples, rate),
        })

    def segment(self, source_id, start, end):
        return self.api('POST', '/segments', {
            'source_id': source_id, 'start_frame': start, 'end_frame': end,
        })

    def story_segments(self):
        source_id = self.source()['source_id']
        return [self.segment(source_id, first, end)['segment_id'] for first, end in ((0, 2), (2, 5), (5, 7))]

    def proof(self, segments, expected=None):
        return self.api('POST', '/revisions', {
            'program_id': 'G', 'expected_revision_id': expected, 'segment_ids': segments,
        })

    def voice_order(self, revision_id, slots):
        return self.api('POST', '/voice-orders', {'revision_id': revision_id, 'slots': slots})

    def submit(self, order_id, request_id, samples, status=201):
        return self.api('POST', f'/voice-orders/{order_id}/takes', {
            'request_id': request_id, 'parts': [pcm(part) for part in samples],
        }, status=status)

    def preview(self, revision_id):
        return self.api('GET', f'/mix/{revision_id}')

    def edition(self, revision_id, status=201):
        return self.api('POST', '/editions', {'revision_id': revision_id}, status=status)

    def assert_audio(self, payload, samples, rate=8000):
        self.assertEqual(read_wave(payload), (rate, len(samples), samples))
        self.assertEqual(payload['sample_rate'], rate)
        self.assertEqual(payload['frame_count'], len(samples))

    def stored(self, query):
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(query).fetchall()

    @contextmanager
    def fail_commit_on(self, table):
        # A real deferred constraint fails COMMIT after the handler has done its writes.
        if table not in {'receipts', 'editions'}:
            raise ValueError('unsupported commit failure target')
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript(f'''
                CREATE TABLE test_commit_parent (id INTEGER PRIMARY KEY);
                CREATE TABLE test_commit_child (
                    parent_id INTEGER REFERENCES test_commit_parent(id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER test_reject_commit AFTER INSERT ON {table}
                BEGIN
                    INSERT INTO test_commit_child VALUES (1);
                END;
            ''')
        try:
            yield
        finally:
            with closing(sqlite3.connect(self.database)) as db:
                db.executescript('''
                    DROP TRIGGER test_reject_commit;
                    DROP TABLE test_commit_child;
                    DROP TABLE test_commit_parent;
                ''')
