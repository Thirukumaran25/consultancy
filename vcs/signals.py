# vcs/signals.py
import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import EmailMessage
from django.conf import settings


def _get_target_emails():
    """Returns emails for all active Pro candidates and Trainees."""
    from vcs.models import CandidateProfile, TraineeProfile
    from django.utils import timezone

    pro_emails = list(
        CandidateProfile.objects.filter(
            subscription_type='Pro',
            pro_expiry_date__gt=timezone.now(),  # ← only non-expired Pro users
            user__is_active=True,
        ).values_list('user__email', flat=True)
    )

    trainee_emails = list(
        TraineeProfile.objects.filter(
            is_active=True,
            user__is_active=True,
        ).values_list('user__email', flat=True)
    )

    all_emails = list(set(pro_emails + trainee_emails))
    return [e for e in all_emails if e]


class _EmailThread(threading.Thread):
    def __init__(self, subject, body, bcc_list):
        super().__init__(daemon=True)
        self.subject  = subject
        self.body     = body
        self.bcc_list = bcc_list

    def run(self):
        if not self.bcc_list:
            return
        email = EmailMessage(
            subject=self.subject,
            body=self.body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.DEFAULT_FROM_EMAIL],
            bcc=self.bcc_list,
        )
        email.send(fail_silently=True)


@receiver(post_save, sender='vcs.Job')
def notify_new_job(sender, instance, created, **kwargs):
    if not created or not instance.is_active:
        return

    emails = _get_target_emails()
    if not emails:
        return

    site = getattr(settings, 'SITE_NAME', 'VCS')
    subject = f"New Job Alert: {instance.title} at {instance.company}"
    body = f"""Hello,

A new job has just been posted that might interest you!

Position : {instance.title}
Company  : {instance.company}
Location : {instance.location}
Type     : {instance.job_type}
Salary   : {instance.get_salary_display()}

Log in to your {site} dashboard to apply early!

Best Regards,
The {site} Team"""

    _EmailThread(subject, body, emails).start()


@receiver(post_save, sender='vcs.Feed')
def notify_new_feed(sender, instance, created, **kwargs):
    if not created or not instance.is_published:
        return

    emails = _get_target_emails()
    if not emails:
        return

    site       = getattr(settings, 'SITE_NAME', 'VCS')
    feed_label = instance.get_feed_type_display()
    subject    = f"New {site} {feed_label}: {instance.title}"
    body = f"""Hello,

We just published a new {feed_label} for you!

"{instance.title}"

{instance.excerpt}

Log in to your {site} dashboard to read the full article.

Best Regards,
The {site} Team"""

    _EmailThread(subject, body, emails).start()