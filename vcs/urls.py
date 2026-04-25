# vcs/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('',                     views.login_view,          name='login'),
    path('logout/',              views.logout_view,         name='logout'),
    path('dashboard/', views.dashboard_router, name='dashboard'),
    path('candidate/register/',  views.candidate_register,  name='candidate_register'),
    path('company/register/',    views.company_register,    name='company_register'),
    path('candidate/dashboard/', views.candidate_dashboard, name='candidate_dashboard'),
    path('candidate/profile/', views.candidate_profile, name='candidate_profile'),
    path('trainee/dashboard/',   views.trainee_dashboard,   name='trainee_dashboard'),
    path('company/dashboard/',   views.company_dashboard,   name='company_dashboard'),
    path('check-availability/',  views.check_availability,  name='check_availability'),
]