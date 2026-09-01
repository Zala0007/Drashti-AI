# P0.1 Representative Seed Data

These files contain fictional camera records at approximate public-area coordinates for functional demonstration. They are not an inventory of deployed government assets and contain no live endpoint, username, password, token, or production credential reference.

Files:

- `departments.csv` — departments to create first through `POST /api/v1/departments`.
- `cameras.csv` — canonical input for `POST /api/v1/cameras/import`.

The camera importer resolves `department_code`; this keeps the file portable across databases whose department UUIDs differ. JSON-valued columns contain valid compact JSON and therefore require CSV quoting.

Recommended import order:

1. Create each department using `code`, `name`, and `description` from `departments.csv`.
2. Upload `cameras.csv` with a unique `Idempotency-Key` header.
3. Verify the structured per-row result and then inspect list, GeoJSON, statistics, and audit endpoints.

Never replace the safe blank/reference values with a credential-bearing RTSP URI. A future federation module will keep restricted endpoints in connection profiles and credentials in a secret manager.

