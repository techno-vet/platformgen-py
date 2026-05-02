# Jira Widget

The **Jira** widget connects to `gsa-standard.atlassian-us-gov-mod.net` and gives you a full Jira interface inside Auger — without a browser. View your stories, manage sprints, transition issues, and post comments.

## Authentication

Jira uses PIV/MFA cookie authentication. The first time you open the widget:

1. Click **Login** — a Chrome window opens on the host
2. Complete your PIV/smart card login in the browser
3. The session cookies are captured automatically and saved to `~/.auger/.env` as `JIRA_COOKIES`
4. Future logins reuse saved cookies (refreshed when expired)

> The login flow uses Selenium via the Host Tools Daemon. Chrome must be installed on the host.

## Tabs

### My Stories
- All open Jira issues assigned to you
- Filter by project key (e.g., `ASSIST`, `DATA`)
- Click a story to open the detail view

### Sprint Board
- All issues in the active sprint for your selected project
- Grouped by status column (To Do → In Progress → In Review → Done)
- Drag-and-drop status transitions

### Story Detail
- Rendered HTML description
- Attachment thumbnails
- Comment history
- **Add Comment** box — post directly from Auger
- **Quick Actions**: transition status, copy issue key, open in browser

## Quick Actions

- **Move To** buttons — transition status in one click
- **Copy Key** — copies e.g. `ASSIST-1234` to clipboard
- **Open in Browser** — launches the Jira issue in Chrome

## Configuration (`.env`)

```bash
JIRA_URL=https://gsa-standard.atlassian-us-gov-mod.net
JIRA_COOKIES=<captured automatically on first login>
```

> **Tip:** Ask Auger: *"Show me all my in-progress Jira stories for ASSIST project"*
