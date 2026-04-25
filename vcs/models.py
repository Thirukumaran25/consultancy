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