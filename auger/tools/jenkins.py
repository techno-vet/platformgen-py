from ujenkins import JenkinsClient
import requests
import json
from urllib.parse import quote, unquote


class JenkinsConfigError(RuntimeError):
    """Raised when Jenkins connection settings are incomplete."""


class JenkinsAuthError(RuntimeError):
    """Raised when Jenkins rejects the supplied credentials."""


def _request_json(api_url, username, api_token):
    """Fetch JSON from Jenkins and raise specific config/auth errors."""
    if not api_url or not username or not api_token:
        raise JenkinsConfigError("Missing Jenkins URL, username, or API token")

    response = requests.get(api_url, auth=(username, api_token), timeout=20)
    if response.status_code == 401:
        raise JenkinsAuthError("Invalid Jenkins username or API token")

    response.raise_for_status()
    return response.json()


def example():
    client = JenkinsClient('https://jenkins-mcaas.helix.gsa.gov', 'bobbygblair', '11f11a03431406da57e3448e562ce00382')
    version = client.system.get_version()
    print(version)
    jobs = client.jobs.get(depth=10)
    print(jobs)


def get_all_repositories(jenkins_url, username, api_token, folder_path="ASSIST/job/core/job/assist"):
    """
    Retrieves a distinct list of all repositories that Jenkins is aware of.
    
    Traverses the Jenkins folder structure to extract repository names from jobs.
    Assumes structure like: ASSIST/job/core/job/assist/job/{repo}/job/{branch}
    
    Args:
        jenkins_url (str): The URL of the Jenkins server.
        username (str): Jenkins username.
        api_token (str): Jenkins API token.
        folder_path (str): The folder path to search for repositories (default: "ASSIST/job/core/job/assist").
    
    Returns:
        list: A sorted, distinct list of repository names. Returns None if there's an error.
    """
    try:
        repositories = set()
        
        # Get all jobs in the folder
        api_url = f"{jenkins_url}/job/{folder_path}/api/json?tree=jobs[name,url,jobs[name,url]]"
        data = _request_json(api_url, username, api_token)
        
        # Extract repository names from job structure
        jobs = data.get("jobs", [])
        for job in jobs:
            repo_name = job.get('name')
            if repo_name:
                repositories.add(repo_name)
        
        # Return sorted list
        return sorted(list(repositories))
        
    except (JenkinsConfigError, JenkinsAuthError):
        raise
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def get_repository_branches(jenkins_url, username, api_token, repo_name, folder_path="ASSIST/job/core/job/assist"):
    """
    Retrieves a distinct list of all branches for a specific repository.
    
    Args:
        jenkins_url (str): The URL of the Jenkins server.
        username (str): Jenkins username.
        api_token (str): Jenkins API token.
        repo_name (str): Repository name (e.g., 'assist-data-utils').
        folder_path (str): The folder path containing repositories (default: "ASSIST/job/core/job/assist").
    
    Returns:
        list: A sorted, distinct list of branch names. Returns None if there's an error.
    """
    try:
        branches = set()
        
        # Get all jobs (branches) for the repository
        api_url = f"{jenkins_url}/job/{folder_path}/job/{repo_name}/api/json?tree=jobs[name,url]"
        data = _request_json(api_url, username, api_token)
        
        # Extract branch names from job structure
        jobs = data.get("jobs", [])
        for job in jobs:
            branch_name = job.get('name')
            if branch_name:
                # Decode URL-encoded branch names (e.g., release%2FDATA_1.5.3.99_DME -> release/DATA_1.5.3.99_DME)
                decoded_branch = unquote(branch_name)
                branches.add(decoded_branch)
        
        # Return sorted list
        return sorted(list(branches))
        
    except (JenkinsConfigError, JenkinsAuthError):
        raise
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


def build_job_name(repo, branch):
    """
    Build the Jenkins job name from repo and branch.
    
    Args:
        repo (str): Repository name (e.g., 'assist-data-utils')
        branch (str): Full branch name (e.g., 'release/DATA_1.5.3.99_DME', 'feature/ASSIST3-34495', 'PR-1904')
        
    Returns:
        str: Full Jenkins job path
    """
    # URL-encode the branch name (replace / with %2F)
    encoded_branch = quote(branch, safe='')
    
    # Build the full job path
    job_name = f"ASSIST/job/core/job/assist/job/{repo}/job/{encoded_branch}"
    
    return job_name


