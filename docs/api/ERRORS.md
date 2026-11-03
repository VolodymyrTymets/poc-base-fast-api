# Error contract

> Task 4.2, decided in ADR-0003. Code: `app/core/errors.py`. Tests: `tests/unit/test_errors.py`, `tests/unit/test_errors_openapi.py`, `tests/e2e/test_http_errors.py`.

Every error the API returns has this body, and only this body:

```json
{"error": {"code": "NOT_FOUND", "message": "Not found", "details": []}}
```

- **Clients key on `code`.** `message` is an English string for developers and logs: do not show it to an end user and do not parse it (rule D7). It may change without notice; a `code` may not.
- `details` is always a list: empty, validation entries, or (only in `local`, for an unexpected error) one traceback string.
- FastAPI's own `{"detail": ...}` body never appears. The OpenAPI contract (`openapi.json`) documents `ErrorResponse` for 422 and 500 on every route.

## Codes

| Code | Status | Raised by | Meaning and client rule |
|------|--------|-----------|-------------------------|
| `UNAUTHORIZED` | 401 | `UnauthorizedError` (a 401 `HTTPException`) | token missing, expired, tampered or maps to no account. **The only code a client answers with a token refresh.** |
| `INVALID_CREDENTIALS` | 401 | `InvalidCredentialsError` | wrong email or password, or a bad OTP. Never refresh; show a sign-in error. |
| `INVALID_RESET_TOKEN` | 400 | `InvalidResetTokenError` | reset token unknown, expired or already used. |
| `EMAIL_ALREADY_REGISTERED` | 409 | `EmailAlreadyRegisteredError` | the email belongs to another account. |
| `FORBIDDEN` | 403 | `ForbiddenError` (a 403 `HTTPException`) | authenticated but not allowed (role or ownership). |
| `NOT_FOUND` | 404 | `NotFoundError`, an unknown path (404 `HTTPException`) | the addressed resource or route does not exist. |
| `VALIDATION_FAILED` | 422 (413, 405) | `ValidationFailedError`, a request body that fails validation | see below. |
| `INTERNAL_SERVER_ERROR` | 500 | any unhandled exception | unexpected. No stack trace outside `local`. |

### `VALIDATION_FAILED`
- **422:** the body, query or path failed validation. `details` has one entry per failed field: `{"in": "body", "field": "profile.email", "message": "...", "type": "missing"}`. `field` is the dotted path inside the part named by `in` (`body`, `query`, `path`, `header`); it is empty when the whole body is wrong (malformed JSON, type `json_invalid`). **The submitted value is never in `details`**: Pydantic's `input` is dropped, and the text of a validator's `ValueError` or failed `assert` (types `value_error`, `assertion_error`) is replaced by `Invalid value` because it may contain the value (rules D8, P4). One limit: a key of a client-sent dict is part of `field`, so a request model must not take a dict whose keys are personal data.
- **`type` values of our own validators** (task 4.3, `app/core/validation.py`): `email_invalid`, `password_too_short`, `password_too_long`, `control_character`, `invalid_text` (not valid UTF-8, for example a lone surrogate), `phone_invalid`, `uuid_invalid`, `null_not_allowed` (`email: null` in a profile update). Their messages are fixed and never contain the value. Pydantic's own types appear too: `extra_forbidden` (an unknown key, the field is that key), `string_too_long`, `missing`, `json_invalid`. Password limits count bytes, not characters.
- **413:** a body over `MAX_REQUEST_BODY_BYTES` (12 MiB), answered before routing with empty `details` (task 1.6). An upload over `FILE_MAX_SIZE` is also 413; a disallowed or missing mime type is 422 (endpoint map, decision 6; the upload routes come in task 8.x).
- **405 and other HTTP statuses without a code** (for example a wrong method) keep their status and use `VALIDATION_FAILED` with empty `details` and the exception's text (or the HTTP reason phrase when it is not a string) as `message`; 204 and 304 carry no body; headers such as `Allow` are kept. This was decided with the owner on 2026-11-03 to avoid a new code (a new code needs a superseding ADR).

### `INTERNAL_SERVER_ERROR`
- `message` is always `Internal server error`. In `APP_ENV=local` `details` holds the traceback as one string; in every other environment it is `[]`.
- The exception is logged once at `ERROR` with its stack by `app.core.errors`, in every environment (request method and path only; no body, headers or query string). Uvicorn then logs its own `Exception in ASGI application` line for the same crash, because Starlette re-raises after answering: that is expected, not a second failure.
- **Known limitation:** the 500 response carries no CORS headers. The handler for unexpected exceptions runs in Starlette's outermost middleware, outside `CORSMiddleware`, so a browser reports a CORS error instead of the 500 for a cross-origin call. 4xx responses are not affected. Fixing it means catching at a layer inside CORS; not part of task 4.2.

## Adding an error
1. Subclass `AppError` in `app/core/errors.py` with `status_code`, `code` (an existing `ErrorCode`) and `default_message`; raise it from a service. No router code is needed.
2. A new `ErrorCode` changes the contract: write a superseding ADR for ADR-0003, add the row above, and regenerate `openapi.json` (`uv run python -m app.cli --export-openapi`).
3. Add a test to `tests/e2e/test_http_errors.py`.
