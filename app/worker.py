# Назначение файла: Celery work/DLQ, transactional outbox dispatcher и lease recovery.
import logging
import threading
import time
from datetime import timedelta, timezone
from celery import Celery
from celery.signals import setup_logging
from kombu import Exchange, Queue
from sqlalchemy import select, or_
from app.config import settings
from app.db import Uow
from app.domain import now, uid, TransientError, TERMINAL
from app.models.data import Outbox, JobItem
from app.services.pipeline import Runner, aggregate

config = settings()
celery = Celery('science_extract', broker=config.rabbitmq_url.get_secret_value(), backend=config.redis_url)
celery.conf.update(task_serializer='json', result_serializer='json', accept_content=['json'],
    task_default_queue='work', task_default_delivery_mode='persistent', task_acks_late=True,
    task_reject_on_worker_lost=True, worker_prefetch_multiplier=1, result_expires=3600,
    task_ignore_result=True, broker_connection_retry_on_startup=True,
    broker_transport_options={'confirm_publish': True},
    task_queues=(Queue('work', Exchange('work', durable=True), routing_key='work', durable=True,
                      queue_arguments={'x-dead-letter-exchange': 'dead', 'x-dead-letter-routing-key': 'dead_letter'}),
                 Queue('dead_letter', Exchange('dead', durable=True), routing_key='dead_letter', durable=True)))
log = logging.getLogger(__name__)


@setup_logging.connect
def configure_worker_logging(**kwargs):
    from app.main import JsonLog
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLog())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(config.log_level)


class Publisher:
    def publish(self, item_id, task_id):
        execute.apply_async(args=[item_id], task_id=task_id, queue='work', retry=False)

    def dead_letter(self, payload):
        with celery.connection_for_write() as connection:
            with connection.Producer(serializer='json') as producer:
                producer.publish(payload, exchange=Exchange('dead', durable=True), routing_key='dead_letter',
                                 delivery_mode=2, declare=[celery.conf.task_queues[1]], retry=True)


@celery.task(bind=True, name='science_extract.execute', max_retries=3)
def execute(self, item_id):
    from app.storage import Storage
    from app.provider import ResponsesModel
    runner = Runner(Uow, Storage(config), ResponsesModel(config), config)
    started = time.monotonic()
    try:
        runner.run(item_id)
    except TransientError as exc:
        if self.request.retries < 3:
            raise self.retry(countdown=min(2 ** (self.request.retries+1), 30), exc=exc)
        with Uow() as u:
            item = u.repo.get('job_items', item_id, lock=True)
            u.repo.update('job_items', item_id, status='failed', error='transient_retry_exhausted')
            aggregate(u.repo, item['job_id'])
            u.commit()
        schedule_dead_letter(item_id, 'transient_retry_exhausted')
    except Exception as exc:
        schedule_dead_letter(item_id, type(exc).__name__)
        log.error('job_failed', extra={'item_id': item_id, 'error_code': type(exc).__name__})
    finally:
        fields = {'item_id': item_id, 'elapsed_ms': round(1000*(time.monotonic()-started))}
        try:
            item, job = runner.load(item_id)
            fields.update(job_id=job['id'], corpus_id=job['corpus_id'], status=item['status'])
        except Exception:
            fields['status'] = 'unknown'
        log.info('job_item_finished', extra=fields)


def schedule_dead_letter(item_id, code):
    with Uow() as u:
        out = u.repo.find('outbox', item_id=item_id)[0]
        u.repo.update('outbox', out['id'], dispatched=False, lease_until=None, task_id=uid(), last_error='dead_letter_pending:'+code)
        u.commit()


def dispatch_once(publisher=None):
    publisher = publisher or Publisher()
    with Uow() as u:
        expired = [(obj.id, obj.job_id) for obj in u.session.scalars(select(JobItem).where(JobItem.status == 'running', JobItem.lease_until < now()))]
    for item_id, job_id in expired:
        with Uow() as u:
            job = u.repo.get('jobs', job_id, lock=True)
            item = u.repo.get('job_items', item_id, lock=True)
            if item['status'] != 'running' or not item['lease_until'] or item['lease_until'].replace(tzinfo=timezone.utc) >= now():
                continue
            state = 'cancelled' if job['status'] == 'cancel_requested' else 'failed' if item['attempts'] >= 4 else 'queued'
            u.repo.update('job_items', item_id, status=state, lease_token=None, lease_until=None,
                          error='lease_retry_exhausted' if state == 'failed' else item['error'])
            out = u.repo.find('outbox', item_id=item_id)[0]
            u.repo.update('outbox', out['id'], dispatched=state == 'cancelled', lease_until=None, task_id=uid(),
                          last_error='dead_letter_pending:lease_retry_exhausted' if state == 'failed' else out['last_error'])
            aggregate(u.repo, job_id)
            u.commit()
    with Uow() as u:
        out = u.session.scalars(select(Outbox).where(Outbox.dispatched.is_(False),
            or_(Outbox.lease_until.is_(None), Outbox.lease_until < now())).order_by(Outbox.created_at).with_for_update(skip_locked=True).limit(1)).first()
        if out is None:
            return False
        item = u.repo.get('job_items', out.item_id)
        dead_letter_code = out.last_error.split(':', 1)[1] if out.last_error and out.last_error.startswith('dead_letter_pending:') else None
        if not dead_letter_code and (item['status'] in TERMINAL or item['status'] == 'waiting_review'):
            out.dispatched = True
            u.commit()
            return True
        id, item_id, task_id = out.id, out.item_id, out.task_id
        out.lease_until = now()+timedelta(seconds=30)
        out.attempts += 1
        u.commit()
    try:
        if dead_letter_code:
            publisher.dead_letter({'item_id': item_id, 'code': dead_letter_code})
        else:
            publisher.publish(item_id, task_id)
    except Exception as exc:
        with Uow() as u:
            u.repo.update('outbox', id, last_error='dead_letter_pending:'+dead_letter_code if dead_letter_code else type(exc).__name__)
            u.commit()
        return False
    with Uow() as u:
        current = u.repo.get('outbox', id, lock=True)
        if current['task_id'] == task_id:
            u.repo.update('outbox', id, dispatched=True, lease_until=None, last_error=None)
        u.commit()
    return True


def start_dispatcher():
    stop = threading.Event()
    def loop():
        while not stop.is_set():
            try:
                worked = dispatch_once()
            except Exception as exc:
                log.error('dispatcher_error', extra={'error_code': type(exc).__name__})
                worked = False
            stop.wait(.2 if worked else 2)
    thread = threading.Thread(target=loop, name='outbox-dispatcher', daemon=True)
    thread.start()
    return stop, thread
