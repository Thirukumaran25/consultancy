# vcs/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.safestring import mark_safe
from django.utils.html import escape
from django.utils.html import format_html
from django.contrib import messages as admin_messages
from django.shortcuts import redirect
from django.urls import path
from .models import *
import csv
import openpyxl
from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from django.db.models import Count
from django.urls import reverse


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
    list_display   = ('title', 'company', 'application_count_link', 'location', 'job_type', 'experience',
                      'work_mode', 'is_active', 'is_featured', 'openings', 'posted_at')
    
    list_filter    = ('is_active', 'is_featured', 'job_type', 'work_mode', 'category')
    search_fields  = ('title', 'company', 'location', 'skills_required')
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

    def get_queryset(self, request):
        """Annotate the queryset with the count of applications for fast loading."""
        queryset = super().get_queryset(request)
        queryset = queryset.annotate(_application_count=Count('applications'))
        return queryset

    @admin.display(description='Total Applicants', ordering='_application_count')
    def application_count_link(self, obj):
        """Create a clickable link that filters the JobApplication admin page."""
        count = obj._application_count
        
        if count == 0:
            return "0"
        
        url = (
            reverse("admin:vcs_jobapplication_changelist") 
            + "?"
            + f"job__id__exact={obj.id}"
        )
        return format_html('<a href="{}" style="font-weight: bold; color: #4b6cf5;">{} Applicants</a>', url, count)


@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('job', 'candidate', 'trainee', 'status', 'applied_at')
    list_filter   = ('status', 'applied_at')
    search_fields = ('candidate__full_name', 'job__title')
    list_editable = ('status',)
    readonly_fields = ('applied_at', 'updated_at')
    actions = ['export_as_csv', 'export_as_excel', 'export_as_pdf']

    @admin.action(description="Export Selected as CSV")
    def export_as_csv(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="job_applications.csv"'
        
        writer = csv.writer(response)
        writer.writerow(['Job Title', 'Candidate Name', 'Trainee Name', 'Status', 'Date Applied'])
        
        for app in queryset:
            candidate_name = app.candidate.full_name if app.candidate else 'N/A'
            trainee_name = app.trainee.full_name if app.trainee else 'N/A'
            writer.writerow([app.job.title, candidate_name, trainee_name, app.status, app.applied_at.strftime('%Y-%m-%d %H:%M')])
            
        return response

    @admin.action(description="Export Selected as Excel")
    def export_as_excel(self, request, queryset):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "Applications"
        
        headers = ['Job Title', 'Candidate Name', 'Trainee Name', 'Status', 'Date Applied']
        sheet.append(headers)
        
        for cell in sheet[1]:
            cell.font = openpyxl.styles.Font(bold=True)
            
        for app in queryset:
            candidate_name = app.candidate.full_name if app.candidate else 'N/A'
            trainee_name = app.trainee.full_name if app.trainee else 'N/A'
            sheet.append([app.job.title, candidate_name, trainee_name, app.status, app.applied_at.strftime('%Y-%m-%d %H:%M')])
            
        for col in sheet.columns:
            max_length = max(len(str(cell.value)) for cell in col if cell.value)
            sheet.column_dimensions[col[0].column_letter].width = max_length + 2

        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = 'attachment; filename="job_applications.xlsx"'
        workbook.save(response)
        
        return response

    @admin.action(description="Export Selected as PDF")
    def export_as_pdf(self, request, queryset):
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="job_applications.pdf"'
        doc = SimpleDocTemplate(response, pagesize=landscape(letter))
        elements = []
        
        data = [['Job Title', 'Candidate Name', 'Trainee Name', 'Status', 'Date Applied']]

        for app in queryset:
            candidate_name = app.candidate.full_name if app.candidate else 'N/A'
            trainee_name = app.trainee.full_name if app.trainee else 'N/A'
            data.append([
                str(app.job.title)[:30], 
                candidate_name[:25], 
                trainee_name[:25], 
                app.status, 
                app.applied_at.strftime('%Y-%m-%d')
            ])
            
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4238ca')), 
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fbff')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#d8e4f0')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('PADDING', (0, 0), (-1, -1), 6),
        ]))
        
        elements.append(table)
        doc.build(elements)
        
        return response


