import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import jobs, services
from .models import ArticlePost

MAX_QUESTION_LENGTH = 1000

@login_required
def index(request):
    return render(request, 'index.html')

def user_login(request):
    if request.method =='POST':
      username=request.POST['username']
      password=request.POST['password'] 

      user = authenticate(request,username=username,password=password)
      if user is not None:
          login(request,user)
          return redirect('/')
      else:
            error_message = "No such user found recheck credentials"
            return render(request, 'login.html', {'error_message': error_message})
    return render(request,'login.html')

def user_signup(request):
    if request.method == 'POST':
        username = request.POST['username']
        email = request.POST['email']
        password = request.POST['password']
        repeatPassword = request.POST['repeatPassword']

        if password == repeatPassword:
            try:
                user = User.objects.create_user(username, email, password)
                user.save()
                login(request, user)
                return redirect('/')
            except:
                error_message = 'Error creating account'
                return render(request, 'signup.html', {'error_message':error_message})
        else:
            error_message = 'Password do not match'
            return render(request, 'signup.html', {'error_message':error_message})
        
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
        services.extract_video_id(yt_link)
    except services.PipelineError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

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
    return render(request, 'all-scripts.html', {'articles': articles})


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
