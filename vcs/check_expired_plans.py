from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from .models import CandidateProfile

class Command(BaseCommand):
    help = 'Checks for expired Pro subscriptions, downgrades to Free, and sends an email.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        
        # Find all Pro users whose expiry date has passed
        expired_profiles = CandidateProfile.objects.filter(
            subscription_type='Pro',
            pro_expiry_date__lte=now
        )

        count = 0
        for profile in expired_profiles:
            # 1. Downgrade them to Free
            profile.subscription_type = 'Free'
            profile.pro_expiry_date = None
            profile.save()

            # 2. Send the expiration email
            subject = "Your Pro Plan has expired"
            message = f"""Hi {profile.full_name},

Your Pro subscription has expired and your account has been safely switched back to the Free plan. 

You can upgrade again at any time to regain access to premium features!

Best regards,
The Team"""

            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [profile.user.email],
                    fail_silently=True,
                )
            except Exception as e:
                self.stderr.write(f"Failed to send email to {profile.user.email}: {e}")

            count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully downgraded {count} expired accounts.'))