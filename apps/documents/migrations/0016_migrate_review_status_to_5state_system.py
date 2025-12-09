# Generated manually for Task 41.16 on 2025-12-09
"""
Data migration to convert existing ParsedData records from the old 4-state
review system to the new 5-state optimistic concurrency system.

Old States → New States Mapping:
- 'approved' → 'reviewed' (manual human approval)
- 'pending' → 'pending' (no change)
- 'flagged' → 'flagged' (no change)
- 'rejected' → 'rejected' (no change)

Additionally sets auto_approved field based on the migration logic:
- Records that were manually 'approved' → auto_approved=False (human reviewed)
- Records that were 'pending' → auto_approved=False (not yet approved)
- Records that were 'flagged' → auto_approved=False (needs review)
- Records that were 'rejected' → auto_approved=False (rejected)
"""

from django.db import migrations


def migrate_review_statuses_forward(apps, schema_editor):
    """
    Migrate existing ParsedData records to the new 5-state system.
    
    This is the forward migration that updates existing records.
    """
    ParsedData = apps.get_model('documents', 'ParsedData')
    
    # Get database alias for this migration
    db_alias = schema_editor.connection.alias
    
    # Count records before migration for logging
    total_records = ParsedData.objects.using(db_alias).count()
    
    if total_records == 0:
        # No records to migrate - fresh database
        print("  No ParsedData records found. Skipping migration.")
        return
    
    print(f"  Migrating {total_records} ParsedData records to new 5-state system...")
    
    # Track migration statistics
    stats = {
        'approved_to_reviewed': 0,
        'pending_unchanged': 0,
        'flagged_unchanged': 0,
        'rejected_unchanged': 0,
        'unknown_status': 0,
    }
    
    # Migrate 'approved' → 'reviewed'
    # These were manually approved by humans in the old system
    approved_records = ParsedData.objects.using(db_alias).filter(review_status='approved')
    approved_count = approved_records.count()
    
    if approved_count > 0:
        approved_records.update(
            review_status='reviewed',
            auto_approved=False,  # These were manually approved, not auto-approved
        )
        stats['approved_to_reviewed'] = approved_count
        print(f"    ✓ Migrated {approved_count} 'approved' records to 'reviewed' (auto_approved=False)")
    
    # Ensure 'pending' records have auto_approved=False
    pending_records = ParsedData.objects.using(db_alias).filter(review_status='pending')
    pending_count = pending_records.count()
    
    if pending_count > 0:
        # Update auto_approved to False for consistency (should already be False, but being explicit)
        pending_records.update(auto_approved=False)
        stats['pending_unchanged'] = pending_count
        print(f"    ✓ Verified {pending_count} 'pending' records (auto_approved=False)")
    
    # Ensure 'flagged' records have auto_approved=False
    flagged_records = ParsedData.objects.using(db_alias).filter(review_status='flagged')
    flagged_count = flagged_records.count()
    
    if flagged_count > 0:
        flagged_records.update(auto_approved=False)
        stats['flagged_unchanged'] = flagged_count
        print(f"    ✓ Verified {flagged_count} 'flagged' records (auto_approved=False)")
    
    # Ensure 'rejected' records have auto_approved=False
    rejected_records = ParsedData.objects.using(db_alias).filter(review_status='rejected')
    rejected_count = rejected_records.count()
    
    if rejected_count > 0:
        rejected_records.update(auto_approved=False)
        stats['rejected_unchanged'] = rejected_count
        print(f"    ✓ Verified {rejected_count} 'rejected' records (auto_approved=False)")
    
    # Check for any unexpected statuses (should not happen, but good to verify)
    known_statuses = ['approved', 'pending', 'flagged', 'rejected', 'reviewed', 'auto_approved']
    unknown_records = ParsedData.objects.using(db_alias).exclude(
        review_status__in=known_statuses
    )
    unknown_count = unknown_records.count()
    
    if unknown_count > 0:
        # Log warning but don't fail migration
        stats['unknown_status'] = unknown_count
        print(f"    ⚠ Warning: Found {unknown_count} records with unexpected status values")
        for record in unknown_records[:5]:  # Show first 5 examples
            print(f"      - ParsedData ID {record.id}: review_status='{record.review_status}'")
    
    # Final summary
    print(f"  Migration complete! Summary:")
    print(f"    - Total records: {total_records}")
    print(f"    - 'approved' → 'reviewed': {stats['approved_to_reviewed']}")
    print(f"    - 'pending' (unchanged): {stats['pending_unchanged']}")
    print(f"    - 'flagged' (unchanged): {stats['flagged_unchanged']}")
    print(f"    - 'rejected' (unchanged): {stats['rejected_unchanged']}")
    if stats['unknown_status'] > 0:
        print(f"    - Unknown status: {stats['unknown_status']} (manual review recommended)")


def migrate_review_statuses_backward(apps, schema_editor):
    """
    Reverse migration to restore old 4-state system.
    
    This is the backward migration in case we need to rollback.
    """
    ParsedData = apps.get_model('documents', 'ParsedData')
    
    # Get database alias for this migration
    db_alias = schema_editor.connection.alias
    
    # Count records before migration for logging
    total_records = ParsedData.objects.using(db_alias).count()
    
    if total_records == 0:
        print("  No ParsedData records found. Skipping reverse migration.")
        return
    
    print(f"  Reversing migration for {total_records} ParsedData records...")
    
    # Migrate 'reviewed' → 'approved' (reverse of forward migration)
    reviewed_records = ParsedData.objects.using(db_alias).filter(review_status='reviewed')
    reviewed_count = reviewed_records.count()
    
    if reviewed_count > 0:
        reviewed_records.update(review_status='approved')
        print(f"    ✓ Reverted {reviewed_count} 'reviewed' records to 'approved'")
    
    # Migrate 'auto_approved' → 'approved' (both were approved in old system)
    auto_approved_records = ParsedData.objects.using(db_alias).filter(review_status='auto_approved')
    auto_approved_count = auto_approved_records.count()
    
    if auto_approved_count > 0:
        auto_approved_records.update(review_status='approved')
        print(f"    ✓ Reverted {auto_approved_count} 'auto_approved' records to 'approved'")
    
    print(f"  Reverse migration complete!")


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0015_add_review_status_created_index'),
    ]

    operations = [
        migrations.RunPython(
            migrate_review_statuses_forward,
            reverse_code=migrate_review_statuses_backward,
        ),
    ]

