from django.urls import path
from . import views
urlpatterns = [
   path('', views.index, name='index'),
   path('login', views.user_login, name='login'),
   path('signup',views.user_signup, name='signup'),
   path('logout',views.user_logout, name='logout'),
   path('allscripts',views.all_scripts, name='all-scripts'),
   path('generate-transcript',views.generate_transcript,name='generate-transcript'),
   path('jobs/<int:pk>/', views.job_status, name='job-status'),
   path('full-article/<int:pk>/',views.full_article,name='full-article'),
   path('full-article/<int:pk>/ask', views.ask_question, name='ask-question'),
   path('full-article/<int:pk>/rename', views.rename_article, name='rename-article'),
   path('full-article/<int:pk>/delete', views.delete_article, name='delete-article'),
   path('full-article/<int:pk>/retry', views.retry_article, name='retry-article'),
   path('full-article/<int:pk>/export.md', views.export_article, name='export-article'),
]