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


class FormatSegmentsTests(TestCase):
    def test_groups_into_timestamped_blocks(self):
        segments = [(0, 'hello'), (10, 'there\n'), (31, 'next'), (3700, 'later')]
        self.assertEqual(services.format_segments(segments),
                         '[00:00] hello there\n[00:31] next\n[1:01:40] later')

    def test_skips_empty_text(self):
        self.assertEqual(services.format_segments([(0, '  '), (5, 'hi')]), '[00:05] hi')


class ParseTranscriptTests(TestCase):
    def test_round_trips_formatted_segments(self):
        transcript = services.format_segments([(0, 'hello'), (31, 'next'), (3700, 'later')])
        self.assertEqual(services.parse_transcript(transcript),
                         [(0, 'hello'), (31, 'next'), (3700, 'later')])

    def test_untimed_text_is_kept(self):
        self.assertEqual(services.parse_transcript('plain text\n[00:05] hi\nmore'),
                         [(0, 'plain text'), (5, 'hi more')])
        self.assertEqual(services.parse_transcript(''), [])


class GenerateNotesTests(TestCase):
    def notes_json(self, **overrides):
        data = {
            'summary': 'Para one.\n\nPara two.',
            'key_takeaways': ['a', 'b'],
            'chapters': [{'start_seconds': 90, 'title': 'B', 'summary': 'x'},
                         {'start_seconds': 0, 'title': 'A', 'summary': 'y'}],
            'quiz': [{'question': 'Q?', 'options': ['1', '2', '3', '4'], 'answer_index': 1, 'explanation': 'e'},
                     {'question': 'Bad', 'options': ['1', '2'], 'answer_index': 5, 'explanation': 'e'}],
        }
        data.update(overrides)
        return mock.Mock(parsed=None, text=json.dumps(data))

    def test_parses_sorts_and_drops_invalid_quiz(self):
        with mock.patch.object(services, '_gemini', return_value=self.notes_json()):
            notes = services.generate_notes('[00:00] hi')
        self.assertEqual([c.title for c in notes.chapters], ['A', 'B'])
        self.assertEqual(len(notes.quiz), 1)

    def test_bad_json_is_a_pipeline_error(self):
        with mock.patch.object(services, '_gemini', return_value=mock.Mock(parsed=None, text='nope')):
            with self.assertRaises(services.PipelineError):
                services.generate_notes('[00:00] hi')

    def test_empty_summary_is_a_pipeline_error(self):
        with mock.patch.object(services, '_gemini', return_value=self.notes_json(summary=' ')):
            with self.assertRaises(services.PipelineError):
                services.generate_notes('[00:00] hi')

    @override_settings(GEMINI_API_KEY='')
    def test_missing_key(self):
        with self.assertRaises(services.PipelineError) as ctx:
            services.generate_notes('[00:00] hi')
        self.assertIn('GEMINI_API_KEY', str(ctx.exception))


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

    @mock.patch.object(services, 'generate_notes', return_value=services.Notes(
        summary='the notes', key_takeaways=['one'], quiz=[],
        chapters=[services.Chapter(start_seconds=65, title='Intro', summary='s')]))
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
        self.assertEqual(article.transcript, 'the transcript')
        self.assertEqual(article.key_takeaways, ['one'])
        self.assertEqual(article.chapters_with_links()[0]['url'],
                         'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=65s')
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


