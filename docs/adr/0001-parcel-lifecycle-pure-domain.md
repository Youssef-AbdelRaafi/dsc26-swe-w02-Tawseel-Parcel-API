# 0001 - Parcel lifecycle in a pure domain module

## Status

Accepted

## Context

The parcel lifecycle (state machine governing transitions such as dispatch, deliver, fail, and return) is a core business rule. If this logic is embedded directly in the HTTP handler layer, it becomes tightly coupled to the web framework (FastAPI), making it harder to test in isolation, reuse in other contexts (CLI tools, background workers), and reason about correctness. Different teams (courier app, merchant integrations) depend on these rules being reliable, and Sherif expects the rules to evolve as the product matures.

## Decision

We place all lifecycle logic — `ParcelState`, `EventType`, `InvalidTransition`, `Parcel`, and `apply_event` — in `app/domain.py`, a pure Python module with no imports from FastAPI, Starlette, Pydantic, or any ORM. The HTTP layer (`app/api.py`) calls into this module but never duplicates or overrides its rules.

## Consequences

- **Easier**: Unit-testing the state machine requires no HTTP client or framework setup; tests run faster and are more focused. Property-based testing (e.g. Hypothesis) becomes straightforward because `apply_event` is a pure function with no side effects. Swapping the web framework or adding a CLI entry point requires no changes to business logic.
- **Harder**: Developers must be disciplined about not importing framework types into the domain module. Any new validation that touches both the HTTP contract and the domain needs careful placement to avoid leaking framework concerns into the pure layer.
