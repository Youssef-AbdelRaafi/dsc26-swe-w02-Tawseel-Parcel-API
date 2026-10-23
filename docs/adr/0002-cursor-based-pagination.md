# 0002 - Cursor-based pagination for parcel listing

## Status

Accepted

## Context

The `GET /v1/parcels` endpoint must support pagination. Two common approaches exist: offset-based (`?offset=20&limit=10`) and cursor-based (`?cursor=<opaque>&limit=10`). The courier and merchant teams will paginate through parcels while dispatchers are simultaneously changing parcel states. With offset pagination, if earlier items are removed from a filtered result set (e.g. a parcel moves out of `state=created`) between page requests, subsequent pages skip items or return duplicates, because the offset refers to a position in a changing list.

## Decision

We use cursor-based pagination. The cursor is an opaque token that encodes a stable position in the insertion-ordered list of parcels. Because cursors reference the global insertion index rather than the position within a filtered view, state changes to earlier parcels do not shift the window for later pages.

## Consequences

- **Easier**: Clients paginating with a state filter get consistent results even when dispatchers are actively changing parcel states between page fetches. The API contract is simpler: the client just passes back the `next_cursor` it received, with no arithmetic.
- **Harder**: Clients cannot jump to an arbitrary page (e.g. "page 5"); they must walk forward from the beginning. The server must track or validate issued cursors; invalid or fabricated cursors must be rejected with a 400 error. The cursor format is opaque, so clients cannot construct cursors themselves.
