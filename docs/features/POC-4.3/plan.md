# POC-4.3 — implementation plan

<!-- A human writes this line to approve. Until it is here, guard-plan-approval blocks writes to code.
     Approved-by: <name> · <date> -->
Approved-by: Volodymyr - 2026-11-03

Pattern followed: `app/core/errors.py` (one module per concern in `core/`, no layer imports, typed without `Any`) for the validation primitives, and the stub files in `app/schemas/` (`auth.py`, `account_profile.py`) for the request models. Tests follow `tests/unit/test_errors.py` (pure) and `tests/e2e/test_http_errors.py` (test-local routes on `create_app(Settings())`, `running_client`, no database). No precedent for field types exists; they stay inside ADR-0003 (Pydantic request models), so no ADR.
Layers: `core` (field types, base model; imports no layer) and `schemas` (may import `core`; project-structure rule 4 forbids only services, models and routers).

## Contract changes
- boundary: request models only; no route uses them yet, so `openapi.json` should not change (checked by the stale test; if it does, regenerate by command).
- dependencies: `uv add email-validator phonenumbers` (runtime, approved). `uv.lock` changes through uv only (T3). `pyproject.toml` is "ask first": confirm when prompted.
- data: none. Errors: `validation_details` in `errors.py` stays unchanged unless R1 shows a custom type leaks a value.

## Requirements (ordered; branch `feat/POC-4.3-validation`, one draft PR, one commit each)

### R1 — Dependencies and `app/core/validation.py` (M)
- files: `pyproject.toml`, `uv.lock` (via `uv add`); `app/core/validation.py` (new): `StrictModel(BaseModel)` with `extra="forbid"`, camelCase alias generator, `populate_by_name=True`; Annotated types `Email`, `ProfileEmail`, `NewPassword`, `CurrentPassword`, `PhoneNumber`, `UuidStr` (own `PydanticCustomError`, because pydantic's built-in `uuid_parsing` message echoes a character of the input); helper `byte_length_between(min, max)`. Failures raise `PydanticCustomError` with our own type codes (`password_too_short`, `password_too_long`, `control_character`, `phone_invalid`) and fixed messages that never contain the input (AC7). API of `email-validator`, `phonenumbers` and pydantic `EmailStr` verified with Context7 before use (rule D4).
- layer: core.
- test: `tests/unit/test_validation.py`: table-driven per type, incl. 7/8/72/73 bytes, 40 two-byte characters, tab/NUL/newline, email with spaces and uppercase, 255-char email, phone with and without `+`, bad UUID, unknown key; each failure's `errors()` output (and `validation_details`) free of the submitted value, and no character of it in a bad-UUID message.
- executed how: `uv run python -c` validating a good and a bad value for each type and printing the resulting errors; real HTTP is R3.
- risk: pydantic `EmailStr` may trim or accept names like `A <a@b.c>`; cheapest check is the unit test on those inputs in R1, then validate with `email_validator.validate_email` directly if it does.

### R2 — Request models in `app/schemas` (S)
- files: `app/schemas/auth.py`: `SignUpInput`, `SignInInput`, `OtpRequestInput`, `OtpVerifyInput` (code string max 6), `ChangePasswordInput`, `RestorePasswordInput`, `ResetPasswordInput` (token 1 to 200); `app/schemas/account_profile.py`: `UpdateAccountProfileInput` (`first_name`, `last_name`, `middle_name` max 50; `email`; `date_of_birth` max 10 aliased `dataOfBirth`; `avatar_id` UUID; nullable fields accept `null`, `email: null` is 422, unsent means unset). All inherit `StrictModel`.
- layer: schemas.
- test: `tests/unit/test_auth_schemas.py` and `tests/unit/test_account_profile_schemas.py` (`test_<module>_<layer>.py`, project-structure rule 8): valid body parses, each limit from ENDPOINTS.md, `null` vs unsent in the profile update, unknown key rejected.
- executed how: unit run; R3 does the HTTP call.
- risk: "unsent" vs `null` for nullable fields; use `model_fields_set` and a test for it.

### R3 — HTTP check of the acceptance criterion (S)
- files: `tests/e2e/test_http_validation.py`: a test-local `POST` route taking `SignUpInput` on `create_app(Settings())` through `running_client`; no database.
- test: bad sign-up body gives 422 `VALIDATION_FAILED`, `details[].field` contains `email`, `password` and the unknown key; the password text is not in the body or in `caplog` (AC1, AC7); a valid body gives 200.
- executed how (evidence): scratchpad script serving that route with `uvicorn`, then `curl -i` with the bad and the good body; paste both responses.
- risk: none beyond R1.

## Done check (rule B1)
Before the PR, run and paste the output of: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, `uv run pytest tests/unit`, `uv run pytest tests/e2e` (needs Docker or `TEST_DATABASE_URL`; the new e2e test needs neither, the rest of the directory does), `uv run python -m app.cli --export-openapi --check`. Anything that cannot run goes under "Not verified".

## Docs (same PR, rule E1)
`docs/api/ENDPOINTS.md` (validation rules now enforced by `app/core/validation.py`, remove "come in task 4.3"), `docs/api/ERRORS.md` (the new `type` values under `VALIDATION_FAILED`), `docs/ARCHITECTURE.md` (validation.py built, two runtime deps), `docs/RUNBOOK.md` only if setup changes (it should not). Glossary: no new term.

## Risks and unknowns
1. `phonenumbers` accepts numbers by region metadata; "valid" may be stricter than Node's `IsPhoneNumber`. Experiment: R1 table test with 3 real formats.
2. A custom `type` code leaking the input through `ctx`: `validation_details` reads only `loc`, `msg`, `type`; R1 test asserts it.
3. Dependency approval prompts for `pyproject.toml` (ask-first path); that is expected, not a bypass.

## Estimate
R1 M, R2 S, R3 S.

## Not covered
Routes, services, hashing, tokens, response models, upload checks, list params.
