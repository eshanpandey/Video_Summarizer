import json

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import jobs, services
from .models import ArticlePost

MAX_QUESTION_LENGTH = 1000
NOTES_PER_PAGE = 20


def healthz(request):
    return HttpResponse('ok', content_type='text/plain')


@login_required
def index(request):
    return render(request, 'index.html')


def _safe_next(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return next_url
    return reverse('index')


def user_login(request):
    context = {'next': request.POST.get('next') or request.GET.get('next', '')}
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username', ''),
            password=request.POST.get('password', ''),
        )
        if user is not None:
            login(request, user)
            return redirect(_safe_next(request))
        context['error_message'] = 'Wrong username or password.'
    return render(request, 'login.html', context)


def user_signup(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        repeat_password = request.POST.get('repeatPassword', '')

        error_message = None
        if not username:
            error_message = 'Choose a username.'
        elif User.objects.filter(username__iexact=username).exists():
            error_message = 'That username is taken.'
        elif password != repeat_password:
            error_message = 'Passwords do not match.'
        else:
            try:
                validate_password(password, User(username=username, email=email))
            except ValidationError as exc:
                error_message = ' '.join(exc.messages)

        if error_message:
            return render(request, 'signup.html', {'error_message': error_message, 'username': username, 'email': email})

        user = User.objects.create_user(username, email, password)
        login(request, user)
        return redirect('index')

    return render(request, 'signup.html')


@login_required
@require_POST
def generate_transcript(request):
    try:
        data = json.loads(request.body)
        yt_link = data['link'].strip()
    except (KeyError, AttributeError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data sent'}, status=400)

    try:
        video_id = services.extract_video_id(yt_link)
    except services.PipelineError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

    # Already have (or are making) notes for this video: open those instead of a duplicate.
    existing = (
        ArticlePost.objects.filter(user=request.user, video_id=video_id)
        .exclude(status=ArticlePost.Status.FAILED)
        .first()
    )
    if existing and jobs.fail_if_stale(existing).status != ArticlePost.Status.FAILED:
        return JsonResponse({**job_payload(existing), 'existing': True})

    article = ArticlePost.objects.create(
        user=request.user,
        youtube_link=yt_link,
        status=ArticlePost.Status.PENDING,
        stage='Queued',
    )
    jobs.enqueue(article)
    article.refresh_from_db()

    return JsonResponse(job_payload(article), status=202)


@login_required
def job_status(request, pk):
    article = get_object_or_404(ArticlePost, id=pk, user=request.user)
    return JsonResponse(job_payload(jobs.fail_if_stale(article)))


def job_payload(article):
    payload = {
        'id': article.id,
        'status': article.status,
        'stage': article.stage,
        'title': article.video_title,
        'status_url': reverse('job-status', args=[article.id]),
        'article_url': reverse('full-article', args=[article.id]),
    }
    if article.status == ArticlePost.Status.DONE:
        payload['content'] = article.generated_content
    if article.status == ArticlePost.Status.FAILED:
        payload['error'] = article.error
    return payload


@login_required
def all_scripts(request):
    articles = ArticlePost.objects.filter(user=request.user)
    query = request.GET.get('q', '').strip()
    if query:
        articles = articles.filter(
            Q(video_title__icontains=query)
            | Q(generated_content__icontains=query)
            | Q(transcript__icontains=query)
        )
    page = Paginator(articles, NOTES_PER_PAGE).get_page(request.GET.get('page'))
    return render(request, 'all-scripts.html', {'page': page, 'articles': page.object_list, 'query': query})


@require_POST
def user_logout(request):
    logout(request)
    return redirect('/')


@login_required
def full_article(request, pk):
    full_article = get_object_or_404(ArticlePost, id=pk, user=request.user)
    return render(request, 'full-article.html', {
        'full_article': full_article,
        'chapters': full_article.chapters_with_links(),
        'transcript_lines': full_article.transcript_lines(),
        'questions': full_article.questions.all(),
    })


@login_required
@require_POST
def ask_question(request, pk):
    article = get_object_or_404(ArticlePost, id=pk, user=request.user, status=ArticlePost.Status.DONE)
    try:
        question = json.loads(request.body)['question'].strip()
    except (KeyError, AttributeError, TypeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data sent'}, status=400)
    if not question or len(question) > MAX_QUESTION_LENGTH:
        return JsonResponse({'error': f'Ask a question of up to {MAX_QUESTION_LENGTH} characters.'}, status=400)

    context = article.transcript or article.generated_content
    try:
        answer = services.answer_question(context, question)
    except services.PipelineError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

    article.questions.create(question=question, answer=answer)
    return JsonResponse({'question': question, 'answer': answer})



def _own_article(request, pk):
    return get_object_or_404(ArticlePost, id=pk, user=request.user)


@login_required
@require_POST
def rename_article(request, pk):
    article = _own_article(request, pk)
    title = request.POST.get('title', '').strip()[:300]
    if title:
        article.video_title = title
        article.save(update_fields=['video_title', 'updated_at'])
        messages.success(request, 'Renamed.')
    return redirect('full-article', pk=article.id)


@login_required
@require_POST
def delete_article(request, pk):
    article = _own_article(request, pk)
    article.delete()
    messages.success(request, f'Deleted "{article}".')
    return redirect('all-scripts')


@login_required
@require_POST
def retry_article(request, pk):
    article = _own_article(request, pk)
    if article.status == ArticlePost.Status.FAILED:
        article.status = ArticlePost.Status.PENDING
        article.stage = 'Queued'
        article.error = ''
        article.save(update_fields=['status', 'stage', 'error', 'updated_at'])
        jobs.enqueue(article)
    return redirect('full-article', pk=article.id)


@login_required
def export_article(request, pk):
    article = _own_article(request, pk)
    if article.status != ArticlePost.Status.DONE:
        raise Http404
    response = HttpResponse(article.to_markdown(), content_type='text/markdown; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{slugify(str(article))[:80] or "notes"}.md"'
    return response
