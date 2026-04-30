# vcs/recommender.py
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .models import Job, JobApplication, CandidateProfile


def build_candidate_profile_text(profile):
    """Build a text representation of the candidate for TF-IDF."""
    parts = []

    # Skills
    if hasattr(profile, 'skills'):
        skills = list(profile.skills.values_list('name', flat=True))
        if skills:
            parts.append(' '.join(skills) * 3) 

    # Headline
    if getattr(profile, 'resume_headline', None):
        parts.append(profile.resume_headline * 2)

    # Summary
    if getattr(profile, 'profile_summary', None):
        parts.append(profile.profile_summary)

    # Employment history (Check if the profile has this relation first!)
    if hasattr(profile, 'employments'):
        for emp in profile.employments.all():
            parts.append(emp.designation)
            parts.append(emp.company_name)
            if emp.description:
                parts.append(emp.description)

    # Education
    if hasattr(profile, 'educations'):
        for edu in profile.educations.all():
            parts.append(edu.education_level)
            parts.append(edu.course)

    # Projects
    if hasattr(profile, 'projects'):
        for proj in profile.projects.all():
            parts.append(proj.title)
            if proj.description:
                parts.append(proj.description)

    return ' '.join(parts).lower().strip()


def build_job_text(job):
    """Build a text representation of a job for TF-IDF."""
    parts = []

    parts.append(job.title * 3)                          # weight title higher

    if job.skills_required:
        parts.append(job.skills_required * 2)

    parts.append(job.description)

    if job.responsibilities:
        parts.append(job.responsibilities)

    if job.requirements:
        parts.append(job.requirements)

    parts.append(job.experience)
    parts.append(job.location)

    return ' '.join(parts).lower().strip()


def get_recommendations(profile, limit=6):
    """
    Content-based filtering using TF-IDF + cosine similarity.
    Returns ranked list of (job, score) tuples.
    """
    # Get active jobs the candidate hasn't applied to
    # ── CHANGE IT TO THIS ──
    applied_ids = JobApplication.objects.filter(candidate__user=profile.user).values_list('job_id', flat=True)

    jobs = list(
        Job.objects.filter(is_active=True)
        .exclude(id__in=applied_ids)
        .select_related('category')[:200]  # cap for performance
    )

    if not jobs:
        return []

    candidate_text = build_candidate_profile_text(profile)

    if not candidate_text.strip():
        # No profile data — return featured jobs as fallback
        return [(job, 0.0) for job in jobs[:limit]]

    job_texts    = [build_job_text(j) for j in jobs]
    all_texts    = [candidate_text] + job_texts

    try:
        vectorizer = TfidfVectorizer(
            max_features=5000,
            stop_words='english',
            ngram_range=(1, 2),
            min_df=1,
        )
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        candidate_vec = tfidf_matrix[0]
        job_vecs      = tfidf_matrix[1:]
        scores        = cosine_similarity(candidate_vec, job_vecs).flatten()
    except Exception:
        return [(job, 0.0) for job in jobs[:limit]]

    # Sort by score descending, boost featured jobs
    ranked = []
    for job, score in zip(jobs, scores):
        boosted = score + (0.1 if job.is_featured else 0)
        ranked.append((job, round(float(boosted), 3)))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:limit]


def get_skill_gap(profile, job):
    """
    Compare candidate skills vs job required skills.
    Returns (matching_skills, missing_skills).
    """
    candidate_skills = set(
        s.lower() for s in profile.skills.values_list('name', flat=True)
    )
    job_skills = set(
        s.strip().lower()
        for s in (job.skills_required or '').split(',')
        if s.strip()
    )

    matching = candidate_skills & job_skills
    missing  = job_skills - candidate_skills

    return list(matching), list(missing)


def get_similar_jobs(job, limit=4):
    """Jobs similar to the one being viewed."""
    other_jobs = list(
        Job.objects.filter(is_active=True)
        .exclude(id=job.id)
        .select_related('category')[:100]
    )

    if not other_jobs:
        return []

    this_text  = build_job_text(job)
    other_texts = [build_job_text(j) for j in other_jobs]
    all_texts   = [this_text] + other_texts

    try:
        vectorizer   = TfidfVectorizer(max_features=3000, stop_words='english')
        matrix       = vectorizer.fit_transform(all_texts)
        scores       = cosine_similarity(matrix[0], matrix[1:]).flatten()
    except Exception:
        return other_jobs[:limit]

    ranked = sorted(zip(other_jobs, scores), key=lambda x: x[1], reverse=True)
    return [j for j, _ in ranked[:limit]]