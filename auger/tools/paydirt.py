"""S3-first helpers for the Paydirt Task 174 workflow widget."""

from __future__ import annotations

import fnmatch
import io
import re
import zipfile
from collections import OrderedDict, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import boto3
import yaml
from dotenv import dotenv_values

from auger.tools import prisma_cloud as _prisma_cloud

DEFAULT_BUCKET = "assist-data-development-s3"
DEFAULT_PREFIX = "prisma/raw/"
DEFAULT_REGION = "us-east-1"
DEFAULT_KIND = "fixable"
DEFAULT_MODE = "manual"
LOCAL_GLOB = "IA-FAA*Deployed_Image_Vulnerability_Report*.zip"
CONFIG_PATH = Path.home() / ".auger" / "config.yaml"
ENV_FILE = Path.home() / ".auger" / ".env"
ENV_ORDER = {"dev": 0, "staging": 1, "prod": 2}
ENV_LABELS = {"dev": "DEV", "staging": "STAGING", "prod": "PROD"}
ENV_ALIASES = {
    "dev": "dev",
    "development": "dev",
    "stg": "staging",
    "stage": "staging",
    "staging": "staging",
    "prod": "prod",
    "production": "prod",
    "all": "all",
}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
DEFAULT_MONITOR_TARGETS = [
    {
        "enabled": True,
        "name": "Core Production",
        "env": "prod",
        "cluster_patterns": ["assist-core-production"],
        "namespace_patterns": ["assist-prod"],
    },
    {
        "enabled": True,
        "name": "Core Staging06",
        "env": "staging",
        "cluster_patterns": ["assist-core-staging"],
        "namespace_patterns": ["assist-staging06"],
    },
    {
        "enabled": True,
        "name": "Data Tools Production",
        "env": "prod",
        "cluster_patterns": ["assist-core-production"],
        "namespace_patterns": ["data-api", "data-catalog", "data-pipeline", "data-utils", "help-cms", "kafka*", "debezium*"],
    },
    {
        "enabled": True,
        "name": "Data Tools Staging",
        "env": "staging",
        "cluster_patterns": ["assist-core-staging"],
        "namespace_patterns": ["data-api", "data-catalog", "data-pipeline", "data-utils", "help-cms", "kafka*", "debezium*"],
    },
]
_SNAPSHOT_CACHE: "OrderedDict[tuple[str, str], Snapshot]" = OrderedDict()


class PaydirtError(RuntimeError):
    """Raised when Paydirt cannot list or load report data."""


@dataclass(frozen=True)
class ReportArchive:
    source: str
    env: str
    report_date: str
    label: str
    bucket: str = ""
    key: str = ""
    path: str = ""
    size: int = 0
    last_modified: str = ""

    @property
    def locator(self) -> str:
        if self.source == "s3":
            return f"s3://{self.bucket}/{self.key}"
        return self.path


@dataclass
class Snapshot:
    archive: ReportArchive
    report_kind: str
    member_name: str
    rows: list[dict[str, str]]
    summary: dict[str, int]


def load_settings() -> dict[str, object]:
    env = dotenv_values(ENV_FILE)
    config = _load_config().get("paydirt") or {}
    return {
        "bucket": str(config.get("bucket") or env.get("PRISMA_REPORTS_BUCKET") or DEFAULT_BUCKET).strip(),
        "prefix": str(config.get("prefix") or env.get("PRISMA_REPORTS_PREFIX") or DEFAULT_PREFIX).strip(),
        "region": str(config.get("region") or env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION).strip(),
        "workflow_mode": _normalize_mode(config.get("workflow_mode") or DEFAULT_MODE),
        "monitor_targets": normalize_monitor_targets(config.get("monitor_targets"), use_default_if_empty=True),
        "access_key": str(env.get("DEV_S3_AWS_ACCESS_KEY_ID") or env.get("AWS_ACCESS_KEY_ID") or "").strip(),
        "secret_key": str(env.get("DEV_S3_AWS_SECRET_ACCESS_KEY") or env.get("AWS_SECRET_ACCESS_KEY") or "").strip(),
    }


