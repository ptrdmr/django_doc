# apps/documents/services/response_parser.py
"""
Multi-strategy response parser template
Based on proven Flask parsing patterns from example_parser.md
"""

import json
import re
import logging
from typing import Dict, List, Any, Optional, Union


class ResponseParser:
    """
    Multi-fallback JSON parsing strategies from Flask DocumentAnalyzer
    Handles AI response parsing with 5 different fallback strategies
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def extract_structured_data(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Extract structured data from AI response using multiple fallback strategies
        
        Args:
            text_content: Raw text response from AI
            
        Returns:
            List of structured fields with id, label, value, and confidence
        """
        self.logger.info(f"Parsing response of {len(text_content)} characters")
        
        # Strategy 1: Direct JSON parsing
        try:
            return self._parse_direct_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Direct JSON parsing failed, trying sanitized approach")
        
        # Strategy 2: Sanitized JSON parsing
        try:
            return self._parse_sanitized_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Sanitized JSON parsing failed, trying code block extraction")
        
        # Strategy 3: Code block extraction
        try:
            return self._parse_code_block_json(text_content)
        except json.JSONDecodeError:
            self.logger.warning("Code block parsing failed, trying regex extraction")
        
        # Strategy 4: Regex key-value extraction
        try:
            return self._parse_regex_patterns(text_content)
        except Exception:
            self.logger.warning("Regex parsing failed, trying medical pattern recognition")
        
        # Strategy 5: Medical pattern recognition fallback
        return self._parse_medical_patterns(text_content)
    
    def _parse_direct_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 1: Direct JSON parsing of the response
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If content is not valid JSON
        """
        data = json.loads(text_content.strip())
        self.logger.info("Successfully parsed response as direct JSON")
        return self._convert_json_to_fields(data)
    
    def _parse_sanitized_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 2: Sanitized JSON parsing - clean up common formatting issues
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If sanitized content is not valid JSON
        """
        # Remove markdown code block markers
        sanitized_text = text_content.strip()
        sanitized_text = re.sub(r'^```json\s*', '', sanitized_text)
        sanitized_text = re.sub(r'\s*```$', '', sanitized_text)
        
        # If the response starts with a curly brace, extract just the JSON portion
        if sanitized_text.startswith('{'):
            # Find matching closing bracket
            open_count = 0
            close_idx = -1
            
            for i, char in enumerate(sanitized_text):
                if char == '{':
                    open_count += 1
                elif char == '}':
                    open_count -= 1
                    if open_count == 0:
                        close_idx = i
                        break
            
            if close_idx >= 0:
                sanitized_text = sanitized_text[:close_idx + 1]
                self.logger.info("Extracted complete JSON object from sanitized text")
        
        data = json.loads(sanitized_text)
        self.logger.info("Successfully parsed sanitized JSON")
        return self._convert_json_to_fields(data)
    
    def _parse_code_block_json(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 3: Extract JSON from markdown code blocks
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
            
        Raises:
            json.JSONDecodeError: If code block content is not valid JSON
        """
        # Look for JSON-like content between ``` markers
        json_match = re.search(r'```(?:json)?(.*?)```', text_content, re.DOTALL)
        
        if not json_match:
            raise json.JSONDecodeError("No code block found", text_content, 0)
        
        json_str = json_match.group(1).strip()
        data = json.loads(json_str)
        self.logger.info("Successfully parsed JSON from code block")
        return self._convert_json_to_fields(data)
    
    def _parse_regex_patterns(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 4: Regex-based key-value extraction for non-JSON responses
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list
        """
        # Extract key-value pairs using regex
        pairs = re.findall(r'([A-Za-z][A-Za-z0-9\s]*?):\s*([^:\n]+)', text_content)
        
        if not pairs:
            raise ValueError("No key-value pairs found in text")
        
        fields = []
        for i, (key, value) in enumerate(pairs):
            # Clean up the key and value
            clean_key = key.strip()
            clean_value = value.strip()
            
            # Skip very short or invalid entries
            if len(clean_key) < 2 or len(clean_value) < 1:
                continue
            
            fields.append({
                "id": str(i + 1),
                "label": clean_key,
                "value": clean_value,
                "confidence": 0.7  # Lower confidence for regex extraction
            })
        
        self.logger.info(f"Extracted {len(fields)} fields using regex patterns")
        return fields
    
    def _parse_medical_patterns(self, text_content: str) -> List[Dict[str, Any]]:
        """
        Strategy 5: Medical pattern recognition fallback for difficult documents
        
        Args:
            text_content: Raw response text
            
        Returns:
            Parsed fields list (may be empty if no patterns found)
        """
        medical_fields = []
        
        # Patient name patterns
        patient_name_patterns = [
            r'Patient:?\s*([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',
            r'Name:?\s*([A-Z][a-z]+,\s*[A-Z][a-z\s]+)',
            r'([A-Z][A-Z\s]+,\s*[A-Z][A-Z\s]+)'  # All caps names
        ]
        
        for pattern in patient_name_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "patientName",
                    "value": match.group(1).strip(),
                    "confidence": 0.8
                })
                break
        
        # Date of birth patterns
        dob_patterns = [
            r'DOB:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'Date of Birth:?\s*(\d{1,2}/\d{1,2}/\d{4})',
            r'Born:?\s*(\d{1,2}/\d{1,2}/\d{4})'
        ]
        
        for pattern in dob_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "dateOfBirth",
                    "value": match.group(1).strip(),
                    "confidence": 0.9
                })
                break
        
        # Gender/Sex patterns
        sex_patterns = [
            r'Sex:?\s*(Male|Female|M|F)',
            r'Gender:?\s*(Male|Female|M|F)'
        ]
        
        for pattern in sex_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                sex_value = match.group(1).upper()
                if sex_value in ['M', 'MALE']:
                    sex_value = 'Male'
                elif sex_value in ['F', 'FEMALE']:
                    sex_value = 'Female'
                
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "sex",
                    "value": sex_value,
                    "confidence": 0.9
                })
                break
        
        # Age patterns
        age_patterns = [
            r'Age:?\s*(\d+)\s*(?:years?|y\.?o\.?)',
            r'(\d+)\s*(?:year old|years old|yo)'
        ]
        
        for pattern in age_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "age",
                    "value": match.group(1).strip(),
                    "confidence": 0.8
                })
                break
        
        # Medical Record Number patterns
        mrn_patterns = [
            r'MR#:?\s*(\d+)',
            r'MRN:?\s*(\d+)',
            r'Medical Record:?\s*(\d+)'
        ]
        
        for pattern in mrn_patterns:
            match = re.search(pattern, text_content)
            if match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "medicalRecordNumber",
                    "value": match.group(1).strip(),
                    "confidence": 0.9
                })
                break
        
        # Diagnosis patterns
        diagnoses = self._extract_diagnoses(text_content)
        if diagnoses:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "diagnoses",
                "value": diagnoses,
                "confidence": 0.7
            })
        
        # Medication patterns
        medications = self._extract_medications(text_content)
        if medications:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "medications",
                "value": medications,
                "confidence": 0.7
            })
        
        # Allergy patterns
        allergies = self._extract_allergies(text_content)
        if allergies:
            medical_fields.append({
                "id": str(len(medical_fields) + 1),
                "label": "allergies",
                "value": allergies,
                "confidence": 0.7
            })
        
        self.logger.info(f"Extracted {len(medical_fields)} fields using medical patterns")
        return medical_fields
    
    def _extract_diagnoses(self, text_content: str) -> Optional[Union[str, List[str]]]:
        """Extract diagnosis information from text"""
        diagnoses = []
        
        # Look for problem lists
        problem_section = re.search(
            r'PROBLEM LIST(.*?)(?:^[A-Z\s]+:|$)', 
            text_content, 
            re.MULTILINE | re.DOTALL
        )
        
        if problem_section:
            problem_text = problem_section.group(1)
            problem_entries = re.findall(
                r'Problem Name:\s*([^\n]+).*?Life Cycle Status:\s*([^\n]+)', 
                problem_text, 
                re.DOTALL
            )
            
            for diagnosis, status in problem_entries:
                diagnoses.append(f"{diagnosis.strip()} ({status.strip()})")
        
        # Look for preoperative diagnosis
        preop_match = re.search(
            r'PREOPERATIVE DIAGNOSIS:(.*?)(?:POSTOPERATIVE|PROCEDURE|$)', 
            text_content, 
            re.DOTALL
        )
        
        if preop_match and preop_match.group(1).strip():
            diagnoses.append("Preoperative: " + preop_match.group(1).strip())
        
        # Look for postoperative diagnosis
        postop_match = re.search(
            r'POSTOPERATIVE DIAGNOSIS:(.*?)(?:PROCEDURE|SURGEON|$)', 
            text_content, 
            re.DOTALL
        )
        
        if postop_match and postop_match.group(1).strip():
            diagnoses.append("Postoperative: " + postop_match.group(1).strip())
        
        return diagnoses if diagnoses else None
    
    def _extract_medications(self, text_content: str) -> Optional[Union[str, List[str]]]:
        """Extract medication information from text"""
        medications = []
        
        # Look for medication sections
        med_patterns = [
            r'Medication Name:\s*([^\n]+).*?Ingredients:\s*([^\n]+)',
            r'Medications?:?\s*([^\n]+)',
            r'Current Medications?:?\s*([^\n]+)'
        ]
        
        for pattern in med_patterns:
            matches = re.findall(pattern, text_content, re.DOTALL)
            for match in matches:
                if isinstance(match, tuple):
                    # Handle medication name + ingredients pattern
                    med_name, ingredients = match
                    medications.append(f"{med_name.strip()} ({ingredients.strip()})")
                else:
                    # Handle simple medication pattern
                    medications.append(match.strip())
        
        return medications if medications else None
    
    def _extract_allergies(self, text_content: str) -> Optional[Union[str, List[str]]]:
        """Extract allergy information from text"""
        allergy_patterns = [
            r'ALLERG(?:Y|IES)(?:\s+LIST)?:?\s*([^\n]+)',
            r'Known Allergies:?\s*([^\n]+)',
            r'Drug Allergies:?\s*([^\n]+)'
        ]
        
        for pattern in allergy_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                allergy_text = match.group(1).strip()
                # Split by common delimiters
                allergies = [a.strip() for a in re.split(r'[,;]\s*', allergy_text) if a.strip()]
                return allergies if len(allergies) > 1 else allergy_text
        
        return None
    
    def _convert_json_to_fields(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Convert parsed JSON data to standardized field format
        
        Args:
            data: Parsed JSON data
            
        Returns:
            List of field dictionaries
        """
        fields = []
        
        for i, (key, value) in enumerate(data.items()):
            # Handle nested value/confidence structure
            if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                fields.append({
                    "id": str(i + 1),
                    "label": key,
                    "value": value['value'],
                    "confidence": float(value['confidence'])
                })
            # Handle simple key-value pairs
            else:
                fields.append({
                    "id": str(i + 1),
                    "label": key,
                    "value": str(value) if value is not None else "",
                    "confidence": 0.9  # Default confidence for simple values
                })
        
        return fields
    
    def validate_parsed_fields(self, fields: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate the quality of parsed fields
        
        Args:
            fields: List of parsed field dictionaries
            
        Returns:
            Validation results
        """
        validation = {
            "is_valid": True,
            "field_count": len(fields),
            "avg_confidence": 0.0,
            "issues": [],
            "required_fields_present": []
        }
        
        if not fields:
            validation["is_valid"] = False
            validation["issues"].append("No fields extracted")
            return validation
        
        # Calculate average confidence
        confidences = [f.get("confidence", 0.0) for f in fields]
        validation["avg_confidence"] = sum(confidences) / len(confidences)
        
        # Check for required medical fields
        required_fields = ["patientName", "dateOfBirth", "medicalRecordNumber"]
        present_labels = [f.get("label", "").lower() for f in fields]
        
        for req_field in required_fields:
            if any(req_field.lower() in label for label in present_labels):
                validation["required_fields_present"].append(req_field)
        
        # Quality checks
        if validation["avg_confidence"] < 0.5:
            validation["issues"].append("Low average confidence score")
        
        if len(validation["required_fields_present"]) == 0:
            validation["issues"].append("No critical patient demographics found")
        
        return validation


# Usage example:
"""
# In the DocumentAnalyzer service
parser = ResponseParser()

# Parse AI response
fields = parser.extract_structured_data(ai_response_text)

# Validate results
validation = parser.validate_parsed_fields(fields)

if validation["is_valid"]:
    # Process the fields
    process_extracted_fields(fields)
else:
    # Handle parsing issues
    logger.warning(f"Field parsing issues: {validation['issues']}")
""" 