#!/usr/bin/env python3
"""Bounded source listing for Learn. Outputs JSON; never downloads media."""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import socket
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

MAX_FEED_BYTES = 2 * 1024 * 1024


def public_url(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password:
        return False
    try:
        addresses = socket.getaddrinfo(parts.hostname, None, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(addresses) and all(
        ipaddress.ip_address(address[4][0].split("%")[0]).is_global
        for address in addresses
    )


class PublicRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not public_url(newurl):
            raise ValueError("Redirect destination is not a public web URL")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def rss_entries(url: str, count: int) -> list[dict]:
    opener = urllib.request.build_opener(PublicRedirects())
    request = urllib.request.Request(url, headers={"User-Agent": "gpt-video-learn/0.1"})
    with opener.open(request, timeout=25) as response:
        if not public_url(response.geturl()):
            raise ValueError("Feed redirected to a non-public address")
        raw = response.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds 2 MB limit")
    root = ET.fromstring(raw)
    items = []
    for entry in root.iter():
        tag = entry.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title, enclosure = "Untitled episode", None
        for node in entry:
            label = node.tag.rsplit("}", 1)[-1]
            if label == "title" and node.text:
                title = node.text.strip()[:200]
            if label == "enclosure":
                enclosure = node.get("url") or node.get("href")
            if label == "link" and node.get("rel") == "enclosure":
                enclosure = node.get("href")
        if enclosure and public_url(enclosure):
            items.append({"title": title, "url": enclosure, "kind": "podcast"})
        if len(items) >= count:
            break
    return items


def playlist_entries(url: str, count: int) -> list[dict]:
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-single-json",
             "--playlist-end", str(count), "--no-warnings", "--", url],
            capture_output=True, text=True, timeout=90, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Playlist listing unavailable: {type(exc).__name__}") from None
    if result.returncode:
        raise ValueError("yt-dlp could not list this playlist (check URL, access and yt-dlp installation)")
    info = json.loads(result.stdout)
    entries = []
    for entry in (info.get("entries") or [])[:count]:
        if not isinstance(entry, dict):
            continue
        link = entry.get("webpage_url") or entry.get("url") or ""
        if not str(link).startswith(("https://", "http://")):
            vid = entry.get("id") or link
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", str(vid)):
                link = "https://www.youtube.com/watch?v=" + str(vid)
        if isinstance(link, str) and public_url(link):
            entries.append({"title": str(entry.get("title") or "Untitled video")[:200],
                            "url": link, "kind": "video"})
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="List bounded playlist or podcast feed entries as JSON")
    parser.add_argument("url")
    parser.add_argument("--latest", type=int, default=5)
    args = parser.parse_args()
    if not 1 <= args.latest <= 20:
        parser.error("--latest must be between 1 and 20")
    if not public_url(args.url):
        parser.error("Only public HTTP(S) URLs are supported")
    try:
        path = urllib.parse.urlsplit(args.url).path.lower()
        if (path.endswith((".rss", ".xml")) or "/feed" in path
                or "rss" in path or "feeds." in urllib.parse.urlsplit(args.url).hostname):
            entries = rss_entries(args.url, args.latest)
        else:
            entries = playlist_entries(args.url, args.latest)
    except (ValueError, OSError, ET.ParseError, json.JSONDecodeError) as exc:
        print(json.dumps({"entries": [], "error": str(exc)}))
        return 1
    print(json.dumps({"entries": entries, "count": len(entries)}, indent=2, ensure_ascii=False))
    return 0 if entries else 1


if __name__ == "__main__":
    sys.exit(main())