@admin.register(Feed)
class FeedAdmin(admin.ModelAdmin):
    list_display   = ('title', 'feed_type', 'author_name', 'is_published',
                      'is_featured', 'views', 'published_at')
    list_filter    = ('feed_type', 'is_published', 'is_featured')
    search_fields  = ('title', 'author_name', 'tags')
    list_editable  = ('is_published', 'is_featured')
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields     = ('published_at', 'updated_at', 'views')

    fieldsets = (
        ('Content', {
            'fields': ('title', 'slug', 'feed_type', 'media_file',
                       'excerpt', 'content', 'author_name', 'tags')
        }),
        ('Visibility', {
            'fields': ('is_published', 'is_featured')
        }),
        ('Stats', {
            'fields': ('views', 'published_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

@admin.register(SubscriptionOffer)
class SubscriptionOfferAdmin(admin.ModelAdmin):
    list_display = ('main_title', 'subtitle', 'is_active')
    list_editable = ('is_active',)


@admin.register(ProFeature)
class ProFeatureAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'order')
    list_editable = ('is_active', 'order')


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        'months', 'days', 'base_price', 'discount1', 
        'discount2', 'is_popular', 'is_active', 'final_calculated_price'
    )
    list_filter = ('is_active', 'is_popular', 'months', 'days')
    search_fields = ('discount1_code', 'discount2_code')
    
    fieldsets = (
        ('Plan Duration & Price', {
            'fields': ('months', 'days', 'base_price'),
            'description': "Set either Months or Days. For a 28-day plan, set Months to 0 and Days to 28."
        }),
        ('First Discount (Duration Based)', {
            'fields': ('discount1', 'discount1_code'),
            'description': "Example: 33% off for buying 3 months."
        }),
        ('Second Discount (Promo Based)', {
            'fields': ('discount2', 'discount2_code'),
            'description': "Example: 30% off PROSALE promo."
        }),
        ('Taxes & Display', {
            'fields': ('gst_pct', 'is_popular', 'daily_text', 'is_active')
        }),
    )



@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display  = ('candidate', 'plan', 'amount_rupees_display', 'status',
                      'razorpay_order_id', 'created_at', 'paid_at')
    list_filter   = ('status', 'created_at')
    search_fields = ('candidate__full_name', 'razorpay_order_id', 'razorpay_payment_id')
    readonly_fields = ('razorpay_order_id', 'razorpay_payment_id',
                       'razorpay_signature', 'created_at', 'paid_at')

    def amount_rupees_display(self, obj):
        return f"₹{obj.amount_rupees}"
    amount_rupees_display.short_description = 'Amount'


@admin.register(TermsAndConditions)
class TermsAndConditionsAdmin(admin.ModelAdmin):
    list_display = ('title', 'role', 'is_active', 'updated_at')
    list_filter = ('role', 'is_active')
    search_fields = ('title', 'content')
    list_editable = ('is_active',) 
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChatbotDocument)
class ChatbotDocumentAdmin(admin.ModelAdmin):
    list_display  = ('title', 'is_active', 'page_count', 'chunk_count', 'indexed_at', 'status_badge', 'index_action')
    list_filter   = ('is_active',)
    search_fields = ('title', 'description')
    readonly_fields = ('indexed_at', 'page_count', 'chunk_count', 'uploaded_at')

    def status_badge(self, obj):
        if not obj.indexed_at: 
            return format_html('<span style="color:red;">{}</span>', '⏳ Not Indexed')
        return format_html('<span style="color:green;">{}</span>', '✓ Indexed')
    
    def index_action(self, obj):
        return format_html('<a href="/admin/vcs/chatbotdocument/{}/index/" class="button">⚡ Index</a>', obj.pk)

    def get_urls(self):
        return [path('<int:doc_id>/index/', self.admin_site.admin_view(self.index_view))] + super().get_urls()

    def index_view(self, request, doc_id):
        from .rag_engine import index_document
        try:
            doc = ChatbotDocument.objects.get(pk=doc_id)
            count = index_document(doc)
            self.message_user(request, f'Indexed successfully: {count} chunks.', admin_messages.SUCCESS)
        except Exception as e:
            self.message_user(request, f'Failed: {e}', admin_messages.ERROR)
        return redirect('/admin/vcs/chatbotdocument/')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        
        if not change or 'pdf_file' in form.changed_data:
            from .rag_engine import index_document
            try:
                index_document(obj)
                self.message_user(request, "Document uploaded and indexed perfectly!", admin_messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"Document saved, but indexing failed: {e}", admin_messages.ERROR)

    def delete_model(self, request, obj):
        from .rag_engine import delete_document_vectors
        delete_document_vectors(obj.id)
        super().delete_model(request, obj)