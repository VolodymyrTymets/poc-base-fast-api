# Domain glossary

> One meaning per term. This drives naming in code, database and UI copy.
> A new user-facing noun means a line here, in the same PR (rule E1).

No domain code exists yet. These are the terms inherited from the Node `poc-base`, which the scope doc ports with the
same table and column names. They are deliberately generic: a POC forked from this repo extends the table with its own
domain and does not repurpose these names. Python identifiers are not decided yet (task 2.2); the Node name is the reference.

| Term (client language) | Reference identifier (Node base) | Means exactly | Not to be confused with |
|------------------------|----------------------------------|---------------|-------------------------|
| Account | `Account` | The authenticatable identity: id, login timestamps, soft-delete flag. Holds no personal data itself. | Profile |
| Profile | `AccountProfile` | Personal details attached 1:1 to an Account: name, phone, email, DOB, SSN, avatar. | Account |
| Identity / credentials | `AccountIdentity` | Password and OTP hash material, the password-reset token hash and the refresh-token hash. Never exposed through the API. | Profile |
| Role | `AccountRole` (`CUSTOMER`, `ADMIN`), `AccountOnRole` | A named permission bucket; an Account is placed in roles many-to-many. | — |
| File | `File` | A tracked upload: bytes in a Postgres `bytea` column, mime type, size. | an external object store; bytes live in the database |
| Notification | `Notification`, `NotificationRecipient` | A message plus the accounts it was sent to. | — |
| Sign-in code / OTP | OTP code | The one-time code sent to a phone number to authenticate; hashed at rest, 2 minute TTL, never logged. | JWT tokens, issued after verification |
| Password reset token | `resetTokenHash` | A random single-use token valid 30 minutes, stored only as a sha256 hash and sent to the account's email. | OTP code, refresh token |
| Refresh token | `refreshToken` | A long-lived JWT used only to get a new access token. Stored as sha256 (decision D5), not bcrypt. | Access token (short-lived, 15 min default) |

## Naming rules that follow from the above
- "Delete" always means a soft delete (`deleted` flag); there is no hard-delete vocabulary.
- Relationship names follow the Node base's PascalCase-per-model convention only if task 2.2 confirms it for SQLAlchemy.

## Status/enum vocabularies
| Enum | Values | Meaning of each |
|------|--------|-----------------|
| `AccountRoleType` | `CUSTOMER`, `ADMIN` | Who the account acts as; gates role checks. |
| `FileType` | `IMG`, `VIDEO` | Declared in the Node schema, never wired to logic there; confirm before relying on it (task 2.3). |
