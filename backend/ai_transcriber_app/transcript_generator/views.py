from django.shortcuts import render
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
# Create your views here.
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

@csrf_exempt
def generate_transcript(request):
    if request.method=='POST':
        try:
            data=json.loads(request.body)
            yt_link = data['link']
        except (KeyError, json.JSONDecodeError):
            return JsonResponse({'error':'Invalid data sent'}, status=400)
    else:
        return JsonResponse({'error':'Ivalid request method'}, status=405)




@login_required
def all_scripts(request):
    return render(request,'all-scripts.html')


def user_logout(request):
    logout(request)
    return redirect('/')

