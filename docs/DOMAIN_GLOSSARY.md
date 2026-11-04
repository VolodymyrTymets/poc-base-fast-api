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
| Sign-in code / OTP | OTP code | The one-time code sent to a phone number to authenticate; hashed at rest with Argon2id (ADR-0028; `otpSalt` is unused, the salt is in the hash), 2 minute TTL, never logged. | JWT tokens, issued after verification |
| Secret hash | `hash_secret`, `verify_secret` (`app/core/hashing.py`) | An Argon2id hash whose salt and cost are inside the string; used for the sign-in code and, from task 7.3, passwords. | The sha256 of a refresh or reset token (ADR-0008), which is a fast hash of a high-entropy value |
| Password reset token | `resetTokenHash` | A random single-use token valid 30 minutes, stored only as a sha256 hash and sent to the account's email. | OTP code, refresh token |
| Seed item | none (Node: migration item) | One unit of base data the app creates for itself (the two roles; in development environments also the sample admin and three sample customers). It has a unique name, a check for whether it is needed, and a run. Never a schema change. | Alembic revision, which changes the schema |
| Seed history | `SeedHistory` (Node: `Migration`, a different table) | One row per seed item: whether its last run succeeded and, if not, the error text. Updated in place on a retry. | `alembic_version`, which records schema revisions |
| Job | none (Node: a BullMQ job) | A named unit of background work the API hands to the worker with JSON arguments (`ping`, `send_totp_code` and `send_password_reset`; both senders only log, no provider). Tried at most 3 times; its result is not kept. | Seed item, which runs once at boot |
| Notifier | `NotifierService` (Node: `NotifierService` and its three channel services) | Hands a sign-in code or a password-reset token to the chosen channels: `SMS` (job `send_totp_code`), `EMAIL` (job `send_password_reset`), `LOG` (a log line that never holds the code or token), `ALL` (the three). A queue that is down is logged, never raised. | The worker jobs it enqueues; the Node `LogNotifierService`, which logged the code |
| Queue client | none | The `QueueClient` protocol (`enqueue(job_name, *args, **kwargs)`) that services use to hand over a job; `ArqQueueClient` in production, `FakeQueue` in tests. | The worker, which runs jobs |
| Refresh token | `refreshToken` | A long-lived JWT used only to get a new access token. Stored as sha256 hex in `AccountIdentity.refreshToken` (decision D5, `hash_token`), not bcrypt or Argon2; every sign-in replaces it, so the previous refresh token stops matching (task 7.2). | Access token (short-lived, 15 min default) |

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
- The Node `Migration` table is not part of this base (ADR-0018): applied schema revisions are recorded by Alembic in `alembic_version`; do not add it back. The Node base also used it to record its seed items ("migrations" in its code); here that job belongs to `SeedHistory` (task 5.1), and "migration" means only a schema revision.
- The Node columns `"SSN"` and `"is18YearOld"` of `AccountProfile` are not part of this base (ADR-0015); do not add them back.
- The Node column `"dataOfBirth"` is a typo kept for schema parity (ADR-0004); the Python attribute is `date_of_birth`. It holds text, not a date.
- `refreshToken` and `resetTokenHash` keep their Node column names on `AccountIdentity`; both hold a sha256, never the token (rule P5).

## Status/enum vocabularies
| Enum | Values | Meaning of each |
|------|--------|-----------------|
| `AccountRoleType` | `CUSTOMER`, `ADMIN` | Who the account acts as; gates role checks. |
| `FileType` | `IMG`, `VIDEO` | Declared in the Node schema, never wired to logic there. The Postgres type exists (task 2.3) but no column uses it; do not rely on it. |
