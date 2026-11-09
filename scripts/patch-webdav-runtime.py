#!/usr/bin/env python3
"""Apply runtime compatibility and HTTP port defaults to the restored WebDAV source."""
from pathlib import Path
import sys

def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise SystemExit(f"Could not find expected source block: {label}")
    return text.replace(old, new, 1)

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch-webdav-runtime.py <upstream-root>")

    root = Path(sys.argv[1]).resolve()
    source_path = root / "src/all/webdav/src/eu/kanade/tachiyomi/animeextension/all/webdav/WebDav.kt"
    manifest_path = root / "src/all/webdav/AndroidManifest.xml"
    if not source_path.is_file() or not manifest_path.is_file():
        raise SystemExit("Restored WebDAV source or manifest is missing.")

    source = source_path.read_text(encoding="utf-8")

    old_preferences = '''            title = "WebDAV 서버 주소",
            summary = "예: http://192.168.0.10:8081 또는 Tailscale 주소",
            dialogMessage = "http:// 또는 https:// 주소를 입력하세요.",'''
    new_preferences = '''            title = "WebDAV 서버 주소",
            summary = "예: http://192.168.0.10:8081 또는 Tailscale 주소 (HTTP 포트 생략 시 8081)",
            dialogMessage = "http:// 또는 https:// 주소를 입력하세요. HTTP 포트를 생략하면 8081을 사용합니다.",'''
    source = replace_once(source, old_preferences, new_preferences, "server address preference summary")

    old_url_parser = '''    private fun configuredServerUrl(): HttpUrl? {
        val raw = preferences.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL)?.trim().orEmpty()
        val parsed = raw.toHttpUrlOrNull() ?: return null
        if (parsed.scheme != "http" && parsed.scheme != "https") return null
        if (parsed.username.isNotEmpty() || parsed.password.isNotEmpty()) return null
        if (parsed.query != null || parsed.fragment != null) return null
        return parsed
    }'''
    new_url_parser = '''    private fun configuredServerUrl(): HttpUrl? {
        var raw = preferences.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL)?.trim().orEmpty()

        // Migrate the old built-in default only; leave user-entered explicit ports untouched.
        if (raw.equals(LEGACY_DEFAULT_SERVER_URL, ignoreCase = true)) {
            preferences.edit().putString(KEY_SERVER_URL, DEFAULT_SERVER_URL).apply()
            raw = DEFAULT_SERVER_URL
        }

        val parsed = raw.toHttpUrlOrNull() ?: return null
        if (parsed.scheme != "http" && parsed.scheme != "https") return null
        if (parsed.username.isNotEmpty() || parsed.password.isNotEmpty()) return null
        if (parsed.query != null || parsed.fragment != null) return null

        // OkHttp otherwise silently selects port 80 for "http://host".
        // For this extension, an omitted HTTP port means the WebDAV default 8081.
        return if (parsed.scheme == "http" && !hasExplicitPort(raw)) {
            parsed.newBuilder().port(DEFAULT_SERVER_PORT).build()
        } else {
            parsed
        }
    }

    private fun hasExplicitPort(rawUrl: String): Boolean {
        val authority = rawUrl.substringAfter("://").substringBefore('/').substringBefore('?').substringBefore('#')
        val hostAndPort = authority.substringAfterLast('@')
        return if (hostAndPort.startsWith("[")) {
            val closingBracket = hostAndPort.indexOf(']')
            closingBracket >= 0 && hostAndPort.getOrNull(closingBracket + 1) == ':'
        } else {
            hostAndPort.count { it == ':' } == 1
        }
    }'''
    source = replace_once(source, old_url_parser, new_url_parser, "URL parser and default HTTP port")

    old_constants = '''        const val DEFAULT_SERVER_URL = "http://192.168.0.10:8081"
        internal const val INSTANCE_COUNT_KEY'''
    new_constants = '''        const val DEFAULT_SERVER_URL = "http://192.168.0.10:8081"
        private const val LEGACY_DEFAULT_SERVER_URL = "http://192.168.0.10:8080"
        private const val DEFAULT_SERVER_PORT = 8081
        internal const val INSTANCE_COUNT_KEY'''
    source = replace_once(source, old_constants, new_constants, "server default constants")

    source_path.write_text(source, encoding="utf-8")

    manifest = manifest_path.read_text(encoding="utf-8")
    old_version = '''            android:name="tachiyomi.animeextension.versionId"
            android:value="3" />'''
    new_version = '''            android:name="tachiyomi.animeextension.versionId"
            android:value="3"
            tools:replace="android:value" />'''
    manifest = replace_once(manifest, old_version, new_version, "versionId manifest metadata")
    manifest_path.write_text(manifest, encoding="utf-8")

    print("Patched WebDAV HTTP port fallback/migration and versionId manifest priority.")

if __name__ == "__main__":
    main()
