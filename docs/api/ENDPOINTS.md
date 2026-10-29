# Endpoint map: GraphQL operations as REST routes

> Reference for tasks 4.x to 8.x. It maps each of the 14 operations of the Node base's `api/schema.gql` to a REST route, and records
> the behaviour each one must keep. Source of behaviour: the Node repo (`poc-base`, read-only), cited as `file:line` in the
> last column; paths are relative to `api/src/`. Contract decisions: ADR-0003 (REST and errors), ADR-0008 (tokens),
> ADR-0009 (files), ADR-0010 (configuration). Models, validation code and `openapi.json` come in tasks 4.1 to 4.3.

## Conventions

- **Base path:** `/api/v1`. Bodies are JSON, except file upload (`multipart/form-data`). Field names keep the Node spelling, camelCase, including `dataOfBirth` and `SSN`. Dates are ISO 8601 UTC strings.
- **Access token:** `Authorization: Bearer <accessToken>`; HS256 JWT with payload `{sub, jti}`, signed with `JWT_SECRET`, default lifetime 15 minutes (ADR-0010).
- **Refresh token:** the `x-refresh-token` header, accepted only by `POST /auth/refresh`; HS256 JWT signed with `JWT_REFRESH_TOKEN_SECRET`, default lifetime 7 days. Every issue of tokens (sign-up, sign-in, OTP verify, refresh) replaces the stored refresh hash, so the previous refresh token stops working (`auth/services/jwt-strategy/jwt-strategy.service.ts:16-45`).
- **Error body:** `{"error": {"code", "message", "details"}}` (ADR-0003). Every route can also return `INTERNAL_SERVER_ERROR` (500); the Errors column lists only the codes specific to the route.

  | Code | Status | Meaning |
  |------|--------|---------|
  | `UNAUTHORIZED` | 401 | token missing, expired, tampered or no longer maps to an account; the only code a client answers with a refresh |
  | `INVALID_CREDENTIALS` | 401 | wrong email or password, or a bad OTP; never triggers a refresh |
  | `INVALID_RESET_TOKEN` | 400 | reset token unknown, expired or already used |
  | `EMAIL_ALREADY_REGISTERED` | 409 | the email belongs to another account |
  | `FORBIDDEN` | 403 | authenticated but not allowed |
  | `NOT_FOUND` | 404 | the addressed resource does not exist |
  | `VALIDATION_FAILED` | 422 (413 for an oversized upload) | body failed validation; `details` lists the fields |
  | `INTERNAL_SERVER_ERROR` | 500 | unexpected; no stack trace outside local |

- **Shared validation rules** (from the Node DTOs in `auth/dto/`, `common/`):
  - email: valid address, at most 254 characters, normalised by trimming and lowercasing before lookup and storage (`common/normalize-email.ts:3-4`);
  - new password (sign-up, reset, change): 8 to 72 **bytes**, no control characters (`common/password-rules.ts:3`); current password and sign-in password: 1 to 72 bytes;
  - phone number: a valid phone number in international format.
- **Success status:** 200, except 201 for `sign-up` and `POST /files`, and 204 (no body) for the operations that returned only `true` in GraphQL.
- **Role names:** `CUSTOMER` and `ADMIN`. "any" means any authenticated account.

## Auth endpoints

