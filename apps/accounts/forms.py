"""
Forms for user accounts and invitation management.
Provides HIPAA-compliant forms for user registration and provider invitations.
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

from .models import Role, ProviderInvitation


class ProviderInvitationForm(forms.ModelForm):
    """
    Form for creating provider invitations.
    
    Allows administrators to send invitation links to healthcare providers
    with pre-assigned roles and optional personal messages.
    """
    
    expiration_days = forms.IntegerField(
        initial=7,
        min_value=1,
        max_value=30,
        help_text="Number of days until the invitation expires (1-30 days)",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '7'
        })
    )
    
    class Meta:
        model = ProviderInvitation
        fields = ['email', 'role', 'personal_message', 'expiration_days']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'provider@example.com',
                'required': True
            }),
            'role': forms.Select(attrs={
                'class': 'form-control',
                'required': True
            }),
            'personal_message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Optional personal message to include in the invitation...'
            }),
        }
        help_texts = {
            'email': 'Email address where the invitation will be sent',
            'role': 'Role to be assigned to the provider upon registration',
            'personal_message': 'Optional personal message to include in the invitation email',
        }
    
    def __init__(self, *args, **kwargs):
        """Initialize form with active roles only."""
        super().__init__(*args, **kwargs)
        
        # Only show active roles that are appropriate for providers
        self.fields['role'].queryset = Role.objects.filter(
            is_active=True
        ).order_by('display_name')
        
        # Set field labels
        self.fields['email'].label = 'Provider Email Address'
        self.fields['role'].label = 'Assigned Role'
        self.fields['personal_message'].label = 'Personal Message (Optional)'
        self.fields['expiration_days'].label = 'Expiration (Days)'
    
    def clean_email(self):
        """Validate email address and check for existing invitations."""
        email = self.cleaned_data['email'].lower().strip()
        
        # Check if user already exists
        if User.objects.filter(email=email).exists():
            raise ValidationError(
                f"A user with email '{email}' already exists. "
                "Please use a different email address."
            )
        
        # Check for existing active invitations
        existing_invitation = ProviderInvitation.objects.filter(
            email=email,
            is_active=True,
            expires_at__gt=timezone.now()
        ).first()
        
        if existing_invitation:
            raise ValidationError(
                f"An active invitation for '{email}' already exists. "
                f"It expires on {existing_invitation.expires_at.strftime('%B %d, %Y')}."
            )
        
        return email
    
    def clean_expiration_days(self):
        """Validate expiration days."""
        days = self.cleaned_data['expiration_days']
        
        if days < 1:
            raise ValidationError("Expiration must be at least 1 day.")
        if days > 30:
            raise ValidationError("Expiration cannot exceed 30 days.")
        
        return days
    
    def save(self, commit=True):
        """Save invitation with calculated expiration date."""
        invitation = super().save(commit=False)
        
        # Calculate expiration date
        expiration_days = self.cleaned_data['expiration_days']
        invitation.expires_at = timezone.now() + timedelta(days=expiration_days)
        
        if commit:
            invitation.save()
        
        return invitation


class InvitationRegistrationForm(UserCreationForm):
    """
    Registration form for users accepting provider invitations.
    
    Pre-fills email from invitation and ensures proper account creation
    with role assignment upon successful registration.
    """
    
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'First Name'
        }),
        help_text="Your first name"
    )
    
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Last Name'
        }),
        help_text="Your last name"
    )
    
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'readonly': True,  # Pre-filled from invitation
        }),
        help_text="Email address from your invitation"
    )
    
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'password1', 'password2')
    
    def __init__(self, *args, **kwargs):
        """Initialize form with invitation data."""
        self.invitation = kwargs.pop('invitation', None)
        super().__init__(*args, **kwargs)
        
        # Pre-fill email from invitation
        if self.invitation:
            self.fields['email'].initial = self.invitation.email
            self.fields['email'].widget.attrs['readonly'] = True
        
        # Add Bootstrap classes to password fields
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        })
        
        # Update labels
        self.fields['password1'].label = 'Password'
        self.fields['password2'].label = 'Confirm Password'
    
    def clean_email(self):
        """Validate email matches invitation."""
        email = self.cleaned_data['email'].lower().strip()
        
        if self.invitation and email != self.invitation.email:
            raise ValidationError(
                "Email address must match the invitation email."
            )
        
        # Check if user already exists
        if User.objects.filter(email=email).exists():
            raise ValidationError(
                "A user with this email address already exists."
            )
        
        return email
    
    def clean(self):
        """Additional form validation."""
        cleaned_data = super().clean()
        
        # Validate invitation is still valid
        if self.invitation and not self.invitation.is_valid():
            raise ValidationError(
                "This invitation has expired or is no longer valid."
            )
        
        return cleaned_data
    
    def save(self, commit=True):
        """Create user and accept invitation."""
        user = super().save(commit=False)
        
        # Set username to email
        user.username = self.cleaned_data['email']
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        
        if commit:
            user.save()
            
            # Accept the invitation (assigns role and creates profile)
            if self.invitation:
                self.invitation.accept(user)
        
        return user


class InvitationSearchForm(forms.Form):
    """
    Form for searching and filtering provider invitations.
    """
    
    SEARCH_CHOICES = [
        ('email', 'Email Address'),
        ('role', 'Role'),
        ('invited_by', 'Invited By'),
    ]
    
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
        ('revoked', 'Revoked'),
    ]
    
    search_term = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search invitations...'
        })
    )
    
    search_field = forms.ChoiceField(
        choices=SEARCH_CHOICES,
        required=False,
        initial='email',
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
    
    role = forms.ModelChoiceField(
        queryset=Role.objects.filter(is_active=True),
        required=False,
        empty_label="All Roles",
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
    
    def __init__(self, *args, **kwargs):
        """Initialize form."""
        super().__init__(*args, **kwargs)
        
        # Set labels
        self.fields['search_term'].label = 'Search'
        self.fields['search_field'].label = 'Search In'
        self.fields['status'].label = 'Status'
        self.fields['role'].label = 'Role'


class BulkInvitationForm(forms.Form):
    """
    Form for sending bulk invitations to multiple providers.
    """
    
    emails = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 8,
            'placeholder': 'Enter email addresses, one per line:\nprovider1@example.com\nprovider2@example.com\nprovider3@example.com'
        }),
        help_text="Enter email addresses, one per line (maximum 20 addresses)"
    )
    
    role = forms.ModelChoiceField(
        queryset=Role.objects.filter(is_active=True),
        required=True,
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        help_text="Role to be assigned to all invited providers"
    )
    
    expiration_days = forms.IntegerField(
        initial=7,
        min_value=1,
        max_value=30,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': '7'
        }),
        help_text="Number of days until invitations expire (1-30 days)"
    )
    
    personal_message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Optional personal message to include in all invitations...'
        }),
        help_text="Optional personal message to include in all invitation emails"
    )
    
    def __init__(self, *args, **kwargs):
        """Initialize form."""
        super().__init__(*args, **kwargs)
        
        # Set labels
        self.fields['emails'].label = 'Email Addresses'
        self.fields['role'].label = 'Assigned Role'
        self.fields['expiration_days'].label = 'Expiration (Days)'
        self.fields['personal_message'].label = 'Personal Message (Optional)'
    
    def clean_emails(self):
        """Validate and parse email addresses."""
        emails_text = self.cleaned_data['emails'].strip()
        
        if not emails_text:
            raise ValidationError("Please enter at least one email address.")
        
        # Split by lines and clean up
        email_lines = [line.strip() for line in emails_text.split('\n') if line.strip()]
        
        if len(email_lines) > 20:
            raise ValidationError("Maximum 20 email addresses allowed.")
        
        # Validate each email
        valid_emails = []
        invalid_emails = []
        duplicate_emails = []
        existing_users = []
        existing_invitations = []
        
        for line in email_lines:
            try:
                # Basic email validation
                forms.EmailField().clean(line.lower())
                email = line.lower().strip()
                
                # Check for duplicates in this submission
                if email in valid_emails:
                    duplicate_emails.append(email)
                    continue
                
                # Check if user already exists
                if User.objects.filter(email=email).exists():
                    existing_users.append(email)
                    continue
                
                # Check for existing active invitations
                if ProviderInvitation.objects.filter(
                    email=email,
                    is_active=True,
                    expires_at__gt=timezone.now()
                ).exists():
                    existing_invitations.append(email)
                    continue
                
                valid_emails.append(email)
                
            except ValidationError:
                invalid_emails.append(line)
        
        # Build error messages
        errors = []
        
        if invalid_emails:
            errors.append(f"Invalid email addresses: {', '.join(invalid_emails)}")
        
        if duplicate_emails:
            errors.append(f"Duplicate email addresses: {', '.join(duplicate_emails)}")
        
        if existing_users:
            errors.append(f"Users already exist: {', '.join(existing_users)}")
        
        if existing_invitations:
            errors.append(f"Active invitations already exist: {', '.join(existing_invitations)}")
        
        if errors:
            raise ValidationError(errors)
        
        if not valid_emails:
            raise ValidationError("No valid email addresses found.")
        
        return valid_emails
    
    def clean_expiration_days(self):
        """Validate expiration days."""
        days = self.cleaned_data['expiration_days']
        
        if days < 1:
            raise ValidationError("Expiration must be at least 1 day.")
        if days > 30:
            raise ValidationError("Expiration cannot exceed 30 days.")
        
        return days
