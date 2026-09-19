"""add_created_by_admin_to_folders

Revision ID: 7a8b9c0d1e2f
Revises: 36bb152d23c0
Create Date: 2026-09-17 18:30:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '7a8b9c0d1e2f'
down_revision = '36bb152d23c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_admin', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('folders', schema=None) as batch_op:
        batch_op.drop_column('created_by_admin')
