"""
GitHub Integration Module
Tests and utilities for GitHub API
"""

import requests
from typing import Optional


def test_github(config) -> bool:
    """Test GitHub API connection
    
    Args:
        config: AugerConfigManager instance or dict with github.token
        
    Returns:
        True if connection successful, False otherwise
    """
    try:
        # Get token from config
        if hasattr(config, 'get'):
            token = config.get('github.token')
        else:
            token = config.get('github', {}).get('token')
        
        if not token or token.startswith('${'):
            print("GitHub token not configured")
            return False
        
        # Test API call
        headers = {'Authorization': f'token {token}'}
        response = requests.get('https://api.github.com/user', headers=headers, timeout=10)
        
        if response.status_code == 200:
            user = response.json()
            print(f"Connected as: {user.get('login', 'Unknown')}")
            return True
        else:
            print(f"GitHub API returned: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error testing GitHub: {e}")
        return False
