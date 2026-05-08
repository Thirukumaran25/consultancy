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
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import send_mail
import json, uuid ,openpyxl ,hmac , hashlib ,razorpay ,random
from .models import ChatSession
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.core.cache import cache
from django.contrib.auth import get_user_model



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

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
        return render(request, 'payment_result.html', {
            'success':     False,
            'error_msg':   "Missing payment verification data.",
            'ui_settings': get_ui(),
        })

    key_secret = settings.RAZORPAY_KEY_SECRET.encode('utf-8')
    msg        = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
    generated  = hmac.new(key_secret, msg, hashlib.sha256).hexdigest()

    if hmac.compare_digest(generated, razorpay_signature):
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

        if plan.days > 0:
            days_to_add = plan.days
        else:
            days_to_add = 30 * plan.months

        current_expiry = profile.pro_expiry_date
        if profile.subscription_type == 'Pro' and current_expiry and current_expiry > timezone.now():
            new_expiry = current_expiry + timedelta(days=days_to_add)
        else:
            new_expiry = timezone.now() + timedelta(days=days_to_add)

        profile.subscription_type = 'Pro'
        profile.pro_expiry_date   = new_expiry
        profile.save()
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
        return render(request, 'payment_result.html', {
            'success':     False,
            'error_msg':   "Payment verification failed. Invalid signature.",
            'ui_settings': get_ui(),
        })


# ── PAYMENT FAILED CALLBACK ────────────────────────────────────────────────
def payment_failed(request):
    return render(request, 'payment_result.html', {
        'success':     False,
        'ui_settings': get_ui(),
    })


# Add this helper anywhere in views.py
def _check_and_expire_subscription(user):
    """Silently expire Pro if past expiry date — called at login."""
    if user.role != User.Role.CANDIDATE:
        return
    if not hasattr(user, 'candidate_profile'):
        return
    profile = user.candidate_profile
    if (
        profile.subscription_type == 'Pro'
        and profile.pro_expiry_date
        and profile.pro_expiry_date <= timezone.now()
    ):
        profile.subscription_type = 'Free'
        profile.pro_expiry_date   = None
        profile.save(update_fields=['subscription_type', 'pro_expiry_date'])

        send_mail(
            subject="Your Pro Plan Has Expired",
            message=f"Hi {profile.full_name},\n\nYour Pro subscription has expired. "
                    f"Upgrade again to regain access to premium features.\n\nBest,\nVCS Team",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=True,
        )

    
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
        _check_and_expire_subscription(user) 
        return redirect_by_role(user)

    return render(request, 'login.html', {
        'active_tab': 'candidate',
        'ui_settings': get_ui(),
    })


def send_reset_otp(request):
    """Generates a 6-digit OTP, saves it to the cache for 10 mins, and emails it."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            
            if not email:
                return JsonResponse({'error': 'Email is required.'}, status=400)
                
            if not User.objects.filter(email=email).exists():
                return JsonResponse({'error': 'No account found with this email address.'}, status=404)
            
            otp = str(random.randint(100000, 999999))
            cache_key = f'pwd_reset_otp_{email}'
            cache.set(cache_key, otp, timeout=600)
            subject = 'Your Password Reset Code'
            message = (
                f"Hello,\n\n"
                f"We received a request to reset your password.\n"
                f"Your 6-digit verification code is: {otp}\n\n"
                f"This code will expire in 10 minutes. If you did not request this, please ignore this email.\n\n"
                f"Regards,\n"
                f"The Team at Vetri Consultancy Services"
            )
            
            send_mail(
                subject,
                message,
                settings.EMAIL_HOST_USER,
                [email],
                fail_silently=False,
            )
            
            return JsonResponse({'success': True, 'message': 'OTP sent successfully.'})
            
        except Exception as e:
            print(f"CRITICAL OTP ERROR: {str(e)}") 
            return JsonResponse({'error': f'Failed to send email. Please try again later.'}, status=500)
            
    return JsonResponse({'error': 'Invalid request method.'}, status=405)


def verify_reset_otp(request):
    """Checks if the submitted OTP matches the cached OTP."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            otp = data.get('otp')
            
            # Retrieve the OTP from the cache
            cached_otp = cache.get(f'pwd_reset_otp_{email}')
            
            if not cached_otp:
                return JsonResponse({'error': 'OTP has expired. Please request a new one.'}, status=400)
                
            if cached_otp != otp:
                return JsonResponse({'error': 'Invalid OTP. Please try again.'}, status=400)
                
            return JsonResponse({'success': True, 'message': 'OTP verified successfully.'})
            
        except Exception as e:
            return JsonResponse({'error': 'An error occurred during verification.'}, status=500)
            
    return JsonResponse({'error': 'Invalid request method.'}, status=405)


