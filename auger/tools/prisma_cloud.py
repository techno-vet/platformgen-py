"""Prisma Cloud helpers for Gov and Runtime Security workflows."""

from __future__ import annotations

import csv
import io
import os
import base64
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

try:
    from auger.ui.utils import auger_home as _auger_home
except ImportError:
    def _auger_home():  # type: ignore[no-redef]
        return Path.home()


class PrismaCloudError(RuntimeError):
    """Base Prisma Cloud error."""


class PrismaCloudAuthError(PrismaCloudError):
    """Authentication failed."""


def _load_env() -> dict[str, str]:
    env_file = _auger_home() / ".auger" / ".env"
    load_dotenv(env_file, override=True)
    return {
        "url": os.getenv("PRISMA_CLOUD_URL", "").strip(),
        "access_key": os.getenv("PRISMA_CLOUD_ACCESS_KEY", "").strip(),
        "secret_key": os.getenv("PRISMA_CLOUD_SECRET_KEY", "").strip(),
    }


def _parse_url(value: str):
    candidate = (value or "").strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if not parsed.netloc:
        return None
    return parsed


def _dedupe(items):
    seen: set[str] = set()
    result = []
    for item in items:
        url = item[1]
        if url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def prisma_auth_candidates(value: str) -> list[tuple[str, str, str]]:
    """Return likely auth endpoints for a Prisma console/API URL."""
    parsed = _parse_url(value)
    if not parsed:
        return []

    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    results: list[tuple[str, str, str]] = []

    if host.startswith("app"):
        api_host = host.replace("app", "api", 1)
        results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/login", "x-redlock-auth"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v1/authenticate", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/authenticate", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/api/v1/authenticate", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/api/v34.03/authenticate", "bearer"))
    elif host.startswith("api"):
        results.append(("Prisma Cloud Gov", f"{scheme}://{host}/login", "x-redlock-auth"))
        app_host = host.replace("api", "app", 1)
        results.append(("Prisma Cloud Compute", f"{scheme}://{app_host}/compute/api/v1/authenticate", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{app_host}/compute/api/v34.03/authenticate", "bearer"))

    if path.startswith("/compute"):
        results.insert(0, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v1/authenticate", "bearer"))
        results.insert(1, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/authenticate", "bearer"))

    return _dedupe(results)


def prisma_download_candidates(value: str) -> list[tuple[str, str]]:
    """Return likely image-report CSV endpoints."""
    parsed = _parse_url(value)
    if not parsed:
        return []

    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    results: list[tuple[str, str]] = []

    if host.startswith("api"):
        results.append(("Prisma Cloud Gov", f"{scheme}://{host}/api/v34.03/images/download"))
        app_host = host.replace("api", "app", 1)
        results.append(("Prisma Cloud Compute", f"{scheme}://{app_host}/compute/api/v34.03/images/download"))
    elif host.startswith("app"):
        api_host = host.replace("app", "api", 1)
        results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/api/v34.03/images/download"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/images/download"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/api/v34.03/images/download"))

    if path.startswith("/compute"):
        results.insert(0, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/images/download"))

    return _dedupe(results)


def prisma_stats_candidates(value: str) -> list[tuple[str, str]]:
    """Return likely vulnerability summary endpoints."""
    parsed = _parse_url(value)
    if not parsed:
        return []

    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    results: list[tuple[str, str]] = []

    if host.startswith("app"):
        api_host = host.replace("app", "api", 1)
        results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/api/v34.03/stats/vulnerabilities"))
    elif host.startswith("api"):
        results.append(("Prisma Cloud Gov", f"{scheme}://{host}/api/v34.03/stats/vulnerabilities"))

    return _dedupe(results)


def prisma_vulnerability_download_candidates(value: str) -> list[tuple[str, str, str]]:
    """Return likely CVE/report CSV endpoints for Gov and Compute."""
    parsed = _parse_url(value)
    if not parsed:
        return []

    scheme = parsed.scheme or "https"
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    results: list[tuple[str, str, str]] = []

    if host.startswith("app"):
        api_host = host.replace("app", "api", 1)
        results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/api/v34.03/stats/vulnerabilities/download", "x-redlock-auth"))
        results.append(("Prisma Cloud Gov", f"{scheme}://{api_host}/api/v34.03/stats/vulnerabilities", "x-redlock-auth"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v1/images/download", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/images/download", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/api/v1/images/download", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{host}/api/v34.03/images/download", "bearer"))
    elif host.startswith("api"):
        app_host = host.replace("api", "app", 1)
        results.append(("Prisma Cloud Gov", f"{scheme}://{host}/api/v34.03/stats/vulnerabilities/download", "x-redlock-auth"))
        results.append(("Prisma Cloud Gov", f"{scheme}://{host}/api/v34.03/stats/vulnerabilities", "x-redlock-auth"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{app_host}/compute/api/v1/images/download", "bearer"))
        results.append(("Prisma Cloud Compute", f"{scheme}://{app_host}/compute/api/v34.03/images/download", "bearer"))

    if path.startswith("/compute"):
        results.insert(0, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v1/images/download", "bearer"))
        results.insert(1, ("Prisma Cloud Compute", f"{scheme}://{host}/compute/api/v34.03/images/download", "bearer"))

    return _dedupe(results)


def _token_from_response(response: requests.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        for key in ("token", "jwt", "accessToken"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    text = response.text.strip()
    if text:
        return text
    return ""


def _stringify(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        parts = [_stringify(v) for v in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        try:
            import json
            return json.dumps(value, sort_keys=True)
        except Exception:
            return str(value).strip()
    return str(value).strip()


def _canon(row: dict[str, str]) -> dict[str, str]:
    canon: dict[str, str] = {}
    for key, value in row.items():
        clean_key = _stringify(key)
        canon[clean_key] = _stringify(value)
    return canon


def _pick(row: dict[str, str], *aliases: str) -> str:
    lowered = {k.lower(): _stringify(v) for k, v in row.items()}
    for alias in aliases:
        alias_lower = alias.lower()
        if alias_lower in lowered and lowered[alias_lower]:
            return lowered[alias_lower]
    return ""


def _extract_fixed_version(row: dict[str, str]) -> str:
    fixed_version = _pick(
        row,
        "fixed version",
        "fix version",
        "recommended fix version",
        "available fix version",
    )
    if fixed_version:
        return fixed_version
    fixable = _pick(row, "fixable")
    if fixable.lower().startswith("fixed in "):
        return fixable
    return ""


def _split_image_name(image_name: str) -> tuple[str, str]:
    image_name = _stringify(image_name)
    if not image_name:
        return "", ""
    if "/" in image_name:
        registry, remainder = image_name.split("/", 1)
        return registry, remainder
    return "", image_name


def normalize_csv_row(raw: dict[str, object]) -> dict[str, str]:
    """Normalize one Prisma CSV row across live/API and emailed-report formats."""
    row = _canon({str(key): _stringify(value) for key, value in raw.items()})
    cve = _pick(row, "cve", "cve id", "vulnerability", "vulnerability id", "id")
    severity = _pick(row, "severity", "cvss severity")
    package = _pick(row, "package", "package name", "packageName", "resource", "name")
    version = _pick(row, "version", "package version", "installed version", "current version")
    fixed_version = _extract_fixed_version(row)

    direct_image = _pick(row, "image", "image name", "image_name")
    registry = _pick(row, "repotag.registry", "registry", "image registry")
    image_repo = _pick(row, "repotag.repo", "repository", "repo")
    image_tag = _pick(row, "repotag.tag", "tag", "image tag")
    if direct_image:
        derived_registry, derived_image = _split_image_name(direct_image)
        registry = registry or derived_registry
        image = direct_image
        image_repo = image_repo or derived_image.rsplit(":", 1)[0]
        if ":" in direct_image and not image_tag:
            image_tag = direct_image.rsplit(":", 1)[1]
    else:
        image = ":".join(part for part in (image_repo, image_tag) if part)

    cluster = _pick(row, "clusters", "cluster", "cluster name")
    host = _pick(row, "hosts", "host", "host name")
    namespace = _pick(row, "namespace", "kubernetes namespace")
    description = _pick(row, "description", "message", "summary")
    cvss = _pick(row, "cvss", "cvss score", "score")
    fixable = _pick(row, "fixable")
    fix_date = _pick(row, "fix date")
    source = _pick(row, "source")
    location = _pick(row, "location")
    risk_factors = _pick(row, "risk factors")
    published_on = _pick(row, "published on")
    scanned_on = _pick(row, "scanned on")
    first_discovered_on_image = _pick(
        row,
        "first time cve discovered on image",
        "first discovered on image",
    )
    first_discovered_on_system = _pick(
        row,
        "first time cve discovered on system",
        "first discovered on system",
    )
    vulnerability_type = _pick(row, "vulnerability type", "type")
    link = _pick(row, "link", "url")

    normalized = {
        "cve": cve,
        "severity": severity,
        "package": package,
        "version": version,
        "fixed_version": fixed_version,
        "fixable": fixable,
        "fix_date": fix_date,
        "registry": registry,
        "image": image,
        "image_repo": image_repo,
        "image_tag": image_tag,
        "cluster": cluster,
        "host": host,
        "namespace": namespace,
        "source": source,
        "location": location,
        "description": description,
        "cvss": cvss,
        "risk_factors": risk_factors,
        "published_on": published_on,
        "scanned_on": scanned_on,
        "first_discovered_on_image": first_discovered_on_image,
        "first_discovered_on_system": first_discovered_on_system,
        "vulnerability_type": vulnerability_type,
        "link": link,
    }

    for key, value in row.items():
        if key not in normalized:
            normalized[key] = value
    return normalized


def parse_images_csv(csv_text: str) -> list[dict[str, str]]:
    """Normalize Prisma image-download CSV rows."""
    if not csv_text.strip():
        return []

    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[dict[str, str]] = []
    for raw in reader:
        if not raw:
            continue
        rows.append(normalize_csv_row(raw))
    return rows


def summarize_findings(rows: list[dict[str, str]]) -> dict[str, int]:
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
    unique_cves: set[str] = set()
    unique_images: set[str] = set()
    for row in rows:
        sev = _stringify(row.get("severity")).lower()
        if sev in severity_counts:
            severity_counts[sev] += 1
        else:
            severity_counts["unknown"] += 1
        cve = _stringify(row.get("cve"))
        if cve:
            unique_cves.add(cve)
        image = _stringify(row.get("image"))
        if image:
            unique_images.add(image)
    return {
        "rows": len(rows),
        "unique_cves": len(unique_cves),
        "unique_images": len(unique_images),
        **severity_counts,
    }


class PrismaCloudClient:
    """Minimal Prisma Cloud client for auth + CSV/report retrieval."""

    def __init__(
        self,
        base_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        timeout: int = 30,
    ):
        env = _load_env()
        self.base_url = (base_url or env["url"]).strip()
        self.access_key = (access_key or env["access_key"]).strip()
        self.secret_key = (secret_key or env["secret_key"]).strip()
        self.timeout = timeout
        self.session = requests.Session()
        self.token = ""
        self.auth_endpoint = ""
        self.auth_mode = ""
        self.auth_header_kind = ""
        self._mode_tokens: dict[str, tuple[str, str, str]] = {}

    def _header_for_token(self, token: str, header_kind: str) -> dict[str, str]:
        if header_kind == "bearer":
            return {"Authorization": f"Bearer {token}"}
        return {"x-redlock-auth": token}

    def _basic_auth_header(self) -> dict[str, str]:
        raw = f"{self.access_key}:{self.secret_key}".encode()
        return {"Authorization": f"Basic {base64.b64encode(raw).decode()}"}

    def authenticate(self, preferred_mode: str | None = None) -> dict[str, str]:
        if not self.base_url:
            raise PrismaCloudAuthError("Prisma Cloud URL is required")
        if not self.access_key or not self.secret_key:
            raise PrismaCloudAuthError("Prisma Cloud access key and secret key are required")

        if preferred_mode and preferred_mode in self._mode_tokens:
            token, endpoint, header_kind = self._mode_tokens[preferred_mode]
            self.token = token
            self.auth_endpoint = endpoint
            self.auth_mode = preferred_mode
            self.auth_header_kind = header_kind
            self.session.headers.update(self._header_for_token(token, header_kind))
            return {"endpoint": endpoint, "token": token, "mode": preferred_mode, "header_kind": header_kind}

        errors: list[str] = []
        for label, endpoint, header_kind in prisma_auth_candidates(self.base_url):
            if preferred_mode and label != preferred_mode:
                continue
            try:
                response = self.session.post(
                    endpoint,
                    json={"username": self.access_key, "password": self.secret_key},
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                errors.append(f"{label}: {exc}")
                continue

            if response.status_code == 200:
                token = _token_from_response(response)
                if not token:
                    errors.append(f"{label}: empty token response")
                    continue
                self.token = token
                self.auth_endpoint = endpoint
                self.auth_mode = label
                self.auth_header_kind = header_kind
                self._mode_tokens[label] = (token, endpoint, header_kind)
                self.session.headers.update(self._header_for_token(token, header_kind))
                return {"endpoint": endpoint, "token": token, "mode": label, "header_kind": header_kind}

            errors.append(f"{label}: HTTP {response.status_code}")

        raise PrismaCloudAuthError("; ".join(errors) or "Authentication failed")

    def fetch_vulnerability_stats(self) -> dict | None:
        if not self.token:
            self.authenticate()

        for label, endpoint in prisma_stats_candidates(self.base_url):
            try:
                auth = self.authenticate(preferred_mode=label)
                response = self.session.get(
                    endpoint,
                    headers=self._header_for_token(auth["token"], auth["header_kind"]),
                    timeout=self.timeout,
                )
            except requests.RequestException:
                continue
            if response.status_code == 200:
                try:
                    return response.json()
                except Exception:
                    return None
        return None

    def fetch_live_findings(self) -> dict[str, object]:
        """Fetch live Prisma data, preferring Gov vulnerability downloads for task 149/151."""
        errors: list[str] = []
        for label, endpoint, header_kind in prisma_vulnerability_download_candidates(self.base_url):
            try:
                auth = self.authenticate(preferred_mode=label)
                headers = {"Accept": "text/csv, application/json"}
                headers.update(self._header_for_token(auth["token"], header_kind))
                response = self.session.get(endpoint, headers=headers, timeout=max(self.timeout, 60))
            except requests.RequestException as exc:
                errors.append(f"{label}: {exc}")
                continue
            except PrismaCloudAuthError as exc:
                errors.append(f"{label}: {exc}")
                continue

            if response.status_code == 200:
                content_type = (response.headers.get("content-type") or "").lower()
                if "json" in content_type:
                    try:
                        payload = response.json()
                    except Exception:
                        payload = None
                    if isinstance(payload, (dict, list)):
                        summary = self._summary_from_stats(payload)
                        return {
                            "endpoint": endpoint,
                            "mode": label,
                            "rows": [],
                            "summary": summary,
                            "stats": payload,
                            "note": "Loaded live Prisma summary data; row-level CSV download was not available from this endpoint.",
                            "note_short": "Loaded live Prisma summary data only",
                        }
                text = response.text
                rows = parse_images_csv(text)
                if rows:
                    return {
                        "endpoint": endpoint,
                        "mode": label,
                        "csv": text,
                        "rows": rows,
                        "summary": summarize_findings(rows),
                    }
                errors.append(f"{label}: no parseable row data returned")
                continue

            if label == "Prisma Cloud Compute":
                try:
                    basic_headers = {"Accept": "text/csv, application/json"}
                    basic_headers.update(self._basic_auth_header())
                    response = self.session.get(endpoint, headers=basic_headers, timeout=max(self.timeout, 60))
                    if response.status_code == 200:
                        text = response.text
                        rows = parse_images_csv(text)
                        if rows:
                            return {
                                "endpoint": endpoint,
                                "mode": f"{label} (Basic Auth)",
                                "csv": text,
                                "rows": rows,
                                "summary": summarize_findings(rows),
                            }
                except requests.RequestException:
                    pass

            errors.append(f"{label}: HTTP {response.status_code}")

        stats = self.fetch_vulnerability_stats()
        if isinstance(stats, dict) and stats:
            return {
                "endpoint": self.auth_endpoint or "",
                "mode": self.auth_mode or "Prisma Cloud Gov",
                "rows": [],
                "summary": self._summary_from_stats(stats),
                "stats": stats,
                "note": "Loaded live Prisma summary data only. Detailed CSV-style row data was not available from the current endpoints.",
                "note_short": "Loaded live Prisma summary data only",
            }

        if not self.auth_endpoint:
            raise PrismaCloudError(
                "Unable to authenticate to Prisma Cloud live APIs. "
                f"Last errors: {'; '.join(errors[:6])}"
            )

        return {
            "endpoint": self.auth_endpoint,
            "mode": self.auth_mode or "Prisma Cloud Gov",
            "rows": [],
            "summary": {
                "rows": 0,
                "unique_cves": 0,
                "unique_images": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
                "unknown": 0,
            },
            "stats": None,
            "source_detail": "Auth only — no readable live export endpoint",
            "note": (
                "Authenticated to Prisma Cloud, but this tenant/user does not currently expose a "
                "live vulnerability export endpoint that the widget can read. "
                "Use Load Prisma CSV for now, or request additional Prisma API permissions. "
                f"Last endpoint responses: {'; '.join(errors[:4])}"
            ),
            "note_short": "Authenticated, but no readable live export endpoint is available",
        }

    def _summary_from_stats(self, payload) -> dict[str, int]:
        summary = {"rows": 0, "unique_cves": 0, "unique_images": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "unknown": 0}
        if isinstance(payload, list):
            payload = {"items": payload}
        if not isinstance(payload, dict):
            return summary

        candidates = []
        for key in ("total", "count", "totalCount", "affected", "items"):
            if key in payload:
                candidates.append((key, payload[key]))

        for key, value in candidates:
            if isinstance(value, int) and key in ("total", "count", "totalCount"):
                summary["rows"] = max(summary["rows"], value)
            elif isinstance(value, list):
                summary["rows"] = max(summary["rows"], len(value))
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    sev = _stringify(item.get("severity")).lower()
                    if sev in ("critical", "high", "medium", "low"):
                        summary[sev] += 1
                    elif sev:
                        summary["unknown"] += 1
                    cve = _stringify(item.get("cve") or item.get("id"))
                    if cve:
                        summary["unique_cves"] += 1
                    image = _stringify(item.get("image") or item.get("resource"))
                    if image:
                        summary["unique_images"] += 1

        if isinstance(payload.get("severityDistribution"), dict):
            dist = payload["severityDistribution"]
            for key in ("critical", "high", "medium", "low"):
                if key in dist and isinstance(dist[key], int):
                    summary[key] = dist[key]

        return summary

    def fetch_images_csv(self) -> dict[str, object]:
        """Backward-compatible alias."""
        return self.fetch_live_findings()
