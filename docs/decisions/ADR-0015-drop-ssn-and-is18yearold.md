# ADR-0015 — Drop `SSN` and `is18YearOld` from `AccountProfile`

- **Date:** 2026-10-31
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-2.2
- **Amends:** the schema-parity target of [ADR-0004](ADR-0004-data-layer-sqlalchemy-alembic.md) by two columns. ADR-0004 otherwise stands.

## Context
The Node base's `AccountProfile` has two columns this base does not need: `SSN` (text) and `is18YearOld` (boolean, default false). ADR-0004 makes
the Prisma schema a parity target, proven by task 2.5, so leaving them out is a decision, not an oversight. The human's reason: "no need for this project".

## Decision
- The `AccountProfile` model, the first Alembic revision (2.4) and the REST contract have no `SSN` and no `is18YearOld`.
- Every other `AccountProfile` column keeps its Prisma name and shape, including `dataOfBirth`.
- Task 2.5's `pg_dump --schema-only` diff expects exactly these two columns to differ; any further difference is still a finding.

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep both columns for exact parity | the project does not need them, and `SSN` would be a sensitive column with no use |
| Keep the columns but leave them out of the API | an unused column in the schema that a fork might start filling |

## Consequences
- Positive: a smaller profile table and REST contract.
- Accepted cost: the schema is not byte-identical to the Node base's, so 2.5 must explain these two lines.
- Follow-ups: 2.4 must not create the columns; 2.5 lists them as the explained differences; task 5.4 (profile update) has no `SSN` or `is18YearOld` input. Log redaction of the name `ssn` (ADR-0013, `app/core/logging.py`) is generic and stays.

## Revisit when
A forked POC needs either field; it adds the column with its own migration, not by changing this base.
