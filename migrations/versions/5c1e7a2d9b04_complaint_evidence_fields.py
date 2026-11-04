"""complaint evidence fields

Revision ID: 5c1e7a2d9b04
Revises: babc0f3203da
Create Date: 2026-11-04 07:43:22.251823

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c1e7a2d9b04'
down_revision: Union[str, Sequence[str], None] = 'babc0f3203da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('complaint_record', sa.Column('enquiries_note', sa.Text(), nullable=True))
    op.add_column('complaint_record', sa.Column('progress_updates', sa.Text(), nullable=True))
    op.add_column('complaint_record', sa.Column('outcome_communicated_at', sa.DateTime(), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('complaint_record', 'outcome_communicated_at')
    op.drop_column('complaint_record', 'progress_updates')
    op.drop_column('complaint_record', 'enquiries_note')

