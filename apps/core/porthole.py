"""
Porthole Debugging System

This module provides debugging utilities to capture data at various points
in the document processing pipeline for development visibility.

Usage:
    from apps.core.porthole import capture_pdf_text, capture_llm_output, capture_fhir_data
    
    # Capture PDF text
    capture_pdf_text(document_id, extracted_text)
    
    # Capture LLM output
    capture_llm_output(document_id, structured_data)
    
    # Capture FHIR data
    capture_fhir_data(document_id, fhir_resources)
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union
import logging

logger = logging.getLogger(__name__)

# Porthole directory path
PORTHOLE_DIR = Path(__file__).resolve().parent.parent.parent / "porthole"

def ensure_porthole_dir():
    """Ensure the porthole directory exists."""
    PORTHOLE_DIR.mkdir(exist_ok=True)

def capture_pdf_text(document_id: int, extracted_text: str, metadata: Dict[str, Any] = None):
    """
    Capture plain text extracted by PDF plumber before it hits the LLM.
    
    Args:
        document_id: Document ID
        extracted_text: Raw text extracted from PDF
        metadata: Additional metadata (page count, file size, etc.)
    """
    try:
        ensure_porthole_dir()
        
        capture_data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "stage": "pdf_extraction",
            "text_length": len(extracted_text),
            "text_content": extracted_text,
            "metadata": metadata or {}
        }
        
        filename = f"pdf_text_{document_id}.json"
        filepath = PORTHOLE_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(capture_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[PORTHOLE] Captured PDF text for document {document_id}: {len(extracted_text)} chars -> {filename}")
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to capture PDF text for document {document_id}: {e}")

def capture_llm_output(document_id: int, llm_response: Union[Dict, str], llm_type: str = "unknown", success: bool = True):
    """
    Capture structured output from the LLM.
    
    Args:
        document_id: Document ID
        llm_response: Raw LLM response (could be dict, string, or structured data)
        llm_type: Type of LLM used ("claude", "openai", etc.)
        success: Whether the LLM call was successful
    """
    try:
        ensure_porthole_dir()
        
        # Handle different response types
        if hasattr(llm_response, 'dict'):
            # Pydantic model
            response_data = llm_response.dict()
        elif hasattr(llm_response, '__dict__'):
            # Object with attributes
            response_data = vars(llm_response)
        elif isinstance(llm_response, (dict, list)):
            # Already JSON-serializable
            response_data = llm_response
        else:
            # String or other type
            response_data = {"raw_response": str(llm_response)}
        
        capture_data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "stage": "llm_extraction",
            "llm_type": llm_type,
            "success": success,
            "response_data": response_data
        }
        
        filename = f"llm_output_{document_id}.json"
        filepath = PORTHOLE_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(capture_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[PORTHOLE] Captured LLM output for document {document_id}: {llm_type} -> {filename}")
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to capture LLM output for document {document_id}: {e}")

def capture_fhir_data(document_id: int, fhir_resources: List[Dict], patient_id: str = None, stage: str = "fhir_conversion"):
    """
    Capture FHIR data after it's been processed/appended.
    
    Args:
        document_id: Document ID
        fhir_resources: List of FHIR resources
        patient_id: Patient ID if available
        stage: Stage of FHIR processing ("fhir_conversion", "patient_append", etc.)
    """
    try:
        ensure_porthole_dir()
        
        capture_data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "stage": stage,
            "patient_id": patient_id,
            "resource_count": len(fhir_resources) if fhir_resources else 0,
            "fhir_resources": fhir_resources or []
        }
        
        # Count resources by type
        if fhir_resources:
            resource_types = {}
            for resource in fhir_resources:
                resource_type = resource.get('resourceType', 'Unknown')
                resource_types[resource_type] = resource_types.get(resource_type, 0) + 1
            capture_data["resource_types"] = resource_types
        
        filename = f"fhir_data_{document_id}.json"
        filepath = PORTHOLE_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(capture_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[PORTHOLE] Captured FHIR data for document {document_id}: {len(fhir_resources or [])} resources -> {filename}")
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to capture FHIR data for document {document_id}: {e}")

def capture_raw_llm_response(document_id: int, raw_response: str, llm_type: str = "unknown", parsing_successful: bool = False):
    """
    Capture raw LLM response text for debugging parsing issues.
    
    Args:
        document_id: Document ID
        raw_response: Raw text response from LLM
        llm_type: Type of LLM used
        parsing_successful: Whether JSON parsing succeeded
    """
    try:
        ensure_porthole_dir()
        
        capture_data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "stage": "raw_llm_response",
            "llm_type": llm_type,
            "parsing_successful": parsing_successful,
            "response_length": len(raw_response),
            "raw_response": raw_response
        }
        
        filename = f"raw_llm_response_{document_id}.json"
        filepath = PORTHOLE_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(capture_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[PORTHOLE] Captured raw LLM response for document {document_id}: {len(raw_response)} chars -> {filename}")
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to capture raw LLM response for document {document_id}: {e}")

def capture_pipeline_error(document_id: int, stage: str, error_message: str, error_data: Dict[str, Any] = None):
    """
    Capture pipeline errors for debugging.
    
    Args:
        document_id: Document ID
        stage: Pipeline stage where error occurred
        error_message: Error message
        error_data: Additional error context
    """
    try:
        ensure_porthole_dir()
        
        capture_data = {
            "document_id": document_id,
            "timestamp": datetime.now().isoformat(),
            "stage": f"error_{stage}",
            "error_message": error_message,
            "error_data": error_data or {}
        }
        
        filename = f"error_{stage}_{document_id}.json"
        filepath = PORTHOLE_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(capture_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[PORTHOLE] Captured error for document {document_id} at stage {stage} -> {filename}")
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to capture error for document {document_id}: {e}")

def list_porthole_files(document_id: int = None):
    """
    List all porthole files, optionally filtered by document ID.
    
    Args:
        document_id: Optional document ID to filter by
        
    Returns:
        List of porthole files
    """
    try:
        ensure_porthole_dir()
        
        if document_id:
            pattern = f"*_{document_id}.json"
        else:
            pattern = "*.json"
        
        files = list(PORTHOLE_DIR.glob(pattern))
        return sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
        
    except Exception as e:
        logger.error(f"[PORTHOLE] Failed to list porthole files: {e}")
        return []
