# Domain glossary

> One meaning per term. This drives naming in code, database and UI copy.
> A new user-facing noun means a line here, in the same PR (rule E1).

Only the account tables are mapped so far (task 2.2). These are the terms inherited from the Node `poc-base`, which the scope doc ports with the
same table and column names. They are deliberately generic: a POC forked from this repo extends the table with its own
domain and does not repurpose these names. Python identifiers are decided for the account tables (task 2.2, see "Naming rules"); the Node name is still the reference.

| Term (client language) | Reference identifier (Node base) | Means exactly | Not to be confused with |
|------------------------|----------------------------------|---------------|-------------------------|
| Account | `Account` | The authenticatable identity: id, login timestamps, soft-delete flag. Holds no personal data itself. | Profile |
| Profile | `AccountProfile` | Personal details attached 1:1 to an Account: name, phone, email, DOB, avatar. | Account |
| Identity / credentials | `AccountIdentity` | Password and OTP hash material, the password-reset token hash and the refresh-token hash. Never exposed through the API. | Profile |
| Role | `AccountRole` (`CUSTOMER`, `ADMIN`), `AccountOnRole` | A named permission bucket; an Account is placed in roles many-to-many. | — |
| File | `File` | A tracked upload: bytes in a Postgres `bytea` column, mime type, size. | an external object store; bytes live in the database |
| Notification | `Notification`, `NotificationRecipient` | A message plus the accounts it was sent to. | — |
| Sign-in code / OTP | OTP code | The one-time code sent to a phone number to authenticate; hashed at rest, 2 minute TTL, never logged. | JWT tokens, issued after verification |
| Password reset token | `resetTokenHash` | A random single-use token valid 30 minutes, stored only as a sha256 hash and sent to the account's email. | OTP code, refresh token |
| Refresh token | `refreshToken` | A long-lived JWT used only to get a new access token. Stored as sha256 (decision D5), not bcrypt. | Access token (short-lived, 15 min default) |

## Naming rules that follow from the above
- "Delete" always means a soft delete (`deleted` flag); there is no hard-delete vocabulary.
- Python class names are the Node names (`Account`, `AccountOnRole`). Relationship attributes follow SQLAlchemy convention, not Prisma's
  PascalCase (ADR-0016): snake_case, singular for one row, plural for a collection (`Account.profile`, `Account.account_on_roles`,
  `AccountOnRole.account_role`; Prisma's `AccountRole.accounts`, which really means the accounts whose last role this is, is `last_role_accounts`). Column attributes are snake_case
  over the unchanged quoted column name (`first_name` for `"firstName"`, `is_phone_verified` for `"isPhoneVerified"`).
- The Node columns `"SSN"` and `"is18YearOld"` of `AccountProfile` are not part of this base (ADR-0015); do not add them back.
- The Node column `"dataOfBirth"` is a typo kept for schema parity (ADR-0004); the Python attribute is `date_of_birth`. It holds text, not a date.
- `refreshToken` and `resetTokenHash` keep their Node column names on `AccountIdentity`; both hold a sha256, never the token (rule P5).

## Status/enum vocabularies
| Enum | Values | Meaning of each |
|------|--------|-----------------|
| `AccountRoleType` | `CUSTOMER`, `ADMIN` | Who the account acts as; gates role checks. |
| `FileType` | `IMG`, `VIDEO` | Declared in the Node schema, never wired to logic there; confirm before relying on it (task 2.3). |
