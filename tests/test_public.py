"""Public tests for dsc26-swe-w02 — Tawseel parcel API, contract first."""

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.domain import (
    EventType,
    InvalidTransition,
    Parcel,
    ParcelState,
    apply_event,
)


# ── domain ──────────────────────────────────────────────────────────────────

def test_happy_path_lifecycle():
    """created → dispatch → deliver is the simplest success path."""
    p = Parcel(id="pcl_1", merchant_ref="MR-1",
               cod_amount_piastres=1500, address_text="123 Elm St")
    p = apply_event(p, EventType.DISPATCH)
    assert p.state == ParcelState.OUT_FOR_DELIVERY
    assert p.attempts == 1
    p = apply_event(p, EventType.DELIVER)
    assert p.state == ParcelState.DELIVERED


def test_invalid_transition_raises():
    """deliver is not valid on a CREATED parcel."""
    p = Parcel(id="pcl_1", merchant_ref="MR-1",
               cod_amount_piastres=0, address_text="addr")
    with pytest.raises(InvalidTransition):
        apply_event(p, EventType.DELIVER)


# ── api ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    return TestClient(create_app())


def test_create_and_get(client):
    r = client.post("/v1/parcels", json={
        "merchant_ref": "MR-42",
        "cod_amount_piastres": 2500,
        "address_text": "7 Nile St",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("pcl_")
    assert body["state"] == "created"
    assert r.headers["location"].endswith(f"/v1/parcels/{body['id']}")

    r2 = client.get(f"/v1/parcels/{body['id']}")
    assert r2.status_code == 200
    assert r2.json() == body


def test_validation_error_is_problem_json(client):
    r = client.post("/v1/parcels", json={
        "merchant_ref": "",
        "cod_amount_piastres": -1,
        "address_text": "ok",
    })
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 422
    locs = {tuple(e["loc"]) for e in body["errors"]}
    assert ("body", "merchant_ref") in locs
    assert ("body", "cod_amount_piastres") in locs


def test_list_parcels_basic(client):
    for i in range(3):
        client.post("/v1/parcels", json={
            "merchant_ref": f"MR-{i}",
            "cod_amount_piastres": i * 100,
            "address_text": f"addr {i}",
        })
    r = client.get("/v1/parcels")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None
