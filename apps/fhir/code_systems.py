"""
FHIR Code System Mapping and Normalization

This module provides comprehensive mapping and normalization capabilities for medical
code systems including LOINC, SNOMED CT, ICD-10, CPT, and others. It enables
intelligent matching, conversion, and confidence scoring for medical codes to improve
deduplication and conflict detection in FHIR merge operations.
"""

import re
import json
import logging
from typing import Dict, List, Optional, Tuple, Any, Set
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
import hashlib

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


@dataclass
class CodeMapping:
    """Represents a mapping between different code systems."""
    source_code: str
    source_system: str
    target_code: str
    target_system: str
    confidence: float  # 0.0 to 1.0
    mapping_type: str  # 'exact', 'equivalent', 'broader', 'narrower', 'related'
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedCode:
    """Represents a normalized medical code with system information."""
    code: str
    system: str
    system_uri: str
    display: Optional[str] = None
    original_code: Optional[str] = None
    original_system: Optional[str] = None
    confidence: float = 1.0
    normalization_notes: List[str] = field(default_factory=list)


@dataclass
class CodeSystemInfo:
    """Information about a medical code system."""
    name: str
    uri: str
    description: str
    pattern: str  # Regex pattern for code validation
    example_codes: List[str]
    authoritative: bool = True  # Whether this is an official code system


class CodeSystemRegistry:
    """Registry of supported medical code systems."""
    
    SYSTEMS = {
        'LOINC': CodeSystemInfo(
            name='LOINC',
            uri='http://loinc.org',
            description='Logical Observation Identifiers Names and Codes',
            pattern=r'^\d{1,5}-\d$',
            example_codes=['8480-6', '8462-4', '2093-3', '33747-0'],
            authoritative=True
        ),
        'SNOMED': CodeSystemInfo(
            name='SNOMED CT',
            uri='http://snomed.info/sct',
            description='Systematized Nomenclature of Medicine Clinical Terms',
            pattern=r'^\d{6,18}$',
            example_codes=['386661006', '44054006', '271649006', '162864005'],
            authoritative=True
        ),
        'ICD-10-CM': CodeSystemInfo(
            name='ICD-10-CM',
            uri='http://hl7.org/fhir/sid/icd-10-cm',
            description='International Classification of Diseases, 10th Revision, Clinical Modification',
            pattern=r'^[A-TV-Z]\d{2}(\.[A-TV-Z0-9]{1,4})?$',
            example_codes=['E11.9', 'I10', 'Z51.11', 'F41.1'],
            authoritative=True
        ),
        'ICD-10': CodeSystemInfo(
            name='ICD-10',
            uri='http://hl7.org/fhir/sid/icd-10',
            description='International Classification of Diseases, 10th Revision',
            pattern=r'^[A-Z]\d{2}(\.\d{1,2})?$',
            example_codes=['E11', 'I10', 'Z51', 'F41'],
            authoritative=True
        ),
        'CPT': CodeSystemInfo(
            name='CPT',
            uri='http://www.ama-assn.org/go/cpt',
            description='Current Procedural Terminology',
            pattern=r'^\d{5}$',
            example_codes=['99213', '99214', '80053', '36415'],
            authoritative=True
        ),
        'RxNorm': CodeSystemInfo(
            name='RxNorm',
            uri='http://www.nlm.nih.gov/research/umls/rxnorm',
            description='Normalized names for clinical drugs',
            pattern=r'^\d{1,8}$',
            example_codes=['161', '8640', '197361', '313782'],
            authoritative=True
        ),
        'UCUM': CodeSystemInfo(
            name='UCUM',
            uri='http://unitsofmeasure.org',
            description='Unified Code for Units of Measure',
            pattern=r'^[a-zA-Z0-9/\[\]{}.*-]+$',  # UCUM has specific character set
            example_codes=['mg/dL', 'mmol/L', 'g/L', 'IU/L'],
            authoritative=True
        )
    }
    
    @classmethod
    def get_system_info(cls, system_name: str) -> Optional[CodeSystemInfo]:
        """Get information about a code system."""
        return cls.SYSTEMS.get(system_name.upper())
    
    @classmethod
    def get_all_systems(cls) -> List[str]:
        """Get list of all supported system names."""
        return list(cls.SYSTEMS.keys())
    
    @classmethod
    def validate_code_format(cls, code: str, system: str) -> bool:
        """Validate that a code matches the expected format for its system."""
        system_info = cls.get_system_info(system)
        if not system_info:
            return False
        return bool(re.match(system_info.pattern, code))


