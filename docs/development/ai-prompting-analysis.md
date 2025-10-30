# Medical Document Parser - AI Prompting Analysis

## Overview
This document outlines the current AI prompting strategy in our medical document processing system. We have a sophisticated, multi-layered approach centered around the "MediExtract" prompt system.

## System Architecture

### Core AI Service: DocumentAnalyzer
- **Location**: `apps/documents/services.py` (lines 307-3076)
- **Primary Role**: Orchestrates AI-powered medical document analysis
- **Dual Provider Support**: Anthropic Claude (primary) + OpenAI GPT (fallback)

### Prompt Management: MediExtract System
- **Location**: `apps/documents/prompts.py` (586 lines)
- **Core Philosophy**: Specialized prompts for different document types and scenarios
- **Design Pattern**: "Right tool for the job" - different prompts for different medical contexts

## AI Configuration

### Model Selection
- **Primary Model**: Claude Sonnet 4.5 (production) / Claude-3-Haiku (development)
- **Fallback Model**: GPT-4o-mini
- **Configuration**: Environment-based with smart defaults

### Parameters
```python
max_tokens = 4096
chunk_threshold = 30000  # tokens (1M in dev to disable chunking)
temperature = 0.2        # Low for medical precision
request_timeout = 120    # seconds
```

## The MediExtract Prompt System

### 1. Primary Extraction Prompt (`MEDIEXTRACT_SYSTEM_PROMPT`)
**Purpose**: Main medical data extraction
**Personality**: "Professional, focused, and conscientious"
**Key Features**:
- Extracts data "exactly as written" without interpretation
- Returns structured JSON with confidence scores
- Focuses on patient demographics, diagnoses, medications, allergies
- Enforces strict JSON-only responses

**Sample Output Format**:
```json
{
  "patientName": {"value": "Smith, John", "confidence": 0.9},
  "dateOfBirth": {"value": "01/15/1980", "confidence": 0.9},
  "diagnoses": {"value": "Type 2 diabetes; Hypertension", "confidence": 0.8}
}
```

### 2. FHIR-Focused Prompt (`FHIR_EXTRACTION_PROMPT`)
**Purpose**: FHIR-compliant medical data extraction
**Structure**: Organizes data by FHIR resource types
**Priority Order**:
1. Patient (demographics)
2. Condition (diagnoses)
3. Observation (vitals, labs)
4. MedicationStatement
5. Procedure
6. AllergyIntolerance

### 3. Document Type-Specific Prompts

#### Emergency Department (`ED_PROMPT`)
- **Focus**: Chief complaint, triage, vital signs, emergency procedures
- **Special Fields**: `chiefComplaint`, `triageLevel`, `disposition`

#### Surgical (`SURGICAL_PROMPT`)
- **Focus**: Pre/post-op diagnoses, procedures, surgical team, complications
- **Special Fields**: `preOpDiagnosis`, `surgeon`, `anesthesia`, `complications`

#### Laboratory (`LAB_PROMPT`)
- **Focus**: Test results, reference ranges, abnormal flags
- **Special Fields**: `labResults`, `abnormalFlags`, `referenceRanges`

### 4. Chunked Document Prompt (`CHUNKED_DOCUMENT_PROMPT`)
**Purpose**: Handles large documents split into sections
**Features**:
- Context-aware of which section (e.g., "part 2 of 5")
- Focuses on complete information within the chunk
- Lower confidence for potentially incomplete data at boundaries

### 5. Fallback Prompt (`FALLBACK_EXTRACTION_PROMPT`)
**Purpose**: Simplified extraction when primary methods fail
**Approach**: Basic key-value pairs, simpler structure
**Use Case**: Error recovery, degraded service scenarios

## Processing Strategy

### 1. Document Size Detection
```python
estimated_tokens = len(content) // 4
if estimated_tokens >= chunk_threshold:
    # Use chunked processing
else:
    # Single document processing
```

### 2. Progressive Prompt Strategy
The system employs a fallback sequence:
1. **Primary**: Document-type specific or FHIR prompt
2. **Secondary**: Standard MediExtract prompt
3. **Fallback**: Simplified extraction prompt

