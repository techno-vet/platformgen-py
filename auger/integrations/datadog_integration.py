"""
DataDog Integration Module
Tests and utilities for DataDog API
"""

import requests
from typing import Optional


def test_datadog(config) -> bool:
    """Test DataDog API connection
    
    Args:
        config: AugerConfigManager instance or dict with datadog keys
        
    Returns:
        True if connection successful, False otherwise
    """
    try:
        # Get keys from config
        if hasattr(config, 'get'):
            api_key = config.get('datadog.api_key')
            app_key = config.get('datadog.app_key')
            site = config.get('datadog.site', 'ddog-gov.com')
        else:
            dd_config = config.get('datadog', {})
            api_key = dd_config.get('api_key')
            app_key = dd_config.get('app_key')
            site = dd_config.get('site', 'ddog-gov.com')
        
        if not api_key or api_key.startswith('${'):
            print("DataDog API key not configured")
            return False
        
        if not app_key or app_key.startswith('${'):
            print("DataDog Application key not configured")
            return False
        
        # Test API call
        url = f"https://api.{site}/api/v1/validate"
        headers = {
            'DD-API-KEY': api_key,
            'DD-APPLICATION-KEY': app_key
        }
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('valid'):
                print("DataDog API keys valid")
                return True
            else:
                print("DataDog API keys invalid")
                return False
        else:
            print(f"DataDog API returned: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error testing DataDog: {e}")
        return False
