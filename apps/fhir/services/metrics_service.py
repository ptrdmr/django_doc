"""
FHIR Metrics Service

Provides comprehensive metrics tracking for FHIR data capture improvements.
Calculates capture rates by comparing extracted AI data with processed FHIR resources.
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class FHIRMetricsService:
    """Service for calculating and tracking FHIR data capture metrics."""
    
    def __init__(self):
        """Initialize the metrics service."""
        self.supported_resource_types = [
            'MedicationStatement',
            'DiagnosticReport', 
            'ServiceRequest',
            'Encounter',
            'Condition',
            'Observation',
            'Procedure',
            'AllergyIntolerance',
            'CarePlan',
            'Organization',
            'Practitioner'
        ]
        
    def calculate_data_capture_metrics(
        self, 
        extracted_ai_data: Dict[str, Any], 
        processed_fhir_resources: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive data capture metrics.
        
        Args:
            extracted_ai_data: Raw data extracted by AI from document
            processed_fhir_resources: FHIR resources created from extracted data
            
        Returns:
            Dictionary containing detailed metrics
        """
        try:
            logger.info("Calculating FHIR data capture metrics")
            
            # Initialize metrics structure
            metrics = {
                'overall': {
                    'total_data_points': 0,
                    'captured_data_points': 0,
                    'capture_rate': 0.0
                },
                'by_category': {},
                'resource_counts': {},
                'processing_metadata': {
                    'timestamp': datetime.now().isoformat(),
                    'ai_data_categories': list(extracted_ai_data.keys()),
                    'fhir_resource_types': []
                }
            }
            
            # Count data points by category
            category_metrics = self._calculate_category_metrics(extracted_ai_data, processed_fhir_resources)
            metrics['by_category'] = category_metrics
            
            # Count FHIR resources by type
            resource_counts = self._count_fhir_resources(processed_fhir_resources)
            metrics['resource_counts'] = resource_counts
            metrics['processing_metadata']['fhir_resource_types'] = list(resource_counts.keys())
            
            # Calculate overall metrics
            total_extracted = sum(cat['extracted_count'] for cat in category_metrics.values())
            total_captured = sum(cat['captured_count'] for cat in category_metrics.values())
            
            metrics['overall']['total_data_points'] = total_extracted
            metrics['overall']['captured_data_points'] = total_captured
            
            if total_extracted > 0:
                metrics['overall']['capture_rate'] = (total_captured / total_extracted) * 100
            else:
                metrics['overall']['capture_rate'] = 0.0
                
            # Add quality indicators
            metrics['quality_indicators'] = self._calculate_quality_indicators(
                category_metrics, resource_counts
            )
            
            logger.info(f"Metrics calculated: {metrics['overall']['capture_rate']:.1f}% capture rate")
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating metrics: {e}")
            return self._get_empty_metrics()
    
    def _calculate_category_metrics(
        self, 
        extracted_data: Dict[str, Any], 
        fhir_resources: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Calculate metrics for each data category."""
        category_metrics = {}
        
        # Define category mappings (AI extraction field -> FHIR resource type)
        category_mappings = {
            'medications': 'MedicationStatement',
            'diagnostic_reports': 'DiagnosticReport',
            'diagnostics': 'DiagnosticReport',
            'lab_results': 'DiagnosticReport',
            'imaging_studies': 'DiagnosticReport',
            'service_requests': 'ServiceRequest',
            'referrals': 'ServiceRequest',
            'consultations': 'ServiceRequest',
            'encounter': 'Encounter',
            'visit_information': 'Encounter',
            'conditions': 'Condition',
            'diagnoses': 'Condition',
            'procedures': 'Procedure',
            'vital_signs': 'Observation',
            'observations': 'Observation',
            'allergies': 'AllergyIntolerance',
            'care_plans': 'CarePlan',
            'treatment_plans': 'CarePlan',
            'providers': 'Practitioner',
            'organizations': 'Organization'
        }
        
        # Count extracted data points by category
        for category, data in extracted_data.items():
            if category in category_mappings:
                resource_type = category_mappings[category]
                extracted_count = self._count_extracted_items(data)
                captured_count = self._count_captured_resources(fhir_resources, resource_type)
                
                capture_rate = 0.0
                if extracted_count > 0:
                    capture_rate = (captured_count / extracted_count) * 100
                
                category_metrics[category] = {
                    'extracted_count': extracted_count,
                    'captured_count': captured_count,
                    'capture_rate': capture_rate,
                    'fhir_resource_type': resource_type
                }
        
        return category_metrics
    
    def _count_extracted_items(self, data: Any) -> int:
        """Count the number of items in extracted data."""
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            # For single items like encounter
            return 1 if data else 0
        elif isinstance(data, str):
            # For string data, count non-empty strings
            return 1 if data.strip() else 0
        else:
            return 0
    
    def _count_captured_resources(self, fhir_resources: List[Dict[str, Any]], resource_type: str) -> int:
        """Count FHIR resources of a specific type."""
        return len([r for r in fhir_resources if r.get('resourceType') == resource_type])
    
    def _count_fhir_resources(self, fhir_resources: List[Dict[str, Any]]) -> Dict[str, int]:
        """Count FHIR resources by type."""
        resource_counts = {}
        for resource in fhir_resources:
            resource_type = resource.get('resourceType', 'Unknown')
            resource_counts[resource_type] = resource_counts.get(resource_type, 0) + 1
        return resource_counts
    
    def _calculate_quality_indicators(
        self, 
        category_metrics: Dict[str, Dict[str, Any]], 
        resource_counts: Dict[str, int]
    ) -> Dict[str, Any]:
        """Calculate quality indicators for the data capture."""
        indicators = {
            'high_capture_categories': [],
            'low_capture_categories': [],
            'missing_categories': [],
            'resource_diversity': 0,
            'completeness_score': 0.0
        }
        
        # Identify high and low capture categories
        for category, metrics in category_metrics.items():
            capture_rate = metrics['capture_rate']
            if capture_rate >= 90:
                indicators['high_capture_categories'].append({
                    'category': category,
                    'rate': capture_rate
                })
            elif capture_rate < 50:
                indicators['low_capture_categories'].append({
                    'category': category,
                    'rate': capture_rate
                })
        
        # Check for missing expected categories
        expected_categories = [
            'medications', 'diagnostic_reports', 'conditions', 'procedures'
        ]
        for category in expected_categories:
            if category not in category_metrics:
                indicators['missing_categories'].append(category)
        
        # Calculate resource diversity (number of different resource types)
        indicators['resource_diversity'] = len(resource_counts)
        
        # Calculate completeness score (weighted average of important categories)
        important_categories = ['medications', 'conditions', 'diagnostic_reports']
        total_weight = 0
        weighted_sum = 0
        
        for category in important_categories:
            if category in category_metrics:
                weight = 1.0
                rate = category_metrics[category]['capture_rate']
                weighted_sum += weight * rate
                total_weight += weight
        
        if total_weight > 0:
            indicators['completeness_score'] = weighted_sum / total_weight
        
        return indicators
    
    def generate_metrics_report(self, metrics: Dict[str, Any]) -> str:
        """Generate a human-readable metrics report."""
        try:
            report_lines = [
                "=== FHIR Data Capture Metrics Report ===",
                f"Generated: {metrics['processing_metadata']['timestamp']}",
                "",
                "OVERALL PERFORMANCE:",
                f"  • Total Data Points Extracted: {metrics['overall']['total_data_points']}",
                f"  • Data Points Captured in FHIR: {metrics['overall']['captured_data_points']}",
                f"  • Overall Capture Rate: {metrics['overall']['capture_rate']:.1f}%",
                ""
            ]
            
            # Category breakdown
            if metrics['by_category']:
                report_lines.extend([
                    "CAPTURE RATE BY CATEGORY:",
                ])
                for category, cat_metrics in metrics['by_category'].items():
                    rate = cat_metrics['capture_rate']
                    status = "✅" if rate >= 90 else "⚠️" if rate >= 70 else "❌"
                    report_lines.append(
                        f"  {status} {category.replace('_', ' ').title()}: "
                        f"{cat_metrics['captured_count']}/{cat_metrics['extracted_count']} "
                        f"({rate:.1f}%)"
                    )
                report_lines.append("")
            
            # Resource counts
            if metrics['resource_counts']:
                report_lines.extend([
                    "FHIR RESOURCES CREATED:",
                ])
                for resource_type, count in metrics['resource_counts'].items():
                    report_lines.append(f"  • {resource_type}: {count}")
                report_lines.append("")
            
            # Quality indicators
            quality = metrics.get('quality_indicators', {})
            if quality:
                report_lines.extend([
                    "QUALITY INDICATORS:",
                    f"  • Resource Diversity: {quality['resource_diversity']} different types",
                    f"  • Completeness Score: {quality['completeness_score']:.1f}%",
                ])
                
                if quality['high_capture_categories']:
                    report_lines.append("  • High Performance Categories:")
                    for cat in quality['high_capture_categories']:
                        report_lines.append(f"    - {cat['category']}: {cat['rate']:.1f}%")
                
                if quality['low_capture_categories']:
                    report_lines.append("  • Needs Improvement:")
                    for cat in quality['low_capture_categories']:
                        report_lines.append(f"    - {cat['category']}: {cat['rate']:.1f}%")
            
            return "\n".join(report_lines)
            
        except Exception as e:
            logger.error(f"Error generating metrics report: {e}")
            return f"Error generating report: {e}"
    
    def _get_empty_metrics(self) -> Dict[str, Any]:
        """Return empty metrics structure for error cases."""
        return {
            'overall': {
                'total_data_points': 0,
                'captured_data_points': 0,
                'capture_rate': 0.0
            },
            'by_category': {},
            'resource_counts': {},
            'processing_metadata': {
                'timestamp': datetime.now().isoformat(),
                'ai_data_categories': [],
                'fhir_resource_types': [],
                'error': True
            },
            'quality_indicators': {
                'high_capture_categories': [],
                'low_capture_categories': [],
                'missing_categories': [],
                'resource_diversity': 0,
                'completeness_score': 0.0
            }
        }
    
    def calculate_improvement_metrics(
        self, 
        before_metrics: Dict[str, Any], 
        after_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate improvement metrics by comparing before and after capture rates.
        
        Args:
            before_metrics: Metrics from previous processing
            after_metrics: Metrics from current processing
            
        Returns:
            Dictionary containing improvement metrics
        """
        try:
            improvement = {
                'overall_improvement': {
                    'before_rate': before_metrics['overall']['capture_rate'],
                    'after_rate': after_metrics['overall']['capture_rate'],
                    'improvement': after_metrics['overall']['capture_rate'] - before_metrics['overall']['capture_rate']
                },
                'category_improvements': {},
                'new_categories': [],
                'improved_categories': [],
                'declined_categories': []
            }
            
            # Compare category improvements
            before_categories = before_metrics.get('by_category', {})
            after_categories = after_metrics.get('by_category', {})
            
            all_categories = set(before_categories.keys()) | set(after_categories.keys())
            
            for category in all_categories:
                before_rate = before_categories.get(category, {}).get('capture_rate', 0)
                after_rate = after_categories.get(category, {}).get('capture_rate', 0)
                
                improvement['category_improvements'][category] = {
                    'before_rate': before_rate,
                    'after_rate': after_rate,
                    'improvement': after_rate - before_rate
                }
                
                # Categorize improvements
                if category not in before_categories:
                    improvement['new_categories'].append(category)
                elif after_rate > before_rate + 5:  # 5% improvement threshold
                    improvement['improved_categories'].append({
                        'category': category,
                        'improvement': after_rate - before_rate
                    })
                elif after_rate < before_rate - 5:  # 5% decline threshold
                    improvement['declined_categories'].append({
                        'category': category,
                        'decline': before_rate - after_rate
                    })
            
            return improvement
            
        except Exception as e:
            logger.error(f"Error calculating improvement metrics: {e}")
            return {}
