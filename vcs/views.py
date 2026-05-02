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
from django.urls import reverse
import razorpay
import hmac
import hashlib
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
import json
from django.core.mail import send_mail



def get_razorpay_client():
    return razorpay.Client(
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
    )


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
    if getattr(request.user, 'role', '') != 'candidate':
        return redirect('dashboard')

    profile  = request.user.candidate_profile
    features = ProFeature.objects.filter(is_active=True).order_by('order')
    db_plans = SubscriptionPlan.objects.filter(is_active=True).order_by('months', 'days')

    def calculate_plan(p):
        """Strict Integer Calculation to prevent 1-rupee rounding mismatches."""
        base = int(round(float(p.base_price)))

        # Update variable names to match new model fields
        discount1_amount = int(round(base * (p.discount1 / 100.0)))
        after_disc1  = base - discount1_amount

        discount2_amount = int(round(after_disc1 * (p.discount2 / 100.0)))
        display_price = after_disc1 - discount2_amount

        gst_amount = int(round(display_price * (p.gst_pct / 100.0)))
        final_payable = display_price + gst_amount

        return {
            'base_price':       base,
            'discount1_amount': discount1_amount,
            'after_disc1':      after_disc1,
            'discount2_amount': discount2_amount,
            'display_price':    display_price,
            'gst_amount':       gst_amount,
            'final_payable':    final_payable,
        }

    processed_plans = []
    for p in db_plans:
        calc = calculate_plan(p)

        badge_text = ""
        if p.discount1 > 0 and p.discount2 > 0:
            badge_text = f"{p.discount1}% + {p.discount2}% off"
        elif p.discount1 > 0:
            badge_text = f"{p.discount1}% off"
        elif p.discount2 > 0:
            badge_text = f"{p.discount2}% off"

        processed_plans.append({
            'id':               p.id,
            'months':           p.months,
            'days':             p.days,
            'base_price':       calc['base_price'],
            'display_price':    calc['display_price'],
            'discount1':        p.discount1,
            'discount1_code':   p.discount1_code,
            'discount1_amount': calc['discount1_amount'],
            'discount2':        p.discount2,
            'discount2_code':   p.discount2_code,
            'discount2_amount': calc['discount2_amount'],
            'gst_amount':       calc['gst_amount'],
            'final_payable':    calc['final_payable'],
            'badge_text':       badge_text,
            'is_popular':       p.is_popular,
            'daily_text':       p.daily_text,
        })

    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')
        if not plan_id:
            messages.error(request, "Please select a plan.")
            return redirect('upgrade_subscription')

        plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)

        calc         = calculate_plan(plan)
        final_rupees = calc['final_payable']
        amount_paise = final_rupees * 100

        client = get_razorpay_client()
        rz_order = client.order.create({
            'amount':   amount_paise,
            'currency': 'INR',
            'receipt':  f"vcs_sub_{profile.id}_{plan.id}",
            'notes': {
                'candidate_id': profile.id,
                'plan_id':      plan.id,
                'plan_months':  plan.months,
                'plan_days':    plan.days,
            }
        })

        return render(request, 'upgrade_plan.html', {
            'profile':            profile,
            'features':           features,
            'plans':              processed_plans,
            'plans_json':         json.dumps(processed_plans),
            'ui_settings':        get_ui() if 'get_ui' in globals() else None,
            'show_payment_modal': True,
            'amount_paise':       amount_paise, 
            'plan':               plan,
            'calc':               calc,
            'final_rupees':       final_rupees,
            'razorpay_key_id':    settings.RAZORPAY_KEY_ID,
            'rz_order':           rz_order,
        })

    return render(request, 'upgrade_plan.html', {
        'profile':     profile,
        'features':    features,
        'plans':       processed_plans,
        'plans_json':  json.dumps(processed_plans),
        'ui_settings': get_ui() if 'get_ui' in globals() else None,
    })