class CodeSystemDetector:
    """Detects code systems based on code patterns and context."""
    
    @staticmethod
    def detect_system(code: str, context: Optional[str] = None) -> Tuple[str, float]:
        """
        Detect the most likely code system for a given code.
        
        Args:
            code: The medical code to analyze
            context: Optional context (e.g., "lab", "diagnosis", "procedure")
            
        Returns:
            Tuple of (system_name, confidence_score)
        """
        if not code:
            return 'UNKNOWN', 0.0
        
        # Clean and normalize the code
        clean_code = re.sub(r'[^\w\.-]', '', str(code)).strip()
        if not clean_code:
            return 'UNKNOWN', 0.0
        
        # Check each system's pattern
        matches = []
        for system_name, system_info in CodeSystemRegistry.SYSTEMS.items():
            if re.match(system_info.pattern, clean_code):
                confidence = 0.8  # Base confidence for pattern match
                
                # Boost confidence based on context
                if context:
                    confidence += CodeSystemDetector._get_context_boost(
                        system_name, context.lower()
                    )
                
                # Boost confidence for more specific patterns
                if system_name == 'LOINC' and '-' in clean_code:
                    confidence += 0.1
                elif system_name == 'ICD-10-CM' and '.' in clean_code:
                    confidence += 0.1
                elif system_name == 'SNOMED' and len(clean_code) >= 8:
                    confidence += 0.1
                
                matches.append((system_name, min(confidence, 1.0)))
        
        if not matches:
            return 'UNKNOWN', 0.0
        
        # Return the highest confidence match
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0]
    
    @staticmethod
    def _get_context_boost(system: str, context: str) -> float:
        """Get confidence boost based on context clues."""
        context_mappings = {
            'LOINC': ['lab', 'laboratory', 'test', 'observation', 'vital'],
            'ICD-10-CM': ['diagnosis', 'condition', 'disease', 'disorder'],
            'ICD-10': ['diagnosis', 'condition', 'disease', 'disorder'],
            'CPT': ['procedure', 'surgery', 'treatment', 'service'],
            'SNOMED': ['clinical', 'assessment', 'finding'],
            'RxNorm': ['medication', 'drug', 'prescription', 'medicine'],
            'UCUM': ['unit', 'measure', 'quantity']
        }
        
        system_contexts = context_mappings.get(system, [])
        for ctx in system_contexts:
            if ctx in context:
                return 0.15
        return 0.0


class FuzzyCodeMatcher:
    """Provides fuzzy matching capabilities for medical codes."""
    
    def __init__(self, similarity_threshold: float = 0.8):
        self.similarity_threshold = similarity_threshold
    
    def find_similar_codes(
        self, 
        target_code: str, 
        candidate_codes: List[str],
        max_results: int = 10
    ) -> List[Tuple[str, float]]:
        """
        Find codes similar to the target code.
        
        Args:
            target_code: Code to find matches for
            candidate_codes: List of potential matching codes
            max_results: Maximum number of results to return
            
        Returns:
            List of (code, similarity_score) tuples, sorted by similarity
        """
        if not target_code or not candidate_codes:
            return []
        
        similarities = []
        target_normalized = self._normalize_for_comparison(target_code)
        
        for candidate in candidate_codes:
            candidate_normalized = self._normalize_for_comparison(candidate)
            
            # Calculate multiple similarity metrics
            sequence_sim = SequenceMatcher(None, target_normalized, candidate_normalized).ratio()
            
            # Boost similarity for codes that are structurally similar
            structure_sim = self._calculate_structure_similarity(target_code, candidate)
            
            # Combined similarity score
            final_similarity = (sequence_sim * 0.7) + (structure_sim * 0.3)
            
            if final_similarity >= self.similarity_threshold:
                similarities.append((candidate, final_similarity))
        
        # Sort by similarity and return top results
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:max_results]
    
    def _normalize_for_comparison(self, code: str) -> str:
        """Normalize code for similarity comparison."""
        # Remove punctuation and convert to lowercase
        normalized = re.sub(r'[^\w]', '', str(code)).lower()
        return normalized
    
    def _calculate_structure_similarity(self, code1: str, code2: str) -> float:
        """Calculate structural similarity between codes."""
        # Check if codes have similar patterns (letters, numbers, punctuation)
        pattern1 = re.sub(r'\w', 'X', code1)  # Replace word chars with X
        pattern1 = re.sub(r'\d', '9', pattern1)  # Replace digits with 9
        
        pattern2 = re.sub(r'\w', 'X', code2)
        pattern2 = re.sub(r'\d', '9', pattern2)
        
        if pattern1 == pattern2:
            return 1.0
        else:
            return SequenceMatcher(None, pattern1, pattern2).ratio()


