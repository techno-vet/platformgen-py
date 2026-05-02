# ServiceNow Widget

The ServiceNow widget provides a streamlined interface for interacting with your ServiceNow instance, including MFA-based login and incident/change management.

## Features

- **MFA Login** — automated ServiceNow login with MFA push notification support
- **Incident View** — browse and filter open incidents
- **Change Requests** — view upcoming and in-progress changes
- **Quick Actions** — update ticket status, add work notes

## Login

1. Enter your ServiceNow credentials in the Login tab
2. Click **Login** — the widget streams login progress in real time
3. On MFA prompt, approve the push notification on your device
4. Session cookie is cached for subsequent requests

## Configuration

Set these in your `~/.auger/.env`:

```bash
SERVICENOW_INSTANCE=your-instance.service-now.com
SERVICENOW_USER=your.username
```

## Ask Auger

> "show me my open ServiceNow incidents"
> "create a change request in ServiceNow"
> "what is the status of CHG0012345?"