# ── PAYMENT SUCCESS CALLBACK ───────────────────────────────────────────────
@csrf_exempt
def payment_success(request):
    if request.method != 'POST':
        return redirect('upgrade_subscription')

    razorpay_order_id   = request.POST.get('razorpay_order_id')
    razorpay_payment_id = request.POST.get('razorpay_payment_id')
    razorpay_signature  = request.POST.get('razorpay_signature')

    # 1. Verify Razorpay Signature
    key_secret = settings.RAZORPAY_KEY_SECRET.encode()
    msg        = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    generated  = hmac.new(key_secret, msg, hashlib.sha256).hexdigest()

    if generated == razorpay_signature:
        # 2. Fetch Order Details from Razorpay Notes
        client = get_razorpay_client()
        try:
            rz_order_details = client.order.fetch(razorpay_order_id)
            notes = rz_order_details.get('notes', {})
            candidate_id = notes.get('candidate_id')
            plan_id      = notes.get('plan_id')
            amount_paise = rz_order_details.get('amount')
            
            profile = get_object_or_404(CandidateProfile, id=candidate_id)
            plan    = get_object_or_404(SubscriptionPlan, id=plan_id)

        except Exception as e:
            return render(request, 'payment_result.html', {
                'success':     False,
                'error_msg':   "Could not verify order data with payment gateway.",
                'ui_settings': get_ui(),
            })

        # 3. Create the PaymentOrder record (Finalizes the audit trail)
        payment_order, created = PaymentOrder.objects.get_or_create(
            razorpay_order_id=razorpay_order_id,
            defaults={
                'candidate': profile,
                'plan': plan,
                'amount_paise': amount_paise,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
                'status': PaymentOrder.Status.PAID,
                'paid_at': timezone.now()
            }
        )

        # 4. Handle Plan Expiry Logic (Requirement 1 & Daily Plan support)
        # Check if it's a day-based plan or a month-based plan
        if plan.days > 0:
            days_to_add = plan.days
        else:
            days_to_add = 30 * plan.months

        # Requirement 2: Expiry Stacking
        # If user is already Pro, add time to their existing expiry date
        current_expiry = profile.pro_expiry_date
        if profile.subscription_type == 'Pro' and current_expiry and current_expiry > timezone.now():
            new_expiry = current_expiry + timedelta(days=days_to_add)
        else:
            new_expiry = timezone.now() + timedelta(days=days_to_add)

        # 5. Update Profile
        profile.subscription_type = 'Pro'
        profile.pro_expiry_date   = new_expiry
        profile.save()

        # 6. Send Success Email
        subject = "Welcome to Pro! Your Subscription is Active"
        message = f"""Hi {profile.full_name},

Thank you for upgrading! Your payment of ₹{amount_paise / 100} was successful.

Plan: {plan}
Expiry Date: {new_expiry.strftime('%B %d, %Y')}

Your premium features are now unlocked.

Best regards,
The {get_ui().site_name if get_ui() else 'VCS'} Team
"""
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [profile.user.email],
            fail_silently=True,
        )

        return render(request, 'payment_result.html', {
            'success':        True,
            'payment_order':  payment_order,
            'ui_settings':    get_ui(),
        })
    else:
        # Invalid signature
        return render(request, 'payment_result.html', {
            'success':     False,
            'error_msg':   "Payment verification failed.",
            'ui_settings': get_ui(),
        })

