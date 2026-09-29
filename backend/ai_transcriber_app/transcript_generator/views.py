import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .models import ArticlePost

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
    except (KeyError, AttributeError, json.JSONDecodeError):
        return JsonResponse({'error': 'Invalid data sent'}, status=400)

    try:
        services.extract_video_id(yt_link)
        title = services.get_video_title(yt_link)
        transcript = services.get_transcript(yt_link)
        article_content = services.generate_notes(transcript)
    except services.PipelineError as exc:
        return JsonResponse({'error': str(exc)}, status=exc.status)

    article = ArticlePost.objects.create(
        user=request.user,
        video_title=title,
        youtube_link=yt_link,
        generated_content=article_content,
    )

    return JsonResponse({'content': article_content, 'title': title, 'id': article.id})


@login_required
def all_scripts(request):
    articles = ArticlePost.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'all-scripts.html', {'articles': articles})


def user_logout(request):
    logout(request)
    return redirect('/')


@login_required
def full_article(request, pk):
    full_article = get_object_or_404(ArticlePost, id=pk, user=request.user)
    return render(request, 'full-article.html', {'full_article': full_article})
