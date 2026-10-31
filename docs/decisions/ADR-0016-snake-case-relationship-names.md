# ADR-0016 — Name ORM relationships in snake_case, not Prisma's PascalCase

- **Date:** 2026-10-31
- **Status:** accepted
- **Deciders:** volodymyr
- **Ticket:** POC-2.2
- **Overrides:** the "PascalCase relationships (P1)" wording of scope-doc row 2.2, and the glossary line that left it open "only if task 2.2 confirms it for SQLAlchemy".

## Context
The Node base names relations after their model (`Account.AccountProfile`, `AccountRole.AccountOnRole`). The scope doc carried that over. In Python it is
unconventional: PEP 8 and the SQLAlchemy documentation name attributes in snake_case, singular for one row and plural for a collection. It also caused a bug
here: an attribute named `AccountRole` on the `AccountRole` class made an annotation such as `Mapped[AccountRole]` resolve to the attribute, and
`configure_mappers()` recursed forever (mypy did not notice), which needed a string-target workaround. The human's direction: follow SQLAlchemy best practice, not Prisma style.

## Decision
- Relationship attributes are snake_case: singular for a scalar, plural for a collection, named for what they hold. Class names and table and column names are unchanged.
- Annotations use the plain pattern, `relationship(back_populates="...")` with no string target.
- The names for the account models:

| Model | Relationships |
|-------|---------------|
| `Account` | `identity`, `profile`, `account_on_roles`, `last_account_role` |
| `AccountRole` | `account_on_roles`, `last_role_accounts` |
| `AccountOnRole` | `account_role`, `account` |
| `AccountIdentity`, `AccountProfile` | `account` |

- `last_role_accounts` is Prisma's `AccountRole.accounts`, renamed because it holds the accounts whose *last used* role this is, not every account with the role.
- Tasks 2.3 and later follow the same rule (`AccountProfile.avatar`, `Account.files`, `Account.notification_recipients`).

## Rejected alternatives
| Alternative | Why not |
|-------------|---------|
| Keep Prisma's PascalCase for parity with the Node names | parity matters for tables and columns (the database), not for Python attributes, which no database or client sees; it breaks Python convention and needed a workaround |
| snake_case but keep the Prisma singular for collections (`account_on_role`) | a collection that reads as one row |

## Consequences
- Positive: conventional, readable models; no shadowing between an attribute and its class.
- Accepted cost: a reader comparing with the Node code maps names by hand; the glossary lists them.
- Follow-ups: `docs/DOMAIN_GLOSSARY.md` carries the naming rule; 2.3 uses it for the `File` and `Notification*` relationships.

## Revisit when
The project generates code or an API from relationship names that must match the Node base.
