# ADR-0003 — REST API with FastAPI and an OpenAPI contract

- **Date:** 2026-10-29
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-1.1
- **Supersedes:** Node ADR-0002 (GraphQL-first API, code-first, no REST surface) and Node ADR-0003 (Pass `GraphQLResolveInfo` into service read methods). Decision D2 of the scope doc.

## Context
The Node base exposes GraphQL only. This repo rebuilds the same behaviour in Python and has no consumer that needs GraphQL
(`web/` is not part of it). Node ADR-0003 existed only to serve GraphQL field selection, so it falls with Node ADR-0002.

## Decision
- The API is REST, served by FastAPI, under the prefix `/api/v1`. One `APIRouter` per feature.
- Request and response bodies are Pydantic models. A response model is never an ORM object.
- The contract is the OpenAPI document, exported by a command to `openapi.json` at the repo root (this repo's layout, ADR-0010, has no `api/` directory). A test fails when the committed file is stale. The file is generated: never hand-edited.
- Errors use one body, `{"error": {"code", "message", "details"}}`. `UNAUTHORIZED` (401, token rejected) is the only code a client may answer with a token refresh. Other codes: `INVALID_CREDENTIALS` 401, `INVALID_RESET_TOKEN` 400, `EMAIL_ALREADY_REGISTERED` 409, `FORBIDDEN` 403, `NOT_FOUND` 404, `VALIDATION_FAILED` 422 with per-field details, `INTERNAL_SERVER_ERROR` 500 without a stack outside local.
- Response shapes are fixed. GraphQL field selection is not ported, so services do not receive transport objects.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep GraphQL (for example Strawberry) | no GraphQL consumer in this repo; the scope doc rules out a GraphQL endpoint beside REST |
| REST without a committed contract | a fork could not tell what changed; the stale-spec test is the guard |
| FastAPI's default 422 body | clients would need two error shapes |

## Consequences
- Positive: standard tooling, a generated contract, services free of transport types.
- Accepted cost: the endpoint map (task 1.2) must translate 14 GraphQL operations; clients written for GraphQL do not work.
- Follow-ups: tasks 1.2, 4.1, 4.2. Add `openapi.json` to `protected-paths.md` in task 4.1.

## Revisit when
A consumer needs client-chosen field selection or subscriptions.
