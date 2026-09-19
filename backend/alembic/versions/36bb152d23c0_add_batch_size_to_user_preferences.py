"""add_batch_size_to_user_preferences

Revision ID: 36bb152d23c0
Revises: 69c4151aa633
Create Date: 2026-09-15 22:25:16.918961
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '36bb152d23c0'
down_revision = '69c4151aa633'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.add_column(sa.Column('batch_size', sa.Integer(), server_default='7', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('user_preferences', schema=None) as batch_op:
        batch_op.drop_column('batch_size')
