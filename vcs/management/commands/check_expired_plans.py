from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from vcs.models import CandidateProfile


class Command(BaseCommand):
    help = 'Downgrades expired Pro subscriptions to Free and notifies users.'

    def handle(self, *args, **kwargs):
        now     = timezone.now()
        expired = CandidateProfile.objects.filter(
            subscription_type='Pro',
            pro_expiry_date__lte=now
        ).select_related('user')

        count = 0
        for profile in expired:
            # Downgrade
            profile.subscription_type = 'Free'
            profile.pro_expiry_date   = None
            profile.save(update_fields=['subscription_type', 'pro_expiry_date'])

            # Notify
            site_name = settings.SITE_NAME if hasattr(settings, 'SITE_NAME') else 'VCS'
            send_mail(
                subject=f"Your {site_name} Pro Plan Has Expired",
                message=f"""Hi {profile.full_name},

Your Pro subscription has expired and your account has been moved back to the Free plan.

You can renew anytime to regain access to:
  • Career Feeds
  • Interview Experiences
  • Salary & Offer Insights

Upgrade here: {settings.SITE_URL if hasattr(settings, 'SITE_URL') else ''}/upgrade/

Best regards,
The {site_name} Team""",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[profile.user.email],
                fail_silently=True,
            )

            self.stdout.write(
                self.style.SUCCESS(f'  ✓ Downgraded: {profile.full_name} ({profile.user.email})')
            )
            count += 1

        if count == 0:
            self.stdout.write('No expired subscriptions found.')
        else:
            self.stdout.write(self.style.SUCCESS(f'\nTotal downgraded: {count}'))