| Operation | Method and path | Request | Response | Success | Errors | Auth | Roles | Node source |
|-----------|-----------------|---------|----------|---------|--------|------|-------|-------------|
| `signInOtp` | `POST /auth/otp/request` | `{phoneNumber}` | `{success: true, code?: string}`; `code` only when `APP_ENV` is local, development or test | 200 | `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:32-49`, `auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:30-65` |
| `verifyOtp` | `POST /auth/otp/verify` | `{phoneNumber, code}` | `{accessToken, refreshToken}` | 200 | `INVALID_CREDENTIALS`, `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:51-54`, `auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:67-119` |
| `signUp` | `POST /auth/sign-up` | `{email, password}` | `{accessToken, refreshToken}` | 201 | `EMAIL_ALREADY_REGISTERED`, `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:60-63`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:58-90` |
| `signIn` | `POST /auth/sign-in` | `{email, password}` | `{accessToken, refreshToken}` | 200 | `INVALID_CREDENTIALS`, `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:69-72`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:92-116` |
| `refreshToken` | `POST /auth/refresh` | no body; header `x-refresh-token` | `{accessToken, refreshToken}` | 200 | `UNAUTHORIZED` | refresh token | none | `auth/auth.resolver.ts:79-82`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:249-274`, `auth/strategies/jwt-refresh.strategy.ts:19-35` |
| `signOut` | `POST /auth/sign-out` | none | none | 204 | `UNAUTHORIZED` | Bearer | any | `auth/auth.resolver.ts:125-128`, `auth/auth.service.ts:8-12` |
| `changePassword` | `POST /auth/password/change` | `{currentPassword, newPassword}` | none | 204 | `INVALID_CREDENTIALS`, `UNAUTHORIZED`, `VALIDATION_FAILED` | Bearer | any | `auth/auth.resolver.ts:112-121`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:118-159` |
| `restorePassword` | `POST /auth/password/restore` | `{email}` | `{success: true}` | 200 | `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:89-94`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:164-207` |
| `resetPassword` | `POST /auth/password/reset` | `{token, newPassword}` | none | 204 | `INVALID_RESET_TOKEN`, `VALIDATION_FAILED` | none | none | `auth/auth.resolver.ts:100-104`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:209-247` |

Behaviours to keep:

- **`signInOtp`**: an unknown phone number creates a customer account (`auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:34-38`); the code is stored only as a hash and is valid for 2 minutes (`auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:28,43-45`); a new request replaces the previous code; the code is returned in the response only when `APP_ENV` is local, development or test, never otherwise (`auth/auth.resolver.ts:36-44`). Delivery is an SMS job on the queue (log-only at this stage, ADR-0005).
- **`verifyOtp`**: an unknown account, an expired code and a wrong code all answer 401 `INVALID_CREDENTIALS` (mapping decision 4); on success the code is cleared, `isPhoneVerified` becomes true and tokens are issued (`auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:102-118`).
- **`signUp`**: the email is normalised; an existing profile with that email answers 409 (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:62-68`), and so does losing a race on the unique index (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:82-87`); the password is stored as bcrypt (10 rounds) with its salt; tokens are issued at once; `isPhoneVerified` is not touched.
- **`signIn`**: an unknown email, a deleted account or identity, an OTP-only account (no password hash) and a wrong password are indistinguishable: 401 `INVALID_CREDENTIALS` (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:106-113`); on success tokens are issued.
- **`refreshToken`**: the header token must verify with the refresh secret and match the stored hash; anything else is 401 `UNAUTHORIZED` (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:249-269`). Success issues a new pair and replaces the stored hash, so the old refresh token is dead. The stored value becomes `sha256(refreshToken)` (ADR-0008).
- **`signOut`**: clears the stored refresh hash and the OTP (`auth/auth.service.ts:8-12`); the refresh token is rejected afterwards, the access token stays valid until it expires. Node's update fails when the account has no identity row; task 7.4 decides the REST answer.
- **`changePassword`**: needs the current password; an account without a password hash answers 401 `INVALID_CREDENTIALS` (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:128-130`); the new hash replaces the old and the refresh token, reset token and OTP are cleared in the same update, so every session must sign in again (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:146-158`).
- **`restorePassword`**: answers `{{success: true}}` for any well-formed email, registered or not, and never contains the token (`auth/auth.resolver.ts:89-94`, `auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:180-182`); for a registered account it stores `sha256(token)` of a random 32-byte token valid for 30 minutes (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:44,184-198`) and queues an email job (log-only at this stage, ADR-0005); a new request replaces the live token.
- **`resetPassword`**: the token is matched by its hash; unknown or expired is 400 `INVALID_RESET_TOKEN` (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:219-224`); the token is consumed with one conditional update and a count other than 1 is also `INVALID_RESET_TOKEN` (`auth/services/jwt-auth-strategy/jwt-auth-strategy.service.ts:231-246`), so two concurrent resets cannot both win; the password changes and the refresh token, reset token and OTP are cleared, so every session must sign in again.

