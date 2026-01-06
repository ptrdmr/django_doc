# Encryption Standards

## Document Information

| Field | Value |
|-------|-------|
| Document Title | Data Encryption Standards |
| Version | 1.0 |
| Classification | Confidential |
| Last Updated | 2026-01-01 |
| Review Cycle | Annual |

---

## Executive Summary

This document describes the encryption standards and implementation used by the Medical Document Parser to protect electronic Protected Health Information (ePHI) in compliance with HIPAA Security Rule §164.312(a)(2)(iv) and §164.312(e)(2)(ii).

---

## 1. Encryption Overview

### 1.1 Encryption Strategy

The system implements a **hybrid encryption approach** that balances security with operational requirements:

| Data State | Encryption Method | Purpose |
|------------|-------------------|---------|
| At Rest (PHI) | Application-level AES-256 | Protect sensitive data in database |
| At Rest (Files) | Encrypted file storage | Protect uploaded documents |
| In Transit | TLS 1.2+ | Protect data during transmission |
| Backups | AES-256 | Protect backup media |

### 1.2 HIPAA Addressable vs. Required

| Implementation | HIPAA Status | Our Implementation |
|----------------|--------------|-------------------|
| Encryption at rest | Addressable | ✅ Implemented (exceeds requirement) |
| Encryption in transit | Addressable | ✅ Implemented |
| Access controls | Required | ✅ Implemented |

---

## 2. Encryption at Rest

### 2.1 PHI Field Encryption

**Algorithm:** Fernet symmetric encryption
- Based on AES-128 in CBC mode
- HMAC using SHA256 for authentication
- Authenticated encryption (encrypt-then-MAC)

**Protected Data Elements:**

| Field | Encryption | Justification |
|-------|------------|---------------|
| Patient First Name | ✅ Encrypted | PHI identifier |
| Patient Last Name | ✅ Encrypted | PHI identifier |
| Date of Birth | ✅ Encrypted | PHI identifier |
| Social Security Number | ✅ Encrypted | PHI identifier |
| Address | ✅ Encrypted | PHI identifier |
| Phone Number | ✅ Encrypted | PHI identifier |
| Email | ✅ Encrypted | PHI identifier |
| Medical Records (FHIR) | ✅ Encrypted | PHI content |
| Document Content | ✅ Encrypted | PHI content |
| Review Notes | ✅ Encrypted | May contain PHI |

### 2.2 Encryption Implementation Details

| Aspect | Specification |
|--------|---------------|
| Library | django-cryptography (Fernet) |
| Key Size | 256-bit (Fernet specification) |
| Mode | CBC with PKCS7 padding |
| Authentication | HMAC-SHA256 |
| IV Generation | Cryptographically random per encryption |

### 2.3 Non-Encrypted Data (Performance Optimization)

Certain data elements are intentionally not encrypted to support efficient database operations:

| Field | Justification | Risk Assessment |
|-------|---------------|-----------------|
| Medical Record Number (MRN) | Unique identifier for lookups | Low PHI risk alone |
| Medical Codes (ICD, SNOMED) | Search optimization | Not PHI without patient context |
| Encounter Dates | Date range searches | Limited PHI value |
| Search Fields (lowercase names) | Fast patient lookup | Minimal risk (documented) |

**Risk Mitigation for Non-Encrypted Fields:**
- Database access restricted to application only
- All access logged in audit trail
- Network encryption (TLS) for all connections
- Data alone insufficient for patient identification

---

## 3. Key Management

### 3.1 Key Storage

| Aspect | Implementation |
|--------|---------------|
| Storage Location | Environment variables |
| Access Control | Server-level only |
| Version Control | Never committed to code repository |
| Documentation | Keys never in documentation |

### 3.2 Key Rotation

| Aspect | Specification |
|--------|---------------|
| Rotation Capability | Supported via key versioning |
| Rotation Frequency | Annual or after suspected compromise |
| Backward Compatibility | Old keys retained for decryption |
| Rotation Procedure | Documented in operational runbooks |

### 3.3 Key Hierarchy

```
┌─────────────────────────────────────────────┐
│           MASTER ENCRYPTION KEY             │
│         (Environment Variable)              │
└─────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────┐
│         FIELD ENCRYPTION KEYS               │
│     (Derived/Configured per purpose)        │
└─────────────────────────────────────────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
     ┌─────────┐ ┌─────────┐ ┌─────────┐
     │ Patient │ │Document │ │  File   │
     │  Data   │ │ Content │ │ Storage │
     └─────────┘ └─────────┘ └─────────┘
```

