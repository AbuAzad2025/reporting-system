"""ws3: ops feedback comments + DSR workflow tables

Revision ID: 20260916_ws3
Revises: 20260916_001033
Create Date: 2026-09-16
"""
from alembic import op
import sqlalchemy as sa


revision = '20260916_ws3'
down_revision = '20260916_001033'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ops_record_comments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('record_kind', sa.String(length=40), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('author_name', sa.String(length=200), nullable=False),
        sa.Column('author_role', sa.String(length=30), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('ops_record_comments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ops_record_comments_record_kind'),
                              ['record_kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_ops_record_comments_record_id'),
                              ['record_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ops_record_comments_project'),
                              ['project_id'], unique=False)
    op.create_index('ix_cmt_kind_record', 'ops_record_comments',
                    ['record_kind', 'record_id'])
    op.create_index('ix_cmt_project', 'ops_record_comments', ['project_id'])

    with op.batch_alter_table('daily_reports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('labor_table', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('equipment_table', sa.JSON(),
                                      nullable=True))
        batch_op.add_column(sa.Column('work_fronts', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('daily_reports', schema=None) as batch_op:
        batch_op.drop_column('work_fronts')
        batch_op.drop_column('equipment_table')
        batch_op.drop_column('labor_table')
    op.drop_index('ix_cmt_project', table_name='ops_record_comments')
    op.drop_index('ix_cmt_kind_record', table_name='ops_record_comments')
    with op.batch_alter_table('ops_record_comments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ops_record_comments_project'))
        batch_op.drop_index(batch_op.f('ix_ops_record_comments_record_id'))
        batch_op.drop_index(batch_op.f('ix_ops_record_comments_record_kind'))
    op.drop_table('ops_record_comments')
