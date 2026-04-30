# signals.py
import threading
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import EmailMessage
from django.conf import settings
from .models import Job, Feed, CandidateProfile, TraineeProfile

# ── BACKGROUND THREAD FOR FAST SENDING ──
class EmailThread(threading.Thread):
    def __init__(self, subject, message, bcc_list):
        self.subject = subject
        self.message = message
        self.bcc_list = bcc_list
        threading.Thread.__init__(self)

    def run(self):
        email = EmailMessage(
            subject=self.subject,
            body=self.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[settings.DEFAULT_FROM_EMAIL], # Send to self
            bcc=self.bcc_list                 # Blind-copy everyone else
        )
        email.send(fail_silently=True)

def get_target_emails():
    """Helper function to get all Trainees and PRO Candidates"""
    # Get Pro Candidate emails
    pro_candidates = CandidateProfile.objects.filter(
        subscription_type='Pro', 
        user__is_active=True
    ).values_list('user__email', flat=True)
    
    # Get Trainee emails
    trainees = TraineeProfile.objects.filter(
        user__is_active=True
    ).values_list('user__email', flat=True)
    
    # Combine lists, remove duplicates, and remove empty emails
    all_emails = list(set(list(pro_candidates) + list(trainees)))
    return [email for email in all_emails if email]


# ── TRIGGER: WHEN A JOB IS ADDED ──
@receiver(post_save, sender=Job)
def notify_new_job(sender, instance, created, **kwargs):
    # Only trigger if it's a NEW job and it's active
    if created and instance.is_active:
        emails = get_target_emails()
        if not emails:
            return
            
        subject = f"New Job Posted: {instance.title} at {instance.company}"
        message = (
            f"Hello,\n\n"
            f"A new job '{instance.title}' has just been posted by {instance.company}.\n\n"
            f"Log in to your VCS dashboard to check the requirements and apply early!\n\n"
            f"Best Regards,\nVCS Team"
        )
        
        # Start the background email thread
        EmailThread(subject, message, emails).start()


# ── TRIGGER: WHEN A FEED/NEWS IS ADDED ──
@receiver(post_save, sender=Feed)
def notify_new_feed(sender, instance, created, **kwargs):
    # Only trigger if it's a NEW feed and it's published
    if created and getattr(instance, 'is_published', True):
        emails = get_target_emails()
        if not emails:
            return
            
        feed_type = instance.get_feed_type_display() if hasattr(instance, 'get_feed_type_display') else 'Update'
        
        subject = f"New VCS {feed_type}: {instance.title}"
        message = (
            f"Hello,\n\n"
            f"We just published a new {feed_type}: '{instance.title}'.\n\n"
            f"Log in to your VCS dashboard to read more insights and updates.\n\n"
            f"Best Regards,\nVCS Team"
        )
        
        # Start the background email thread
        EmailThread(subject, message, emails).start()