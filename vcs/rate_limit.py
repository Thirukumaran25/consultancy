# vcs/rate_limit.py
"""
Central place for all rate limit rules.
Uses django-ratelimit under the hood.
"""
from functools import wraps
from django.http import JsonResponse
from django.shortcuts import render
from django.contrib import messages as django_messages
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited


def _get_rate_limited_response(request, is_ajax=False, msg=None):
    """Return appropriate response when rate limit is hit."""
    default_msg = "Too many attempts. Please wait a few minutes and try again."
    message = msg or default_msg

    if is_ajax or request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'error': message, 'rate_limited': True}, status=429)

    return render(request, 'errors/429.html', {'message': message}, status=429)


def rate_limit(key='ip', rate='5/m', method='POST', block=True, ajax=False, msg=None):
    """
    Decorator factory for rate limiting views.

    Usage:
        @rate_limit(rate='5/m')
        def my_view(request): ...

        @rate_limit(key='user', rate='10/h', ajax=True)
        def my_api(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            # Apply ratelimit check
            decorated = ratelimit(key=key, rate=rate, method=method, block=block)(view_func)
            try:
                return decorated(request, *args, **kwargs)
            except Ratelimited:
                return _get_rate_limited_response(request, is_ajax=ajax, msg=msg)
        return wrapped
    return decorator