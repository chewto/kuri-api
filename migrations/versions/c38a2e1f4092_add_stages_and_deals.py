"""add stages and deals tables

Revision ID: c38a2e1f4092
Revises: f755aad6da27
Create Date: 2026-10-27 23:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c38a2e1f4092'
down_revision = 'f755aad6da27'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create the stages table
    op.create_table(
        'stages',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('probability', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('stages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stages_tenant_id'), ['tenant_id'], unique=False)

    # 2. Create the deals table
    op.create_table(
        'deals',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('company_id', sa.String(length=36), nullable=False),
        sa.Column('contact_id', sa.String(length=36), nullable=True),
        sa.Column('stage_id', sa.String(length=36), nullable=False),
        sa.Column('title', sa.String(length=120), nullable=False),
        sa.Column('value', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('expected_close_date', sa.Date(), nullable=True),
        sa.Column('status', sa.Enum('open', 'won', 'lost', name='deal_status_enum'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['stage_id'], ['stages.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deals_tenant_id'), ['tenant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_deals_company_id'), ['company_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_deals_contact_id'), ['contact_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_deals_stage_id'), ['stage_id'], unique=False)


def downgrade():
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deals_stage_id'))
        batch_op.drop_index(batch_op.f('ix_deals_contact_id'))
        batch_op.drop_index(batch_op.f('ix_deals_company_id'))
        batch_op.drop_index(batch_op.f('ix_deals_tenant_id'))

    op.drop_table('deals')

    with op.batch_alter_table('stages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stages_tenant_id'))

    op.drop_table('stages')

    # Alembic does not drop the native PostgreSQL enum when the table is dropped.
    if op.get_bind().dialect.name == "postgresql":
        op.execute('DROP TYPE IF EXISTS deal_status_enum')
