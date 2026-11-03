"""SeedHistory: which seed items ran (task 5.1).

Revision ID: 0002_seed_history
Revises: 0001_init

`0001_init` stays the final state of the Node schema, so the table the seed runner needs is a revision of its own.
It is not the Node `Migration` table (ADR-0018): that one recorded schema revisions, this one records seed items
(`name` unique, so a retried item updates its row).

Frozen like `0001_init`: it names the table and columns itself and imports nothing from `app`.

Rollback: `alembic downgrade 0001_init` drops the table. The history is gone with it, so on the next start the
runner decides again, item by item, from `needs_to_run`; a seed that does not guard itself would run twice.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_seed_history"
down_revision: str | None = "0001_init"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "SeedHistory",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "successful", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="SeedHistory_pkey"),
    )
    op.create_index("SeedHistory_name_key", "SeedHistory", ["name"], unique=True)


def downgrade() -> None:
    # The unique index goes with the table.
    op.drop_table("SeedHistory")
