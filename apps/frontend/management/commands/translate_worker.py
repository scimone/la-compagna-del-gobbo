"""Background worker that fills in `TranslationJob`s. Runs in its own container
(`dnd-translator` in docker-compose) - the only one that has the LLM credentials."""

import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections, transaction
from django.utils import timezone

from apps.frontend import llm
from apps.frontend.models import TranslationJob

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
#: Ceiling on model calls per hour, so a flood of jobs (a compromised web process can queue
#: some) cannot run up the LLM's bill or keep it busy for good.
MAX_JOBS_PER_HOUR = 120
IDLE_SECONDS = 3
DB_RETRY_SECONDS = 15
STALE_RUNNING = timedelta(minutes=20)


def claim_next() -> TranslationJob | None:
    """The oldest waiting job, marked running (one worker only - `skip_locked` keeps a second
    from taking the same row)."""
    with transaction.atomic():
        job = (
            TranslationJob.objects.select_for_update(skip_locked=True)
            .filter(status=TranslationJob.PENDING)
            .order_by("id")
            .first()
        )
        if job:
            job.status = TranslationJob.RUNNING
            job.attempts += 1
            job.save(update_fields=["status", "attempts", "updated_at"])
        return job


def run_job(job: TranslationJob) -> None:
    try:
        result = llm.translate(job.source, job.source_lang, job.target_lang)
    except llm.TranslationError as error:
        job.error = str(error)[:200]
        job.status = (
            TranslationJob.FAILED if job.attempts >= MAX_ATTEMPTS else TranslationJob.PENDING
        )
        log.warning("translation job %s failed (attempt %s): %s", job.pk, job.attempts, job.error)
    else:
        job.result, job.error, job.status = result, "", TranslationJob.DONE
    job.save(update_fields=["result", "error", "status", "updated_at"])


def over_budget() -> bool:
    since = timezone.now() - timedelta(hours=1)
    return (
        TranslationJob.objects.filter(updated_at__gte=since, attempts__gt=0)
        .exclude(status=TranslationJob.PENDING)
        .count()
        >= MAX_JOBS_PER_HOUR
    )


def work_once() -> bool:
    """Handle one job; False when there was nothing to do (or the hourly budget is used up)."""
    if over_budget():
        return False
    job = claim_next()
    if job is None:
        return False
    run_job(job)
    return True


class Command(BaseCommand):
    help = "Translate queued player-written texts (Logbook entries, backstories) in the background."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Drain the queue, then exit.")

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO)
        while True:
            try:
                # A job left `running` by a worker that died goes back in the queue.
                TranslationJob.objects.filter(
                    status=TranslationJob.RUNNING, updated_at__lt=timezone.now() - STALE_RUNNING
                ).update(status=TranslationJob.PENDING)
                busy = work_once()
            except DatabaseError as error:
                # Normal for a moment after a deploy: this container can start before the web
                # container has migrated. One line, then wait - not a traceback every 3 seconds.
                log.warning(
                    "translate worker: database not ready (%s), retrying", type(error).__name__
                )
                close_old_connections()
                time.sleep(DB_RETRY_SECONDS)
                continue
            if options["once"] and not busy:
                return
            if not busy:
                time.sleep(IDLE_SECONDS)