def save_settings(settings: dict[str, object]) -> dict[str, object]:
    normalized = normalize_settings(settings)
    config = _load_config()
    config["paydirt"] = {
        "bucket": normalized["bucket"],
        "prefix": normalized["prefix"],
        "region": normalized["region"],
        "workflow_mode": normalized["workflow_mode"],
        "monitor_targets": normalized["monitor_targets"],
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return normalized


def normalize_settings(settings: dict[str, object] | None) -> dict[str, object]:
    current = load_settings()
    data = settings or {}
    return {
        "bucket": str(data.get("bucket") or current["bucket"] or DEFAULT_BUCKET).strip(),
        "prefix": str(data.get("prefix") or current["prefix"] or DEFAULT_PREFIX).strip(),
        "region": str(data.get("region") or current["region"] or DEFAULT_REGION).strip(),
        "workflow_mode": _normalize_mode(data.get("workflow_mode") or current["workflow_mode"]),
        "monitor_targets": normalize_monitor_targets(data.get("monitor_targets"), use_default_if_empty=True),
        "access_key": str(data.get("access_key") or current.get("access_key") or "").strip(),
        "secret_key": str(data.get("secret_key") or current.get("secret_key") or "").strip(),
    }


def default_monitor_targets() -> list[dict[str, object]]:
    return deepcopy(DEFAULT_MONITOR_TARGETS)


def normalize_monitor_targets(targets, *, use_default_if_empty: bool = False) -> list[dict[str, object]]:
    if targets is None:
        return default_monitor_targets() if use_default_if_empty else []
    normalized: list[dict[str, object]] = []
    for idx, target in enumerate(targets):
        if not isinstance(target, dict):
            continue
        name = str(target.get("name") or f"Scope {idx + 1}").strip()
        if not name:
            continue
        normalized.append(
            {
                "enabled": bool(target.get("enabled", True)),
                "name": name,
                "env": _normalize_env_name(target.get("env") or "all"),
                "cluster_patterns": _normalize_patterns(target.get("cluster_patterns") or target.get("clusters") or []),
                "namespace_patterns": _normalize_patterns(target.get("namespace_patterns") or target.get("namespaces") or []),
            }
        )
    if normalized:
        return normalized
    return default_monitor_targets() if use_default_if_empty else []


def make_s3_client(
    *,
    access_key: str | None = None,
    secret_key: str | None = None,
    region: str | None = None,
):
    settings = load_settings()
    aws_access_key_id = str(access_key or settings["access_key"]).strip()
    aws_secret_access_key = str(secret_key or settings["secret_key"]).strip()
    aws_region = str(region or settings["region"]).strip() or DEFAULT_REGION
    if not aws_access_key_id or not aws_secret_access_key:
        raise PaydirtError("Missing DEV S3 AWS credentials in ~/.auger/.env")
    return boto3.Session(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        region_name=aws_region,
    ).client("s3")


def list_s3_archives(
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    client=None,
) -> list[ReportArchive]:
    settings = load_settings()
    bucket_name = str(bucket or settings["bucket"]).strip()
    prefix_value = str(prefix or settings["prefix"]).strip()
    s3 = client or make_s3_client(region=str(settings["region"]))
    archives: list[ReportArchive] = []
    paginator = s3.get_paginator("list_objects_v2")
    try:
        pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix_value)
        for page in pages:
            for item in page.get("Contents", []):
                key = str(item.get("Key") or "")
                if not key.lower().endswith(".zip"):
                    continue
                archive = _archive_from_s3_object(bucket_name, key, item)
                if archive:
                    archives.append(archive)
    except Exception as exc:
        raise PaydirtError(f"Failed to list S3 reports from s3://{bucket_name}/{prefix_value}: {exc}") from exc
    return sorted(archives, key=_archive_sort_key)


