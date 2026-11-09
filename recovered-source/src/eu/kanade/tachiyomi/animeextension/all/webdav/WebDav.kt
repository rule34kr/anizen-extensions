package eu.kanade.tachiyomi.animeextension.all.webdav

import android.app.AlertDialog
import android.content.Context
import android.text.InputType
import android.util.Base64
import android.widget.EditText
import androidx.preference.Preference
import androidx.preference.PreferenceScreen
import eu.kanade.tachiyomi.animeextension.all.webdav.crypto.CredentialVault
import eu.kanade.tachiyomi.animeextension.all.webdav.model.DavEntry
import eu.kanade.tachiyomi.animeextension.all.webdav.net.WebDavXml
import eu.kanade.tachiyomi.animesource.model.AnimeFilterList
import eu.kanade.tachiyomi.animesource.model.AnimesPage
import eu.kanade.tachiyomi.animesource.model.SAnime
import eu.kanade.tachiyomi.animesource.model.SEpisode
import eu.kanade.tachiyomi.animesource.model.Video
import extensions.utils.Source
import keiyoushi.utils.addEditTextPreference
import keiyoushi.utils.addListPreference
import okhttp3.Headers
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * An AniZen external source for a user-managed rclone WebDAV endpoint.
 *
 * Directories are presented through AniZen's source-related navigation cards. The current
 * directory's media files are ordinary episodes, so playback continues through AniZen's MPV.
 */
class WebDav(private val suffix: String) : Source() {

    override val name: String = "WebDAV ($suffix)"
    override val versionId: Int = 3
    override val id: Long by lazy {
        val key = "webdav ($suffix)/all/$versionId"
        val bytes = MessageDigest.getInstance("MD5").digest(key.toByteArray())
        (0..7).map { bytes[it].toLong() and 0xff shl 8 * (7 - it) }.reduce(Long::or) and Long.MAX_VALUE
    }
    override val lang: String = "all"
    override val supportsLatest: Boolean = false

    override val baseUrl: String
        get() = configuredServerUrl()?.toString()?.trimEnd('/') ?: DEFAULT_SERVER_URL

    override val client: OkHttpClient by lazy {
        network.client.newBuilder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .callTimeout(45, TimeUnit.SECONDS)
            .build()
    }

    private val credentialVault by lazy { CredentialVault(context, "anizen_webdav_$id") }

    override fun setupPreferenceScreen(screen: PreferenceScreen) {
        if (suffix == "1") {
            screen.addListPreference(
                key = INSTANCE_COUNT_KEY,
                default = INSTANCE_COUNT_DEFAULT,
                title = "WebDAV 인스턴스 개수",
                summary = "생성할 WebDAV 소스 개수입니다. 1~10개까지 설정할 수 있으며 변경 후 AniZen 재시작이 필요합니다.",
                entries = INSTANCE_COUNT_ENTRIES,
                entryValues = INSTANCE_COUNT_ENTRIES,
                restartRequired = true,
            )
        }

        screen.addEditTextPreference(
            key = KEY_SERVER_URL,
            default = DEFAULT_SERVER_URL,
            title = "WebDAV 서버 주소",
            summary = "예: http://192.168.0.10:8081 또는 Tailscale 주소",
            dialogMessage = "http:// 또는 https:// 주소를 입력하세요.",
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI,
            allowBlank = false,
            validate = ::isValidServerUrl,
            validationMessage = { "올바른 http:// 또는 https:// WebDAV 주소를 입력하세요." },
        )
        screen.addPreference(secretPreference(screen.context, KEY_USERNAME, "사용자 이름", InputType.TYPE_CLASS_TEXT))
        screen.addPreference(secretPreference(screen.context, KEY_PASSWORD, "비밀번호", InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD))
        screen.addEditTextPreference(
            key = KEY_ROOT_PATH,
            default = "",
            title = "기본 탐색 경로",
            summary = "선택 항목. 예: /media/anime",
            dialogMessage = "비워 두면 WebDAV 서버의 기본 경로를 사용합니다.",
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI,
        )
        screen.addListPreference(
            key = KEY_SORT_MODE,
            default = SORT_NAME_ASC,
            title = "영상 정렬",
            summary = "파일 브라우저의 기본 정렬 순서",
            entries = listOf("파일명 오름차순", "파일명 내림차순", "파일 크기 큰 순", "파일 크기 작은 순"),
            entryValues = listOf(SORT_NAME_ASC, SORT_NAME_DESC, SORT_SIZE_DESC, SORT_SIZE_ASC),
        )

        screen.addPreference(Preference(screen.context).apply {
            title = "WebDAV 연결 테스트"
            summary = "현재 주소와 인증 정보로 PROPFIND 요청을 보냅니다."
            setOnPreferenceClickListener {
                testConnection()
                true
            }
        })
    }

