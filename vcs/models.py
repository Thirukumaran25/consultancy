from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.core.validators import FileExtensionValidator
from django.db.models.signals import post_save
from django.dispatch import receiver


class UISettings(models.Model):
    site_name = models.CharField(max_length=100, default="Vetri Consultancy Services")
    logo = models.ImageField(upload_to='site_config/', blank=True, null=True)
    login_illustration = models.ImageField(upload_to='site_config/', blank=True, null=True)
    candidate_tab_text = models.CharField(max_length=50, default="Candidate")
    trainee_tab_text = models.CharField(max_length=50, default="Trainee")
    company_tab_text = models.CharField(max_length=50, default="Company")

    class Meta:
        verbose_name = "Login UI Settings"
        verbose_name_plural = "Login UI Settings"

    def __str__(self):
        return "Global UI Configuration"

class User(AbstractUser):
    class Role(models.TextChoices):
        CANDIDATE = 'candidate', 'Candidate'
        TRAINEE   = 'trainee',   'Trainee'
        COMPANY   = 'company',   'Company'

    role = models.CharField(max_length=20,choices=Role.choices,blank=True,null=True,)
    groups = models.ManyToManyField(Group, blank=True,related_name='vcs_user_set',)
    user_permissions = models.ManyToManyField(Permission, blank=True,related_name='vcs_user_set',)

    def __str__(self):
        return f"{self.username} ({self.role})"

class Skill(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class CandidateProfile(models.Model):
    class SubscriptionPlan(models.TextChoices):
        FREE = 'Free', 'Free'
        PRO  = 'Pro',  'Pro'

    GENDER_CHOICES = (
        ('Male', 'Male'), 
        ('Female', 'Female'), 
        ('Other', 'Other')
    )
    
    MARITAL_CHOICES = (
        ('Single', 'Single'), 
        ('Married', 'Married'), 
        ('Other', 'Other')
    )

    user            = models.OneToOneField(User, on_delete=models.CASCADE, related_name='candidate_profile')
    profile_photo   = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    full_name       = models.CharField(max_length=255)
    phone_number    = models.CharField(max_length=20, blank=True, null=True)
    resume          = models.FileField(upload_to='resumes/', blank=True, null=True)
    accepted_terms  = models.BooleanField(default=False)
    created_at      = models.DateTimeField(auto_now_add=True)
    resume_headline = models.CharField(max_length=255, blank=True, null=True)
    profile_summary = models.TextField(blank=True, null=True)
    
    gender          = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    marital_status  = models.CharField(max_length=20, choices=MARITAL_CHOICES, blank=True, null=True)
    date_of_birth   = models.DateField(blank=True, null=True)
    languages_known = models.CharField(max_length=255, blank=True, null=True, help_text="Comma separated, e.g. English, Tamil")
    skills          = models.ManyToManyField('Skill', blank=True, related_name='candidates')
    is_fresher      = models.BooleanField(default=False)
    subscription_type = models.CharField(max_length=10,choices=SubscriptionPlan.choices, 
        default=SubscriptionPlan.FREE,
        help_text="Candidate's current subscription plan"
    )
    pro_expiry_date   = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.full_name} ({self.user.username})"


