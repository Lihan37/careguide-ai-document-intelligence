from celery import Celery
from sqlalchemy.exc import OperationalError
from app.config import settings
from app.jobs import run_job

celery_app = Celery('careguide', broker=settings().redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_soft_time_limit=settings().job_timeout, task_time_limit=settings().job_timeout + 60, broker_connection_retry_on_startup=True, broker_connection_timeout=3, task_serializer='json', accept_content=['json'])
namespace = 'careguide:' + settings().app_env + (':' + settings().automation_run_id if settings().automation_run_id else '')
celery_app.conf.update(task_default_queue=namespace, broker_transport_options={'global_keyprefix': namespace + ':'})


@celery_app.task(bind=True, max_retries=2)
def process_document(self, job_id):
    try:
        run_job(job_id)
    except (ConnectionError, OSError, OperationalError):
        raise self.retry(exc=ConnectionError('Document worker could not reach a required service'),
                         countdown=5 * (self.request.retries + 1)) from None
