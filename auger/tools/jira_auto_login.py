#!/usr/bin/env python3
"""
Jira Auto-Login with Selenium
Opens Chrome, navigates to gsa-standard.atlassian-us-gov-mod.net, waits for user to complete PIV/MFA,
then captures session cookies and saves them to ~/.auger/.env.
"""
import os
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv, set_key

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print('❌ selenium not installed. Run: pip install selenium webdriver-manager')
    sys.exit(1)


class JiraAutoLogin:
    """Automated Jira login with cookie capture."""

    def __init__(self, instance_url: str | None = None):
        self.env_file = Path.home() / '.auger' / '.env'
        load_dotenv(self.env_file)
        self.instance_url = (
            instance_url or
            os.getenv('JIRA_URL', 'https://gsa-standard.atlassian-us-gov-mod.net')
        ).rstrip('/')
        self.driver = None
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        self.log_file = log_dir / 'jira_auto_login.log'

    def log(self, message: str):
        print(message, flush=True)
        try:
            with open(self.log_file, 'a') as f:
                f.write(message + '\n')
        except Exception:
            pass

    def setup_driver(self):
        options = Options()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option('excludeSwitches', ['enable-automation'])
        options.add_experimental_option('useAutomationExtension', False)

        # Use host DISPLAY
        display = os.environ.get('DISPLAY', ':1')
        os.environ['DISPLAY'] = display

        self.log('🌐 Starting Chrome for Jira login...')
        self.log(f'   Instance: {self.instance_url}')
        self.log('   Complete your PIV/MFA login, then wait for the board to load.')

        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.maximize_window()
            self.log('✅ Chrome started')
        except Exception as e:
            self.log(f'❌ Chrome error: {e}')
            raise

    def login_and_capture(self) -> bool:
        """Navigate to Jira, wait for user login, capture cookies."""
        board_url = f'{self.instance_url}/secure/RapidBoard.jspa'
        self.log(f'📂 Opening: {board_url}')
        self.driver.get(board_url)

        self.log('')
        self.log('━' * 60)
        self.log('  👤  Please complete your Jira login in the browser.')
        self.log('  ⏳  Waiting up to 10 minutes...')
        self.log('━' * 60)

        # Wait until we land on a page that looks like a Jira board
        # (URL no longer contains /login and page title contains "Jira")
        deadline = time.time() + 600  # 10 minutes
        last_url = ''
        while time.time() < deadline:
            current_url = self.driver.current_url
            if current_url != last_url:
                self.log(f'  📍 URL: {current_url}')
                last_url = current_url

            # Check if we're past login
            if ('login' not in current_url.lower() and
                    'authenticate' not in current_url.lower() and
                    current_url.startswith(self.instance_url) and
                    'RapidBoard' in current_url or '/jira/' in current_url or
                    '/secure/' in current_url):
                # Give the page a moment to fully settle
                time.sleep(3)
                cookies = self.driver.get_cookies()
                if cookies:
                    self.log(f'✅ Logged in — captured {len(cookies)} cookies')
                    self._save_cookies(cookies)
                    return True

            time.sleep(2)

        self.log('⏰ Login timed out after 10 minutes')
        return False

    def _save_cookies(self, selenium_cookies: list):
        """Convert Selenium cookies to dict and save to ~/.auger/.env."""
        cookie_dict = {c['name']: c['value'] for c in selenium_cookies}
        expiry = datetime.now() + timedelta(hours=12)
        set_key(str(self.env_file), 'JIRA_URL',           self.instance_url)
        set_key(str(self.env_file), 'JIRA_COOKIES',       json.dumps(cookie_dict))
        set_key(str(self.env_file), 'JIRA_COOKIE_EXPIRY', expiry.isoformat())
        self.log(f'💾 Cookies saved → {self.env_file}')
        self.log(f'   Expires: {expiry.strftime("%Y-%m-%d %H:%M")}')

    def run(self):
        try:
            self.setup_driver()
            ok = self.login_and_capture()
            return ok
        except Exception as e:
            self.log(f'❌ Fatal error: {e}')
            return False
        finally:
            if self.driver:
                try:
                    self.driver.quit()
                except Exception:
                    pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Jira auto-login via Selenium')
    parser.add_argument('--url', default=None, help='Jira instance URL')
    parser.add_argument('--no-prompt', action='store_true')
    args = parser.parse_args()

    login = JiraAutoLogin(instance_url=args.url)
    success = login.run()
    sys.exit(0 if success else 1)
