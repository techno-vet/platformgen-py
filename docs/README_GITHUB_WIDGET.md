# GitHub Widget - User Guide

## Overview
The GitHub Widget provides a comprehensive interface for browsing and managing GitHub repositories directly within the Auger SRE Platform.

## Features

### 🔐 Authentication
- **Auto-authentication**: Automatically uses the `GHE_TOKEN` from your API Config
- **GitHub Enterprise support**: Works with both GitHub.com and GitHub Enterprise (github.helix.gsa.gov)
- **Token storage**: Securely saves token for future sessions

### 📁 Repository Browser
- Browse all repositories (user and organization repos)
- Quick repository selection dropdown
- One-click "Open in Browser" button
- Repository statistics (stars, forks, watchers, issues)

### 📊 Six Tabbed Views

#### 1. **Overview Tab**
- Complete repository information
- README display
- Repository metadata (size, language, license, created date)
- Homepage link if available

#### 2. **Issues Tab**
- Browse issues with state filtering (open/closed/all)
- View issue number, title, author, state, and creation date
- Double-click to open issue in browser
- Create new issues directly from the widget
- Displays up to 100 issues

#### 3. **Pull Requests Tab**
- Browse PRs with state filtering
- View PR details in tabular format
- Double-click to open PR in browser
- Shows up to 100 PRs

#### 4. **Commits Tab**
- Browse commit history
- Branch selection dropdown
- Adjustable limit (10-500 commits)
- Shows SHA, message, author, and date
- Double-click to view commit details in browser

#### 5. **Branches Tab**
- View all repository branches
- Protection status indicator
- Latest commit SHA for each branch
- Auto-refreshes when repository changes

#### 6. **Actions Tab**
- Monitor GitHub Actions workflow runs
- View run ID, workflow name, status, conclusion, branch, and date
- Adjustable limit (5-100 runs)
- Double-click to open workflow run in browser

## Setup

### 1. Configure GitHub Token in API Config

The widget automatically uses the GitHub Enterprise token from API Config:

1. Open **API Config** widget (from Widgets menu)
2. Scroll to **"GitHub Enterprise (SSH)"** section
3. Enter your **API Token** (field: `GHE_TOKEN`)
4. Click **"Save to .env"**
5. Return to GitHub widget - it will auto-authenticate

### 2. Generate a GitHub Token (if needed)

If you don't have a token yet:

1. Go to: https://github.helix.gsa.gov/settings/tokens
2. Click **"Generate new token (classic)"**
3. Give it a name (e.g., "Auger SRE Platform")
4. Select required scopes:
   - ✅ `repo` - Full control of private repositories
   - ✅ `read:org` - Read org and team membership
   - ✅ `workflow` - Update GitHub Action workflows
5. Click **"Generate token"**
6. Copy the token and add to API Config

## Usage

### Browsing Repositories

1. **Select Repository**: Use the dropdown or type to search
2. **View Overview**: See repository details and README
3. **Navigate Tabs**: Click tabs to view different aspects

### Working with Issues

1. Switch to **Issues tab**
2. Select state: Open, Closed, or All
3. Browse the list
4. **Double-click** any issue to open in browser
5. Click **"➕ Create Issue"** to create new

### Viewing Pull Requests

1. Switch to **Pull Requests tab**
2. Filter by state (open/closed/all)
3. **Double-click** to open PR in browser

### Exploring Commits

1. Switch to **Commits tab**
2. Select a branch from dropdown
3. Adjust limit if needed (default: 50)
4. Click **🔄 Refresh** to reload
5. **Double-click** to view commit in browser

### Monitoring Actions

1. Switch to **Actions tab**
2. Adjust limit (default: 20)
3. View workflow run statuses
4. **Double-click** to open run details in browser

## Integration with Ask Auger

The widget provides rich context to the Ask Auger panel:

- Current authentication status
- Selected repository details
- Active tab information
- Available for intelligent queries about your repositories

Example queries:
- "Summarize the open issues for this repository"
- "What are the most recent commits on the main branch?"
- "Check if there are any failed GitHub Actions runs"

## Keyboard Shortcuts

- **F5**: Execute query (in query tabs)
- **Double-click**: Open item in browser (issues/PRs/commits/actions)

## Tips & Tricks

### Performance
- Large repositories may take a moment to load
- Use the limit controls on Commits and Actions tabs for faster loading
- All loading happens in background threads (UI stays responsive)

### Navigation
- Repository stats update when you select a new repo
- Branches auto-load when repository changes
- Default branch is pre-selected in Commits tab

### Browser Integration
- Click **🌐 Open in Browser** to open current repository
- Double-click any item in tables to view details
- "Get Token" button opens GitHub settings page

## Troubleshooting

### "Not authenticated" message
- Check that `GHE_TOKEN` is set in API Config
- Click "Connect" button to retry
- Verify token has required permissions

### "PyGithub not installed" error
```bash
pip install PyGithub requests
```

### Empty repository list
- Verify token has access to repositories
- Check token scopes include `repo` and `read:org`
- Try clicking "🔄 Refresh" button

### Authentication fails
- Ensure token is valid (not expired)
- For GitHub Enterprise: verify `GHE_URL` is correct in API Config
- Check network connectivity

### Actions tab shows no data
- Some repositories may not have GitHub Actions enabled
- Verify token has `workflow` scope

## Technical Details

### API Endpoints Used
- GitHub REST API v3
- Uses PyGithub library for API calls
- Supports both GitHub.com and GitHub Enterprise

### Data Storage
- Token saved to: `~/.auger_github_token`
- Configuration read from: `.env` file
- File permissions: 600 (user read/write only)

### Threading
- All API calls run in background threads
- UI remains responsive during loading
- Thread-safe UI updates using `after()`

### Rate Limits
- GitHub API rate limits apply
- Authenticated: 5,000 requests/hour
- Widget displays first 100 items in most lists

## Widget Metadata
- **Name**: `github`
- **Title**: `GitHub`
- **Icon**: `🐙`
- **File**: `ui/widgets/github.py`

## Dependencies
- `PyGithub` - GitHub API wrapper
- `requests` - HTTP library
- `python-dotenv` - Environment variable loading
- Standard library: `tkinter`, `threading`, `json`, `webbrowser`

## Related Widgets
- **API Config** - Configure GitHub tokens
- **Prospector** - Uses GitHub for repo operations
- **Shell Terminal** - Run git commands

## Future Enhancements
Ideas for future development:
- Code search within repositories
- File browser with syntax highlighting
- Inline issue/PR commenting
- Webhook management
- Repository settings editor
- GitHub Projects integration
- Release management
- Dependency graph viewer

## Support
For issues or questions:
1. Check API Config has valid `GHE_TOKEN`
2. Review status bar for error messages
3. Check console logs for detailed errors
4. Verify network connectivity to GitHub Enterprise

---

**Version**: 1.0  
**Last Updated**: 2026-02-27  
**Author**: Auger Team
