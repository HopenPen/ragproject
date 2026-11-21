from datetime import timedelta
from sqlalchemy import delete, update, select, text
from app.domain import Error, corpus_access, require_editor, now
from app.db import Uow
from app.models.data import (Corpus, Document, Page, Artifact, Job, JobItem, Outbox,
    Publication, PublicationRevision, ClassificationRevision, Issue, AuditEntry, StorageDeletion)


def queue_files(u, keys):
    keys = set(k for k in keys if k)
    prefixes = [key for key in keys if key.endswith('/')]
    for key in sorted(k for k in keys if k in prefixes or not any(k.startswith(prefix) for prefix in prefixes)):
        if not u.repo.find('storage_deletions', storage_key=key):
            u.repo.add('storage_deletions', storage_key=key)


def delete_rows(u, model, condition):
    u.session.execute(delete(model).where(condition).execution_options(synchronize_session=False))


class Deletions:
    def __init__(self, uow):
        self.uow = uow

    def remove(self, actor, corpus_id=None, document_id=None):
        with self.uow() as u:
            doc = u.repo.get('documents', document_id) if document_id else None
            if document_id and not doc:
                raise Error(404, 'not_found', 'Document not found')
            corpus_id = doc['corpus_id'] if doc else corpus_id
            corpus = corpus_access(u.repo.get('corpora', corpus_id, lock=True), actor)
            require_editor(actor)
            # Archived corpora may also be explicitly deleted by their owner/admin.
            docs = [doc] if doc else u.repo.find('documents', corpus_id=corpus_id)
            doc_ids = [d['id'] for d in docs]
            jobs = []
            for row in sorted(u.repo.find('jobs', corpus_id=corpus_id), key=lambda j: j['id']):
                row = u.repo.get('jobs', row['id'], lock=True)
                items = u.repo.find('job_items', job_id=row['id'])
                selected = set(row['input'].get('selected_document_ids', []))
                relevant = not document_id or document_id in selected or any(i['document_id'] == document_id for i in items)
                if not relevant:
                    continue
                for item in items:
                    item = u.repo.get('job_items', item['id'], lock=True)
                    if item['status'] == 'running':
                        raise Error(409, 'processing_active', 'Pause or cancel processing and wait for it to stop before deleting')
                jobs.append((row, items))
            keys = [d['storage_key'] for d in docs]
            keys += [f'documents/{d["id"]}/' for d in docs]
            keys += [f'corpora/{corpus_id}/documents/{d["id"]}/' for d in docs]
            pages = u.repo.find('pages', document_id=doc_ids) if doc_ids else []
            artifacts = u.repo.find('artifacts', document_id=doc_ids) if doc_ids else []
            keys += [p['image_key'] for p in pages] + [a['storage_key'] for a in artifacts]
            for job, items in jobs:
                snapshot_job = job['kind'] in ('validate', 'export')
                removed = items if not document_id or snapshot_job else [i for i in items if i['document_id'] == document_id]
                item_ids = [i['id'] for i in removed]
                if item_ids:
                    delete_rows(u, Outbox, Outbox.item_id.in_(item_ids))
                    delete_rows(u, JobItem, JobItem.id.in_(item_ids))
                if snapshot_job or not document_id:
                    keys.append(job['result'].get('storage_key'))
                    keys.append(f'jobs/{job["id"]}/')
                if document_id:
                    payload = {k: v for k, v in job['input'].items() if k not in ('snapshot', 'document_ids', 'selected_document_ids')}
                    remaining = [i['document_id'] for i in items if i not in removed and i['document_id']]
                    payload.update(document_ids=remaining, selected_document_ids=remaining, all_documents=False)
                    u.repo.update('jobs', job['id'], input=payload, result={}, expires_at=None,
                                  status='cancelled' if snapshot_job or not remaining else job['status'],
                                  error='A source document was deleted' if snapshot_job else job['error'])
                    if remaining and not snapshot_job:
                        from app.services.pipeline import aggregate
                        aggregate(u.repo, job['id'])
            pubs = u.repo.find('publications', document_id=doc_ids) if doc_ids else []
            pub_ids = [p['id'] for p in pubs]
            if u.session.bind.dialect.name == 'postgresql':
                # Only this explicit purge can delete revisions; UPDATE stays forbidden.
                u.session.execute(text("SET LOCAL science_extract.allow_revision_delete = 'on'"))
            if doc_ids:
                u.session.execute(update(Document).where(Document.id.in_(doc_ids)).values(classification_id=None))
                delete_rows(u, Issue, Issue.publication_id.in_(pub_ids))
                delete_rows(u, AuditEntry, (AuditEntry.document_id.in_(doc_ids)) | (AuditEntry.publication_id.in_(pub_ids)))
                delete_rows(u, PublicationRevision, PublicationRevision.publication_id.in_(pub_ids))
                delete_rows(u, Publication, Publication.id.in_(pub_ids))
                delete_rows(u, ClassificationRevision, ClassificationRevision.document_id.in_(doc_ids))
                delete_rows(u, Page, Page.document_id.in_(doc_ids))
                delete_rows(u, Artifact, Artifact.document_id.in_(doc_ids))
                delete_rows(u, Document, Document.id.in_(doc_ids))
            if not document_id:
                job_ids = [j['id'] for j, _ in jobs]
                delete_rows(u, Issue, Issue.corpus_id == corpus_id)
                delete_rows(u, AuditEntry, AuditEntry.corpus_id == corpus_id)
                if job_ids:
                    u.session.execute(update(Job).where(Job.parent_id.in_(job_ids)).values(parent_id=None))
                    delete_rows(u, Job, Job.id.in_(job_ids))
                delete_rows(u, Corpus, Corpus.id == corpus_id)
            else:
                u.repo.update('corpora', corpus_id, revision=corpus['revision'] + 1)
            queue_files(u, keys)
            u.commit()


def cleanup_storage_once(storage, uow=Uow):
    # Database deletion and this durable queue commit together. Failed S3 deletion is retried.
    with uow() as u:
        row = u.session.scalars(select(StorageDeletion).where(StorageDeletion.retry_at <= now())
                                .order_by(StorageDeletion.created_at).with_for_update(skip_locked=True).limit(1)).first()
        if row is None:
            return False
        try:
            storage.delete(row.storage_key)
        except Exception as exc:
            row.attempts += 1
            row.last_error = type(exc).__name__
            row.retry_at = now() + timedelta(seconds=min(2 ** min(row.attempts, 8), 300))
        else:
            u.session.delete(row)
        u.commit()
        return True
