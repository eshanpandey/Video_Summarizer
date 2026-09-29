from django.contrib.auth.models import User
from django.db import models

from .services import PipelineError, extract_video_id, format_timestamp, parse_transcript


class ArticlePost(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Queued'
        PROCESSING = 'processing', 'Processing'
        DONE = 'done', 'Done'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(User, on_delete=models.CASCADE)  # user who created the article
    video_title = models.CharField(max_length=300, blank=True)
    youtube_link = models.URLField(max_length=300)
    generated_content = models.TextField(blank=True)  # the summary article
    transcript = models.TextField(blank=True)  # '[mm:ss] text' lines
    key_takeaways = models.JSONField(default=list, blank=True)
    chapters = models.JSONField(default=list, blank=True)  # [{start_seconds, title, summary}]
    quiz = models.JSONField(default=list, blank=True)  # [{question, options, answer_index, explanation}]
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

    @property
    def video_id(self):
        try:
            return extract_video_id(self.youtube_link)
        except PipelineError:
            return None

    def chapters_with_links(self):
        return [
            {
                **chapter,
                'timestamp': format_timestamp(chapter['start_seconds']),
                'url': f"https://www.youtube.com/watch?v={self.video_id}&t={int(chapter['start_seconds'])}s",
            }
            for chapter in self.chapters
        ]

    def transcript_lines(self):
        return [
            {'seconds': seconds, 'timestamp': format_timestamp(seconds), 'text': text}
            for seconds, text in parse_transcript(self.transcript)
        ]

    def to_markdown(self):
        lines = [f'# {self}', '', f'Video: {self.youtube_link}', '']
        if self.key_takeaways:
            lines += ['## Key takeaways', ''] + [f'- {point}' for point in self.key_takeaways] + ['']
        lines += ['## Summary', '', self.generated_content.strip(), '']
        if self.chapters:
            lines += ['## Chapters', '']
            lines += [f"- [{c['timestamp']}]({c['url']}) **{c['title']}**: {c['summary']}" for c in self.chapters_with_links()]
            lines += ['']
        if self.quiz:
            lines += ['## Quiz', '']
            for number, q in enumerate(self.quiz, 1):
                lines.append(f"{number}. {q['question']}")
                lines += [f"   - {'**' + option + '**' if i == q['answer_index'] else option}" for i, option in enumerate(q['options'])]
                lines += [f"   - _{q['explanation']}_", '']
        questions = list(self.questions.all())
        if questions:
            lines += ['## Questions', '']
            for item in questions:
                lines += [f'**Q: {item.question}**', '', item.answer, '']
        if self.transcript:
            lines += ['## Transcript', '', self.transcript, '']
        return '\n'.join(lines)

class Question(models.Model):
    article = models.ForeignKey(ArticlePost, on_delete=models.CASCADE, related_name='questions')
    question = models.TextField()
    answer = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
