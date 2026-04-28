from django.db import models
from django.contrib.auth.models import AbstractUser, Group, Permission
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
    user           = models.OneToOneField(User, on_delete=models.CASCADE, related_name='candidate_profile')
    profile_photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    full_name      = models.CharField(max_length=255)
    phone_number   = models.CharField(max_length=20, blank=True, null=True)
    resume         = models.FileField(upload_to='resumes/', blank=True, null=True)
    accepted_terms = models.BooleanField(default=False)
    created_at     = models.DateTimeField(auto_now_add=True)
    resume_headline = models.CharField(max_length=255, blank=True, null=True)
    profile_summary = models.TextField(blank=True, null=True)
    GENDER_CHOICES = (('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other'))
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    MARITAL_CHOICES = (('Single', 'Single'), ('Married', 'Married'), ('Other', 'Other'))
    marital_status = models.CharField(max_length=20, choices=MARITAL_CHOICES, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    languages_known = models.CharField(max_length=255, blank=True, null=True, help_text="Comma separated, e.g. English, Tamil")
    skills = models.ManyToManyField(Skill, blank=True, related_name='candidates')
    is_fresher = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.full_name} ({self.user.username})"


class Employment(models.Model):
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name='employments')
    designation = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150)
    is_current = models.BooleanField(default=False)
    start_date = models.DateField()
    end_date = models.DateField(blank=True, null=True) # Null if is_current is True
    location = models.CharField(max_length=150, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['-start_date'] # Orders by most recent job first

    def __str__(self):
        return f"{self.designation} at {self.company_name}"


class Education(models.Model):
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name='educations')
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
    candidate = models.ForeignKey(CandidateProfile, on_delete=models.CASCADE, related_name='projects')
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
    user         = models.OneToOneField(User, on_delete=models.CASCADE, related_name='trainee_profile')
    full_name    = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    batch_name   = models.CharField(max_length=100, blank=True, null=True)
    is_active    = models.BooleanField(default=True)
    joined_at    = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} — {self.batch_name or 'No Batch'}"


class CompanyProfile(models.Model):
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
    is_approved           = models.BooleanField(default=False)
    accepted_terms        = models.BooleanField(default=False)
    created_at            = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name} ({'Approved' if self.is_approved else 'Pending'})"


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

    # Core
    company         = models.CharField(max_length=255, help_text="Enter company name manually")
    category        = models.ForeignKey(JobCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='jobs')
    title           = models.CharField(max_length=255)
    slug            = models.SlugField(unique=True, blank=True)
    description     = models.TextField()
    responsibilities = models.TextField(blank=True, null=True, help_text="One per line")
    requirements    = models.TextField(blank=True, null=True, help_text="One per line")
    benefits        = models.TextField(blank=True, null=True, help_text="One per line")

    # Classification
    job_type        = models.CharField(max_length=20, choices=JobType.choices, default=JobType.FULL_TIME)
    work_mode       = models.CharField(max_length=20, choices=WorkMode.choices, default=WorkMode.ONSITE)
    experience      = models.CharField(max_length=100, help_text="Enter experience manually (e.g., 2-5 Years, Fresher)")

    # Location & Salary
    location        = models.CharField(max_length=200)
    salary_min      = models.PositiveIntegerField(null=True, blank=True, help_text="Annual in LPA (e.g. 3)")
    salary_max      = models.PositiveIntegerField(null=True, blank=True, help_text="Annual in LPA (e.g. 8)")
    salary_hidden   = models.BooleanField(default=False, help_text="Show 'Not Disclosed' instead of salary")

    # Skills
    skills_required = models.CharField(max_length=255, help_text="Enter skills manually, separated by commas (e.g., Python, Django, React)")

    # Meta
    openings        = models.PositiveIntegerField(default=1)
    is_active       = models.BooleanField(default=True)
    is_featured     = models.BooleanField(default=False)
    posted_at       = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)
    deadline        = models.DateField(null=True, blank=True)

    hr_name  = models.CharField(max_length=100, blank=True, null=True)
    hr_email = models.EmailField(blank=True, null=True)
    hr_phone = models.CharField(max_length=20, blank=True, null=True)

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
    candidate = models.ForeignKey('CandidateProfile', on_delete=models.CASCADE, related_name='applications')
    status    = models.CharField(max_length=20, choices=Status.choices, default=Status.APPLIED)
    cover_letter = models.TextField(blank=True, null=True)
    applied_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('job', 'candidate')
        ordering = ['-applied_at']

    def __str__(self):
        return f"{self.candidate.full_name} → {self.job.title}"