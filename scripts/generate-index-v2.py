#!/usr/bin/env python3
"""Generate AniZen's gzip-compressed Protobuf v2 index and repo.json."""
import argparse
import gzip
import json
import re
import sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo-dir", required=True, type=Path)
    p.add_argument("--owner", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--fingerprint", required=True)
    a = p.parse_args()

    fingerprint = a.fingerprint.strip().lower().replace(":", "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise SystemExit("Fingerprint must be 64 lowercase hexadecimal characters.")

    repo_dir = a.repo_dir.resolve()
    index_path = repo_dir / "index.min.json"
    if not index_path.is_file():
        raise SystemExit(f"Missing {index_path}")
    entries = json.loads(index_path.read_text(encoding="utf-8"))
    if not entries:
        raise SystemExit("No extension entries were generated.")

    workspace = Path(__file__).resolve().parents[1]
    upstream_scripts = workspace / "upstream" / ".github" / "scripts"
    sys.path.insert(0, str(upstream_scripts))
    import index_pb2

    base = f"https://raw.githubusercontent.com/{a.owner}/{a.repo}/{a.branch}"
    website = f"https://github.com/{a.owner}/{a.repo}"
    extensions = []
    for entry in entries:
        apk_name = str(entry.get("apk") or "")
        package = str(entry.get("pkg") or "")
        if not apk_name or not package:
            continue

        sources = []
        for source in entry.get("sources", []):
            try:
                source_id = int(source.get("id") or 0)
            except (TypeError, ValueError):
                source_id = 0
            sources.append(index_pb2.Source(
                id=source_id,
                name=str(source.get("name") or ""),
                language=str(source.get("lang") or ""),
                homeUrl=str(source.get("baseUrl") or ""),
                mirrorUrls=list(source.get("mirrorUrls") or []),
            ))

        version = str(entry.get("version") or "16.1")
        extension_lib = str(entry.get("extensionLib") or "16")
        try:
            version_code = int(entry.get("code") or 0)
        except (TypeError, ValueError):
            version_code = 0
        try:
            warning = int(entry.get("contentRating") or 1)
        except (TypeError, ValueError):
            warning = 1
        warning = min(max(warning, 1), 3)

        extensions.append(index_pb2.Extension(
            name=str(entry.get("name") or package),
            packageName=package,
            resources=index_pb2.Resources(
                apkUrl=f"{base}/apk/{apk_name}",
                iconUrl=f"{base}/icon/{package}.png",
            ),
            extensionLib=extension_lib,
            versionCode=version_code,
            versionName=version,
            contentWarning=warning,
            isTorrent=bool(entry.get("isTorrent", False)),
            sources=sources,
        ))

    if not extensions:
        raise SystemExit("No valid APK entries found.")

    index = index_pb2.Index(
        name="AniZen WebDAV Extensions",
        badgeLabel="WDB",
        signingKey=fingerprint,
        contact=index_pb2.Contact(website=website),
        extensionList=index_pb2.ExtensionList(extensions=extensions),
    )
    payload = gzip.compress(index.SerializeToString(deterministic=True), mtime=0)
    (repo_dir / "index.pb").write_bytes(payload)

    metadata = {
        "index_v2": f"{base}/index.pb",
        "meta": {
            "name": "AniZen WebDAV Extensions",
            "shortName": "WDB",
            "website": website,
            "signingKeyFingerprint": fingerprint,
        },
    }
    (repo_dir / "repo.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated AniZen index for {len(extensions)} extension(s).")

if __name__ == "__main__":
    main()