class Employment(models.Model):
    candidate = models.ForeignKey('CandidateProfile', on_delete=models.CASCADE, related_name='employments', null=True, blank=True)
    trainee = models.ForeignKey('TraineeProfile', on_delete=models.CASCADE, related_name='employments', null=True, blank=True)
    designation = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150)
    is_current = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True) 
    location = models.CharField(max_length=150, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-start_date'] # Orders by most recent job first

    def __str__(self):
        return f"{self.designation} at {self.company_name}"


class Education(models.Model):
    candidate = models.ForeignKey('CandidateProfile', on_delete=models.CASCADE, related_name='educations', null=True, blank=True)
    trainee = models.ForeignKey('TraineeProfile', on_delete=models.CASCADE, related_name='educations', null=True, blank=True)
    education_level = models.CharField(max_length=100, help_text="e.g. B.Tech / B.E.")
    course = models.CharField(max_length=100, help_text="e.g. Computer Science")
    university = models.CharField(max_length=200)
    start_year = models.IntegerField()
    end_year = models.IntegerField()
    
    COURSE_TYPE_CHOICES = (('Full Time', 'Full Time'), ('Part Time', 'Part Time'), ('Correspondence', 'Correspondence'))
    course_type = models.CharField(max_length=20, choices=COURSE_TYPE_CHOICES, default='Full Time')

    class Meta:
        ordering = ['-end_year'] # Orders by most recent graduation first

    def __str__(self):
        return f"{self.education_level} from {self.university}"


class Project(models.Model):
    candidate = models.ForeignKey('CandidateProfile', on_delete=models.CASCADE, related_name='projects', null=True, blank=True)
    trainee = models.ForeignKey('TraineeProfile', on_delete=models.CASCADE, related_name='projects', null=True, blank=True)
    title = models.CharField(max_length=200)
    project_url = models.URLField(blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_ongoing = models.BooleanField(default=False)
    description = models.TextField()

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.title
    

class TraineeProfile(models.Model):
    GENDER_CHOICES = (
        ('Male', 'Male'), 
        ('Female', 'Female'), 
        ('Other', 'Other')
    )
    
    MARITAL_CHOICES = (
        ('Single', 'Single'), 
        ('Married', 'Married'), 
        ('Other', 'Other')
    )

    # Core Identifiers
    user            = models.OneToOneField('User', on_delete=models.CASCADE, related_name='trainee_profile')
    batch_name      = models.CharField(max_length=100, blank=True, null=True)
    is_active       = models.BooleanField(default=True)
    joined_at       = models.DateTimeField(auto_now_add=True)

    # Basic Info
    profile_photo   = models.ImageField(upload_to='trainee_photos/', blank=True, null=True)
    full_name       = models.CharField(max_length=255)
    phone_number    = models.CharField(max_length=20, blank=True, null=True)
    
    # Professional Details
    resume          = models.FileField(upload_to='trainee_resumes/', blank=True, null=True)
    resume_headline = models.CharField(max_length=255, blank=True, null=True)
    profile_summary = models.TextField(blank=True, null=True)
    skills          = models.ManyToManyField('Skill', blank=True, related_name='trainees')
    is_fresher      = models.BooleanField(default=True) # Defaulting to True since they are trainees
    
    # Personal Details
    gender          = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    marital_status  = models.CharField(max_length=20, choices=MARITAL_CHOICES, blank=True, null=True)
    date_of_birth   = models.DateField(blank=True, null=True)
    languages_known = models.CharField(max_length=255, blank=True, null=True, help_text="Comma separated, e.g. English, Tamil")

    def __str__(self):
        return f"{self.full_name} — {self.batch_name or 'No Batch'}"


class CompanyProfile(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING  = 'Pending',  'Pending'
        APPROVED = 'Approved', 'Approved'
        REJECTED = 'Rejected', 'Rejected'

    user                  = models.OneToOneField(User, on_delete=models.CASCADE, related_name='company_profile')
    company_name          = models.CharField(max_length=255)
    email                 = models.EmailField(unique=True)
    location              = models.CharField(max_length=300)
    registration_document = models.FileField(upload_to='company_docs/reg/')
    gst_document          = models.FileField(upload_to='company_docs/gst/')
    linkedin_url          = models.URLField(blank=True, null=True)
    website_url           = models.URLField(blank=True, null=True)
    instagram_url         = models.URLField(blank=True, null=True)
    facebook_url          = models.URLField(blank=True, null=True)
    accepted_terms        = models.BooleanField(default=False)
    created_at            = models.DateTimeField(auto_now_add=True)

    status           = models.CharField(max_length=20, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    rejection_reason = models.TextField(blank=True, null=True, help_text="Provide a reason if rejecting the company")

    def __str__(self):
        return f"{self.company_name} ({self.status})"


class CompanyPhoto(models.Model):
    company = models.ForeignKey(CompanyProfile, on_delete=models.CASCADE, related_name='photos')
    photo   = models.ImageField(upload_to='company_photos/')

    def __str__(self):
        return f"Photo — {self.company.company_name}"
    

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Automatically creates the corresponding profile when a User is created via Admin.
    """
    if created:
        if instance.role == User.Role.TRAINEE:
            TraineeProfile.objects.create(
                user=instance, 
                full_name=instance.username 
            )
            
        elif instance.role == User.Role.CANDIDATE:
            CandidateProfile.objects.get_or_create(
                user=instance, 
                defaults={'full_name': instance.username} 
            )


class JobCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    icon = models.CharField(max_length=50, blank=True, null=True, help_text="Font Awesome class e.g. fa-code")

    class Meta:
        verbose_name_plural = "Job Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Job(models.Model):
    class JobType(models.TextChoices):
        FULL_TIME  = 'Full Time',  'Full Time'
        PART_TIME  = 'Part Time',  'Part Time'
        CONTRACT   = 'Contract',   'Contract'
        INTERNSHIP = 'Internship', 'Internship'
        FREELANCE  = 'Freelance',  'Freelance'
        REMOTE     = 'Remote',     'Remote'

    class WorkMode(models.TextChoices):
        ONSITE = 'On-site', 'On-site'
        REMOTE = 'Remote',  'Remote'
        HYBRID = 'Hybrid',  'Hybrid'

    company         = models.CharField(max_length=255, help_text="Enter company name manually")
    company_profile = models.ForeignKey('CompanyProfile', on_delete=models.CASCADE, related_name='posted_jobs', null=True, blank=True)
    category        = models.ForeignKey(JobCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    title           = models.CharField(max_length=255)
    slug            = models.SlugField(unique=True, blank=True)
    description     = models.TextField()
    responsibilities = models.TextField(blank=True, null=True, help_text="One per line")
    requirements    = models.TextField(blank=True, null=True, help_text="One per line")
    benefits        = models.TextField(blank=True, null=True, help_text="One per line")
    job_type        = models.CharField(max_length=20, choices=JobType.choices, default=JobType.FULL_TIME)
    work_mode       = models.CharField(max_length=20, choices=WorkMode.choices, default=WorkMode.ONSITE)
    experience      = models.CharField(max_length=100, help_text="Enter experience manually (e.g., 2-5 Years, Fresher)")
    location        = models.CharField(max_length=200)
    salary_min      = models.PositiveIntegerField(null=True, blank=True, help_text="Annual in LPA (e.g. 3)")
    salary_max      = models.PositiveIntegerField(null=True, blank=True, help_text="Annual in LPA (e.g. 8)")
    salary_hidden   = models.BooleanField(default=False, help_text="Show 'Not Disclosed' instead of salary")
    skills_required = models.CharField(max_length=255, help_text="Enter skills manually, separated by commas (e.g., Python, Django, React)")
    openings        = models.PositiveIntegerField(default=1)
    is_active       = models.BooleanField(default=True)
    is_featured     = models.BooleanField(default=False)
    posted_at       = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    deadline        = models.DateField(null=True, blank=True)

    hr_name  = models.CharField(max_length=100, blank=True, null=True)
    hr_email = models.EmailField(blank=True, null=True)
    hr_phone = models.CharField(max_length=20, blank=True, null=True)
    is_masked_contact = models.BooleanField(
        default=True, 
        help_text="Check to partially mask HR contact details and require a button click to reveal."
    )

    class Meta:
        ordering = ['-is_featured', '-posted_at']

    def __str__(self):
        return f"{self.title} — {self.company}"

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(f"{self.title}-{self.company}")
            slug = base
            n = 1
            while Job.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_salary_display(self):
        if self.salary_hidden:
            return "Not Disclosed"
        if self.salary_min and self.salary_max:
            return f"₹{self.salary_min} – {self.salary_max} LPA"
        if self.salary_min:
            return f"₹{self.salary_min}+ LPA"
        return "Not Disclosed"

    def days_ago(self):
        from django.utils import timezone
        delta = timezone.now() - self.posted_at
        if delta.days == 0:
            return "Today"
        if delta.days == 1:
            return "1 day ago"
        if delta.days < 30:
            return f"{delta.days} days ago"
        if delta.days < 60:
            return "1 month ago"
        return f"{delta.days // 30} months ago"


class JobApplication(models.Model):
    class Status(models.TextChoices):
        APPLIED    = 'Applied',    'Applied'
        REVIEWING  = 'Reviewing',  'Reviewing'
        SHORTLISTED = 'Shortlisted', 'Shortlisted'
        INTERVIEW  = 'Interview',  'Interview Scheduled'
        OFFERED    = 'Offered',    'Offer Extended'
        REJECTED   = 'Rejected',  'Rejected'
        WITHDRAWN  = 'Withdrawn',  'Withdrawn'

    job       = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')
    candidate = models.ForeignKey('CandidateProfile', on_delete=models.CASCADE, related_name='applications', null=True, blank=True)    
    trainee = models.ForeignKey('TraineeProfile', on_delete=models.CASCADE, related_name='applications', null=True, blank=True)
    status    = models.CharField(max_length=20, choices=Status.choices, default=Status.APPLIED)
    cover_letter = models.TextField(blank=True, null=True)
    applied_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('job', 'candidate')
        ordering = ['-applied_at']

    def __str__(self):
        applicant_name = "Unknown Applicant"
        
        if self.candidate:
            applicant_name = self.candidate.full_name
        elif self.trainee:
            applicant_name = self.trainee.full_name

        return f"{applicant_name} → {self.job.title}"
    


class Feed(models.Model):
    class FeedType(models.TextChoices):
        ARTICLE      = 'article',     'Article'
        TIP          = 'tip',         'Career Tip'
        NEWS         = 'news',        'Industry News'
        ANNOUNCEMENT = 'announcement', 'Announcement'

    title       = models.CharField(max_length=255)
    slug        = models.SlugField(unique=True, blank=True)
    feed_type   = models.CharField(max_length=20, choices=FeedType.choices, default=FeedType.ARTICLE)
    
    # ── UPDATED: Now accepts images and videos ──
    media_file  = models.FileField(
        upload_to='feeds/media/', 
        blank=True, 
        null=True,
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif', 'webp', 'mp4', 'webm', 'mov'])],
        help_text="Upload an image or a short video clip"
    )
    
    excerpt     = models.TextField(max_length=300, help_text="Short summary shown on card")
    content     = models.TextField(help_text="Full article content")
    author_name = models.CharField(max_length=100, default="VCS Team")
    tags        = models.CharField(max_length=255, blank=True, null=True,
                                   help_text="Comma separated e.g. Python, Career, Jobs")
    is_published = models.BooleanField(default=True)
    is_featured  = models.BooleanField(default=False)
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    views        = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['-is_featured', '-published_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            from django.utils.text import slugify
            base = slugify(self.title)
            slug, n = base, 1
            while Feed.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_tags_list(self):
        return [t.strip() for t in (self.tags or '').split(',') if t.strip()]

    def read_time(self):
        words = len(self.content.split())
        mins  = max(1, words // 200)
        return f"{mins} min read"
        

    @property
    def is_video(self):
        if self.media_file:
            extension = self.media_file.name.split('.')[-1].lower()
            return extension in ['mp4', 'webm', 'mov']
        return False



class SubscriptionOffer(models.Model):
    subtitle = models.CharField(max_length=100, default="ELEVATE YOUR CAREER")
    main_title = models.CharField(max_length=100, default="25% Off on Pro")
    button_text = models.CharField(max_length=50, default="Claim your offer")
    bottom_text = models.CharField(max_length=100, default="Limited time only!")
    
    illustration = models.ImageField(upload_to='offers/', blank=True, null=True, help_text="Upload the isometric 3D character image here")
    bg_gradient_start = models.CharField(max_length=20, default="#ffd97d", help_text="Hex color code (e.g., #ffd97d)")
    bg_gradient_end = models.CharField(max_length=20, default="#fff4d1", help_text="Hex color code (e.g., #fff4d1)")
    
    is_active = models.BooleanField(default=False, help_text="Turn this on to display the banner to Free users")

    def save(self, *args, **kwargs):
        if self.is_active:
            SubscriptionOffer.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.main_title


class ProFeature(models.Model):
    name = models.CharField(max_length=200, help_text="e.g. Auto-Apply on Jobs")
    is_active = models.BooleanField(default=True, help_text="Uncheck to hide this feature from the list")
    order = models.PositiveIntegerField(default=0, help_text="Use numbers (1, 2, 3) to sort the list")

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return self.name
    

class SubscriptionPlan(models.Model):
    # Core Plan Details
    months = models.PositiveIntegerField(
        default=0,
        help_text="Duration in months (e.g., 1, 3). Enter 0 if this is a daily plan."
    )
    days = models.PositiveIntegerField(
        default=0,
        help_text="Duration in days (e.g., 28, 56). Enter 0 if this is a monthly plan."
    )
    base_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        help_text="The original full price before any discounts"
    )
    
    # First Discount
    discount1 = models.PositiveIntegerField(
        default=0, 
        help_text="First discount percentage (e.g., 33). Enter 0 if none."
    )
    discount1_code = models.CharField(
        max_length=50, 
        blank=True, 
        help_text="Code name for 1st discount (e.g., 3MOFF)"
    )
    
    # Second Discount
    discount2 = models.PositiveIntegerField(
        default=0, 
        help_text="Second discount percentage (e.g., 30). Enter 0 if none."
    )
    discount2_code = models.CharField(
        max_length=50, 
        blank=True, 
        help_text="Code name for 2nd discount (e.g., PROSALE30)"
    )
    
    # Taxes
    gst_pct = models.PositiveIntegerField(
        default=18, 
        help_text="GST Percentage (default is 18%)"
    )
    
    # UI/Display Adjustments
    is_popular = models.BooleanField(
        default=False, 
        help_text="Highlight this plan with a 'Popular' badge?"
    )
    daily_text = models.CharField(
        max_length=100, 
        blank=True, 
        help_text="Optional bottom text (e.g., 'just ₹ 20/day')"
    )
    
    # Control Visibility
    is_active = models.BooleanField(
        default=True, 
        help_text="Uncheck to hide this plan from users"
    )

    class Meta:
        ordering = ['months', 'days']
        verbose_name = "Subscription Plan"
        verbose_name_plural = "Subscription Plans"

    def __str__(self):
        if self.days > 0 and self.months == 0:
            return f"{self.days}-Day Plan (₹{self.base_price})"
        elif self.months > 0:
            return f"{self.months}-Month Plan (₹{self.base_price})"
        return f"Custom Plan (₹{self.base_price})"

    @property
    def final_calculated_price(self):
        """Helper to preview the final calculated price in the admin"""
        base = float(self.base_price)
        after_disc1 = base - (base * (self.discount1 / 100))
        after_disc2 = after_disc1 - (after_disc1 * (self.discount2 / 100))
        final = after_disc2 + (after_disc2 * (self.gst_pct / 100))
        return round(final)
    


class PaymentOrder(models.Model):
    class Status(models.TextChoices):
        CREATED  = 'created',  'Created'
        PAID     = 'paid',     'Paid'
        FAILED   = 'failed',   'Failed'

    candidate= models.ForeignKey(CandidateProfile, on_delete=models.CASCADE,related_name='payments')
    plan= models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True)
    razorpay_order_id = models.CharField(max_length=100, unique=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, null=True)
    razorpay_signature  = models.CharField(max_length=255, blank=True, null=True)
    amount_paise      = models.PositiveIntegerField(help_text="Amount in paise")
    status            = models.CharField(max_length=10, choices=Status.choices,
                                         default=Status.CREATED)
    created_at        = models.DateTimeField(auto_now_add=True)
    paid_at           = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.candidate.full_name} — ₹{self.amount_paise//100} — {self.status}"

    @property
    def amount_rupees(self):
        return self.amount_paise // 100