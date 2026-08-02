from __future__ import annotations

import re
from urllib.parse import urlparse

WHY_HEADER = "**Why:**"
DONE_HEADER = "**Done when:**"
LINKS_HEADER = "**Links:**"

SAME_LINE_HEADERS = (WHY_HEADER, DONE_HEADER)

RETIRED_MARKERS = ("SPEC.md", ".pulsar/memories")

_LINK_TARGET = re.compile(r"\]\(\s*<?([^)>]+?)>?\s*\)")
_MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)")
_TITLE_PREFIX = re.compile(
    r"^\s*(\[|\d+[.)]\s|PLE-\d+|(repo|type|bug|chore|feature|refactor|docs|improvement):)", re.IGNORECASE
)
_FORBIDDEN_SECTIONS = re.compile(
    r"^[\s#*]*(Checklist|Changes\s+needed|Implementation\s+steps|Task\s+list)[\s*:.*]*$",
    re.MULTILINE | re.IGNORECASE,
)
_BARE_PATH = re.compile(r"(?<![\w/])(?<!~\/\.)[\w][\w.-]*(?:/[\w.-]+)+\.(?:md|py|yml|yaml|json|xlsx|docx|pdf)\b")
# _BARE_PATH catches repo-relative paths in prose; _FILENAME_TLDS catches filenames masquerading as URL hostnames — different detection goals, different extension sets.
_FILENAME_TLDS = frozenset({
    "py",
    "md",
    "json",
    "yml",
    "yaml",
    "txt",
    "csv",
    "ts",
    "js",
    "rs",
    "go",
    "cs",
    "sh",
    "sql",
    "tsx",
    "jsx",
})


def validate_title(title: str) -> list[str]:
    if _TITLE_PREFIX.match(title):
        return [
            "title carries an ordinal or label prefix — sequence lives in blocks relations and labels carry repo/type"
        ]

    return []


def validate_body(body: str) -> list[str]:
    violations: list[str] = []

    for header in (WHY_HEADER, DONE_HEADER, LINKS_HEADER):
        if header not in body:
            violations.append(f"missing canonical section header {header!r}")

    for header in SAME_LINE_HEADERS:
        index = body.find(header)
        if index == -1:
            continue

        first_line = body[index + len(header) :].split("\n", 1)[0]
        if not first_line.strip():
            violations.append(f"{header!r} must be followed by its text on the same line, not the next line")

    for marker in RETIRED_MARKERS:
        if marker in body:
            violations.append(
                f"retired reference {marker!r} — link the co-located AGENTS.md by GitHub blob URL instead"
            )

    for match in _FORBIDDEN_SECTIONS.finditer(body):
        violations.append(
            f"forbidden section {match.group().strip()!r} — implementation plans belong in sub-issues or PRs, not ticket bodies"
        )

    violations.extend(_validate_link_targets(body))

    body_without_links = _MARKDOWN_LINK.sub("", body)
    for match in _BARE_PATH.finditer(body_without_links):
        violations.append(
            f"bare path {match.group()!r} in body — use a full github.com blob URL instead of a repo-relative path"
        )

    return violations


def _validate_link_targets(body: str) -> list[str]:
    violations: list[str] = []
    for match in _LINK_TARGET.finditer(body):
        target = match.group(1)
        if target is None:
            continue
        parsed = urlparse(target)
        hostname = parsed.hostname or ""
        if parsed.scheme not in ("http", "https"):
            violations.append(f"link target {target!r} is not an absolute URL — use a full github.com blob URL on dev")
        elif "." not in hostname:
            violations.append(f"link target {target!r} has no valid hostname — use a full github.com blob URL")
        elif hostname.split(".")[-1].lower() in _FILENAME_TLDS:
            violations.append(
                f"link target {target!r} looks like a bare filename auto-linked as a URL — use a full github.com blob URL"
            )
    return violations


def fix_bare_paths(body: str, repo_urls: dict[str, str], default_repo: str | None) -> tuple[str, list[str]]:
    body_without_links = _MARKDOWN_LINK.sub("", body)
    fixes: list[str] = []

    for bare_path in dict.fromkeys(m.group() for m in _BARE_PATH.finditer(body_without_links)):
        url = _resolve_repo_path(bare_path, repo_urls, default_repo)
        if url is not None:
            body = body.replace(bare_path, f"[{bare_path}]({url})")
            fixes.append(f"{bare_path} -> {url}")

    return body, fixes


def _resolve_repo_path(path: str, repo_urls: dict[str, str], default_repo: str | None) -> str | None:
    for repo_name, base_url in repo_urls.items():
        prefix = f"{repo_name}/"
        if path.startswith(prefix):
            return f"{base_url}/{path[len(prefix) :]}"
    if default_repo and default_repo in repo_urls:
        return f"{repo_urls[default_repo]}/{path}"
    return None


def validate_label_presence(label_names: list[str], required_group_labels: set[str], group_name: str) -> list[str]:
    if not any(name in required_group_labels for name in label_names):
        return [f"ticket carries no label in the {group_name!r} group"]
    return []


def orphan_design_docs(doc_names: list[str], ticket_bodies: list[str]) -> list[str]:
    corpus = "\n".join(ticket_bodies)
    return [name for name in doc_names if f"design/{name}" not in corpus]
