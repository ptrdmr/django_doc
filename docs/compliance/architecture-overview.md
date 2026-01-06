# System Architecture Overview

## Document Information

| Field | Value |
|-------|-------|
| Document Title | System Architecture Overview |
| Version | 1.0 |
| Classification | Confidential |
| Last Updated | 2026-01-01 |
| Review Cycle | Annual |

---

## Executive Summary

The Medical Document Parser is a healthcare SaaS application designed to transform unstructured medical documents into structured, FHIR-compliant patient records. This document provides an architectural overview suitable for security assessments and compliance reviews.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INTERNET                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (TLS 1.2+)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LOAD BALANCER / WAF                          │
│                   (SSL Termination)                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    APPLICATION TIER                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              WEB APPLICATION (Django)                    │   │
│  │  • Authentication & Session Management                   │   │
│  │  • Role-Based Access Control                            │   │
│  │  • PHI Encryption/Decryption                            │   │
│  │  • Audit Logging                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │            ASYNC PROCESSING (Celery + Redis)            │   │
│  │  • Document Processing Queue                             │   │
│  │  • AI/ML Integration                                     │   │
│  │  • Background Tasks                                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ TLS Encrypted
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      DATA TIER                                   │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │   PostgreSQL DB     │    │   File Storage      │            │
│  │                     │    │                     │            │
│  │ • PHI Fields:       │    │ • Encrypted Files   │            │
│  │   Encrypted at      │    │ • Access Controlled │            │
│  │   Application Layer │    │ • Audit Logged      │            │
│  │                     │    │                     │            │
│  │ • Search Fields:    │    │                     │            │
│  │   Optimized Indexes │    │                     │            │
│  └─────────────────────┘    └─────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                             │
│  ┌─────────────────────┐    ┌─────────────────────┐            │
│  │   AI/ML Services    │    │   Email Service     │            │
│  │                     │    │                     │            │
│  │ • Document Analysis │    │ • Notifications     │            │
│  │ • Data Extraction   │    │ • Verification      │            │
│  │ • FHIR Mapping      │    │                     │            │
│  └─────────────────────┘    └─────────────────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow

### 2.1 Document Upload Flow

```
User                 Application              Storage              Database
  │                      │                       │                    │
  │──── Upload PDF ─────►│                       │                    │
  │                      │                       │                    │
  │                      │── Validate File ─────►│                    │
  │                      │   (Type, Size, Virus) │                    │
  │                      │                       │                    │
  │                      │◄── Validation OK ─────│                    │
  │                      │                       │                    │
  │                      │── Encrypt & Store ───►│                    │
  │                      │                       │                    │
  │                      │── Log Audit Event ────────────────────────►│
  │                      │                       │                    │
  │                      │── Queue Processing ──►│                    │
  │                      │   (Async)             │                    │
  │◄──── Success ────────│                       │                    │
```

### 2.2 Document Processing Flow

```
Queue                AI Service            Application           Database
  │                      │                       │                    │
  │── Dequeue Task ─────►│                       │                    │
  │                      │                       │                    │
  │                      │── Extract Text ──────►│                    │
  │                      │                       │                    │
  │                      │── Call AI API ───────►│                    │
  │                      │   (PHI Removed)       │                    │
  │                      │                       │                    │
  │                      │◄── FHIR Data ─────────│                    │
  │                      │                       │                    │
  │                      │                       │── Encrypt PHI ────►│
  │                      │                       │                    │
  │                      │                       │── Store FHIR ─────►│
  │                      │                       │                    │
  │                      │                       │── Log Audit ──────►│
```

### 2.3 PHI Access Flow

```
User                 Application              Database           Audit Log
  │                      │                       │                    │
  │── Request Patient ──►│                       │                    │
  │                      │                       │                    │
  │                      │── Verify Auth ───────►│                    │
  │                      │                       │                    │
  │                      │── Check RBAC ────────►│                    │
  │                      │                       │                    │
  │                      │── Fetch Encrypted ───►│                    │
  │                      │   Data                │                    │
  │                      │                       │                    │
  │                      │◄── Return Data ───────│                    │
  │                      │                       │                    │
  │                      │── Decrypt PHI ───────►│                    │
  │                      │   (Application Layer) │                    │
  │                      │                       │                    │
  │                      │────────────────────── Log Access ─────────►│
  │                      │                       │                    │
  │◄── Display Data ─────│                       │                    │
```

---

## 3. Security Boundaries

### 3.1 Network Boundaries

