"""lia rli condition

Revision ID: 7d3f0b8e6a15
Revises: 5c1e7a2d9b04
Create Date: 2026-11-04 07:43:22.478524

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7d3f0b8e6a15'
down_revision: Union[str, Sequence[str], None] = '5c1e7a2d9b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    sa.Enum('NATIONAL_SECURITY_DEFENCE', 'EMERGENCIES', 'CRIME', 'SAFEGUARDING_VULNERABLE', 'PUBLIC_INTEREST_DISCLOSURE_REQUEST', name="rlicondition").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column('lia_rli_record', sa.Column('rli_condition', sa.Enum('NATIONAL_SECURITY_DEFENCE', 'EMERGENCIES', 'CRIME', 'SAFEGUARDING_VULNERABLE', 'PUBLIC_INTEREST_DISCLOSURE_REQUEST', name='rlicondition'), nullable=True))



def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('lia_rli_record', 'rli_condition')
    sa.Enum(name="rlicondition").drop(op.get_bind(), checkfirst=True)

