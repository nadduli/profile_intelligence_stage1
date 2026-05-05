"""add profile query indexes

Revision ID: 5457380f5462
Revises: 3a8d5ff6c0e4
Create Date: 2026-05-05 15:23:03.438061

Two indexes for the Stage 4b query optimization:

1. ix_profiles_country_gender_age — composite on (country_id, gender, age).
   Covers the dominant filter pattern: WHERE country_id = X [AND gender = Y]
   [AND age BETWEEN A AND B]. Column order is highest-cardinality-first so
   the prefix is usable on its own (queries that only filter by country
   still benefit). This replaces the role of the existing single-column
   country_id index for combined-filter queries.

2. ix_profiles_created_at_desc — descending B-tree on created_at. Covers
   the API's default sort (ORDER BY created_at DESC LIMIT N) on unfiltered
   list queries. Without this, /api/profiles?limit=10 reads and sorts the
   whole table; with it, Postgres walks the index backward and stops at N.

Existing single-column indexes on country_id and age_group are kept — they
have negligible storage cost and cover queries that filter by only one of
those columns.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5457380f5462'
down_revision: Union[str, Sequence[str], None] = '3a8d5ff6c0e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_profiles_country_gender_age",
        "profiles",
        ["country_id", "gender", "age"],
    )
    op.create_index(
        "ix_profiles_created_at_desc",
        "profiles",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_profiles_created_at_desc", table_name="profiles")
    op.drop_index("ix_profiles_country_gender_age", table_name="profiles")