def list_local_archives(root: str | Path) -> list[ReportArchive]:
    base = Path(root).expanduser()
    if not base.exists():
        raise PaydirtError(f"Local Prisma report folder not found: {base}")
    archives: list[ReportArchive] = []
    for path in sorted(base.glob(LOCAL_GLOB)):
        archive = _archive_from_local_path(path)
        if archive:
            archives.append(archive)
    return sorted(archives, key=_archive_sort_key)


def latest_archives_by_env(archives: Iterable[ReportArchive]) -> dict[str, ReportArchive]:
    latest: dict[str, ReportArchive] = {}
    for archive in archives:
        existing = latest.get(archive.env)
        if existing is None or _archive_sort_key(archive) > _archive_sort_key(existing):
            latest[archive.env] = archive
    return latest


def previous_archive(archives: Iterable[ReportArchive], current: ReportArchive) -> ReportArchive | None:
    matches = [item for item in archives if item.env == current.env and item.report_date < current.report_date]
    if not matches:
        return None
    return sorted(matches, key=_archive_sort_key)[-1]


def build_latest_summary(archives: Iterable[ReportArchive], *, client=None) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for env, archive in sorted(latest_archives_by_env(archives).items(), key=lambda item: ENV_ORDER.get(item[0], 99)):
        snapshot = load_snapshot(archive, client=client)
        tracked_rows = filter_rows(snapshot.rows, load_settings()["monitor_targets"])
        tracked_summary = _prisma_cloud.summarize_findings(tracked_rows) if tracked_rows else _empty_summary()
        summaries.append(
            {
                "env": env,
                "report_date": archive.report_date,
                "locator": archive.locator,
                **snapshot.summary,
                "tracked_rows": len(tracked_rows),
                "tracked_unique_cves": tracked_summary.get("unique_cves", 0),
                "tracked_unique_images": tracked_summary.get("unique_images", 0),
            }
        )
    return summaries


def load_snapshot(archive: ReportArchive, *, report_kind: str = DEFAULT_KIND, client=None) -> Snapshot:
    cache_key = (archive.locator, report_kind)
    cached = _SNAPSHOT_CACHE.get(cache_key)
    if cached is not None:
        _SNAPSHOT_CACHE.move_to_end(cache_key)
        return cached

    blob = _read_archive_bytes(archive, client=client)
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            member = _select_member(zf, report_kind=report_kind)
            with zf.open(member, "r") as raw:
                text = raw.read().decode("utf-8-sig", errors="ignore")
    except Exception as exc:
        raise PaydirtError(f"Failed to read {archive.locator}: {exc}") from exc

    rows = _prisma_cloud.parse_images_csv(text)
    for row in rows:
        row["env"] = archive.env
        row["report_date"] = archive.report_date
        row["report_kind"] = report_kind
        row["finding_key"] = finding_key(row)
    rows.sort(key=_row_sort_key)
    snapshot = Snapshot(
        archive=archive,
        report_kind=report_kind,
        member_name=member.filename,
        rows=rows,
        summary=_prisma_cloud.summarize_findings(rows),
    )
    _SNAPSHOT_CACHE[cache_key] = snapshot
    while len(_SNAPSHOT_CACHE) > 12:
        _SNAPSHOT_CACHE.popitem(last=False)
    return snapshot


def compare_snapshots(current: Snapshot, previous: Snapshot | None) -> dict[str, object]:
    current_by_key = {row["finding_key"]: row for row in current.rows}
    previous_by_key = {row["finding_key"]: row for row in (previous.rows if previous else [])}

    current_keys = set(current_by_key)
    previous_keys = set(previous_by_key)
    persistent_keys = current_keys & previous_keys
    new_keys = current_keys - previous_keys
    resolved_keys = previous_keys - current_keys

    new_rows = sorted((current_by_key[key] for key in new_keys), key=_row_sort_key)
    resolved_rows = sorted((previous_by_key[key] for key in resolved_keys), key=_row_sort_key)
    persistent_rows = sorted((current_by_key[key] for key in persistent_keys), key=_row_sort_key)

    return {
        "current_date": current.archive.report_date,
        "previous_date": previous.archive.report_date if previous else "",
        "new_rows": new_rows,
        "resolved_rows": resolved_rows,
        "persistent_rows": persistent_rows,
        "summary": {
            "new_findings": len(new_rows),
            "resolved_findings": len(resolved_rows),
            "persistent_findings": len(persistent_rows),
            "new_cves": len({row.get("cve", "") for row in new_rows if row.get("cve")}),
            "resolved_cves": len({row.get("cve", "") for row in resolved_rows if row.get("cve")}),
            "persistent_cves": len({row.get("cve", "") for row in persistent_rows if row.get("cve")}),
        },
    }


