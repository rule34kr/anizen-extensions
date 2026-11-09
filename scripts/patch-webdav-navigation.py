#!/usr/bin/env python3
"""Patch WebDAV navigation, NFO episode metadata and asynchronous folder artwork."""
from pathlib import Path
import sys
import re


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block; found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch-webdav-navigation.py <upstream-root>")

    root = Path(sys.argv[1]).resolve()
    base = root / "src/ko/webdav/src/eu/kanade/tachiyomi/animeextension/ko/webdav"
    webdav_path = base / "WebDav.kt"
    nfo_path = base / "NfoXml.kt"
    xml_path = base / "net/WebDavXml.kt"
    for path in (webdav_path, nfo_path, xml_path):
        if not path.is_file():
            raise SystemExit(f"Required WebDAV source file is missing: {path}")

    source = webdav_path.read_text(encoding="utf-8")

    # season.nfo is already a supported folder-NFO candidate in the base module.
    # Keep it first and unique so it takes precedence without duplicate requests.
    source, count = re.subn(
        r'(?m)^\s*val names = listOf\([^\n]*\)',
        '        val names = listOf("season.nfo", "tvshow.nfo", "movie.nfo", "folder.nfo")',
        source,
        count=1,
    )
    if count != 1:
        raise SystemExit("Could not normalize readFolderNfo candidates.")

    # Map only NFO values represented by AniZen's SAnime model.
    # Studio is not author, and season number is not a supported SAnime property.
    source = replace_once(
        source,
        """        metadata.title?.takeIf { it.isNotBlank() }?.let { anime.title = it }
        metadata.plot?.takeIf { it.isNotBlank() }?.let { anime.description = cleanPlot(it) }
        metadata.genres.takeIf { it.isNotEmpty() }?.let { anime.genre = it.joinToString(", ") }
        metadata.studio?.takeIf { it.isNotBlank() }?.let { anime.author = it }
        metadata.season?.let { anime.season_number = it.toDouble() }""",
        """        metadata.title?.takeIf { it.isNotBlank() }?.let { anime.title = it }
        metadata.plot?.takeIf { it.isNotBlank() }?.let { anime.description = cleanPlot(it) }
            ?: metadata.outline?.takeIf { it.isNotBlank() }?.let { anime.description = cleanPlot(it) }
        metadata.genres.takeIf { it.isNotEmpty() }?.let { anime.genre = it.joinToString(", ") }""",
        "AniZen-supported folder NFO metadata mapping",
    )

    source = replace_once(
        source,
        "import okhttp3.RequestBody.Companion.toRequestBody\n",
        """import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Headers
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import java.util.concurrent.ConcurrentHashMap
""",
        "coroutine and image executor imports",
    )

    source = replace_once(
        source,
        '    private val credentialVault by lazy { CredentialVault(context, "anizen_webdav_$id") }\n',
        """    private val credentialVault by lazy { CredentialVault(context, "anizen_webdav_$id") }
    private val folderCoverCache = ConcurrentHashMap<String, String>()
    private val folderCoverSemaphore = Semaphore(4)

    // AniZen uses source.headers when downloading thumbnail_url images.
    // Expose the same per-instance WebDAV authentication headers used by probes.
    override val headers: Headers
        get() = authHeaders()
""",
        "asynchronous folder image state",
    )

    source = replace_once(
        source,
        """        val entries = sortEntries(listDirectory(rootUrl()))
        val items = ArrayList<SAnime>(entries.size)
        for (entry in entries) {
            when {
                entry.isCollection -> items += enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                isVideoFile(entry.name) -> items += enrichFileAnime(fileSearchAnime(entry), entry.url)
            }
        }
        return AnimesPage(items, false)""",
        """        val entries = sortEntries(listDirectory(rootUrl()))
        val items = coroutineScope {
            entries.map { entry ->
                async(Dispatchers.IO) {
                    folderCoverSemaphore.withPermit {
                        when {
                            isDirectoryEntry(entry) -> enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                            isVideoFile(entry.name) -> enrichFileAnime(fileSearchAnime(entry), entry.url)
                            else -> null
                        }
                    }
                }
            }.awaitAll().filterNotNull()
        }
        return AnimesPage(items, false)""",
        "parallel root item metadata",
    )

    source = replace_once(
        source,
        """        val entries = listDirectory(rootUrl())
            .filter { it.name.contains(query, ignoreCase = true) && (it.isCollection || isVideoFile(it.name)) }
        val matches = ArrayList<SAnime>(entries.size)
        for (entry in sortEntries(entries)) {
            if (entry.isCollection) {
                matches += enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
            } else {
                matches += enrichFileAnime(fileSearchAnime(entry), entry.url)
            }
        }
        return AnimesPage(matches, false)""",
        """        val entries = listDirectory(rootUrl())
            .filter { it.name.contains(query, ignoreCase = true) && (isDirectoryEntry(it) || isVideoFile(it.name)) }
        val matches = coroutineScope {
            sortEntries(entries).map { entry ->
                async(Dispatchers.IO) {
                    folderCoverSemaphore.withPermit {
                        if (isDirectoryEntry(entry)) {
                            enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                        } else {
                            enrichFileAnime(fileSearchAnime(entry), entry.url)
                        }
                    }
                }
            }.awaitAll()
        }
        return AnimesPage(matches, false)""",
        "parallel search item metadata",
    )

    source = replace_once(
        source,
        """        val metadata = readFolderNfo(url)
        applyNfoMetadata(anime, metadata)
        findFolderCover(url)?.let { anime.thumbnail_url = it }
        val path = displayPath(url)""",
        """        val metadata = readFolderNfo(url)
        applyNfoMetadata(anime, metadata)
        // Folder progress is always completed; ignore any status value supplied by NFO.
        anime.status = SAnime.COMPLETED
        attachDirectoryCover(anime, url)
        val path = displayPath(url)""",
        "folder detail cover from existing listing",
    )

    source = replace_once(
        source,
        """        val sortedFiles = sortEntries(files)
        val episodes = ArrayList<SEpisode>(sortedFiles.size)
        for ((index, file) in sortedFiles.withIndex()) {
            val metadata = readFileNfo(file.url)
            val episodeNumber = metadata?.episode ?: (index + 1)
            val displayTitle = metadata?.title?.takeIf { it.isNotBlank() } ?: file.name
            val episodeName = if (metadata?.season != null && metadata.episode != null) {
                "S${metadata.season.toString().padStart(2, '0')}E${metadata.episode.toString().padStart(2, '0')} - $displayTitle"
            } else {
                displayTitle
            }
            episodes += SEpisode.create().apply {
                name = if (file.size >= 0L) "$episodeName · ${formatBytes(file.size)}" else episodeName
                this.url = file.url.toString()
                episode_number = episodeNumber.toFloat()
                summary = metadata?.plot?.let(::cleanPlot) ?: metadata?.outline?.let(::cleanPlot)
                date_upload = metadata?.premieredMillis ?: file.modified
            }
        }
        return episodes""",
        """        val sortedFiles = sortEntries(files)
        return coroutineScope {
            sortedFiles.mapIndexed { index, file ->
                async(Dispatchers.IO) {
                    val metadata = readFileNfo(file.url)
                    val seasonNumber = metadata?.season ?: metadata?.displaySeason
                    val episodeNumber = metadata?.episode ?: metadata?.displayEpisode ?: (index + 1)
                    val displayTitle = metadata?.title?.takeIf { it.isNotBlank() } ?: file.name
                    val episodeName = if (seasonNumber != null && (metadata?.episode != null || metadata?.displayEpisode != null)) {
                        "S${seasonNumber.toString().padStart(2, '0')}E${episodeNumber.toString().padStart(2, '0')} - $displayTitle"
                    } else {
                        displayTitle
                    }
                    SEpisode.create().apply {
                        name = if (file.size >= 0L) "$episodeName · ${formatBytes(file.size)}" else episodeName
                        this.url = file.url.toString()
                        episode_number = episodeNumber.toFloat()
                        summary = metadata?.plot?.takeIf { it.isNotBlank() }?.let(::cleanPlot)
                            ?: metadata?.outline?.takeIf { it.isNotBlank() }?.let(::cleanPlot)
                        date_upload = metadata?.premieredMillis ?: file.modified
                    }
                }
            }.awaitAll()
        }""",
        "parallel episode NFO loading",
    )


    source = replace_once(
        source,
        """        val directories = ArrayList<SAnime>()
        for (entry in sortEntries(entries.filter { it.isCollection })) {
            directories += enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
        }

        parentDirectory(current)?.let { parent ->""",
        """        val directories = coroutineScope {
            sortEntries(entries.filter(::isDirectoryEntry).filterNot {
                it.name.equals("theme-music", ignoreCase = true)
            }).map { entry ->
                async(Dispatchers.IO) {
                    enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                }
            }.awaitAll().toMutableList()
        }

        parentDirectory(current)?.let { parent ->""",
        "parallel related folder listing",
    )

    # Recommendation is a list of the current folder's contents, not a breadcrumb.
    # Do not inject the immediate parent directory as a related/recommended item.
    source, parent_count = re.subn(
        r"(?ms)^[ \t]*parentDirectory\(current\)\?\.let \{ parent ->\n.*?^[ \t]*\}\s*\n",
        "\n",
        source,
        count=1,
    )
    if parent_count != 1:
        raise SystemExit(f"Expected exactly one immediate-parent Recommendation block; found {parent_count}")

    source = replace_once(
        source,
        """    private fun directoryAnime(url: HttpUrl, titleText: String): SAnime = SAnime.create().apply {
        this.url = url.toString()
        title = titleText
        description = "경로: ${displayPath(url)}"
        initialized = false
    }""",
        """    private fun directoryAnime(url: HttpUrl, titleText: String): SAnime = SAnime.create().apply {
        val directoryUrl = if (url.encodedPath.endsWith('/')) url else {
            url.newBuilder().encodedPath(url.encodedPath + "/").build()
        }
        this.url = directoryUrl.toString()
        title = titleText
        status = SAnime.COMPLETED
        description = "경로: ${displayPath(directoryUrl)}"
        initialized = false
    }""",
        "directory URL normalization",
    )

    source = replace_once(
        source,
        """    private fun enrichDirectoryAnime(anime: SAnime, url: HttpUrl): SAnime {
        applyNfoMetadata(anime, readFolderNfo(url))
        findFolderCover(url)?.let { anime.thumbnail_url = it }
        return anime
    }

    private fun enrichFileAnime(anime: SAnime, url: HttpUrl): SAnime {
        applyNfoMetadata(anime, readFileNfo(url))
        val parentPath = url.encodedPath.substringBeforeLast('/') + "/"
        val parent = url.newBuilder().encodedPath(parentPath).build()
        findFolderCover(parent)?.let { anime.thumbnail_url = it }
        return anime
    }""",
        """    private fun enrichDirectoryAnime(anime: SAnime, url: HttpUrl): SAnime {
        applyNfoMetadata(anime, readFolderNfo(url))
        // Folder progress is always completed; NFO status must never override it.
        anime.status = SAnime.COMPLETED
        attachDirectoryCover(anime, url)
        return anime
    }

    private fun enrichFileAnime(anime: SAnime, url: HttpUrl): SAnime {
        applyNfoMetadata(anime, readFileNfo(url))
        val parentPath = url.encodedPath.substringBeforeLast('/') + "/"
        val parent = url.newBuilder().encodedPath(parentPath).build()
        attachFolderCover(anime, parent)
        return anime
    }

    private fun isDirectoryEntry(entry: DavEntry): Boolean {
        val contentType = entry.contentType?.substringBefore(';')?.trim()?.lowercase()
        return entry.isCollection ||
            entry.url.encodedPath.endsWith('/') ||
            contentType == "httpd/unix-directory" ||
            contentType == "inode/directory" ||
            contentType?.endsWith("/directory") == true
    }

    // A 404 is conclusive. Unsupported HEAD methods fall back to a ranged GET;
    // transient server/network failures are retried instead of being cached as no cover.
    private fun probeFolderImage(candidate: HttpUrl): Boolean {
        repeat(3) { attempt ->
            try {
                val headRequest = Request.Builder()
                    .url(candidate)
                    .headers(authHeaders())
                    .head()
                    .build()
                val headCode = client.newCall(headRequest).execute().use { response ->
                    when {
                        response.isSuccessful -> return true
                        response.code == 404 -> return false
                        response.code == 401 || response.code == 403 -> return false
                        else -> response.code
                    }
                }

                // 405/501 means HEAD is unsupported; for other non-404 responses,
                // a ranged GET also handles WebDAV servers with unusual HEAD behavior.
                val getRequest = Request.Builder()
                    .url(candidate)
                    .headers(authHeaders())
                    .header("Range", "bytes=0-0")
                    .get()
                    .build()
                val getCode = client.newCall(getRequest).execute().use { response ->
                    when {
                        response.isSuccessful -> return true
                        response.code == 404 -> return false
                        response.code == 401 || response.code == 403 -> return false
                        else -> response.code
                    }
                }
                if (headCode !in 500..599 && getCode !in 500..599 && getCode != 429) return false
            } catch (_: Exception) {
                // Retry below; an I/O error is not evidence that the image is absent.
            }
            if (attempt < 2) {
                try {
                    Thread.sleep(200L * (attempt + 1))
                } catch (_: InterruptedException) {
                    Thread.currentThread().interrupt()
                    return false
                }
            }
        }
        return false
    }

    private fun resolveDirectoryCover(url: HttpUrl): String? {
        val key = url.toString()
        folderCoverCache[key]?.let { return it }

        val directoryName = url.pathSegments.lastOrNull { it.isNotEmpty() }.orEmpty()
        val seasonNumber = Regex("^season[\\\\s._-]*0*(\\\\d+)$", RegexOption.IGNORE_CASE)
            .matchEntire(directoryName)?.groupValues?.getOrNull(1)?.toIntOrNull()

        val siblingPosterBaseName = when {
            seasonNumber == null -> null
            seasonNumber == 0 -> "season-specials-poster"
            else -> "season${seasonNumber.toString().padStart(2, '0')}-poster"
        }

        // Probe the exact candidate URLs with the authenticated WebDAV client.
        // Relying on PROPFIND entry names can fail on servers that return encoded
        // hrefs or incomplete directory listings. HEAD is preferred; GET with a
        // one-byte range is used when the server does not support HEAD.
        fun findImage(baseUrl: HttpUrl, baseName: String): String? {
            val extensions = listOf(
                "jpg", "jpeg", "png", "webp", "avif", "heic", "heif",
                "jxl", "gif", "bmp", "tif", "tiff",
            )
            for (extension in extensions) {
                val candidate = baseUrl.newBuilder()
                    .addPathSegment("$baseName.$extension")
                    .build()
                if (probeFolderImage(candidate)) return candidate.toString()
            }
            return null
        }

        // Season artwork is stored beside the season directory, in its parent.
        val encodedPath = url.encodedPath.trimEnd('/')
        val parentPath = encodedPath.substringBeforeLast('/', "").let {
            if (it.isEmpty()) "/" else "$it/"
        }
        val parentUrl = url.newBuilder().encodedPath(parentPath).build()

        val siblingPoster = siblingPosterBaseName?.let { baseName ->
            findImage(parentUrl, baseName)
        }

        // folder.jpg (or another supported extension) is also a sibling of the
        // season directory, and is used only when its dedicated poster is absent.
        val parentFolderCover = if (siblingPoster == null) {
            findImage(parentUrl, "folder")
        } else {
            null
        }

        val cover = siblingPoster ?: parentFolderCover
        if (cover != null) folderCoverCache[key] = cover
        return cover
    }

    private fun resolveCurrentFolderImage(url: HttpUrl): String? {
        val key = "folder:$url"
        folderCoverCache[key]?.let { return it }

        // Movie and 같이보기 artwork belongs to the directory itself, not its parent.
        // Probe common image extensions because PROPFIND listings can omit or encode names.
        for (extension in listOf(
            "jpg", "jpeg", "png", "webp", "avif", "heic", "heif",
            "jxl", "gif", "bmp", "tif", "tiff",
        )) {
            val candidate = url.newBuilder()
                .addPathSegment("folder.$extension")
                .build()
            if (probeFolderImage(candidate)) {
                folderCoverCache[key] = candidate.toString()
                return candidate.toString()
            }
        }
        return null
    }

    // These categories store artwork inside each folder itself.
    // Keep the existing season-parent poster logic for animation and all other paths.
    private fun usesCurrentFolderArtwork(url: HttpUrl): Boolean {
        val artworkCategories = setOf("영화", "같이보기", "반찬", "야동")
        return url.pathSegments.any { segment ->
            artworkCategories.any { it.equals(segment, ignoreCase = true) }
        }
    }

    private fun attachFolderCover(anime: SAnime, url: HttpUrl) {
        val cover = if (usesCurrentFolderArtwork(url)) {
            resolveCurrentFolderImage(url)
        } else {
            resolveDirectoryCover(url)
        }
        cover?.let { anime.thumbnail_url = it }
    }

    private fun attachDirectoryCover(anime: SAnime, url: HttpUrl) {
        val cover = if (usesCurrentFolderArtwork(url)) {
            resolveCurrentFolderImage(url)
        } else {
            resolveDirectoryCover(url)
        }
        cover?.let { anime.thumbnail_url = it }
    }""",
        "asynchronous folder cover discovery",
    )

    source = replace_once(
        source,
        """        val candidates = listOf(
            parent.newBuilder().addPathSegment("$baseName.nfo").build(),
            parent.newBuilder().addPathSegment("movie.nfo").build(),
        )""",
        """        val candidates = listOf(
            parent.newBuilder().addPathSegment("$fileName.nfo").build(),
            parent.newBuilder().addPathSegment("$baseName.nfo").build(),
            parent.newBuilder().addPathSegment("episode.nfo").build(),
            parent.newBuilder().addPathSegment("movie.nfo").build(),
        ).distinct()""",
        "episode NFO candidate names",
    )

    source = replace_once(
        source,
        """    private fun findFolderCover(url: HttpUrl): String? {
        for (extension in listOf("jpg", "png", "webp")) {
            val candidate = url.newBuilder().addPathSegment("folder.$extension").build()
            val exists = try {
                val request = Request.Builder().url(candidate).headers(authHeaders()).head().build()
                client.newCall(request).execute().use { it.isSuccessful }
            } catch (_: Exception) {
                false
            }
            if (exists) return candidate.toString()
        }
        return null
    }

""",
        "",
        "remove blocking folder image HEAD requests",
    )

    webdav_path.write_text(source, encoding="utf-8")

    nfo = nfo_path.read_text(encoding="utf-8")
    # Do not even ingest the NFO <status> tag. Folder status is controlled only
    # by the extension default (SAnime.COMPLETED), never by server-side NFO data.
    nfo = re.sub(r'(?m)^[ \\t]*"status",[ \\t]*\\n', "", nfo)
    old_parser_loop = "\n".join([
        "        while (event != XmlPullParser.END_DOCUMENT) {",
        "            when (event) {",
        "                XmlPullParser.DOCDECL -> throw IOException(\"NFO XML에서 DOCTYPE 선언은 허용되지 않습니다.\")",
        "                XmlPullParser.START_TAG -> {",
        "                    val tag = parser.name.substringAfterLast(':').lowercase(Locale.ROOT)",
        "                    if (tag in textTags) {",
        "                        val value = parser.nextText().trim()",
        "                        if (value.isNotEmpty()) values.getOrPut(tag) { mutableListOf() }.add(value)",
        "                    }",
        "                }",
        "            }",
        "            event = parser.next()",
        "        }",
    ])
    new_parser_loop = "\n".join([
        "        while (event != XmlPullParser.END_DOCUMENT) {",
        "            when (event) {",
        "                XmlPullParser.DOCDECL -> throw IOException(\"NFO XML에서 DOCTYPE 선언은 허용되지 않습니다.\")",
        "                XmlPullParser.START_TAG -> {",
        "                    val tag = parser.name.substringAfterLast(':').lowercase(Locale.ROOT)",
        "                    if (tag in textTags) {",
        "                        val valueEvent = parser.next()",
        "                        if (valueEvent == XmlPullParser.TEXT || valueEvent == XmlPullParser.CDSECT) {",
        "                            val value = parser.text.trim()",
        "                            if (value.isNotEmpty()) values.getOrPut(tag) { mutableListOf() }.add(value)",
        "                            event = parser.next()",
        "                        } else {",
        "                            // The <season> root can be a container; continue parsing its child tags.",
        "                            event = valueEvent",
        "                        }",
        "                        continue",
        "                    }",
        "                }",
        "            }",
        "            event = parser.next()",
        "        }",
    ])
    nfo = replace_once(nfo, old_parser_loop, new_parser_loop, "NFO container and leaf tag parsing")
    nfo = replace_once(
        nfo,
        "    val episode: Int? = null,\n    val runtimeMinutes: Int? = null,",
        "    val episode: Int? = null,\n    val displaySeason: Int? = null,\n    val displayEpisode: Int? = null,\n    val runtimeMinutes: Int? = null,",
        "NFO display season and episode fields",
    )
    nfo = replace_once(
        nfo,
        '        "episode",\n        "runtime",',
        '        "episode",\n        "displayseason",\n        "displayepisode",\n        "aired",\n        "runtime",',
        "NFO episode tags",
    )
    nfo = replace_once(
        nfo,
        '        val premiered = first("premiered")',
        '        val premiered = first("premiered") ?: first("aired")',
        "episode aired date fallback",
    )
    nfo = replace_once(
        nfo,
        '            episode = number("episode"),\n            runtimeMinutes = number("runtime"),',
        '            episode = number("episode"),\n            displaySeason = number("displayseason"),\n            displayEpisode = number("displayepisode"),\n            runtimeMinutes = number("runtime"),',
        "NFO episode number mapping",
    )
    nfo_path.write_text(nfo, encoding="utf-8")

    xml = xml_path.read_text(encoding="utf-8")
    xml = replace_once(
        xml,
        '        val isDirectory = entry.isCollection || resolved.encodedPath.endsWith(\'/\')',
        '''        val contentType = entry.contentType?.substringBefore(';')?.trim()?.lowercase()
        val isDirectory = entry.isCollection ||
            resolved.encodedPath.endsWith('/') ||
            contentType == "httpd/unix-directory" ||
            contentType == "inode/directory" ||
            contentType?.endsWith("/directory") == true''',
        "WebDAV directory resource type detection",
    )
    xml_path.write_text(xml, encoding="utf-8")

    print("Patched WebDAV: nested collection detection, season-container NFO parsing, synchronous multi-format folder covers, and episode NFO fields.")


if __name__ == "__main__":
    main()
