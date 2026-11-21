from alembic import op
from app.models.data import StorageDeletion

revision = '0002_deletion_cleanup'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    StorageDeletion.__table__.create(op.get_bind(), checkfirst=True)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION reject_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP = 'DELETE' AND current_setting('science_extract.allow_revision_delete', true) = 'on' THEN
                RETURN OLD;
              END IF;
              RAISE EXCEPTION 'scientific revisions are immutable';
            END; $$""")


def downgrade():
    StorageDeletion.__table__.drop(op.get_bind(), checkfirst=True)
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""CREATE OR REPLACE FUNCTION reject_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'scientific revisions are immutable'; END; $$""")
