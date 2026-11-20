# Назначение файла: initial revision всех технических таблиц, FK/unique и JSONB.
from alembic import op
from app.db import Base
import app.models.auth
import app.models.data

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())
    if op.get_bind().dialect.name == 'postgresql':
        # Revisions are immutable even if an accidental adapter attempts UPDATE/DELETE.
        op.execute("""CREATE FUNCTION reject_revision_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN RAISE EXCEPTION 'scientific revisions are immutable'; END; $$""")
        for table in ('publication_revisions', 'classification_revisions'):
            op.execute(f'CREATE TRIGGER immutable_revision BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_revision_mutation()')
        op.execute("CREATE INDEX ix_pages_fts ON pages USING gin(to_tsvector('simple', text))")


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP FUNCTION IF EXISTS reject_revision_mutation()')
