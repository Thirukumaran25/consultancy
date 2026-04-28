# vcs/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import *

class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'email', 'role', 'is_staff']
    fieldsets = UserAdmin.fieldsets + (
        ('Role Management', {'fields': ('role',)}),
    )

admin.site.register(User, CustomUserAdmin)
admin.site.register(CandidateProfile)
admin.site.register(CompanyProfile)
admin.site.register(UISettings)
admin.site.register(Skill)
admin.site.register(Employment)
admin.site.register(Education)
admin.site.register(Project)


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
                ('HR Contact', {                              # ← new section
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