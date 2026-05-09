"""SQLite-backed history store for daily Prisma vulnerability ZIP imports."""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from platformgen.ui.utils import auger_home as _auger_home
except ImportError:
    def _auger_home():  # type: ignore[no-redef]
        return Path.home()

from auger.tools import prisma_cloud as _prisma_cloud


DOWNLOAD_ZIP_GLOB = "IA-FAA ASSIST *_Deployed_Image_Vulnerability_Report_*.zip"
DB_PATH = _auger_home() / ".auger" / "logs" / "prisma_cloud.db"
ENV_ALIASES = {
    "DEV": "dev",
    "STG": "stg",
    "PROD": "prod",
    "DEVELOPMENT": "dev",
    "STAGING": "stg",
    "PRODUCTION": "prod",
}
SEVERITY_RANK = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "unknown": 4,
    "": 5,
}


class PrismaHistoryError(RuntimeError):
    """Raised when the Prisma history DB or ZIP imports fail."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def history_db_path() -> Path:
    """Return the widget-owned Prisma history DB path."""
    return DB_PATH


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path | None = None) -> Path:
    """Create the Prisma history DB schema if needed."""
    path = Path(db_path or DB_PATH)
    with _connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS report_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                env TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_kind TEXT NOT NULL,
                zip_path TEXT NOT NULL,
                zip_name TEXT NOT NULL,
                member_name TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL UNIQUE,
                row_count INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS findings (
                finding_key TEXT PRIMARY KEY,
                env TEXT NOT NULL,
                cluster_name TEXT,
                namespace TEXT,
                image TEXT,
                cve TEXT NOT NULL,
                package TEXT,
                version TEXT,
                location TEXT,
                source TEXT,
                vulnerability_type TEXT,
                first_seen_date TEXT,
                last_seen_date TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                current_severity TEXT,
                current_fixable TEXT,
                current_fix_date TEXT,
                current_fixed_version TEXT,
                current_summary TEXT,
                current_link TEXT,
                current_risk_factors TEXT,
                first_report_id INTEGER,
                last_report_id INTEGER,
                remediated_at TEXT,
                remediated_by_report_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS finding_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                finding_key TEXT NOT NULL,
                report_id INTEGER NOT NULL,
                env TEXT NOT NULL,
                report_date TEXT NOT NULL,
                report_kind TEXT NOT NULL,
                severity TEXT,
                cluster_name TEXT,
                namespace TEXT,
                image TEXT,
                host TEXT,
                cve TEXT NOT NULL,
                package TEXT,
                version TEXT,
                fixable TEXT,
                fix_date TEXT,
                fixed_version TEXT,
                source TEXT,
                location TEXT,
                risk_factors TEXT,
                scanned_on TEXT,
                first_discovered_on_image TEXT,
                first_discovered_on_system TEXT,
                vulnerability_type TEXT,
                summary TEXT,
                link TEXT,
                raw_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(finding_key, report_id),
                FOREIGN KEY (finding_key) REFERENCES findings(finding_key),
                FOREIGN KEY (report_id) REFERENCES report_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_report_runs_env_date ON report_runs(env, report_date, report_kind);
            CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, env, last_seen_date);
            CREATE INDEX IF NOT EXISTS idx_findings_cve ON findings(cve, env);
            CREATE INDEX IF NOT EXISTS idx_occurrences_report ON finding_occurrences(report_id);
            """
        )
        _ensure_findings_columns(conn)
    return path


