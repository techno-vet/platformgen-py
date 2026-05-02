#!/usr/bin/env python3
"""
ServiceNow Auto-Login with Selenium
Automatically captures session cookies after MFA login
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv, set_key
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


class ServiceNowAutoLogin:
    """Automated ServiceNow login with cookie capture"""
    
    def __init__(self, instance_url=None):
        self.env_file = Path.home() / '.auger' / '.env'
        load_dotenv(self.env_file)
        
        self.instance_url = instance_url or os.getenv('SERVICENOW_URL', 
                                                       'https://gsassistprod.servicenowservices.com')
        self.driver = None
        
        # Setup logging to file
        self.log_file = Path('logs/servicenow_auto_login.log')
        self.log_file.parent.mkdir(exist_ok=True)
    
    def log(self, message):
        """Write to both console and log file"""
        print(message)
        sys.stdout.flush()
        try:
            with open(self.log_file, 'a') as f:
                f.write(message + '\n')
                f.flush()
        except Exception:
            pass
    
    def setup_driver(self):
        """Setup Chrome webdriver"""
        import os
        from pathlib import Path
        
        options = Options()
        
        # Use a temporary profile for Selenium (avoids conflicts)
        # User will need to login fresh, but it's more reliable
        
        # Chrome options for stability
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        # Disable some automation flags
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)
        
        self.log("🌐 Starting Chrome browser...")
        self.log("   Complete login + MFA, and wait for the full ServiceNow homepage to load")
        
        try:
            # Auto-install/update ChromeDriver
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.maximize_window()
            self.log("✅ Chrome browser started successfully!")
        except Exception as e:
            self.log(f"❌ Error starting Chrome: {e}")
            raise
    
    def login_and_capture(self):
        """Open ServiceNow, wait for user to login, capture cookies"""
        try:
            self.setup_driver()
            
            self.log("\n" + "="*70)
            self.log("ServiceNow Automated Cookie Capture")
            self.log("="*70)
            self.log(f"\n🌐 Opening: {self.instance_url}")
            
            # Navigate to ServiceNow
            self.driver.get(self.instance_url)
            
            self.log("\n📱 Please complete login in the browser:")
            self.log("   1. Enter your username and password")
            self.log("   2. Complete MFA on your phone")
            self.log("   3. Wait until you see the ServiceNow homepage")
            self.log("\n⏳ Waiting for successful login...")
            self.log("   (This script will detect when you're logged in)")
            
            # Wait for successful login by checking for common ServiceNow elements
            # Option 1: Wait for URL to change from login page
            # Option 2: Wait for specific ServiceNow UI elements
            
            wait = WebDriverWait(self.driver, 300)  # 5 minute timeout
            
            # Keep checking if we're past the login page
            logged_in = False
            start_time = time.time()
            
            self.log("\n🔍 Monitoring login progress...")
            self.log("   Waiting for you to complete username + password + MFA...")
            while not logged_in and (time.time() - start_time) < 300:
                current_url = self.driver.current_url
                
                # Debug: Print URL every 10 seconds
                elapsed = int(time.time() - start_time)
                if elapsed > 0 and elapsed % 10 == 0:
                    self.log(f"   [{elapsed}s] URL: {current_url[:60]}...")
                
                # Check if we have session cookies
                cookies = self.driver.get_cookies()
                session_cookies = [c for c in cookies if c['name'] in 
                                  ['JSESSIONID', 'glide_user', 'glide_user_session']]
                
                # IMPORTANT: Must be on a home/main page, NOT on login or MFA pages
                # Look for specific home page indicators in URL
                is_home_page = any([
                    '/now/nav/ui/' in current_url,
                    '/now/workspace/' in current_url,
                    '/now/sow/home' in current_url,
                    '/navpage.do' in current_url,
                    '/nav_to.do' in current_url
                ])
                
                # Also make sure we're NOT on auth-related pages
                is_auth_page = any([
                    'login' in current_url.lower(),
                    'sso' in current_url.lower(),
                    'auth' in current_url.lower(),
                    'mfa' in current_url.lower(),
                    'saml' in current_url.lower()
                ])
                
                # Debug every check
                if elapsed > 0 and elapsed % 10 == 0:
                    cookie_names = [c['name'] for c in session_cookies]
                    self.log(f"   Cookies: {len(session_cookies)} ({', '.join(cookie_names)}), Home: {is_home_page}, Auth: {is_auth_page}")
                
                # Only consider logged in if:
                # 1. We have at least 1 session cookie (some instances only set JSESSIONID initially)
                # 2. We're on a home page
                # 3. We're NOT on an auth page
                if len(session_cookies) >= 1 and is_home_page and not is_auth_page:
                    
                    self.log(f"\n✅ Found {len(session_cookies)} session cookies on home page!")
                    self.log(f"   URL: {current_url[:60]}...")
                    self.log("   Waiting 5 seconds to ensure login is fully complete...")
                    time.sleep(5)
                    
                    # Re-check after waiting (make sure we didn't get redirected back)
                    final_url = self.driver.current_url
                    final_cookies = self.driver.get_cookies()
                    final_session = [c for c in final_cookies if c['name'] in 
                                    ['JSESSIONID', 'glide_user', 'glide_user_session']]
                    
                    if len(final_session) >= 1 and 'login' not in final_url.lower():
                        logged_in = True
                        self.log("✅ Login verified and stable!")
                        break
                    else:
                        self.log("   ⚠️  Session unstable, continuing to wait...")
                
                # Check every 2 seconds
                time.sleep(2)
            
            if not logged_in:
                print("\n❌ Timeout waiting for login")
                print("   Please try again and complete login within 5 minutes")
                return False
            
            # Extract all cookies
            self.log("\n🍪 Capturing session cookies...")
            all_cookies = self.driver.get_cookies()
            
            # Log ALL cookies for debugging
            self.log(f"\n📋 All available cookies ({len(all_cookies)}):")
            for c in all_cookies:
                self.log(f"   - {c['name']}: {c['value'][:50]}...")
            
            # Filter for ServiceNow session cookies
            session_cookies = {}
            cookie_names = ['JSESSIONID', 'glide_user', 'glide_user_session', 
                          'glide_user_route', 'BIGipServerpool_gsassistprod', 
                          'glide_session_store', 'glide_user_activity']
            
            for cookie in all_cookies:
                if cookie['name'] in cookie_names:
                    session_cookies[cookie['name']] = cookie['value']
                    self.log(f"   ✓ {cookie['name']}")
            
            if not session_cookies:
                self.log("\n❌ No session cookies found")
                return False
            
            self.log(f"\n📦 Captured {len(session_cookies)} cookies")
            
            # Save cookies to .env
            expiry = datetime.now() + timedelta(hours=8)
            self._save_cookies(session_cookies, expiry)
            
            self.log(f"\n✅ Cookies saved to: {self.env_file}")
            self.log(f"📅 Valid until: {expiry.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Test the cookies
            self.log("\n🔍 Testing cookies with API call...")
            if self._test_cookies(session_cookies):
                self.log("✅ Cookies are valid and working!")
            else:
                self.log("⚠️  Cookies captured but API test failed")
                self.log("   They should still work for browser-based access")
            
            # Return success if we captured cookies
            self.log("\n✅ Cookie capture complete!")
            return True
            
        except Exception as e:
            self.log(f"\n❌ Error: {e}")
            import traceback
            self.log(traceback.format_exc())
            return False
        
        finally:
            if self.driver:
                self.log("\n🔒 Closing browser...")
                time.sleep(2)  # Give user time to see result
                self.driver.quit()
    
    def _save_cookies(self, cookies, expiry):
        """Save cookies to .env file"""
        cookies_json = json.dumps(cookies)
        set_key(self.env_file, 'SERVICENOW_URL', self.instance_url)
        set_key(self.env_file, 'SERVICENOW_COOKIES', cookies_json)
        set_key(self.env_file, 'SERVICENOW_COOKIE_EXPIRY', expiry.isoformat())
    
    def _test_cookies(self, cookies):
        """Test cookies with API call"""
        import requests
        
        session = requests.Session()
        
        # Add cookies to session
        for name, value in cookies.items():
            session.cookies.set(name, value)
        
        # Test API call
        url = f"{self.instance_url}/api/now/table/sys_user?sysparm_limit=1"
        headers = {'Accept': 'application/json'}
        
        try:
            response = session.get(url, headers=headers, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"   Test failed: {e}")
            return False


def main():
    """Main entry point"""
    import sys
    
    print("\n" + "="*70)
    print("ServiceNow Auto-Login Tool")
    print("="*70)
    print("\nThis will:")
    print("  1. Open Chrome in a fresh session")
    print("  2. Navigate to ServiceNow login")
    print("  3. Complete login + MFA manually")
    print("  4. WAIT for the ServiceNow homepage to fully load")
    print("  5. Automatically detect and capture session cookies")
    print("  6. Save cookies to .env file")
    print("\n" + "="*70)
    
    # Check if --no-prompt flag is passed (for automated widget use)
    no_prompt = '--no-prompt' in sys.argv
    
    if not no_prompt:
        response = input("\nReady to start? (y/n): ").strip().lower()
        
        if response != 'y':
            print("Cancelled.")
            return
    else:
        print("\n[Auto-mode: Skipping prompt]")
    
    auto_login = ServiceNowAutoLogin()
    success = auto_login.login_and_capture()
    
    if success:
        print("\n" + "="*70)
        print("✅ SUCCESS! You're all set!")
        print("="*70)
        print("\nNext steps:")
        print("  • Test connection: python3 servicenow_session.py --test")
        print("  • Use in Python: from servicenow_session import ServiceNowSession")
        print("  • Create ServiceNow widgets for Auger Platform")
        print("\nCookies valid for 8 hours. Re-run this script when they expire.")
    else:
        print("\n" + "="*70)
        print("❌ Setup incomplete")
        print("="*70)
        print("\nTroubleshooting:")
        print("  • Make sure you complete the full login")
        print("  • Wait until you see ServiceNow homepage")
        print("  • Try running again: python3 servicenow_auto_login.py")


if __name__ == '__main__':
    main()
