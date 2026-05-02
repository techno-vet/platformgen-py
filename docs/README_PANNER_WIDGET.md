# Panner Widget - DataDog Log Downloader

## Overview
The Panner widget (also known as Rover) provides a powerful interface for downloading and analyzing logs from DataDog. It bypasses the 5000 log export limit in the DataDog UI by using the DataDog API directly.

## Features

### 🔍 Advanced Filtering
- **Query Builder** - Manually enter DataDog queries or use visual filters
- **Cluster Selection** - Multi-select from available clusters
- **Namespace Selection** - Filter by Kubernetes namespaces
- **Service Selection** - Choose from ASSIST services and Dockerfile services
- **Auto-Query Generation** - Selections automatically build the query string

### 📊 Results Display
- **Tabular View** - See logs in organized columns (Cluster, Namespace, Service, Container, Status, Timestamp, Message)
- **Error Highlighting** - Rows with error status are highlighted in red
- **JSON Details** - Click any log entry to view complete JSON in details panel
- **Scrollable** - Horizontal and vertical scrolling for large datasets

### 🌐 DataDog URL Builder (Integrated)
- **Quick Browser Access** - Open DataDog UI directly from current selections
- **Launch Logs** - Opens DataDog Logs view with your filters applied
- **Launch Pods** - Opens DataDog Orchestration/Pods view
- **Live Tailing** - Enable live tail mode (experimental, may not work)
- **Smart Time Conversion** - Automatically converts "minutes ago" to timestamps
- **One-Click Access** - No need to manually construct URLs

### ⚙️ Configuration Options
- **Index** - Select which DataDog index to query (default: main)
- **Time Range** - Specify "from" and "to" times in minutes ago
- **Page Size** - Control batch size (up to 5000, default: 5000)
- **Output File** - Where to save results (default: results.json)
- **Format** - Choose JSON or NDJSON output format

### 🚀 Large Dataset Support
- Download more than 5000 logs (DataDog UI export limit)
- Background processing - UI remains responsive
- Memory-efficient NDJSON streaming for huge datasets
- Cursor support for resuming interrupted downloads

## Setup

### 1. Configure DataDog Credentials

The widget uses credentials from the API Config widget:

1. Open **API Config** (API Keys+) widget
2. Scroll to **"Datadog"** section
3. Enter your credentials:
   - **API Key** (DATADOG_API_KEY)
   - **App Key** (DATADOG_APP_KEY)
   - **Site** (DATADOG_SITE) - default: ddog-gov.com
4. Click **"Save to .env"**

### 2. Install Node Dependencies

The widget uses a Node.js script to download logs from DataDog:

1. Open the **Panner** widget
2. Click **"📦 Install Dependencies"** button
3. Wait for npm install to complete
4. Status bar will show "✓ Dependencies installed successfully"

**Manual Installation:**
```bash
cd /home/bobbygblair/repos/devtools-scripts/au-silver/astutl_python/au_sre/ui/widgets
npm install --verbose --strict-ssl=false
```

## Usage

### Quick Access to DataDog UI

The easiest way to view logs in DataDog:

1. **Select Filters** (Cluster/Namespace/Service)
2. **Check Options**:
   - ✅ Launch Logs (opens DataDog Logs view)
   - ✅ Launch Pods (opens DataDog Pods view)
   - ⚠️ Live Tailing (experimental, may not work)
3. **Click "🌐 Open in DataDog"**
4. Your browser opens with filters applied

**Example:**
- Select: dev-green cluster, assist-core-dev namespace, core-assist-api service
- Check: Launch Logs
- Result: Opens DataDog Logs filtered to those selections

### Basic Query

1. **Select Filters**:
   - Click items in Cluster, Namespace, or Service lists
   - Hold Ctrl/Cmd for multiple selections
   - Query field updates automatically

2. **Configure Time Range**:
   - "From (min ago)" - how far back to search (e.g., 1 = last minute)
   - "To (min ago)" - optional end time

3. **Click "📡 Download Logs"**:
   - Status bar shows progress
   - Results appear in table when complete
   - Count displayed in bottom-right

4. **View Details**:
   - Click any log entry in table
   - Full JSON appears in bottom panel

### Manual Query

You can bypass the filters and write DataDog queries directly:

```
service:core-assist-api status:error
```

```
kube_cluster_name:dev-green kube_namespace:assist-core-dev
```

```
"exception" OR "failed" -status:info
```

### Advanced Features

**Time Range Examples:**
- `From: 60` = last hour
- `From: 1440` = last 24 hours
- `From: 10080` = last week
- Can also use ISO dates: `2024-01-01`

**Large Downloads:**
1. Set page size to 5000 (max)
2. Select format: **ndjson** (more memory efficient)
3. Results stream to file as they arrive
4. Use cursor option to resume if interrupted

**Export Results:**
- Results saved to file specified in "Output File"
- Default: `results.json` in widget directory
- Access at: `ui/widgets/results.json`

## DataDog Query Syntax

### Field Filters
```
service:core-assist-api
kube_cluster_name:prod-blue
kube_namespace:assist-core-prod
status:error
```