def filter_rows(rows: Iterable[dict[str, str]], targets: list[dict[str, object]] | None) -> list[dict[str, str]]:
    target_list = normalize_monitor_targets(targets)
    if not target_list:
        return []
    return [row for row in rows if row_matches_targets(row, target_list)]


def row_matches_targets(row: dict[str, str], targets: list[dict[str, object]] | None) -> bool:
    return any(row_matches_target(row, target) for target in normalize_monitor_targets(targets))


def row_matches_target(row: dict[str, str], target: dict[str, object]) -> bool:
    if not target.get("enabled", True):
        return False
    target_env = _normalize_env_name(target.get("env") or "all")
    row_env = _normalize_env_name(row.get("env") or "")
    if target_env != "all" and row_env != target_env:
        return False
    cluster_patterns = _normalize_patterns(target.get("cluster_patterns") or [])
    namespace_patterns = _normalize_patterns(target.get("namespace_patterns") or [])
    cluster_values = split_multi_value(row.get("cluster"))
    namespace_values = split_multi_value(row.get("namespace"))
    if cluster_patterns and not _values_match_patterns(cluster_values, cluster_patterns):
        return False
    if namespace_patterns and not _values_match_patterns(namespace_values, namespace_patterns):
        return False
    return bool(cluster_patterns or namespace_patterns)


def matched_scope_namespaces(row: dict[str, str], targets: list[dict[str, object]] | None) -> list[str]:
    matches: set[str] = set()
    namespaces = split_multi_value(row.get("namespace"))
    for target in normalize_monitor_targets(targets):
        if not row_matches_target(row, target):
            continue
        patterns = _normalize_patterns(target.get("namespace_patterns") or [])
        if not patterns:
            matches.add(str(target.get("name") or "tracked").strip())
            continue
        for namespace in namespaces or [str(target.get("name") or "tracked").strip()]:
            if _pattern_matches(namespace, patterns):
                matches.add(namespace)
    return sorted(matches)


def split_multi_value(value: str | None) -> list[str]:
    parts = []
    for chunk in str(value or "").split(","):
        cleaned = chunk.strip()
        if cleaned:
            parts.append(cleaned)
    return parts


