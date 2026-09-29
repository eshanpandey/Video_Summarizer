"""Per-user caps that keep one account from running up the transcription and Gemini bills.

Each limit comes from settings; 0 turns it off. Staff accounts are never limited.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import ArticlePost, Question

WINDOW = timedelta(hours=24)


def _exempt(user):
    return user.is_staff


def summaries_left(user):
    """Videos this user can still summarize in the current 24 hours, or None if unlimited."""
    limit = settings.SUMMARIES_PER_DAY
    if not limit or _exempt(user):
        return None
    used = ArticlePost.objects.filter(user=user, created_at__gte=timezone.now() - WINDOW).count()
    return max(limit - used, 0)


def active_jobs_error(user):
    limit = settings.MAX_ACTIVE_JOBS
    if not limit or _exempt(user):
        return None
    active = ArticlePost.objects.filter(
        user=user,
        status__in=[ArticlePost.Status.PENDING, ArticlePost.Status.PROCESSING],
        updated_at__gte=timezone.now() - timedelta(seconds=settings.JOB_STALE_AFTER),
    ).count()
    if active >= limit:
        return f'You already have {active} videos processing. Wait for one to finish, then try again.'
    return None


def summary_error(user):
    """Why this user can't start another summary right now, or None."""
    if summaries_left(user) == 0:
        return f'You have reached the limit of {settings.SUMMARIES_PER_DAY} videos a day. Try again tomorrow.'
    return active_jobs_error(user)


def question_error(user):
    limit = settings.QUESTIONS_PER_DAY
    if not limit or _exempt(user):
        return None
    used = Question.objects.filter(article__user=user, created_at__gte=timezone.now() - WINDOW).count()
    if used >= limit:
        return f'You have reached the limit of {limit} questions a day. Try again tomorrow.'
    return None
