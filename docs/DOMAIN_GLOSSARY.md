# Domain glossary

> One meaning per term. This drives naming in code, database and UI copy.
> A new user-facing noun means a line here, in the same PR (rule E1).

The account tables (task 2.2) and the file, notification and system tables (task 2.3) are mapped. These are the terms inherited from the Node `poc-base`, which the scope doc ports with the
same table and column names. They are deliberately generic: a POC forked from this repo extends the table with its own
domain and does not repurpose these names. Python identifiers are decided for all of them (tasks 2.2 and 2.3, see "Naming rules"); the Node name is still the reference.

| Term (client language) | Reference identifier (Node base) | Means exactly | Not to be confused with |
|------------------------|----------------------------------|---------------|-------------------------|
| Account | `Account` | The authenticatable identity: id, login timestamps, soft-delete flag. Holds no personal data itself. | Profile |
| Profile | `AccountProfile` | Personal details attached 1:1 to an Account: name, phone, email, DOB, avatar. | Account |
| Identity / credentials | `AccountIdentity` | Password and OTP hash material, the password-reset token hash and the refresh-token hash. Never exposed through the API. | Profile |
| Role | `AccountRole` (`CUSTOMER`, `ADMIN`), `AccountOnRole` | A named permission bucket; an Account is placed in roles many-to-many. | — |
| File | `File` | A tracked upload: bytes in a Postgres `bytea` column, mime type, size. | an external object store; bytes live in the database |
| Notification | `Notification`, `NotificationRecipient` | A message plus the accounts it was sent to. | — |
| Deletion record | `DeletedHistory` | A bookkeeping row naming a record that was deleted (`relationId`), by whom (`deletedBy`, optional) and a `deletedAt` flag. No code writes it yet. | Soft delete: the `deleted` column on domain tables is what marks a row deleted |
| Sign-in code / OTP | OTP code | The one-time code sent to a phone number to authenticate; hashed at rest, 2 minute TTL, never logged. | JWT tokens, issued after verification |
| Password reset token | `resetTokenHash` | A random single-use token valid 30 minutes, stored only as a sha256 hash and sent to the account's email. | OTP code, refresh token |
| Refresh token | `refreshToken` | A long-lived JWT used only to get a new access token. Stored as sha256 (decision D5), not bcrypt. | Access token (short-lived, 15 min default) |

## Naming rules that follow from the above
- "Delete" always means a soft delete (`deleted` flag); there is no hard-delete vocabulary.
- Python class names are the Node names (`Account`, `AccountOnRole`). Relationship attributes follow SQLAlchemy convention, not Prisma's
  PascalCase (ADR-0016): snake_case, singular for one row, plural for a collection (`Account.profile`, `Account.account_on_roles`,
  `AccountOnRole.account_role`; Prisma's `AccountRole.accounts`, which really means the accounts whose last role this is, is `last_role_accounts`). Column attributes are snake_case
  over the unchanged quoted column name (`first_name` for `"firstName"`, `is_phone_verified` for `"isPhoneVerified"`).
- Task 2.3 relationship names, same rule: `Account.files` (the files an account created) with `File.created_by`; `File.account_profiles` with `AccountProfile.avatar`;
  `Account.notification_recipients` and `Notification.notification_recipients` with `NotificationRecipient.account` and `.notification`.
- `DeletedHistory.deletedAt` is a boolean flag despite its name, kept for schema parity like `dataOfBirth`; the Python attribute is `deleted_at`.
  `DeletedHistory` carries no `deleted` column, as in the Node schema, so "Delete always means a soft delete" does not apply to its rows.
- The Node `Migration` table is not part of this base (ADR-0018): applied schema revisions are recorded by Alembic in `alembic_version`; do not add it back.
- The Node columns `"SSN"` and `"is18YearOld"` of `AccountProfile` are not part of this base (ADR-0015); do not add them back.
- The Node column `"dataOfBirth"` is a typo kept for schema parity (ADR-0004); the Python attribute is `date_of_birth`. It holds text, not a date.
- `refreshToken` and `resetTokenHash` keep their Node column names on `AccountIdentity`; both hold a sha256, never the token (rule P5).

## Status/enum vocabularies
| Enum | Values | Meaning of each |
|------|--------|-----------------|
| `AccountRoleType` | `CUSTOMER`, `ADMIN` | Who the account acts as; gates role checks. |
| `FileType` | `IMG`, `VIDEO` | Declared in the Node schema, never wired to logic there. The Postgres type exists (task 2.3) but no column uses it; do not rely on it. |