@override_settings(JOBS_RUN_SYNC=True)
class ReuseResultsTests(TestCase):
    url = reverse('generate-transcript')
    link = 'https://youtu.be/dQw4w9WgXcQ'

    def setUp(self):
        self.alice = User.objects.create_user('alice', password='pw-12345-long')
        self.bob = User.objects.create_user('bob', password='pw-12345-long')
        self.saved = ArticlePost.objects.create(
            user=self.alice, video_title='Renamed by Alice', youtube_link='https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            generated_content='saved notes', transcript='[00:00] saved', key_takeaways=['k'],
            chapters=[{'start_seconds': 0, 'title': 'A', 'summary': 's'}], quiz=[])
        self.saved.questions.create(question='private?', answer='yes')

    def post(self, user):
        self.client.force_login(user)
        return self.client.post(self.url, data=json.dumps({'link': self.link}), content_type='application/json')

    def test_video_id_is_stored(self):
        self.assertEqual(self.saved.video_id, 'dQw4w9WgXcQ')

    @mock.patch.object(services, 'generate_notes')
    @mock.patch.object(services, 'get_transcript')
    @mock.patch.object(services, 'get_video_title', return_value='Original title')
    def test_reuses_another_users_notes(self, title, transcript, notes):
        response = self.post(self.bob)
        self.assertEqual(response.json()['status'], 'done')
        transcript.assert_not_called()
        notes.assert_not_called()
        article = ArticlePost.objects.get(user=self.bob)
        self.assertEqual((article.video_title, article.generated_content, article.transcript, article.key_takeaways),
                         ('Original title', 'saved notes', '[00:00] saved', ['k']))
        self.assertEqual(article.questions.count(), 0)

    @mock.patch.object(jobs, 'run')
    def test_same_user_gets_existing_notes(self, run):
        response = self.post(self.alice)
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.json()['id'], response.json()['existing']), (self.saved.id, True))
        self.assertEqual(ArticlePost.objects.count(), 1)
        run.assert_not_called()

    @mock.patch.object(jobs, 'run')
    def test_failed_notes_are_not_reused(self, run):
        self.saved.status = ArticlePost.Status.FAILED
        self.saved.save()
        response = self.post(self.alice)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(ArticlePost.objects.filter(user=self.alice).count(), 2)


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

    def test_embeds_player_with_seekable_transcript(self):
        self.article.youtube_link = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'
        self.article.transcript = '[00:00] intro\n[01:05] <i>main</i> part'
        self.article.chapters = [{'start_seconds': 65, 'title': 'Main', 'summary': 's'}]
        self.article.save()
        self.client.force_login(self.owner)
        response = self.client.get(reverse('full-article', args=[self.article.id]))
        self.assertContains(response, 'youtube-nocookie.com/embed/dQw4w9WgXcQ?enablejsapi=1')
        self.assertContains(response, 'data-seconds="65"', count=2)  # chapter + transcript line
        self.assertContains(response, '&lt;i&gt;main&lt;/i&gt; part')
        self.assertNotContains(response, 'Full transcript')

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
            user=self.user, youtube_link='https://youtu.be/dQw4w9WgXcQ', video_title='Done one', generated_content='hi',
            key_takeaways=['Takeaway <1>'],
            chapters=[{'start_seconds': 75, 'title': 'Chapter A', 'summary': 'x'}],
            quiz=[{'question': 'Quiz Q?', 'options': ['a', 'b'], 'answer_index': 0, 'explanation': 'because'}])
        self.assertContains(self.client.get(reverse('index')), 'Summarize')
        listing = self.client.get(reverse('all-scripts'))
        self.assertContains(listing, 'Done one')
        self.assertContains(listing, 'Processing')
        self.assertContains(self.client.get(reverse('full-article', args=[pending.id])), 'Writing notes')
        page = self.client.get(reverse('full-article', args=[done.id]))
        self.assertContains(page, 'Takeaway &lt;1&gt;')
        self.assertContains(page, 'watch?v=dQw4w9WgXcQ&amp;t=75s')
        self.assertContains(page, '01:15')
        self.assertContains(page, 'Quiz Q?')

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('logout')).status_code, 302)


class AskQuestionViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw-12345-long')
        self.client.force_login(self.user)
        self.article = ArticlePost.objects.create(
            user=self.user, youtube_link='https://youtu.be/dQw4w9WgXcQ', generated_content='s',
            transcript='[00:00] hello')
        self.url = reverse('ask-question', args=[self.article.id])

    def ask(self, body):
        return self.client.post(self.url, data=json.dumps(body), content_type='application/json')

    @mock.patch.object(services, 'answer_question', return_value='They said hello at [00:00].')
    def test_answers_and_saves(self, answer):
        response = self.ask({'question': 'What did they say?'})
        self.assertEqual(response.json()['answer'], 'They said hello at [00:00].')
        answer.assert_called_once_with('[00:00] hello', 'What did they say?')
        self.assertEqual(self.article.questions.get().question, 'What did they say?')
        self.assertContains(self.client.get(reverse('full-article', args=[self.article.id])), 'They said hello')

    def test_validates_question(self):
        self.assertEqual(self.ask({'question': '  '}).status_code, 400)
        self.assertEqual(self.ask({'question': 'x' * 1001}).status_code, 400)
        self.assertEqual(self.ask({}).status_code, 400)

    def test_other_users_article_is_404(self):
        other = User.objects.create_user('bob', password='pw-12345-long')
        self.client.force_login(other)
        self.assertEqual(self.ask({'question': 'hi'}).status_code, 404)

    @mock.patch.object(services, 'answer_question', side_effect=services.PipelineError("Couldn't answer that right now."))
    def test_error(self, answer):
        response = self.ask({'question': 'hi'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.article.questions.count(), 0)


class NotesLibraryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw-12345-long')
        self.client.force_login(self.user)
        self.article = ArticlePost.objects.create(
            user=self.user, youtube_link='https://youtu.be/dQw4w9WgXcQ', video_title='Rust basics',
            generated_content='Ownership explained.', transcript='[00:00] borrow checker',
            key_takeaways=['Own it'], chapters=[{'start_seconds': 5, 'title': 'Start', 'summary': 's'}],
            quiz=[{'question': 'Q?', 'options': ['a', 'b'], 'answer_index': 1, 'explanation': 'e'}])
        ArticlePost.objects.create(user=self.user, youtube_link='https://youtu.be/b', video_title='Cooking pasta')

    def test_search(self):
        url = reverse('all-scripts')
        for query in ['rust', 'OWNERSHIP', 'borrow']:
            response = self.client.get(url, {'q': query})
            self.assertContains(response, 'Rust basics')
            self.assertNotContains(response, 'Cooking pasta')
        self.assertContains(self.client.get(url, {'q': 'zzz'}), 'No notes match')

    def test_pagination(self):
        for i in range(25):
            ArticlePost.objects.create(user=self.user, youtube_link='https://youtu.be/c', video_title=f'Extra {i}')
        response = self.client.get(reverse('all-scripts'))
        self.assertEqual(len(response.context['articles']), 20)
        self.assertContains(response, 'Page 1 of 2')

    def test_rename(self):
        self.client.post(reverse('rename-article', args=[self.article.id]), {'title': 'Ownership in Rust'})
        self.article.refresh_from_db()
        self.assertEqual(self.article.video_title, 'Ownership in Rust')

    def test_delete(self):
        response = self.client.post(reverse('delete-article', args=[self.article.id]))
        self.assertRedirects(response, reverse('all-scripts'))
        self.assertFalse(ArticlePost.objects.filter(id=self.article.id).exists())

    def test_cannot_touch_other_users_notes(self):
        other = User.objects.create_user('bob', password='pw-12345-long')
        self.client.force_login(other)
        for name in ['rename-article', 'delete-article', 'retry-article']:
            self.assertEqual(self.client.post(reverse(name, args=[self.article.id]), {'title': 'x'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('export-article', args=[self.article.id])).status_code, 404)
        self.assertTrue(ArticlePost.objects.filter(id=self.article.id, video_title='Rust basics').exists())

    def test_export_markdown(self):
        self.article.questions.create(question='Why?', answer='Because.')
        response = self.client.get(reverse('export-article', args=[self.article.id]))
        self.assertEqual(response['Content-Type'], 'text/markdown; charset=utf-8')
        self.assertIn('rust-basics.md', response['Content-Disposition'])
        body = response.content.decode()
        for expected in ['# Rust basics', '- Own it', 'Ownership explained.',
                         '[00:05](https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5s)', '**b**', '**Q: Why?**',
                         '[00:00] borrow checker']:
            self.assertIn(expected, body)

    @override_settings(JOBS_RUN_SYNC=True)
    @mock.patch.object(jobs, 'run')
    def test_retry_failed_job(self, run):
        self.article.status = 'failed'
        self.article.error = 'boom'
        self.article.save()
        self.client.post(reverse('retry-article', args=[self.article.id]))
        self.article.refresh_from_db()
        self.assertEqual((self.article.status, self.article.error), ('pending', ''))
        run.assert_called_once_with(self.article.id)


class AuthTests(TestCase):
    def signup(self, **overrides):
        data = {'username': 'newbie', 'email': 'n@example.com', 'password': 'a-Long-passphrase-9',
                'repeatPassword': 'a-Long-passphrase-9'}
        data.update(overrides)
        return self.client.post(reverse('signup'), data)

    def test_signup_logs_in(self):
        self.assertRedirects(self.signup(), reverse('index'))

    def test_signup_rejects_weak_or_mismatched_password(self):
        self.assertContains(self.signup(password='123', repeatPassword='123'), 'too short')
        self.assertContains(self.signup(repeatPassword='different'), 'do not match')
        self.assertFalse(User.objects.exists())

    def test_signup_rejects_taken_username(self):
        User.objects.create_user('Newbie', password='x')
        self.assertContains(self.signup(), 'taken')

    def test_login_honours_safe_next_only(self):
        User.objects.create_user('alice', password='pw-12345-long')
        creds = {'username': 'alice', 'password': 'pw-12345-long'}
        response = self.client.post(reverse('login'), {**creds, 'next': reverse('all-scripts')})
        self.assertRedirects(response, reverse('all-scripts'))
        response = self.client.post(reverse('login'), {**creds, 'next': 'https://evil.example.com/'})
        self.assertRedirects(response, reverse('index'))

    def test_login_bad_credentials(self):
        self.assertContains(self.client.post(reverse('login'), {'username': 'x', 'password': 'y'}), 'Wrong username')


class HealthTests(TestCase):
    def test_healthz_is_public(self):
        response = self.client.get(reverse('healthz'))
        self.assertEqual((response.status_code, response.content), (200, b'ok'))
