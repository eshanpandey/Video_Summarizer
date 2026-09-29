"""Run the summarize pipeline off the request thread.

Jobs run in a small in-process thread pool; all state lives on the
ArticlePost row, so any web worker can report progress. A job whose worker
died (server restart) is marked failed once it has been silent for
settings.JOB_STALE_AFTER seconds.
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from . import services
from .models import ArticlePost

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=settings.JOB_WORKERS, thread_name_prefix='summarize')


def enqueue(article):
    """Start processing a pending ArticlePost."""
    if settings.JOBS_RUN_SYNC:
        run(article.pk)
    else:
        _executor.submit(run, article.pk)


def _update(pk, **fields):
    fields['updated_at'] = timezone.now()
    ArticlePost.objects.filter(pk=pk).update(**fields)


def run(pk):
    close_old_connections()
    try:
        article = ArticlePost.objects.get(pk=pk)
        url = article.youtube_link

        _update(pk, status=ArticlePost.Status.PROCESSING, stage='Looking up the video')
        title = services.get_video_title(url)
        _update(pk, video_title=title, stage='Getting the transcript')

        transcript = services.get_transcript(url)
        _update(pk, stage='Writing notes')

        notes = services.generate_notes(transcript)
        _update(pk, generated_content=notes, status=ArticlePost.Status.DONE, stage='')
    except services.PipelineError as exc:
        _update(pk, status=ArticlePost.Status.FAILED, error=str(exc), stage='')
    except Exception:
        logger.exception('Summarize job %s crashed', pk)
        _update(pk, status=ArticlePost.Status.FAILED, error='Something went wrong.', stage='')
    finally:
        close_old_connections()


def fail_if_stale(article):
    """Mark a job failed if its worker stopped reporting progress."""
    if article.is_finished:
        return article
    cutoff = timezone.now() - timedelta(seconds=settings.JOB_STALE_AFTER)
    if article.updated_at < cutoff:
        article.status = ArticlePost.Status.FAILED
        article.error = 'Processing was interrupted. Please try again.'
        article.stage = ''
        article.save(update_fields=['status', 'error', 'stage', 'updated_at'])
    return article