    private fun secretPreference(
        context: Context,
        key: String,
        titleText: String,
        inputType: Int,
    ): Preference = Preference(context).apply {
        title = titleText
        summary = if (credentialVault.read(key).isNullOrEmpty()) "설정되지 않음" else "저장됨 · 탭하여 변경"
        setOnPreferenceClickListener {
            val input = EditText(context).apply {
                this.inputType = inputType
                setSingleLine(true)
                setText(credentialVault.read(key).orEmpty())
                selectAll()
            }
            AlertDialog.Builder(context)
                .setTitle(titleText)
                .setView(input)
                .setPositiveButton("저장") { _, _ ->
                    val value = input.text?.toString().orEmpty()
                    credentialVault.write(key, value)
                    summary = if (value.isEmpty()) "설정되지 않음" else "저장됨 · 탭하여 변경"
                }
                .setNegativeButton("취소", null)
                .setNeutralButton("삭제") { _, _ ->
                    credentialVault.write(key, "")
                    summary = "설정되지 않음"
                }
                .show()
            true
        }
    }

    private fun testConnection() {
        Thread {
            val message = try {
                val root = rootUrl()
                checkTcpReachability(root)
                val response = client.newCall(propfindRequest(root, "0")).execute()
                response.use {
                    when (it.code) {
                        207, 200, 204 -> "WebDAV 연결 성공 (${it.code})"
                        401 -> "인증 실패 (401): 사용자 이름 또는 비밀번호를 확인하세요."
                        403 -> "접근 거부 (403): 서버 경로 또는 권한을 확인하세요."
                        404 -> "경로를 찾을 수 없습니다 (404). 기본 탐색 경로를 확인하세요."
                        else -> "연결 실패 (${it.code} ${it.message})"
                    }
                }
            } catch (e: Exception) {
                "연결 실패: ${e.javaClass.simpleName} · ${safeErrorMessage(e)}"
            }
            displayToast(message, android.widget.Toast.LENGTH_LONG)
        }.start()
    }

