# Tasks Widget

The **Tasks** widget is Auger's built-in SRE task tracker. It persists to `~/.auger/tasks.db` (SQLite) and auto-refreshes every 5 seconds so changes made by Ask Auger appear immediately.

## Features

| Feature | Detail |
|---------|--------|
| **Add task** | Click **Add** to create a new task with title, description, status, priority, and category |
| **Edit task** | Select a row and modify fields in the detail pane; click **Save** |
| **Delete task** | Select a row and click **Delete** |
| **Filter** | Type in the search box to filter across title, description, and category |
| **Color coding** | Rows are color-coded by status (In Progress = blue, Done = green, Blocked = red) |
| **Ask Auger integration** | Ask Auger can create, update, and query tasks automatically |

## Task Fields

- **Title** — Short summary
- **Description** — Full detail; supports multi-line
- **Status** — `Open`, `In Progress`, `Done`, `Blocked`
- **Priority** — `Low`, `Medium`, `High`, `Critical`
- **Category** — Free-form grouping (e.g., `Story to Prod`, `Platform`, `Infra`)

## Database

Tasks are stored at `~/.auger/tasks.db`, shared between the container and host. The file is volume-mounted so tasks survive container restarts.

```bash
# View tasks from the command line
sqlite3 ~/.auger/tasks.db "SELECT id,title,status FROM tasks ORDER BY id DESC LIMIT 20;"
```

## Ask Auger Integration

Ask Auger can manage tasks for you:

> *"Add a task to deploy cryptkeeper BUILD4 to prod with high priority"*
> *"What tasks are currently blocked?"*
> *"Mark task 42 as done"*

Tasks added by Ask Auger appear in the widget within 5 seconds.
