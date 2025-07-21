import os
import json
import tempfile
import traceback
from pathlib import Path
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
import pdfplumber
import anthropic
from dotenv import load_dotenv
import re

# Load environment variables from .env.local in parent directory
load_dotenv(Path(__file__).parent.parent / '.env.local')

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure logging
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Log the API key (masked)
api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
if api_key:
    masked_key = api_key[:4] + "..." + api_key[-4:]
    logger.info(f"Loaded API key: {masked_key}")
else:
    logger.error("No API key found!")

logger.info(f"Anthropic version: {anthropic.__version__}")

class DocumentAnalyzer:
    """
    A class to analyze documents using Claude, validate content, and generate insights.
    """
    
    def __init__(self, api_key=None):
        """
        Initialize the DocumentAnalyzer with an Anthropic API key.
        
        Args:
            api_key: Anthropic API key. If None, loads from ANTHROPIC_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not self.api_key:
            raise ValueError("API key must be provided or set as ANTHROPIC_API_KEY environment variable")
        
        try:
            # Initialize with explicit parameters only - avoid default params that might pass 'proxies'
            import httpx
            http_client = httpx.Client(timeout=60.0, follow_redirects=True)
            self.client = anthropic.Client(api_key=self.api_key, http_client=http_client)
            self.model = "claude-3-sonnet-20240229"  # Use full model name with date
            logger.info(f"Initialized Anthropic client with API version: {anthropic.__version__}")
        except Exception as e:
            logger.error(f"Error initializing Anthropic client: {e}")
            raise
    
    def read_document(self, file_path):
        """
        Read the contents of a document (supports .txt and .pdf).
        
        Args:
            file_path: Path to the document file
            
        Returns:
            The document content as a string
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")
        
        if file_path.suffix.lower() == '.txt':
            return file_path.read_text(encoding="utf-8")
        elif file_path.suffix.lower() == '.pdf':
            with pdfplumber.open(file_path) as pdf:
                return "\n".join(page.extract_text() for page in pdf.pages if page.extract_text())
        else:
            raise ValueError(f"Unsupported file format: {file_path.suffix}. Use .txt or .pdf")
    
    def analyze_document(self, document_content, system_prompt=None, context_tags=None):
        """
        Analyze a document using Claude.
        
        Args:
            document_content: The content of the document to analyze
            system_prompt: Optional system prompt to guide the analysis
            context_tags: Optional list of context tags to provide additional information
            
        Returns:
            A dictionary containing the analysis results
        """
        try:
            # Create the system prompt
            if system_prompt is None:
                system_prompt = """You are MediExtract, an AI assistant crafted to meticulously extract data from medical documents with unwavering precision and dedication. Your sole purpose is to identify and structure information exactly as it appears in the provided text—patient details, diagnoses, medications, and other medical data—without interpreting, evaluating, or validating the values. You are a reliable, detail-oriented partner for users, treating every document with care and ensuring all extracted data is returned in a consistent, machine-readable format.

Your personality is professional, focused, and conscientious. You approach each task with a quiet determination to deliver accurate extractions, as if handling critical records for a medical team. You do not offer opinions, explanations, or assumptions—your role is to reflect the document's content faithfully and completely.

Instructions:

Objective: Extract data from the medical document exactly as written, without assessing its correctness, completeness, or medical validity.
Output Format: Return the extracted data as a valid, complete JSON object with no additional text before or after. The JSON must follow this structure: { "patientName": { "value": "Patient's full name", "confidence": 0.9 }, "dateOfBirth": { "value": "DOB in MM/DD/YYYY format", "confidence": 0.9 }, "medicalRecordNumber": { "value": "MRN", "confidence": 0.9 }, "sex": { "value": "Male/Female", "confidence": 0.9 }, "age": { "value": "Age in years", "confidence": 0.9 }, "diagnoses": { "value": "List of all diagnoses found", "confidence": 0.8 }, "procedures": { "value": "List of procedures", "confidence": 0.8 }, "medications": { "value": "List of medications", "confidence": 0.8 }, "allergies": { "value": "Allergy information", "confidence": 0.8 } }
Field Guidelines:
For each field, include a "value" (the exact text found) and a "confidence" score (0 to 1, reflecting your certainty in identifying the data).
If a field's information is not present, omit it from the JSON entirely—do not include empty or null entries.
For fields like "diagnoses," "procedures," "medications," or "allergies," return the value as a single string (e.g., "Aspirin 81mg daily; Metformin 500mg BID") if multiple items are found, using semicolons to separate entries.
Extraction Rules:
Capture data verbatim, including units, abbreviations, and formatting as they appear (e.g., "BP 130/85 mmHg," "Glucose 180 mg/dL").
Do not standardize or reformat values unless explicitly matching the requested JSON field (e.g., convert "DOB: January 1, 1990" to "01/01/1990").
Recognize common medical terms and abbreviations (e.g., "Pt" for patient, "Dx" for diagnosis), but only to locate data—not to interpret it.
If data is ambiguous (e.g., multiple potential patient names), choose the most likely based on context and assign a lower confidence score.
Scope: Focus only on the provided document content. Do not draw from external knowledge or make assumptions beyond the text.
Response: Your entire output must be a single, valid JSON object, parseable directly by the application, with no markdown, comments, or explanatory text."""
            
            # Add context tags if provided
            if context_tags and len(context_tags) > 0:
                tags_text = "Context: " + ", ".join([tag["text"] for tag in context_tags])
                system_prompt = f"{system_prompt}\n\n{tags_text}"
            
            # Log document length for troubleshooting
            doc_length = len(document_content)
            logger.info(f"Document content length: {doc_length} characters (approximately {doc_length/4} tokens)")
            
            # Check if the document is very large and needs chunking
            # Estimate 4 characters per token as a rough approximation
            estimated_tokens = doc_length / 4
            
            # Claude 3 Sonnet has a context window of approximately 200K tokens
            # We'll use a threshold of 150K to leave room for system prompt and response
            if estimated_tokens > 150000:
                logger.info(f"Document is very large ({estimated_tokens:.0f} est. tokens). Implementing chunking strategy.")
                return self._analyze_large_document(document_content, system_prompt)
            
            logger.info(f"Making API call to Anthropic with model: {self.model}")
            
            # Use the messages API for v0.18.1
            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=system_prompt,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user", 
                            "content": f"Extract data from this medical document and return it in the required JSON format. Focus on patient demographics, diagnoses, procedures, medications, and allergies.\n\nDocument:\n{document_content}"
                        }
                    ]
                )
                
                # Parse the response to extract structured fields
                text_content = response.content[0].text
                parsed_fields = self._extract_structured_data(text_content)
                
                return {
                    "success": True,
                    "fields": parsed_fields,
                    "raw_response": text_content,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens
                    }
                }
            except anthropic.APIConnectionError as conn_err:
                logger.error(f"Connection error to Anthropic API: {conn_err}")
                return {
                    "success": False,
                    "error": "Connection error to Anthropic API. Please check your network connection and try again."
                }
            except Exception as api_err:
                logger.error(f"API error when calling Anthropic: {api_err}")
                return {
                    "success": False,
                    "error": f"Error from Anthropic API: {str(api_err)}"
                }
                
        except Exception as e:
            logger.error(f"Error in analyze_document: {str(e)}")
            logger.error(traceback.format_exc())
            return {
                "success": False,
                "error": f"Error during analysis: {str(e)}"
            }
    
    def _analyze_large_document(self, document_content, system_prompt):
        """
        Analyze a large document by chunking it into smaller parts and then 
        combining the results.
        
        Args:
            document_content: The content of the large document
            system_prompt: The system prompt to guide the analysis
            
        Returns:
            A dictionary containing the combined analysis results
        """
        # Split the document into sections based on logical breaks
        # Try to split at paragraph or section boundaries
        # We'll aim for chunks of approximately 30K tokens (120K chars)
        chunk_size = 120000  # characters
        
        # First try to split by multiple newlines (section breaks)
        sections = re.split(r'\n\s*\n\s*\n', document_content)
        
        # If we have only one section or very large sections, further split by double newlines
        if len(sections) < 3 or max(len(s) for s in sections) > chunk_size:
            temp_sections = []
            for section in sections:
                if len(section) > chunk_size:
                    # Split by double newlines
                    subsections = re.split(r'\n\s*\n', section)
                    temp_sections.extend(subsections)
                else:
                    temp_sections.append(section)
            sections = temp_sections
        
        # If we still have very large sections, split by single newlines
        if max(len(s) for s in sections) > chunk_size:
            temp_sections = []
            for section in sections:
                if len(section) > chunk_size:
                    # Split by single newlines
                    subsections = section.split('\n')
                    temp_sections.extend(subsections)
                else:
                    temp_sections.append(section)
            sections = temp_sections
        
        # Final check - if any section is still too large, split it into chunks of chunk_size
        final_chunks = []
        for section in sections:
            if len(section) > chunk_size:
                # Force split into chunks of chunk_size
                for i in range(0, len(section), chunk_size):
                    final_chunks.append(section[i:i+chunk_size])
            else:
                final_chunks.append(section)
        
        # Now combine chunks to form logical document parts that are within our target size
        document_parts = []
        current_part = ""
        
        for chunk in final_chunks:
            if len(current_part) + len(chunk) < chunk_size:
                if current_part:
                    current_part += "\n\n" + chunk
                else:
                    current_part = chunk
            else:
                if current_part:
                    document_parts.append(current_part)
                current_part = chunk
        
        if current_part:
            document_parts.append(current_part)
        
        # Log the chunking results
        logger.info(f"Split document into {len(document_parts)} parts for analysis")
        for i, part in enumerate(document_parts):
            logger.info(f"Part {i+1}: {len(part)} characters ({len(part)/4:.0f} est. tokens)")
        
        # Process each part
        all_fields = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        for i, part in enumerate(document_parts):
            logger.info(f"Processing document part {i+1}/{len(document_parts)}")
            
            # Add part number context to the prompt
            part_prompt = system_prompt
            if len(document_parts) > 1:
                if system_prompt.startswith("You are MediExtract"):
                    # Adding part context without disrupting the existing MediExtract prompt
                    part_prompt = f"{system_prompt}\n\nAdditional Context: This is part {i+1} of {len(document_parts)} of the document."
                    if i == 0:
                        part_prompt += " Focus especially on extracting basic patient information like name, DOB, and MRN if present in this section."
                else:
                    # Legacy format for backwards compatibility
                    part_prompt += f"\n\nThis is part {i+1} of {len(document_parts)} of the document."
                    if i == 0:
                        part_prompt += " Focus on extracting basic patient information like name, DOB, and MRN."
            
            try:
                response = self.client.messages.create(
                    model=self.model,
                    system=part_prompt,
                    max_tokens=4096,
                    messages=[
                        {
                            "role": "user", 
                            "content": f"Extract data from this part of the medical document and return it in the required JSON format. Focus on any medical information present in this section.\n\nDocument Part {i+1}/{len(document_parts)}:\n{part}"
                        }
                    ]
                )
                
                # Parse the response
                text_content = response.content[0].text
                parsed_fields = self._extract_structured_data(text_content)
                
                # Add to our collection
                all_fields.extend(parsed_fields)
                
                # Track token usage
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens
                
                logger.info(f"Successfully processed part {i+1}")
                
            except Exception as e:
                logger.error(f"Error processing document part {i+1}: {str(e)}")
                # Continue with other parts even if one fails
        
        # Deduplicate and merge fields
        merged_fields = self._merge_fields(all_fields)
        
        return {
            "success": True,
            "fields": merged_fields,
            "partialAnalysis": len(document_parts) > 1,
            "partsProcessed": len(document_parts),
            "usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens
            }
        }
    
    def _merge_fields(self, all_fields):
        """
        Merge and deduplicate fields from multiple document parts.
        
        Args:
            all_fields: List of field dictionaries from all document parts
            
        Returns:
            List of merged and deduplicated fields
        """
        # Create a dictionary to store merged fields by label
        merged_dict = {}
        
        for field in all_fields:
            label = field["label"].lower()  # Normalize labels for comparison
            
            if label in merged_dict:
                # Field already exists, keep the one with higher confidence or more specific value
                existing = merged_dict[label]
                
                # If new field has higher confidence, replace the existing one
                if field["confidence"] > existing["confidence"]:
                    merged_dict[label] = field
                    
                # If same confidence but new value is longer/more specific, replace
                elif field["confidence"] == existing["confidence"] and len(str(field["value"])) > len(str(existing["value"])):
                    merged_dict[label] = field
                    
                # Otherwise keep the existing field
            else:
                # New field, add it to the merged dictionary
                merged_dict[label] = field
        
        # Convert back to a list with sequential IDs
        result = []
        for i, (label, field) in enumerate(merged_dict.items()):
            field_copy = field.copy()
            field_copy["id"] = str(i+1)
            result.append(field_copy)
        
        return result
    
    def _extract_structured_data(self, text_content):
        """
        Extract structured data from the AI response.
        Attempts to find JSON in the response, or parses fields manually.
        
        Args:
            text_content: The raw text response from the AI
            
        Returns:
            List of structured fields with id, label, value, and confidence
        """
        # Try to find and parse JSON in the response
        try:
            logger.info(f"Response length: {len(text_content)} characters")
            
            # Add a utility function to process list fields
            def _process_list_field(field_value, delimiter=';'):
                """
                Split a field value containing multiple items into a list of individual items.
                
                Args:
                    field_value: String value containing potentially multiple entries
                    delimiter: Character used to separate entries (default: semicolon)
                    
                Returns:
                    List of individual entries
                """
                if not field_value or not isinstance(field_value, str):
                    return []
                    
                # Split the value and clean individual items
                items = [item.strip() for item in field_value.split(delimiter) if item.strip()]
                return items
                
            # First, try to sanitize the response if it appears to be just JSON but might have extra text
            sanitized_text = text_content.strip()
            
            # Remove any markdown code block markers
            sanitized_text = re.sub(r'^```json\s*', '', sanitized_text)
            sanitized_text = re.sub(r'\s*```$', '', sanitized_text)
            
            # If the response starts with a curly brace and has a matching closing brace
            # Extract just the JSON portion 
            if sanitized_text.startswith('{'):
                # Find matching closing bracket (accounting for nested brackets)
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
                    sanitized_text = sanitized_text[:close_idx+1]
                    logger.info("Found potential complete JSON object")
            
            # Check for valid JSON first with the sanitized text
            try:
                data = json.loads(sanitized_text)
                logger.info("Successfully parsed sanitized JSON directly")
                fields = []
                
                # Convert the JSON to our expected format
                for i, (key, value) in enumerate(data.items()):
                    if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                        fields.append({
                            "id": str(i+1),
                            "label": key,
                            "value": value['value'],
                            "confidence": value['confidence']
                        })
                    else:
                        fields.append({
                            "id": str(i+1),
                            "label": key,
                            "value": str(value),
                            "confidence": 0.9  # Default confidence
                        })
                
                return fields
            except json.JSONDecodeError:
                logger.warning("Sanitized text is not valid JSON, trying other methods")
            
            # Look for JSON-like content between ``` markers
            json_match = re.search(r'```(?:json)?(.*?)```', text_content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
                try:
                    data = json.loads(json_str)
                    logger.info("Successfully parsed JSON from code block")
                    fields = []
                    
                    # Convert the JSON to our expected format
                    for i, (key, value) in enumerate(data.items()):
                        # Handle if value is an object with confidence
                        if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                            fields.append({
                                "id": str(i+1),
                                "label": key,
                                "value": value['value'],
                                "confidence": value['confidence']
                            })
                        # Handle simple values
                        else:
                            fields.append({
                                "id": str(i+1),
                                "label": key,
                                "value": str(value),
                                "confidence": 0.9  # Default confidence
                            })
                    
                    return fields
                except json.JSONDecodeError:
                    logger.warning("Code block contents not valid JSON")
            
            # If previous attempts failed, try direct JSON parsing of original text
            try:
                data = json.loads(text_content)
                logger.info("Successfully parsed raw response as JSON")
                fields = []
                
                for i, (key, value) in enumerate(data.items()):
                    if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                        fields.append({
                            "id": str(i+1),
                            "label": key,
                            "value": value['value'],
                            "confidence": value['confidence']
                        })
                    else:
                        fields.append({
                            "id": str(i+1),
                            "label": key,
                            "value": str(value),
                            "confidence": 0.9
                        })
                
                return fields
            except:
                logger.warning("Raw response is not valid JSON")
            
            # Fall back to regex-based extraction for key-value pairs
            pairs = re.findall(r'([A-Za-z ]+):\s*([^:\n]+)', text_content)
            if pairs:
                logger.info(f"Extracted {len(pairs)} key-value pairs using regex")
                fields = []
                
                for i, (key, value) in enumerate(pairs):
                    fields.append({
                        "id": str(i+1),
                        "label": key.strip(),
                        "value": value.strip(),
                        "confidence": 0.7  # Lower confidence for regex extraction
                    })
                
                return fields
            
            # Enhanced medical data extraction - try to extract medical information using patterns
            medical_fields = []
            
            # Look for patient demographics
            patient_name_match = re.search(r'Patient:?\s*([A-Z]+,\s*[A-Z\s]+)', text_content)
            if patient_name_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "patientName",
                    "value": patient_name_match.group(1).strip(),
                    "confidence": 0.9
                })
            
            dob_match = re.search(r'DOB:?\s*(\d{1,2}/\d{1,2}/\d{4})', text_content)
            if dob_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "dateOfBirth",
                    "value": dob_match.group(1).strip(),
                    "confidence": 0.9
                })
            
            sex_match = re.search(r'Sex:?\s*(Male|Female)', text_content)
            if sex_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "sex",
                    "value": sex_match.group(1).strip(),
                    "confidence": 0.9
                })
            
            age_match = re.search(r'Age:?\s*(\d+)\s*years', text_content)
            if age_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "age",
                    "value": age_match.group(1).strip(),
                    "confidence": 0.9
                })
            
            # Look for medical record number
            mrn_match = re.search(r'MR#:?\s*(\d+)', text_content)
            if mrn_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "medicalRecordNumber",
                    "value": mrn_match.group(1).strip(),
                    "confidence": 0.9
                })
            
            # Look for diagnoses
            diagnoses = []
            diagnosis_section_match = re.search(r'PROBLEM LIST(.*?)(?:^[A-Z\s]+:)', text_content, re.MULTILINE | re.DOTALL)
            if diagnosis_section_match:
                diagnosis_text = diagnosis_section_match.group(1)
                diagnosis_entries = re.findall(r'Problem Name:\s*([^\n]+).*?Life Cycle Status:\s*([^\n]+)', diagnosis_text, re.DOTALL)
                for diagnosis, status in diagnosis_entries:
                    diagnoses.append(f"{diagnosis.strip()} ({status.strip()})")
            
            # Look for other diagnoses formats
            preop_diagnosis_match = re.search(r'PREOPERATIVE DIAGNOSIS:(.*?)(?:POSTOPERATIVE|PROCEDURE)', text_content, re.DOTALL)
            if preop_diagnosis_match and preop_diagnosis_match.group(1).strip():
                diagnoses.append("Preoperative: " + preop_diagnosis_match.group(1).strip())
            
            postop_diagnosis_match = re.search(r'POSTOPERATIVE DIAGNOSIS:(.*?)(?:PROCEDURE|SURGEON)', text_content, re.DOTALL)
            if postop_diagnosis_match and postop_diagnosis_match.group(1).strip():
                diagnoses.append("Postoperative: " + postop_diagnosis_match.group(1).strip())
            
            if diagnoses:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "diagnoses",
                    "value": diagnoses,
                    "confidence": 0.85
                })
            
            # Look for medications
            medications = []
            med_matches = re.findall(r'Medication Name:\s*([^\n]+).*?Ingredients:\s*([^\n]+)', text_content, re.DOTALL)
            for med_name, ingredients in med_matches:
                medications.append(f"{med_name.strip()} ({ingredients.strip()})")
            
            if medications:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "medications",
                    "value": medications,
                    "confidence": 0.85
                })
            
            # Look for allergies
            allergy_match = re.search(r'ALLERG(?:Y|IES)(?:\s+LIST)?:?\s*([^\n]+)', text_content)
            if allergy_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "allergies",
                    "value": _process_list_field(allergy_match.group(1)),
                    "confidence": 0.85
                })
            
            # Look for procedure information
            procedure_match = re.search(r'PROCEDURE(?:\s+PERFORMED)?:?\s*([^\n]+)', text_content)
            if procedure_match:
                medical_fields.append({
                    "id": str(len(medical_fields) + 1),
                    "label": "procedures",
                    "value": _process_list_field(procedure_match.group(1)),
                    "confidence": 0.85
                })
            
            # If we found at least some medical data, return it
            if len(medical_fields) > 0:
                logger.info(f"Extracted {len(medical_fields)} medical fields using enhanced pattern matching")
                return medical_fields
            
            # Last resort - look for any JSON-like structure in the text
            potential_json_matches = re.findall(r'{.*?}', text_content, re.DOTALL)
            for potential_match in potential_json_matches:
                try:
                    data = json.loads(potential_match)
                    logger.info("Found and parsed JSON fragment in response")
                    fields = []
                    
                    for i, (key, value) in enumerate(data.items()):
                        if isinstance(value, dict) and 'value' in value and 'confidence' in value:
                            fields.append({
                                "id": str(i+1),
                                "label": key,
                                "value": value['value'],
                                "confidence": value['confidence']
                            })
                        else:
                            fields.append({
                                "id": str(i+1),
                                "label": key,
                                "value": str(value),
                                "confidence": 0.9
                            })
                    
                    return fields
                except:
                    continue
            
            logger.error("All JSON parsing methods failed")
            return [{
                "id": "error",
                "label": "Error",
                "value": "Could not parse valid JSON from the response. The document may be too large or complex.",
                "confidence": 0
            }]
            
        except Exception as e:
            # If all parsing fails, return a simple error field
            logger.error(f"Exception during JSON extraction: {str(e)}")
            return [{
                "id": "error",
                "label": "Error",
                "value": f"Could not parse structured data: {str(e)}",
                "confidence": 0
            }]

