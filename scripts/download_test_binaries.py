#!/usr/bin/env python3
import concurrent.futures
from pathlib import Path
import urllib.request

VERSIONS = [
    "0.200.0",
    "0.205.0",
    "0.210.0",
    "0.211.0",
    "0.213.0",
    "0.215.0",
    "0.215.1",
    "0.216.0",
    "0.217.0",
    "0.218.0",
    "0.218.1",
    "0.218.2",
    "0.219.0",
    "0.220.0",
]
ARCHES = ["x64", "x64-baseline"]
BASE_URL = "https://downloads.factory.ai/factory-cli/releases"
DEST_DIR = Path(".tmp/factory-releases")
DEST_DIR.mkdir(parents=True, exist_ok=True)


def download_one(task):
    ver, arch = task
    url = f"{BASE_URL}/{ver}/linux/{arch}/droid"
    dest = DEST_DIR / f"droid-{ver}-{arch}"
    if dest.exists() and dest.stat().st_size > 50_000_000:
        print(f"Skipping {ver} {arch} (already downloaded, {dest.stat().st_size} bytes)")
        return
    print(f"Downloading {ver} {arch}...")
    part = dest.with_name(f"{dest.name}.part")
    try:
        urllib.request.urlretrieve(url, part)
        part.rename(dest)
        print(f"Completed {ver} {arch} ({dest.stat().st_size} bytes)")
    except Exception as e:
        if part.exists():
            part.unlink()
        print(f"Error {ver} {arch}: {e}")


def main():
    tasks = [(v, a) for v in VERSIONS for a in ARCHES]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(download_one, tasks))
    print("All downloads finished.")


if __name__ == "__main__":
    main()

