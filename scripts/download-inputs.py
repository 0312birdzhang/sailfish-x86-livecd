#!/usr/bin/env python3
"""Download and verify the Ubuntu Base and Sailfish SDK emulator inputs."""

import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import urllib.request


WORK = Path(os.environ.get("SFOS_WORK", "/home/bird/data/tmp/sfos-live"))
DOWNLOADS = WORK / "downloads"
USER_AGENT = "sfos-ubuntu-live-builder"
RELEASE_CONFIG = json.loads((Path(__file__).resolve().parents[1] / "config/release.json").read_text())
RELEASE = RELEASE_CONFIG["version"]
SDK_SEED_RELEASE = RELEASE_CONFIG["sdk_seed_version"]


def request(url):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
        timeout=120,
    )


def download(url, target, digest):
    if target.exists():
        checksum = hashlib.sha256()
        with target.open("rb") as existing:
            while chunk := existing.read(1024 * 1024):
                checksum.update(chunk)
        if checksum.hexdigest() == digest:
            print(f"Already verified {target.name}", flush=True)
            return
    temporary = target.with_suffix(target.suffix + ".part")
    checksum = hashlib.sha256()
    count = 0
    with request(url) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
            checksum.update(chunk)
            count += len(chunk)
    if checksum.hexdigest() != digest:
        raise RuntimeError(f"Checksum mismatch for {target.name}")
    temporary.replace(target)
    print(f"Verified {target.name}, {count // (1024 * 1024)} MiB", flush=True)


def ubuntu():
    base = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/"
    filename = "ubuntu-base-24.04.5-base-amd64.tar.gz"
    digest = "e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86"
    download(base + filename, DOWNLOADS / filename, digest)
    return {"filename": filename, "sha256": digest, "url": base + filename}


def sailfish():
    if SDK_SEED_RELEASE != "5.1.0.11":
        raise RuntimeError("No pinned SDK checksum for " + SDK_SEED_RELEASE)
    filename = f"Sailfish_OS-{SDK_SEED_RELEASE}-Sailfish_SDK_Emulator.7z"
    url = "https://releases.sailfishos.org/sdk/emulators/" + filename
    digest = "a92e06d3bac500495e9c49b4ed77dd07a826793a8e460725022851e8f4479a94"
    download(url, DOWNLOADS / filename, digest)
    return {"filename": filename, "sha256": digest, "url": url}


def weston_compatibility():
    base = "https://archive.ubuntu.com/ubuntu/pool/universe/w/weston/"
    packages = [
        ("weston_9.0.0-4ubuntu1_amd64.deb", "f6abfdd55c0bdb62097e14cea2d4834ba4546f28210a68aa31c8cd9bab4e6969"),
        ("libweston-9-0_9.0.0-4ubuntu1_amd64.deb", "a54f399cb3b9f28314945875e40072eeb766a1fe0022659b66e88de43fa9c012"),
    ]
    inputs = []
    for filename, digest in packages:
        download(base + filename, DOWNLOADS / filename, digest)
        inputs.append({"filename": filename, "sha256": digest, "url": base + filename})
    return inputs


def sailfish_package_manager():
    packages = [
        ("augeas-libs-1.14.1+git1-1.7.3.jolla.i486.rpm", "7d41b31f50155665cd012b76217c8fb20b5bc17f29a0390f8e75d3206db3862f"),
        ("readline-8.3+git2-1.7.3.jolla.i486.rpm", "364d571d622f8e5a6b90d0c37bcb17416f43bad10c4fa9fccf6df3c6e1e4594b"),
        ("zypper-1.14.68+git1-1.7.4.jolla.i486.rpm", "e3d0f868e337b88a7b00736b2136c18c2c10937274105ce68cb3418215391570"),
    ]
    directory = DOWNLOADS / "sailfish-package-manager" / RELEASE
    directory.mkdir(parents=True, exist_ok=True)
    inputs = []
    for filename, digest in packages:
        url = f"https://releases.jolla.com/releases/{RELEASE}/jolla/i486/oss/i486/{filename}"
        download(url, directory / filename, digest)
        inputs.append({"filename": str((directory / filename).relative_to(DOWNLOADS)), "sha256": digest, "url": url})
    return inputs


def main():
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        ubuntu_task = pool.submit(ubuntu)
        sailfish_task = pool.submit(sailfish)
        weston_task = pool.submit(weston_compatibility)
        package_manager_task = pool.submit(sailfish_package_manager)
        inputs = {
            "sailfish_release": RELEASE,
            "sailfish_seed_release": SDK_SEED_RELEASE,
            "ubuntu": ubuntu_task.result(),
            "sailfish": sailfish_task.result(),
            "weston_compatibility": weston_task.result(),
            "sailfish_package_manager": package_manager_task.result(),
        }
    (DOWNLOADS / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    print(json.dumps(inputs, indent=2), flush=True)


if __name__ == "__main__":
    main()
