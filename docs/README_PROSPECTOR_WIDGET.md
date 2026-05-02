# Prospector Widget - CVE Analysis Tool

The **Prospector Widget** is an integrated version of the standalone `au_utils/prospector.py` tool, designed to analyze Jenkins build logs and security scans within the Auger SRE Platform.

## Overview

Prospector provides CVE (Common Vulnerabilities and Exposures) analysis from Jenkins builds, extracting security scan results from Prisma Cloud scanning. It helps SRE teams:

- View build logs and security scan results
- Analyze CVE vulnerabilities by severity
- Compare CVE differences between builds
- Get AI-powered analysis via Ask Auger

## Key Differences from Standalone Prospector

The widget version differs from the standalone `prospector.py` tool in several ways:

1. **No Built-in Auger Chat**: Uses the platform's centralized Ask Auger panel instead of its own chat interface
2. **Widget Integration**: Runs as a tab within the Auger SRE Platform
3. **Dark Theme**: Uses the platform's dark theme and color scheme
4. **Local Copies**: Uses local copies of `jenkins.py` and `jenkins-cli.py` (does not modify originals)
5. **Hot Reload**: Automatically updates when code changes are detected

## Features

### 1. Repository/Branch/Build Selection
- Load repositories from Jenkins
- Select branches for analysis
- Choose specific build numbers or use latest
- Refresh buttons (🔄) to reload data

### 2. Console Log Tab
- View full Jenkins build console log
- Build status indicator (SUCCESS/FAILURE)
- Searchable log content

### 3. Summary Tab
- Repository information (repo, branch, commit)
- Docker image details
- Vulnerability counts by severity:
  - Critical
  - High
  - Medium
  - Low
- Compliance issues summary

### 4. Vulnerabilities Tab
- Sortable table of all CVEs
- Columns: CVE ID, Severity, CVSS Score, Package, Version, Description
- Color-coded by severity:
  - Critical: Dark red background
  - High: Orange-red background
  - Medium: Yellow background
  - Low: Gray background

### 5. CVE Comparison (Diff)
- Compare vulnerabilities between two builds
- Select diff branch and build number
- Shows:
  - Fixed CVEs (vulnerabilities resolved)
  - New CVEs (new vulnerabilities introduced)
  - Unchanged CVEs

### 6. Ask Auger Integration
The widget integrates with the platform's Ask Auger panel. When you have a build loaded, you can ask questions like:

- "What are the critical vulnerabilities in this build?"
- "How do I fix CVE-2023-12345?"
- "Compare this build to the previous one"
- "What packages have the most vulnerabilities?"

The widget provides context to Ask Auger including:
- Repository and branch information
- Docker image details
- Vulnerability counts and details
- Build status

## Configuration

### Environment Variables

Prospector requires Jenkins credentials set in environment variables:

```bash
# In .env file
URL_TO_JENKINS=https://your-jenkins-instance.com
ARTIFACTORY_USER=your-username
JENKINS_API_KEY=your-api-token
```

### Getting Jenkins API Token

1. Log into Jenkins
2. Click your name (top right) → Configure
3. Under "API Token", click "Add new Token"
4. Name it and click "Generate"
5. Copy the token to your `.env` file

## Usage

### Basic Workflow

1. **Load Repositories**
   - Click the 🔄 button next to Repository dropdown
   - Wait for repositories to load
   - Select a repository from the dropdown

2. **Select Branch**
   - The branch dropdown will auto-populate
   - Select the branch you want to analyze
   - Or click 🔄 to refresh branches

3. **Select Build**
   - The build dropdown will show available builds (sorted newest first)
   - Select a specific build or leave empty for latest
   - Click 🔄 to refresh builds

4. **Get Logs**
   - Click the "Get Logs" button
   - Wait for logs and vulnerability data to load
   - View results in the tabs

5. **Analyze with Ask Auger**
   - Switch to the Ask Auger panel (bottom of window)
   - Ask questions about the loaded CVEs
   - Auger will have context about your current build

### Comparing Builds

1. Load the primary build (steps 1-4 above)
2. Select "Diff Branch" (can be same or different branch)
3. Select "Diff Build #"
4. Click "Compare CVEs"
5. View the comparison results

### Filtering Repositories

To analyze specific repos (e.g., all `core-assist-*` repos with `release/ASSIST_4.4.4.0_DME` branch):

1. Load repositories
2. Select repos matching pattern manually, or
3. Use Ask Auger: "Show me CVEs for all core-assist-* repos on release/ASSIST_4.4.4.0_DME branch #latest"

## Technical Details

### Architecture

```
Prospector Widget
├── jenkins.py (local copy)         # Jenkins API wrapper
├── jenkins-cli.py (local copy)     # CLI for fetching logs/CVEs
└── prospector.py (widget)          # UI and integration
```

### Data Flow

1. User selects repo/branch/build
2. Widget calls `jenkins-cli.py` via subprocess
3. `jenkins-cli.py` fetches logs from Jenkins
4. Parses Prisma Cloud security scan results
5. Returns JSON with:
   - Console log
   - Vulnerabilities list
   - Compliance issues
   - Git information
   - Docker image
6. Widget displays data in tabs

### CVE Parsing

