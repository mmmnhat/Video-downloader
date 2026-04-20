from downloader_app.platforms import detect_platform

urls = [
    "https://www.threads.net/@zuck/post/Cx7z8Rmx9_R",
    "https://threads.net/t/123",
]

for url in urls:
    match = detect_platform(url)
    print(f"URL: {url}")
    print(f"Platform: {match.name}")
    print(f"Supported: {match.supported}")
    print("-" * 20)
