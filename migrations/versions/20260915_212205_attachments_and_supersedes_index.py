"""attachments table + supersedes_id index

Revision ID: 20260915_212205
Revises: 10f7c5e73f7a
Create Date: 2026-09-15 21:22:05
"""
from alembic import op
import sqlalchemy as sa


revision = '20260915_212205'
down_revision = 'ea65d1dae50d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ops_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('record_kind', sa.String(length=40), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=260), nullable=False),
        sa.Column('storage_key', sa.String(length=120), nullable=False),
        sa.Column('mime_type', sa.String(length=80), nullable=False),
        sa.Column('byte_size', sa.Integer(), nullable=False),
        sa.Column('uploaded_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('ops_attachments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ops_attachments_record_kind'),
                              ['record_kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_ops_attachments_record_id'),
                              ['record_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ops_attachments_project'),
                              ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ops_attachments_storage_key'),
                              ['storage_key'], unique=True)
        batch_op.create_index(batch_op.f('ix_ops_attachments_uploaded_by'),
                              ['uploaded_by'], unique=False)

    op.create_index('ix_ops_attachments_kind_record',
                    'ops_attachments', ['record_kind', 'record_id'])


def downgrade():
    op.drop_index('ix_ops_attachments_kind_record',
                  table_name='ops_attachments')
    with op.batch_alter_table('ops_attachments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ops_attachments_uploaded_by'))
        batch_op.drop_index(batch_op.f('ix_ops_attachments_storage_key'))
        batch_op.drop_index(batch_op.f('ix_ops_attachments_project'))
        batch_op.drop_index(batch_op.f('ix_ops_attachments_record_id'))
        batch_op.drop_index(batch_op.f('ix_ops_attachments_record_kind'))
    op.drop_table('ops_attachments')