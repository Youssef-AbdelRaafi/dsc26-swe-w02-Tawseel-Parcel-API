from dataclasses import dataclass, replace
from enum import StrEnum

MAX_ATTEMPTS = 3


class ParcelState(StrEnum):
    CREATED = "created"
    OUT_FOR_DELIVERY = "out_for_delivery"
    FAILED_ATTEMPT = "failed_attempt"
    DELIVERED = "delivered"
    RETURNED = "returned"


class EventType(StrEnum):
    DISPATCH = "dispatch"
    DELIVER = "deliver"
    FAIL = "fail"
    RETURN = "return"


class InvalidTransition(Exception):
    ...


@dataclass(frozen=True)
class Parcel:
    id: str
    merchant_ref: str
    cod_amount_piastres: int
    address_text: str
    state: ParcelState = ParcelState.CREATED
    attempts: int = 0


def apply_event(parcel: Parcel, event: EventType) -> Parcel:
    """Return a new Parcel. Raise InvalidTransition if the event is not allowed."""
    s = parcel.state
    e = event

    if s == ParcelState.CREATED and e == EventType.DISPATCH:
        return replace(parcel, state=ParcelState.OUT_FOR_DELIVERY, attempts=parcel.attempts + 1)

    if s == ParcelState.OUT_FOR_DELIVERY and e == EventType.DELIVER:
        return replace(parcel, state=ParcelState.DELIVERED)

    if s == ParcelState.OUT_FOR_DELIVERY and e == EventType.FAIL:
        return replace(parcel, state=ParcelState.FAILED_ATTEMPT)

    if s == ParcelState.FAILED_ATTEMPT and e == EventType.DISPATCH:
        if parcel.attempts >= MAX_ATTEMPTS:
            raise InvalidTransition(
                f"Cannot dispatch: max attempts ({MAX_ATTEMPTS}) reached"
            )
        return replace(parcel, state=ParcelState.OUT_FOR_DELIVERY, attempts=parcel.attempts + 1)

    if s == ParcelState.FAILED_ATTEMPT and e == EventType.RETURN:
        return replace(parcel, state=ParcelState.RETURNED)

    raise InvalidTransition(
        f"Event {e!r} is not allowed in state {s!r}"
    )
