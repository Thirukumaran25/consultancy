# vcs/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('',                     views.login_view,          name='login'),
    path('logout/',              views.logout_view,         name='logout'),
    path('dashboard/', views.dashboard_router, name='dashboard'),
    path('candidate/register/',  views.candidate_register,  name='candidate_register'),
    path('send-otp/', views.send_registration_otp, name='send_registration_otp'),
    path('upgrade/', views.upgrade_subscription, name='upgrade_subscription'),
    path('payment/success/',   views.payment_success,      name='payment_success'),
    path('payment/failed/',    views.payment_failed,       name='payment_failed'),

    # Add to urlpatterns
    path('services/',                         views.services,          name='services'),
    path('services/feeds/',                   views.feed_list,         name='feed_list'),
    path('services/feeds/<slug:slug>/',       views.feed_detail,       name='feed_detail'),


    path('jobs/',                        views.job_list,            name='job_list'),
    path('jobs/<slug:slug>/',            views.job_detail,          name='job_detail'),
    path('jobs/<slug:slug>/apply/',      views.apply_job,           name='apply_job'),
    path('jobs/<slug:slug>/withdraw/',   views.withdraw_application, name='withdraw_application'),
    path('my-applications/',             views.my_applications,     name='my_applications'),


    path('company/register/',    views.company_register,    name='company_register'),
    path('api/check-status/', views.check_company_status, name='check_company_status'),
    path('company/dashboard/', views.company_dashboard, name='company_dashboard'),
    path('company/post-job/', views.company_post_job, name='company_post_job'),
    path('company/job/<int:job_id>/edit/', views.company_edit_job, name='company_edit_job'),
    path('company/job/<int:job_id>/delete/', views.company_delete_job, name='company_delete_job'),
    path('company/update-application/<int:app_id>/', views.update_application_status, name='update_application_status'),


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
    path('candidate/profile/photo/', views.update_profile_photo, name='update_profile_photo'),

    path('trainee/dashboard/',   views.trainee_dashboard,   name='trainee_dashboard'),
    path('trainee/profile/', views.trainee_profile, name='trainee_profile'),
    path('trainee/profile/update/', views.update_trainee_profile, name='update_trainee_profile'),
    path('check-availability/',  views.check_availability,  name='check_availability'),
]