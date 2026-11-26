import json
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import RunningService, origins, pcm, read_wave


ORIGINAL = ("A", "B", "C", "D", "E")
LATE_PARTS = ((31, 32), (51, 52), (71, 72))


def request(service, method, path, body=None, status=None):
    expected = status if status is not None else (201 if method == "POST" else 200)
    actual, result = service.request(method, path, body)
    if actual != expected:
        raise AssertionError((method, path, expected, actual, result))
    return result


def prepare(service):
    source = request(service, "POST", "/sources", {
        "program_id": "G", "description": "渡口剪节样例",
        "pcm": pcm(range(1, 11)),
    })
    segments = {}
    for start, name in enumerate(("A", "B", "C", "D", "X")):
        item = request(service, "POST", "/segments", {
            "source_id": source["source_id"], "start_frame": 2 * start, "end_frame": 2 * start + 2,
        })
        segments[name] = item["segment_id"]
    segments["E"] = segments["B"]
    proof = request(service, "POST", "/revisions", {
        "program_id": "G", "expected_revision_id": None,
        "segment_ids": [segments[name] for name in ORIGINAL],
    })
    revision_id = proof["revision_id"]
    order = request(service, "POST", "/voice-orders", {"revision_id": revision_id, "slots": [2, 3, 4]})
    edition = request(service, "POST", "/editions", {"revision_id": revision_id})
    return revision_id, segments, order["order_id"], edition


def verify_original(service):
    revision_id, segments, order_id, edition = prepare(service)
    changed = request(service, "POST", "/revisions", {
        "program_id": "G", "expected_revision_id": revision_id,
        "segment_ids": [segments[name] for name in ("A", "B", "X", "E")],
    })["revision_id"]
    path = f"/voice-orders/{order_id}/takes"
    body = {"request_id": "cuts-late-take", "parts": [pcm(part) for part in LATE_PARTS]}
    first = request(service, "POST", path, body)
    if request(service, "POST", path, body, 200) != first:
        raise AssertionError("original receipt changed")
    old_mix = request(service, "GET", f"/mix/{revision_id}")
    old_expected = [("source", segments["A"])] + [("voice", part["part_id"]) for part in first["parts"]]
    old_expected.append(("source", segments["E"]))
    if read_wave(old_mix) != (8000, 10, [1, 2, 31, 32, 51, 52, 71, 72, 3, 4]) or origins(old_mix) != old_expected:
        raise AssertionError("original order did not stay with its revision slots")
    new_mix = request(service, "GET", f"/mix/{changed}")
    if read_wave(new_mix) != (8000, 8, [1, 2, 3, 4, 9, 10, 3, 4]):
        raise AssertionError("ordinary full save unexpectedly reused a voice")
    edition_id = edition["edition_id"]
    if request(service, "GET", f"/editions/{edition_id}") != edition:
        raise AssertionError("original signed edition changed")
    print(json.dumps({"ordered_parts": first["parts"], "original_mix": read_wave(old_mix)[2],
                      "full_save_mix": read_wave(new_mix)[2], "signed_mix": read_wave(edition)[2]}))


def main():
    with TemporaryDirectory() as temporary:
        with RunningService(Path(temporary) / "workbench.sqlite3") as service:
            verify_original(service)


if __name__ == "__main__":
    main()