def _ensure_findings_columns(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
    for column_name, column_type in (
        ("jira_issue_key", "TEXT"),
        ("jira_status", "TEXT"),
        ("jira_summary", "TEXT"),
        ("jira_updated", "TEXT"),
    ):
        if column_name not in columns:
            conn.execute(f"ALTER TABLE findings ADD COLUMN {column_name} {column_type}")


def _parse_env_from_name(name: str) -> str:
    upper = name.upper()
    for token, env in ENV_ALIASES.items():
        if f" {token}_" in upper or f" {token} " in upper or upper.startswith(token):
            return env
    return ""


def _parse_date_from_name(name: str) -> str:
    stem = Path(name).stem
    for part in reversed(stem.split("_")):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return ""


def _row_fingerprint(row: dict[str, str]) -> str:
    material = "|".join(
        (
            row.get("env", "").lower(),
            row.get("cluster", "").lower(),
            row.get("namespace", "").lower(),
            row.get("image", "").lower(),
            row.get("cve", "").upper(),
            row.get("package", "").lower(),
            row.get("version", "").lower(),
            row.get("location", "").lower(),
        )
    )
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _min_date(*values: str) -> str:
    cleaned = sorted(value for value in values if value)
    return cleaned[0] if cleaned else ""


def _severity_sort_key(value: str) -> tuple[int, str]:
    clean = (value or "").strip().lower()
    return (SEVERITY_RANK.get(clean, 99), clean)


def _report_kind(member_name: str) -> str:
    return "fixable" if "FIXABLE" in member_name.upper() else "all"


def _display_fixed_version(fixed_version: str, fixable: str) -> str:
    fixed_version = (fixed_version or "").strip()
    if fixed_version:
        return fixed_version
    fixable = (fixable or "").strip()
    return fixable if fixable.lower().startswith("fixed in ") else ""


def _split_namespaces(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def namespace_is_relevant(env: str, namespace: str) -> bool:
    """Return whether the finding namespace is in scope for Task 174."""
    namespaces = _split_namespaces(namespace)
    if not namespaces:
        return False
    if "assist-prod" in namespaces:
        return True
    if "assist-staging06" in namespaces:
        return True
    if env in {"stg", "prod"} and any(item.startswith("data-") for item in namespaces):
        return True
    return False


def row_is_relevant(row: dict[str, str]) -> bool:
    """Return whether a normalized finding row is in the current Prisma scope."""
    return namespace_is_relevant((row.get("env") or "").strip().lower(), row.get("namespace", ""))


def filter_relevant_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Keep only the namespace-scoped findings currently relevant to Task 174."""
    return [row for row in rows if row_is_relevant(row)]


def discover_download_archives(download_dir: Path | None = None) -> list[Path]:
    """Return matching daily Prisma ZIP archives from Downloads."""
    root = Path(download_dir or (Path.home() / "Downloads"))
    if not root.exists():
        return []
    return sorted(root.glob(DOWNLOAD_ZIP_GLOB))


def import_download_archives(download_dir: Path | None = None, db_path: Path | None = None) -> dict[str, object]:
    """Import all matching Prisma ZIP archives from Downloads."""
    archives = discover_download_archives(download_dir)
    if not archives:
        raise PrismaHistoryError(f"No Prisma ZIP archives found in {(download_dir or (Path.home() / 'Downloads'))}")

    init_db(db_path)
    imported: list[dict[str, object]] = []
    for archive in archives:
        imported.append(import_archive(archive, db_path=db_path))

    summary = get_db_summary(db_path=db_path)
    latest_rows = load_current_findings(db_path=db_path)
    return {
        "archives": imported,
        "db_summary": summary,
        "latest_rows": latest_rows,
    }


def import_archive(zip_path: Path | str, db_path: Path | None = None) -> dict[str, object]:
    """Import one Prisma ZIP archive containing the daily CSV reports."""
    path = Path(zip_path)
    if not path.exists():
        raise PrismaHistoryError(f"ZIP archive not found: {path}")

    env = _parse_env_from_name(path.name)
    report_date = _parse_date_from_name(path.name)
    if not env or not report_date:
        raise PrismaHistoryError(f"Could not parse env/date from {path.name}")

    init_db(db_path)
    totals = {
        "zip_path": str(path),
        "env": env,
        "report_date": report_date,
        "reports_imported": 0,
        "reports_skipped": 0,
        "rows_imported": 0,
    }

    with _connect(db_path) as conn, zipfile.ZipFile(path) as zf:
        for info in sorted(zf.infolist(), key=lambda item: item.filename):
            if info.is_dir() or not info.filename.lower().endswith(".csv"):
                continue

            report_kind = _report_kind(info.filename)
            fingerprint = f"{path.name}:{info.filename}:{info.CRC}:{info.file_size}"
            existing = conn.execute(
                "SELECT id FROM report_runs WHERE content_fingerprint = ?",
                (fingerprint,),
            ).fetchone()
            if existing:
                totals["reports_skipped"] += 1
                continue

            imported_at = _now()
            cursor = conn.execute(
                """
                INSERT INTO report_runs (
                    env, report_date, report_kind, zip_path, zip_name, member_name,
                    content_fingerprint, row_count, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    env,
                    report_date,
                    report_kind,
                    str(path),
                    path.name,
                    info.filename,
                    fingerprint,
                    imported_at,
                ),
            )
            report_id = int(cursor.lastrowid)

            rows_imported, seen_keys = _import_member_rows(
                conn=conn,
                zf=zf,
                info=info,
                env=env,
                report_date=report_date,
                report_kind=report_kind,
                report_id=report_id,
                imported_at=imported_at,
            )
            conn.execute(
                "UPDATE report_runs SET row_count = ? WHERE id = ?",
                (rows_imported, report_id),
            )
            totals["reports_imported"] += 1
            totals["rows_imported"] += rows_imported

            latest_full = conn.execute(
                "SELECT MAX(report_date) AS latest FROM report_runs WHERE env = ? AND report_kind = 'all'",
                (env,),
            ).fetchone()
            if report_kind == "all" and latest_full and latest_full["latest"] == report_date:
                _mark_missing_as_remediated(conn, env=env, report_date=report_date, report_id=report_id, seen_keys=seen_keys)

    return totals


def _import_member_rows(
    *,
    conn: sqlite3.Connection,
    zf: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    env: str,
    report_date: str,
    report_kind: str,
    report_id: int,
    imported_at: str,
) -> tuple[int, set[str]]:
    seen_keys: set[str] = set()
    count = 0

    with zf.open(info, "r") as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="ignore"))
        for raw_row in reader:
            if not raw_row:
                continue
            row = _prisma_cloud.normalize_csv_row(raw_row)
            if not row.get("cve"):
                continue

            row["env"] = env
            row["report_date"] = report_date
            row["report_kind"] = report_kind
            if not row_is_relevant(row):
                continue
            finding_key = _row_fingerprint(row)
            seen_keys.add(finding_key)
            _upsert_finding(conn, row=row, finding_key=finding_key, report_id=report_id, report_date=report_date)
            conn.execute(
                """
                INSERT OR IGNORE INTO finding_occurrences (
                    finding_key, report_id, env, report_date, report_kind, severity, cluster_name,
                    namespace, image, host, cve, package, version, fixable, fix_date, fixed_version,
                    source, location, risk_factors, scanned_on, first_discovered_on_image,
                    first_discovered_on_system, vulnerability_type, summary, link, raw_json, imported_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_key,
                    report_id,
                    env,
                    report_date,
                    report_kind,
                    row.get("severity", ""),
                    row.get("cluster", ""),
                    row.get("namespace", ""),
                    row.get("image", ""),
                    row.get("host", ""),
                    row.get("cve", ""),
                    row.get("package", ""),
                    row.get("version", ""),
                    row.get("fixable", ""),
                    row.get("fix_date", ""),
                    row.get("fixed_version", ""),
                    row.get("source", ""),
                    row.get("location", ""),
                    row.get("risk_factors", ""),
                    row.get("scanned_on", ""),
                    row.get("first_discovered_on_image", ""),
                    row.get("first_discovered_on_system", ""),
                    row.get("vulnerability_type", ""),
                    row.get("description", ""),
                    row.get("link", ""),
                    _prisma_cloud._stringify(row),
                    imported_at,
                ),
            )
            count += 1
    return count, seen_keys


def _upsert_finding(
    conn: sqlite3.Connection,
    *,
    row: dict[str, str],
    finding_key: str,
    report_id: int,
    report_date: str,
) -> None:
    conn.execute(
        """
        INSERT INTO findings (
            finding_key, env, cluster_name, namespace, image, cve, package, version, location,
            source, vulnerability_type, first_seen_date, last_seen_date, status, current_severity,
            current_fixable, current_fix_date, current_fixed_version, current_summary, current_link,
            current_risk_factors, first_report_id, last_report_id, remediated_at, remediated_by_report_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
        ON CONFLICT(finding_key) DO UPDATE SET
            first_seen_date = CASE
                WHEN findings.first_seen_date IS NULL OR findings.first_seen_date = '' THEN excluded.first_seen_date
                WHEN excluded.first_seen_date < findings.first_seen_date THEN excluded.first_seen_date
                ELSE findings.first_seen_date
            END,
            last_seen_date = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.last_seen_date
                ELSE excluded.last_seen_date
            END,
            status = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.status
                ELSE 'open'
            END,
            current_severity = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_severity
                ELSE excluded.current_severity
            END,
            current_fixable = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_fixable
                ELSE excluded.current_fixable
            END,
            current_fix_date = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_fix_date
                ELSE excluded.current_fix_date
            END,
            current_fixed_version = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_fixed_version
                ELSE excluded.current_fixed_version
            END,
            current_summary = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_summary
                ELSE excluded.current_summary
            END,
            current_link = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_link
                ELSE excluded.current_link
            END,
            current_risk_factors = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.current_risk_factors
                ELSE excluded.current_risk_factors
            END,
            last_report_id = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.last_report_id
                ELSE excluded.last_report_id
            END,
            remediated_at = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.remediated_at
                ELSE NULL
            END,
            remediated_by_report_id = CASE
                WHEN COALESCE(findings.last_seen_date, '') > excluded.last_seen_date THEN findings.remediated_by_report_id
                ELSE NULL
            END
        """,
        (
            finding_key,
            row.get("env", ""),
            row.get("cluster", ""),
            row.get("namespace", ""),
            row.get("image", ""),
            row.get("cve", ""),
            row.get("package", ""),
            row.get("version", ""),
            row.get("location", ""),
            row.get("source", ""),
            row.get("vulnerability_type", ""),
            report_date,
            report_date,
            row.get("severity", ""),
            row.get("fixable", ""),
            row.get("fix_date", ""),
            row.get("fixed_version", ""),
            row.get("description", ""),
            row.get("link", ""),
            row.get("risk_factors", ""),
            report_id,
            report_id,
        ),
    )


def _mark_missing_as_remediated(
    conn: sqlite3.Connection,
    *,
    env: str,
    report_date: str,
    report_id: int,
    seen_keys: Iterable[str],
) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.current_prisma_seen")
    conn.execute("CREATE TEMP TABLE current_prisma_seen (finding_key TEXT PRIMARY KEY)")
    conn.executemany(
        "INSERT OR IGNORE INTO current_prisma_seen(finding_key) VALUES (?)",
        ((key,) for key in seen_keys),
    )
    conn.execute(
        """
        UPDATE findings
        SET status = 'remediated',
            remediated_at = ?,
            remediated_by_report_id = ?
        WHERE env = ?
          AND status = 'open'
          AND COALESCE(last_seen_date, '') <= ?
          AND NOT EXISTS (
              SELECT 1 FROM current_prisma_seen seen
              WHERE seen.finding_key = findings.finding_key
          )
        """,
        (report_date, report_id, env, report_date),
    )
    conn.execute("DROP TABLE IF EXISTS temp.current_prisma_seen")


def load_current_findings(db_path: Path | None = None) -> list[dict[str, str]]:
    """Return the latest open findings from the Prisma history DB."""
    init_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                env,
                cluster_name,
                namespace,
                image,
                cve,
                package,
                version,
                current_fixed_version,
                current_fixable,
                current_fix_date,
                current_severity,
                current_summary,
                current_link,
                current_risk_factors,
                jira_issue_key,
                jira_status,
                jira_summary,
                jira_updated,
                first_seen_date,
                last_seen_date,
                status
            FROM findings
            WHERE status = 'open'
            ORDER BY
                CASE lower(current_severity)
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                cve,
                image
            """
        ).fetchall()

    results: list[dict[str, str]] = []
    for record in rows:
        env = (record["env"] or "").strip().lower()
        namespace = record["namespace"] or ""
        if not namespace_is_relevant(env, namespace):
            continue
        results.append(
            {
                "env": env,
                "cluster": record["cluster_name"] or "",
                "namespace": namespace,
                "image": record["image"] or "",
                "cve": record["cve"] or "",
                "package": record["package"] or "",
                "version": record["version"] or "",
                "fixed_version": _display_fixed_version(record["current_fixed_version"] or "", record["current_fixable"] or ""),
                "fixable": record["current_fixable"] or "",
                "fix_date": record["current_fix_date"] or "",
                "severity": record["current_severity"] or "",
                "description": record["current_summary"] or "",
                "link": record["current_link"] or "",
                "risk_factors": record["current_risk_factors"] or "",
                "jira_story_key": record["jira_issue_key"] or "",
                "jira_story": _jira_story_suffix(record["jira_issue_key"] or ""),
                "jira_status": record["jira_status"] or "",
                "jira_story_summary": record["jira_summary"] or "",
                "jira_updated": record["jira_updated"] or "",
                "first_seen_date": record["first_seen_date"] or "",
                "last_seen_date": record["last_seen_date"] or "",
                "history_status": record["status"] or "",
            }
        )
    return results


def load_history_rows(status: str = "all", db_path: Path | None = None, limit: int = 5000) -> list[dict[str, str]]:
    """Return tracked findings from the Prisma history DB."""
    init_db(db_path)
    status_clause = ""
    params: list[object] = []
    if status != "all":
        status_clause = "WHERE status = ?"
        params.append(status)
    params.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                cve,
                status,
                env,
                cluster_name,
                namespace,
                package,
                version,
                image,
                current_severity,
                current_fixed_version,
                current_fixable,
                first_seen_date,
                last_seen_date
            FROM findings
            {status_clause}
            ORDER BY
                CASE status WHEN 'open' THEN 0 ELSE 1 END,
                CASE lower(current_severity)
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                last_seen_date DESC,
                cve
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    results: list[dict[str, str]] = []
    for row in rows:
        env = (row["env"] or "").strip().lower()
        namespace = row["namespace"] or ""
        if not namespace_is_relevant(env, namespace):
            continue
        results.append(
            {
                "cve": row["cve"] or "",
                "status": row["status"] or "",
                "env": env,
                "cluster": row["cluster_name"] or "",
                "namespace": namespace,
                "package": row["package"] or "",
                "version": row["version"] or "",
                "image": row["image"] or "",
                "severity": row["current_severity"] or "",
                "fixed_version": _display_fixed_version(row["current_fixed_version"] or "", row["current_fixable"] or ""),
                "first_seen_date": row["first_seen_date"] or "",
                "last_seen_date": row["last_seen_date"] or "",
            }
        )
    return results


def get_db_summary(db_path: Path | None = None) -> dict[str, object]:
    """Return high-level Prisma history DB counts and latest report dates."""
    init_db(db_path)
    with _connect(db_path) as conn:
        counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM report_runs) AS report_runs,
                (SELECT COUNT(*) FROM report_runs WHERE report_kind = 'all') AS full_reports,
                (SELECT COUNT(*) FROM report_runs WHERE report_kind = 'fixable') AS fixable_reports,
                (SELECT COUNT(*) FROM findings) AS total_findings,
                (SELECT COUNT(*) FROM findings WHERE status = 'open') AS open_findings,
                (SELECT COUNT(*) FROM findings WHERE status = 'remediated') AS remediated_findings
            """
        ).fetchone()
        latest = conn.execute(
            """
            SELECT env, MAX(report_date) AS latest_report_date
            FROM report_runs
            WHERE report_kind = 'all'
            GROUP BY env
            ORDER BY env
            """
        ).fetchall()
        finding_rows = conn.execute("SELECT env, namespace, status FROM findings").fetchall()

    relevant_rows = [
        row for row in finding_rows
        if namespace_is_relevant((row["env"] or "").strip().lower(), row["namespace"] or "")
    ]
    open_by_env: dict[str, int] = {}
    total_findings = 0
    open_findings = 0
    remediated_findings = 0
    for row in relevant_rows:
        total_findings += 1
        env = (row["env"] or "").strip().lower()
        status = (row["status"] or "").strip().lower()
        if status == "open":
            open_findings += 1
            open_by_env[env] = open_by_env.get(env, 0) + 1
        elif status == "remediated":
            remediated_findings += 1

    return {
        "db_path": str(Path(db_path or DB_PATH)),
        "report_runs": int(counts["report_runs"] or 0),
        "full_reports": int(counts["full_reports"] or 0),
        "fixable_reports": int(counts["fixable_reports"] or 0),
        "total_findings": total_findings,
        "open_findings": open_findings,
        "remediated_findings": remediated_findings,
        "latest_by_env": {
            row["env"]: row["latest_report_date"]
            for row in latest
            if (row["env"] or "").strip().lower() in {"stg", "prod"}
        },
        "open_by_env": open_by_env,
    }


def purge_irrelevant_findings(db_path: Path | None = None) -> dict[str, int]:
    """Delete findings/occurrences outside the current Task 174 namespace scope."""
    init_db(db_path)
    removed_findings = 0
    removed_occurrences = 0
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT finding_key, env, namespace FROM findings").fetchall()
        stale_keys = [
            row["finding_key"]
            for row in rows
            if not namespace_is_relevant((row["env"] or "").strip().lower(), row["namespace"] or "")
        ]
        if not stale_keys:
            return {"removed_findings": 0, "removed_occurrences": 0}

        for index in range(0, len(stale_keys), 500):
            chunk = stale_keys[index:index + 500]
            placeholders = ",".join("?" for _ in chunk)
            removed_occurrences += conn.execute(
                f"DELETE FROM finding_occurrences WHERE finding_key IN ({placeholders})",
                tuple(chunk),
            ).rowcount
            removed_findings += conn.execute(
                f"DELETE FROM findings WHERE finding_key IN ({placeholders})",
                tuple(chunk),
            ).rowcount
    return {"removed_findings": removed_findings, "removed_occurrences": removed_occurrences}


def save_jira_matches(matches_by_cve: dict[str, dict[str, str]], db_path: Path | None = None) -> int:
    """Persist best Jira match metadata onto findings keyed by CVE."""
    init_db(db_path)
    updated = 0
    with _connect(db_path) as conn:
        for cve, match in matches_by_cve.items():
            updated += conn.execute(
                """
                UPDATE findings
                SET jira_issue_key = ?,
                    jira_status = ?,
                    jira_summary = ?,
                    jira_updated = ?
                WHERE UPPER(cve) = ?
                """,
                (
                    match.get("jira_issue_key", ""),
                    match.get("jira_status", ""),
                    match.get("jira_summary", ""),
                    match.get("jira_updated", ""),
                    (cve or "").upper(),
                ),
            ).rowcount
    return updated


def _jira_story_suffix(issue_key: str) -> str:
    issue_key = (issue_key or "").strip()
    if "-" not in issue_key:
        return ""
    digits = issue_key.rsplit("-", 1)[-1]
    return digits[-5:] if digits.isdigit() else ""
