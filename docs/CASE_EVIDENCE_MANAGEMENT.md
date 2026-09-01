# Case and Evidence Management (P-S02)

The case workspace connects authorized investigations to controlled evidence metadata without exposing camera credentials, stream endpoints, or raw storage locations.

## Delivered records

- Case file: case number, purpose, authorization reference, priority, assignment, retention class, and optional one-to-one investigation link.
- Evidence link: source type/id, time, camera, classification, model version, confidence, safe metadata, controlled reference availability, and SHA-256 integrity value.
- Activity: actor-attributed creation, attachment, metadata view, transition, notes, and export.
- Structured export: the current case workspace plus an explicit integrity limitation.

Accepted investigation observations are linked automatically when a case is opened. Duplicate source links are idempotent. Assigned investigators and case creators can access a case; supervisors can access all cases. Non-supervisor case lists are filtered by assignment/creation.

## Integrity statement

The current SHA-256 value covers a canonical captured evidence manifest. It verifies that manifest, not a video file that the service never received. When production object storage supplies file bytes, the same record can carry the object-byte digest. The structured export is not, by itself, a complete legal chain of custody.

## Production requirements

- trusted gateway identity and policy enforcement;
- WORM/immutable evidence object storage and key-managed encryption;
- signed exports, formal custody transfer events, legal retention/hold workflows;
- malware scanning and content-type validation for future uploads;
- a controlled retrieval service that authorizes every object access.

The browser receives only safe metadata and `retrieval_available`; it never receives `controlled_reference`.
