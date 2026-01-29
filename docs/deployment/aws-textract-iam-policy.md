# AWS IAM Policy for Textract OCR Integration

**Version:** 1.0  
**Created:** 2026-01-29  
**Task:** 42.3 - Create IAM policy for Textract and S3

---

## Overview

This document provides the IAM policy required for the AWS Textract OCR integration. The policy grants permissions for:

1. **Amazon Textract** - Document analysis (sync and async modes)
2. **Amazon S3** - Temporary file storage for async OCR processing

---

## IAM Policy Document

### Policy Name: `MeddocparserTextractOCRPolicy`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TextractDocumentAnalysis",
      "Effect": "Allow",
      "Action": [
        "textract:AnalyzeDocument",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3OCRBucketObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-*/*"
    },
    {
      "Sid": "S3OCRBucketListAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-*"
    }
  ]
}
```

---

## Permission Details

### Textract Permissions

| Permission | Purpose | Sync/Async |
|------------|---------|------------|
| `textract:AnalyzeDocument` | Direct document analysis for files <5MB | Sync |
| `textract:StartDocumentAnalysis` | Initiate async job for files >=5MB | Async |
| `textract:GetDocumentAnalysis` | Retrieve results from async jobs | Async |

**Note:** Textract permissions use `Resource: "*"` because Textract does not support resource-level permissions for these actions.

### S3 Permissions

| Permission | Purpose |
|------------|---------|
| `s3:PutObject` | Upload documents to S3 for async Textract processing |
| `s3:GetObject` | Retrieve documents (required by Textract for async jobs) |
| `s3:DeleteObject` | Clean up temp files after OCR completes |
| `s3:ListBucket` | List bucket contents (required for bucket operations) |

**Resource Pattern:** `arn:aws:s3:::meddocparser-ocr-temp-*` supports multiple environments:
- `meddocparser-ocr-temp-dev`
- `meddocparser-ocr-temp-staging`
- `meddocparser-ocr-temp-prod`

---

## Deployment Instructions

### Option A: Production - Attach to EC2/ECS Role (Recommended)

For production deployments, attach this policy to the IAM role used by your EC2 instance or ECS task.

1. **Navigate to IAM Console:** https://console.aws.amazon.com/iam/

2. **Create the Policy:**
   - Go to **Policies** → **Create policy**
   - Select **JSON** tab
   - Paste the policy document above
   - Name: `MeddocparserTextractOCRPolicy`
   - Description: "Grants Textract OCR and S3 temp bucket access for medical document processing"
   - Click **Create policy**

3. **Attach to Instance/Task Role:**
   - Go to **Roles**
   - Find your EC2 instance role or ECS task execution role
   - Click **Add permissions** → **Attach policies**
   - Search for `MeddocparserTextractOCRPolicy`
   - Click **Attach policy**

4. **Verify:** No code changes needed - boto3 automatically uses the instance role.

### Option B: Local Development - Create IAM User

For local development, create an IAM user with programmatic access.

1. **Create IAM User:**
   - Go to **Users** → **Create user**
   - Name: `meddocparser-dev-textract`
   - Check "Provide user access to the AWS Management Console" (optional)
   - Click **Next**

2. **Attach Policy:**
   - Select **Attach policies directly**
   - Search for `MeddocparserTextractOCRPolicy`
   - Click **Next** → **Create user**

3. **Generate Access Keys:**
   - Click on the new user
   - Go to **Security credentials** tab
   - Click **Create access key**
   - Select **Local code** use case
   - Download or copy the Access Key ID and Secret Access Key

4. **Configure Local Environment:**

   Add to your `.env` file:
   ```bash
   # AWS Credentials for Textract OCR
   AWS_ACCESS_KEY_ID=AKIA...your_access_key
   AWS_SECRET_ACCESS_KEY=...your_secret_key
   AWS_DEFAULT_REGION=us-east-1
   
   # S3 OCR Bucket
   OCR_S3_BUCKET=meddocparser-ocr-temp-dev
   ```

---

## Environment-Specific Bucket ARNs

If you need stricter resource constraints, use environment-specific policies:

### Development Policy (Restrictive)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TextractDocumentAnalysis",
      "Effect": "Allow",
      "Action": [
        "textract:AnalyzeDocument",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3OCRBucketObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-dev/*"
    },
    {
      "Sid": "S3OCRBucketListAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-dev"
    }
  ]
}
```

### Production Policy (Restrictive)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TextractDocumentAnalysis",
      "Effect": "Allow",
      "Action": [
        "textract:AnalyzeDocument",
        "textract:StartDocumentAnalysis",
        "textract:GetDocumentAnalysis"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3OCRBucketObjectAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-prod/*"
    },
    {
      "Sid": "S3OCRBucketListAccess",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket"
      ],
      "Resource": "arn:aws:s3:::meddocparser-ocr-temp-prod"
    }
  ]
}
```

---

## Verification

After attaching the policy, verify permissions work correctly:

### From Django Shell (Local Dev)

```python
import boto3
from django.conf import settings

# Test Textract access
textract = boto3.client(
    'textract',
    region_name=settings.AWS_DEFAULT_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
)

# This should NOT raise AccessDeniedException
# (Will raise InvalidParameterType with empty bytes, which is expected)
try:
    textract.analyze_document(
        Document={'Bytes': b'test'},
        FeatureTypes=['TABLES', 'FORMS']
    )
except Exception as e:
    print(f"Expected error (not AccessDenied): {type(e).__name__}")

# Test S3 access
s3 = boto3.client(
    's3',
    region_name=settings.AWS_DEFAULT_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
)

# This should succeed if bucket exists
try:
    response = s3.list_objects_v2(
        Bucket=settings.OCR_S3_BUCKET,
        MaxKeys=1
    )
    print(f"S3 access verified: {settings.OCR_S3_BUCKET}")
except Exception as e:
    print(f"S3 error: {type(e).__name__}: {e}")
```

### From EC2/ECS (Production)

```python
import boto3

# No credentials needed - uses instance role automatically
textract = boto3.client('textract', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')

# Run same verification tests as above
```

---

## Security Considerations

### HIPAA Compliance

- **Least Privilege:** Policy grants only the minimum permissions needed
- **Resource Constraints:** S3 access limited to specific bucket pattern
- **No Wildcard S3:** Object operations restricted to OCR temp bucket only
- **Audit Trail:** All Textract/S3 operations logged via CloudTrail

### Credential Security

- **Production:** Use IAM roles (no static credentials)
- **Development:** Rotate access keys regularly
- **Never Commit:** AWS credentials must never be committed to version control
- **Environment Variables:** Use `.env` file (gitignored) for local credentials

---

## Related Documentation

- [AWS Textract IAM Documentation](https://docs.aws.amazon.com/textract/latest/dg/security-iam.html)
- [S3 Bucket Lifecycle Configuration](./aws-s3-ocr-bucket-setup.md) (Task 42.2)
- [AWS OCR Upgrade PRD](../../.taskmaster/docs/aws-ocr-upgrade.md)

---

## Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-29 | Initial policy document (Task 42.3) |
