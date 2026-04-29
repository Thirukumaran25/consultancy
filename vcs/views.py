# vcs/views.py
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from .models import *
from .otp_utils import generate_otp, send_otp_email
from django.shortcuts import get_object_or_404
from .recommender import get_recommendations, get_skill_gap



# ── HELPERS ────────────────────────────────────────────────────────────────
def redirect_by_role(user):
    if user.role == User.Role.CANDIDATE:
        return redirect('candidate_dashboard')
    elif user.role == User.Role.TRAINEE:
        return redirect('trainee_dashboard')
    elif user.role == User.Role.COMPANY:
        return redirect('company_dashboard')
    return redirect('login')


def get_ui():
    return UISettings.objects.first()


# ── CHECK USERNAME / EMAIL AVAILABILITY (AJAX) ─────────────────────────────
def check_availability(request):
    username = request.GET.get('username')
    email    = request.GET.get('email')
    taken    = False
    if username:
        taken = User.objects.filter(username__iexact=username).exists()
    elif email:
        taken = User.objects.filter(email__iexact=email).exists()
    return JsonResponse({'is_taken': taken})



@login_required(login_url='login')
def upgrade_subscription(request):
    if request.method == 'POST' and getattr(request.user, 'role', '') == 'candidate':
        profile = request.user.candidate_profile
        profile.subscription_type = 'Pro'  # Updates to Pro
        profile.save()
        messages.success(request, "🎉 Successfully upgraded to PRO!")
    return redirect('candidate_profile')


# ── LOGIN ──────────────────────────────────────────────────────────────────
def login_view(request):
    if request.user.is_authenticated:
        return redirect_by_role(request.user)

    if request.method == 'POST':
        login_type = request.POST.get('login_type', '').strip().lower()
        username   = request.POST.get('username', '').strip()
        password   = request.POST.get('password', '')

        def fail(msg):
            messages.error(request, msg)
            return render(request, 'login.html', {
                'active_tab': login_type,
                'ui_settings': get_ui(),
            })

        user = authenticate(request, username=username, password=password)

        if user is None:
            return fail("Invalid username or password.")

        if user.role != login_type:
            label = user.get_role_display() if user.role else "Unknown"
            return fail(f"Wrong portal. Your account type is: {label}.")

        if login_type == User.Role.COMPANY:
            if not hasattr(user, 'company_profile'):
                return fail("Company profile missing. Contact admin.")
            
            profile = user.company_profile
            if profile.status == 'Rejected':
                reason = profile.rejection_reason or "No reason provided."
                return fail(f"Registration Rejected: {reason}")
            
            elif profile.status == 'Pending':
                return fail("Your account is pending admin approval.")

        if login_type == User.Role.TRAINEE:
            if hasattr(user, 'trainee_profile') and not user.trainee_profile.is_active:
                return fail("Your trainee account has been deactivated.")

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return redirect_by_role(user)

    return render(request, 'login.html', {
        'active_tab': 'candidate',
        'ui_settings': get_ui(),
    })


# ── LOGOUT ─────────────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('login')


