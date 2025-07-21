"""
Custom password validators for HIPAA compliance.
These validators ensure passwords meet strict medical security requirements.
"""

import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from django.contrib.auth.password_validation import MinimumLengthValidator


class SpecialCharacterValidator:
    """
    Validate that the password contains at least one special character.
    Required for HIPAA compliance - passwords must be complex.
    """
    
    def validate(self, password, user=None):
        """
        Validate that password contains at least one special character.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password doesn't contain special characters
        """
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>\/?]', password):
            raise ValidationError(
                _("Password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)."),
                code='password_no_special_char',
            )
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password must contain at least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?).")


class UppercaseValidator:
    """
    Validate that the password contains at least one uppercase letter.
    Required for HIPAA compliance - passwords must be complex.
    """
    
    def validate(self, password, user=None):
        """
        Validate that password contains at least one uppercase letter.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password doesn't contain uppercase letters
        """
        if not re.search(r'[A-Z]', password):
            raise ValidationError(
                _("Password must contain at least one uppercase letter."),
                code='password_no_uppercase',
            )
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password must contain at least one uppercase letter.")


class LowercaseValidator:
    """
    Validate that the password contains at least one lowercase letter.
    Required for HIPAA compliance - passwords must be complex.
    """
    
    def validate(self, password, user=None):
        """
        Validate that password contains at least one lowercase letter.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password doesn't contain lowercase letters
        """
        if not re.search(r'[a-z]', password):
            raise ValidationError(
                _("Password must contain at least one lowercase letter."),
                code='password_no_lowercase',
            )
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password must contain at least one lowercase letter.")


class NoSequentialCharactersValidator:
    """
    Validate that the password doesn't contain sequential characters.
    This prevents passwords like '123456' or 'abcdef'.
    """
    
    def validate(self, password, user=None):
        """
        Validate that password doesn't contain sequential characters.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password contains sequential characters
        """
        # Check for sequential numbers (123, 234, etc.)
        for i in range(len(password) - 2):
            if password[i:i+3].isdigit():
                nums = [int(x) for x in password[i:i+3]]
                if nums == sorted(nums) and nums[1] == nums[0] + 1 and nums[2] == nums[1] + 1:
                    raise ValidationError(
                        _("Password cannot contain sequential numbers (like 123, 234, etc.)."),
                        code='password_sequential_numbers',
                    )
        
        # Check for sequential letters (abc, def, etc.)
        for i in range(len(password) - 2):
            if password[i:i+3].isalpha():
                chars = password[i:i+3].lower()
                if (ord(chars[1]) == ord(chars[0]) + 1 and 
                    ord(chars[2]) == ord(chars[1]) + 1):
                    raise ValidationError(
                        _("Password cannot contain sequential letters (like abc, def, etc.)."),
                        code='password_sequential_letters',
                    )
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password cannot contain sequential characters (like 123 or abc).")


class NoRepeatingCharactersValidator:
    """
    Validate that the password doesn't contain too many repeating characters.
    This prevents passwords like '1111' or 'aaaa'.
    """
    
    def __init__(self, max_repeating=3):
        """
        Initialize validator with maximum repeating characters.
        
        Args:
            max_repeating: Maximum number of repeating characters allowed
        """
        self.max_repeating = max_repeating
    
    def validate(self, password, user=None):
        """
        Validate that password doesn't contain too many repeating characters.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password contains too many repeating characters
        """
        current_char = None
        count = 1
        
        for char in password:
            if char == current_char:
                count += 1
                if count > self.max_repeating:
                    raise ValidationError(
                        _("Password cannot contain more than %(max_repeating)d repeating characters.") % {
                            'max_repeating': self.max_repeating
                        },
                        code='password_too_many_repeating',
                    )
            else:
                current_char = char
                count = 1
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password cannot contain more than %(max_repeating)d repeating characters.") % {
            'max_repeating': self.max_repeating
        }


class NoPersonalInfoValidator:
    """
    Validate that the password doesn't contain personal information.
    This prevents passwords that contain username, email, first name, or last name.
    """
    
    def validate(self, password, user=None):
        """
        Validate that password doesn't contain personal information.
        
        Args:
            password: The password to validate
            user: The user instance (optional)
            
        Raises:
            ValidationError: If password contains personal information
        """
        if not user:
            return
        
        password_lower = password.lower()
        
        # Check username
        if hasattr(user, 'username') and user.username:
            if user.username.lower() in password_lower:
                raise ValidationError(
                    _("Password cannot contain your username."),
                    code='password_contains_username',
                )
        
        # Check email
        if hasattr(user, 'email') and user.email:
            email_parts = user.email.lower().split('@')
            if email_parts[0] in password_lower:
                raise ValidationError(
                    _("Password cannot contain your email address."),
                    code='password_contains_email',
                )
        
        # Check first name
        if hasattr(user, 'first_name') and user.first_name:
            if len(user.first_name) > 2 and user.first_name.lower() in password_lower:
                raise ValidationError(
                    _("Password cannot contain your first name."),
                    code='password_contains_first_name',
                )
        
        # Check last name
        if hasattr(user, 'last_name') and user.last_name:
            if len(user.last_name) > 2 and user.last_name.lower() in password_lower:
                raise ValidationError(
                    _("Password cannot contain your last name."),
                    code='password_contains_last_name',
                )
    
    def get_help_text(self):
        """Return help text for this validator."""
        return _("Your password cannot contain your personal information (username, email, name).") 