### Logical Operators
```
service:api AND status:error
service:api OR service:worker
service:api -status:info
```

### Wildcards
```
service:core-assist-*
message:*exception*
```

### Grouping
```
(service:api OR service:worker) AND status:error
```

### Text Search
```
"Internal Server Error"
"null pointer exception"
```

## Resource Files

The widget loads filter options from resource files:

- `panner_resources/ddog_assist_clusters` - Available clusters
- `panner_resources/ddog_assist_namespaces` - Kubernetes namespaces
- `panner_resources/ddog_assist_services` - ASSIST services
- `panner_resources/ddog_dockerfile_services` - Dockerfile services

To add more options, edit these files (one option per line).

## Troubleshooting

### "Missing Credentials" error
- Ensure DATADOG_API_KEY and DATADOG_APP_KEY are set in API Config
- Click "Save to .env" after entering credentials
- Restart Auger if needed

### "Node.js not found" error
```bash
# Check if Node.js is installed
node --version

# If not installed, install Node.js
# On Ubuntu/Debian:
sudo apt install nodejs npm

# On macOS:
brew install node
```

### "Dependencies not installed" warning
- Click "📦 Install Dependencies" button in widget
- Or manually run: `cd ui/widgets && npm install`

### Empty results
- Check your query syntax
- Verify time range (might be too narrow)
- Check DataDog credentials are valid
- Look at status bar for error messages

### "JSON decode error"
- Query might have returned no results
- Check DataDog API rate limits
- Verify query syntax is correct

### Large downloads timing out
- Use NDJSON format instead of JSON
- Reduce page size (try 1000 instead of 5000)
- Narrow time range
- Use more specific filters

## Performance Tips

### Memory Usage
- Use **NDJSON** format for downloads over 10,000 logs
- JSON format loads entire dataset into memory
- NDJSON streams line-by-line

### Speed Optimization
- Increase page size to 5000 for faster bulk downloads
- Use specific filters to reduce result set
- Narrow time range when possible

### Best Practices
- Start with small time ranges (1-5 minutes) to test queries
- Use filters instead of broad text searches
- Monitor status bar for progress
- Clear results between queries to free memory

## Technical Details

### DataDog URL Builder
- **Logs URL**: `https://fcs-mcaas-assist.ddog-gov.com/logs`
- **Pods URL**: `https://fcs-mcaas-assist.ddog-gov.com/orchestration/explorer/pod`
- **Query Construction**: Automatically builds DataDog query syntax
- **Timestamp Conversion**: Minutes ago → Unix timestamp (milliseconds)
- **Service Parameter**: Uses `service` for logs, `kube_service` for pods

### Architecture
- **Frontend**: Tkinter widget with Auger dark theme
- **Backend**: Node.js script (index.mjs) calls DataDog API
- **Data Flow**: 
  1. Widget builds command with parameters
  2. Spawns node process with DD credentials
  3. Node script downloads logs via API
  4. Results saved to JSON/NDJSON file
  5. Widget parses and displays in table

### Dependencies
- **Python**: subprocess, json, threading
- **Node.js**: Required for DataDog API calls
- **NPM Packages**: datadog-downloader (installed automatically)

### File Locations
- Widget code: `ui/widgets/panner.py`
- Node script: `ui/widgets/index.mjs`
- Resources: `ui/widgets/panner_resources/`
- Results: `ui/widgets/results.json` (or custom location)
- Node modules: `ui/widgets/node_modules/`

### DataDog API
- Uses DataDog Logs API v2
- Requires API key (organization-level) and App key (user-level)
- Rate limits apply (varies by plan)
- Supports pagination with cursors

## Integration with Ask Auger

The widget provides context to Ask Auger:
- Current query
- Number of logs loaded
- Sample of recent log messages

Example queries:
- "Analyze the error logs and find patterns"
- "What are the most common error messages?"
- "Summarize the logs from the last hour"

## Known Limitations

1. **Node.js Required** - Cannot function without Node.js installed
2. **File-based Output** - Logs saved to file before display (not streamed to UI)
3. **Memory Limits** - Very large JSON datasets (100k+ logs) may cause slowness
4. **No Live Tail** - Downloads historical logs only, not real-time streaming
5. **DataDog API Limits** - Subject to DataDog's rate limits and quotas

## Future Enhancements

Ideas for future development:
- Live tail mode for real-time log streaming
- Export to CSV for analysis in spreadsheets
- Advanced filtering UI with date pickers
- Saved query templates
- Log aggregation and statistics
- Chart/graph visualization
- Integration with other DataDog features (metrics, APM)
- Multi-index querying

## Related Widgets
- **API Keys+** - Configure DataDog credentials
- **Bash $** - Run DataDog CLI commands
- **Prospector** - CVE analysis (uses similar log parsing)

## Support

For issues:
1. Check status bar for error messages
2. Verify DataDog credentials in API Config
3. Run "Install Dependencies" if seeing Node errors
4. Check console logs for detailed errors
5. Verify Node.js is installed: `node --version`

---

**Widget Name**: panner  
**Title**: Panner  
**Icon**: 📡  
**Version**: 1.0  
**Last Updated**: 2026-02-27
