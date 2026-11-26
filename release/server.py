import argparse
import json
import re
import sqlite3
from contextlib import closing, contextmanager
from functools import partial
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from dubbing.orders import ensure_order_schema
from dubbing.receipts import ensure_receipt_schema
from dubbing.routes import DUBBING_ROUTES
from dubbing.takes import ensure_take_schema
from edit.drafts import ensure_draft_schema
from edit.revisions import ensure_revision_schema
from edit.routes import EDIT_ROUTES
from mix.routes import MIX_ROUTES
from release.editions import ensure_edition_schema
from release.routes import RELEASE_ROUTES
from source.catalog import ensure_source_schema
from source.programs import ProgramSpec, ensure_program_schema, seed_programs
from source.routes import SOURCE_ROUTES
from source.segments import ensure_segment_schema

DEFAULT_PROGRAMS = (ProgramSpec('G', 8000),)
SCHEMA_STEPS = (
    ensure_program_schema, ensure_source_schema, ensure_segment_schema,
    ensure_revision_schema, ensure_draft_schema, ensure_order_schema,
    ensure_take_schema, ensure_receipt_schema, ensure_edition_schema,
)
ROUTES = tuple(
    (method, re.compile(pattern), handler)
    for method, pattern, handler in SOURCE_ROUTES + EDIT_ROUTES + DUBBING_ROUTES + MIX_ROUTES + RELEASE_ROUTES
)


@contextmanager
def _transaction(database, *, write):
    with closing(sqlite3.connect(database, isolation_level=None)) as db:
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
        try:
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise


def initialize_database(database, programs=DEFAULT_PROGRAMS):
    with _transaction(database, write=True) as db:
        for ensure_schema in SCHEMA_STEPS:
            ensure_schema(db)
        seed_programs(db, programs)


class Application:
    def __init__(self, database):
        self.database = database

    def dispatch(self, method, path, body=None):
        for verb, pattern, handler in ROUTES:
            if verb != method:
                continue
            match = pattern.fullmatch(path)
            if match is None:
                continue
            parameters = {name: int(value) for name, value in match.groupdict().items()}
            write = method == 'POST'
            if write and not isinstance(body, dict):
                return 400, {'error': 'invalid_json_object'}
            try:
                with _transaction(self.database, write=write) as db:
                    if write:
                        status, payload = handler(db, body, **parameters)
                    else:
                        status, payload = handler(db, **parameters)
                    if status >= 400:
                        db.rollback()
            except sqlite3.Error:
                return 500, {'error': 'database_failure'}
            except (ValueError, OverflowError):
                return 500, {'error': 'invalid_stored_audio'}
            return status, payload
        return 404, {'error': 'unknown_route'}

    def bind(self, host, port):
        return HTTPServer((host, port), partial(HttpHandler, application=self))


def _reject_nonfinite(value):
    raise ValueError(f'invalid JSON constant {value}')


class HttpHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, application, **kwargs):
        self.application = application
        super().__init__(*args, **kwargs)

    def _read_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length < 1:
            raise ValueError('expected a request body')
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError('incomplete request body')
        payload = json.loads(raw.decode('utf-8'), parse_constant=_reject_nonfinite)
        if not isinstance(payload, dict):
            raise ValueError('expected a JSON object')
        # SQLite text values must also be representable as UTF-8.
        json.dumps(payload, ensure_ascii=False).encode('utf-8')
        return payload

    def _send_json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        try:
            path = urlsplit(self.path).path
            body = self._read_json() if self.command == 'POST' else None
        except (ValueError, OverflowError, RecursionError):
            self._send_json(400, {'error': 'invalid_request'})
            return
        self._send_json(*self.application.dispatch(self.command, path, body))

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def log_request(self, code='-', size='-'):
        # Keep the output of local regressions focused on business assertions.
        if str(code).startswith('5'):
            super().log_request(code, size)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Oral history production service')
    parser.add_argument('--database', required=True)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--sample-rate', type=int, default=8000)
    args = parser.parse_args(argv)
    initialize_database(args.database, (ProgramSpec('G', args.sample_rate),))
    with Application(args.database).bind(args.host, args.port) as server:
        host, port = server.server_address
        print(f'Listening on http://{host}:{port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            return


if __name__ == '__main__':
    main()