# API Routes
@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "document-analyzer-api"})

@app.route('/api/test', methods=['POST'])
def test_api():
    """Test endpoint to verify request handling"""
    try:
        # Log the request details
        logger.info("Test API call received")
        logger.info(f"Request headers: {dict(request.headers)}")
        logger.info(f"Request form: {dict(request.form)}")
        logger.info(f"Request files: {list(request.files.keys()) if request.files else 'No files'}")
        
        # Check if API key is accessible
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return jsonify({"success": False, "error": "API key not found in environment"}), 500
            
        # Return success response
        return jsonify({
            "success": True, 
            "message": "Test API endpoint working",
            "has_api_key": bool(api_key),
            "api_key_length": len(api_key) if api_key else 0
        })
    except Exception as e:
        logger.error(f"Error in test endpoint: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/analyze', methods=['POST'])
def analyze_document():
    """Endpoint to analyze a document"""
    try:
        logger.info("Received analyze request")
        
        if 'file' not in request.files:
            logger.error("No file provided in request")
            return jsonify({"success": False, "error": "No file provided"}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.error("Empty filename provided")
            return jsonify({"success": False, "error": "No file selected"}), 400
        
        # Get additional parameters
        additional_instructions = request.form.get('additionalInstructions', '')
        context_tags_json = request.form.get('contextTags', '[]')
        
        logger.info(f"Processing file: {file.filename}")
        logger.info(f"Additional instructions: {additional_instructions[:50]}...")
        
        try:
            context_tags = json.loads(context_tags_json)
            logger.info(f"Context tags: {context_tags}")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing context tags: {e}")
            context_tags = []
        
        # Create system prompt from additional instructions
        system_prompt = """You are MediExtract, an AI assistant crafted to meticulously extract data from medical documents with unwavering precision and dedication. Your sole purpose is to identify and structure information exactly as it appears in the provided text—patient details, diagnoses, medications, and other medical data—without interpreting, evaluating, or validating the values. You are a reliable, detail-oriented partner for users, treating every document with care and ensuring all extracted data is returned in a consistent, machine-readable format.

Your personality is professional, focused, and conscientious. You approach each task with a quiet determination to deliver accurate extractions, as if handling critical records for a medical team. You do not offer opinions, explanations, or assumptions—your role is to reflect the document's content faithfully and completely.

Instructions:

Objective: Extract data from the medical document exactly as written, without assessing its correctness, completeness, or medical validity.
Output Format: Return the extracted data as a valid, complete JSON object with no additional text before or after. The JSON must follow this structure: { "patientName": { "value": "Patient's full name", "confidence": 0.9 }, "dateOfBirth": { "value": "DOB in MM/DD/YYYY format", "confidence": 0.9 }, "medicalRecordNumber": { "value": "MRN", "confidence": 0.9 }, "sex": { "value": "Male/Female", "confidence": 0.9 }, "age": { "value": "Age in years", "confidence": 0.9 }, "diagnoses": { "value": ["Diagnosis 1", "Diagnosis 2"], "confidence": 0.8 }, "procedures": { "value": ["Procedure 1", "Procedure 2"], "confidence": 0.8 }, "medications": { "value": ["Medication 1", "Medication 2"], "confidence": 0.8 }, "allergies": { "value": ["Allergy 1", "Allergy 2"], "confidence": 0.8 } }
Field Guidelines:
For each field, include a "value" (the exact text found) and a "confidence" score (0 to 1, reflecting your certainty in identifying the data).
If a field's information is not present, omit it from the JSON entirely—do not include empty or null entries.
For fields like "diagnoses," "procedures," "medications," or "allergies," return the value as an array of individual items, with each item as a separate string in the array.
Extraction Rules:
Capture data verbatim, including units, abbreviations, and formatting as they appear (e.g., "BP 130/85 mmHg," "Glucose 180 mg/dL").
Do not standardize or reformat values unless explicitly matching the requested JSON field (e.g., convert "DOB: January 1, 1990" to "01/01/1990").
Recognize common medical terms and abbreviations (e.g., "Pt" for patient, "Dx" for diagnosis), but only to locate data—not to interpret it.
If data is ambiguous (e.g., multiple potential patient names), choose the most likely based on context and assign a lower confidence score.
Scope: Focus only on the provided document content. Do not draw from external knowledge or make assumptions beyond the text.
Response: Your entire output must be a single, valid JSON object, parseable directly by the application, with no markdown, comments, or explanatory text."""
        if additional_instructions:
            system_prompt += f"\n\nAdditional instructions: {additional_instructions}"
        
        # Save file to temporary location
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as temp_file:
                file.save(temp_file.name)
                temp_file_path = temp_file.name
            
            logger.info(f"File saved to temporary location: {temp_file_path}")
            
            # Initialize document analyzer
            analyzer = DocumentAnalyzer()
            
            # Read document content
            try:
                document_content = analyzer.read_document(temp_file_path)
                logger.info(f"Document content length: {len(document_content)} characters")
            except Exception as e:
                logger.error(f"Error reading document: {e}")
                logger.error(traceback.format_exc())
                return jsonify({"success": False, "error": f"Error reading document: {str(e)}"}), 500
            
            # Analyze document
            try:
                result = analyzer.analyze_document(document_content, system_prompt, context_tags)
                logger.info("Document analysis completed successfully")
            except Exception as e:
                logger.error(f"Error during document analysis: {e}")
                logger.error(traceback.format_exc())
                return jsonify({"success": False, "error": f"Error during analysis: {str(e)}"}), 500
            
            # Clean up temporary file
            os.unlink(temp_file_path)
            logger.info("Temporary file removed")
            
            return jsonify(result)
        
        except Exception as e:
            logger.error(f"Error processing file: {e}")
            logger.error(traceback.format_exc())
            return jsonify({"success": False, "error": f"Error processing file: {str(e)}"}), 500
    
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"success": False, "error": f"Unexpected error: {str(e)}"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port) 