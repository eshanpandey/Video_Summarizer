import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import jobs, services
from .models import ArticlePost


class ExtractVideoIdTests(TestCase):
    def test_supported_url_shapes(self):
        for url in [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtube.com/watch?feature=share&v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ?t=10',
            'https://www.youtube.com/shorts/dQw4w9WgXcQ',
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
        ]:
            self.assertEqual(services.extract_video_id(url), 'dQw4w9WgXcQ', url)

    def test_rejects_non_youtube_url(self):
        with self.assertRaises(services.PipelineError) as ctx:
            services.extract_video_id('https://example.com/video')
        self.assertEqual(ctx.exception.status, 400)


class GetTranscriptTests(TestCase):
    @mock.patch.object(services, 'get_audio_transcript')
    @mock.patch.object(services, 'get_caption_transcript', return_value='caption text')
    def test_prefers_captions(self, captions, audio):
        self.assertEqual(services.get_transcript('https://youtu.be/dQw4w9WgXcQ'), 'caption text')
        captions.assert_called_once_with('dQw4w9WgXcQ')
        audio.assert_not_called()

    @mock.patch.object(services, 'get_audio_transcript', return_value='audio text')
    @mock.patch.object(services, 'get_caption_transcript', return_value=None)
    def test_falls_back_to_audio(self, captions, audio):
        self.assertEqual(services.get_transcript('https://youtu.be/dQw4w9WgXcQ'), 'audio text')
        audio.assert_called_once()

    @override_settings(ASSEMBLYAI_API_KEY='')
    def test_audio_fallback_needs_key(self):
        with self.assertRaises(services.PipelineError):
            services.get_audio_transcript('https://youtu.be/dQw4w9WgXcQ')


@override_settings(JOBS_RUN_SYNC=True)
class GenerateTranscriptViewTests(TestCase):
    url = reverse('generate-transcript')
    link = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

    def setUp(self):
        self.user = User.objects.create_user('alice', 'a@example.com', 'pw-12345-long')

    def post(self, body):
        return self.client.post(self.url, data=json.dumps(body), content_type='application/json')

    def test_requires_login(self):
        response = self.post({'link': self.link})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ArticlePost.objects.count(), 0)

    def test_rejects_get(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_rejects_bad_body(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post({'nope': 1}).status_code, 400)
        self.assertEqual(self.post({'link': 'https://example.com'}).status_code, 400)
        self.assertEqual(ArticlePost.objects.count(), 0)

    @mock.patch.object(services, 'generate_notes', return_value='the notes')
    @mock.patch.object(services, 'get_transcript', return_value='the transcript')
    @mock.patch.object(services, 'get_video_title', return_value='A video')
    def test_success_saves_article(self, title, transcript, notes):
        self.client.force_login(self.user)
        response = self.post({'link': self.link})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()['status'], 'done')
        self.assertEqual(response.json()['content'], 'the notes')
        article = ArticlePost.objects.get()
        self.assertEqual((article.user, article.video_title, article.generated_content, article.status),
                         (self.user, 'A video', 'the notes', 'done'))
        notes.assert_called_once_with('the transcript')

    @mock.patch.object(services, 'get_transcript', side_effect=services.PipelineError('Transcription failed.'))
    @mock.patch.object(services, 'get_video_title', return_value='A video')
    def test_pipeline_error_marks_job_failed(self, title, transcript):
        self.client.force_login(self.user)
        response = self.post({'link': self.link})
        self.assertEqual(response.json()['status'], 'failed')
        self.assertEqual(response.json()['error'], 'Transcription failed.')
        self.assertEqual(ArticlePost.objects.get().status, 'failed')

    @mock.patch.object(services, 'get_video_title', side_effect=RuntimeError('boom'))
    def test_unexpected_error_marks_job_failed(self, title):
        self.client.force_login(self.user)
        response = self.post({'link': self.link})
        self.assertEqual(response.json()['status'], 'failed')
        self.assertEqual(response.json()['error'], 'Something went wrong.')


class JobStatusViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw-12345-long')
        self.client.force_login(self.user)

    def make(self, **kwargs):
        return ArticlePost.objects.create(user=self.user, youtube_link='https://youtu.be/dQw4w9WgXcQ', **kwargs)

    @override_settings(JOBS_RUN_SYNC=False)
    @mock.patch.object(jobs, '_executor')
    def test_enqueue_submits_to_pool(self, executor):
        article = self.make(status='pending')
        jobs.enqueue(article)
        executor.submit.assert_called_once_with(jobs.run, article.pk)

    def test_reports_progress(self):
        article = self.make(status='processing', stage='Writing notes')
        data = self.client.get(reverse('job-status', args=[article.id])).json()
        self.assertEqual((data['status'], data['stage']), ('processing', 'Writing notes'))
        self.assertNotIn('content', data)

    @override_settings(JOB_STALE_AFTER=60)
    def test_stale_job_is_failed(self):
        article = self.make(status='processing')
        ArticlePost.objects.filter(pk=article.pk).update(updated_at=timezone.now() - timedelta(minutes=5))
        data = self.client.get(reverse('job-status', args=[article.id])).json()
        self.assertEqual(data['status'], 'failed')
        self.assertIn('interrupted', data['error'])

    def test_other_users_job_is_404(self):
        other = User.objects.create_user('bob', password='pw-12345-long')
        article = ArticlePost.objects.create(user=other, youtube_link='https://youtu.be/x')
        self.assertEqual(self.client.get(reverse('job-status', args=[article.id])).status_code, 404)


class FullArticleViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user('owner', password='pw-12345-long')
        self.other = User.objects.create_user('other', password='pw-12345-long')
        self.article = ArticlePost.objects.create(
            user=self.owner, video_title='T', youtube_link='https://youtu.be/x', generated_content='<b>hi</b>')

    def test_owner_sees_escaped_content(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse('full-article', args=[self.article.id]))
        self.assertContains(response, '&lt;b&gt;hi&lt;/b&gt;')

    def test_other_user_gets_404(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse('full-article', args=[self.article.id]))
        self.assertEqual(response.status_code, 404)

    def test_missing_article_gets_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('full-article', args=[999])).status_code, 404)


class PageRenderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw-12345-long')

    def test_public_pages(self):
        for name in ['login', 'signup']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_logged_in_pages(self):
        self.client.force_login(self.user)
        pending = ArticlePost.objects.create(
            user=self.user, youtube_link='https://youtu.be/a', status='processing', stage='Writing notes')
        done = ArticlePost.objects.create(
            user=self.user, youtube_link='https://youtu.be/b', video_title='Done one', generated_content='hi')
        self.assertContains(self.client.get(reverse('index')), 'Summarize')
        listing = self.client.get(reverse('all-scripts'))
        self.assertContains(listing, 'Done one')
        self.assertContains(listing, 'Processing')
        self.assertContains(self.client.get(reverse('full-article', args=[pending.id])), 'Writing notes')
        self.assertContains(self.client.get(reverse('full-article', args=[done.id])), 'hi')

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)
