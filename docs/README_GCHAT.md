# Google Chat Widget

Post messages to Google Chat spaces using incoming webhooks. No OAuth required — webhook URLs are your credentials.

## Setup

1. In Google Chat, open a Space → **Apps & Integrations** → **Manage webhooks** → **Add webhook**
2. Copy the webhook URL
3. In the **⚙️ Webhooks** tab, click **+ Add** and paste the URL with a name

## Sending Messages

1. Open the **📨 Send** tab
2. Select a target from the **To:** dropdown
3. Type your message (plain text or markdown)
4. Click **Send →**

## Quick Fill Buttons

| Button | What it fills |
|---|---|
| **Active PR** | Current branch, last commit, and PR link |
| **Current Task** | The task currently marked  |
| **Auger Invite** | Invite message with install link for new users |

## Webhook Management (⚙️ Webhooks tab)

| Action | How |
|---|---|
| **Add** | Click **+ Add**, enter name and URL |
| **Edit** | Click **Edit** on any webhook row |
| **Delete** | Click **Delete** (asks for confirmation) |
| **Test** | Click **Test** — sends a test message to verify the webhook works |

## Storage

Webhooks are stored in  as:


## Tips

- Webhook name is uppercased automatically ( → )
- You can add as many webhooks as you need — they all appear in the Send dropdown
- Use **Active PR** quick fill + **PR Reviews** webhook to request code review in one click
