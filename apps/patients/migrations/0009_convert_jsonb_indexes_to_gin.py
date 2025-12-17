# Generated manually for Task: Fix JSONB index size limit issue
# Migration to convert B-tree indexes to GIN indexes for JSONB fields
# 
# Problem: B-tree indexes have a row size limit of ~2704 bytes, which is
# exceeded when searchable_medical_codes grows large with many FHIR resources.
#
# Solution: GIN (Generalized Inverted Index) indexes are designed for JSONB
# and have no such size limitations.

from django.db import migrations
from django.contrib.postgres.indexes import GinIndex


class Migration(migrations.Migration):

    dependencies = [
        ('patients', '0008_patient_living_setting_patient_primary_condition_id'),
    ]

    operations = [
        # Drop the old B-tree indexes that have size limitations
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS idx_medical_codes;',
            reverse_sql='CREATE INDEX idx_medical_codes ON patients USING btree (searchable_medical_codes);',
        ),
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS idx_encounter_dates;',
            reverse_sql='CREATE INDEX idx_encounter_dates ON patients USING btree (encounter_dates);',
        ),
        migrations.RunSQL(
            sql='DROP INDEX IF EXISTS idx_provider_refs;',
            reverse_sql='CREATE INDEX idx_provider_refs ON patients USING btree (provider_references);',
        ),
        
        # Create GIN indexes which are better suited for JSONB fields
        # Using jsonb_path_ops for more efficient containment queries (@>)
        migrations.RunSQL(
            sql='CREATE INDEX idx_medical_codes_gin ON patients USING gin (searchable_medical_codes jsonb_path_ops);',
            reverse_sql='DROP INDEX IF EXISTS idx_medical_codes_gin;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX idx_encounter_dates_gin ON patients USING gin (encounter_dates jsonb_path_ops);',
            reverse_sql='DROP INDEX IF EXISTS idx_encounter_dates_gin;',
        ),
        migrations.RunSQL(
            sql='CREATE INDEX idx_provider_refs_gin ON patients USING gin (provider_references jsonb_path_ops);',
            reverse_sql='DROP INDEX IF EXISTS idx_provider_refs_gin;',
        ),
    ]

