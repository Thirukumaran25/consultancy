from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.account.adapter import DefaultAccountAdapter
from django.contrib.auth import get_user_model

User = get_user_model()


class MySocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        """
        If a user with the same email already exists, connect
        the social account to that existing user instead of
        creating a duplicate.
        """
        if sociallogin.is_existing:
            return

        try:
            email = sociallogin.account.extra_data.get('email', '').lower()
            if email:
                existing_user = User.objects.get(email__iexact=email)
                sociallogin.connect(request, existing_user)
        except User.DoesNotExist:
            pass

    def save_user(self, request, sociallogin, form=None):
        """
        When a brand new Google user signs up, automatically
        set role=candidate and create their CandidateProfile.
        """
        user = super().save_user(request, sociallogin, form)
        user.role = User.Role.CANDIDATE
        user.save()

        from vcs.models import CandidateProfile
        if not hasattr(user, 'candidate_profile'):
            full_name = f"{user.first_name} {user.last_name}".strip() or user.username
            CandidateProfile.objects.create(
                user           = user,
                full_name      = full_name,
                accepted_terms = True,
            )
        return user