## Account and profile endpoints

| Operation | Method and path | Request | Response | Success | Errors | Auth | Roles | Node source |
|-----------|-----------------|---------|----------|---------|--------|------|-------|-------------|

## File endpoints

| Operation | Method and path | Request | Response | Success | Errors | Auth | Roles | Node source |
|-----------|-----------------|---------|----------|---------|--------|------|-------|-------------|

## Mapping decisions

Where this map differs from the Node base, and why. Items 1 to 6 were stated in the spec of POC-1.2 and approved by volodymyr on 2026-10-29; items 7 to 12 are choices made while writing this map and are marked for review.

1. **Real status codes.** Node answers every failure as GraphQL with HTTP 200 and often throws `Unauthorized` carrying `NOT_FOUND` or `FORBIDDEN` (`account-profile/account-profile.resolver.ts:33-48`). REST uses the status of the code (table above).
2. **Missing account or profile.** `GET /account` for a token whose account is gone is 401 `UNAUTHORIZED` (the token no longer maps to an account); `PATCH` of a missing profile is 404 `NOT_FOUND`.
3. **Unknown file.** An unknown file id and another account's file are both 403 `FORBIDDEN`, as in Node (`files/services/file-assert.service.ts:71-80`), so the existence of a file is not leaked.
4. **OTP failures.** An unknown account, an expired code and a wrong code all become 401 `INVALID_CREDENTIALS`. Node returned three messages (`auth/services/otp-auth-strategy/otp-auth-strategy.service.ts:80-98`); one code does not reveal which phone numbers exist. It is never `UNAUTHORIZED`, which would make a client try a refresh.
5. **Created.** `sign-up` and `POST /files` answer 201.
6. **Upload failures.** An oversized upload is 413 and a disallowed or missing mime type is 422, both `VALIDATION_FAILED` with the field in `details`; Node answered 403 for all three (`file-assert.service.ts:30-44`). No new error code is added to ADR-0003. Task 4.2 carries this into `docs/api/ERRORS.md`.
7. **Reset token is 400.** `INVALID_RESET_TOKEN` is 400 (ADR-0003); Node answered 401 (`jwt-auth-strategy.service.ts:223,245`).
8. **No body for `true`.** `signOut`, `changePassword` and `resetPassword` returned `Boolean` true in GraphQL; REST answers 204. `restorePassword` keeps its `{success: true}` body and `signInOtp` its `{success, code?}`.
9. **Profile key.** The account response nests the profile under `profile` instead of the GraphQL field `AccountProfile`, as the scope doc's task 5.3 does (`profile.email`).
10. **Files are created with content.** `POST /files` requires the `file` part (ADR-0009). Node's two-step flow, creating a record with metadata only and attaching content later, is not ported; `PATCH /files/{id}` can still replace content. Size and mime type come from the upload, not from client-supplied fields. `publicUrl` (a `data:` URI) is replaced by `contentUrl`, the path of the new content route.
11. **New route.** `GET /files/{id}/content` has no GraphQL operation; it exists because ADR-0009 moved the bytes out of the JSON.
12. **Nullable phone.** `profile.phoneNumber` is `string | null`: the Prisma column is optional (`prisma/models/account.prisma:70`) but the GraphQL type was non-null, which fails for password accounts (scope-doc issue I.3).

Not ported, by design: GraphQL field selection (`GraphToPrisma`, Node ADR-0003), which gives REST responses fixed shapes; the GraphQL `DateTime` scalar.
