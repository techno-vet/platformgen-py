# Database Widget

The **Database** widget is a SQL workbench built into Auger. Run queries, browse schemas, and export results — all without leaving the platform.

## Features

| Feature | Detail |
|---------|--------|
| **SQL Editor** | Multi-line editor with syntax highlighting; press **Ctrl+Enter** or click **Run** to execute |
| **Schema Browser** | Expand tables to see columns, types, and indexes |
| **Results Grid** | Sortable, scrollable table view with row count |
| **Export** | Save results as CSV |
| **Connection Manager** | Switch between SQLite files, PostgreSQL, and MySQL connections |
| **Query History** | Recent queries saved and re-runnable |

## Supported Databases

- **SQLite** — local `.db` files (default: `~/.auger/tasks.db`)
- **PostgreSQL** — via connection string
- **MySQL/MariaDB** — via connection string

## Quick Start

1. The widget opens connected to `~/.auger/tasks.db` by default
2. Type a query in the editor: `SELECT * FROM tasks WHERE status = 'In Progress';`
3. Press **Ctrl+Enter** to run
4. Results appear in the grid below

## Connection Strings

Add database connections via the API Keys+ widget or `.env`:

```bash
# PostgreSQL
DATABASE_URL=postgresql://user:password@hostname:5432/dbname

# SQLite (specify path)
SQLITE_PATH=/path/to/your.db
```

> **Tip:** Ask Auger to help: *"Write a query to find all tasks created in the last 7 days"*
