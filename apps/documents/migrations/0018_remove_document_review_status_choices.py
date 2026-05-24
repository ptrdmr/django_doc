# Generated manually for review UI purge

from django.db import migrations, models


def convert_review_documents_to_completed(apps, schema_editor):
    """Convert legacy review statuses to completed before removing choices."""
    Document = apps.get_model('documents', 'Document')
    Document.objects.filter(status__in=['review', 'requires_review']).update(status='completed')


class Migration(migrations.Migration):

    dependencies = [
        ('documents', '0017_document_status_choices_ocr_and_review'),
    ]

    operations = [
        migrations.RunPython(
            convert_review_documents_to_completed,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='document',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending Processing'),
                    ('processing', 'Processing'),
                    ('ocr_pending', 'OCR Pending'),
                    ('completed', 'Completed'),
                    ('failed', 'Processing Failed'),
                ],
                db_index=True,
                default='pending',
                help_text='Current processing status',
                max_length=25,
            ),
        ),
    ]
