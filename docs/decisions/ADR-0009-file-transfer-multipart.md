# ADR-0009 — Files move as multipart upload and authenticated download

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** Node ADR-0010 (PostgreSQL replaces S3 for file storage), in transport only. Storage stays in PostgreSQL. Decision D7 of the scope doc, confirmed by volodymyr on 2026-10-29.

## Context
The Node base sends file bytes as base64 inside GraphQL and returns them as a `data:` URI. Node ADR-0010 deferred a REST upload and
download as a larger boundary decision, because that base was GraphQL-only. This repo is REST (ADR-0003), so the deferred option is
now the natural one. Base64 inflates payloads by about a third and keeps whole files in memory as JSON strings.

## Decision
- `POST /api/v1/files`: multipart form with a `file` part and an optional `name`. Size comes from the bytes and the mime type from the upload; both are validated (10 MB cap, jpeg and png allowed by default; `FILE_*` settings).
- `PATCH /api/v1/files/{id}` (rename or replace the content) and `GET /api/v1/files/{id}` (metadata plus a content URL) are listed to show the transport; task 1.2 fixes the exact routes.
- `GET /api/v1/files/{id}/content`: owner only; returns the bytes as a response with `Content-Type` and `Content-Length`. The value is read from `bytea` whole, so it is a chunked response over an in-memory value, not a database stream.
- Bytes stay in the `File.content` column (`bytea`). Presence of content is the upload state, as in Node ADR-0010.
- An oversized upload returns 413.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Base64 inside JSON | larger payloads, whole file in memory, no streaming |
| Object storage (S3) | already removed by Node ADR-0010; no client needs it yet |
| Public content URLs | files would be readable without authentication |

## Consequences
- Positive: about a third less transferred than base64, and standard HTTP semantics.
- Accepted cost: the authenticated download cannot be used directly in an `<img src>`; a client must fetch it as a blob, or a signed short-lived URL is added later.
- Follow-ups: tasks 8.1 to 8.3.

## Revisit when
Files grow past what a `bytea` column handles well (true streaming would need large objects or another store), or a browser client needs plain image URLs.