# ── SEND OTP (email only) ──────────────────────────────────────────────────
def send_registration_otp(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request.'})

    email = request.POST.get('target', '').strip()

    if not email:
        return JsonResponse({'success': False, 'error': 'Email address is missing.'})

    otp = generate_otp()

    # Store in session with timestamp
    request.session['registration_otp']      = otp
    request.session['registration_otp_email'] = email
    request.session['registration_otp_time'] = timezone.now().isoformat()

    # Always print to terminal for dev reference
    print(f"\n====== [DEV OTP] ======")
    print(f"Email : {email}")
    print(f"OTP   : {otp}")
    print(f"=======================\n")

    success, message = send_otp_email(email, otp)

    if success:
        return JsonResponse({'success': True, 'message': message})
    else:
        return JsonResponse({'success': False, 'error': message})


# ── CANDIDATE REGISTER ─────────────────────────────────────────────────────
def candidate_register(request):
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        username  = request.POST.get('username', '').strip()
        email     = request.POST.get('email', '').strip().lower()
        phone     = request.POST.get('phone_number', '').strip()
        pass1     = request.POST.get('password1', '')
        pass2     = request.POST.get('password2', '')
        terms     = request.POST.get('terms') == 'on'
        otp       = request.POST.get('otp', '').strip()

        errors = {}

        # Field validations
        if not full_name:
            errors['full_name'] = "Full name is required."
        if not username:
            errors['username'] = "Username is required."
        elif ' ' in username:
            errors['username'] = "No spaces allowed."
        if not email:
            errors['email'] = "Email is required."
        if not phone:
            errors['phone_number'] = "Mobile number is required."
        if not pass1:
            errors['password1'] = "Password is required."
        elif len(pass1) < 8:
            errors['password1'] = "Minimum 8 characters."
        if pass1 and pass2 and pass1 != pass2:
            errors['password2'] = "Passwords do not match."
        if not terms:
            errors['terms'] = "You must accept the terms."

        # Uniqueness checks
        if username and not errors.get('username'):
            if User.objects.filter(username__iexact=username).exists():
                errors['username'] = "Username already taken."
        if email and not errors.get('email'):
            if User.objects.filter(email__iexact=email).exists():
                errors['email'] = "Email already registered."

        # OTP validation with expiry
        session_otp      = request.session.get('registration_otp')
        session_otp_time = request.session.get('registration_otp_time')

        if not otp:
            errors['otp'] = "Verification code is required."
        elif not session_otp:
            errors['otp'] = "No OTP found. Please request a new code."
        elif otp != session_otp:
            errors['otp'] = "Invalid verification code."
        elif session_otp_time:
            otp_time = timezone.datetime.fromisoformat(session_otp_time)
            if timezone.is_naive(otp_time):
                otp_time = timezone.make_aware(otp_time)
            if timezone.now() - otp_time > timedelta(minutes=10):
                errors['otp'] = "OTP has expired. Please request a new one."
                request.session.pop('registration_otp', None)
                request.session.pop('registration_otp_time', None)

        if errors:
            return render(request, 'candidate_register.html', {
                'errors':    errors,
                'form_data': {
                    'full_name': full_name,
                    'username':  username,
                    'email':     email,
                    'phone':     phone,
                },
                'ui_settings': get_ui(),
            })

        # Create user and profile
        user = User.objects.create_user(
            username = username,
            email    = email,
            password = pass1,
            role     = User.Role.CANDIDATE,
        )

        profile = user.candidate_profile
        profile.full_name      = full_name
        profile.phone_number   = phone
        profile.accepted_terms = True
        profile.save()

        # Clear OTP from session
        request.session.pop('registration_otp', None)
        request.session.pop('registration_otp_email', None)
        request.session.pop('registration_otp_time', None)

        # Auto-login
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, "Account created and verified successfully!")
        return redirect('candidate_dashboard')

    return render(request, 'candidate_register.html', {'ui_settings': get_ui()})


# ── DASHBOARD ROUTER ───────────────────────────────────────────────────────
@login_required(login_url='login')
def dashboard_router(request):
    return redirect_by_role(request.user)