    /**
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

    override suspend fun getPopularAnime(page: Int): AnimesPage {
        val root = rootUrl()
        // Verify reachability when the source is opened, then expose the configured root folder.
        listDirectory(root)
        return AnimesPage(listOf(rootAnime(root)), false)
    }

    override suspend fun getLatestUpdates(page: Int): AnimesPage = getPopularAnime(page)

    override suspend fun getSearchAnime(page: Int, query: String, filters: AnimeFilterList): AnimesPage {
        if (query.isBlank()) return getPopularAnime(page)

        // Search is intentionally limited to the configured root's immediate children. Recursive
        // searching is expensive on large WebDAV trees and can be added as an explicit opt-in.
        val entries = listDirectory(rootUrl())
        val matches = entries.filter { it.name.contains(query, ignoreCase = true) }
            .map { entry ->
                if (entry.isCollection) directoryAnime(entry.url, entry.name)
                else fileSearchAnime(entry)
            }
        return AnimesPage(matches, false)
    }

    override suspend fun getAnimeDetails(anime: SAnime): SAnime {
        val url = anime.url.toHttpUrlOrNull() ?: throw IOException("잘못된 WebDAV 항목 주소입니다.")
        if (!isWithinRoot(url)) throw IOException("설정된 기본 경로 바깥의 항목은 열 수 없습니다.")
        if (!url.encodedPath.endsWith('/')) return anime.apply { initialized = true }

        val entries = listDirectory(url)
        val folderName = if (url == rootUrl()) "WebDAV" else displayName(url)
        val path = displayPath(url)
        return anime.apply {
            title = folderName
            description = buildString {
                append("경로: ").append(path)
                append("\n폴더: ").append(entries.count { it.isCollection })
                append(" · 영상: ").append(entries.count { !it.isCollection && isVideoFile(it.name) })
            }
            initialized = true
        }
    }

    override suspend fun getEpisodeList(anime: SAnime): List<SEpisode> {
        val url = anime.url.toHttpUrlOrNull() ?: throw IOException("잘못된 WebDAV 항목 주소입니다.")
        if (!isWithinRoot(url)) throw IOException("설정된 기본 경로 바깥의 항목은 열 수 없습니다.")
        val files = if (url.encodedPath.endsWith('/')) {
            listDirectory(url).filter { !it.isCollection && isVideoFile(it.name) }
        } else {
            val name = displayName(url)
            if (isVideoFile(name)) listOf(DavEntry(url, name, false, -1L, 0L, null)) else emptyList()
        }
        return sortEntries(files).mapIndexed { index, file ->
            SEpisode.create().apply {
                name = if (file.size >= 0L) "${file.name} · ${formatBytes(file.size)}" else file.name
                this.url = file.url.toString()
                episode_number = (index + 1).toFloat()
                date_upload = file.modified
            }
        }
    }

    override suspend fun getVideoList(episode: SEpisode): List<Video> {
        val url = episode.url.toHttpUrlOrNull() ?: throw IOException("잘못된 영상 주소입니다.")
        if (!isWithinRoot(url) || url.encodedPath.endsWith('/')) {
            throw IOException("영상 주소가 유효하지 않습니다.")
        }
        val headers = authHeaders()
        return listOf(
            Video(
                videoUrl = url.toString(),
                videoTitle = displayName(url),
                headers = headers.takeIf { it.size > 0 },
            ),
        )
    }

    /**
     * AniZen's current runtime has the extensions-lib v17 related-source navigation hook, while
     * this extension deliberately compiles against the repository's v16 ABI baseline. The JVM
     * erases List's generic argument, so these two methods intentionally match the runtime
     * method descriptors without importing a v17-only type into the v16 build.
     *
     * Returned relation instances are created from AniZen's runtime class loader, not duplicated
     * inside the extension APK.
     */
    @Suppress("unused")
    val supportsRelatedAnime: Boolean
        get() = true

    @Suppress("unused")
    suspend fun getRelatedAnimeList(anime: SAnime): List<Any> {
        val current = anime.url.toHttpUrlOrNull() ?: return emptyList()
        if (!isWithinRoot(current)) return emptyList()

        val entries = if (current.encodedPath.endsWith('/')) {
            runCatching { listDirectory(current) }.getOrDefault(emptyList())
        } else {
            emptyList()
        }
        val directories = entries.filter { it.isCollection }
            .sortedBy { it.name.lowercase() }
            .map { directoryAnime(it.url, it.name) }
            .toMutableList()

        parentDirectory(current)?.let { parent ->
            directories.add(0, directoryAnime(parent, "↑ 상위 폴더"))
        }

        if (directories.isEmpty()) return emptyList()
        return listOf(createRuntimeAnimeRelation("폴더", directories))
    }

    private fun createRuntimeAnimeRelation(name: String, animes: List<SAnime>): Any {
        val className = "eu.kanade.tachiyomi.animesource.model.AnimeRelation"
        val relationClass = SAnime::class.java.classLoader?.loadClass(className)
            ?: Class.forName(className)
        val constructor = relationClass.getConstructor(String::class.java, List::class.java)
        return constructor.newInstance(name, animes)
    }

    private fun rootAnime(root: HttpUrl): SAnime = SAnime.create().apply {
        url = root.toString()
        title = "WebDAV"
        description = "경로: ${displayPath(root)}"
        initialized = false
    }

    private fun directoryAnime(url: HttpUrl, titleText: String): SAnime = SAnime.create().apply {
        this.url = url.toString()
        title = titleText
        description = "경로: ${displayPath(url)}"
        initialized = false
    }