def build_story_drafts(
    tracked_rows: Iterable[dict[str, str]],
    comparison: dict[str, object] | None = None,
    *,
    targets: list[dict[str, object]] | None = None,
    report_date: str = "",
    max_images: int = 8,
) -> list[dict[str, object]]:
    current_rows = _dedupe_rows(tracked_rows)
    new_rows = _dedupe_rows(filter_rows((comparison or {}).get("new_rows", []), targets))
    persistent_rows = _dedupe_rows(filter_rows((comparison or {}).get("persistent_rows", []), targets))
    resolved_rows = _dedupe_rows(filter_rows((comparison or {}).get("resolved_rows", []), targets))

    groups: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(lambda: {"current": [], "new": [], "persistent": [], "resolved": []})
    for group_name, rows in (
        ("current", current_rows),
        ("new", new_rows),
        ("persistent", persistent_rows),
        ("resolved", resolved_rows),
    ):
        for row in rows:
            cve = str(row.get("cve") or "").strip().upper() or "UNKNOWN-CVE"
            groups[cve][group_name].append(row)

    drafts: list[dict[str, object]] = []
    for cve, payload in groups.items():
        current_group = _dedupe_rows(payload["current"])
        new_group = _dedupe_rows(payload["new"])
        persistent_group = _dedupe_rows(payload["persistent"])
        resolved_group = _dedupe_rows(payload["resolved"])
        if not current_group and not new_group and not persistent_group:
            continue
        short_description = _short_description(current_group or new_group or persistent_group)
        summary = _prisma_cloud.summarize_findings(current_group) if current_group else _empty_summary()
        subtasks = _build_image_subtasks_for_cve(cve, current_group, max_images=max_images)
        highest = _highest_severity(current_group or new_group or persistent_group)
        envs = sorted({str(row.get("env") or "").strip().lower() for row in current_group if row.get("env")})
        namespaces = sorted({namespace for row in current_group for namespace in matched_scope_namespaces(row, targets) or split_multi_value(row.get("namespace"))})
        drafts.append(
            {
                "story_id": cve,
                "cve": cve,
                "report_date": report_date or (current_group[0].get("report_date") if current_group else ""),
                "short_description": short_description,
                "title": _draft_title(cve, short_description),
                "severity": highest.title() if highest else "Unknown",
                "current_findings": len(current_group),
                "new_findings": len(new_group),
                "persistent_findings": len(persistent_group),
                "resolved_findings": len(resolved_group),
                "unique_cves": summary.get("unique_cves", 0),
                "unique_images": summary.get("unique_images", 0),
                "critical": summary.get("critical", 0),
                "high": summary.get("high", 0),
                "medium": summary.get("medium", 0),
                "low": summary.get("low", 0),
                "envs": envs,
                "env_labels": [_env_display_name(env) for env in envs],
                "namespaces": namespaces,
                "clusters": sorted({row.get("cluster", "") for row in current_group if row.get("cluster")}),
                "top_images": _top_values(current_group, "image", limit=6),
                "subtasks": subtasks,
                "description": _story_description(cve, short_description, report_date, current_group, new_group, persistent_group, resolved_group),
            }
        )
    drafts.sort(key=lambda item: (SEVERITY_ORDER.get(str(item.get("severity", "")).lower(), 99), str(item.get("cve", "")).upper()))
    return drafts


def build_workflow_run(
    archives: Iterable[ReportArchive],
    settings: dict[str, object] | None = None,
    *,
    client=None,
) -> dict[str, object]:
    normalized = normalize_settings(settings)
    archive_list = sorted(list(archives), key=_archive_sort_key)
    latest = latest_archives_by_env(archive_list)
    target_envs = workflow_envs(normalized["monitor_targets"], available_envs=list(latest))
    reference_date = max((archive.report_date for env, archive in latest.items() if env in target_envs), default="")
    env_runs: list[dict[str, object]] = []
    issues: list[str] = []
    tracked_current_all: list[dict[str, str]] = []
    tracked_new_all: list[dict[str, str]] = []
    tracked_persistent_all: list[dict[str, str]] = []
    tracked_resolved_all: list[dict[str, str]] = []

    for env in target_envs:
        archive = latest.get(env)
        if archive is None:
            issues.append(f"No report archive found for {env_label(env)} under the current S3 prefix.")
            continue
        current = load_snapshot(archive, client=client)
        previous = previous_archive(archive_list, archive)
        previous_snapshot = load_snapshot(previous, client=client) if previous else None
        comparison = compare_snapshots(current, previous_snapshot)
        tracked_current = _dedupe_rows(filter_rows(current.rows, normalized["monitor_targets"]))
        tracked_new = _dedupe_rows(filter_rows(comparison["new_rows"], normalized["monitor_targets"]))
        tracked_persistent = _dedupe_rows(filter_rows(comparison["persistent_rows"], normalized["monitor_targets"]))
        tracked_resolved = _dedupe_rows(filter_rows(comparison["resolved_rows"], normalized["monitor_targets"]))
        tracked_summary = _prisma_cloud.summarize_findings(tracked_current) if tracked_current else _empty_summary()
        env_runs.append(
            {
                "env": env,
                "report_date": archive.report_date,
                "locator": archive.locator,
                "member_name": current.member_name,
                "previous_date": previous_snapshot.archive.report_date if previous_snapshot else "",
                "latest_for_scope": archive.report_date == reference_date,
                "summary": current.summary,
                "tracked_summary": tracked_summary,
                "tracked_findings": len(tracked_current),
                "tracked_new_findings": len(tracked_new),
                "tracked_persistent_findings": len(tracked_persistent),
                "tracked_resolved_findings": len(tracked_resolved),
                "tracked_namespaces": sorted({ns for row in tracked_current for ns in matched_scope_namespaces(row, normalized["monitor_targets"])}),
            }
        )
        tracked_current_all.extend(tracked_current)
        tracked_new_all.extend(tracked_new)
        tracked_persistent_all.extend(tracked_persistent)
        tracked_resolved_all.extend(tracked_resolved)

    tracked_current_all = _dedupe_rows(tracked_current_all)
    tracked_new_all = _dedupe_rows(tracked_new_all)
    tracked_persistent_all = _dedupe_rows(tracked_persistent_all)
    tracked_resolved_all = _dedupe_rows(tracked_resolved_all)
    story_drafts = build_story_drafts(
        tracked_current_all,
        {
            "new_rows": tracked_new_all,
            "persistent_rows": tracked_persistent_all,
            "resolved_rows": tracked_resolved_all,
        },
        targets=normalized["monitor_targets"],
        report_date=reference_date,
    )
    tracked_summary = _prisma_cloud.summarize_findings(tracked_current_all) if tracked_current_all else _empty_summary()
    return {
        "settings": normalized,
        "reference_date": reference_date,
        "env_runs": env_runs,
        "story_drafts": story_drafts,
        "tracked_current_rows": tracked_current_all,
        "tracked_new_rows": tracked_new_all,
        "tracked_persistent_rows": tracked_persistent_all,
        "tracked_resolved_rows": tracked_resolved_all,
        "summary": {
            **tracked_summary,
            "story_count": len(story_drafts),
            "target_count": len([target for target in normalized["monitor_targets"] if target.get("enabled")]),
            "processed_envs": len(env_runs),
        },
        "issues": issues,
    }


