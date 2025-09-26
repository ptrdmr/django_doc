#!/usr/bin/env python
"""
Comprehensive test runner for the document processing pipeline.

This script runs the complete test suite created for Task 34.12, providing
organized test execution and reporting for all test categories.

Usage:
    python run_comprehensive_tests.py [options]
    
Options:
    --unit           Run only unit tests
    --integration    Run only integration tests  
    --ui             Run only UI tests
    --performance    Run only performance tests
    --security       Run only security tests
    --e2e            Run only end-to-end tests
    --all            Run all tests (default)
    --coverage       Run tests with coverage reporting
    --verbose        Enable verbose output
    --parallel       Run tests in parallel
    --fast           Skip slow tests
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set Django settings module for testing
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'meddocparser.settings.test')

import django
django.setup()


class ComprehensiveTestRunner:
    """Test runner for the comprehensive document processing pipeline tests."""
    
    def __init__(self):
        self.project_root = PROJECT_ROOT
        self.test_categories = {
            'unit': 'apps/documents/test_comprehensive_pipeline.py::AIExtractionUnitTests',
            'integration': 'apps/documents/test_comprehensive_pipeline.py::DocumentPipelineIntegrationTests',
            'ui': 'apps/documents/test_comprehensive_pipeline.py::ReviewInterfaceTests',
            'performance': 'apps/documents/test_comprehensive_pipeline.py::DocumentProcessingPerformanceTests',
            'security': 'apps/documents/test_comprehensive_pipeline.py::SecurityAndAuditTests', 
            'e2e': 'apps/documents/test_comprehensive_pipeline.py::EndToEndWorkflowTests'
        }
    
    def run_tests(self, categories=None, coverage=False, verbose=False, parallel=False, fast=False):
        """Run the specified test categories."""
        if not categories:
            categories = ['all']
        
        # Build pytest command
        cmd = ['python', '-m', 'pytest']
        
        # Add test targets
        if 'all' in categories:
            cmd.append('apps/documents/test_comprehensive_pipeline.py')
        else:
            for category in categories:
                if category in self.test_categories:
                    cmd.append(self.test_categories[category])
        
        # Add options
        if verbose:
            cmd.append('-v')
        else:
            cmd.append('-q')
        
        if coverage:
            cmd.extend([
                '--cov=apps.documents',
                '--cov=apps.fhir',
                '--cov-report=html',
                '--cov-report=term-missing',
                '--cov-fail-under=80'
            ])
        
        if parallel:
            cmd.extend(['-n', 'auto'])
        
        if fast:
            cmd.extend(['-m', 'not slow'])
        
        # Add markers for organization
        cmd.extend([
            '--tb=short',
            '--strict-markers'
        ])
        
        print(f"Running command: {' '.join(cmd)}")
        print("=" * 80)
        
        # Execute tests
        try:
            result = subprocess.run(cmd, cwd=self.project_root, check=False)
            return result.returncode
        except KeyboardInterrupt:
            print("\nTest execution interrupted by user")
            return 1
        except Exception as e:
            print(f"Error running tests: {e}")
            return 1
    
    def run_specific_test_suite(self, suite_name):
        """Run a specific test suite with appropriate configuration."""
        suites = {
            'quick': {
                'markers': 'unit and not slow',
                'description': 'Quick unit tests only'
            },
            'smoke': {
                'markers': 'not slow and not ui',
                'description': 'Fast smoke tests'
            },
            'full': {
                'markers': '',
                'description': 'Complete test suite'
            },
            'ci': {
                'markers': 'not ui and not performance',
                'description': 'CI-friendly tests (no UI/performance)'
            }
        }
        
        if suite_name not in suites:
            print(f"Unknown test suite: {suite_name}")
            print(f"Available suites: {', '.join(suites.keys())}")
            return 1
        
        suite = suites[suite_name]
        print(f"Running {suite_name} test suite: {suite['description']}")
        
        cmd = ['python', '-m', 'pytest', 'apps/documents/test_comprehensive_pipeline.py']
        
        if suite['markers']:
            cmd.extend(['-m', suite['markers']])
        
        if suite_name == 'full':
            cmd.extend(['--cov=apps.documents', '--cov-report=html'])
        
        cmd.extend(['-v', '--tb=short'])
        
        print(f"Command: {' '.join(cmd)}")
        print("=" * 80)
        
        try:
            result = subprocess.run(cmd, cwd=self.project_root, check=False)
            return result.returncode
        except Exception as e:
            print(f"Error running test suite: {e}")
            return 1
    
    def validate_test_environment(self):
        """Validate that the test environment is properly configured."""
        print("Validating test environment...")
        
        # Check Django settings
        from django.conf import settings
        if not settings.TESTING:
            print("Warning: TESTING flag not set in settings")
        
        # Check test database
        if 'test' not in settings.DATABASES['default']['NAME']:
            print(f"Using database: {settings.DATABASES['default']['NAME']}")
        
        # Check required packages
        required_packages = [
            'pytest',
            'pytest-django', 
            'pytest-cov',
            'coverage'
        ]
        
        missing_packages = []
        for package in required_packages:
            try:
                __import__(package.replace('-', '_'))
            except ImportError:
                missing_packages.append(package)
        
        if missing_packages:
            print(f"Missing required packages: {', '.join(missing_packages)}")
            print("Install with: pip install " + " ".join(missing_packages))
            return False
        
        print("Test environment validation passed ✓")
        return True
    
    def generate_test_report(self):
        """Generate a comprehensive test report."""
        print("Generating test report...")
        
        # Run all tests with coverage
        cmd = [
            'python', '-m', 'pytest',
            'apps/documents/test_comprehensive_pipeline.py',
            '--cov=apps.documents',
            '--cov=apps.fhir', 
            '--cov-report=html:htmlcov',
            '--cov-report=xml:coverage.xml',
            '--cov-report=term-missing',
            '--junit-xml=test-results.xml',
            '-v'
        ]
        
        try:
            result = subprocess.run(cmd, cwd=self.project_root, check=False)
            
            if result.returncode == 0:
                print("\n" + "=" * 80)
                print("✅ TEST REPORT GENERATED SUCCESSFULLY")
                print("=" * 80)
                print(f"📊 HTML Coverage Report: file://{self.project_root}/htmlcov/index.html")
                print(f"📋 XML Coverage Report: {self.project_root}/coverage.xml")
                print(f"🧪 JUnit Test Results: {self.project_root}/test-results.xml")
            else:
                print("\n" + "=" * 80)
                print("❌ SOME TESTS FAILED")
                print("=" * 80)
                
            return result.returncode
            
        except Exception as e:
            print(f"Error generating test report: {e}")
            return 1


def main():
    """Main entry point for the test runner."""
    parser = argparse.ArgumentParser(
        description='Comprehensive test runner for document processing pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_comprehensive_tests.py --unit --verbose
  python run_comprehensive_tests.py --integration --coverage
  python run_comprehensive_tests.py --all --coverage --parallel
  python run_comprehensive_tests.py --suite quick
  python run_comprehensive_tests.py --report
        """
    )
    
    # Test category options
    parser.add_argument('--unit', action='store_true', help='Run unit tests')
    parser.add_argument('--integration', action='store_true', help='Run integration tests')
    parser.add_argument('--ui', action='store_true', help='Run UI tests')
    parser.add_argument('--performance', action='store_true', help='Run performance tests')
    parser.add_argument('--security', action='store_true', help='Run security tests')
    parser.add_argument('--e2e', action='store_true', help='Run end-to-end tests')
    parser.add_argument('--all', action='store_true', help='Run all tests (default)')
    
    # Test suite options
    parser.add_argument('--suite', choices=['quick', 'smoke', 'full', 'ci'], 
                       help='Run predefined test suite')
    
    # Execution options
    parser.add_argument('--coverage', action='store_true', help='Run with coverage reporting')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--parallel', action='store_true', help='Run tests in parallel')
    parser.add_argument('--fast', action='store_true', help='Skip slow tests')
    
    # Utility options
    parser.add_argument('--validate', action='store_true', help='Validate test environment')
    parser.add_argument('--report', action='store_true', help='Generate comprehensive test report')
    
    args = parser.parse_args()
    
    runner = ComprehensiveTestRunner()
    
    # Handle utility commands
    if args.validate:
        return 0 if runner.validate_test_environment() else 1
    
    if args.report:
        return runner.generate_test_report()
    
    # Handle test suite commands
    if args.suite:
        return runner.run_specific_test_suite(args.suite)
    
    # Validate environment before running tests
    if not runner.validate_test_environment():
        return 1
    
    # Determine which test categories to run
    categories = []
    if args.unit:
        categories.append('unit')
    if args.integration:
        categories.append('integration')
    if args.ui:
        categories.append('ui')
    if args.performance:
        categories.append('performance')
    if args.security:
        categories.append('security')
    if args.e2e:
        categories.append('e2e')
    if args.all or not categories:
        categories = ['all']
    
    # Run tests
    return runner.run_tests(
        categories=categories,
        coverage=args.coverage,
        verbose=args.verbose,
        parallel=args.parallel,
        fast=args.fast
    )


if __name__ == '__main__':
    sys.exit(main())
