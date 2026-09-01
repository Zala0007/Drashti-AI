# Semantic Visual Search

The portal route is `#/visual`. Searches operate only over persisted visual profiles; stored images are not resent to Groq for each query.

Supported retrieval signals include vehicle type, normalized colour, damage status, damage text, distinctive features, accessories, plate visibility, ANPR value, camera/source and descriptions. Common query attributes are parsed locally, then combined with keyword relevance. Results use `HIGH`, `MEDIUM` and `LOW` match levels and list human-readable match reasons instead of uncalibrated percentages.

API:

- `POST /api/v1/visual-intelligence/search`
- `GET /api/v1/visual-intelligence`
- `GET /api/v1/visual-intelligence/{id}`
- `POST /api/v1/visual-intelligence/analyze/{detection_id}`
- `POST /api/v1/visual-intelligence/backfill`
- `GET /api/v1/visual-intelligence/status`

All endpoints require investigator or supervisor actor headers. Search queries, filters, result counts, actor IDs and timestamps are written to `visual_search_audit`.

The result drawer shows the original vehicle crop, linked plate crop, existing ANPR value, structured attributes, AI description and model provenance. GIS and Special Investigation handoffs are available from result cards.

