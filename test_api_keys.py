#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test script to validate API keys for Anthropic, OpenAI, and Perplexity.
Usage: python test_api_keys.py
"""

import os
import sys
from decouple import config

# Simple status indicators (no special Unicode)
def success(msg):
    return f"[OK] {msg}"

def error(msg):
    return f"[FAIL] {msg}"

def warning(msg):
    return f"[WARN] {msg}"


def test_anthropic_key():
    """Test Anthropic API key."""
    print("\n" + "="*60)
    print("Testing Anthropic (Claude) API Key...")
    print("="*60)
    
    api_key = config('ANTHROPIC_API_KEY', default=None)
    
    if not api_key:
        print(error("ANTHROPIC_API_KEY not found in environment"))
        return False
    
    # Show key with full length info
    print(f"API Key: {api_key[:20]}...{api_key[-10:]} (length: {len(api_key)})")
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        
        # Make a minimal test request
        message = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Say 'test'"}
            ]
        )
        
        print(success("Anthropic API key is VALID"))
        print(f"Response: {message.content[0].text}")
        return True
        
    except anthropic.AuthenticationError as e:
        print(error(f"Authentication failed: {e}"))
        return False
    except Exception as e:
        print(error(f"Error: {e}"))
        return False


def test_openai_key():
    """Test OpenAI API key."""
    print("\n" + "="*60)
    print("Testing OpenAI (GPT) API Key...")
    print("="*60)
    
    api_key = config('OPENAI_API_KEY', default=None)
    
    if not api_key:
        print(error("OPENAI_API_KEY not found in environment"))
        return False
    
    print(f"API Key: {api_key[:20]}...{api_key[-10:]} (length: {len(api_key)})")
    
    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        
        # Make a minimal test request
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Say 'test'"}
            ]
        )
        
        print(success("OpenAI API key is VALID"))
        print(f"Response: {response.choices[0].message.content}")
        return True
        
    except openai.AuthenticationError as e:
        print(error(f"Authentication failed: {e}"))
        return False
    except Exception as e:
        print(error(f"Error: {e}"))
        return False


def test_perplexity_key():
    """Test Perplexity API key."""
    print("\n" + "="*60)
    print("Testing Perplexity API Key...")
    print("="*60)
    
    api_key = config('PERPLEXITY_API_KEY', default=None)
    
    if not api_key:
        print(error("PERPLEXITY_API_KEY not found in environment"))
        return False
    
    print(f"API Key: {api_key[:20]}...{api_key[-10:]} (length: {len(api_key)})")
    
    try:
        import openai
        # Perplexity uses OpenAI-compatible API
        client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.perplexity.ai"
        )
        
        # Make a minimal test request - using newer model format
        response = client.chat.completions.create(
            model="llama-3.1-sonar-small-128k",
            max_tokens=10,
            messages=[
                {"role": "user", "content": "Say 'test'"}
            ]
        )
        
        print(success("Perplexity API key is VALID"))
        print(f"Response: {response.choices[0].message.content}")
        return True
        
    except openai.AuthenticationError as e:
        print(error(f"Authentication failed: {e}"))
        return False
    except Exception as e:
        print(error(f"Error: {e}"))
        return False


def main():
    """Run all API key tests."""
    print("\n" + "="*60)
    print("API KEY VALIDATION TESTS")
    print("="*60)
    
    results = {
        'Anthropic': test_anthropic_key(),
        'OpenAI': test_openai_key(),
        'Perplexity': test_perplexity_key()
    }
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for service, valid in results.items():
        status = "[OK] VALID" if valid else "[FAIL] INVALID"
        print(f"{service:20} {status}")
    
    print("="*60 + "\n")
    
    # Exit code
    if all(results.values()):
        print("All API keys are working!\n")
        sys.exit(0)
    else:
        print("[WARN] Some API keys failed validation. Check the errors above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

