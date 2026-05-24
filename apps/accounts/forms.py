"""
Forms for user accounts.
"""

from django import forms
from django.contrib.auth.models import User


class ProfileEditForm(forms.ModelForm):
    """Form for users to edit their own profile info."""

    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)

    class Meta:
        model = User
        fields = ['first_name', 'last_name']