class CodeSystemMapper:
    """Main class for code system mapping and normalization."""
    
    def __init__(self, enable_caching: bool = True):
        self.enable_caching = enable_caching
        self.detector = CodeSystemDetector()
        self.fuzzy_matcher = FuzzyCodeMatcher()
        self.mappings_cache = {}
        
        # Load predefined mappings if available
        self._load_predefined_mappings()
    
    def normalize_code(
        self, 
        code: str, 
        system: Optional[str] = None,
        context: Optional[str] = None,
        display: Optional[str] = None
    ) -> NormalizedCode:
        """
        Normalize a medical code to standard format.
        
        Args:
            code: The medical code to normalize
            system: Known code system (optional)
            context: Context for system detection (optional)
            display: Human-readable description (optional)
            
        Returns:
            NormalizedCode with normalized information
        """
        if not code:
            raise ValueError("Code cannot be empty")
        
        original_code = str(code)
        original_system = system
        notes = []
        
        # Clean the code
        cleaned_code = self._clean_code(original_code)
        notes.append(f"Cleaned code from '{original_code}' to '{cleaned_code}'")
        
        # Detect system if not provided
        if not system:
            detected_system, confidence = self.detector.detect_system(cleaned_code, context)
            system = detected_system
            if detected_system != 'UNKNOWN':
                notes.append(f"Detected system: {detected_system} (confidence: {confidence:.2f})")
        else:
            confidence = 1.0
        
        # Validate system
        system_info = CodeSystemRegistry.get_system_info(system)
        if not system_info:
            logger.warning(f"Unknown code system: {system}")
            system = 'UNKNOWN'
            confidence = 0.0
        
        # Validate code format
        if system != 'UNKNOWN' and not CodeSystemRegistry.validate_code_format(cleaned_code, system):
            notes.append(f"Code format validation failed for system {system}")
            confidence *= 0.5  # Reduce confidence
        
        # Get system URI
        system_uri = system_info.uri if system_info else 'http://unknown.org'
        
        return NormalizedCode(
            code=cleaned_code,
            system=system,
            system_uri=system_uri,
            display=display,
            original_code=original_code,
            original_system=original_system,
            confidence=confidence,
            normalization_notes=notes
        )
    
    def find_equivalent_codes(
        self, 
        source_code: str, 
        source_system: str,
        target_systems: Optional[List[str]] = None
    ) -> List[CodeMapping]:
        """
        Find equivalent codes in other systems.
        
        Args:
            source_code: Source code to map
            source_system: Source code system
            target_systems: Target systems to map to (optional)
            
        Returns:
            List of CodeMapping objects
        """
        if not target_systems:
            target_systems = [s for s in CodeSystemRegistry.get_all_systems() 
                            if s != source_system.upper()]
        
        mappings = []
        
        # Check cache first
        cache_key = self._get_mapping_cache_key(source_code, source_system, target_systems)
        if self.enable_caching and cache_key in self.mappings_cache:
            return self.mappings_cache[cache_key]
        
        # Look for exact mappings in predefined mappings
        exact_mappings = self._find_exact_mappings(source_code, source_system, target_systems)
        mappings.extend(exact_mappings)
        
        # Look for fuzzy matches if no exact matches found
        if not exact_mappings:
            fuzzy_mappings = self._find_fuzzy_mappings(source_code, source_system, target_systems)
            mappings.extend(fuzzy_mappings)
        
        # Cache results
        if self.enable_caching:
            self.mappings_cache[cache_key] = mappings
        
        return mappings
    
    def _clean_code(self, code: str) -> str:
        """Clean and normalize code format."""
        # Remove extra whitespace
        cleaned = str(code).strip()
        
        # Normalize case for certain systems
        if re.match(r'^[A-Za-z]\d{2}', cleaned):  # ICD-10 pattern (case insensitive)
            cleaned = cleaned.upper()
        
        return cleaned
    
    def _load_predefined_mappings(self):
        """Load predefined code mappings from configuration."""
        # This would typically load from a database or configuration file
        # For now, we'll define some common mappings
        self.predefined_mappings = {
            # Common lab test mappings between LOINC and local codes
            ('2093-3', 'LOINC'): [
                CodeMapping('2093-3', 'LOINC', 'CHOL', 'LOCAL', 1.0, 'exact', 'Total Cholesterol')
            ],
            # Common diagnosis mappings between ICD-10 and SNOMED
            ('E11.9', 'ICD-10-CM'): [
                CodeMapping('E11.9', 'ICD-10-CM', '44054006', 'SNOMED', 0.95, 'equivalent', 'Type 2 diabetes mellitus')
            ]
        }
    
    def _find_exact_mappings(
        self, 
        source_code: str, 
        source_system: str,
        target_systems: List[str]
    ) -> List[CodeMapping]:
        """Find exact mappings in predefined mappings."""
        mappings = []
        key = (source_code, source_system.upper())
        
        if key in self.predefined_mappings:
            for mapping in self.predefined_mappings[key]:
                if mapping.target_system.upper() in [s.upper() for s in target_systems]:
                    mappings.append(mapping)
        
        return mappings
    
    def _find_fuzzy_mappings(
        self, 
        source_code: str, 
        source_system: str,
        target_systems: List[str]
    ) -> List[CodeMapping]:
        """Find fuzzy mappings using similarity algorithms."""
        mappings = []
        
        # This is a simplified implementation
        # In a real system, this would query external terminology services
        # or use machine learning models for code mapping
        
        for target_system in target_systems:
            system_info = CodeSystemRegistry.get_system_info(target_system)
            if system_info and system_info.example_codes:
                # Find similar codes in example codes (demonstration only)
                similar_codes = self.fuzzy_matcher.find_similar_codes(
                    source_code, 
                    system_info.example_codes,
                    max_results=3
                )
                
                for similar_code, similarity in similar_codes:
                    if similarity > 0.8:  # High similarity threshold
                        mappings.append(CodeMapping(
                            source_code=source_code,
                            source_system=source_system,
                            target_code=similar_code,
                            target_system=target_system,
                            confidence=similarity * 0.7,  # Reduce confidence for fuzzy matches
                            mapping_type='related',
                            description=f'Fuzzy match (similarity: {similarity:.2f})'
                        ))
        
        return mappings
    
    def _get_mapping_cache_key(
        self, 
        source_code: str, 
        source_system: str,
        target_systems: List[str]
    ) -> str:
        """Generate cache key for mapping results."""
        key_data = f"{source_code}|{source_system}|{','.join(sorted(target_systems))}"
        return hashlib.md5(key_data.encode()).hexdigest()
    
    @lru_cache(maxsize=1000)
    def get_system_uri(self, system_name: str) -> str:
        """Get the standard URI for a code system."""
        system_info = CodeSystemRegistry.get_system_info(system_name)
        return system_info.uri if system_info else 'http://unknown.org'
    
    def get_mapping_statistics(self) -> Dict[str, Any]:
        """Get statistics about code mappings."""
        return {
            'total_cached_mappings': len(self.mappings_cache),
            'supported_systems': len(CodeSystemRegistry.SYSTEMS),
            'predefined_mappings': len(self.predefined_mappings),
            'cache_enabled': self.enable_caching
        }


# Global instance for easy access
default_code_mapper = CodeSystemMapper()
