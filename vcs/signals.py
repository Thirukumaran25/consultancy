# vcs/signals.py
import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import EmailMessage
from django.conf import settings
from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import CompanyProfile 


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



@receiver(pre_save, sender=CompanyProfile)
def capture_old_status(sender, instance, **kwargs):
    if instance.pk: # If the profile already exists in the database
        try:
            old_profile = CompanyProfile.objects.get(pk=instance.pk)
            instance._old_status = old_profile.status
        except CompanyProfile.DoesNotExist:
            instance._old_status = None
    else:
        instance._old_status = None


@receiver(post_save, sender=CompanyProfile)
def send_status_update_email(sender, instance, created, **kwargs):
    if not created and hasattr(instance, '_old_status'):
        
        # Check if the status actually changed
        if instance._old_status != instance.status:
            subject = ""
            message = ""

            if instance.status == CompanyProfile.ApprovalStatus.APPROVED:
                subject = f"Your Company Profile '{instance.company_name}' is Approved!"
                message = (
                    f"Hello {instance.company_name},\n\n"
                    f"Great news! Your company registration has been approved. "
                    f"You can now log in to your dashboard and start posting jobs.\n\n"
                    f"Regards,\n"
                    f"The Team at VCS"
                )
            
            elif instance.status == CompanyProfile.ApprovalStatus.REJECTED:
                subject = f"Update regarding your Company Profile '{instance.company_name}'"
                reason = instance.rejection_reason if instance.rejection_reason else "No specific reason provided."
                message = (
                    f"Hello {instance.company_name},\n\n"
                    f"Unfortunately, your company registration has been rejected.\n\n"
                    f"Reason: {reason}\n\n"
                    f"If you believe this is a mistake or have updated your details, please contact our support team.\n\n"
                    f"Regards,\n"
                    f"The Team at VCS"
                )


            if subject and message:
                try:
                    send_mail(
                        subject,
                        message,
                        settings.EMAIL_HOST_USER,
                        [instance.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    print(f"Error sending status email to {instance.email}: {e}")