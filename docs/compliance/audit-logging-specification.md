# Audit Logging Specification

## Document Information

| Field | Value |
|-------|-------|
| Document Title | HIPAA Audit Logging Specification |
| Version | 1.0 |
| Classification | Confidential |
| Last Updated | 2026-01-01 |
| Review Cycle | Annual |

---

## Executive Summary

This document specifies the audit logging capabilities of the Medical Document Parser in compliance with HIPAA Security Rule §164.312(b) (Audit Controls). The system maintains comprehensive audit trails for all PHI access and system activities.

---

## 1. Audit Log Requirements

### 1.1 HIPAA Audit Control Requirements

| Requirement | Implementation Status |
|-------------|----------------------|
| Record and examine activity in systems containing ePHI | ✅ Implemented |
| Hardware-level audit trails | ✅ Via infrastructure logging |
| Software-level audit trails | ✅ Application audit logging |
| Procedural mechanisms for monitoring | ✅ Log review procedures |

### 1.2 Logged Event Categories

| Category | Description | Examples |
|----------|-------------|----------|
| Authentication | User access attempts | Login, logout, failed attempts |
| PHI Access | Patient data access | View, search, export |
| Data Modification | Changes to records | Create, update, delete |
| Administrative | System administration | User management, config changes |
| Security | Security-related events | Password changes, lockouts |

---

## 2. Audit Log Schema

### 2.1 Standard Audit Log Entry

Each audit log entry contains the following fields:

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `id` | UUID | Unique identifier | `550e8400-e29b-...` |
| `timestamp` | DateTime | Event time (UTC) | `2026-01-01T22:59:01Z` |
| `event_type` | String | Category of event | `patient_view` |
| `user_id` | UUID | Acting user identifier | `7c9e6679-...` |
| `user_email` | String | User email (for reference) | `user@example.com` |
| `ip_address` | String | Source IP address | `192.168.1.100` |
| `user_agent` | String | Browser/client info | `Mozilla/5.0...` |
| `resource_type` | String | Type of resource accessed | `Patient` |
| `resource_id` | String | Identifier of resource | `patient-123` |
| `action` | String | Specific action taken | `view` |
| `description` | Text | Human-readable description | `Viewed patient John D.` |
| `phi_involved` | Boolean | Whether PHI was accessed | `true` |
| `success` | Boolean | Whether action succeeded | `true` |
| `metadata` | JSON | Additional context | `{"search_query": "..."}` |

