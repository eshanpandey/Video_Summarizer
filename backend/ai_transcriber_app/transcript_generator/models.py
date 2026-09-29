from django.contrib.auth.models import User
from django.db import models


class ArticlePost(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Queued'
        PROCESSING = 'processing', 'Processing'
        DONE = 'done', 'Done'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(User, on_delete=models.CASCADE)  # user who created the article
    video_title = models.CharField(max_length=300, blank=True)
    youtube_link = models.URLField(max_length=300)
    generated_content = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Background processing state
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DONE)
    stage = models.CharField(max_length=100, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.video_title or self.youtube_link

    @property
    def is_finished(self):
        return self.status in (self.Status.DONE, self.Status.FAILED)
