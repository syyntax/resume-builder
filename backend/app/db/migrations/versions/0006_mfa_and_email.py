"""Hardening: TOTP MFA (user fields, recovery codes, session stage), email verification, user preferences

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('recovery_code',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('user_id', sa.String(length=40), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('fk_recovery_code_user_id_user'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recovery_code'))
    )
    with op.batch_alter_table('recovery_code', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recovery_code_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('session', schema=None) as batch_op:
        batch_op.add_column(sa.Column('stage', sa.String(length=8), server_default='active', nullable=False))
        batch_op.create_check_constraint(op.f('ck_session_stage'), sa.text("stage IN ('active', 'mfa', 'enroll')"))

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('mfa_enabled', sa.Boolean(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('totp_ciphertext', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('totp_nonce', sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column('totp_key_fingerprint', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('totp_last_step', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('preferences', sa.JSON().with_variant(
            postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True))

    # Accounts made before email verification existed count as verified.
    op.execute(sa.text('UPDATE "user" SET email_verified_at = created_at'))


def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('preferences')
        batch_op.drop_column('totp_last_step')
        batch_op.drop_column('totp_key_fingerprint')
        batch_op.drop_column('totp_nonce')
        batch_op.drop_column('totp_ciphertext')
        batch_op.drop_column('mfa_enabled')
        batch_op.drop_column('email_verified_at')

    with op.batch_alter_table('session', schema=None) as batch_op:
        batch_op.drop_constraint(op.f('ck_session_stage'), type_='check')
        batch_op.drop_column('stage')

    with op.batch_alter_table('recovery_code', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recovery_code_user_id'))
    op.drop_table('recovery_code')
