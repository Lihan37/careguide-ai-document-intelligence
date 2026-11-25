from celery import Celery
from app.config import settings
from app.jobs import run_job

celery_app = Celery('careguide', broker=settings().redis_url)
celery_app.conf.update(task_acks_late=True, worker_prefetch_multiplier=1, task_soft_time_limit=settings().job_timeout, task_time_limit=settings().job_timeout + 60, broker_connection_retry_on_startup=True, task_serializer='json', accept_content=['json'])


@celery_app.task(bind=True, max_retries=2)
def process_document(self, job_id):
    try:
        run_job(job_id)
    except (ConnectionError, OSError) as exc:
        raise self.retry(exc=exc, countdown=5 * (self.request.retries + 1))