def reset_password(request):
    """Re-verifies the OTP for security, then changes the user's password."""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            email = data.get('email')
            otp = data.get('otp')
            new_password = data.get('new_password')
            
            # Strictly verify the OTP one last time before allowing the password change
            cached_otp = cache.get(f'pwd_reset_otp_{email}')
            if not cached_otp or cached_otp != otp:
                return JsonResponse({'error': 'Session expired or invalid OTP.'}, status=400)
                
            if len(new_password) < 8:
                return JsonResponse({'error': 'Password must be at least 8 characters long.'}, status=400)
                
            # Update the user's password
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            
            # Delete the OTP from the cache so it cannot be reused
            cache.delete(f'pwd_reset_otp_{email}')
            
            return JsonResponse({'success': True, 'message': 'Password reset successful.'})
            
        except User.DoesNotExist:
            return JsonResponse({'error': 'User not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'error': 'An error occurred while resetting the password.'}, status=500)
            
    return JsonResponse({'error': 'Invalid request method.'}, status=405)


# ── LOGOUT ─────────────────────────────────────────────────────────────────
def logout_view(request):
    logout(request)
    return redirect('login')


# ── SEND OTP (email only) ──────────────────────────────────────────────────
def send_registration_otp(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request.'})

    now      = timezone.now()
    otp_log  = request.session.get('otp_send_log', [])
    ten_mins = now - timedelta(minutes=10)

    # Keep only timestamps within last 10 minutes
    otp_log  = [t for t in otp_log if timezone.datetime.fromisoformat(t) > ten_mins]

    if len(otp_log) >= 3:
        return JsonResponse({
            'success': False,
            'error': 'Too many attempts. Please wait 10 minutes before requesting a new code.'
        })

    otp_log.append(now.isoformat())
    request.session['otp_send_log'] = otp_log
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
        elif any(char.isdigit() for char in full_name):
            errors['full_name'] = "Full name cannot contain numbers."
        if not username:
            errors['username'] = "Username is required."
        elif ' ' in username:
            errors['username'] = "No spaces allowed."
        if not email:
            errors['email'] = "Email is required."
        if not phone:
            errors['phone_number'] = "Mobile number is required."
        elif not phone.isdigit():
            errors['phone_number'] = "Mobile number must contain only numbers."
        elif len(phone) < 7 or len(phone) > 15:
            errors['phone_number'] = "Mobile number must be between 7 and 15 digits."
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
        user=request.user, defaults={'full_name': request.user.username}
    )

    days_left = None
    if profile.subscription_type == 'Pro' and profile.pro_expiry_date:
        now = timezone.now()
        if profile.pro_expiry_date > now:
            delta = profile.pro_expiry_date - now
            days_left = delta.days
        else:
            days_left = 0

    has_employment = profile.employments.exists() or profile.is_fresher
    return render(request, 'candidate_profile.html', {
        'profile': profile,
        'has_employment': has_employment,
        'days_left': days_left,
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
        try:
            profile = request.user.candidate_profile
            profile.resume_headline = request.POST.get('resume_headline', '').strip() or None
            profile.save(update_fields=['resume_headline'])
            messages.success(request, "Headline updated.")
        except Exception as e:
            messages.error(request, f"Could not update headline: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_summary(request):
    if request.method == 'POST':
        try:
            profile = request.user.candidate_profile
            profile.profile_summary = request.POST.get('profile_summary', '').strip() or None
            profile.save(update_fields=['profile_summary'])
            messages.success(request, "Summary updated.")
        except Exception as e:
            messages.error(request, f"Could not update summary: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_personal(request):
    if request.method == 'POST':
        try:
            p = request.user.candidate_profile
            p.gender          = request.POST.get('gender') or None
            p.marital_status  = request.POST.get('marital_status') or None
            p.phone_number    = request.POST.get('phone_number', '').strip() or None
            p.languages_known = request.POST.get('languages_known', '').strip() or None

            dob = request.POST.get('date_of_birth', '').strip()
            p.date_of_birth = dob if dob else None

            p.save(update_fields=[
                'gender', 'marital_status', 'phone_number',
                'languages_known', 'date_of_birth'
            ])
            messages.success(request, "Personal details updated.")
        except Exception as e:
            messages.error(request, f"Could not update personal details: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_resume(request):
    if request.method == 'POST':
        try:
            profile = request.user.candidate_profile
            f = request.FILES.get('resume')
            if not f:
                messages.error(request, "No file selected.")
                return redirect('candidate_profile')

            allowed = ['pdf', 'doc', 'docx']
            ext = f.name.rsplit('.', 1)[-1].lower()
            if ext not in allowed:
                messages.error(request, "Only PDF, DOC, DOCX files are allowed.")
                return redirect('candidate_profile')

            if f.size > 5 * 1024 * 1024:  # 5 MB
                messages.error(request, "File too large. Max 5 MB.")
                return redirect('candidate_profile')

            profile.resume = f
            profile.save(update_fields=['resume'])
            messages.success(request, "Resume updated.")
        except Exception as e:
            messages.error(request, f"Could not upload resume: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def add_skill(request):
    if request.method == 'POST':
        raw = request.POST.get('skill_name', '').strip()
        if not raw:
            messages.error(request, "Please enter at least one skill.")
            return redirect('candidate_profile')

        skill_names = [s.strip() for s in raw.split(',') if s.strip()]
        added = 0
        for name in skill_names:
            # Step 1: Try exact case-insensitive match first (find existing)
            existing = Skill.objects.filter(name__iexact=name).first()
            if existing:
                request.user.candidate_profile.skills.add(existing)
            else:
                # Step 2: Create with the user's original casing
                skill = Skill.objects.create(name=name)
                request.user.candidate_profile.skills.add(skill)
            added += 1

        messages.success(request, f"{added} skill{'s' if added > 1 else ''} added.")
    return redirect('candidate_profile')


# ── REMOVE SKILL (candidate) ───────────────────────────────────────────────
@login_required(login_url='login')
def remove_skill(request, skill_id):
    if request.method == 'POST':
        try:
            skill = Skill.objects.get(id=skill_id)
            request.user.candidate_profile.skills.remove(skill)
            messages.success(request, f"'{skill.name}' removed.")
        except Skill.DoesNotExist:
            messages.error(request, "Skill not found.")
    return redirect('candidate_profile')


@login_required(login_url='login')
def update_profile_photo(request):
    if request.method == 'POST':
        try:
            profile = request.user.candidate_profile
            f = request.FILES.get('profile_photo')
            if not f:
                messages.error(request, "No file selected.")
                return redirect('candidate_profile')

            allowed = ['jpg', 'jpeg', 'png', 'webp']
            ext = f.name.rsplit('.', 1)[-1].lower()
            if ext not in allowed:
                messages.error(request, "Only JPG, PNG, WEBP images are allowed.")
                return redirect('candidate_profile')

            if f.size > 2 * 1024 * 1024:  # 2 MB
                messages.error(request, "Image too large. Max 2 MB.")
                return redirect('candidate_profile')

            profile.profile_photo = f
            profile.save(update_fields=['profile_photo'])
            messages.success(request, "Profile photo updated.")
        except Exception as e:
            messages.error(request, f"Could not update photo: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def save_employment(request):
    if request.method == 'POST':
        try:
            profile    = request.user.candidate_profile
            emp_id     = request.POST.get('emp_id', '').strip()
            is_current = request.POST.get('is_current') == 'on'

            designation  = request.POST.get('designation', '').strip()
            company_name = request.POST.get('company_name', '').strip()
            start_date   = request.POST.get('start_date', '').strip()

            if not designation or not company_name or not start_date:
                messages.error(request, "Designation, Company, and Start Date are required.")
                return redirect('candidate_profile')

            data = {
                'designation':  designation,
                'company_name': company_name,
                'start_date':   start_date,
                'end_date':     None if is_current else (request.POST.get('end_date', '').strip() or None),
                'is_current':   is_current,
                'location':     request.POST.get('location', '').strip() or None,
                'description':  request.POST.get('description', '').strip() or None,
            }

            if emp_id:
                updated = Employment.objects.filter(id=emp_id, candidate=profile).update(**data)
                if updated:
                    messages.success(request, "Employment updated.")
                else:
                    messages.error(request, "Employment record not found.")
            else:
                Employment.objects.create(candidate=profile, **data)
                messages.success(request, "Employment added.")

        except Exception as e:
            messages.error(request, f"Could not save employment: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_employment(request, emp_id):
    if request.method == 'POST':
        try:
            deleted, _ = Employment.objects.filter(
                id=emp_id, candidate=request.user.candidate_profile
            ).delete()
            if deleted:
                messages.success(request, "Employment deleted.")
            else:
                messages.error(request, "Record not found.")
        except Exception as e:
            messages.error(request, f"Could not delete employment: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def save_education(request):
    if request.method == 'POST':
        try:
            profile    = request.user.candidate_profile
            edu_id     = request.POST.get('edu_id', '').strip()

            education_level = request.POST.get('education_level', '').strip()
            university      = request.POST.get('university', '').strip()
            start_year      = request.POST.get('start_year', '').strip()
            end_year        = request.POST.get('end_year', '').strip()

            if not education_level or not university or not start_year or not end_year:
                messages.error(request, "Education level, University, and Years are required.")
                return redirect('candidate_profile')

            data = {
                'education_level': education_level,
                'course':          request.POST.get('course', '').strip() or None,
                'university':      university,
                'start_year':      int(start_year),
                'end_year':        int(end_year),
                'course_type':     request.POST.get('course_type', 'Full Time'),
            }

            if edu_id:
                updated = Education.objects.filter(id=edu_id, candidate=profile).update(**data)
                if updated:
                    messages.success(request, "Education updated.")
                else:
                    messages.error(request, "Education record not found.")
            else:
                Education.objects.create(candidate=profile, **data)
                messages.success(request, "Education added.")

        except ValueError:
            messages.error(request, "Invalid year format.")
        except Exception as e:
            messages.error(request, f"Could not save education: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_education(request, edu_id):
    if request.method == 'POST':
        try:
            deleted, _ = Education.objects.filter(
                id=edu_id, candidate=request.user.candidate_profile
            ).delete()
            if deleted:
                messages.success(request, "Education deleted.")
            else:
                messages.error(request, "Record not found.")
        except Exception as e:
            messages.error(request, f"Could not delete education: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def save_project(request):
    if request.method == 'POST':
        try:
            profile    = request.user.candidate_profile
            proj_id    = request.POST.get('proj_id', '').strip()
            is_ongoing = request.POST.get('is_ongoing') == 'on'

            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()

            if not title or not description:
                messages.error(request, "Title and Description are required.")
                return redirect('candidate_profile')

            project_url = request.POST.get('project_url', '').strip()
            # Basic URL validation
            if project_url and not project_url.startswith(('http://', 'https://')):
                project_url = 'https://' + project_url

            data = {
                'title':       title,
                'project_url': project_url or None,
                'start_date':  request.POST.get('start_date', '').strip() or None,
                'end_date':    None if is_ongoing else (request.POST.get('end_date', '').strip() or None),
                'is_ongoing':  is_ongoing,
                'description': description,
            }

            if proj_id:
                updated = Project.objects.filter(id=proj_id, candidate=profile).update(**data)
                if updated:
                    messages.success(request, "Project updated.")
                else:
                    messages.error(request, "Project not found.")
            else:
                Project.objects.create(candidate=profile, **data)
                messages.success(request, "Project added.")

        except Exception as e:
            messages.error(request, f"Could not save project: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def delete_project(request, proj_id):
    if request.method == 'POST':
        try:
            deleted, _ = Project.objects.filter(
                id=proj_id, candidate=request.user.candidate_profile
            ).delete()
            if deleted:
                messages.success(request, "Project deleted.")
            else:
                messages.error(request, "Record not found.")
        except Exception as e:
            messages.error(request, f"Could not delete project: {e}")
    return redirect('candidate_profile')


@login_required(login_url='login')
def mark_fresher(request):
    if request.method == 'POST':
        try:
            user = request.user
            if user.role == 'candidate':
                profile = user.candidate_profile
                redirect_url_name = 'candidate_profile'
            elif user.role == 'trainee':
                profile = user.trainee_profile
                redirect_url_name = 'trainee_profile'
            else:
                messages.error(request, "Action not permitted.")
                return redirect('dashboard_router')

            if request.POST.get('unmark') == '1':
                profile.is_fresher = False
                messages.success(request, "Fresher status removed.")
            else:
                profile.is_fresher = True
                messages.success(request, "Marked as fresher.")

            profile.save(update_fields=['is_fresher'])
            return redirect(reverse(redirect_url_name) + '#employment')

        except Exception as e:
            messages.error(request, f"Could not update fresher status: {e}")
            return redirect('candidate_profile')

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
        if not terms:
            errors['terms'] = "You must accept the terms."

        ALLOWED_DOC_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']
        MAX_DOC_SIZE = 5 * 1024 * 1024 

        def _validate_document(f, field_name, err_dict):
            if not f:
                err_dict[field_name] = f"{field_name.replace('_', ' ').title()} is required."
                return
            ext = f.name.rsplit('.', 1)[-1].lower()
            if ext not in ALLOWED_DOC_EXTENSIONS:
                err_dict[field_name] = "Only PDF, JPG, PNG files are allowed."
            elif f.size > MAX_DOC_SIZE:
                err_dict[field_name] = "File too large. Max 5 MB."

        _validate_document(reg_doc, 'registration_document', errors)
        _validate_document(gst_doc, 'gst_document', errors)

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
        'rejected': apps.filter(status__in=['Rejected']).count(),
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
    
    # Get all records
    my_jobs_list = Job.objects.filter(company_profile=profile).order_by('-posted_at')
    applications_list = JobApplication.objects.filter(job__company_profile=profile).select_related('job', 'candidate', 'candidate__user').order_by('-applied_at')

    # Calculate stats using the full unpaginated querysets
    stats = {
        'jobs_count': my_jobs_list.count(),
        'applicants_count': applications_list.count(),
        'hired_count': applications_list.filter(status='Offered').count() 
    }
    
    # --- Pagination for Jobs (e.g., 5 jobs per page) ---
    job_paginator = Paginator(my_jobs_list, 5) 
    job_page_number = request.GET.get('job_page')
    my_jobs = job_paginator.get_page(job_page_number)
    
    # --- Pagination for Applications (e.g., 10 applications per page) ---
    app_paginator = Paginator(applications_list, 10) 
    app_page_number = request.GET.get('app_page')
    applications = app_paginator.get_page(app_page_number)
    
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
        new_status = request.POST.get('status')
        app = get_object_or_404(JobApplication, id=app_id, job__company_profile=request.user.company_profile)
        
        if new_status and new_status != app.status:
            app.status = new_status
            app.save()

            if app.candidate:
                applicant_email = app.candidate.user.email
                applicant_name  = app.candidate.full_name
            elif app.trainee:
                applicant_email = app.trainee.user.email
                applicant_name  = app.trainee.full_name
            else:
                messages.error(request, "Applicant not found.")
                return redirect('company_dashboard')
                
            company_name = app.job.company_profile.company_name
            job_title = app.job.title
            
            subject = f"Application Update: {job_title} at {company_name}"
            message = (
                f"Dear {applicant_name},\n\n"
                f"There has been an update to your recent job application.\n\n"
                f"Position: {job_title}\n"
                f"Company: {company_name}\n"
                f"New Status: {new_status}\n\n"
                f"Thank you for applying!\n\n"
                f"Best regards,\n"
                f"The Team at VCS"
            )
            
            try:
                send_mail(
                    subject,
                    message,
                    settings.EMAIL_HOST_USER,
                    [applicant_email],
                    fail_silently=False,
                )
                messages.success(request, f"Applicant status updated to '{new_status}' and email sent.")
            except Exception as e:
                messages.warning(request, f"Status updated to '{new_status}', but the email failed to send. Error: {e}")
        else:
            messages.info(request, "Applicant status was already set to that value.")
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


def _can_user_apply(user):
    """Helper to check if a Free candidate has reached their monthly limit."""
    if not user.is_authenticated:
        return False
        
    role = getattr(user, 'role', '')
    if role == 'trainee':
        return True
        
    if role == 'candidate' and hasattr(user, 'candidate_profile'):
        profile = user.candidate_profile
        
        if profile.subscription_type == 'Pro':
            return True
            
        now = timezone.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        app_count = JobApplication.objects.filter(
            candidate=profile,
            applied_at__gte=start_of_month 
        ).count()
        
        return app_count < 5
        
    return False


def job_detail(request, slug):
    job = get_object_or_404(Job, slug=slug, is_active=True)

    if request.method == 'POST' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        if request.POST.get('action') == 'send_hr_email' and request.user.is_authenticated:
            subject = f"HR Contact Details: {job.title} at {job.company}"
            
            msg = f"Hello {request.user.first_name or request.user.username},\n\n"
            msg += f"Here are the HR contact details you requested for the {job.title} role:\n\n"
            msg += f"Company: {job.company}\n"
            if job.hr_name:  msg += f"HR Name: {job.hr_name}\n"
            if job.hr_phone: msg += f"Phone: {job.hr_phone}\n"
            if job.hr_email: msg += f"Email: {job.hr_email}\n\n"
            msg += "Best of luck with your job application!\n\nThe Team"
            
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject,
                    msg,
                    settings.DEFAULT_FROM_EMAIL,  
                    [request.user.email],
                    fail_silently=True,
                )
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
                
        return JsonResponse({'success': False, 'error': 'Unauthorized'})

    similar = Job.objects.filter(
        is_active=True, category=job.category
    ).exclude(id=job.id)[:4]

    already_applied = False
    application     = None
    profile         = None 
    can_apply       = False 
    
    if request.user.is_authenticated:
        role = getattr(request.user, 'role', '')
        can_apply = _can_user_apply(request.user) 
        
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
        'can_apply':       can_apply,
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
        
    if not _can_user_apply(request.user):
        messages.error(request, "You have reached your limit of 5 free applications this month. Please upgrade to Pro to continue applying.")
        return redirect('upgrade_subscription')
   
    profile = request.user.candidate_profile if request.user.role == 'candidate' else request.user.trainee_profile

    if request.user.role == 'candidate':
        already_applied = JobApplication.objects.filter(job=job, candidate=profile).exists()
    else:
        already_applied = JobApplication.objects.filter(job=job, trainee=profile).exists()

    if already_applied:
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
    """Check if user can access premium content — respects expiry date."""
    if not user.is_authenticated:
        return False
    if user.role == User.Role.TRAINEE:
        return True
    if user.role == User.Role.CANDIDATE:
        if hasattr(user, 'candidate_profile'):
            profile = user.candidate_profile
            if profile.subscription_type != 'Pro':
                return False
            if profile.pro_expiry_date and profile.pro_expiry_date <= timezone.now():
                profile.subscription_type = 'Free'
                profile.pro_expiry_date   = None
                profile.save(update_fields=['subscription_type', 'pro_expiry_date'])
                return False
            return True
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



def company_terms_view(request):
    terms = TermsAndConditions.objects.filter(is_active=True, role='company').first()
    
    return render(request, 'company_terms.html', {
        'terms': terms,
        'current_role': 'company'
    })

def candidate_terms_view(request):
    terms = TermsAndConditions.objects.filter(is_active=True, role='candidate').first()
    
    return render(request, 'candidate_terms.html', {
        'terms': terms,
        'current_role': 'candidate'
    })

@login_required(login_url='login')
def export_applications_excel(request):
    # Ensure only companies can access this
    if request.user.role != User.Role.COMPANY:
        return redirect('login')
        
    profile = request.user.company_profile
    
    # Get ALL applications for this company's jobs
    applications = JobApplication.objects.filter(
        job__company_profile=profile
    ).select_related('job', 'candidate', 'candidate__user').order_by('-applied_at')
    
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Job Applications"
    headers = ["Candidate Name", "Email", "Phone", "Applied For", "Status", "Date Applied"]
    sheet.append(headers)
    
    for cell in sheet[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    
    for app in applications:
        sheet.append([
            app.candidate.full_name,
            app.candidate.user.email,
            app.candidate.phone_number,
            app.job.title,
            app.status,
            app.applied_at.strftime('%Y-%m-%d %H:%M:%S')
        ])

    for col in sheet.columns:
        max_length = 0
        column = col[0].column_letter 
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = (max_length + 2)
        sheet.column_dimensions[column].width = adjusted_width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="vcs_applications_export.xlsx"'
    workbook.save(response)
    return response



def _get_session_key(request):
    key = request.session.get('chat_session_key')
    if not key:
        key = f"user_{request.user.id if request.user.is_authenticated else 'anon'}_{uuid.uuid4().hex[:12]}"
        request.session['chat_session_key'] = key
    return key


@login_required
def chatbot_api(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed.'}, status=405)
        
    # Reject non-AJAX requests
    if request.headers.get('x-requested-with') != 'XMLHttpRequest':
        return JsonResponse({'error': 'Bad request (AJAX only).'}, status=400)
        
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON format.'}, status=400)
        
    # Hard cap the query to 1000 chars to prevent memory/processing abuse
    query = data.get('query', '').strip()[:1000]
    
    if not query:
        return JsonResponse({'error': 'Empty question.'}, status=400)
        
    from .rag_engine import chat

    result = chat(query=query, session_key=_get_session_key(request), user=request.user)
    return JsonResponse(result)
    

@login_required
def chatbot_history(request):
    """Loads the previous chat bubbles when the user opens the modal."""
    try:
        session = ChatSession.objects.get(session_key=_get_session_key(request))
        messages = [{'role': m.role, 'content': m.content, 'sources': m.sources} for m in session.messages.order_by('id')]
        return JsonResponse({'messages': messages})
    except ChatSession.DoesNotExist:
        return JsonResponse({'messages': []})

@login_required
def chatbot_clear(request):
    """Wipes the chat session."""
    if request.method == 'POST':
        old_key = request.session.pop('chat_session_key', None)
        if old_key:
            ChatSession.objects.filter(session_key=old_key).delete()
        return JsonResponse({'status': 'cleared'})