# ── DASHBOARDS ─────────────────────────────────────────────────────────────
@login_required(login_url='login')
def candidate_dashboard(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')

    profile, _ = CandidateProfile.objects.get_or_create(
        user=request.user,
        defaults={'full_name': request.user.username}
    )

    # ── Application stats ───────────────────────────────────────────────
    all_apps     = JobApplication.objects.filter(candidate=profile)
    stats = {
        'total':       all_apps.count(),
        'shortlisted': all_apps.filter(status='Shortlisted').count(),
        'pending':     all_apps.filter(status__in=['Applied', 'Reviewing']).count(),
        'rejected':    all_apps.filter(status='Rejected').count(),
        'interview':   all_apps.filter(status='Interview').count(),
        'offered':     all_apps.filter(status='Offered').count(),
    }

    # ── Recent applications ─────────────────────────────────────────────
    recent_apps = all_apps.select_related('job').order_by('-applied_at')[:5]

    # ── ML Recommendations ──────────────────────────────────────────────
    recommended = get_recommendations(profile, limit=6)

    # Add skill gap to each recommendation
    recommendations_with_gap = []
    for job, score in recommended:
        matching, missing = get_skill_gap(profile, job)
        match_pct = int(score * 100)
        recommendations_with_gap.append({
            'job':      job,
            'score':    score,
            'match':    match_pct,
            'matching': matching[:4],
            'missing':  missing[:3],
        })

    # ── Profile completeness ────────────────────────────────────────────
    checks = [
        bool(profile.resume_headline),
        bool(profile.profile_summary),
        bool(profile.resume),
        profile.skills.exists(),
        profile.employments.exists() or profile.is_fresher,
        profile.educations.exists(),
        bool(profile.phone_number),
    ]
    profile_pct = int(sum(checks) / len(checks) * 100)

    return render(request, 'candidate_dashboard.html', {
        'profile':       profile,
        'stats':         stats,
        'recent_apps':   recent_apps,
        'recommended':   recommendations_with_gap,
        'profile_pct':   profile_pct,
        'ui_settings':   get_ui(),
    })


@login_required(login_url='login')
def candidate_profile(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')
    profile, _ = CandidateProfile.objects.get_or_create(
        user=request.user,
        defaults={'full_name': request.user.username}
    )
    return render(request, 'candidate_profile.html', {'profile': profile})


@login_required(login_url='login')
def candidate_profile(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')
    profile, _ = CandidateProfile.objects.get_or_create(
        user=request.user, defaults={'full_name': request.user.username}
    )
    has_employment = profile.employments.exists() or profile.is_fresher
    return render(request, 'candidate_profile.html', {
        'profile': profile,
        'has_employment': has_employment,
        'ui_settings': get_ui(),
        'quick_links': [
            ('resume', 'Resume'), ('headline', 'Resume Headline'),
            ('summary', 'Profile Summary'), ('skills', 'Key Skills'),
            ('employment', 'Employment'), ('education', 'Education'),
            ('projects', 'Projects'), ('personal', 'Personal Details'),
        ],
    })


@login_required(login_url='login')
def update_headline(request):
    if request.method == 'POST':
        profile = request.user.candidate_profile
        profile.resume_headline = request.POST.get('resume_headline', '').strip()
        profile.save()
        messages.success(request, "Headline updated.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_summary(request):
    if request.method == 'POST':
        profile = request.user.candidate_profile
        profile.profile_summary = request.POST.get('profile_summary', '').strip()
        profile.save()
        messages.success(request, "Summary updated.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_personal(request):
    if request.method == 'POST':
        p = request.user.candidate_profile
        p.gender          = request.POST.get('gender') or None
        p.marital_status  = request.POST.get('marital_status') or None
        p.date_of_birth   = request.POST.get('date_of_birth') or None
        p.phone_number    = request.POST.get('phone_number', '').strip() or None
        p.languages_known = request.POST.get('languages_known', '').strip() or None
        p.save()
        messages.success(request, "Personal details updated.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_resume(request):
    if request.method == 'POST' and request.FILES.get('resume'):
        profile = request.user.candidate_profile
        profile.resume = request.FILES['resume']
        profile.save()
        messages.success(request, "Resume updated.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def add_skill(request):
    if request.method == 'POST':
        raw = request.POST.get('skill_name', '').strip()
        if raw:
            # Split by comma, add each skill separately
            skill_names = [s.strip() for s in raw.split(',') if s.strip()]
            for name in skill_names:
                skill, _ = Skill.objects.get_or_create(
                    name__iexact=name,
                    defaults={'name': name}
                )
                request.user.candidate_profile.skills.add(skill)
            count = len(skill_names)
            messages.success(request, f"{count} skill{'s' if count > 1 else ''} added.")
    return redirect('candidate_profile')



@login_required(login_url='login')
def remove_skill(request, skill_id):
    if request.method == 'POST':
        skill = Skill.objects.get(id=skill_id)
        request.user.candidate_profile.skills.remove(skill)
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_profile_photo(request):
    if request.method == 'POST' and request.FILES.get('profile_photo'):
        profile = request.user.candidate_profile
        profile.profile_photo = request.FILES['profile_photo']
        profile.save()
        messages.success(request, "Profile photo updated.")
    return redirect('candidate_profile')

@login_required(login_url='login')
def save_employment(request):
    if request.method == 'POST':
        profile    = request.user.candidate_profile
        emp_id     = request.POST.get('emp_id')
        is_current = request.POST.get('is_current') == 'on'
        data = {
            'designation':  request.POST.get('designation', '').strip(),
            'company_name': request.POST.get('company_name', '').strip(),
            'start_date':   request.POST.get('start_date'),
            'end_date':     None if is_current else request.POST.get('end_date') or None,
            'is_current':   is_current,
            'location':     request.POST.get('location', '').strip() or None,
            'description':  request.POST.get('description', '').strip() or None,
        }
        if emp_id:
            Employment.objects.filter(id=emp_id, candidate=profile).update(**data)
            messages.success(request, "Employment updated.")
        else:
            Employment.objects.create(candidate=profile, **data)
            messages.success(request, "Employment added.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_employment(request, emp_id):
    if request.method == 'POST':
        Employment.objects.filter(id=emp_id, candidate=request.user.candidate_profile).delete()
        messages.success(request, "Employment deleted.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def save_education(request):
    if request.method == 'POST':
        profile = request.user.candidate_profile
        edu_id  = request.POST.get('edu_id')
        data = {
            'education_level': request.POST.get('education_level', '').strip(),
            'course':          request.POST.get('course', '').strip() or None,
            'university':      request.POST.get('university', '').strip(),
            'start_year':      request.POST.get('start_year'),
            'end_year':        request.POST.get('end_year'),
            'course_type':     request.POST.get('course_type', 'Full Time'),
        }
        if edu_id:
            Education.objects.filter(id=edu_id, candidate=profile).update(**data)
            messages.success(request, "Education updated.")
        else:
            Education.objects.create(candidate=profile, **data)
            messages.success(request, "Education added.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_education(request, edu_id):
    if request.method == 'POST':
        Education.objects.filter(id=edu_id, candidate=request.user.candidate_profile).delete()
        messages.success(request, "Education deleted.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def save_project(request):
    if request.method == 'POST':
        profile    = request.user.candidate_profile
        proj_id    = request.POST.get('proj_id')
        is_ongoing = request.POST.get('is_ongoing') == 'on'
        data = {
            'title':       request.POST.get('title', '').strip(),
            'project_url': request.POST.get('project_url', '').strip() or None,
            'start_date':  request.POST.get('start_date') or None,
            'end_date':    None if is_ongoing else request.POST.get('end_date') or None,
            'is_ongoing':  is_ongoing,
            'description': request.POST.get('description', '').strip(),
        }
        if proj_id:
            Project.objects.filter(id=proj_id, candidate=profile).update(**data)
            messages.success(request, "Project updated.")
        else:
            Project.objects.create(candidate=profile, **data)
            messages.success(request, "Project added.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_project(request, proj_id):
    if request.method == 'POST':
        Project.objects.filter(id=proj_id, candidate=request.user.candidate_profile).delete()
        messages.success(request, "Project deleted.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def mark_fresher(request):
    if request.method == 'POST':
        profile = request.user.candidate_profile
        if request.POST.get('unmark'):
            profile.is_fresher = False
            messages.success(request, "Fresher status removed.")
        else:
            profile.is_fresher = True
            messages.success(request, "Marked as Fresher.")
        profile.save()
    return redirect('candidate_profile')


# ── COMPANY REGISTER ───────────────────────────────────────────────────────
def company_register(request):
    if request.method == 'POST':
        company_name = request.POST.get('company_name', '').strip()
        username     = request.POST.get('username', '').strip()
        email        = request.POST.get('email', '').strip().lower()
        location     = request.POST.get('location', '').strip()
        pass1        = request.POST.get('password1', '')
        pass2        = request.POST.get('password2', '')
        terms        = request.POST.get('terms') == 'on'
        reg_doc      = request.FILES.get('registration_document')
        gst_doc      = request.FILES.get('gst_document')
        photos       = request.FILES.getlist('company_photos')

        errors = {}

        if not company_name:
            errors['company_name'] = "Company name is required."
        if not username:
            errors['username'] = "Username is required."
        elif ' ' in username:
            errors['username'] = "No spaces allowed."
        if not email:
            errors['email'] = "Email is required."
        if not location:
            errors['location'] = "Location is required."
        if not pass1:
            errors['password1'] = "Password is required."
        elif len(pass1) < 8:
            errors['password1'] = "Minimum 8 characters."
        if pass1 and pass2 and pass1 != pass2:
            errors['password2'] = "Passwords do not match."
        if not reg_doc:
            errors['registration_document'] = "Registration document required."
        if not gst_doc:
            errors['gst_document'] = "GST document required."
        if not terms:
            errors['terms'] = "You must accept the terms."
        if username and not errors.get('username'):
            if User.objects.filter(username__iexact=username).exists():
                errors['username'] = "Username already taken."
        if email and not errors.get('email'):
            if User.objects.filter(email__iexact=email).exists():
                errors['email'] = "Email already registered."

        if errors:
            return render(request, 'company_register.html', {
                'errors': errors,
                'form_data': {
                    'company_name':  company_name,
                    'username':      username,
                    'email':         email,
                    'location':      location,
                    'linkedin_url':  request.POST.get('linkedin_url', ''),
                    'website_url':   request.POST.get('website_url', ''),
                    'instagram_url': request.POST.get('instagram_url', ''),
                    'facebook_url':  request.POST.get('facebook_url', ''),
                },
                'ui_settings': get_ui(),
            })

        user = User.objects.create_user(
            username = username,
            email    = email,
            password = pass1,
            role     = User.Role.COMPANY,
        )
        profile = CompanyProfile.objects.create(
            user                  = user,
            company_name          = company_name,
            email                 = email,
            location              = location,
            registration_document = reg_doc,
            gst_document          = gst_doc,
            accepted_terms        = True,
            linkedin_url          = request.POST.get('linkedin_url') or None,
            website_url           = request.POST.get('website_url') or None,
            instagram_url         = request.POST.get('instagram_url') or None,
            facebook_url          = request.POST.get('facebook_url') or None,
        )
        for photo in photos:
            if photo:
                CompanyPhoto.objects.create(company=profile, photo=photo)

        messages.success(request, "Registered! Awaiting admin approval.")
        return redirect('login')

    return render(request, 'company_register.html', {'ui_settings': get_ui()})


def check_company_status(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            if user.role != User.Role.COMPANY:
                return JsonResponse({'success': False, 'message': 'This account is not registered as a Company.'})
            
            profile = getattr(user, 'company_profile', None)
            if not profile:
                return JsonResponse({'success': False, 'message': 'Company profile missing.'})
            
            if profile.status == 'Approved':
                return JsonResponse({
                    'success': True, 
                    'status': 'Approved',
                    'message': 'Your application has been approved! You can close this and log in.',
                    'color_class': 'text-[#057a2e] bg-[#e6fff0] border-[#b2f2bb]'
                })
            elif profile.status == 'Rejected':
                reason = profile.rejection_reason or "No reason provided by admin."
                return JsonResponse({
                    'success': True, 
                    'status': 'Rejected',
                    'message': f'Your application was rejected.<br><br><strong>Reason:</strong> {reason}',
                    'color_class': 'text-[#c0392b] bg-[#fff0f0] border-[#ffd0d0]'
                })
            else:
                return JsonResponse({
                    'success': True, 
                    'status': 'Pending',
                    'message': 'Your application is currently under review by our admin team.',
                    'color_class': 'text-[#b45309] bg-[#fff7e6] border-[#fcd34d]'
                })
        else:
            return JsonResponse({'success': False, 'message': 'Invalid username or password.'})
    return JsonResponse({'success': False, 'message': 'Invalid request.'})



@login_required(login_url='login')
def trainee_dashboard(request):
    if request.user.role != User.Role.TRAINEE:
        return redirect('login')
    if not hasattr(request.user, 'trainee_profile'):
        TraineeProfile.objects.create(
            user=request.user,
            full_name=request.user.username
        )
    return render(request, 'trainee_dashboard.html', {
        'profile': request.user.trainee_profile
    })


@login_required(login_url='login')
def company_dashboard(request):
    if request.user.role != User.Role.COMPANY:
        return redirect('login')
    
    profile = request.user.company_profile
    
    # Fetch jobs and applications belonging to this specific company
    my_jobs = Job.objects.filter(company_profile=profile).order_by('-posted_at')
    applications = JobApplication.objects.filter(job__company_profile=profile).select_related('job', 'candidate', 'candidate__user').order_by('-applied_at')
    
    # Calculate Stats
    stats = {
        'jobs_count': my_jobs.count(),
        'applicants_count': applications.count(),
        'hired_count': applications.filter(status='Offered').count() 
    }
    
    return render(request, 'company_dashboard.html', {
        'profile': profile,
        'my_jobs': my_jobs,
        'applications': applications,
        'stats': stats,
        'categories': JobCategory.objects.all(),
        'job_types': Job.JobType.choices,
        'work_modes': Job.WorkMode.choices,
    })


@login_required(login_url='login')
def company_post_job(request):
    if request.method == 'POST' and request.user.role == User.Role.COMPANY:
        profile = request.user.company_profile
        
        if profile.status != 'Approved':
            messages.error(request, "Your account must be approved by an admin before you can post jobs.")
            return redirect('company_dashboard')
            
        cat_id = request.POST.get('category')
        category = JobCategory.objects.filter(id=cat_id).first() if cat_id else None
        
        Job.objects.create(
            # Core
            company_profile=profile,
            company=profile.company_name,
            title=request.POST.get('title', ''),
            category=category,
            location=request.POST.get('location', ''),
            
            # Classification
            job_type=request.POST.get('job_type', 'Full Time'),
            work_mode=request.POST.get('work_mode', 'On-site'),
            experience=request.POST.get('experience', ''),
            openings=request.POST.get('openings') or 1,
            deadline=request.POST.get('deadline') or None,
            
            # Salary & Skills
            salary_min=request.POST.get('salary_min') or None,
            salary_max=request.POST.get('salary_max') or None,
            salary_hidden=request.POST.get('salary_hidden') == 'on',
            skills_required=request.POST.get('skills_required', ''),
            
            # Text Areas
            description=request.POST.get('description', ''),
            responsibilities=request.POST.get('responsibilities', ''),
            requirements=request.POST.get('requirements', ''),
            benefits=request.POST.get('benefits', ''),
            
            # HR Contact Details
            hr_name=request.POST.get('hr_name', ''),
            hr_email=request.POST.get('hr_email', ''),
            hr_phone=request.POST.get('hr_phone', ''),
            
            # Status
            is_active=True
        )
        messages.success(request, "Job posted successfully!")
    return redirect('company_dashboard')


@login_required(login_url='login')
def company_delete_job(request, job_id):
    if request.method == 'POST' and request.user.role == User.Role.COMPANY:
        job = get_object_or_404(Job, id=job_id, company_profile=request.user.company_profile)
        job.delete()
        messages.success(request, "Job deleted successfully.")
    return redirect('company_dashboard')

@login_required(login_url='login')
def company_edit_job(request, job_id):
    # Ensure only companies can access this
    if request.user.role != User.Role.COMPANY:
        return redirect('login')
        
    # Get the job, ensuring it belongs to the logged-in company
    job = get_object_or_404(Job, id=job_id, company_profile=request.user.company_profile)
    
    if request.method == 'POST':
        # 1. Update Category
        cat_id = request.POST.get('category')
        if cat_id:
            job.category = JobCategory.objects.filter(id=cat_id).first()
            
        # 2. Update Core Text Fields
        job.title = request.POST.get('title', job.title)
        job.location = request.POST.get('location', job.location)
        job.job_type = request.POST.get('job_type', job.job_type)
        job.work_mode = request.POST.get('work_mode', job.work_mode)
        job.experience = request.POST.get('experience', job.experience)
        job.skills_required = request.POST.get('skills_required', job.skills_required)
        
        # 3. Update Numbers & Dates (handle empty inputs safely)
        openings = request.POST.get('openings')
        if openings:
            job.openings = int(openings)
            
        deadline = request.POST.get('deadline')
        job.deadline = deadline if deadline else None
        
        salary_min = request.POST.get('salary_min')
        job.salary_min = int(salary_min) if salary_min else None
        
        salary_max = request.POST.get('salary_max')
        job.salary_max = int(salary_max) if salary_max else None
        
        job.salary_hidden = request.POST.get('salary_hidden') == 'on'
        
        # 4. Update Large Text Areas
        job.description = request.POST.get('description', job.description)
        job.responsibilities = request.POST.get('responsibilities', '')
        job.requirements = request.POST.get('requirements', '')
        job.benefits = request.POST.get('benefits', '')
        
        # 5. Update HR Fields
        job.hr_name = request.POST.get('hr_name', '')
        job.hr_email = request.POST.get('hr_email', '')
        job.hr_phone = request.POST.get('hr_phone', '')

        # 6. Save to Database
        job.save()
        messages.success(request, "Job updated successfully.")
        return redirect('company_dashboard')
        
    return render(request, 'company_edit_job.html', {
        'job': job,
        'categories': JobCategory.objects.all(),
        'job_types': Job.JobType.choices,
        'work_modes': Job.WorkMode.choices,
    })


@login_required(login_url='login')
def update_application_status(request, app_id):
    if request.method == 'POST' and request.user.role == User.Role.COMPANY:
        status = request.POST.get('status')
        # Security: Ensure this company actually owns the job the application is for
        app = get_object_or_404(JobApplication, id=app_id, job__company_profile=request.user.company_profile)
        app.status = status
        app.save()
        messages.success(request, f"Applicant status updated to {status}.")
    return redirect('company_dashboard')


def job_list(request):
    jobs = Job.objects.filter(is_active=True).select_related('category')

    # ── Filters ────────────────────────────────────────────────────────────
    q          = request.GET.get('q', '').strip()
    location   = request.GET.get('location', '').strip()
    job_type   = request.GET.get('job_type', '').strip()
    work_mode  = request.GET.get('work_mode', '').strip()
    experience = request.GET.get('experience', '').strip()
    category   = request.GET.get('category', '').strip()
    salary     = request.GET.get('salary', '').strip()
    sort       = request.GET.get('sort', '').strip()

    any_filter_active = any([q, location, job_type, work_mode, experience, category, salary, sort])

    if q:
        jobs = jobs.filter(
            Q(title__icontains=q) |
            Q(company__icontains=q) |
            Q(skills_required__icontains=q) |
            Q(location__icontains=q)
        ).distinct()

    if location:
        jobs = jobs.filter(location__icontains=location)
    if job_type:
        jobs = jobs.filter(job_type=job_type)
    if work_mode:
        jobs = jobs.filter(work_mode=work_mode)
    if experience:
        jobs = jobs.filter(experience__icontains=experience)
    if category:
        jobs = jobs.filter(category__slug=category)
    if salary:
        salary_map = {'0-3': (0,3), '3-6': (3,6), '6-10': (6,10), '10+': (10, 9999)}
        if salary in salary_map:
            lo, hi = salary_map[salary]
            jobs = jobs.filter(salary_min__gte=lo, salary_max__lte=hi)

    # ── Applied job ids ────────────────────────────────────────────────────
    applied_ids   = []
    recommended_ids_ordered = []
    profile       = None

    if request.user.is_authenticated and request.user.role == 'candidate':
        if hasattr(request.user, 'candidate_profile'):
            profile = request.user.candidate_profile
            applied_ids = list(
                JobApplication.objects.filter(
                    candidate=profile
                ).values_list('job_id', flat=True)
            )

            if not any_filter_active:
                recs = get_recommendations(profile, limit=50)
                recommended_ids_ordered = [job.id for job, score in recs if score > 0]

    # ── Sort ───────────────────────────────────────────────────────────────
    if sort == 'salary':
        jobs = jobs.order_by('-salary_max')
    elif sort == 'featured':
        jobs = jobs.order_by('-is_featured', '-posted_at')
    elif sort == 'recent':
        jobs = jobs.order_by('-posted_at')
    else:
        jobs = jobs.order_by('-is_featured', '-posted_at')

    jobs_list = list(jobs)

    if recommended_ids_ordered and not any_filter_active and not sort:
        score_map = {jid: idx for idx, jid in enumerate(recommended_ids_ordered)}

        def sort_key(job):
            rec_rank = score_map.get(job.id, 9999)  # not in recs = goes to end
            featured_boost = 0 if job.is_featured else 1
            return (featured_boost, rec_rank)

        jobs_list.sort(key=sort_key)

    from django.core.paginator import Paginator
    paginator   = Paginator(jobs_list, 10)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)
    
    # ── Attach Match Scores Directly to Job Objects ──
    if recommended_ids_ordered and profile:
        recs = get_recommendations(profile, limit=50)
        score_dict = {job.id: round(score * 100) for job, score in recs}
        for job in page_obj:
            job.match_score = score_dict.get(job.id, 0)
    else:
        for job in page_obj:
            job.match_score = 0

    return render(request, 'jobs/job_list.html', {
        'page_obj':      page_obj,
        'total':         paginator.count,
        'categories':    JobCategory.objects.all(),
        'job_types':     Job.JobType.choices,
        'work_modes':    Job.WorkMode.choices,
        'salary_ranges': [
            ('0-3',  '0 – 3 LPA'),
            ('3-6',  '3 – 6 LPA'),
            ('6-10', '6 – 10 LPA'),
            ('10+',  '10+ LPA'),
        ],
        'applied_ids':   applied_ids,
        # Note: We removed 'match_scores' from here because we attached it to page_obj directly!
        'ui_settings':   get_ui(),
        'is_recommended_view': bool(recommended_ids_ordered and not any_filter_active and not sort),
        'filters': {
            'q': q, 'location': location, 'job_type': job_type,
            'work_mode': work_mode, 'experience': experience,
            'category': category, 'salary': salary, 'sort': sort,
        },
    })


def job_detail(request, slug):
    job = Job.objects.select_related('category').get(slug=slug, is_active=True)

    similar = Job.objects.filter(
        is_active=True, category=job.category
    ).exclude(id=job.id)[:4]

    already_applied = False
    application     = None
    if request.user.is_authenticated and request.user.role == 'candidate':
        if hasattr(request.user, 'candidate_profile'):
            application = JobApplication.objects.filter(
                job=job,
                candidate=request.user.candidate_profile
            ).first()
            already_applied = application is not None

    # Parse comma-separated skills string into list
    skills_list = [
        s.strip() for s in (job.skills_required or '').split(',') if s.strip()
    ]

    return render(request, 'jobs/job_detail.html', {
        'job':             job,
        'similar':         similar,
        'already_applied': already_applied,
        'application':     application,
        'skills_list':     skills_list,
        'responsibilities': [r.strip() for r in (job.responsibilities or '').split('\n') if r.strip()],
        'requirements':    [r.strip() for r in (job.requirements or '').split('\n') if r.strip()],
        'benefits':        [r.strip() for r in (job.benefits or '').split('\n') if r.strip()],
        'ui_settings':     get_ui(),
    })

@login_required(login_url='login')
def apply_job(request, slug):
    if request.user.role != 'candidate':
        messages.error(request, "Only candidates can apply for jobs.")
        return redirect('job_detail', slug=slug)

    job     = Job.objects.get(slug=slug, is_active=True)
    profile = request.user.candidate_profile

    if JobApplication.objects.filter(job=job, candidate=profile).exists():
        messages.warning(request, "You have already applied for this job.")
        return redirect('job_detail', slug=slug)

    if request.method == 'POST':
        profile.full_name = request.POST.get('full_name', profile.full_name)
        profile.phone_number = request.POST.get('phone', profile.phone_number)

        if 'resume' in request.FILES:
            profile.resume = request.FILES['resume']
            
        profile.save()

        new_email = request.POST.get('email')
        if new_email and new_email != request.user.email:
            request.user.email = new_email
            request.user.save()

        cover_letter = request.POST.get('cover_letter', '').strip()
        JobApplication.objects.create(
            job          = job,
            candidate    = profile,
            cover_letter = cover_letter or None,
        )
        messages.success(request, f"Successfully applied for {job.title}!")
        
    return redirect('job_detail', slug=slug)


@login_required(login_url='login')
def withdraw_application(request, slug):
    job = Job.objects.get(slug=slug)
    JobApplication.objects.filter(
        job=job,
        candidate=request.user.candidate_profile
    ).update(status=JobApplication.Status.WITHDRAWN)
    messages.success(request, "Application withdrawn.")
    return redirect('job_detail', slug=slug)


@login_required(login_url='login')
def my_applications(request):
    if request.user.role != 'candidate':
        return redirect('login')
    applications = JobApplication.objects.filter(
        candidate=request.user.candidate_profile
    ).select_related('job').order_by('-applied_at')

    return render(request, 'jobs/my_applications.html', {
        'applications': applications,
        'ui_settings':  get_ui(),
    })