def workflow_envs(targets: list[dict[str, object]] | None, *, available_envs: Iterable[str]) -> list[str]:
    available = {str(env).strip().lower() for env in available_envs if str(env).strip()}
    chosen = set()
    for target in normalize_monitor_targets(targets):
        env = str(target.get("env") or "").strip().lower()
        if env == "all":
            chosen.update(available)
        elif env:
            chosen.add(env)
    if chosen:
        return sorted(chosen, key=lambda item: ENV_ORDER.get(item, 99))
    return sorted(available, key=lambda item: ENV_ORDER.get(item, 99))


def finding_key(row: dict[str, str]) -> str:
    parts = (
        (row.get("env") or "").lower(),
        (row.get("cluster") or "").lower(),
        (row.get("namespace") or "").lower(),
        (row.get("image") or "").lower(),
        (row.get("cve") or "").upper(),
        (row.get("package") or "").lower(),
        (row.get("version") or "").lower(),
        (row.get("location") or "").lower(),
    )
    return "|".join(parts)


def env_label(env: str) -> str:
    return ENV_LABELS.get(env, str(env).upper())


def archive_size_mb(archive: ReportArchive) -> str:
    return f"{archive.size / (1024 * 1024):.1f}" if archive.size else ""


def _read_archive_bytes(archive: ReportArchive, *, client=None) -> bytes:
    if archive.source == "local":
        return Path(archive.path).read_bytes()
    s3 = client or make_s3_client()
    return s3.get_object(Bucket=archive.bucket, Key=archive.key)["Body"].read()


def _select_member(zf: zipfile.ZipFile, *, report_kind: str) -> zipfile.ZipInfo:
    csv_members = [info for info in zf.infolist() if not info.is_dir() and info.filename.lower().endswith(".csv")]
    if not csv_members:
        raise PaydirtError("ZIP archive does not contain any CSV members")
    wanted = (report_kind or DEFAULT_KIND).strip().lower()
    if wanted == "fixable":
        for info in csv_members:
            if "fixable" in info.filename.lower():
                return info
    if wanted == "all":
        for info in csv_members:
            if "fixable" not in info.filename.lower():
                return info
    return sorted(csv_members, key=lambda item: item.filename)[0]


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _normalize_mode(value: object) -> str:
    mode = str(value or DEFAULT_MODE).strip().lower()
    return "auto" if mode == "auto" else "manual"