# ── PAYMENT FAILED CALLBACK ────────────────────────────────────────────────
def payment_failed(request):
    return render(request, 'payment_result.html', {
        'success':     False,
        'ui_settings': get_ui(),
    })


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
    active_offer = SubscriptionOffer.objects.filter(is_active=True).first()
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')

    profile, _ = CandidateProfile.objects.get_or_create(
        user=request.user,
        defaults={'full_name': request.user.username}
    )

    all_apps = JobApplication.objects.filter(candidate=profile)
    stats = {
        'total':       all_apps.count(),
        'shortlisted': all_apps.filter(status='Shortlisted').count(),
        'pending':     all_apps.filter(status__in=['Applied', 'Reviewing']).count(),
        'rejected':    all_apps.filter(status='Rejected').count(),
        'interview':   all_apps.filter(status='Interview').count(),
        'offered':     all_apps.filter(status='Offered').count(),
    }

    recent_apps = all_apps.select_related('job').order_by('-applied_at')[:5]
    recommended = get_recommendations(profile, limit=6)
    recommendations_with_gap = []
    
    candidate_skills_norm = set(
        s.lower().replace(" ", "").strip() 
        for s in profile.skills.values_list('name', flat=True)
    )

    for job, score in recommended:
        job_skills_raw = [s.strip() for s in (job.skills_required or '').split(',') if s.strip()]
        
        matching = []
        missing = []
        
        for skill in job_skills_raw:
            skill_norm = skill.lower().replace(" ", "")
            
            if skill_norm in candidate_skills_norm:
                matching.append(skill) 
            else:
                missing.append(skill)
        
        match_pct = int(score * 100)
        recommendations_with_gap.append({
            'job':      job,
            'score':    score,
            'match':    match_pct,
            'matching': matching[:4],
            'missing':  missing[:3],
        })

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
        'active_offer':  active_offer,
    })


@login_required(login_url='login')
def candidate_profile(request):
    if request.user.role != User.Role.CANDIDATE:
        return redirect('login')
    
    profile, _ = CandidateProfile.objects.get_or_create(
        user=request.user,
        defaults={'full_name': request.user.username}
    )

    days_left = None
    if profile.subscription_type == 'Pro' and profile.pro_expiry_date:
        now = timezone.now()
        if profile.pro_expiry_date > now:
            delta = profile.pro_expiry_date - now
            days_left = delta.days
        else:
            days_left = 0

    return render(request, 'candidate_profile.html', {
        'profile': profile,
        'days_left': days_left
    })


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
        user = request.user
        if getattr(user, 'role', '') == 'candidate':
            profile = user.candidate_profile
            redirect_url_name = 'candidate_profile'
        elif getattr(user, 'role', '') == 'trainee':
            profile = user.trainee_profile
            redirect_url_name = 'trainee_profile'
        else:
            return redirect('dashboard')

        if request.POST.get('unmark') == '1':
            profile.is_fresher = False
            messages.success(request, "Removed fresher status.")
        else:
            profile.is_fresher = True
            messages.success(request, "Marked as fresher. Recruiters will now see you are open to entry-level roles.")
            
        profile.save()
        url = reverse(redirect_url_name) + '#employment'
        return redirect(url)
        
    return redirect('dashboard')


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
def trainee_profile(request):
    if getattr(request.user, 'role', '') != 'trainee':
        return redirect('dashboard')
    
    profile = request.user.trainee_profile
    has_employment = profile.employments.exists() or profile.is_fresher
    return render(request, 'trainee/trainee_profile.html', {
        'profile': profile,
        'has_employment': has_employment,
        'ui_settings': get_ui() if 'get_ui' in globals() else None,
    })


@login_required(login_url='login')
def update_trainee_profile(request):
    """A unified view to handle all trainee profile updates."""
    if request.method == 'POST' and getattr(request.user, 'role', '') == 'trainee':
        profile = request.user.trainee_profile
        action = request.POST.get('action')

        if action == 'photo':
            if 'profile_photo' in request.FILES:
                profile.profile_photo = request.FILES['profile_photo']
                
        elif action == 'resume':
            if 'resume' in request.FILES:
                profile.resume = request.FILES['resume']
                
        elif action == 'headline':
            profile.resume_headline = request.POST.get('resume_headline')
            
        elif action == 'summary':
            profile.profile_summary = request.POST.get('profile_summary')
            
        elif action == 'personal':
            profile.gender = request.POST.get('gender')
            profile.marital_status = request.POST.get('marital_status')
            profile.date_of_birth = request.POST.get('date_of_birth') or None
            profile.phone_number = request.POST.get('phone_number')
            profile.languages_known = request.POST.get('languages_known')
            
        elif action == 'add_skill':
            skill_names = request.POST.get('skill_name', '').split(',')
            for name in skill_names:
                name = name.strip()
                if name:
                    skill_obj, _ = Skill.objects.get_or_create(name=name)
                    profile.skills.add(skill_obj)
                    
        elif action == 'remove_skill':
            skill_id = request.POST.get('skill_id')
            if skill_id:
                profile.skills.remove(skill_id)

        profile.save()
        messages.success(request, "Profile updated successfully!")
    return redirect('trainee_profile')