| Zone | Components | Security Controls |
|------|------------|-------------------|
| Public Internet | End Users | TLS 1.2+, WAF |
| DMZ | Load Balancer | SSL termination, DDoS protection |
| Application Zone | Web Servers, Workers | Firewall, VPC isolation |
| Data Zone | Database, Storage | Private subnet, no public access |
| External Services | AI APIs, Email | Encrypted connections, API keys |

### 3.2 Trust Boundaries

```
┌──────────────────────────────────────────────────────────────┐
│                    UNTRUSTED ZONE                             │
│                                                               │
│                    Internet Users                             │
│                    External APIs                              │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ TLS + Authentication
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    SEMI-TRUSTED ZONE                          │
│                                                               │
│                    Application Layer                          │
│                    (Validates all input)                      │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ Encryption + Access Control
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                    TRUSTED ZONE                               │
│                                                               │
│                    Database Layer                             │
│                    File Storage                               │
│                    Encryption Keys                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 4. Component Overview

### 4.1 Web Application

| Aspect | Details |
|--------|---------|
| Framework | Django 5.0 (Python) |
| Purpose | User interface, API endpoints, business logic |
| Security Role | Authentication, authorization, encryption/decryption |

### 4.2 Database

| Aspect | Details |
|--------|---------|
| Technology | PostgreSQL with JSONB support |
| Purpose | Persistent data storage |
| Security Role | Data at rest (field-level encryption by application) |

### 4.3 Message Queue

| Aspect | Details |
|--------|---------|
| Technology | Redis + Celery |
| Purpose | Async document processing |
| Security Role | Ephemeral data, in-memory only |

### 4.4 File Storage

| Aspect | Details |
|--------|---------|
| Technology | Encrypted file storage |
| Purpose | Original document storage |
| Security Role | Encrypted at rest, access controlled |

---

## 5. Data Classification

### 5.1 PHI Data (Encrypted)

- Patient names (first, last)
- Social Security Numbers
- Dates of birth
- Contact information (address, phone, email)
- Medical record content (FHIR bundles)
- Document text content

### 5.2 Operational Data (Standard Protection)

- Medical codes (ICD, SNOMED, RxNorm, LOINC)
- Encounter dates (de-identified)
- Provider references
- Document metadata (type, status, dates)

### 5.3 System Data

- Audit logs
- User accounts (passwords hashed)
- Configuration settings
- Application logs

---

## 6. Integration Points

### 6.1 Inbound Integrations

| Integration | Protocol | Authentication | Data Exchanged |
|-------------|----------|----------------|----------------|
| User Access | HTTPS | Session/Token | All user data |
| Document Upload | HTTPS | Session | Medical documents |
| API Access | HTTPS | Token | Patient data, FHIR |

### 6.2 Outbound Integrations

| Integration | Protocol | Authentication | Data Exchanged |
|-------------|----------|----------------|----------------|
| AI Services | HTTPS | API Key | Document text (PHI removed when possible) |
| Email Service | HTTPS | API Key | Notifications (no PHI) |
| Monitoring | HTTPS | API Key | Metrics (no PHI) |

---

## 7. Deployment Model

### 7.1 Container Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DOCKER ENVIRONMENT                        │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    Web       │  │   Celery     │  │   Celery     │      │
│  │   Server     │  │   Worker     │  │    Beat      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│         │                 │                 │                │
│         └─────────────────┼─────────────────┘                │
│                           │                                  │
│                           ▼                                  │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │  PostgreSQL  │  │    Redis     │                         │
│  │   Database   │  │    Queue     │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Environment Separation

| Environment | Purpose | Data |
|-------------|---------|------|
| Development | Feature development | Synthetic data only |
| Staging | Pre-production testing | Anonymized data |
| Production | Live system | Real PHI (encrypted) |

---

## 8. Disaster Recovery

### 8.1 Backup Strategy

| Component | Backup Frequency | Retention | Encryption |
|-----------|-----------------|-----------|------------|
| Database | Daily + Continuous | 30 days | AES-256 |
| File Storage | Daily | 30 days | AES-256 |
| Configuration | Per change | Indefinite | Encrypted |

### 8.2 Recovery Objectives

| Metric | Target |
|--------|--------|
| Recovery Time Objective (RTO) | 4 hours |
| Recovery Point Objective (RPO) | 1 hour |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-01 | Architecture Team | Initial document |

---

*This document is confidential and intended for authorized recipients only.*

*Updated: 2026-01-01 22:59:01 | Initial architecture documentation*

