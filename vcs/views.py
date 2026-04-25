from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from .models import *


# ── HELPERS ────────────────────────────────────────────────────────────────
def redirect_by_role(user):
    role = user.role
    if role == User.Role.CANDIDATE:
        return redirect('candidate_dashboard')
    elif role == User.Role.TRAINEE:
        return redirect('trainee_dashboard')
    elif role == User.Role.COMPANY:
        return redirect('company_dashboard')
    return redirect('login')


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


# ── LOGIN ──────────────────────────────────────────────────────────────────
def login_view(request):
    ui_settings = UISettings.objects.first()
    if request.user.is_authenticated:
        return redirect_by_role(request.user)

    if request.method == 'POST':
        login_type = request.POST.get('login_type', '').strip().lower()
        username   = request.POST.get('username', '').strip()
        password   = request.POST.get('password', '')

        def fail(msg):
            messages.error(request, msg)
            return render(request, 'login.html', {'active_tab': login_type})

        user = authenticate(request, username=username, password=password)

        if user is None:
            return fail("Invalid username or password.")

        if user.role != login_type:
            label = user.get_role_display() if user.role else "Unknown"
            return fail(f"Wrong portal. Your account type is: {label}.")

        if login_type == User.Role.COMPANY:
            if not hasattr(user, 'company_profile'):
                return fail("Company profile missing. Contact admin.")
            if not user.company_profile.is_approved:
                return fail("Your account is pending admin approval.")

        if login_type == User.Role.TRAINEE:
            if hasattr(user, 'trainee_profile') and not user.trainee_profile.is_active:
                return fail("Your trainee account has been deactivated.")

        login(request, user)
        return redirect_by_role(user)

    return render(request, 'login.html',
                {'active_tab': 'candidate',
                 'ui_settings': ui_settings,
                 })


# ── LOGOUT ─────────────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('login')


# ── CANDIDATE REGISTER ─────────────────────────────────────────────────────
def candidate_register(request):
    ui_settings = UISettings.objects.first()
    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        username  = request.POST.get('username', '').strip()
        email     = request.POST.get('email', '').strip().lower()
        pass1     = request.POST.get('password1', '')
        pass2     = request.POST.get('password2', '')
        terms     = request.POST.get('terms') == 'on'

        errors = {}

        if not full_name:
            errors['full_name'] = "Full name is required."
        if not username:
            errors['username'] = "Username is required."
        elif ' ' in username:
            errors['username'] = "No spaces allowed."
        if not email:
            errors['email'] = "Email is required."
        if not pass1:
            errors['password1'] = "Password is required."
        elif len(pass1) < 8:
            errors['password1'] = "Minimum 8 characters."
        if pass1 and pass2 and pass1 != pass2:
            errors['password2'] = "Passwords do not match."
        if not terms:
            errors['terms'] = "You must accept the terms."
        if username and not errors.get('username'):
            if User.objects.filter(username__iexact=username).exists():
                errors['username'] = "Username already taken."
        if email and not errors.get('email'):
            if User.objects.filter(email__iexact=email).exists():
                errors['email'] = "Email already registered."

        if errors:
            return render(request, 'candidate_register.html', {
                'errors': errors,
                'form_data': {'full_name': full_name, 'username': username, 'email': email},
            })

        user = User.objects.create_user(
            username = username,
            email    = email,
            password = pass1,
            role     = User.Role.CANDIDATE,
        )
        CandidateProfile.objects.create(
            user           = user,
            full_name      = full_name,
            accepted_terms = True,
        )
        messages.success(request, "Account created! Please log in.")
        return redirect('login')

    return render(request, 'candidate_register.html',
                  {'ui_settings': ui_settings,})


# ── COMPANY REGISTER ───────────────────────────────────────────────────────
def company_register(request):
    ui_settings = UISettings.objects.first()
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

    return render(request, 'company_register.html',
                  {'ui_settings': ui_settings,})


@login_required(login_url='login')
def dashboard_router(request):
    """Routes the logged-in user to their specific dashboard"""
    return redirect_by_role(request.user)

# ── DASHBOARDS ─────────────────────────────────────────────────────────────
@login_required(login_url='login')
def candidate_dashboard(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')
    
    if not hasattr(request.user, 'candidate_profile'):
        CandidateProfile.objects.get_or_create(
            user=request.user,
            defaults={'full_name': request.user.username}
        )
    return render(request, 'candidate_dashboard.html', {
        'profile': request.user.candidate_profile
    })

@login_required(login_url='login')
def candidate_profile(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')

    profile, created = CandidateProfile.objects.get_or_create(
        user=request.user,
        defaults={'full_name': request.user.username}
    )
    context = {
        'profile': profile,
    }
    return render(request, 'candidate_profile.html', context)

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
    return render(request, 'company_dashboard.html', {
        'profile': request.user.company_profile
    })