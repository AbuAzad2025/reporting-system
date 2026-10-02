"""scope template customisation to a project, not a user

Revision ID: b7c1d4e9a210
Revises: de3bc9f3c093
Create Date: 2026-09-30

Why
---
`tenant_template_overrides` was designed so a *user* could customise a
template. Nothing in the application ever wrote the column: the override
functions had no production caller, so the table was inert (the reasoning is
recorded in docs/architecture/roadmap_reordered_fields.md).

It is now being wired up, and the scope is wrong for the requirement. A company
customises its report once; every engineer filling that report in sees the same
form. Scoping the override to `users.id` would have given a company of thirty
engineers thirty different forms.

So the row is keyed by `project_id` instead. `tenant_id` is left in place rather
than dropped: nothing in the application ever wrote it, but an operator could
have inserted rows by hand, and a migration that destroys data on the strength
of "the code never used it" is a worse default than one that does not. It is
marked legacy in the model and can be dropped once the rows are gone.

The old uniqueness constraint was on (template_key, tenant_id). With tenant_id
now nullable and unused, a company could otherwise store two conflicting
overrides for one template, and which one won would depend on row order. The
new constraint is on (template_key, project_id).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7c1d4e9a210'
down_revision = 'de3bc9f3c093'
branch_labels = None
depends_on = None


def _has_unique(table, name):
    """Whether a named unique constraint is present, tolerating SQLite.

    SQLite has no named-constraint introspection through Inspector on older
    builds, and the test suite runs on a file SQLite database, so every lookup
    here is best-effort and the migration is written to be re-runnable.
    """
    try:
        inspector = sa.inspect(op.get_bind())
        for constraint in inspector.get_unique_constraints(table):
            if constraint.get("name") == name:
                return True
    except Exception:
        return False
    return False


def upgrade():
    # The table only exists if the earlier baseline has been applied. On a
    # database bootstrapped by db.create_all() without Alembic history this is
    # a no-op, and that is the correct outcome rather than an error.
    if 'tenant_template_overrides' not in sa.inspect(
            op.get_bind()).get_table_names():
        return

    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns(
        "tenant_template_overrides")}

    if 'project_id' not in columns:
        op.add_column('tenant_template_overrides',
                      sa.Column('project_id', sa.Integer(), nullable=True))
        op.create_index('ix_tenant_template_overrides_project_id',
                        'tenant_template_overrides', ['project_id'])

    # The constraint swap goes through batch mode. SQLite cannot DROP CONSTRAINT
    # at all - the syntax does not exist - and it cannot add one either; batch
    # mode rewrites the table instead, which is also what the test suite runs
    # against, so the portable path is the only path that is exercised.
    old = _has_unique('tenant_template_overrides', 'uq_tenant_tpl_tenant')
    new = _has_unique('tenant_template_overrides', 'uq_tenant_tpl_project')
    if old == new:
        return

    with op.batch_alter_table('tenant_template_overrides') as batch:
        if old:
            batch.drop_constraint('uq_tenant_tpl_tenant', type_='unique')
        if not new:
            batch.create_unique_constraint('uq_tenant_tpl_project',
                                           ['template_key', 'project_id'])


def downgrade():
    if 'tenant_template_overrides' not in sa.inspect(
            op.get_bind()).get_table_names():
        return

    old = _has_unique('tenant_template_overrides', 'uq_tenant_tpl_tenant')
    new = _has_unique('tenant_template_overrides', 'uq_tenant_tpl_project')
    if old == new:
        return
    with op.batch_alter_table('tenant_template_overrides') as batch:
        if new:
            batch.drop_constraint('uq_tenant_tpl_project', type_='unique')
        if not old:
            batch.create_unique_constraint('uq_tenant_tpl_tenant',
                                           ['template_key', 'tenant_id'])
