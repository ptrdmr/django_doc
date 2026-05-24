"""
Access control decorators for the two-tier user model.

Moritrac Admin (is_staff=True) -> full access
User (is_staff=False) -> own data only, no admin features
"""

from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
import logging

logger = logging.getLogger(__name__)


def moritrac_admin_required(view_func):
    """
    Restrict view to Moritrac Admins (is_staff=True).

    Usage:
        @moritrac_admin_required
        def admin_dashboard(request):
            ...

    For CBVs:
        @method_decorator(moritrac_admin_required, name='dispatch')
        class AdminView(LoginRequiredMixin, View):
            ...
    """
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            logger.warning(f"User {request.user.id} denied admin access to {view_func.__name__}")
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapper
