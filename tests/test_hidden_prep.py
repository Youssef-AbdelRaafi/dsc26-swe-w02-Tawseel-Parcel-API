"""Extra tests to verify hidden test requirements."""

from fastapi.testclient import TestClient
from app.api import create_app
from app.domain import *


def test_all_forbidden_transitions():
    """H02: All 15 forbidden (state, event) pairs raise InvalidTransition."""
    forbidden = [
        (ParcelState.CREATED, EventType.DELIVER),
        (ParcelState.CREATED, EventType.FAIL),
        (ParcelState.CREATED, EventType.RETURN),
        (ParcelState.OUT_FOR_DELIVERY, EventType.DISPATCH),
        (ParcelState.OUT_FOR_DELIVERY, EventType.RETURN),
        (ParcelState.FAILED_ATTEMPT, EventType.DELIVER),
        (ParcelState.FAILED_ATTEMPT, EventType.FAIL),
        (ParcelState.DELIVERED, EventType.DISPATCH),
        (ParcelState.DELIVERED, EventType.DELIVER),
        (ParcelState.DELIVERED, EventType.FAIL),
        (ParcelState.DELIVERED, EventType.RETURN),
        (ParcelState.RETURNED, EventType.DISPATCH),
        (ParcelState.RETURNED, EventType.DELIVER),
        (ParcelState.RETURNED, EventType.FAIL),
        (ParcelState.RETURNED, EventType.RETURN),
    ]
    for state, event in forbidden:
        p = Parcel(
            id="pcl_1", merchant_ref="MR-1",
            cod_amount_piastres=100, address_text="addr",
            state=state,
            attempts=1 if state != ParcelState.CREATED else 0,
        )
        try:
            result = apply_event(p, event)
            raise AssertionError(f"{state} + {event} did not raise, got {result}")
        except InvalidTransition:
            pass


def test_third_failure_dispatch_blocked():
    """H03: After 3 dispatch/fail cycles, dispatch raises and return works."""
    p = Parcel(id="pcl_1", merchant_ref="MR-1", cod_amount_piastres=100, address_text="addr")
    for _ in range(3):
        p = apply_event(p, EventType.DISPATCH)
        p = apply_event(p, EventType.FAIL)
    assert p.state == ParcelState.FAILED_ATTEMPT
    assert p.attempts == 3
    try:
        apply_event(p, EventType.DISPATCH)
        raise AssertionError("4th dispatch should raise")
    except InvalidTransition:
        pass
    p = apply_event(p, EventType.RETURN)
    assert p.state == ParcelState.RETURNED


def test_domain_no_framework_imports():
    """H04: app/domain.py imports no framework."""
    import ast
    with open("app/domain.py") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in ("fastapi", "starlette", "pydantic", "sqlalchemy")
            else:
                assert node.module is None or not any(
                    node.module.startswith(m) for m in ("fastapi", "starlette", "pydantic", "sqlalchemy")
                )


