#!/usr/bin/env python3
"""Patch the restored WebDAV module for AniZen runtime behavior."""
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
    nfo_parser_path = root / "src/all/webdav/src/eu/kanade/tachiyomi/animeextension/all/webdav/NfoXml.kt"
    manifest_path = root / "src/all/webdav/AndroidManifest.xml"
    module_build_path = root / "src/all/webdav/build.gradle"
    if (
        not source_path.is_file()
        or not nfo_parser_path.is_file()
        or not manifest_path.is_file()
        or not module_build_path.is_file()
    ):
        raise SystemExit("Restored WebDAV source, NFO parser, manifest or build.gradle is missing.")

    source = source_path.read_text(encoding="utf-8")

    # Instance name is stored in the preference file belonging to each source ID.
    source = replace_once(
        source,
        '    override val name: String = "WebDAV ($suffix)"',
        '''    private val instanceName: String
        get() = preferences.getString(KEY_INSTANCE_NAME, defaultInstanceName())?.trim().orEmpty()
            .ifBlank { defaultInstanceName() }

    override val name: String
        get() = instanceName

    private fun defaultInstanceName(): String = "WebDAV ($suffix)"''',
        "instance display name property",
    )

    setup_marker = "    override fun setupPreferenceScreen(screen: PreferenceScreen) {\n"
    name_preference = '''        screen.addEditTextPreference(
            key = KEY_INSTANCE_NAME,
            default = defaultInstanceName(),
            title = "인스턴스 이름",
            summary = "현재 이름: $instanceName · 변경 후 AniZen 재시작 필요",
            dialogMessage = "이 WebDAV 인스턴스를 구분할 이름을 입력하세요.",
            inputType = InputType.TYPE_CLASS_TEXT,
            allowBlank = false,
            validate = { it.trim().isNotEmpty() && it.trim().length <= 40 },
            validationMessage = { "인스턴스 이름은 1~40자로 입력하세요." },
            restartRequired = true,
        )

'''
    source = replace_once(source, setup_marker, setup_marker + name_preference, "instance name preference")

    source = replace_once(
        source,
        '        val folderName = if (url == rootUrl()) "WebDAV" else displayName(url)',
        '        val folderName = if (url == rootUrl()) instanceName else displayName(url)',
        "root folder display name",
    )
    source = replace_once(
        source,
        '        title = "WebDAV"\n        description = "경로: ${displayPath(root)}"',
        '        title = instanceName\n        description = "경로: ${displayPath(root)}"',
        "root source entry title",
    )

    # The old preflight used java.net.InetAddress and a raw Socket. It could fail
    # even when the app's OkHttp client could reach the same Tailscale endpoint.
    source = replace_once(
        source,
        "                checkTcpReachability(root)\n",
        "",
        "remove raw socket preflight call",
    )
    tcp_block = '''    /**
     * Separate name resolution / TCP reachability from the WebDAV PROPFIND request.
     * This makes connection-test errors actionable for VPN hostnames and non-default ports.
     */
    private fun checkTcpReachability(url: HttpUrl) {
        val addresses = try {
            InetAddress.getAllByName(url.host).sortedBy { if (it is java.net.Inet4Address) 0 else 1 }
        } catch (e: Exception) {
            throw IOException("DNS_LOOKUP_FAILED: ${url.host}", e)
        }
        if (addresses.isEmpty()) {
            throw IOException("DNS_LOOKUP_FAILED: ${url.host}")
        }

        var lastError: Exception? = null
        for (address in addresses) {
            try {
                Socket().use { socket ->
                    socket.connect(InetSocketAddress(address, url.port), 3000)
                }
                return
            } catch (e: Exception) {
                lastError = e
            }
        }
        throw IOException("TCP_CONNECT_FAILED: ${url.host}:${url.port}", lastError)
    }

'''
    if tcp_block in source:
        source = source.replace(tcp_block, "", 1)
    elif "private fun checkTcpReachability(" in source:
        raise SystemExit("TCP preflight function changed unexpectedly; refusing a partial removal.")

    # Use the same OkHttp PROPFIND operation as directory browsing and inspect its
    # underlying exception type to distinguish DNS, timeout and TCP failures.
    source = replace_once(
        source,
        "import java.io.IOException\nimport java.net.InetAddress\nimport java.net.InetSocketAddress\nimport java.net.Socket\n",
        "import java.io.IOException\nimport java.net.ConnectException\nimport java.net.SocketTimeoutException\nimport java.net.UnknownHostException\n",
        "network imports",
    )
    old_safe_errors = '''    private fun safeErrorMessage(error: Exception): String {
        val message = error.message.orEmpty()
        // Avoid echoing an arbitrary URL or any credential-bearing request detail into the UI.
        return when {
            message.contains("DNS_LOOKUP_FAILED", true) -> "DNS 조회 실패: 호스트 이름을 해석할 수 없음"
            message.contains("TCP_CONNECT_FAILED", true) -> "TCP 연결 실패: 서버 주소와 포트, Tailscale 연결 상태를 확인하세요"
            message.contains("timed out", true) -> "시간 초과"
            message.contains("failed to connect", true) -> "서버에 연결할 수 없음"
            message.contains("cleartext", true) -> "HTTP 평문 통신이 차단됨"
            message.isBlank() -> "네트워크 또는 서버 설정을 확인하세요"
            else -> message.take(100)
        }
    }'''
    new_safe_errors = '''    private fun safeErrorMessage(error: Exception): String {
        val causes = generateSequence(error as Throwable) { it.cause }.take(8).toList()
        val message = error.message.orEmpty()
        // Do not display the full URL or any credential-bearing request details.
        return when {
            causes.any { it is UnknownHostException } ->
                "DNS 조회 실패: 호스트 이름을 확인할 수 없습니다. MagicDNS와 Tailscale DNS 설정을 확인하세요."
            causes.any { it is SocketTimeoutException } ->
                "연결 시간 초과: 서버 주소, 포트, Tailscale 경로를 확인하세요."
            causes.any { it is ConnectException } ->
                "TCP 연결 실패: 서버 주소, 포트, Tailscale 경로를 확인하세요."
            message.contains("cleartext", true) ->
                "HTTP 평문 통신이 차단됨"
            message.isBlank() ->
                "네트워크 또는 서버 설정을 확인하세요."
            else ->
                message.take(100)
        }
    }'''
    source = replace_once(source, old_safe_errors, new_safe_errors, "connection error classification")

    source = replace_once(
        source,
        '        const val KEY_SERVER_URL = "webdav_server_url"',
        '        const val KEY_INSTANCE_NAME = "webdav_instance_name"\n        const val KEY_SERVER_URL = "webdav_server_url"',
        "instance preference key",
    )

    # Existing server URL/port defaults and validation.
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

    build = module_build_path.read_text(encoding="utf-8")
    build = replace_once(build, "    extVersionCode = 2", "    extVersionCode = 11", "extension version code")
    module_build_path.write_text(build, encoding="utf-8")

    print("Patched WebDAV: per-instance names, OkHttp-only connection test, default HTTP port, manifest metadata, versionCode 12.")


if __name__ == "__main__":
    main()
