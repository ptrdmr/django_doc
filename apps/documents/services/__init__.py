"""
Document processing services package.
"""

# Import the main classes from the parent services.py module
# This resolves the Python import priority issue where the package directory
# takes precedence over the services.py module file

import sys
import os

# Add the parent directory to the path to import from services.py
parent_dir = os.path.dirname(os.path.dirname(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Import from the services.py file (not the package)
try:
    import importlib.util
    services_file = os.path.join(os.path.dirname(__file__), '..', 'services.py')
    spec = importlib.util.spec_from_file_location("services_module", services_file)
    services_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(services_module)
    
    # Extract the classes we need
    PDFTextExtractor = services_module.PDFTextExtractor
    DocumentAnalyzer = services_module.DocumentAnalyzer
    APIRateLimitError = services_module.APIRateLimitError
    
    # Make them available for import
    __all__ = ['PDFTextExtractor', 'DocumentAnalyzer', 'APIRateLimitError']
    
except Exception as e:
    # Fallback: define minimal classes to prevent import errors
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Failed to import from services.py: {e}")
    
    class PDFTextExtractor:
        def __init__(self):
            pass
        def extract_text(self, file_path):
            return {'success': False, 'error': 'Service unavailable'}
    
    class DocumentAnalyzer:
        def __init__(self, document=None):
            pass
    
    class APIRateLimitError(Exception):
        pass
    
    __all__ = ['PDFTextExtractor', 'DocumentAnalyzer', 'APIRateLimitError']