def test_create_location_and_fields():
    """H05: create returns 201, Location, all six fields, pcl_ prefix, unique ids."""
    client = TestClient(create_app())
    r = client.post("/v1/parcels", json={
        "merchant_ref": "MR-1",
        "cod_amount_piastres": 2500,
        "address_text": "7 Nile St",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("pcl_")
    assert body["merchant_ref"] == "MR-1"
    assert body["cod_amount_piastres"] == 2500
    assert body["address_text"] == "7 Nile St"
    assert body["state"] == "created"
    assert body["attempts"] == 0
    assert r.headers["location"].endswith(f'/v1/parcels/{body["id"]}')

    # Unique ids
    r2 = client.post("/v1/parcels", json={
        "merchant_ref": "MR-2",
        "cod_amount_piastres": 0,
        "address_text": "addr",
    })
    assert r2.json()["id"] != body["id"]


def test_validation_errors_problem_json():
    """H06: boundary values, multiple bad fields."""
    client = TestClient(create_app())

    # Boundary: valid at edges
    r = client.post("/v1/parcels", json={
        "merchant_ref": "x",  # min_length=1
        "cod_amount_piastres": 0,  # ge=0
        "address_text": "a",  # min_length=1
    })
    assert r.status_code == 201

    r = client.post("/v1/parcels", json={
        "merchant_ref": "x" * 64,  # max_length=64
        "cod_amount_piastres": 5_000_000,  # le=5_000_000
        "address_text": "a" * 500,  # max_length=500
    })
    assert r.status_code == 201

    # Invalid: empty ref
    r = client.post("/v1/parcels", json={
        "merchant_ref": "",
        "cod_amount_piastres": -1,
        "address_text": "ok",
    })
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["status"] == 422
    assert "type" in body
    assert "title" in body
    locs = {tuple(e["loc"]) for e in body["errors"]}
    assert ("body", "merchant_ref") in locs
    assert ("body", "cod_amount_piastres") in locs


def test_duplicate_merchant_ref_409():
    """H07: duplicate merchant_ref gives 409."""
    client = TestClient(create_app())
    r1 = client.post("/v1/parcels", json={
        "merchant_ref": "MR-DUP",
        "cod_amount_piastres": 100,
        "address_text": "addr",
    })
    assert r1.status_code == 201
    r2 = client.post("/v1/parcels", json={
        "merchant_ref": "MR-DUP",
        "cod_amount_piastres": 200,
        "address_text": "other addr",
    })
    assert r2.status_code == 409
    body = r2.json()
    assert body["status"] == 409


def test_unknown_parcel_404():
    """H08: unknown parcel returns 404 problem."""
    client = TestClient(create_app())
    r = client.get("/v1/parcels/pcl_nonexistent")
    assert r.status_code == 404
    r = client.post("/v1/parcels/pcl_nonexistent/events", json={"type": "dispatch"})
    assert r.status_code == 404


def test_invalid_transition_409_parcel_unchanged():
    """H09: invalid transition is 409, parcel unchanged."""
    client = TestClient(create_app())
    r = client.post("/v1/parcels", json={
        "merchant_ref": "MR-1",
        "cod_amount_piastres": 100,
        "address_text": "addr",
    })
    pid = r.json()["id"]

    # deliver on created is invalid
    r = client.post(f"/v1/parcels/{pid}/events", json={"type": "deliver"})
    assert r.status_code == 409

    # parcel should be unchanged
    r = client.get(f"/v1/parcels/{pid}")
    assert r.json()["state"] == "created"
    assert r.json()["attempts"] == 0

    # unknown event type
    r = client.post(f"/v1/parcels/{pid}/events", json={"type": "explode"})
    assert r.status_code == 422


def test_pagination_full_walk():
    """H10: 57 parcels, full walk."""
    client = TestClient(create_app())
    created_ids = []
    for i in range(57):
        r = client.post("/v1/parcels", json={
            "merchant_ref": f"MR-{i}",
            "cod_amount_piastres": i,
            "address_text": f"addr {i}",
        })
        assert r.status_code == 201
        created_ids.append(r.json()["id"])

    # Walk with limit=10
    all_ids = []
    cursor = None
    while True:
        url = "/v1/parcels?limit=10"
        if cursor:
            url += f"&cursor={cursor}"
        r = client.get(url)
        assert r.status_code == 200
        body = r.json()
        all_ids.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert all_ids == created_ids
    assert len(all_ids) == 57

    # Walk with default limit
    all_ids2 = []
    cursor = None
    while True:
        url = "/v1/parcels"
        if cursor:
            url += f"?cursor={cursor}"
        r = client.get(url)
        assert r.status_code == 200
        body = r.json()
        all_ids2.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert all_ids2 == created_ids


def test_pagination_cursor_survives_state_changes():
    """H11: cursor survives state changes mid-walk."""
    client = TestClient(create_app())
    ids = []
    for i in range(25):
        r = client.post("/v1/parcels", json={
            "merchant_ref": f"MR-{i}",
            "cod_amount_piastres": 100,
            "address_text": f"addr {i}",
        })
        ids.append(r.json()["id"])

    # Page 1: state=created, limit=10
    r = client.get("/v1/parcels?state=created&limit=10")
    body = r.json()
    page1_ids = [item["id"] for item in body["items"]]
    assert page1_ids == ids[:10]
    cursor = body["next_cursor"]

    # Dispatch page 1 parcels
    for pid in page1_ids:
        client.post(f"/v1/parcels/{pid}/events", json={"type": "dispatch"})

    # Page 2 should be items 11-20
    r = client.get(f"/v1/parcels?state=created&limit=10&cursor={cursor}")
    body = r.json()
    page2_ids = [item["id"] for item in body["items"]]
    assert page2_ids == ids[10:20]


def test_bad_cursor_and_limit():
    """H12: bad cursor 400, bad limit 422."""
    client = TestClient(create_app())
    r = client.get("/v1/parcels?cursor=garbage")
    assert r.status_code == 400

    for bad in ["0", "101", "-1", "abc"]:
        r = client.get(f"/v1/parcels?limit={bad}")
        assert r.status_code == 422

    r = client.get("/v1/parcels?state=nonexistent")
    assert r.status_code == 422


def test_openapi_contract():
    """H13: operationIds, paths, documented errors."""
    app = create_app()
    spec = app.openapi()
    paths = spec["paths"]

    # createParcel
    create = paths["/v1/parcels"]["post"]
    assert create["operationId"] == "createParcel"
    assert "201" in create["responses"] or 201 in create["responses"]
    assert "409" in create["responses"] or 409 in create["responses"]
    assert "422" in create["responses"] or 422 in create["responses"]

    # getParcel
    get = paths["/v1/parcels/{parcel_id}"]["get"]
    assert get["operationId"] == "getParcel"
    assert "404" in get["responses"] or 404 in get["responses"]

    # listParcels
    lst = paths["/v1/parcels"]["get"]
    assert lst["operationId"] == "listParcels"
    assert "400" in lst["responses"] or 400 in lst["responses"]
    assert "422" in lst["responses"] or 422 in lst["responses"]

    # recordParcelEvent
    evt = paths["/v1/parcels/{parcel_id}/events"]["post"]
    assert evt["operationId"] == "recordParcelEvent"
    assert "404" in evt["responses"] or 404 in evt["responses"]
    assert "409" in evt["responses"] or 409 in evt["responses"]
    assert "422" in evt["responses"] or 422 in evt["responses"]


def test_adrs_well_formed():
    """H14: two well-formed ADR files."""
    import os
    import re

    adr_dir = "docs/adr"
    pattern = re.compile(r"^\d{4}-[a-z0-9]+(-[a-z0-9]+)*\.md$")
    valid_statuses = {"Proposed", "Accepted", "Superseded", "Deprecated", "Rejected"}
    required_headings = {"Status", "Context", "Decision", "Consequences"}

    adr_files = [
        f for f in os.listdir(adr_dir)
        if pattern.match(f) and f != "0000-template.md"
    ]
    assert len(adr_files) >= 2, f"Need at least 2 ADRs, found {len(adr_files)}"

    for fname in adr_files:
        with open(os.path.join(adr_dir, fname)) as f:
            content = f.read()
        headings_found = set(re.findall(r"^#{2,3}\s+(.+)$", content, re.MULTILINE))
        for h in required_headings:
            assert h in headings_found, f"{fname} missing heading: {h}"

        # Check status line
        status_match = re.search(r"^#{2,3}\s+Status\s*\n+(.+)", content, re.MULTILINE)
        assert status_match, f"{fname} missing status content"
        status_line = status_match.group(1).strip()
        assert any(status_line.startswith(s) for s in valid_statuses), f"{fname} invalid status: {status_line}"