@login_required(login_url='login')
def trainee_dashboard(request):
    if getattr(request.user, 'role', '') != 'trainee':
        return redirect('dashboard')
        
    profile = request.user.trainee_profile
    apps = JobApplication.objects.filter(trainee=profile) 
   
    stats = {
        'total': apps.count(),
        'shortlisted': apps.filter(status='Shortlisted').count(),
        'interview': apps.filter(status='Interview').count(),
        'pending': apps.filter(status='Pending').count(),
        'offered': apps.filter(status='Offered').count(),
        'rejected': apps.filter(status__in=['Rejected', 'Withdrawn']).count(),
    }
    
    recent_apps = apps.order_by('-applied_at')[:5]
    recommended = []
    raw_recs = get_recommendations(profile, limit=4) 
    
    if raw_recs:
        if hasattr(profile.skills, 'values_list'):
            user_skills_normalized = set(s.lower().replace(" ", "") for s in profile.skills.values_list('name', flat=True))
        else:
            # For comma-separated strings
            user_skills_normalized = set(s.lower().replace(" ", "") for s in (profile.skills or "").split(',') if s.strip())

        for job, score in raw_recs:
            raw_job_skills = [s.strip() for s in (job.skills_required or '').split(',') if s.strip()]
            
            matching = []
            missing = []
            
            for skill in raw_job_skills:
                # Normalize the job skill for the check (lowercase + no spaces)
                normalized_job_skill = skill.lower().replace(" ", "")
                
                if normalized_job_skill in user_skills_normalized:
                    matching.append(skill) # Keeps original "REST API" for display
                else:
                    missing.append(skill)
            
            recommended.append({
                'job': job,
                'match': round(score * 100),
                'matching': matching[:3],
                'missing': missing[:3]
            })

    return render(request, 'trainee/trainee_dashboard.html', {
        'profile': profile,
        'stats': stats,
        'recent_apps': recent_apps,
        'recommended': recommended,
    })


@login_required(login_url='login')
def company_dashboard(request):
    if request.user.role != User.Role.COMPANY:
        return redirect('login')
    
    profile = request.user.company_profile
    my_jobs = Job.objects.filter(company_profile=profile).order_by('-posted_at')
    applications = JobApplication.objects.filter(job__company_profile=profile).select_related('job', 'candidate', 'candidate__user').order_by('-applied_at')

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
            company_profile=profile,
            company=profile.company_name,
            title=request.POST.get('title', ''),
            category=category,
            location=request.POST.get('location', ''),

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
    if request.user.role != User.Role.COMPANY:
        return redirect('login')
        
    job = get_object_or_404(Job, id=job_id, company_profile=request.user.company_profile)
    
    if request.method == 'POST':
        cat_id = request.POST.get('category')
        if cat_id:
            job.category = JobCategory.objects.filter(id=cat_id).first()
            
        job.title = request.POST.get('title', job.title)
        job.location = request.POST.get('location', job.location)
        job.job_type = request.POST.get('job_type', job.job_type)
        job.work_mode = request.POST.get('work_mode', job.work_mode)
        job.experience = request.POST.get('experience', job.experience)
        job.skills_required = request.POST.get('skills_required', job.skills_required)
        
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
        job.description = request.POST.get('description', job.description)
        job.responsibilities = request.POST.get('responsibilities', '')
        job.requirements = request.POST.get('requirements', '')
        job.benefits = request.POST.get('benefits', '')
        job.hr_name = request.POST.get('hr_name', '')
        job.hr_email = request.POST.get('hr_email', '')
        job.hr_phone = request.POST.get('hr_phone', '')

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
        app = get_object_or_404(JobApplication, id=app_id, job__company_profile=request.user.company_profile)
        app.status = status
        app.save()
        messages.success(request, f"Applicant status updated to {status}.")
    return redirect('company_dashboard')