    private fun fileSearchAnime(entry: DavEntry): SAnime = SAnime.create().apply {
        url = entry.url.toString()
        title = entry.name
        description = if (entry.size >= 0) "${formatBytes(entry.size)} · ${displayPath(entry.url)}" else displayPath(entry.url)
        initialized = false
    }

    private fun listDirectory(url: HttpUrl): List<DavEntry> {
        val response = client.newCall(propfindRequest(url, "1")).execute()
        response.use {
            if (!it.isSuccessful) throw webDavHttpException(it.code, it.message)
            val body = it.body ?: throw IOException("WebDAV 서버가 빈 응답을 반환했습니다.")
            return WebDavXml.parse(body.byteStream(), url)
                .filterNot { entry -> sameResource(entry.url, url) }
                .filter { entry -> isWithinRoot(entry.url) }
        }
    }

    private fun propfindRequest(url: HttpUrl, depth: String): Request {
        val body = PROPFIND_BODY.toRequestBody("application/xml; charset=utf-8".toMediaType())
        return Request.Builder()
            .url(url)
            .method("PROPFIND", body)
            .header("Depth", depth)
            .header("Content-Type", "application/xml; charset=utf-8")
            .apply {
                authHeaders()["Authorization"]?.let { header("Authorization", it) }
            }
            .build()
    }

    private fun authHeaders(): Headers {
        val username = credentialVault.read(KEY_USERNAME).orEmpty()
        val password = credentialVault.read(KEY_PASSWORD).orEmpty()
        if (username.isEmpty() && password.isEmpty()) return Headers.Builder().build()
        val raw = "$username:$password".toByteArray(Charsets.UTF_8)
        val encoded = Base64.encodeToString(raw, Base64.NO_WRAP)
        return Headers.Builder().add("Authorization", "Basic $encoded").build()
    }

    private fun configuredServerUrl(): HttpUrl? {
        val raw = preferences.getString(KEY_SERVER_URL, DEFAULT_SERVER_URL)?.trim().orEmpty()
        val parsed = raw.toHttpUrlOrNull() ?: return null
        if (parsed.scheme != "http" && parsed.scheme != "https") return null
        if (parsed.username.isNotEmpty() || parsed.password.isNotEmpty()) return null
        if (parsed.query != null || parsed.fragment != null) return null
        return parsed
    }

    private fun rootUrl(): HttpUrl {
        val base = configuredServerUrl() ?: throw IOException("WebDAV 서버 주소가 올바르지 않습니다.")
        var builder = base.newBuilder()
            .encodedPath(base.encodedPath.trimEnd('/') + "/")
            .query(null)
            .fragment(null)
        val rootPath = preferences.getString(KEY_ROOT_PATH, "").orEmpty().trim()
        rootPath.split('/').filter { it.isNotBlank() && it != "." }.forEach { segment ->
            if (segment == "..") throw IOException("기본 탐색 경로에 '..'를 사용할 수 없습니다.")
            builder = builder.addPathSegment(segment)
        }
        val result = builder.build()
        return if (result.encodedPath.endsWith('/')) result else result.newBuilder().encodedPath(result.encodedPath + "/").build()
    }

    private fun isWithinRoot(url: HttpUrl): Boolean {
        val root = runCatching { rootUrl() }.getOrNull() ?: return false
        return url.scheme == root.scheme && url.host == root.host && url.port == root.port &&
            url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null &&
            url.encodedPath.startsWith(root.encodedPath)
    }

    private fun parentDirectory(url: HttpUrl): HttpUrl? {
        val root = rootUrl()
        if (!isWithinRoot(url) || sameResource(url, root)) return null
        val path = url.encodedPath.trimEnd('/')
        val parentPath = path.substringBeforeLast('/', "") + "/"
        val parent = url.newBuilder().encodedPath(if (parentPath.startsWith('/')) parentPath else "/$parentPath").build()
        return parent.takeIf { isWithinRoot(it) }
    }

    private fun displayName(url: HttpUrl): String {
        val last = url.encodedPath.trimEnd('/').substringAfterLast('/')
        return android.net.Uri.decode(last).ifBlank { "WebDAV" }
    }

