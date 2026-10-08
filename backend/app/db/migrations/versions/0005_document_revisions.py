"""Formats and templates: document revisions, to undo fit to page

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07 18:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0005'
down_revision: str | None = '0004'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql')


def upgrade() -> None:
    op.create_table('document_revision',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('owner_id', sa.String(length=40), nullable=False),
    sa.Column('document_id', sa.String(length=40), nullable=False),
    sa.Column('content', JSON, nullable=False),
    sa.Column('design', JSON, nullable=True),
    sa.Column('reason', sa.String(length=32), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], name=op.f('fk_document_revision_document_id_document'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['user.id'], name=op.f('fk_document_revision_owner_id_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_revision'))
    )
    with op.batch_alter_table('document_revision', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_revision_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_revision_owner_id'), ['owner_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('document_revision', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_revision_owner_id'))
        batch_op.drop_index(batch_op.f('ix_document_revision_document_id'))
    op.drop_table('document_revision')