### 3. Provider Failover
1. **Anthropic Claude** (primary)
2. **OpenAI GPT** (fallback)
3. **Text Pattern Extraction** (last resort)

## Document Processing Flow

### Single Document Processing
```
1. Clean/preprocess text
2. Select appropriate prompt (based on context/type)
3. Call primary AI service (Claude)
4. If failure, try fallback service (OpenAI)
5. If still failing, try simplified prompt
6. Parse and validate response
7. Apply confidence scoring
```

### Large Document Processing (Chunked)
```
1. Split into medical-aware chunks
2. For each chunk:
   - Add chunk context ("part X of Y")
   - Process with chunk-aware prompt
   - Track success/failure
3. Reassemble results with deduplication
4. Generate comprehensive processing report
```

## Advanced Features

### 1. Confidence Scoring System
- **Location**: `ConfidenceScoring` class in prompts.py
- **Purpose**: Quality assessment and manual review flagging
- **Thresholds**:
  - High: ≥0.8 (trusted)
  - Medium: ≥0.5 (acceptable)
  - Manual Review: <0.3 (needs human oversight)

### 2. Context Enhancement
- **Context Tags**: Add situational awareness
- **Additional Instructions**: Custom user guidance
- **Document Type Detection**: Automatic prompt selection

### 3. Error Recovery & Circuit Breakers
- **Rate Limit Handling**: Automatic retries with backoff
- **Circuit Breaker Pattern**: Temporarily disable failing services
- **Comprehensive Logging**: Detailed tracking for debugging

## API Integration

### Message Structure

#### Anthropic Claude:
```python
{
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "temperature": 0.2,
    "system": system_prompt,
    "messages": [{"role": "user", "content": document_content}]
}
```

#### OpenAI GPT:
```python
{
    "model": "gpt-4o-mini",
    "max_tokens": 4096,
    "temperature": 0.2,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": document_content}
    ]
}
```

## Monitoring & Quality Assurance

### 1. Usage Tracking
- **Token consumption** per model/provider
- **Processing time** metrics
- **Success/failure rates** by chunk and document type

### 2. Quality Metrics
- **Average confidence scores**
- **Manual review requirements**
- **Field extraction completeness**

### 3. Error Monitoring
- **API errors** by provider and type
- **Circuit breaker activations**
- **Chunk processing failures**

## Current Strengths

1. **Robust Fallback Strategy**: Multiple layers of error recovery
2. **Medical Specialization**: Tailored prompts for different document types
3. **FHIR Compliance**: Structured output compatible with healthcare standards
4. **Confidence Scoring**: Built-in quality assessment
5. **Large Document Handling**: Smart chunking with context preservation
6. **Dual Provider Support**: Vendor independence and reliability

## Areas for Enhancement

1. **Prompt Engineering**: Could benefit from more domain-specific medical terminology
2. **Few-Shot Examples**: Currently zero-shot; adding examples might improve accuracy
3. **Context Window Utilization**: Could optimize chunk sizes based on model capabilities
4. **Custom Fine-tuning**: Consider domain-specific model training
5. **Real-time Quality Feedback**: Implement learning from manual corrections

## Configuration Management

### Environment Variables
```bash
# API Keys
ANTHROPIC_API_KEY=your_claude_api_key
OPENAI_API_KEY=your_openai_api_key

# Model Selection
AI_MODEL_PRIMARY=claude-sonnet-4-5-20250929
AI_MODEL_FALLBACK=gpt-4o-mini

# Processing Parameters
AI_MAX_TOKENS=4096
AI_CHUNK_THRESHOLD=30000
AI_TEMPERATURE=0.2
AI_REQUEST_TIMEOUT=120
```

### Runtime Configuration
- **Development**: Smaller models (Haiku), larger chunk threshold to prevent chunking
- **Production**: Larger models (Sonnet), standard chunk threshold
- **Cost Controls**: Token limits and timeout controls

---

*This system represents a production-ready, enterprise-grade approach to medical document processing with AI, emphasizing reliability, accuracy, and regulatory compliance.*
