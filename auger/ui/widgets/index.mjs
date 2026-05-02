#!/usr/bin/env node
import { v2 } from "@datadog/datadog-api-client";
import chalk from "chalk";
import * as dotenv from "dotenv";
import * as fs from "fs";
import yargs from "yargs";

const argv = yargs(process.argv).options({
    query: { type: 'string', demandOption: true, description: 'The search query' },
    index: { type: 'string', default: 'main', description: 'The index to search' },
    from: { type: 'string', description: 'Start time (minutes ago or ISO date)' },
    to: { type: 'string', description: 'End time (minutes ago or ISO date)' },
    pageSize: { type: 'number', description: 'Page size' },
    format: { type: 'string', default: 'json', description: 'Output format (json or ndjson)' },
    output: { type: 'string', description: 'Output file' },
    cursor: { type: 'string', description: 'Pagination cursor' },
    append: { type: 'boolean', default: false, description: 'Append to output file' },
    sort: { type: 'string', default: 'timestamp', description: 'Sort order: timestamp (asc) or -timestamp (desc)' }
}).argv;

dotenv.config();

const configuration = v2.createConfiguration();
const apiInstance = new v2.LogsApi(configuration);

async function getLogs(apiInstance, params) {
    let nextPage = params.pageCursor ?? null;
    let n = 1;
    do {
        console.log(`Requesting page ${n++} ${nextPage ? `with cursor ${nextPage} ` : ``}`);
        let query = { ...params };

        if (nextPage) {
            query.pageCursor = nextPage;
        } else {
            delete query.pageCursor;
        }

        try {
            const result = await apiInstance.listLogsGet(query);

            if (result && result.data) {
                result.data.forEach((row) => processLog(params, row));
                nextPage = result?.meta?.page?.after;
                console.log(`${result.data.length} results (${data.length} total)`);
            } else {
                console.log(chalk.yellow("No data returned in this page."));
                nextPage = null;
            }
        } catch (error) {
            console.error(chalk.red("Error fetching logs:"), error);
            return false;
        }
    } while (nextPage);
    return true;
}

const data = [];
let ndjsonOutputFile = null;

async function processLog(params, row) {
    switch (params.format) {
        case "json":
            data.push(row);
            break;
        case "ndjson":
            // Use appendFileSync so each row is flushed immediately —
            // allows Python's file-tail reader to pick up rows as they arrive.
            if (ndjsonOutputFile === null) {
                ndjsonOutputFile = argv.output ?? 'results.json';
                if (!params.append) {
                    fs.writeFileSync(ndjsonOutputFile, ''); // truncate
                }
            }
            fs.appendFileSync(ndjsonOutputFile, JSON.stringify(row, null) + '\n');
            break;
        default:
            console.log(chalk.red(`Unknown format ${params.format}`));
            process.exit(1);
    }
}

function parseTime(timeInput) {
    if (!timeInput) return null;

    // Pure number = minutes ago
    if (!isNaN(timeInput)) {
        const minutesAgo = parseFloat(timeInput);
        return new Date(Date.now() - minutesAgo * 60 * 1000);
    }

    // Relative: 30m, 2h, 1d
    const relMatch = String(timeInput).match(/^(\d+(?:\.\d+)?)(m|h|d)$/i);
    if (relMatch) {
        const n = parseFloat(relMatch[1]);
        const unit = relMatch[2].toLowerCase();
        const ms = unit === 'm' ? n * 60_000
                 : unit === 'h' ? n * 3_600_000
                 : n * 86_400_000;
        return new Date(Date.now() - ms);
    }

    try {
        const d = new Date(timeInput);
        if (isNaN(d.getTime())) return null;
        return d;
    } catch (e) {
        console.error(chalk.red(`Error parsing date: ${timeInput}`), e);
        return null;
    }
}

const defaultFromMinutes = 15;
const initialParams = {
    filterQuery: argv.query,
    filterIndex: argv.index ?? "main",
    filterFrom: parseTime(argv.from) || new Date(Date.now() - defaultFromMinutes * 60 * 1000),
    filterTo: parseTime(argv.to) || new Date(),
    pageLimit: argv.pageSize ? Math.min(argv.pageSize, 5000) : 1000,
    format: argv.format ?? "json",
    append: (argv.append) ? true : false,
    sort: argv.sort ?? 'timestamp',
};

if (!initialParams.filterQuery) {
    console.log(chalk.red("Error: No query supplied, use --query"));
    process.exit();
}

console.log(chalk.cyan("Downloading logs:\n" + JSON.stringify(initialParams, null, 2) + "\n"));

(async function () {
    try {
        await getLogs(apiInstance, initialParams);
    } catch (e) {
        console.log(chalk.red(e.message));
        process.exit(1);
    }

    switch (initialParams.format) {
        case "ndjson":
            // appendFileSync writes are already flushed — nothing to close
            break;
        case "json":
            const outputFile = argv.output ?? "results.json";
            console.log(chalk.cyan(`\nWriting ${data.length} logs to ${outputFile}`));
            fs.writeFileSync(outputFile, JSON.stringify(data, null, 2));
            break;
    }

    console.log(chalk.green("Done!"));
})();
