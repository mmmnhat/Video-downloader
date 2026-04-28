from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlatformMatch:
    name: str
    domain: str
    supported: bool
    normalized_url: str


@dataclass(frozen=True)
class PlatformRule:
    domains: frozenset[str]
    supported: bool = True


PLATFORM_RULES = {
    "youtube": PlatformRule(
        domains=frozenset(
            {
                "youtube.com",
                "youtu.be",
            }
        )
    ),
    "facebook": PlatformRule(
        domains=frozenset(
            {
                "facebook.com",
                "fb.watch",
            }
        )
    ),
    "instagram": PlatformRule(domains=frozenset({"instagram.com"})),
    "tiktok": PlatformRule(domains=frozenset({"tiktok.com"})),
    "pinterest": PlatformRule(
        domains=frozenset(
            {
                "pinterest.com",
                "pin.it",
            }
        )
    ),
    "dumpert": PlatformRule(domains=frozenset({"dumpert.nl"})),
    "x": PlatformRule(
        domains=frozenset(
            {
                "x.com",
                "twitter.com",
            }
        )
    ),
    "threads": PlatformRule(
        domains=frozenset(
            {
                "threads.net",
                "threads.com",
            }
        ),
        supported=True,
    ),
    "reddit": PlatformRule(
        domains=frozenset(
            {
                "reddit.com",
                "redd.it",
            }
        )
    ),
    "telegram": PlatformRule(
        domains=frozenset(
            {
                "t.me",
                "telegram.me",
                "telegram.dog",
            }
        )
    ),
    "dailymotion": PlatformRule(
        domains=frozenset(
            {
                "dailymotion.com",
                "dai.ly",
            }
        )
    ),
    "yandex": PlatformRule(
        domains=frozenset(
            {
                "yandex.ru",
                "yandex.com",
                "yandex.by",
                "yandex.kz",
                "yandex.ua",
                "yandex.com.tr",
                "zen.yandex.ru",
                "dzen.ru",
            }
        )
    ),
    "nicovideo": PlatformRule(
        domains=frozenset(
            {
                "nicovideo.jp",
                "nico.ms",
            }
        )
    ),
    "28lab": PlatformRule(
        domains=frozenset(
            {
                "28lab.com",
            }
        )
    ),
    "snapchat": PlatformRule(
        domains=frozenset(
            {
                "snapchat.com",
                "snap.com",
            }
        )
    ),
}


def normalize_hostname(url: str) -> str:
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("mobile."):
        hostname = hostname[len("mobile.") :]
    if hostname == "threads.com" or hostname.endswith(".threads.com"):
        hostname = hostname.replace("threads.com", "threads.net")
    return hostname


def normalize_video_url(url: str) -> str:
    """True URL rewriting/normalization for engine compatibility."""
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()

    if hostname == "threads.com" or hostname.endswith(".threads.com"):
        # Force rewriting threads.com to threads.net for yt-dlp compatibility
        new_netloc = parsed.netloc.lower().replace("threads.com", "threads.net")
        return parsed._replace(netloc=new_netloc).geturl()

    if "yandex." in hostname or "dzen.ru" in hostname:
        if not hostname.endswith("yandex.ru") and not hostname.endswith("dzen.ru"):
            # Force rewriting international yandex domains (e.g. yandex.kz) to yandex.ru for yt-dlp compatibility
            new_netloc = parsed.netloc.lower()
            new_netloc = re.sub(r"yandex\.(com\.tr|com|by|kz|ua)", "yandex.ru", new_netloc)
            return parsed._replace(netloc=new_netloc).geturl()

    return url


def hostname_matches_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def detect_platform(url: str) -> PlatformMatch:
    normalized_url = normalize_video_url(url)
    hostname = normalize_hostname(normalized_url)

    for platform_name, rule in PLATFORM_RULES.items():
        for domain in rule.domains:
            if hostname_matches_domain(hostname, domain):
                return PlatformMatch(
                    name=platform_name,
                    domain=hostname,
                    supported=rule.supported,
                    normalized_url=normalized_url,
                )

    return PlatformMatch(
        name="unsupported",
        domain=hostname or "unknown",
        supported=False,
        normalized_url=url,
    )


def supported_platforms() -> list[str]:
    return sorted(
        platform_name
        for platform_name, rule in PLATFORM_RULES.items()
        if rule.supported
    )


def is_probable_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def maybe_detect_platform(url: str) -> Optional[PlatformMatch]:
    if not is_probable_video_url(url):
        return None
    return detect_platform(url)