The widget parses CVE data from Prisma Cloud scan results in Jenkins logs. It looks for:

- **Image Scan Results**: Docker image vulnerabilities
- **Compliance Issues**: Security compliance violations
- **Package Information**: Affected packages and versions
- **Severity Levels**: Critical, High, Medium, Low
- **CVSS Scores**: Common Vulnerability Scoring System scores

### Context for Ask Auger

When you use Ask Auger with a loaded build, the widget provides this context:

```
REPOSITORY: core-assist-api
BRANCH: release/ASSIST_4.4.4.0_DME
COMMIT: abc123def456

DOCKER IMAGE: artifactory.../core-assist-api:1.5.4.0

VULNERABILITIES: 42 total
  - Critical: 3
  - High: 12
  - Medium: 18
  - Low: 9

VULNERABILITY DETAILS (sample):
  1. CVE-2023-12345 (CRITICAL) - spring-boot 2.7.0 - CVSS: 9.8
     Remote code execution vulnerability...
  2. CVE-2023-67890 (HIGH) - jackson-databind 2.13.0 - CVSS: 7.5
     XML External Entity (XXE) injection...
  [... up to 20 CVEs ...]
```

## Troubleshooting

### No Repositories Loading

**Problem**: Repository dropdown remains empty after clicking 🔄

**Solutions**:
1. Check Jenkins credentials in `.env` file
2. Verify Jenkins URL is accessible
3. Check logs: `tail -f logs/app.log`
4. Test Jenkins API manually:
   ```bash
   python3 jenkins.py
   ```

### "Error fetching logs"

**Problem**: Getting logs fails

**Solutions**:
1. Verify build exists for selected repo/branch
2. Check Jenkins API token is valid
3. Ensure `jenkins-cli.py` is in the correct location
4. Check if Jenkins is accessible from your network

### CVE Data Not Parsing

**Problem**: Vulnerabilities tab shows 0 even though logs loaded

**Solutions**:
1. Check if build includes Prisma Cloud scan
2. Verify log format matches expected pattern
3. Some builds may not have security scans enabled
4. Check jenkins-cli.py parsing logic if format changed

### Widget Not Appearing

**Problem**: Prospector widget not in Widgets menu

**Solutions**:
1. Check hot reload logs for errors
2. Verify file is in `ui/widgets/` directory
3. Restart application: `./run.sh`
4. Check Python import errors:
   ```bash
   python3 -c "from ui.widgets.prospector import ProspectorWidget"
   ```

## Keyboard Shortcuts

- **Ctrl+L**: Clear Ask Auger chat (platform-wide)
- **Enter**: Send message to Ask Auger
- **Shift+Enter**: New line in Ask Auger input

## Best Practices

1. **Regular Scans**: Check CVEs for each release build
2. **Compare Builds**: Always compare against previous release to track fixes
3. **Prioritize by Severity**: Focus on Critical and High first
4. **Use Auger**: Ask for remediation advice on specific CVEs
5. **Document Exceptions**: If a CVE can't be fixed, document why

## Example Questions for Ask Auger

- "What critical CVEs need to be fixed before release?"
- "How do I upgrade spring-boot to fix CVE-2023-12345?"
- "Which CVEs were introduced in this build compared to the last release?"
- "Generate a CVE remediation report for this build"
- "What's the risk level of this build?"
- "Are there any CVEs with known exploits?"

## Integration with Other Widgets

### Production Release Widget
- Use Prospector to verify CVE status before deployment
- Include CVE summary in deployment documentation
- Link CVE remediation work to deployment tickets

### Cryptkeeper Widget
- Secure storage for Jenkins API tokens
- Encrypted credentials for Jenkins access

## Limitations

- **Build Log Size**: Very large logs may take time to parse
- **Network Dependency**: Requires Jenkins connectivity
- **Scan Availability**: Only works with builds that have Prisma scans
- **Rate Limiting**: Jenkins API may rate limit frequent requests

## Future Enhancements

Planned features for future versions:

1. **Export to CSV/Excel**: Export CVE data for reporting
2. **Historical Tracking**: Track CVE trends over time
3. **Automated Remediation**: Suggest package upgrades automatically
4. **JIRA Integration**: Create tickets for CVE fixes
5. **Slack Notifications**: Alert on new Critical CVEs
6. **Multi-Build Comparison**: Compare more than 2 builds at once

## Contributing

To modify the Prospector widget:

1. Edit `ui/widgets/prospector.py` for UI changes
2. Edit local `jenkins-cli.py` for parsing changes
3. **DO NOT** modify `au_utils/prospector.py` (standalone tool)
4. Test with real Jenkins data before committing
5. Update this documentation for any feature changes

## Resources

- [Prisma Cloud Documentation](https://docs.paloaltonetworks.com/prisma/prisma-cloud)
- [CVE Database](https://cve.mitre.org/)
- [CVSS Calculator](https://nvd.nist.gov/vuln-metrics/cvss/v3-calculator)
- [Jenkins API](https://www.jenkins.io/doc/book/using/remote-access-api/)

---

**Widget Version**: 1.0.0  
**Created**: 2024-02-26  
**Author**: Auger AI  
**Status**: Active Development
