"""契約測試：以 JSON Schema 驗證 fixtures 與各種錯誤輸入。"""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRACT_DIR = Path(__file__).resolve().parents[1]
FIXTURES = CONTRACT_DIR / "fixtures"

TOPOLOGY_FIXTURES = ["topology_edge.json", "topology_api.json"]
STATUS_FIXTURES = ["status_edge_camera_down.json", "status_before_first_evaluation.json"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validator(name: str) -> Draft202012Validator:
    schema = load(CONTRACT_DIR / name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def compute_topology_version(doc: dict) -> str:
    text = json.dumps(
        {"lanes": doc["lanes"], "nodes": doc["nodes"]},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@pytest.fixture
def status_validator():
    return validator("status.schema.json")


@pytest.fixture
def topology_validator():
    return validator("topology.schema.json")


@pytest.fixture
def status_doc():
    return load(FIXTURES / "status_edge_camera_down.json")


@pytest.fixture
def topology_doc():
    return load(FIXTURES / "topology_edge.json")


def test_fixtures_match_schema(status_validator, topology_validator):
    for name in TOPOLOGY_FIXTURES:
        topology_validator.validate(load(FIXTURES / name))
    for name in STATUS_FIXTURES:
        status_validator.validate(load(FIXTURES / name))


@pytest.mark.parametrize("name", TOPOLOGY_FIXTURES)
def test_topology_version_matches_content(name):
    doc = load(FIXTURES / name)
    assert doc["topology_version"] == compute_topology_version(doc)


def test_status_fixture_version_matches_topology(status_doc, topology_doc):
    assert status_doc["topology_version"] == topology_doc["topology_version"]
    assert set(status_doc["nodes"]) == {n["id"] for n in topology_doc["nodes"]}


def test_api_fixture_covers_generality():
    doc = load(FIXTURES / "topology_api.json")
    assert doc["service"] != "edge"
    nodes = {n["id"]: n for n in doc["nodes"]}
    assert any(set(n["dependencies"]) == {"database", "cache"} for n in nodes.values())
    assert any(len(n["upstream"]) >= 2 for n in nodes.values())
    lanes = {lane["id"]: lane for lane in doc["lanes"]}
    node_lane = {nid: lane["id"] for lane in doc["lanes"] for nid in lane["nodes"]}
    assert any(
        lane["parent"] is not None and lanes[node_lane[lane["parent"]]]["parent"] is not None
        for lane in lanes.values()
    ), "需要巢狀 lane（parent 節點位於非頂層 lane）"


def test_rejects_unknown_state(status_validator, status_doc):
    status_doc["nodes"]["ingest-worker"]["state"] = "broken"
    assert not status_validator.is_valid(status_doc)


def test_rejects_bad_reason(status_validator, status_doc):
    status_doc["nodes"]["ingest-worker"]["reason"] = "Bad Reason"
    assert not status_validator.is_valid(status_doc)


def test_rejects_long_message(status_validator, status_doc):
    status_doc["nodes"]["ingest-worker"]["message"] = "x" * 201
    assert not status_validator.is_valid(status_doc)


def test_accepts_null_message_and_reason(status_validator, status_doc):
    node = status_doc["nodes"]["ingest-worker"]
    node["message"] = None
    node["reason"] = None
    status_validator.validate(status_doc)


def test_accepts_unknown_fields(status_validator, topology_validator, status_doc, topology_doc):
    status_doc["future_field"] = {"a": 1}
    status_doc["nodes"]["ingest-worker"]["extra"] = True
    topology_doc["future_field"] = "x"
    topology_doc["nodes"][0]["extra"] = 1
    status_validator.validate(status_doc)
    topology_validator.validate(topology_doc)


def test_rejects_wrong_schema_version(status_validator, status_doc):
    status_doc["schema_version"] = 999
    assert not status_validator.is_valid(status_doc)


def test_rejects_time_without_timezone(status_validator, status_doc):
    status_doc["started_at"] = "2026-11-05T10:00:00"
    assert not status_validator.is_valid(status_doc)


def test_rejects_non_scalar_metric(status_validator, status_doc):
    status_doc["nodes"]["ingest-worker"]["metrics"] = {"fps": [1]}
    assert not status_validator.is_valid(status_doc)


def test_rejects_more_than_50_transitions(status_validator, status_doc):
    item = status_doc["recent_transitions"][0]
    status_doc["recent_transitions"] = [copy.deepcopy(item) for _ in range(51)]
    assert not status_validator.is_valid(status_doc)


def test_transition_from_may_be_null(status_validator, status_doc):
    status_doc["recent_transitions"][0]["from"] = None
    status_validator.validate(status_doc)


def test_status_before_first_evaluation_is_valid(status_validator):
    doc = load(FIXTURES / "status_before_first_evaluation.json")
    assert doc["evaluated_at"] is None
    assert doc["nodes"] == {}
    assert doc["recent_transitions"] == []
    status_validator.validate(doc)


def test_rejects_null_evaluated_at_with_nodes(status_validator, status_doc):
    status_doc["evaluated_at"] = None
    assert not status_validator.is_valid(status_doc)


def test_rejects_null_evaluated_at_with_transitions(status_validator):
    doc = load(FIXTURES / "status_before_first_evaluation.json")
    doc["recent_transitions"] = [
        {"node": "a", "from": None, "to": "ok", "reason": None, "at": "2026-11-05T10:00:00+08:00"}
    ]
    assert not status_validator.is_valid(doc)


@pytest.mark.parametrize("bad", ["Edge", "1edge", "", "edge name", "_edge"])
def test_rejects_bad_service_id(status_validator, topology_validator, status_doc, topology_doc, bad):
    status_doc["service"] = bad
    topology_doc["service"] = bad
    assert not status_validator.is_valid(status_doc)
    assert not topology_validator.is_valid(topology_doc)


def test_rejects_bad_lane_node_or_dependency_id(
    status_validator, topology_validator, status_doc, topology_doc
):
    bad_lane = copy.deepcopy(topology_doc)
    bad_lane["lanes"][0]["id"] = "Main"
    assert not topology_validator.is_valid(bad_lane)

    bad_lane_node = copy.deepcopy(topology_doc)
    bad_lane_node["lanes"][0]["nodes"][0] = "Bad Node"
    assert not topology_validator.is_valid(bad_lane_node)

    bad_node = copy.deepcopy(topology_doc)
    bad_node["nodes"][0]["id"] = "Bad_Node"
    assert not topology_validator.is_valid(bad_node)

    bad_upstream = copy.deepcopy(topology_doc)
    bad_upstream["nodes"][0]["upstream"] = ["Up"]
    assert not topology_validator.is_valid(bad_upstream)

    bad_dep = copy.deepcopy(topology_doc)
    bad_dep["nodes"][-1]["dependencies"] = ["MQTT"]
    assert not topology_validator.is_valid(bad_dep)

    bad_status_key = copy.deepcopy(status_doc)
    bad_status_key["nodes"]["Bad Key"] = bad_status_key["nodes"].pop("ingest-worker")
    assert not status_validator.is_valid(bad_status_key)

    bad_transition_node = copy.deepcopy(status_doc)
    bad_transition_node["recent_transitions"][0]["node"] = "Bad Node"
    assert not status_validator.is_valid(bad_transition_node)


def test_instance_accepts_uppercase(status_validator, topology_validator, status_doc, topology_doc):
    status_doc["instance"] = "CamA-northbound-1"
    topology_doc["instance"] = "CamA-northbound-1"
    status_validator.validate(status_doc)
    topology_validator.validate(topology_doc)


def test_rejects_empty_instance(status_validator, topology_validator, status_doc, topology_doc):
    status_doc["instance"] = ""
    topology_doc["instance"] = ""
    assert not status_validator.is_valid(status_doc)
    assert not topology_validator.is_valid(topology_doc)
