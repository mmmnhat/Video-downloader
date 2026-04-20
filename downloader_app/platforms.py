from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlatformMatch:
    name: str
    domain: str
    supported: bool


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
        supported=False,
    ),
    "reddit": PlatformRule(
        domains=frozenset(
            {
                "reddit.com",
                "redd.it",
            }
        )
    ),
}


def normalize_hostname(url: str) -> str:
    parsed = urlparse(url.strip())
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("mobile."):
        hostname = hostname[len("mobile.") :]
    return hostname


def hostname_matches_domain(hostname: str, domain: str) -> bool:
    return hostname == domain or hostname.endswith(f".{domain}")


def detect_platform(url: str) -> PlatformMatch:
    hostname = normalize_hostname(url)

    for platform_name, rule in PLATFORM_RULES.items():
        for domain in rule.domains:
            if hostname_matches_domain(hostname, domain):
                return PlatformMatch(
                    name=platform_name,
                    domain=hostname,
                    supported=rule.supported,
                )

    return PlatformMatch(
        name="unsupported",
        domain=hostname or "unknown",
        supported=False,
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
