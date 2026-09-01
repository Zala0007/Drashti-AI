# Advanced modules security boundary

The advanced modules enforce role gates and case-level access inside the API, redact controlled references, attribute mutations, and avoid returning stream credentials. This is defense in depth, not a complete production identity system.

## Development versus production

The local portal sends `X-Actor-ID` and `X-Actor-Role` to exercise workflows. Those headers are untrusted unless a production ingress removes client-supplied copies, authenticates the user/workload, authorizes policy, and injects signed or network-protected identity context. Production must deny these endpoints without that gateway.

## Sensitive data controls

- Vehicle observations, plates, routes, camera topology, health, cases, and evidence metadata are restricted operational data.
- Raw crop/object references remain server-side. Evidence exports contain safe metadata only.
- Analytics and health publishers need workload identity, replay protection, rate limiting, and schema validation.
- Audit storage needs append-only/WORM controls and centralized monitoring.
- Database/object backups require encryption, retention policy, tested restoration, and access review.
- Development scenarios are disabled in production and must never be presented as real evidence.

Threat models for federation and media remain in `docs/security/`. They continue to apply to every advanced module that consumes camera or stream outputs.