---

## 4. Encryption in Transit

### 4.1 TLS Configuration

| Setting | Value |
|---------|-------|
| Minimum Version | TLS 1.2 |
| Preferred Version | TLS 1.3 |
| Certificate Type | X.509 (2048-bit RSA or 256-bit ECDSA) |
| Certificate Authority | Trusted public CA |

### 4.2 Cipher Suites

**Allowed Cipher Suites (in order of preference):**

```
TLS_AES_256_GCM_SHA384 (TLS 1.3)
TLS_CHACHA20_POLY1305_SHA256 (TLS 1.3)
TLS_AES_128_GCM_SHA256 (TLS 1.3)
ECDHE-RSA-AES256-GCM-SHA384 (TLS 1.2)
ECDHE-RSA-AES128-GCM-SHA256 (TLS 1.2)
```

**Disabled:**
- SSLv2, SSLv3, TLS 1.0, TLS 1.1
- RC4, DES, 3DES, MD5-based MACs
- Export-grade ciphers
- NULL ciphers

### 4.3 HTTPS Enforcement

| Control | Setting |
|---------|---------|
| HTTP Redirect | Automatic redirect to HTTPS |
| HSTS | Enabled (1 year, includeSubDomains) |
| Preload | Ready for HSTS preload list |
| Secure Cookies | Enforced |

### 4.4 Internal Communications

| Connection | Encryption |
|------------|------------|
| Application to Database | TLS encrypted |
| Application to Redis | TLS encrypted (production) |
| Application to AI Services | HTTPS |
| Application to Email Service | TLS/STARTTLS |

---

## 5. Backup Encryption

### 5.1 Database Backups

| Aspect | Specification |
|--------|---------------|
| Encryption Algorithm | AES-256 |
| Key Management | Separate backup encryption keys |
| Storage | Encrypted at infrastructure level |

### 5.2 File Backups

| Aspect | Specification |
|--------|---------------|
| Encryption | Same as source files (already encrypted) |
| Additional Layer | Infrastructure encryption |
| Access Control | Restricted to backup operators |

---

## 6. Cryptographic Best Practices

### 6.1 Random Number Generation

| Use Case | Source |
|----------|--------|
| Encryption IVs | `os.urandom()` (CSPRNG) |
| Token Generation | `secrets` module |
| Session IDs | Django's cryptographic backend |

### 6.2 Password Hashing

| Aspect | Specification |
|--------|---------------|
| Algorithm | Argon2 (winner of PHC) |
| Fallback | PBKDF2-SHA256 |
| Work Factor | Tuned for ~250ms on target hardware |
| Salt | Unique per password |

### 6.3 Avoided Cryptographic Practices

| Practice | Status |
|----------|--------|
| Custom encryption algorithms | ❌ Prohibited |
| ECB mode | ❌ Prohibited |
| MD5/SHA1 for security | ❌ Prohibited |
| Hardcoded keys | ❌ Prohibited |
| Weak key derivation | ❌ Prohibited |

---

## 7. Compliance Mapping

### 7.1 HIPAA Security Rule

| Requirement | Section | Implementation |
|-------------|---------|---------------|
| §164.312(a)(2)(iv) | Encryption and decryption | Section 2, 4 |
| §164.312(e)(2)(ii) | Encryption (transmission) | Section 4 |
| §164.308(a)(1)(ii)(D) | Encryption risk assessment | Section 2.3 |

### 7.2 Industry Standards

| Standard | Compliance |
|----------|------------|
| NIST SP 800-111 | Storage encryption guidance followed |
| NIST SP 800-52 | TLS guidelines followed |
| FIPS 140-2 | Algorithms are FIPS-approved |

---

## 8. Verification and Testing

### 8.1 Encryption Verification

Regular verification includes:
- Database inspection confirms encrypted storage
- Network traffic analysis confirms TLS
- Key rotation testing
- Decryption verification

### 8.2 Audit Queries

Sample verification queries are maintained for:
- Confirming PHI fields are encrypted in database
- Verifying no plaintext PHI exposure
- Checking encryption consistency

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-01 | Security Team | Initial standards document |

---

*This document is confidential and intended for authorized recipients only.*

*Updated: 2026-01-01 22:59:01 | Initial encryption standards documentation*

