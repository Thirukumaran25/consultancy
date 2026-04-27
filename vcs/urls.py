# vcs/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('',                     views.login_view,          name='login'),
    path('logout/',              views.logout_view,         name='logout'),
    path('dashboard/', views.dashboard_router, name='dashboard'),
    path('candidate/register/',  views.candidate_register,  name='candidate_register'),
    path('send-otp/', views.send_registration_otp, name='send_registration_otp'), # ADD THIS

    path('company/register/',    views.company_register,    name='company_register'),
    path('candidate/dashboard/', views.candidate_dashboard, name='candidate_dashboard'),
    path('candidate/profile/', views.candidate_profile, name='candidate_profile'),
    path('candidate/profile/',              views.candidate_profile,   name='candidate_profile'),
    path('candidate/profile/headline/',     views.update_headline,     name='update_headline'),
    path('candidate/profile/summary/',      views.update_summary,      name='update_summary'),
    path('candidate/profile/personal/',     views.update_personal,     name='update_personal'),
    path('candidate/profile/resume/',       views.update_resume,       name='update_resume'),
    path('candidate/profile/skill/add/',    views.add_skill,           name='add_skill'),
    path('candidate/profile/skill/<int:skill_id>/remove/', views.remove_skill, name='remove_skill'),
    path('candidate/profile/employment/save/',             views.save_employment,  name='save_employment'),
    path('candidate/profile/employment/<int:emp_id>/delete/', views.delete_employment, name='delete_employment'),
    path('candidate/profile/education/save/',              views.save_education,   name='save_education'),
    path('candidate/profile/education/<int:edu_id>/delete/', views.delete_education, name='delete_education'),
    path('candidate/profile/project/save/',                views.save_project,     name='save_project'),
    path('candidate/profile/project/<int:proj_id>/delete/', views.delete_project,  name='delete_project'),
    path('candidate/profile/fresher/',                     views.mark_fresher,     name='mark_fresher'),

    path('trainee/dashboard/',   views.trainee_dashboard,   name='trainee_dashboard'),
    path('company/dashboard/',   views.company_dashboard,   name='company_dashboard'),
    path('check-availability/',  views.check_availability,  name='check_availability'),
]