def _normalize_env_name(value: object) -> str:
    return ENV_ALIASES.get(str(value or "").strip().lower(), str(value or "").strip().lower())


def _normalize_patterns(value) -> list[str]:
    if isinstance(value, str):
        values = value.split(",")
    elif isinstance(value, Iterable):
        values = value
    else:
        values = []
    patterns = []
    for item in values:
        pattern = str(item or "").strip()
        if pattern:
            patterns.append(pattern)
    return patterns


def _values_match_patterns(values: list[str], patterns: list[str]) -> bool:
    for value in values:
        if _pattern_matches(value, patterns):
            return True
    return False


def _pattern_matches(value: str, patterns: list[str]) -> bool:
    lowered = str(value or "").strip().lower()
    for pattern in patterns:
        if fnmatch.fnmatch(lowered, str(pattern).strip().lower()):
            return True
    return False


def _dedupe_rows(rows: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    deduped: OrderedDict[str, dict[str, str]] = OrderedDict()
    for row in rows:
        key = str(row.get("finding_key") or finding_key(row))
        deduped[key] = row
    return sorted(deduped.values(), key=_row_sort_key)


def _build_image_subtasks_for_cve(cve: str, rows: list[dict[str, str]], *, max_images: int) -> list[dict[str, object]]:
    image_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        image_groups[str(row.get("image") or "unknown-image")].append(row)
    subtasks = []
    for image, image_rows in sorted(
        image_groups.items(),
        key=lambda item: (_severity_rank(item[1]), -len(item[1]), item[0].lower()),
    )[:max_images]:
        summary = _prisma_cloud.summarize_findings(image_rows)
        envs = sorted({str(row.get("env") or "").strip().lower() for row in image_rows if row.get("env")})
        namespaces = sorted({namespace for row in image_rows for namespace in split_multi_value(row.get("namespace"))})
        subtasks.append(
            {
                "summary": f"{image}",
                "title": f"{cve} in {image}",
                "image": image,
                "findings": len(image_rows),
                "unique_cves": summary.get("unique_cves", 0),
                "critical": summary.get("critical", 0),
                "high": summary.get("high", 0),
                "environments": envs,
                "environment_labels": [_env_display_name(env) for env in envs],
                "namespaces": namespaces,
                "clusters": sorted({row.get("cluster", "") for row in image_rows if row.get("cluster")}),
                "namespace_preview": namespaces[:6],
            }
        )
    return subtasks


def _story_description(
    cve: str,
    short_description: str,
    report_date: str,
    current_rows: list[dict[str, str]],
    new_rows: list[dict[str, str]],
    persistent_rows: list[dict[str, str]],
    resolved_rows: list[dict[str, str]],
) -> str:
    summary = _prisma_cloud.summarize_findings(current_rows) if current_rows else _empty_summary()
    envs = sorted({str(row.get("env") or "").strip().lower() for row in current_rows if row.get("env")})
    namespaces = sorted({namespace for row in current_rows for namespace in split_multi_value(row.get("namespace"))})
    lines = [
        f"Paydirt draft for {cve}",
        f"Short description: {short_description or 'n/a'}",
        f"Report date: {report_date or 'unknown'}",
        f"Environments: {', '.join(_env_display_name(env) for env in envs) or 'none'}",
        f"Namespaces: {', '.join(namespaces[:12]) or 'none'}",
        "",
        f"Current tracked findings: {len(current_rows)}",
        f"New findings since prior report: {len(new_rows)}",
        f"Persistent findings since prior report: {len(persistent_rows)}",
        f"Resolved findings since prior report: {len(resolved_rows)}",
        "",
        "Current severity mix:",
        "  critical={critical} high={high} medium={medium} low={low} unknown={unknown}".format(
            critical=summary.get("critical", 0),
            high=summary.get("high", 0),
            medium=summary.get("medium", 0),
            low=summary.get("low", 0),
            unknown=summary.get("unknown", 0),
        ),
        "",
        "Affected images: " + ", ".join(_top_values(current_rows, "image", limit=8)),
    ]
    return "\n".join(lines).strip()


def _top_values(rows: Iterable[dict[str, str]], key: str, *, limit: int) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        value = str(row.get(key) or "").strip()
        if value:
            counts[value] += 1
    return [value for value, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:limit]]


