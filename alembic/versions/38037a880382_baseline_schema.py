"""baseline schema

Revision ID: 38037a880382
Revises: 
Create Date: 2026-04-28 01:56:25.244473

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '38037a880382'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "profiles",
        # --- columns inherited from Base (database.py:45-53) ---
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # --- columns from Profile (models.py:10-17) ---
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("gender", sa.String(), nullable=False),
        sa.Column("gender_probability", sa.Float(), nullable=False),
        sa.Column("age", sa.Integer(), nullable=False),
        sa.Column("age_group", sa.String(), nullable=False),
        sa.Column("country_id", sa.String(length=20), nullable=False),
        sa.Column("country_name", sa.String(), nullable=False),
        sa.Column("country_probability", sa.Float(), nullable=False),
        # --- constraints ---
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # --- indexes (declared via index=True on the model) ---
    op.create_index("ix_profiles_name", "profiles", ["name"], unique=False)
    op.create_index("ix_profiles_age_group", "profiles", ["age_group"], unique=False)
    op.create_index("ix_profiles_country_id", "profiles", ["country_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_profiles_country_id", table_name="profiles")
    op.drop_index("ix_profiles_age_group", table_name="profiles")
    op.drop_index("ix_profiles_name", table_name="profiles")
    op.drop_table("profiles")
