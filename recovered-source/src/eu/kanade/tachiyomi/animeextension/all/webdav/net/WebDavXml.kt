package eu.kanade.tachiyomi.animeextension.all.webdav.net

import android.net.Uri
import android.util.Xml
import eu.kanade.tachiyomi.animeextension.all.webdav.model.DavEntry
import okhttp3.HttpUrl
import org.xmlpull.v1.XmlPullParser
import java.io.InputStream
import java.io.IOException
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/** Secure, streaming parser for a WebDAV 207 Multi-Status response. */
internal object WebDavXml {

    fun parse(input: InputStream, requestUrl: HttpUrl): List<DavEntry> {
        val parser = Xml.newPullParser().apply {
            setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, true)
            setFeature("http://xmlpull.org/v1/doc/features.html#process-docdecl", false)
            setInput(input, "UTF-8")
        }

        val result = ArrayList<DavEntry>()
        var current: EntryBuilder? = null
        var event = parser.eventType
        while (event != XmlPullParser.END_DOCUMENT) {
            when (event) {
                XmlPullParser.DOCDECL -> throw IOException("WebDAV XML에서 DOCTYPE 선언은 허용되지 않습니다.")
                XmlPullParser.START_TAG -> {
                    val tag = localName(parser.name)
                    if (tag == "response") {
                        current = EntryBuilder()
                    } else if (current != null) {
                        when (tag) {
                            "href" -> current.href = parser.nextText().trim()
                            "getcontentlength" -> current.size = parser.nextText().trim().toLongOrNull() ?: -1L
                            "getlastmodified" -> current.modified = parseHttpDate(parser.nextText().trim())
                            "getcontenttype" -> current.contentType = parser.nextText().trim().takeIf { it.isNotEmpty() }
                            "collection" -> current.isCollection = true
                        }
                    }
                }
                XmlPullParser.END_TAG -> {
                    if (localName(parser.name) == "response") {
                        current?.let { builder ->
                            resolveEntry(requestUrl, builder)?.let(result::add)
                        }
                        current = null
                    }
                }
            }
            event = parser.next()
        }
        return result
    }

    private fun resolveEntry(parent: HttpUrl, entry: EntryBuilder): DavEntry? {
        val href = entry.href.takeIf { it.isNotBlank() } ?: return null
        val resolved = parent.resolve(href) ?: return null
        // Do not allow a malicious or malformed Multi-Status response to introduce another host,
        // carry user-info, or smuggle query/fragment data into a resource URL.
        if (resolved.scheme != parent.scheme || resolved.host != parent.host || resolved.port != parent.port) return null
        if (resolved.username.isNotEmpty() || resolved.password.isNotEmpty()) return null
        if (resolved.query != null || resolved.fragment != null) return null

        val isDirectory = entry.isCollection || resolved.encodedPath.endsWith('/')
        val encodedPath = when {
            isDirectory && !resolved.encodedPath.endsWith('/') -> resolved.encodedPath + "/"
            !isDirectory && resolved.encodedPath.length > 1 -> resolved.encodedPath.trimEnd('/')
            else -> resolved.encodedPath
        }
        val normalized = resolved.newBuilder().encodedPath(encodedPath).build()
        val rawName = normalized.encodedPath.trimEnd('/').substringAfterLast('/')
        val name = Uri.decode(rawName).ifBlank { "/" }

        return DavEntry(
            url = normalized,
            name = name,
            isCollection = isDirectory,
            size = entry.size,
            modified = entry.modified,
            contentType = entry.contentType,
        )
    }

    private fun localName(name: String?): String =
        name.orEmpty().substringAfterLast(':').lowercase(Locale.ROOT)

    private fun parseHttpDate(value: String): Long {
        if (value.isBlank()) return 0L
        val formats = listOf(
            "EEE, dd MMM yyyy HH:mm:ss zzz",
            "EEEE, dd-MMM-yy HH:mm:ss zzz",
            "EEE MMM d HH:mm:ss yyyy",
        )
        for (pattern in formats) {
            try {
                val formatter = SimpleDateFormat(pattern, Locale.US).apply {
                    isLenient = false
                    timeZone = TimeZone.getTimeZone("GMT")
                }
                return formatter.parse(value)?.time ?: continue
            } catch (_: Exception) {
                // Try the next HTTP-date variant.
            }
        }
        return 0L
    }

    private class EntryBuilder {
        var href: String = ""
        var size: Long = -1L
        var modified: Long = 0L
        var contentType: String? = null
        var isCollection: Boolean = false
    }
}