def _highest_severity(rows: Iterable[dict[str, str]]) -> str:
    severities = [str(row.get("severity") or "").strip().lower() for row in rows]
    severities = [severity for severity in severities if severity]
    if not severities:
        return ""
    return sorted(severities, key=lambda item: SEVERITY_ORDER.get(item, 99))[0]


def _severity_rank(rows: Iterable[dict[str, str]]) -> int:
    highest = _highest_severity(rows)
    return SEVERITY_ORDER.get(highest, 99)


def _empty_summary() -> dict[str, int]:
    return {
        "rows": 0,
        "unique_cves": 0,
        "unique_images": 0,
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "unknown": 0,
    }


def _env_display_name(env: str) -> str:
    env_key = str(env or "").strip().lower()
    return env_label(env_key) if env_key else ""


def _draft_title(cve: str, short_description: str) -> str:
    description = short_description.strip()
    return f"{cve} - {description}" if description else cve


def _short_description(rows: Iterable[dict[str, str]]) -> str:
    for row in rows:
        for key in ("description", "Summary", "summary"):
            value = str(row.get(key) or "").strip()
            if value:
                value = re.sub(r"\s+", " ", value)
                if len(value) > 120:
                    value = value[:117].rstrip() + "..."
                return value
    return ""


def _archive_from_s3_object(bucket: str, key: str, item: dict) -> ReportArchive | None:
    name = Path(key).name
    env = _parse_env(key) or _parse_env(name)
    report_date = _parse_date(key) or _parse_date(name)
    if not env or not report_date:
        return None
    last_modified = item.get("LastModified")
    if isinstance(last_modified, datetime):
        last_modified_value = last_modified.isoformat(timespec="seconds")
    else:
        last_modified_value = str(last_modified or "")
    return ReportArchive(
        source="s3",
        env=env,
        report_date=report_date,
        label=f"{env_label(env)} {report_date}",
        bucket=bucket,
        key=key,
        size=int(item.get("Size") or 0),
        last_modified=last_modified_value,
    )


def _archive_from_local_path(path: Path) -> ReportArchive | None:
    env = _parse_env(path.name)
    report_date = _parse_date(path.name)
    if not env or not report_date:
        return None
    stat = path.stat()
    return ReportArchive(
        source="local",
        env=env,
        report_date=report_date,
        label=f"{env_label(env)} {report_date}",
        path=str(path),
        size=int(stat.st_size),
        last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    )


def _parse_env(value: str) -> str:
    tokens = []
    upper = str(value or "").upper()
    for chunk in upper.replace("/", "_").replace("-", "_").split("_"):
        clean = chunk.strip().lower()
        if clean:
            tokens.append(clean)
    for token in reversed(tokens):
        env = ENV_ALIASES.get(token)
        if env in {"dev", "staging", "prod"}:
            return env
    return ""


def _parse_date(value: str) -> str:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", str(value or ""))
    return match.group(1) if match else ""


def _archive_sort_key(archive: ReportArchive) -> tuple[str, int, str]:
    return (archive.report_date, ENV_ORDER.get(archive.env, 99), archive.locator)


def _row_sort_key(row: dict[str, str]) -> tuple[int, str, str, str, str]:
    severity = (row.get("severity") or "").strip().lower()
    return (
        SEVERITY_ORDER.get(severity, 99),
        (row.get("cve") or "").upper(),
        (row.get("image") or "").lower(),
        (row.get("namespace") or "").lower(),
        (row.get("package") or "").lower(),
    )
