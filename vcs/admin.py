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