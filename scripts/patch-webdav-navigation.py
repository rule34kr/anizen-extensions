#!/usr/bin/env python3
"""Patch WebDAV navigation, NFO episode metadata and asynchronous folder artwork."""
from pathlib import Path
import sys


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one {label} block; found {count}")
    return source.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch-webdav-navigation.py <upstream-root>")

    root = Path(sys.argv[1]).resolve()
    base = root / "src/all/webdav/src/eu/kanade/tachiyomi/animeextension/all/webdav"
    webdav_path = base / "WebDav.kt"
    nfo_path = base / "NfoXml.kt"
    xml_path = base / "net/WebDavXml.kt"
    for path in (webdav_path, nfo_path, xml_path):
        if not path.is_file():
            raise SystemExit(f"Required WebDAV source file is missing: {path}")

    source = webdav_path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        "import okhttp3.RequestBody.Companion.toRequestBody\n",
        """import okhttp3.RequestBody.Companion.toRequestBody
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
""",
        "coroutine and image executor imports",
    )

    source = replace_once(
        source,
        '    private val credentialVault by lazy { CredentialVault(context, "anizen_webdav_$id") }\n',
        """    private val credentialVault by lazy { CredentialVault(context, "anizen_webdav_$id") }
    private val folderCoverCache = ConcurrentHashMap<String, String>()
    private val folderCoverChecks = ConcurrentHashMap.newKeySet<String>()
    private val folderImageExecutor by lazy { Executors.newFixedThreadPool(4) }
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
                    when {
                        isDirectoryEntry(entry) -> enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                        isVideoFile(entry.name) -> enrichFileAnime(fileSearchAnime(entry), entry.url)
                        else -> null
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
                    if (isDirectoryEntry(entry)) {
                        enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                    } else {
                        enrichFileAnime(fileSearchAnime(entry), entry.url)
                    }
                }
            }.awaitAll()
        }
        return AnimesPage(matches, false)""",
        "parallel search item metadata",
    )

    source = replace_once(
        source,
        "        findFolderCover(url)?.let { anime.thumbnail_url = it }",
        "        applyFolderCoverFromEntries(anime, url, entries)",
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
            sortEntries(entries.filter(::isDirectoryEntry)).map { entry ->
                async(Dispatchers.IO) {
                    enrichDirectoryAnime(directoryAnime(entry.url, entry.name), entry.url)
                }
            }.awaitAll().toMutableList()
        }

        parentDirectory(current)?.let { parent ->""",
        "parallel related folder listing",
    )

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
        attachFolderCoverAsync(anime, url)
        return anime
    }

    private fun enrichFileAnime(anime: SAnime, url: HttpUrl): SAnime {
        applyNfoMetadata(anime, readFileNfo(url))
        val parentPath = url.encodedPath.substringBeforeLast('/') + "/"
        val parent = url.newBuilder().encodedPath(parentPath).build()
        attachFolderCoverAsync(anime, parent)
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

    private fun folderCoverCandidates(url: HttpUrl): List<String> =
        listOf("jpg", "png", "webp").map { extension ->
            url.newBuilder().addPathSegment("folder.$extension").build().toString()
        }

    private fun applyFolderCoverFromEntries(anime: SAnime, url: HttpUrl, entries: List<DavEntry>) {
        val cover = entries.firstOrNull {
            !it.isCollection && it.name.lowercase() in setOf("folder.jpg", "folder.png", "folder.webp")
        }?.url?.toString()
        if (cover != null) {
            folderCoverCache[url.toString()] = cover
            anime.thumbnail_url = cover
        } else {
            attachFolderCoverAsync(anime, url)
        }
    }

    private fun attachFolderCoverAsync(anime: SAnime, url: HttpUrl) {
        val key = url.toString()
        val cached = folderCoverCache[key]
        anime.thumbnail_url = cached ?: folderCoverCandidates(url).first()
        if (cached != null || !folderCoverChecks.add(key)) return

        folderImageExecutor.execute {
            try {
                val cover = runCatching {
                    listDirectory(url).firstOrNull {
                        !it.isCollection && it.name.lowercase() in setOf("folder.jpg", "folder.png", "folder.webp")
                    }?.url?.toString()
                }.getOrNull()
                if (cover != null) {
                    folderCoverCache[key] = cover
                    anime.thumbnail_url = cover
                }
            } finally {
                folderCoverChecks.remove(key)
            }
        }
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

    print("Patched WebDAV: nested collection detection, parallel NFO loading, non-blocking folder covers, and episode NFO fields.")


if __name__ == "__main__":
    main()
