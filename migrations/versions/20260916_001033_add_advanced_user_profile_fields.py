"""add advanced user profile fields

Revision ID: 20260916_001033
Revises: 20260915_212205
Create Date: 2026-09-16 00:10:33
"""
from alembic import op
import sqlalchemy as sa


revision = '20260916_001033'
down_revision = '20260915_212205'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar', sa.String(length=260), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('job_title', sa.String(length=120), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('department', sa.String(length=120), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('certification', sa.String(length=200), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('notification_prefs', sa.JSON(), nullable=False, server_default='{"email": true, "sms": false, "push": true, "in_app": true}'))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('notification_prefs')
        batch_op.drop_column('certification')
        batch_op.drop_column('department')
        batch_op.drop_column('job_title')
        batch_op.drop_column('avatar')