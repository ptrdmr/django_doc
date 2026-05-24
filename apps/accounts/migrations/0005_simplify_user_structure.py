# Migration to simplify user structure: drop Role, ProviderInvitation,
# and remove fields from UserProfile that are no longer needed.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_add_provider_invitation_model'),
    ]

    operations = [
        # 1. Remove M2M 'roles' field from UserProfile (drops the join table)
        migrations.RemoveField(
            model_name='userprofile',
            name='roles',
        ),
        # 2. Remove fields no longer in the simplified UserProfile
        migrations.RemoveField(
            model_name='userprofile',
            name='allowed_ip_ranges',
        ),
        migrations.RemoveField(
            model_name='userprofile',
            name='require_mfa',
        ),
        # 3. Drop ProviderInvitation model (has FK to Role, must go before Role)
        migrations.DeleteModel(
            name='ProviderInvitation',
        ),
        # 4. Drop Role model
        migrations.DeleteModel(
            name='Role',
        ),
    ]
