#!/usr/bin/env python3
"""
ServiceNow Session Manager v2 - Better cookie capture
Captures ALL cookies needed for ServiceNow authentication
Supports both REST API (if credentials available) and web scraping
"""

import os
import json
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta
import requests
from dotenv import load_dotenv, set_key
from bs4 import BeautifulSoup
import re


class ServiceNowSession:
    """Manage ServiceNow session with MFA support"""
    
    def __init__(self, instance_url=None):
        self.env_file = Path.home() / '.auger' / '.env'
        load_dotenv(self.env_file, override=True)
        
        self.instance_url = instance_url or os.getenv('SERVICENOW_URL', 'https://gsassistprod.servicenowservices.com')
        self.session = requests.Session()
        self._load_session()
    
    def _load_session(self):
        """Load stored session cookies if available"""
        cookies_json = os.getenv('SERVICENOW_COOKIES')
        cookie_expiry = os.getenv('SERVICENOW_COOKIE_EXPIRY')
        
        if cookies_json and cookie_expiry:
            expiry_date = datetime.fromisoformat(cookie_expiry)
            if datetime.now() < expiry_date:
                # Cookies still valid
                try:
                    cookies = json.loads(cookies_json)
                    # Extract domain from instance URL
                    from urllib.parse import urlparse
                    parsed = urlparse(self.instance_url)
                    domain = parsed.netloc
                    
                    for name, value in cookies.items():
                        self.session.cookies.set(name, value, domain=domain)
                    return True
                except Exception as e:
                    print(f"Error loading cookies: {e}")
            else:
                print("⚠️  Session expired - need to re-authenticate")
        
        return False
    
    def login_interactive(self):
        """Interactive login with MFA - captures ALL cookies"""
        print("\n" + "="*70)
        print("ServiceNow MFA Login - Cookie Capture")
        print("="*70)
        print("\nThis will open ServiceNow in your browser.")
        print("Please complete the login (including MFA on your phone).\n")
        
        input("Press ENTER to open browser...")
        
        # Open ServiceNow in browser
        login_url = f"{self.instance_url}/login.do"
        webbrowser.open(login_url)
        
        print("\n" + "="*70)
        print("📱 Complete login in your browser (including MFA)")
        print("="*70)
        print("\n🔧 STEP-BY-STEP INSTRUCTIONS:")
        print("-" * 70)
        print("1. After successful login, stay on any ServiceNow page")
        print("2. Press F12 to open Developer Tools")
        print("3. Click the 'Console' tab at the top")
        print("4. In the console, paste this EXACT command:")
        print()
        print("   document.cookie")
        print()
        print("5. Press ENTER")
        print("6. You'll see a long string with multiple cookies")
        print("7. SELECT ALL the text (Ctrl+A or Cmd+A)")
        print("8. COPY it (Ctrl+C or Cmd+C)")
        print("="*70 + "\n")
        
        cookie_string = input("Paste the ENTIRE cookie string here: ").strip()
        
        if not cookie_string:
            print("❌ No cookies provided")
            return False
        
        # Parse cookie string
        cookies = self._parse_cookie_string(cookie_string)
        
        if not cookies:
            print("❌ Could not parse cookies")
            return False
        
        print(f"\n✅ Found {len(cookies)} cookies:")
        for name in cookies.keys():
            print(f"   - {name}")
        
        # Set cookies in session
        for name, value in cookies.items():
            self.session.cookies.set(name, value)
        
        # Test the cookies
        print("\n🔍 Testing session cookies...")
        if self.test_connection():
            # Store in .env for future use
            expiry = datetime.now() + timedelta(hours=8)  # Match your 8-hour setting
            
            self._save_session(cookies, expiry)
            
            print("✅ Session authenticated successfully!")
            print(f"📅 Cookie valid until: {expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"💾 Saved to: {self.env_file}")
            return True
        else:
            print("❌ Session cookies invalid")
            print("\n🔍 Debugging info:")
            print(f"   Cookies captured: {list(cookies.keys())}")
            print("\n💡 Troubleshooting:")
            print("   1. Make sure you're still logged in")
            print("   2. Copy cookies from a ServiceNow page (not login page)")
            print("   3. Copy the ENTIRE string from console")
            print("   4. Try copying from: document.cookie")
            return False
    
    def _parse_cookie_string(self, cookie_string):
        """Parse browser cookie string into dict"""
        cookies = {}
        
        # Split by semicolon and parse each cookie
        parts = cookie_string.split(';')
        for part in parts:
            part = part.strip()
            if '=' in part:
                name, value = part.split('=', 1)
                name = name.strip()
                value = value.strip()
                
                # Only include cookies relevant to session
                if name in ['JSESSIONID', 'glide_user', 'glide_user_session', 'glide_user_route', 
                           'BIGipServerpool_gsassistprod', 'glide_session_store']:
                    cookies[name] = value
        
        return cookies
    
    def _save_session(self, cookies, expiry):
        """Save session cookies to .env"""
        cookies_json = json.dumps(cookies)
        set_key(self.env_file, 'SERVICENOW_URL', self.instance_url)
        set_key(self.env_file, 'SERVICENOW_COOKIES', cookies_json)
        set_key(self.env_file, 'SERVICENOW_COOKIE_EXPIRY', expiry.isoformat())
    
    def test_connection(self):
        """Test if session is valid"""
        try:
            response = self.get('/api/now/table/sys_user', params={'sysparm_limit': 1})
            
            if response.status_code == 200:
                return True
            else:
                print(f"   API returned: {response.status_code}")
                print(f"   Message: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"   Connection test failed: {e}")
            return False
    
    def get(self, endpoint, **kwargs):
        """Make GET request to ServiceNow API"""
        url = f"{self.instance_url}{endpoint}"
        headers = kwargs.get('headers', {})
        headers['Accept'] = 'application/json'
        kwargs['headers'] = headers
        
        response = self.session.get(url, **kwargs)
        
        if response.status_code == 401:
            print("⚠️  Session expired - please re-authenticate")
            print("   Run: python3 servicenow_session.py --login")
        
        return response
    
    def post(self, endpoint, **kwargs):
        """Make POST request to ServiceNow API"""
        url = f"{self.instance_url}{endpoint}"
        headers = kwargs.get('headers', {})
        headers['Accept'] = 'application/json'
        headers['Content-Type'] = 'application/json'
        kwargs['headers'] = headers
        
        response = self.session.post(url, **kwargs)
        
        if response.status_code == 401:
            print("⚠️  Session expired - please re-authenticate")
        
        return response
    
    def get_incidents(self, limit=10, assigned_to=None):
        """Get incidents from ServiceNow"""
        params = {'sysparm_limit': limit}
        
        if assigned_to:
            params['sysparm_query'] = f'assigned_to.email={assigned_to}'
        
        response = self.get('/api/now/table/incident', params=params)
        
        if response.status_code == 200:
            return response.json().get('result', [])
        else:
            print(f"Error fetching incidents: {response.status_code}")
            return []
    
    def get_changes(self, limit=10):
        """Get change requests from ServiceNow"""
        params = {'sysparm_limit': limit}
        response = self.get('/api/now/table/change_request', params=params)
        
        if response.status_code == 200:
            return response.json().get('result', [])
        else:
            print(f"Error fetching changes: {response.status_code}")
            return []
    
    def search(self, table, query, limit=10):
        """Search any ServiceNow table"""
        params = {
            'sysparm_limit': limit,
            'sysparm_query': query
        }
        
        response = self.get(f'/api/now/table/{table}', params=params)
        
        if response.status_code == 200:
            return response.json().get('result', [])
        else:
            print(f"Error searching {table}: {response.status_code}")
            return []
    
    # Web scraping methods (for when API doesn't work with cookies)
    
    def scrape_incidents(self, limit=20):
        """Scrape incidents via CSV export (REST API requires OAuth, cookies don't work)"""
        try:
            csv_url = f"{self.instance_url}/incident_list.do"
            csv_params = {
                'CSV': '',
                'sysparm_query': 'active=true^ORDERBYDESCsys_created_on',
                'sysparm_first_row': '1',
                'sysparm_limit': limit,
                'sysparm_view': ''
            }
            r = self.session.get(csv_url, params=csv_params, timeout=30)
            if r.status_code == 200 and 'Number' in r.text:
                import csv, io
                reader = csv.DictReader(io.StringIO(r.text))
                return [dict(row) for row in list(reader)[:limit]]
            print(f"scrape_incidents: status={r.status_code}, has Number={'Number' in r.text}")
            return []
        except Exception as e:
            print(f"Error scraping incidents: {e}")
            return []
    
    def scrape_changes(self, limit=20):
        """Scrape change requests from web UI"""
        try:
            # Try CSV export
            csv_url = f"{self.instance_url}/change_request_list.do"
            csv_params = {
                'CSV': '',
                'sysparm_query': 'active=true',
                'sysparm_first_row': '1',
                'sysparm_view': ''
            }
            csv_response = self.session.get(csv_url, params=csv_params)
            
            if csv_response.status_code == 200 and 'Number' in csv_response.text:
                import csv
                import io
                reader = csv.DictReader(io.StringIO(csv_response.text))
                return [dict(row) for row in list(reader)[:limit]]
            
            return []
            
        except Exception as e:
            print(f"Error scraping changes: {e}")
            return []


def main():
    """CLI interface for session management"""
    import sys
    
    sn = ServiceNowSession()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--login':
        # Interactive login
        sn.login_interactive()
    
    elif len(sys.argv) > 1 and sys.argv[1] == '--test':
        # Test existing session
        print("🔍 Testing ServiceNow connection...")
        if sn.test_connection():
            print("✅ Session is valid!")
            
            # Fetch some test data
            print("\n📋 Fetching recent incidents...")
            incidents = sn.get_incidents(limit=5)
            print(f"   Found {len(incidents)} incidents")
            
            if incidents:
                inc = incidents[0]
                print(f"\n   Example incident:")
                print(f"   - Number: {inc.get('number')}")
                print(f"   - Short desc: {inc.get('short_description', 'N/A')[:60]}...")
                print(f"   - State: {inc.get('state')}")
        else:
            print("❌ Session invalid or expired")
            print("   Run: python3 servicenow_session.py --login")
    
    else:
        # Show usage
        print("\nServiceNow Session Manager v2")
        print("="*70)
        print("\nUsage:")
        print("  python3 servicenow_session.py --login    # Login with MFA")
        print("  python3 servicenow_session.py --test     # Test connection")
        print("\nExample Python usage:")
        print("""
from servicenow_session import ServiceNowSession

# Create session (uses stored cookies)
sn = ServiceNowSession()

# Get your assigned incidents
my_incidents = sn.get_incidents(assigned_to='bobby.blair@gsa.gov')

# Get all incidents
all_incidents = sn.get_incidents(limit=50)

# Get changes
changes = sn.get_changes(limit=10)

# Custom query
results = sn.search('incident', 'priority=1^state=2', limit=20)
""")


if __name__ == '__main__':
    main()
