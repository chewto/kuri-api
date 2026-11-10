"""translate default stage names

Revision ID: a1b2c3d4e5f6
Revises: c38a2e1f4092
Create Date: 2026-11-10 11:00:00.000000

Renames the default pipeline stages seeded before the UI was translated to
English. Rows are matched on their original name, order, and probability so
custom stages created by users are left untouched.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'c38a2e1f4092'
branch_labels = None
depends_on = None


STAGE_RENAMES = [
    ('Prospección', 'Prospecting', 1, 10),
    ('Calificado', 'Qualified', 2, 25),
    ('Propuesta Enviada', 'Proposal Sent', 3, 50),
    ('Negociación', 'Negotiation', 4, 75),
    ('Cerrado Ganado', 'Closed Won', 5, 100),
    ('Cerrado Perdido', 'Closed Lost', 6, 0),
]


def _rename_stages(pairs):
    bind = op.get_bind()
    statement = sa.text(
        'UPDATE stages '
        'SET name = :new_name '
        'WHERE name = :old_name '
        'AND "order" = :stage_order '
        'AND probability = :probability'
    )
    for old_name, new_name, stage_order, probability in pairs:
        bind.execute(
            statement,
            {
                'old_name': old_name,
                'new_name': new_name,
                'stage_order': stage_order,
                'probability': probability,
            },
        )


def upgrade():
    _rename_stages(STAGE_RENAMES)


def downgrade():
    _rename_stages([(new, old, order, prob) for old, new, order, prob in STAGE_RENAMES])
