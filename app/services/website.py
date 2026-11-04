"""Website content source for maintenance checks (technical doc 7.3). Nothing outside this module knows
whether pages come from sample content or the live web; switch with WEBSITE_BACKEND=sample|live."""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib import robotparser

UA = "ResourceEngineBot/1.0 (+https://www.1degree.org/; data-quality checks)"


@dataclass
class WebPage:
    url: str
    status: int | None
    text: str = ""
    error: str | None = None      # expired_certificate | dns_failure | connection_refused | timeout | blocked_by_robots | not_in_samples | ...


def norm_url(u: str) -> str:
    p = urlparse(u if "//" in u else f"//{u}")
    return (p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")).strip()


class SampleWebsiteSource:
    def __init__(self, path: Path):
        self.pages = {}
        if Path(path).exists():
            self.pages = {norm_url(k): v for k, v in json.loads(Path(path).read_text()).items()}

    def fetch(self, url: str) -> WebPage:
        v = self.pages.get(norm_url(url))
        if v is None:
            return WebPage(url, None, "", "not_in_samples")
        return WebPage(url, v.get("status", 200 if not v.get("error") else None), v.get("text", ""), v.get("error"))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        if tag in ("p", "br", "li", "h1", "h2", "h3", "tr", "div"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, d):
        if not self.skip:
            self.out.append(d)


class LiveWebsiteSource:  # pragma: no cover - live network
    """Honest user agent, robots.txt respected, per-host rate limit. Pages that need JavaScript will
    yield little text; those become `check_failed`, which is the intended, visible outcome."""

    def __init__(self, min_interval: float = 2.0):
        self.min_interval, self._last, self._robots = min_interval, {}, {}

    def _allowed(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            rp = robotparser.RobotFileParser()
            rp.set_url(f"{urlparse(url).scheme}://{host}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001
                rp = None
            self._robots[host] = rp
        rp = self._robots[host]
        return True if rp is None else rp.can_fetch(UA, url)

    def fetch(self, url: str) -> WebPage:
        import requests
        if not url.startswith("http"):
            url = "http://" + url
        if not self._allowed(url):
            return WebPage(url, None, "", "blocked_by_robots")
        host = urlparse(url).netloc
        wait = self.min_interval - (time.time() - self._last.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.time()
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        except requests.exceptions.SSLError as e:
            return WebPage(url, None, "", "expired_certificate" if "expired" in str(e).lower() else "tls_error")
        except requests.exceptions.ConnectTimeout:
            return WebPage(url, None, "", "timeout")
        except requests.exceptions.ReadTimeout:
            return WebPage(url, None, "", "timeout")
        except requests.exceptions.ConnectionError as e:
            msg = str(e).lower()
            return WebPage(url, None, "", "dns_failure" if "name or service" in msg or "getaddrinfo" in msg else "connection_refused")
        p = _Text()
        p.feed(r.text)
        text = re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", "".join(p.out))).strip()
        return WebPage(url, r.status_code, text[:60000], None)


def build_website_source(settings):
    return LiveWebsiteSource() if settings.website_backend == "live" else SampleWebsiteSource(settings.website_samples_path)