### 2.2 Sample Log Entry (Anonymized)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2026-01-01T22:59:01.000Z",
  "event_type": "patient_view",
  "user_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "user_email": "clinician@hospital.org",
  "ip_address": "10.0.0.50",
  "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
  "resource_type": "Patient",
  "resource_id": "patient-abc123",
  "action": "view",
  "description": "Viewed patient record",
  "phi_involved": true,
  "success": true,
  "metadata": {
    "view_type": "detail",
    "fields_accessed": ["demographics", "conditions"]
  }
}
```

---

## 3. Event Types

### 3.1 Authentication Events

| Event Type | Trigger | PHI Flag |
|------------|---------|----------|
| `login` | Successful user login | No |
| `login_failed` | Failed login attempt | No |
| `logout` | User logout | No |
| `session_expired` | Session timeout | No |
| `account_locked` | Account lockout triggered | No |
| `password_changed` | Password update | No |
| `mfa_enrolled` | MFA device registered | No |
| `mfa_verified` | MFA verification successful | No |

### 3.2 PHI Access Events

| Event Type | Trigger | PHI Flag |
|------------|---------|----------|
| `patient_view` | Patient record accessed | Yes |
| `patient_create` | New patient created | Yes |
| `patient_update` | Patient record modified | Yes |
| `patient_search` | Patient search performed | Yes |
| `patient_list` | Patient list viewed | Yes |
| `fhir_export` | FHIR data exported | Yes |
| `fhir_access` | FHIR bundle accessed | Yes |

### 3.3 Document Events

| Event Type | Trigger | PHI Flag |
|------------|---------|----------|
| `document_upload` | Document uploaded | Yes |
| `document_view` | Document viewed | Yes |
| `document_download` | Document downloaded | Yes |
| `document_process` | Document processing started | Yes |
| `document_delete` | Document deleted (soft) | Yes |

### 3.4 Administrative Events

| Event Type | Trigger | PHI Flag |
|------------|---------|----------|
| `user_create` | New user created | No |
| `user_update` | User profile updated | No |
| `user_deactivate` | User account disabled | No |
| `role_change` | User role modified | No |
| `config_change` | System configuration changed | No |
| `report_generated` | Compliance report created | Depends |

### 3.5 Security Events

| Event Type | Trigger | PHI Flag |
|------------|---------|----------|
| `access_denied` | Unauthorized access attempt | Depends |
| `csrf_failure` | CSRF validation failed | No |
| `rate_limit` | Rate limit exceeded | No |
| `suspicious_activity` | Anomaly detected | Depends |

---

## 4. Log Storage and Retention

### 4.1 Storage Configuration

| Aspect | Specification |
|--------|---------------|
| Storage Location | Database (PostgreSQL) |
| Backup Frequency | Daily with database backup |
| Encryption | At rest (database encryption) |
| Access Control | Admin role only |

### 4.2 Retention Policy

| Log Type | Retention Period | Justification |
|----------|-----------------|---------------|
| PHI Access Logs | 6 years | HIPAA minimum requirement |
| Authentication Logs | 6 years | Security best practice |
| Administrative Logs | 6 years | Compliance requirement |
| Security Events | 6 years | Incident investigation |
| Application Errors | 1 year | Operational needs |

### 4.3 Log Immutability

| Control | Implementation |
|---------|---------------|
| No Delete Capability | Logs cannot be deleted via application |
| No Modification | Log entries are append-only |
| Timestamp Integrity | Server-side timestamps only |
| Chain of Custody | Database-level protections |

---

## 5. Log Access and Review

### 5.1 Access Controls

| Role | Permissions |
|------|-------------|
| Standard User | No audit log access |
| Clinical Staff | View own activity |
| Administrator | View all logs, generate reports |
| Security Officer | Full access, export capability |

### 5.2 Review Schedule

| Review Type | Frequency | Responsibility |
|-------------|-----------|----------------|
| Security Incident Review | Real-time | Security Team |
| Failed Login Analysis | Daily | Security Team |
| PHI Access Review | Weekly | Privacy Officer |
| Full Audit Review | Monthly | Compliance Team |
| Compliance Report | Quarterly | Security Officer |

### 5.3 Review Procedures

1. **Daily Review**
   - Check for failed login patterns
   - Review access denied events
   - Monitor for anomalous activity

2. **Weekly Review**
   - Analyze PHI access patterns
   - Verify legitimate access
   - Review new user activity

3. **Monthly Review**
   - Comprehensive log analysis
   - Generate compliance metrics
   - Document findings

---

## 6. Alerting and Monitoring

### 6.1 Real-Time Alerts

| Alert Condition | Threshold | Response |
|-----------------|-----------|----------|
| Multiple failed logins | 5 in 5 minutes | Account lockout |
| After-hours PHI access | Any | Review next business day |
| Bulk data export | >100 records | Immediate review |
| Admin action | Any | Logged for review |

### 6.2 Monitoring Metrics

| Metric | Normal Range | Alert Threshold |
|--------|--------------|-----------------|
| Login failures/day | <10 | >50 |
| PHI accesses/user/day | 10-100 | >500 |
| Export events/week | <20 | >100 |

---

## 7. Compliance Reporting

### 7.1 Standard Reports

| Report | Frequency | Contents |
|--------|-----------|----------|
| Access Summary | Monthly | PHI access by user |
| Security Events | Monthly | Auth failures, lockouts |
| User Activity | Quarterly | Full user audit trail |
| Compliance Summary | Quarterly | Overall metrics |

### 7.2 Report Format

Reports are generated in the following formats:
- PDF (for distribution)
- CSV (for analysis)
- JSON (for integration)

### 7.3 Sample Report Structure

```
HIPAA AUDIT REPORT
Period: 2026-01-01 to 2026-01-31

SUMMARY
- Total PHI accesses: 1,234
- Unique users accessing PHI: 15
- Failed login attempts: 23
- Security incidents: 0

PHI ACCESS BY USER
| User | Accesses | Last Access |
|------|----------|-------------|
| user1@example.com | 156 | 2026-01-31 |
| user2@example.com | 89 | 2026-01-30 |
...

SECURITY EVENTS
- Account lockouts: 2
- CSRF failures: 0
- Access denied: 5
```

---

## 8. Integration Capabilities

### 8.1 Log Export

| Format | Availability |
|--------|-------------|
| Syslog | Configurable |
| JSON over HTTPS | API endpoint |
| CSV Export | Admin interface |

### 8.2 SIEM Integration

The audit logging system supports integration with Security Information and Event Management (SIEM) systems via:
- Syslog forwarding
- API-based export
- Webhook notifications

---

## 9. Privacy Considerations

### 9.1 Log Sanitization

| Data Element | Treatment |
|--------------|-----------|
| Patient Names | Partial masking in descriptions |
| SSN | Never logged |
| Full PHI | Not stored in logs |
| Search Queries | Logged for audit |

### 9.2 Log Access Auditing

Access to audit logs is itself audited:
- Who accessed logs
- When logs were accessed
- What query/filter was used
- Export activities

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-01 | Security Team | Initial specification |

---

*This document is confidential and intended for authorized recipients only.*

*Updated: 2026-01-01 22:59:01 | Initial audit logging specification*

