"""Check Markdown links that point inside the repository or to project-owned pages.

The default mode only checks relative links. Pass ``--external`` to also check
links to the project's GitHub organization, GitHub Pages site, and Workers
mirror. External checks intentionally skip ``blob/main`` and security advisory
URLs because they may legitimately be absent on ``main`` during a pull request.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "output", "logs", "weights",
    "raw_snapshots", "promo", "reports",
}
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_LINK = re.compile(r"""href=["']([^"']+)["']""")
OWN_GITHUB_ORG = "/hccccc01333/"
OWN_HOSTS = {
    "github.com",
    "hccccc01333.github.io",
    "kpldata-site.hccccc01333.workers.dev",
}
EXTERNAL_SKIP_FRAGMENTS = (
    "/security/advisories/new",
    "/security/policy",
    "/blob/main/",
)
USER_AGENT = "kpl-insight-link-check/1.0"


def markdown_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        files.append(path)
    return files


def links_in(text: str) -> set[str]:
    found = {html.unescape(match.group(1)) for match in MARKDOWN_LINK.finditer(text)}
    found.update(html.unescape(match.group(1)) for match in HTML_LINK.finditer(text))
    return found


def resolve_relative(markdown: Path, link: str) -> tuple[str | None, str | None]:
    """Return (target, error). A None target means the link is not a path."""
    split = urllib.parse.urlsplit(link)
    if split.scheme or split.netloc:
        return None, None
    path = urllib.parse.unquote(split.path).strip()
    if not path:
        return None, None
    if path.startswith("/"):
        target = ROOT / path.lstrip("/")
    else:
        target = (markdown.parent / path).resolve()
    try:
        target.relative_to(ROOT)
    except ValueError:
        return str(target), "points outside the repository"
    if not target.exists():
        return str(target), "missing file or directory"
    return str(target), None


def is_project_url(url: str) -> bool:
    split = urllib.parse.urlsplit(url)
    host = (split.hostname or "").casefold()
    if host == "github.com":
        return split.path.startswith(OWN_GITHUB_ORG)
    return host in OWN_HOSTS


def should_skip_external(url: str) -> bool:
    return any(fragment in url for fragment in EXTERNAL_SKIP_FRAGMENTS)


def fetch(url: str, timeout: float) -> tuple[int | None, str | None]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, None
    except urllib.error.HTTPError as error:
        if error.code in (403, 405):
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Range": "bytes=0-0"},
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return response.status, None
            except urllib.error.HTTPError as retry_error:
                return retry_error.code, None
            except (urllib.error.URLError, TimeoutError, OSError) as retry_error:
                return None, str(retry_error)
        return error.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return None, str(error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true", help="also check project-owned external pages")
    parser.add_argument("--timeout", type=float, default=12.0, help="per-request timeout in seconds")
    args = parser.parse_args()

    relative_count = 0
    external_count = 0
    skipped_count = 0
    broken: list[str] = []
    external_cache: dict[str, str | None] = {}

    for markdown in markdown_files():
        for link in sorted(links_in(markdown.read_text(encoding="utf-8"))):
            if link.startswith("#"):
                continue
            target, error = resolve_relative(markdown, link)
            if target is not None:
                relative_count += 1
                if error:
                    broken.append(f"{markdown.relative_to(ROOT)} -> {link} ({error})")
                continue

            split = urllib.parse.urlsplit(link)
            if split.scheme not in ("http", "https") or not is_project_url(link):
                skipped_count += 1
                continue
            if should_skip_external(link):
                skipped_count += 1
                continue
            if not args.external:
                skipped_count += 1
                continue

            external_count += 1
            if link not in external_cache:
                status, error = fetch(link, args.timeout)
                if status is None:
                    external_cache[link] = f"request failed: {error}"
                elif status >= 400:
                    external_cache[link] = f"HTTP {status}"
                else:
                    external_cache[link] = None
            problem = external_cache[link]
            if problem:
                broken.append(f"{markdown.relative_to(ROOT)} -> {link} ({problem})")

    mode = "relative + project-owned external" if args.external else "relative"
    print(
        f"Link check ({mode}): relative={relative_count}, "
        f"external={external_count}, skipped={skipped_count}, broken={len(broken)}"
    )
    for item in broken:
        print("  BROKEN " + item)
    if broken:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
