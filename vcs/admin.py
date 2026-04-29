# vcs/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.safestring import mark_safe
from django.utils.html import escape
from .models import *

class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'email', 'role', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('Role Management', {'fields': ('role',)}),
    )

admin.site.register(User, CustomUserAdmin)
class EducationInline(admin.TabularInline):
    model = Education
    extra = 0 

class EmploymentInline(admin.TabularInline):
    model = Employment
    extra = 0

class ProjectInline(admin.TabularInline):
    model = Project
    extra = 0


@admin.register(CandidateProfile)
class CandidateProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'subscription_type', 'is_fresher', 'created_at')
    search_fields = ('full_name', 'user__username', 'user__email', 'phone_number')
    list_filter = ('subscription_type', 'is_fresher', 'gender')
    inlines = [EducationInline, EmploymentInline, ProjectInline]

    exclude = ('skills',)
    readonly_fields = ('candidate_skills',)

    def candidate_skills(self, obj):
        skills = obj.skills.all()
        if skills:
            return mark_safe("<br>".join([escape(skill.name) for skill in skills]))
        return "No skills added."
    
    candidate_skills.short_description = "Skills"


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'status', 'created_at')
    list_editable = ('status',) 
    list_filter = ('status', 'created_at')
    search_fields = ('company_name', 'email', 'user__username')

admin.site.register(UISettings)
admin.site.register(TraineeProfile)


@admin.register(JobCategory)
class JobCategoryAdmin(admin.ModelAdmin):
    list_display  = ('name', 'slug', 'icon', 'job_count')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

    def job_count(self, obj):
        return obj.jobs.count()
    job_count.short_description = 'Jobs'


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display   = ('title', 'company', 'location', 'job_type', 'experience',
                      'work_mode', 'is_active', 'is_featured', 'openings', 'posted_at')
    list_filter    = ('is_active', 'is_featured', 'job_type', 'work_mode', 'category')
    search_fields  = ('title', 'company', 'location', 'skills_required') # Updated for manual fields
    list_editable  = ('is_active', 'is_featured')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields     = ('posted_at', 'updated_at')
    date_hierarchy      = 'posted_at'

    fieldsets = (
                ('Basic Info', {
                    'fields': ('company', 'category', 'title', 'slug', 'description')
                }),
                ('Details', {
                    'fields': ('responsibilities', 'requirements', 'benefits', 'skills_required')
                }),
                ('Classification', {
                    'fields': ('job_type', 'work_mode', 'experience', 'location', 'openings', 'deadline')
                }),
                ('Salary', {
                    'fields': ('salary_hidden', 'salary_min', 'salary_max')
                }),
                ('HR Contact', {                          
                    'fields': ('hr_name', 'hr_email', 'hr_phone')
                }),
                ('Visibility', {
                    'fields': ('is_active', 'is_featured')
                }),
                ('Timestamps', {
                    'fields': ('posted_at', 'updated_at'),
                    'classes': ('collapse',),
                }),
            )


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display  = ('candidate', 'job', 'status', 'applied_at')
    list_filter   = ('status', 'applied_at')
    search_fields = ('candidate__full_name', 'job__title')
    list_editable = ('status',)
    readonly_fields = ('applied_at', 'updated_at')