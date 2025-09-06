"""
Services for user accounts and invitation management.
Provides business logic for provider invitations and user management.
"""

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import transaction
from datetime import timedelta
import logging

from .models import ProviderInvitation, Role, UserProfile

logger = logging.getLogger(__name__)


class InvitationService:
    """
    Service class for managing provider invitations.
    
    Handles invitation creation, email sending, validation, and acceptance
    with proper error handling and audit logging.
    """
    
    @staticmethod
    def create_invitation(email, role, invited_by, expiration_days=7, personal_message=""):
        """
        Create a new provider invitation.
        
        Args:
            email (str): Email address of the invited provider
            role (Role): Role instance to be assigned
            invited_by (User): User who is creating the invitation
            expiration_days (int): Number of days until expiration (default: 7)
            personal_message (str): Optional personal message
        
        Returns:
            ProviderInvitation: Created invitation instance
            
        Raises:
            ValidationError: If invitation cannot be created
        """
        try:
            with transaction.atomic():
                # Clean up any expired invitations for this email first
                InvitationService.cleanup_expired_invitations_for_email(email)
                
                # Create the invitation
                invitation = ProviderInvitation.objects.create(
                    email=email.lower().strip(),
                    role=role,
                    invited_by=invited_by,
                    expires_at=timezone.now() + timedelta(days=expiration_days),
                    personal_message=personal_message
                )
                
                logger.info(f"Created invitation {invitation.id} for {email} by {invited_by.email}")
                return invitation
                
        except Exception as e:
            logger.error(f"Failed to create invitation for {email}: {e}")
            raise
    
    @staticmethod
    def send_invitation_email(invitation, request):
        """
        Send invitation email to the provider.
        
        Args:
            invitation (ProviderInvitation): Invitation instance
            request (HttpRequest): Request object for building URLs
            
        Returns:
            bool: True if email was sent successfully
            
        Raises:
            Exception: If email sending fails
        """
        try:
            # Build invitation URL
            invitation_url = request.build_absolute_uri(
                reverse('accounts:accept_invitation', kwargs={'token': invitation.token})
            )
            
            # Prepare email context
            context = {
                'invitation': invitation,
                'invitation_url': invitation_url,
                'invited_by_name': invitation.invited_by.get_full_name() or invitation.invited_by.email,
                'role_name': invitation.role.display_name,
                'site_name': getattr(settings, 'SITE_NAME', 'Medical Document Parser'),
                'expiration_date': invitation.expires_at.strftime('%B %d, %Y at %I:%M %p'),
                'days_until_expiry': invitation.get_days_until_expiry(),
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@meddocparser.com'),
                'personal_message': invitation.personal_message,
            }
            
            # Render email templates
            subject = f"Invitation to join {context['site_name']} as a healthcare provider"
            html_message = render_to_string('accounts/emails/provider_invitation.html', context)
            plain_message = render_to_string('accounts/emails/provider_invitation.txt', context)
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@meddocparser.com'),
                recipient_list=[invitation.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f"Sent invitation email to {invitation.email} for invitation {invitation.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send invitation email to {invitation.email}: {e}")
            raise
    
    @staticmethod
    def get_invitation_by_token(token):
        """
        Get an active invitation by token.
        
        Args:
            token (str): Invitation token
            
        Returns:
            ProviderInvitation or None: Active invitation if found and valid
        """
        try:
            invitation = ProviderInvitation.objects.get(
                token=token,
                is_active=True
            )
            
            # Check if expired
            if invitation.is_expired():
                logger.info(f"Invitation {invitation.id} has expired")
                return None
            
            return invitation
            
        except ProviderInvitation.DoesNotExist:
            logger.warning(f"No active invitation found for token: {token[:8]}...")
            return None
    
    @staticmethod
    def accept_invitation(invitation, user):
        """
        Accept an invitation and assign role to user.
        
        Args:
            invitation (ProviderInvitation): Invitation to accept
            user (User): User accepting the invitation
            
        Returns:
            bool: True if invitation was successfully accepted
        """
        try:
            with transaction.atomic():
                # Validate invitation
                if not invitation.is_valid():
                    logger.warning(f"Attempted to accept invalid invitation {invitation.id}")
                    return False
                
                # Accept the invitation using the model method
                success = invitation.accept(user)
                
                if success:
                    logger.info(f"User {user.email} accepted invitation {invitation.id}")
                else:
                    logger.warning(f"Failed to accept invitation {invitation.id} for user {user.email}")
                
                return success
                
        except Exception as e:
            logger.error(f"Error accepting invitation {invitation.id}: {e}")
            return False
    
    @staticmethod
    def revoke_invitation(invitation_id, revoked_by):
        """
        Revoke an invitation.
        
        Args:
            invitation_id (str): UUID of the invitation to revoke
            revoked_by (User): User revoking the invitation
            
        Returns:
            bool: True if invitation was revoked successfully
        """
        try:
            invitation = ProviderInvitation.objects.get(id=invitation_id)
            
            if invitation.revoke():
                logger.info(f"Invitation {invitation_id} revoked by {revoked_by.email}")
                return True
            else:
                logger.warning(f"Could not revoke invitation {invitation_id} - already accepted or inactive")
                return False
                
        except ProviderInvitation.DoesNotExist:
            logger.error(f"Invitation {invitation_id} not found for revocation")
            return False
        except Exception as e:
            logger.error(f"Error revoking invitation {invitation_id}: {e}")
            return False
    
    @staticmethod
    def resend_invitation(invitation_id, request):
        """
        Resend an invitation email.
        
        Args:
            invitation_id (str): UUID of the invitation to resend
            request (HttpRequest): Request object for building URLs
            
        Returns:
            bool: True if email was resent successfully
        """
        try:
            invitation = ProviderInvitation.objects.get(id=invitation_id)
            
            # Only resend if invitation is still valid
            if not invitation.is_valid():
                logger.warning(f"Cannot resend invalid invitation {invitation_id}")
                return False
            
            # Send the email
            return InvitationService.send_invitation_email(invitation, request)
            
        except ProviderInvitation.DoesNotExist:
            logger.error(f"Invitation {invitation_id} not found for resending")
            return False
        except Exception as e:
            logger.error(f"Error resending invitation {invitation_id}: {e}")
            return False
    
    @staticmethod
    def create_bulk_invitations(emails, role, invited_by, expiration_days=7, personal_message=""):
        """
        Create multiple invitations at once.
        
        Args:
            emails (list): List of email addresses
            role (Role): Role to assign to all invitations
            invited_by (User): User creating the invitations
            expiration_days (int): Days until expiration
            personal_message (str): Optional personal message
            
        Returns:
            dict: Results with successful and failed invitations
        """
        results = {
            'successful': [],
            'failed': [],
            'total_attempted': len(emails)
        }
        
        for email in emails:
            try:
                invitation = InvitationService.create_invitation(
                    email=email,
                    role=role,
                    invited_by=invited_by,
                    expiration_days=expiration_days,
                    personal_message=personal_message
                )
                results['successful'].append({
                    'email': email,
                    'invitation_id': str(invitation.id)
                })
                
            except Exception as e:
                logger.error(f"Failed to create bulk invitation for {email}: {e}")
                results['failed'].append({
                    'email': email,
                    'error': str(e)
                })
        
        logger.info(f"Bulk invitation creation: {len(results['successful'])} successful, {len(results['failed'])} failed")
        return results
    
    @staticmethod
    def send_bulk_invitation_emails(invitation_ids, request):
        """
        Send emails for multiple invitations.
        
        Args:
            invitation_ids (list): List of invitation IDs
            request (HttpRequest): Request object for building URLs
            
        Returns:
            dict: Results with successful and failed email sends
        """
        results = {
            'successful': [],
            'failed': [],
            'total_attempted': len(invitation_ids)
        }
        
        invitations = ProviderInvitation.objects.filter(id__in=invitation_ids)
        
        for invitation in invitations:
            try:
                if InvitationService.send_invitation_email(invitation, request):
                    results['successful'].append({
                        'email': invitation.email,
                        'invitation_id': str(invitation.id)
                    })
                else:
                    results['failed'].append({
                        'email': invitation.email,
                        'invitation_id': str(invitation.id),
                        'error': 'Email sending failed'
                    })
                    
            except Exception as e:
                results['failed'].append({
                    'email': invitation.email,
                    'invitation_id': str(invitation.id),
                    'error': str(e)
                })
        
        logger.info(f"Bulk email sending: {len(results['successful'])} successful, {len(results['failed'])} failed")
        return results
    
    @staticmethod
    def cleanup_expired_invitations():
        """
        Clean up expired invitations by marking them inactive.
        
        Returns:
            int: Number of invitations cleaned up
        """
        try:
            count = ProviderInvitation.cleanup_expired_invitations()
            logger.info(f"Cleaned up {count} expired invitations")
            return count
        except Exception as e:
            logger.error(f"Error during invitation cleanup: {e}")
            return 0
    
    @staticmethod
    def cleanup_expired_invitations_for_email(email):
        """
        Clean up expired invitations for a specific email address.
        
        Args:
            email (str): Email address to clean up
            
        Returns:
            int: Number of invitations cleaned up
        """
        try:
            expired_invitations = ProviderInvitation.objects.filter(
                email=email.lower().strip(),
                is_active=True,
                accepted_at__isnull=True,
                expires_at__lte=timezone.now()
            )
            
            count = expired_invitations.count()
            if count > 0:
                expired_invitations.update(is_active=False)
                logger.info(f"Cleaned up {count} expired invitations for {email}")
            
            return count
            
        except Exception as e:
            logger.error(f"Error cleaning up invitations for {email}: {e}")
            return 0
    
    @staticmethod
    def get_invitation_statistics():
        """
        Get statistics about invitations.
        
        Returns:
            dict: Statistics about invitations
        """
        try:
            total_invitations = ProviderInvitation.objects.count()
            active_invitations = ProviderInvitation.get_active_invitations().count()
            accepted_invitations = ProviderInvitation.objects.filter(
                accepted_at__isnull=False
            ).count()
            expired_invitations = ProviderInvitation.objects.filter(
                is_active=True,
                accepted_at__isnull=True,
                expires_at__lte=timezone.now()
            ).count()
            revoked_invitations = ProviderInvitation.objects.filter(
                is_active=False,
                accepted_at__isnull=True
            ).count()
            
            return {
                'total': total_invitations,
                'active': active_invitations,
                'accepted': accepted_invitations,
                'expired': expired_invitations,
                'revoked': revoked_invitations,
                'acceptance_rate': (accepted_invitations / total_invitations * 100) if total_invitations > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting invitation statistics: {e}")
            return {
                'total': 0,
                'active': 0,
                'accepted': 0,
                'expired': 0,
                'revoked': 0,
                'acceptance_rate': 0
            }


class UserManagementService:
    """
    Service class for user management operations.
    
    Provides business logic for user profile management, role assignments,
    and user-related operations.
    """
    
    @staticmethod
    def create_user_from_invitation(invitation, user_data):
        """
        Create a user account from an invitation.
        
        Args:
            invitation (ProviderInvitation): The invitation being accepted
            user_data (dict): User data from registration form
            
        Returns:
            User: Created user instance
        """
        try:
            with transaction.atomic():
                # Create user
                user = User.objects.create_user(
                    username=user_data['email'],
                    email=user_data['email'],
                    first_name=user_data.get('first_name', ''),
                    last_name=user_data.get('last_name', ''),
                    password=user_data['password']
                )
                
                # Accept invitation (creates profile and assigns role)
                if not InvitationService.accept_invitation(invitation, user):
                    # If invitation acceptance fails, delete the user
                    user.delete()
                    raise Exception("Failed to accept invitation")
                
                logger.info(f"Created user {user.email} from invitation {invitation.id}")
                return user
                
        except Exception as e:
            logger.error(f"Failed to create user from invitation {invitation.id}: {e}")
            raise
    
    @staticmethod
    def get_user_profile_with_roles(user):
        """
        Get user profile with roles information.
        
        Args:
            user (User): User instance
            
        Returns:
            dict: User profile information with roles
        """
        try:
            profile, created = UserProfile.objects.get_or_create(user=user)
            
            return {
                'user': user,
                'profile': profile,
                'roles': list(profile.roles.all()),
                'role_names': profile.get_role_names(),
                'display_roles': profile.get_display_roles(),
                'can_access_phi': profile.can_access_phi(),
                'is_locked': profile.is_account_locked(),
                'permissions': profile.get_all_permissions(),
            }
            
        except Exception as e:
            logger.error(f"Error getting profile for user {user.email}: {e}")
            return None
    
    @staticmethod
    def assign_role_to_user(user, role_name, assigned_by):
        """
        Assign a role to a user.
        
        Args:
            user (User): User to assign role to
            role_name (str): Name of the role to assign
            assigned_by (User): User performing the assignment
            
        Returns:
            bool: True if role was assigned successfully
        """
        try:
            profile, created = UserProfile.objects.get_or_create(user=user)
            
            if profile.add_role(role_name):
                logger.info(f"Assigned role '{role_name}' to user {user.email} by {assigned_by.email}")
                return True
            else:
                logger.info(f"User {user.email} already has role '{role_name}'")
                return False
                
        except Exception as e:
            logger.error(f"Error assigning role '{role_name}' to user {user.email}: {e}")
            return False
    
    @staticmethod
    def remove_role_from_user(user, role_name, removed_by):
        """
        Remove a role from a user.
        
        Args:
            user (User): User to remove role from
            role_name (str): Name of the role to remove
            removed_by (User): User performing the removal
            
        Returns:
            bool: True if role was removed successfully
        """
        try:
            profile, created = UserProfile.objects.get_or_create(user=user)
            
            if profile.remove_role(role_name):
                logger.info(f"Removed role '{role_name}' from user {user.email} by {removed_by.email}")
                return True
            else:
                logger.info(f"User {user.email} does not have role '{role_name}'")
                return False
                
        except Exception as e:
            logger.error(f"Error removing role '{role_name}' from user {user.email}: {e}")
            return False
