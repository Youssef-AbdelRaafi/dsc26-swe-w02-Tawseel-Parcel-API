## Tools

- Claude (Anthropic) — used for pair-programming, code review, and understanding API design patterns.

## What AI got wrong

- Initial pagination implementation used offset-based filtering, which would break consistency when items change state between page requests. Had to rethink to use insertion-order index-based cursors.
- First draft of the validation error handler did not include the `loc` field structure expected by the tests (`["body", "field_name"]`).

## In my own words

**Why does listParcels need a cursor rather than an offset?**
Because offset pagination breaks when items move in or out of a filtered result set between page requests. If a dispatcher changes a parcel's state from "created" to "out_for_delivery" while a client is paginating `?state=created`, an offset-based approach would shift all subsequent items and cause the client to skip one or see a duplicate. A cursor anchored to a stable insertion index avoids that problem.

**Which of your four operations would break the courier app if you renamed one field, and who would have to approve that change?**
Any of the read operations (getParcel, listParcels) or the response of createParcel and recordParcelEvent could break the courier app if a field like `state` or `attempts` were renamed, since the courier app parses those fields. The change would need to be approved by both the courier app team and the merchant integration team, since they are building against this contract, and ideally documented as a breaking change in a new API version.
