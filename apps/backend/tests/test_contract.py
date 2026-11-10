"""Pydantic 契約模型與 contract/*.schema.json 的一致性。"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

from support import FIXTURES, ROOT, load_fixture
from smart_health_backend.contract import (
    SUPPORTED_SCHEMA_VERSIONS,
    ContractError,
    parse_status,
    parse_topology,
)

TOPOLOGY_SCHEMA = json.loads((ROOT / "contract" / "topology.schema.json").read_text("utf-8"))
STATUS_SCHEMA = json.loads((ROOT / "contract" / "status.schema.json").read_text("utf-8"))


def dumps(doc) -> str:
    return json.dumps(doc, ensure_ascii=False)


@pytest.mark.parametrize("name", ["topology_edge.json", "topology_api.json"])
def test_topology_fixtures_accepted(name):
    doc = load_fixture(name)
    jsonschema.validate(doc, TOPOLOGY_SCHEMA)
    model = parse_topology(dumps(doc))
    assert model.topology_version == doc["topology_version"]
    assert [n.id for n in model.nodes] == [n["id"] for n in doc["nodes"]]


@pytest.mark.parametrize(
    "name", ["status_edge_camera_down.json", "status_before_first_evaluation.json"]
)
def test_status_fixtures_accepted(name):
    doc = load_fixture(name)
    jsonschema.validate(doc, STATUS_SCHEMA)
    model = parse_status(dumps(doc))
    assert model.started_at == doc["started_at"]
    assert set(model.nodes) == set(doc["nodes"])


STATUS_FIXTURE_NAMES = ["status_edge_camera_down.json", "status_before_first_evaluation.json"]


@pytest.mark.parametrize("name", STATUS_FIXTURE_NAMES)
def test_status_v14_and_v15_parse_to_same_model(name):
    """SPEC 1.5 的 ready_at 是新增欄位：v1.4（沒有 ready_at）與 v1.5 都能解析，且後端忽略它。"""
    v15 = load_fixture(name)
    assert "ready_at" in v15
    v14 = copy.deepcopy(v15)
    del v14["ready_at"]
    jsonschema.validate(v14, STATUS_SCHEMA)
    assert parse_status(dumps(v14)) == parse_status(dumps(v15))


@pytest.mark.parametrize("ready_at", [None, "2026-11-05T10:00:42.000+08:00"])
def test_status_ready_at_value_does_not_affect_model(ready_at):
    base = load_fixture("status_edge_camera_down.json")
    doc = copy.deepcopy(base)
    doc["ready_at"] = ready_at
    jsonschema.validate(doc, STATUS_SCHEMA)
    model = parse_status(dumps(doc))
    assert model == parse_status(dumps(base))
    assert "ready_at" not in model.model_dump()


def test_unknown_fields_ignored():
    doc = load_fixture("status_edge_camera_down.json")
    doc["future"] = {"x": 1}
    doc["nodes"]["ingest"]["extra"] = 1
    doc["recent_transitions"][0]["extra"] = 1
    parse_status(dumps(doc))
    topo = load_fixture("topology_edge.json")
    topo["lanes"][0]["extra"] = 1
    topo["nodes"][0]["extra"] = 1
    parse_topology(dumps(topo))


def _mutate(fn):
    def apply(doc):
        doc = copy.deepcopy(doc)
        fn(doc)
        return doc

    return apply


STATUS_NEGATIVE = {
    "bad_service_id": _mutate(lambda d: d.update(service="Bad Id")),
    "empty_instance": _mutate(lambda d: d.update(instance="")),
    "bad_version_format": _mutate(lambda d: d.update(topology_version="XYZ")),
    "bad_node_id": _mutate(lambda d: d["nodes"].update({"Bad": d["nodes"]["ingest"]})),
    "bad_reason": _mutate(lambda d: d["nodes"]["ingest"].update(reason="Bad Reason")),
    "message_too_long": _mutate(lambda d: d["nodes"]["ingest"].update(message="x" * 201)),
    "unknown_state": _mutate(lambda d: d["nodes"]["ingest"].update(state="broken")),
    "metrics_object": _mutate(lambda d: d["nodes"]["ingest"].update(metrics={"a": {"b": 1}})),
    "metrics_list": _mutate(lambda d: d["nodes"]["ingest"].update(metrics={"a": [1]})),
    "null_not_empty": _mutate(lambda d: d.update(evaluated_at=None)),
    "bad_timestamp": _mutate(lambda d: d.update(started_at="2026-11-05 10:00:00")),
    "naive_timestamp": _mutate(lambda d: d.update(started_at="2026-11-05T10:00:00")),
    "fullwidth_digits": _mutate(lambda d: d.update(started_at="２０２６-11-05T10:00:00+08:00")),
    "bad_since": _mutate(lambda d: d["nodes"]["ingest"].update(since="yesterday")),
    "negative_age": _mutate(lambda d: d.update(evaluation_age_s=-1)),
    "string_age": _mutate(lambda d: d.update(evaluation_age_s="1")),
    "bool_age": _mutate(lambda d: d.update(evaluation_age_s=True)),
    "too_many_transitions": _mutate(
        lambda d: d.update(recent_transitions=d["recent_transitions"][:1] * 51)
    ),
    "bad_transition_to": _mutate(lambda d: d["recent_transitions"][0].update(to="nope")),
    "bad_transition_from": _mutate(lambda d: d["recent_transitions"][0].update(**{"from": "nope"})),
    "bad_transition_node": _mutate(lambda d: d["recent_transitions"][0].update(node="Bad")),
    "missing_key": _mutate(lambda d: d.pop("nodes")),
    "nodes_not_object": _mutate(lambda d: d.update(nodes=[])),
    "state_null": _mutate(lambda d: d["nodes"]["ingest"].update(state=None)),
}


@pytest.mark.parametrize("name", sorted(STATUS_NEGATIVE))
def test_status_negative_cases_rejected_by_both(name):
    doc = STATUS_NEGATIVE[name](load_fixture("status_edge_camera_down.json"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, STATUS_SCHEMA)
    with pytest.raises(ContractError) as info:
        parse_status(dumps(doc))
    assert info.value.code == "invalid_response"


def test_status_null_evaluated_with_transitions_rejected():
    doc = load_fixture("status_before_first_evaluation.json")
    doc["recent_transitions"] = load_fixture("status_edge_camera_down.json")["recent_transitions"][:1]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, STATUS_SCHEMA)
    with pytest.raises(ContractError):
        parse_status(dumps(doc))


TOPOLOGY_NEGATIVE = {
    "bad_service": _mutate(lambda d: d.update(service="X Y")),
    "bad_version": _mutate(lambda d: d.update(topology_version="short")),
    "bad_lane_id": _mutate(lambda d: d["lanes"][0].update(id="Main")),
    "bad_lane_parent": _mutate(lambda d: d["lanes"][1].update(parent="Bad")),
    "lane_sequential_str": _mutate(lambda d: d["lanes"][0].update(sequential="yes")),
    "lane_node_bad_id": _mutate(lambda d: d["lanes"][0].update(nodes=["Bad"])),
    "node_missing_label": _mutate(lambda d: d["nodes"][0].pop("label")),
    "node_upstream_bad": _mutate(lambda d: d["nodes"][0].update(upstream=["Bad"])),
    "node_dep_not_list": _mutate(lambda d: d["nodes"][0].update(dependencies="messaging")),
    "nodes_not_list": _mutate(lambda d: d.update(nodes={})),
}


@pytest.mark.parametrize("name", sorted(TOPOLOGY_NEGATIVE))
def test_topology_negative_cases_rejected_by_both(name):
    doc = TOPOLOGY_NEGATIVE[name](load_fixture("topology_edge.json"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, TOPOLOGY_SCHEMA)
    with pytest.raises(ContractError) as info:
        parse_topology(dumps(doc))
    assert info.value.code == "invalid_response"


def test_supported_versions_is_set():
    assert SUPPORTED_SCHEMA_VERSIONS == {1}


@pytest.mark.parametrize("parse", [parse_topology, parse_status])
@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("not json", "invalid_response"),
        ("", "invalid_response"),
        ("[]", "invalid_response"),
        ('"x"', "invalid_response"),
        ("{}", "invalid_response"),
        ('{"schema_version": "1"}', "invalid_response"),
        ('{"schema_version": true}', "invalid_response"),
        ('{"schema_version": 1.0}', "invalid_response"),
        ('{"schema_version": null}', "invalid_response"),
        ('{"schema_version": 2, "anything": 1}', "incompatible"),
        ('{"schema_version": 0}', "incompatible"),
        ('{"schema_version": 1, "metrics": NaN}', "invalid_response"),
        ('{"schema_version": 1, "metrics": Infinity}', "invalid_response"),
        ('{"schema_version": 1, "metrics": -Infinity}', "invalid_response"),
    ],
)
def test_error_codes(parse, body, code):
    with pytest.raises(ContractError) as info:
        parse(body)
    assert info.value.code == code


def test_invalid_utf8_is_invalid_response():
    with pytest.raises(ContractError) as info:
        parse_status(b"\xff\xfe{")
    assert info.value.code == "invalid_response"


def test_nan_inside_valid_status_rejected():
    text = (FIXTURES / "status_edge_camera_down.json").read_text("utf-8").replace("0.0", "NaN")
    assert "NaN" in text
    with pytest.raises(ContractError) as info:
        parse_status(text)
    assert info.value.code == "invalid_response"


def test_future_version_with_other_shape_is_incompatible_not_invalid():
    doc = load_fixture("status_edge_camera_down.json")
    doc["schema_version"] = 2
    doc["nodes"] = "new shape"
    with pytest.raises(ContractError) as info:
        parse_status(dumps(doc))
    assert info.value.code == "incompatible"


def test_metrics_overflow_to_inf_rejected():
    text = (FIXTURES / "status_edge_camera_down.json").read_text("utf-8").replace("0.0", "1e400")
    assert "1e400" in text
    with pytest.raises(ContractError) as info:
        parse_status(text)
    assert info.value.code == "invalid_response"


def test_age_overflow_to_inf_rejected():
    doc = dumps(load_fixture("status_edge_camera_down.json")).replace('"evaluation_age_s": 0.4', '"evaluation_age_s": 1e999')
    assert "1e999" in doc
    with pytest.raises(ContractError):
        parse_status(doc)


def test_models_are_frozen():
    model = parse_status(dumps(load_fixture("status_edge_camera_down.json")))
    with pytest.raises(Exception):
        model.instance = "x"
