"""
ServiceRequest Service for FHIR Resource Processing

This service handles the conversion of extracted service request data into proper FHIR 
ServiceRequest resources for ordered services, consultations, and referrals.
"""

import logging
from typing import List, Dict, Any, Optional
from uuid import uuid4
from datetime import datetime

logger = logging.getLogger(__name__)


class ServiceRequestService:
    """
    Service for processing service request data into FHIR ServiceRequest resources.
    
    Handles various types of service requests including consultations, referrals,
    ordered tests, and other medical services.
    """
    
    def __init__(self):
        self.logger = logger
        
    def process_service_requests(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process service requests with complete service and order information.
        
        Args:
            extracted_data: Dictionary containing extracted medical data with service requests
            
        Returns:
            List of FHIR ServiceRequest resources
        """
        requests = []
        patient_id = extracted_data.get('patient_id')
        
        # Handle different service request data structures
        request_data = self._extract_service_request_data(extracted_data)
        
        for request in request_data:
            try:
                request_resource = self._create_service_request(request, patient_id)
                if request_resource:
                    requests.append(request_resource)
                    self.logger.info(f"Created ServiceRequest for: {request.get('service', 'Unknown service')}")
            except Exception as e:
                self.logger.error(f"Failed to create ServiceRequest for {request}: {e}")
                continue
                
        self.logger.info(f"Processed {len(requests)} service requests from {len(request_data)} extracted entries")
        return requests
        
    def _extract_service_request_data(self, extracted_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract service request data from various possible structures in extracted data.
        
        Args:
            extracted_data: Raw extracted data that may contain service requests in different formats
            
        Returns:
            List of normalized service request dictionaries
        """
        request_data = []
        
        # Handle direct service_requests list
        if 'service_requests' in extracted_data and isinstance(extracted_data['service_requests'], list):
            request_data.extend(extracted_data['service_requests'])
            
        # Handle referrals and consultations
        if 'referrals' in extracted_data and isinstance(extracted_data['referrals'], list):
            for referral in extracted_data['referrals']:
                request_data.append(self._convert_referral_to_request(referral))
                
        if 'consultations' in extracted_data and isinstance(extracted_data['consultations'], list):
            for consult in extracted_data['consultations']:
                request_data.append(self._convert_consultation_to_request(consult))
                
        # Handle orders
        if 'orders' in extracted_data and isinstance(extracted_data['orders'], list):
            for order in extracted_data['orders']:
                request_data.append(self._convert_order_to_request(order))
                
        # Handle fields from document analyzer
        if 'fields' in extracted_data:
            for field in extracted_data['fields']:
                if isinstance(field, dict):
                    label = field.get('label', '').lower()
                    if any(term in label for term in ['referral', 'consult', 'order', 'request', 'follow-up', 'followup']):
                        # Convert field to service request format
                        request = self._convert_field_to_request(field)
                        if request:
                            request_data.append(request)
                            
        # Handle plan or recommendations that are actually service requests
        if 'plan' in extracted_data:
            plan_requests = self._extract_requests_from_plan(extracted_data['plan'])
            request_data.extend(plan_requests)
            
        if 'recommendations' in extracted_data:
            rec_requests = self._extract_requests_from_recommendations(extracted_data['recommendations'])
            request_data.extend(rec_requests)
            
        return request_data
        
    def _convert_referral_to_request(self, referral: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a referral dictionary to a service request format.
        
        Args:
            referral: Referral data dictionary
            
        Returns:
            Service request data dictionary
        """
        return {
            'service': f"Referral to {referral.get('specialty', referral.get('provider', 'specialist'))}",
            'date': referral.get('date'),
            'reason': referral.get('reason'),
            'priority': referral.get('priority', 'routine'),
            'status': 'active',
            'intent': 'order',
            'source': 'referral_conversion'
        }
        
    def _convert_consultation_to_request(self, consult: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a consultation dictionary to a service request format.
        
        Args:
            consult: Consultation data dictionary
            
        Returns:
            Service request data dictionary
        """
        return {
            'service': f"Consultation with {consult.get('specialty', consult.get('provider', 'specialist'))}",
            'date': consult.get('date'),
            'reason': consult.get('reason', consult.get('indication')),
            'priority': consult.get('priority', 'routine'),
            'status': 'active',
            'intent': 'order',
            'source': 'consultation_conversion'
        }
        
    def _convert_order_to_request(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert an order dictionary to a service request format.
        
        Args:
            order: Order data dictionary
            
        Returns:
            Service request data dictionary
        """
        return {
            'service': order.get('service', order.get('item')),
            'date': order.get('date', order.get('ordered_date')),
            'reason': order.get('indication', order.get('reason')),
            'priority': order.get('priority', 'routine'),
            'status': order.get('status', 'active'),
            'intent': 'order',
            'source': 'order_conversion'
        }
        
    def _convert_field_to_request(self, field: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convert a document analyzer field into a service request dictionary.
        
        Args:
            field: Field dictionary from document analyzer
            
        Returns:
            Normalized service request dictionary or None
        """
        value = field.get('value', '')
        label = field.get('label', '')
        
        if not value:
            return None
            
        # Parse service request information from the field
        request_info = self._parse_service_request_text(value, label)
        if request_info['service']:
            return {
                'service': request_info['service'],
                'date': request_info.get('date'),
                'reason': request_info.get('reason'),
                'priority': request_info.get('priority', 'routine'),
                'status': 'active',
                'intent': 'order',
                'confidence': field.get('confidence', 0.8),
                'source': 'document_field'
            }
        return None
        
    def _extract_requests_from_plan(self, plan_text: str) -> List[Dict[str, Any]]:
        """
        Extract service requests from a plan or treatment plan text.
        
        Args:
            plan_text: Text containing treatment plan
            
        Returns:
            List of service request dictionaries
        """
        if not isinstance(plan_text, str):
            return []
            
        requests = []
        
        # Common plan indicators that suggest service requests
        request_indicators = [
            r'refer to ([^.]+)',
            r'consult with ([^.]+)',
            r'order ([^.]+)',
            r'schedule ([^.]+)',
            r'follow[- ]?up with ([^.]+)',
            r'see ([^.]+)',
            r'obtain ([^.]+)'
        ]
        
        import re
        
        for pattern in request_indicators:
            matches = re.finditer(pattern, plan_text, re.IGNORECASE)
            for match in matches:
                service = match.group(1).strip()
                if service:
                    requests.append({
                        'service': service,
                        'date': None,
                        'reason': 'As per treatment plan',
                        'priority': 'routine',
                        'status': 'active',
                        'intent': 'order',
                        'source': 'plan_extraction'
                    })
                    
        return requests
        
    def _extract_requests_from_recommendations(self, recommendations: str) -> List[Dict[str, Any]]:
        """
        Extract service requests from recommendations text.
        
        Args:
            recommendations: Text containing recommendations
            
        Returns:
            List of service request dictionaries
        """
        if not isinstance(recommendations, str):
            return []
            
        # Use similar logic as plan extraction
        return self._extract_requests_from_plan(recommendations)
        
    def _parse_service_request_text(self, text: str, context: str = '') -> Dict[str, Any]:
        """
        Parse service request information from a text string.
        
        Args:
            text: Text containing service request information
            context: Context about the type of request
            
        Returns:
            Dictionary with parsed service request components
        """
        import re
        
        text = text.strip()
        if not text:
            return {'service': None}
            
        # Initialize result
        result = {
            'service': None,
            'date': None,
            'reason': None,
            'priority': 'routine'
        }
        
        # Service patterns
        service_patterns = [
            r'(cardiology|neurology|orthopedic|dermatology|psychiatry|psychology)\s*(?:consult|consultation)',
            r'(?:refer|referral)\s+to\s+([^.]+)',
            r'(?:consult|consultation)\s+with\s+([^.]+)',
            r'(?:order|obtain)\s+([^.]+)',
            r'follow[- ]?up\s+with\s+([^.]+)',
            r'see\s+([^.]+)',
        ]
        
        # Date patterns
        date_patterns = [
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{4}-\d{2}-\d{2})',
            r'(in \d+ weeks?)',
            r'(in \d+ months?)',
            r'(next week|next month)',
            r'(asap|urgent|stat)'
        ]
        
        # Priority patterns
        priority_patterns = [
            r'\b(urgent|stat|asap|emergency)\b',
            r'\b(routine|standard)\b'
        ]
        
        text_lower = text.lower()
        
        # Extract service
        service = None
        for pattern in service_patterns:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                if len(match.groups()) > 0:
                    service = match.group(1).strip()
                else:
                    service = match.group(0).strip()
                break
                
        # If no specific service pattern found, use the whole text as service
        if not service:
            service = text.strip()
            
        result['service'] = service
        
        # Extract date
        for pattern in date_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['date'] = match.group(1)
                break
                
        # Extract priority
        for pattern in priority_patterns:
            match = re.search(pattern, text_lower)
            if match:
                priority_text = match.group(1)
                if priority_text in ['urgent', 'stat', 'asap', 'emergency']:
                    result['priority'] = 'urgent'
                else:
                    result['priority'] = 'routine'
                break
                
        # Extract reason (look for common reason indicators)
        reason_patterns = [
            r'for\s+([^.]+)',
            r'due to\s+([^.]+)',
            r'because of\s+([^.]+)',
            r'indication[:\s]+([^.]+)'
        ]
        
        for pattern in reason_patterns:
            match = re.search(pattern, text_lower)
            if match:
                result['reason'] = match.group(1).strip()
                break
                
        return result
        
    def _create_service_request(self, request_data: Dict[str, Any], patient_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Create a ServiceRequest resource from service request information.
        
        Args:
            request_data: Service request data dictionary
            patient_id: Patient ID for the resource
            
        Returns:
            FHIR ServiceRequest resource or None if creation fails
        """
        try:
            service = request_data.get('service')
            if not service:
                self.logger.warning("Service request missing service description, skipping")
                return None
                
            request_id = str(uuid4())
            
            # Create basic ServiceRequest resource structure
            request_resource = {
                "resourceType": "ServiceRequest",
                "id": request_id,
                "status": request_data.get('status', 'active'),
                "intent": request_data.get('intent', 'order'),
                "code": {
                    "text": service
                },
                "meta": {
                    "versionId": "1",
                    "lastUpdated": datetime.now().isoformat(),
                    "source": f"ServiceRequestService-{request_data.get('source', 'unknown')}"
                }
            }
            
            # Add patient reference if available
            if patient_id:
                request_resource["subject"] = {
                    "reference": f"Patient/{patient_id}"
                }
                
            # Add authored date if available
            if request_data.get('date'):
                request_resource["authoredOn"] = request_data['date']
                
            # Add priority if specified
            priority = request_data.get('priority', 'routine')
            if priority in ['routine', 'urgent', 'asap', 'stat']:
                request_resource["priority"] = priority
                
            # Add reason/indication if available
            if request_data.get('reason'):
                request_resource["reasonCode"] = [{
                    "text": request_data['reason']
                }]
                
            # Add category based on service type
            category = self._determine_category(service)
            if category:
                request_resource["category"] = [{
                    "coding": [{
                        "system": "http://snomed.info/sct",
                        "code": category['code'],
                        "display": category['display']
                    }]
                }]
                
            # Add confidence as extension if available
            if request_data.get('confidence'):
                request_resource["extension"] = [{
                    "url": "http://hl7.org/fhir/StructureDefinition/data-confidence",
                    "valueDecimal": request_data['confidence']
                }]
                
            return request_resource
            
        except Exception as e:
            self.logger.error(f"Failed to create ServiceRequest: {e}")
            return None
            
    def _determine_category(self, service: str) -> Optional[Dict[str, str]]:
        """
        Determine the appropriate category for a service request.
        
        Args:
            service: Type of service requested
            
        Returns:
            Dictionary with category code and display, or None
        """
        service_lower = service.lower()
        
        if any(term in service_lower for term in ['cardiology', 'cardiac', 'heart']):
            return {'code': '394579002', 'display': 'Cardiology'}
        elif any(term in service_lower for term in ['neurology', 'neuro', 'brain']):
            return {'code': '394591006', 'display': 'Neurology'}
        elif any(term in service_lower for term in ['orthopedic', 'ortho', 'bone', 'joint']):
            return {'code': '394801008', 'display': 'Trauma and orthopedics'}
        elif any(term in service_lower for term in ['dermatology', 'skin']):
            return {'code': '394582007', 'display': 'Dermatology'}
        elif any(term in service_lower for term in ['psychiatry', 'mental health', 'psychology']):
            return {'code': '394587001', 'display': 'Psychiatry'}
        elif any(term in service_lower for term in ['lab', 'laboratory', 'blood', 'test']):
            return {'code': '394595002', 'display': 'Pathology'}
        elif any(term in service_lower for term in ['imaging', 'x-ray', 'ct', 'mri', 'ultrasound']):
            return {'code': '394914008', 'display': 'Radiology'}
        elif any(term in service_lower for term in ['physical therapy', 'pt', 'rehabilitation']):
            return {'code': '394602003', 'display': 'Rehabilitation'}
        else:
            return {'code': '394658006', 'display': 'Clinical specialty'}
