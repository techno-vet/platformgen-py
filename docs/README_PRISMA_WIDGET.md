# Prisma Cloud Widget

The **Prisma Cloud** widget is built for the CVE tracking work behind tasks **149**, **151**, and **174 / ASSIST3-39486**. It combines live Prisma Cloud access, Jira reconciliation, CSV fallback imports, daily ZIP history imports, and embedded AI analysis in one tab.

## What It Does

1. Authenticates to **Prisma Cloud Gov** using:
   - `PRISMA_CLOUD_URL`
   - `PRISMA_CLOUD_ACCESS_KEY`
   - `PRISMA_CLOUD_SECRET_KEY`
2. Pulls live image vulnerability data from Prisma endpoints when available
3. Imports Prisma CSV exports if live API data is unavailable or you want a saved snapshot
4. Imports the daily emailed Prisma ZIP reports from `~/Downloads` into a widget-owned SQLite history DB
5. Marks tracked findings as **open** vs **remediated** when they disappear from later daily reports
6. Loads Jira issues via the shared Jira MFA session or imports Jira CSVs
7. Buckets CVEs into:
   - **Only in Prisma**
   - **In Both**
   - **Validate Fixed**
   - **Likely Remediated**
   - **Only in Jira**
8. Provides **AI analysis** for summarizing findings and drafting Jira/Scrum updates

## Why It Exists

This widget is meant to replace the older “manual CSV juggling” workflow with a reusable reconciliation workspace:

- **Task 149**: compare Prisma and Jira CVE tracking
- **Task 151**: make better use of the Prisma API key once available
- **Task 174 / ASSIST3-39486**: build the daily Prisma history workflow so findings can be tracked over time and checked against Jira

## Main Tabs

### Overview
- shows auth mode, source endpoint, Prisma counts, Jira counts, and reconciliation totals

### Vulnerabilities
- searchable/filterable Prisma findings table
- selection details for the currently highlighted CVE/package/image row

### Jira
- shows Jira issues loaded from live JQL or imported CSV
- extracts CVE IDs from issue content for tracking comparison

### Reconcile
- breaks findings into the reconciliation buckets used by the remediation workflow

### History
- shows tracked findings from the local Prisma history DB
- supports **Open**, **Remediated**, and **All** views across imported daily reports

### AI
- runs targeted Copilot-based analysis from the current widget context
- useful for:
  - summarizing current risk
  - drafting a Jira/SRE update
  - checking CVEs that look fixed in Jira but still appear in Prisma
  - reviewing likely-remediated CVEs before closure

## Expected Credentials

Use the **API Keys+** widget to save:

```bash
PRISMA_CLOUD_URL=https://app.gov.prismacloud.io
PRISMA_CLOUD_ACCESS_KEY=...
PRISMA_CLOUD_SECRET_KEY=...
```

For Jira API loading, the widget reuses the existing **Jira MFA session** from the Jira widget.

The local history DB lives at:

```text
~/.platformgen/logs/prisma_cloud.db
```

## Notes

- The widget supports both **Gov tenant auth** and **Runtime Security / Compute-oriented endpoints**
- For Prisma auth, the standard mapping is:
  - **username = Access Key**
  - **password = Secret Key**
- If live API pulls are limited, use the **Load Prisma CSV** / **Load Jira CSV** buttons and continue the same reconciliation flow
- For Task 174, download the 3 daily ZIP archives to `~/Downloads` and use **Import Daily ZIPs** to append them into history without deleting older findings
- Current Task 174 scope is filtered to:
  - `assist-prod`
  - `assist-staging06`
  - namespaces starting with `data-` in staging and prod
