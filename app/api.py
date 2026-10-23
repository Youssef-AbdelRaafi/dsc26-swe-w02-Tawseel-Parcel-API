"""HTTP layer for the Tawseel parcel API."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.domain import (
    EventType,
    InvalidTransition,
    Parcel,
    ParcelState,
    apply_event,
)

# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class CreateParcelRequest(BaseModel):
    merchant_ref: str = Field(..., min_length=1, max_length=64)
    cod_amount_piastres: int = Field(..., ge=0, le=5_000_000)
    address_text: str = Field(..., min_length=1, max_length=500)


class ParcelResponse(BaseModel):
    id: str
    merchant_ref: str
    cod_amount_piastres: int
    address_text: str
    state: str
    attempts: int


class RecordEventRequest(BaseModel):
    type: str


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    errors: list[dict[str, Any]] | None = None


class ListParcelsResponse(BaseModel):
    items: list[ParcelResponse]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parcel_to_response(parcel: Parcel) -> ParcelResponse:
    return ParcelResponse(
        id=parcel.id,
        merchant_ref=parcel.merchant_ref,
        cod_amount_piastres=parcel.cod_amount_piastres,
        address_text=parcel.address_text,
        state=parcel.state.value,
        attempts=parcel.attempts,
    )


def _problem(status_code: int, title: str, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": title,
        "status": status_code,
    }
    body.update(extra)
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Create a new FastAPI app with its own in-memory store."""

    # ---- per-app state ----
    parcels_by_id: dict[str, Parcel] = {}
    parcels_ordered: list[str] = []  # insertion-order list of ids
    merchant_refs: set[str] = set()
    cursor_registry: set[str] = set()  # known cursors we have issued

    application = FastAPI(title="Tawseel Parcel API", version="0.1.0")

    # ---- exception handlers ----

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors = []
        for err in exc.errors():
            loc = list(err["loc"])
            errors.append({"loc": loc, "msg": err["msg"]})
        return JSONResponse(
            status_code=422,
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "errors": errors,
            },
            media_type="application/problem+json",
        )

    # ---- routes ----

    @application.post(
        "/v1/parcels",
        status_code=status.HTTP_201_CREATED,
        response_model=ParcelResponse,
        operation_id="createParcel",
        responses={
            409: {"description": "Duplicate merchant_ref", "content": {"application/problem+json": {}}},
            422: {"description": "Validation Error", "content": {"application/problem+json": {}}},
        },
    )
    async def create_parcel(body: CreateParcelRequest) -> Any:
        if body.merchant_ref in merchant_refs:
            return _problem(409, "Duplicate merchant_ref")

        parcel_id = f"pcl_{uuid.uuid4().hex}"
        parcel = Parcel(
            id=parcel_id,
            merchant_ref=body.merchant_ref,
            cod_amount_piastres=body.cod_amount_piastres,
            address_text=body.address_text,
        )
        parcels_by_id[parcel_id] = parcel
        parcels_ordered.append(parcel_id)
        merchant_refs.add(body.merchant_ref)

        resp = _parcel_to_response(parcel)
        return JSONResponse(
            status_code=201,
            content=resp.model_dump(),
            headers={"Location": f"/v1/parcels/{parcel_id}"},
        )

    @application.get(
        "/v1/parcels/{parcel_id}",
        response_model=ParcelResponse,
        operation_id="getParcel",
        responses={
            404: {"description": "Parcel not found", "content": {"application/problem+json": {}}},
        },
    )
    async def get_parcel(parcel_id: str) -> Any:
        parcel = parcels_by_id.get(parcel_id)
        if parcel is None:
            return _problem(404, "Parcel not found")
        return _parcel_to_response(parcel)

    @application.get(
        "/v1/parcels",
        response_model=ListParcelsResponse,
        operation_id="listParcels",
        responses={
            400: {"description": "Bad cursor", "content": {"application/problem+json": {}}},
            422: {"description": "Validation Error", "content": {"application/problem+json": {}}},
        },
    )
    async def list_parcels(
        request: Request,
        state: str | None = Query(default=None),
        limit: str | None = Query(default=None),
        cursor: str | None = Query(default=None),
    ) -> Any:
        # Validate state
        if state is not None:
            valid_states = {s.value for s in ParcelState}
            if state not in valid_states:
                return JSONResponse(
                    status_code=422,
                    content={
                        "type": "about:blank",
                        "title": "Validation Error",
                        "status": 422,
                        "errors": [{"loc": ["query", "state"], "msg": f"Invalid state: {state}"}],
                    },
                    media_type="application/problem+json",
                )

        # Validate limit
        if limit is not None:
            try:
                limit_int = int(limit)
            except (ValueError, TypeError):
                return JSONResponse(
                    status_code=422,
                    content={
                        "type": "about:blank",
                        "title": "Validation Error",
                        "status": 422,
                        "errors": [{"loc": ["query", "limit"], "msg": "limit must be an integer between 1 and 100"}],
                    },
                    media_type="application/problem+json",
                )
            if limit_int < 1 or limit_int > 100:
                return JSONResponse(
                    status_code=422,
                    content={
                        "type": "about:blank",
                        "title": "Validation Error",
                        "status": 422,
                        "errors": [{"loc": ["query", "limit"], "msg": "limit must be an integer between 1 and 100"}],
                    },
                    media_type="application/problem+json",
                )
        else:
            limit_int = 20

        # Validate cursor
        if cursor is not None and cursor not in cursor_registry:
            return _problem(400, "Bad cursor")

        # Build the filtered list using stable insertion-order indices.
        # The cursor encodes the insertion-order index to resume from,
        # so state changes between pages cannot cause skips or repeats.
        start_index = 0
        if cursor is not None:
            # cursor format: "cursor_<index>"
            try:
                start_index = int(cursor.split("_", 1)[1])
            except (IndexError, ValueError):
                return _problem(400, "Bad cursor")

        items: list[ParcelResponse] = []

        i = start_index
        while i < len(parcels_ordered) and len(items) < limit_int:
            pid = parcels_ordered[i]
            p = parcels_by_id[pid]
            if state is None or p.state.value == state:
                items.append(_parcel_to_response(p))
            i += 1

        # Check if there are actually more *matching* items beyond position i.
        # Without this check, a state filter could produce an extra empty
        # trailing page (the spec forbids that).
        has_more = False
        if state is None:
            # No filter: any remaining entry is a match
            has_more = i < len(parcels_ordered)
        else:
            # With a filter: scan ahead to see if at least one more matches
            for j in range(i, len(parcels_ordered)):
                if parcels_by_id[parcels_ordered[j]].state.value == state:
                    has_more = True
                    break

        next_cursor: str | None = None
        if has_more:
            next_cursor = f"cursor_{i}"
            cursor_registry.add(next_cursor)

        return ListParcelsResponse(items=items, next_cursor=next_cursor)

    @application.post(
        "/v1/parcels/{parcel_id}/events",
        response_model=ParcelResponse,
        operation_id="recordParcelEvent",
        responses={
            404: {"description": "Parcel not found", "content": {"application/problem+json": {}}},
            409: {"description": "Invalid transition", "content": {"application/problem+json": {}}},
            422: {"description": "Validation Error", "content": {"application/problem+json": {}}},
        },
    )
    async def record_parcel_event(parcel_id: str, body: RecordEventRequest) -> Any:
        # Validate event type
        try:
            event = EventType(body.type)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={
                    "type": "about:blank",
                    "title": "Validation Error",
                    "status": 422,
                    "errors": [{"loc": ["body", "type"], "msg": f"Unknown event type: {body.type}"}],
                },
                media_type="application/problem+json",
            )

        parcel = parcels_by_id.get(parcel_id)
        if parcel is None:
            return _problem(404, "Parcel not found")

        try:
            updated = apply_event(parcel, event)
        except InvalidTransition:
            return _problem(409, "Invalid transition")

        parcels_by_id[parcel_id] = updated
        return _parcel_to_response(updated)

    return application


app = create_app()