def job_list(request):
    jobs = Job.objects.filter(is_active=True).select_related('category')
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

    # ── Applied job ids & Recommendations ──────────────────────────────────
    applied_ids   = []
    recommended_ids_ordered = []
    profile       = None

    if request.user.is_authenticated:
        # 1. Dynamically fetch the correct profile based on the user's role
        if getattr(request.user, 'role', '') == 'candidate' and hasattr(request.user, 'candidate_profile'):
            profile = request.user.candidate_profile
        elif getattr(request.user, 'role', '') == 'trainee' and hasattr(request.user, 'trainee_profile'):
            profile = request.user.trainee_profile

        if profile:
            applied_ids = list(
                JobApplication.objects.filter(
                    candidate__user=request.user
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

    # ── 1. HANDLE SILENT AJAX REQUEST TO SEND EMAIL ──
    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Check if this is the "Send HR Email" action and the user is actually logged in
        if request.POST.get('action') == 'send_hr_email' and request.user.is_authenticated:
            subject = f"HR Contact Details: {job.title} at {job.company}"
            
            # Construct the email body
            msg = f"Hello {request.user.first_name or request.user.username},\n\n"
            msg += f"Here are the HR contact details you requested for the {job.title} role:\n\n"
            msg += f"Company: {job.company}\n"
            if job.hr_name:  msg += f"HR Name: {job.hr_name}\n"
            if job.hr_phone: msg += f"Phone: {job.hr_phone}\n"
            if job.hr_email: msg += f"Email: {job.hr_email}\n\n"
            msg += "Best of luck with your job application!\n\nThe Team"
            
            try:
                send_mail(
                    subject,
                    msg,
                    settings.DEFAULT_FROM_EMAIL,  # Make sure this is set in settings.py
                    [request.user.email],
                    fail_silently=True,
                )
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
                
        return JsonResponse({'success': False, 'error': 'Unauthorized'})

    # ── 2. STANDARD GET REQUEST LOGIC (Your existing code) ──
    similar = Job.objects.filter(
        is_active=True, category=job.category
    ).exclude(id=job.id)[:4]

    already_applied = False
    application     = None
    profile         = None 
    
    if request.user.is_authenticated:
        role = getattr(request.user, 'role', '')
        
        if role == 'candidate':
            application = JobApplication.objects.filter(job=job, candidate__user=request.user).first()
            if hasattr(request.user, 'candidate_profile'):
                profile = request.user.candidate_profile
                
        elif role == 'trainee':
            application = JobApplication.objects.filter(job=job, trainee__user=request.user).first()
            if hasattr(request.user, 'trainee_profile'):
                profile = request.user.trainee_profile
                
        already_applied = application is not None

    skills_list = [
        s.strip() for s in (job.skills_required or '').split(',') if s.strip()
    ]

    return render(request, 'jobs/job_detail.html', {
        'job':             job,
        'similar':         similar,
        'already_applied': already_applied,
        'application':     application,
        'profile':         profile, 
        'skills_list':     skills_list,
        'responsibilities': [r.strip() for r in (job.responsibilities or '').split('\n') if r.strip()],
        'requirements':    [r.strip() for r in (job.requirements or '').split('\n') if r.strip()],
        'benefits':        [r.strip() for r in (job.benefits or '').split('\n') if r.strip()],
        'ui_settings':     get_ui() if 'get_ui' in globals() else None,
        'today': timezone.now().date(),
    })


@login_required(login_url='login')
def apply_job(request, slug):
    if request.user.role not in ['candidate', 'trainee']:
        messages.error(request, "Only candidates and trainees can apply for jobs.")
        return redirect('job_detail', slug=slug)

    job = Job.objects.get(slug=slug, is_active=True)
    
    if job.deadline and job.deadline < timezone.now().date():
        messages.error(request, "Sorry, applications for this job are now closed.")
        return redirect('job_detail', slug=slug)
   
    profile = request.user.candidate_profile if request.user.role == 'candidate' else request.user.trainee_profile

    if JobApplication.objects.filter(job=job, candidate__user=request.user).exists():
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
        
        if request.user.role == 'candidate':
            JobApplication.objects.create(
                job=job,
                candidate=profile,  
                cover_letter=cover_letter or None,
            )
        elif request.user.role == 'trainee':
            JobApplication.objects.create(
                job=job,
                trainee=profile,    
                cover_letter=cover_letter or None,
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
    role = getattr(request.user, 'role', '')
    if role not in ['candidate', 'trainee']:
        return redirect('dashboard')

    if role == 'candidate':
        applications = JobApplication.objects.filter(
            candidate__user=request.user
        ).select_related('job').order_by('-applied_at')
    elif role == 'trainee':
        applications = JobApplication.objects.filter(
            trainee__user=request.user
        ).select_related('job').order_by('-applied_at')
    else:
        applications = []

    return render(request, 'jobs/my_applications.html', {
        'applications': applications,
        'ui_settings':  get_ui() if 'get_ui' in globals() else None,
    })



def is_premium_user(user):
    """Check if user can access premium content."""
    if not user.is_authenticated:
        return False
    if user.role == User.Role.TRAINEE:
        return True
    if user.role == User.Role.CANDIDATE:
        if hasattr(user, 'candidate_profile'):
            return user.candidate_profile.subscription_type == 'Pro'
    return False


# ── SERVICES HUB ──────────────────────────────────────────────────────────
@login_required(login_url='login')
def services(request):
    premium = is_premium_user(request.user)
    recent_feeds = Feed.objects.filter(is_published=True).order_by('-published_at')[:10]
    active_offer = SubscriptionOffer.objects.filter(is_active=True).first()
    
    return render(request, 'services/services.html', {
        'is_premium':   premium,
        'recent_feeds': recent_feeds,
        'ui_settings':  get_ui(),
        'active_offer': active_offer,
    })


# ── FEEDS ─────────────────────────────────────────────────────────────────
@login_required(login_url='login')
def feed_list(request):
    if not is_premium_user(request.user):
        return redirect('services')

    feeds = Feed.objects.filter(is_published=True)
    feed_type = request.GET.get('type', '').strip()
    q         = request.GET.get('q', '').strip()

    if feed_type:
        feeds = feeds.filter(feed_type=feed_type)
    if q:
        feeds = feeds.filter(
            Q(title__icontains=q) | Q(tags__icontains=q) | Q(excerpt__icontains=q)
        )

    from django.core.paginator import Paginator
    page_obj = Paginator(feeds, 9).get_page(request.GET.get('page', 1))

    return render(request, 'services/feed_list.html', {
        'page_obj':    page_obj,
        'feed_types':  Feed.FeedType.choices,
        'active_type': feed_type,
        'q':           q,
        'ui_settings': get_ui(),
    })


@login_required(login_url='login')
def feed_detail(request, slug):
    if not is_premium_user(request.user):
        return redirect('services')

    feed = Feed.objects.get(slug=slug, is_published=True)
    feed.views += 1
    feed.save(update_fields=['views'])

    related = Feed.objects.filter(
        is_published=True, feed_type=feed.feed_type
    ).exclude(id=feed.id)[:3]

    return render(request, 'services/feed_detail.html', {
        'feed':        feed,
        'related':     related,
        'tags':        feed.get_tags_list(),
        'ui_settings': get_ui(),
    })
