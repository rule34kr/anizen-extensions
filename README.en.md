# AniZen WebDAV Extensions

Personal WebDAV extension distribution repository for AniZen.

- Extension: WebDAV
- Package: `eu.kanade.tachiyomi.animeextension.ko.webdav`
- Language category: `ko` (Korean)
- Extensions-lib baseline: v16
- Default WebDAV port: `8081`
- Instances: 1–10 independent WebDAV sources (default 3)
- Build environment: `salmanbappi/sb-extensions-source` pinned to `c8d9cef922353b0399ee802d5a594d1884c9be41`

**Language:** [한국어](README.md) | English

## AniZen repository URL

After the first successful signed build, add:

```text
https://raw.githubusercontent.com/rule34kr/anizen-extensions/main/repo.json
```

In AniZen, open **Settings → Browse → Extension repositories → Add repository**.

> APKs and repository indices are not published until all signing secrets are configured and the GitHub Actions workflow succeeds.

## Release signing setup

Create a persistent signing key on a trusted PC with JDK keytool:

```powershell
keytool -genkeypair -v -keystore .\webdav-signing.jks -storetype JKS -alias webdav -keyalg RSA -keysize 2048 -validity 10000
```

Keep the JKS file and passwords private. Never commit the keystore. Use the same key for every future update.

Get the certificate SHA-256 fingerprint:

```powershell
keytool -list -v -keystore .\webdav-signing.jks -alias webdav
```

Remove colons and spaces from the SHA256 value and convert it to lowercase (exactly 64 hexadecimal characters).

Encode the keystore:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\webdav-signing.jks)))
```

In **GitHub → Settings → Secrets and variables → Actions**, add these repository secrets:

| Secret | Value |
|---|---|
| `SIGNING_KEY` | Entire Base64 output of the JKS |
| `ALIAS` | `webdav` |
| `KEY_STORE_PASSWORD` | Keystore password |
| `KEY_PASSWORD` | Key password |
| `SIGNING_KEY_FINGERPRINT` | Lowercase 64-character SHA-256 fingerprint, without colons |

Do not send these values in chat or put them in source control.

## Build and publish

After adding all five secrets, open **Actions → Build and publish WebDAV extension → Run workflow** and run it on `main`.

The workflow restores the source module, builds a signed Release APK with Java 17/Gradle, verifies its signing certificate, generates AniZen's Protobuf v2 repository index and legacy JSON indices, then publishes APKs and metadata to this repository. The extension and each exposed WebDAV source use the `ko` language category. The WebDAV extension defaults to port `8081` (also when an HTTP address omits its port), supports up to 10 independent source instances (default 3), allows each instance to have its own display name, and tests connectivity through the same OkHttp WebDAV request used for browsing. Only the previous built-in default `http://192.168.0.10:8080` is migrated automatically; other explicitly configured ports are preserved.

Changes under `payload/` trigger a rebuild. Increment `extVersionCode` in the embedded `src/ko/webdav/build.gradle` before publishing an update. Initial source version: `16.1`.

## Verification status

The source was prepared against the uploaded AniZen and extension-source snapshots. The first hosted Gradle build is the first real compile/signing check. Device-level validation is still required for extension loading, WebDAV PROPFIND, MPV Range requests and seeking.

## Security

Prefer HTTPS or Tailscale for remote access. Do not expose an unauthenticated WebDAV server directly to the public Internet. Keep the signing key unchanged between releases.
