# vcs/otp_utils.py
import random
from django.core.mail import send_mail
from django.conf import settings


def generate_otp():
    return str(random.randint(100000, 999999))


def send_otp_email(email, otp):
    try:
        send_mail(
            subject='Your Verification Code — Vetri Consultancy Services',
            message=f'''Hello,

Your verification code is: {otp}

This code is valid for 10 minutes. Do not share it with anyone.

Regards,
Vetri Consultancy Services''',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        return True, f"Verification code sent to {email}"
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False, f"Failed to send email. Please check your email address."