def get_branch_build_numbers(jenkins_url, username, api_token, repo_name, branch_name):
    """
    Retrieves all build numbers for a specific repository and branch.
    
    Args:
        jenkins_url (str): The URL of the Jenkins server.
        username (str): Jenkins username.
        api_token (str): Jenkins API token.
        repo_name (str): Repository name (e.g., 'assist-data-utils').
        branch_name (str): Full branch name (e.g., 'release/DATA_1.5.3.99_DME', 'feature/ASSIST3-34495', 'PR-1904').
    
    Returns:
        list: A list of dictionaries with build information (number, result, timestamp, duration).
              Sorted by build number (newest first). Returns None if there's an error.
    """
    try:
        # Build the job name using existing function
        job_name = build_job_name(repo_name, branch_name)
        
        # Get all builds for this job
        api_url = f"{jenkins_url}/job/{job_name}/api/json?tree=builds[number,result,timestamp,duration,url]"
        data = _request_json(api_url, username, api_token)
        
        builds = data.get("builds", [])
        
        # Sort by build number (newest first)
        builds.sort(key=lambda x: x.get('number', 0), reverse=True)
        
        return builds
        
    except (JenkinsConfigError, JenkinsAuthError):
        raise
    except requests.exceptions.RequestException as e:
        print(f"Error during API request: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None


if __name__ == '__main__':
    example()

def strip_ansi_codes(text):
    """Remove ANSI escape sequences from text."""
    import re as _re
    ansi_escape = _re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def parse_prisma_vulnerabilities(log_content):
    """Parse Prisma CVE vulnerabilities table from Jenkins log."""
    import re as _re
    vulnerabilities = []
    lines = log_content.split('\n')
    in_vuln_table = False
    headers = []

    for line in lines:
        clean_line = strip_ansi_codes(line)
        clean_line = _re.sub(r'^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s*', '', clean_line)

        if 'Vulnerabilities' in clean_line and not in_vuln_table:
            in_vuln_table = True
            continue
        if 'Compliance Issues' in clean_line:
            break
        if not in_vuln_table:
            continue
        if clean_line.startswith('+---') or clean_line.startswith('+===') or not clean_line.strip():
            continue
        if not headers and '|' in clean_line and 'CVE' in clean_line.upper():
            parts = [p.strip() for p in clean_line.split('|')]
            headers = [p for p in parts if p]
            continue
        if headers and '|' in clean_line:
            parts = [p.strip() for p in clean_line.split('|')]
            while parts and not parts[0]:
                parts.pop(0)
            while parts and not parts[-1]:
                parts.pop()
            if len(parts) >= len(headers) and parts[0].startswith('CVE-'):
                vuln = {}
                for i, header in enumerate(headers):
                    if i < len(parts):
                        vuln[header.lower()] = parts[i]
                vulnerabilities.append(vuln)
            elif vulnerabilities and len(parts) > 0:
                for i in range(len(parts)):
                    if parts[i] and i < len(headers):
                        header = headers[i].lower()
                        if header != 'cve' and header in vulnerabilities[-1]:
                            vulnerabilities[-1][header] += ' ' + parts[i]

    for vuln in vulnerabilities:
        if 'cve' in vuln:
            cve_match = _re.search(r'CVE-\d{4}-\d+', vuln['cve'])
            if cve_match:
                vuln['cve'] = cve_match.group(0)
    return vulnerabilities


def parse_prisma_compliance(log_content):
    """Parse Prisma Compliance Issues table from Jenkins log."""
    import re as _re
    compliance_issues = []
    lines = log_content.split('\n')
    in_compliance_table = False
    headers = []

    for line in lines:
        clean_line = strip_ansi_codes(line)
        clean_line = _re.sub(r'^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s*', '', clean_line)

        if 'Compliance Issues' in clean_line:
            in_compliance_table = True
            continue
        if in_compliance_table and 'Compliance found for image' in clean_line:
            break
        if not in_compliance_table:
            continue
        if clean_line.startswith('+---') or not clean_line.strip():
            continue
        if not headers and '|' in clean_line and 'SEVERITY' in clean_line:
            parts = [p.strip() for p in clean_line.split('|') if p.strip()]
            headers = parts
            continue
        if headers and '|' in clean_line:
            parts = [p.strip() for p in clean_line.split('|')]
            if len(parts) >= 3 and parts[1].strip():
                issue = {}
                for i, header in enumerate(headers):
                    if i + 1 < len(parts):
                        issue[header.lower()] = parts[i + 1].strip()
                if issue:
                    compliance_issues.append(issue)
    return compliance_issues
