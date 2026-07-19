"""normalize subscription_plan casing

Revision ID: 21d39bab6abd
Revises: 5d892b1c63a4
Create Date: 2026-07-19 21:25:44.209722+00:00

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '21d39bab6abd'
down_revision: Union[str, None] = '5d892b1c63a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fixes a real data-corruption bug: the `subscription_plan` Enum column
    # lacked `values_callable`, so SQLAlchemy bound/read it by enum MEMBER
    # NAME ("TRIAL") instead of `.value` ("trial") for ORM-created rows,
    # while this table's own server_default (and every JSON response
    # elsewhere) used `.value`. Rows created via the ORM before the model
    # fix ended up stored as "TRIAL"/"FREE"/etc — unreadable once the model
    # is corrected to expect lowercase consistently. Normalize every value
    # to lowercase so both old and new rows agree with the fixed model.
    op.execute("UPDATE organizations SET subscription_plan = lower(subscription_plan)")


def downgrade() -> None:
    # No meaningful reverse: which rows were originally upper vs lower case
    # is not recoverable after the forward migration has run.
    pass