    private fun displayPath(url: HttpUrl): String {
        val root = rootUrl()
        val relative = url.encodedPath.removePrefix(root.encodedPath).trim('/').split('/')
            .filter { it.isNotEmpty() }
            .joinToString("/") { android.net.Uri.decode(it) }
        return if (relative.isEmpty()) "/" else "/$relative"
    }

    private fun sameResource(a: HttpUrl, b: HttpUrl): Boolean =
        a.scheme == b.scheme && a.host == b.host && a.port == b.port &&
            a.encodedPath.trimEnd('/') == b.encodedPath.trimEnd('/')

    private fun sortEntries(entries: List<DavEntry>): List<DavEntry> {
        return when (preferences.getString(KEY_SORT_MODE, SORT_NAME_ASC)) {
            SORT_NAME_DESC -> entries.sortedByDescending { it.name.lowercase() }
            SORT_SIZE_DESC -> entries.sortedWith(compareByDescending<DavEntry> { it.size }.thenBy { it.name.lowercase() })
            SORT_SIZE_ASC -> entries.sortedWith(compareBy<DavEntry> { it.size }.thenBy { it.name.lowercase() })
            else -> entries.sortedBy { it.name.lowercase() }
        }
    }

    private fun webDavHttpException(code: Int, message: String): IOException = when (code) {
        401 -> IOException("WebDAV 인증 실패 (401). 사용자 이름과 비밀번호를 확인하세요.")
        403 -> IOException("WebDAV 접근 거부 (403). 서버 경로와 읽기 권한을 확인하세요.")
        404 -> IOException("WebDAV 경로를 찾을 수 없습니다 (404).")
        405 -> IOException("서버가 PROPFIND 메서드를 허용하지 않습니다 (405).")
        else -> IOException("WebDAV HTTP 오류: $code $message")
    }

    private fun safeErrorMessage(error: Exception): String {
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
    }

    private fun isValidServerUrl(value: String): Boolean {
        val url = value.trim().toHttpUrlOrNull() ?: return false
        return (url.scheme == "http" || url.scheme == "https") && url.host.isNotBlank() &&
            url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null
    }

    private fun isVideoFile(name: String): Boolean =
        VIDEO_EXTENSIONS.contains(name.substringAfterLast('.', "").lowercase())

    private fun formatBytes(bytes: Long): String {
        if (bytes < 0) return "크기 알 수 없음"
        if (bytes < 1024) return "$bytes B"
        val units = listOf("KB", "MB", "GB", "TB")
        var value = bytes.toDouble()
        var unit = -1
        do {
            value /= 1024.0
            unit++
        } while (value >= 1024.0 && unit < units.lastIndex)
        return String.format(java.util.Locale.US, "%.2f %s", value, units[unit])
    }


    companion object {
        const val DEFAULT_SERVER_URL = "http://192.168.0.10:8081"
        internal const val INSTANCE_COUNT_KEY = "webdav_instance_count"
        internal const val INSTANCE_COUNT_DEFAULT = "3"
        private val INSTANCE_COUNT_ENTRIES = (1..10).map { it.toString() }
        const val KEY_SERVER_URL = "webdav_server_url"
        const val KEY_USERNAME = "webdav_username_enc"
        const val KEY_PASSWORD = "webdav_password_enc"
        const val KEY_ROOT_PATH = "webdav_root_path"
        const val KEY_SORT_MODE = "webdav_sort_mode"

        const val SORT_NAME_ASC = "name_asc"
        const val SORT_NAME_DESC = "name_desc"
        const val SORT_SIZE_DESC = "size_desc"
        const val SORT_SIZE_ASC = "size_asc"

        val VIDEO_EXTENSIONS = setOf("mp4", "mkv", "avi", "mov", "m4v", "webm")

        val PROPFIND_BODY = """
            <?xml version="1.0" encoding="utf-8"?>
            <d:propfind xmlns:d="DAV:">
              <d:prop>
                <d:resourcetype />
                <d:getcontentlength />
                <d:getlastmodified />
                <d:getcontenttype />
              </d:prop>
            </d:propfind>
        """.trimIndent()
    }
}
