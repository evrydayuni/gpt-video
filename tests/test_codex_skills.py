"""Offline checks for the two Codex skills and local-only defaults."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATCH = ROOT / "skills" / "watch"
LEARN = ROOT / "skills" / "learn"


def test_skill_layout_and_invocation_contract():
    for path, name in ((WATCH, "watch"), (LEARN, "learn")):
        content = (path / "SKILL.md").read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert f"name: {name}\n" in content
        assert "description:" in content
        assert (path / "agents" / "openai.yaml").is_file()


def test_watch_forces_codex_local_in_agent_instructions():
    content = (WATCH / "SKILL.md").read_text(encoding="utf-8")
    assert "--engine local" in content
    assert "--no-whisper" in content
    assert "explicitly opts" in content


def test_learn_requires_review_before_install():
    content = (LEARN / "SKILL.md").read_text(encoding="utf-8")
    assert "SKILL.draft.md" in content
    assert "Do you approve installing this skill?" in content
    assert "Do not write to" in content
    assert "Untrusted sources" in content


def test_codex_manifest_points_to_our_fork_and_both_skills():
    data = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
    market = json.loads((ROOT / ".agents" / "plugins" / "marketplace.json").read_text())
    assert data["name"] == "gpt-video"
    assert data["skills"] == "./skills/"
    assert data["repository"] == "https://github.com/evrydayuni/gpt-video"
    assert market["plugins"][0]["source"]["url"] == "https://github.com/evrydayuni/gpt-video.git"


def _source_module():
    path = LEARN / "scripts" / "list_sources.py"
    spec = importlib.util.spec_from_file_location("learn_source_listing", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_source_listing_limits_and_local_url_guard(monkeypatch):
    module = _source_module()
    assert not module.public_url("file:///etc/passwd")
    assert not module.public_url("http://127.0.0.1/private")
    assert not module.public_url("http://user:secret@example.com/feed")
    monkeypatch.setattr(module.socket, "getaddrinfo",
                        lambda *a, **kw: [(None, None, None, None, ("1.1.1.1", 0))])
    assert module.public_url("https://example.com/feed")


def test_rss_extracts_bounded_podcast_episodes(monkeypatch):
    module = _source_module()
    monkeypatch.setattr(module, "public_url", lambda url: True)
    data = b'<rss><channel><item><title>Episode One</title><enclosure url="https://cdn.example.com/one.mp3"/></item><item><title>Episode Two</title><enclosure url="https://cdn.example.com/two.mp3"/></item></channel></rss>'

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return None
        def geturl(self): return "https://example.com/feed.xml"
        def read(self, n): return data

    class Opener:
        def open(self, *a, **kw): return Response()

    monkeypatch.setattr(module.urllib.request, "build_opener", lambda *a: Opener())
    entries = module.rss_entries("https://example.com/feed.xml", 1)
    assert [entry["title"] for entry in entries] == ["Episode One"]


def test_playlist_enumeration_bound_and_video_id(monkeypatch):
    module = _source_module()
    monkeypatch.setattr(module, "public_url", lambda url: True)

    class Result:
        returncode = 0
        stdout = json.dumps({"entries": [{"id": "dQw4w9WgXcQ", "title": "Demo"}]})
    def run(cmd, **kwargs):
        assert "--playlist-end" in cmd
        assert "3" in cmd
        return Result()

    monkeypatch.setattr(module.subprocess, "run", run)
    entries = module.playlist_entries("https://www.youtube.com/playlist?list=x", 3)
    assert entries == [{"title": "Demo",
                        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                        "kind": "video"}]
