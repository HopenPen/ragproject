from sqlalchemy import select, Uuid
from uuid import UUID
from sqlalchemy.inspection import inspect
from app.models.auth import User, RefreshSession
from app.models.data import (Corpus, Document, Page, Artifact, Job, JobItem, Outbox, Publication,
                             PublicationRevision, ClassificationRevision, Issue, AuditEntry)
from app.repositories.auth import AuthRepository

TABLES = {c.__tablename__: c for c in (User, RefreshSession, Corpus, Document, Page, Artifact, Job, JobItem,
          Outbox, Publication, PublicationRevision, ClassificationRevision, Issue, AuditEntry)}


def mapping(obj):
    return {c.key: getattr(obj, c.key) for c in inspect(type(obj)).columns} if obj else None


class Repo(AuthRepository):
    def __init__(self, session):
        self.session = session

    def get(self, table, id, lock=False):
        try:
            UUID(str(id))
        except (ValueError, TypeError):
            return None
        query = select(TABLES[table]).where(TABLES[table].id == id)
        if lock:
            query = query.with_for_update()
        return mapping(self.session.scalars(query.execution_options(populate_existing=True)).first())

    def find(self, table, **filters):
        cls = TABLES[table]
        query = select(cls)
        for key, value in filters.items():
            column = getattr(cls, key)
            if isinstance(column.type, Uuid) and value is not None:
                try:
                    for val in value if isinstance(value,(list,tuple,set)) else [value]:
                        UUID(str(val))
                except (ValueError, TypeError):
                    return []
            query = query.where(column.in_(value) if isinstance(value, (list, tuple, set)) else column == value)
        order = (cls.number, cls.id) if table in ('pages', 'publication_revisions', 'classification_revisions') else (cls.created_at, cls.id)
        return [mapping(o) for o in self.session.scalars(query.order_by(*order))]

    def add(self, table, **values):
        obj = TABLES[table](**values)
        self.session.add(obj)
        self.session.flush()
        return mapping(obj)

    def update(self, table, id, **values):
        if table in ('publication_revisions', 'classification_revisions'):
            raise ValueError('Immutable revision')
        obj = self.session.get(TABLES[table], id)
        for key, value in values.items():
            setattr(obj, key, value)
        self.session.flush()
        return mapping(obj)

    def delete(self, table, id):
        if table.endswith('_revisions'):
            raise ValueError('Immutable revision')
        self.session.delete(self.session.get(TABLES[table], id))
        self.session.flush()

    def search(self, corpus_id, q, scope):
        # ILIKE preserves scientific symbols; no separate search service is required.
        docs = self.find('documents', corpus_id=corpus_id)
        ids = [d['id'] for d in docs]
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        matches = []
        if scope in ('text', 'all'):
            query = select(Page).where(Page.document_id.in_(ids), Page.text.ilike(pattern, escape='\\'))
            matches += [{'document_id': p.document_id, 'page': p.number, 'snippet': p.text[max(0, p.text.casefold().find(q.casefold())-80):][:400]} for p in self.session.scalars(query)]
        if scope in ('metadata', 'all'):
            for doc in docs:
                pubs = self.find('publications', document_id=doc['id'])
                bibliography = []
                for pub in pubs:
                    bibliography += [self.get('publication_revisions', rid)['graph']['bibliography'] for rid in pub['current'].values()]
                if q.casefold() in str([doc['publication_code'], doc['display_name'], doc['note'], bibliography]).casefold():
                    matches.append({'document_id': doc['id'], 'page': None, 'snippet': str(bibliography)[:400] or doc['display_name']})
        return sorted(matches, key=lambda x: (x['document_id'], x['page'] or 0))
