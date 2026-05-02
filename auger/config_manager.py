#!/usr/bin/env python3
"""
Auger Configuration Manager
Handles configuration files, defaults, and environment variables
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv, set_key
from auger.runtime import state_dir


class AugerConfigManager:
    """Manages Auger configuration with defaults, user config, and env vars"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize config manager
        
        Args:
            config_dir: Custom config directory (default: runtime state dir)
        """
        self.config_dir = config_dir or state_dir()
        self.config_file = self.config_dir / 'config.yaml'
        self.env_file = self.config_dir / '.env'
        
        # Load configurations
        self.defaults = self._get_defaults()
        self.user_config = self._load_user_config()
        
        # Load environment variables
        if self.env_file.exists():
            load_dotenv(self.env_file)
    
    def _get_defaults(self) -> Dict[str, Any]:
        """Get default configuration"""
        return {
            'display': ':1',
            'port': 6000,
            'theme': 'dark',
            'log_level': 'INFO',
            'hot_reload': True,
            'widgets_enabled': [
                'chat',
                'github',
                'pods',
                'cryptkeeper_lite',
                'servicenow',
            ],
            'github': {
                'token': '${GITHUB_TOKEN}',
            },
            'datadog': {
                'api_key': '${DATADOG_API_KEY}',
                'app_key': '${DATADOG_APP_KEY}',
                'site': 'ddog-gov.com',
            },
            'servicenow': {
                'url': 'https://gsassistprod.servicenowservices.com',
                'cookies': '${SERVICENOW_COOKIES}',
            }
        }
    
    def _load_user_config(self) -> Dict[str, Any]:
        """Load user configuration from file"""
        if not self.config_file.exists():
            return {}
        
        try:
            with open(self.config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Error loading config: {e}")
            return {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value with precedence: env > user > defaults
        
        Args:
            key: Config key (can be nested with dots, e.g., 'github.token')
            default: Default value if not found
            
        Returns:
            Config value
        """
        # Split nested keys
        keys = key.split('.')
        
        # Try user config first
        value = self.user_config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                value = None
                break
        
        # If not in user config, try defaults
        if value is None:
            value = self.defaults
            for k in keys:
                if isinstance(value, dict) and k in value:
                    value = value[k]
                else:
                    value = None
                    break
        
        # If still None, use provided default
        if value is None:
            return default
        
        # Substitute environment variables
        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
            env_key = value[2:-1]
            return os.getenv(env_key, default)
        
        return value
    
    def set(self, key: str, value: Any, save: bool = True):
        """Set config value
        
        Args:
            key: Config key (can be nested with dots)
            value: Value to set
            save: Whether to save to file immediately
        """
        keys = key.split('.')
        
        # Navigate to the nested dict
        current = self.user_config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Set the value
        current[keys[-1]] = value
        
        if save:
            self.save()
    
    def save(self):
        """Save user configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_file, 'w') as f:
            yaml.dump(self.user_config, f, default_flow_style=False, sort_keys=False)
        
        # Secure the config file
        os.chmod(self.config_file, 0o600)
    
    def init(self, github_token: str, datadog_api_key: Optional[str] = None,
             datadog_app_key: Optional[str] = None, servicenow_url: Optional[str] = None):
        """Initialize Auger configuration
        
        Args:
            github_token: GitHub personal access token (required)
            datadog_api_key: DataDog API key (optional)
            datadog_app_key: DataDog Application key (optional)
            servicenow_url: ServiceNow instance URL (optional)
        """
        # Create config directory
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Save tokens to .env
        self._save_env('GITHUB_TOKEN', github_token)
        
        if datadog_api_key:
            self._save_env('DATADOG_API_KEY', datadog_api_key)
        if datadog_app_key:
            self._save_env('DATADOG_APP_KEY', datadog_app_key)
        
        # Create config.yaml with defaults
        config = self._get_defaults()
        
        # Update ServiceNow URL if provided
        if servicenow_url:
            config['servicenow']['url'] = servicenow_url
        
        self.user_config = config
        self.save()
        
        # Secure the .env file
        if self.env_file.exists():
            os.chmod(self.env_file, 0o600)
    
    def _save_env(self, key: str, value: str):
        """Save value to .env file
        
        Args:
            key: Environment variable name
            value: Environment variable value
        """
        # Create .env if it doesn't exist
        if not self.env_file.exists():
            self.env_file.touch()
            os.chmod(self.env_file, 0o600)
        
        set_key(self.env_file, key, value)
    
    def is_widget_enabled(self, widget_name: str) -> bool:
        """Check if a widget is enabled
        
        Args:
            widget_name: Name of the widget
            
        Returns:
            True if enabled, False otherwise
        """
        enabled_widgets = self.get('widgets_enabled', [])
        return widget_name in enabled_widgets
    
    def enable_widget(self, widget_name: str):
        """Enable a widget
        
        Args:
            widget_name: Name of the widget
        """
        enabled_widgets = self.get('widgets_enabled', [])
        if widget_name not in enabled_widgets:
            enabled_widgets.append(widget_name)
            self.set('widgets_enabled', enabled_widgets)
    
    def disable_widget(self, widget_name: str):
        """Disable a widget
        
        Args:
            widget_name: Name of the widget
        """
        enabled_widgets = self.get('widgets_enabled', [])
        if widget_name in enabled_widgets:
            enabled_widgets.remove(widget_name)
            self.set('widgets_enabled', enabled_widgets)
    
    def to_dict(self) -> Dict[str, Any]:
        """Get full configuration as dictionary
        
        Returns:
            Complete configuration (with env vars substituted)
        """
        result = {}
        
        def _substitute(obj):
            """Recursively substitute environment variables"""
            if isinstance(obj, dict):
                return {k: _substitute(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_substitute(item) for item in obj]
            elif isinstance(obj, str) and obj.startswith('${') and obj.endswith('}'):
                env_key = obj[2:-1]
                return os.getenv(env_key, obj)
            else:
                return obj
        
        # Start with defaults
        result = _substitute(self.defaults.copy())
        
        # Override with user config
        def _deep_update(base, updates):
            """Deep update dictionary"""
            for key, value in updates.items():
                if isinstance(value, dict) and key in base:
                    _deep_update(base[key], value)
                else:
                    base[key] = value
        
        _deep_update(result, _substitute(self.user_config))
        
        return result
