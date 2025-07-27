#!/usr/bin/env python
"""
Minimal test that bypasses Django to test DocumentAnalyzer imports.
"""
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test basic imports without Django"""
    print("🔧 Testing basic imports...")
    
    try:
        import anthropic
        print("✅ anthropic imports successfully")
    except ImportError as e:
        print(f"❌ anthropic import failed: {e}")
    
    try:
        import openai  
        print("✅ openai imports successfully")
    except ImportError as e:
        print(f"❌ openai import failed: {e}")
        
    try:
        import httpx
        print("✅ httpx imports successfully") 
    except ImportError as e:
        print(f"❌ httpx import failed: {e}")
    
    print("🎉 Basic import test completed!")

if __name__ == "__main__":
    test_imports() 