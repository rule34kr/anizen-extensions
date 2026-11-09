package eu.kanade.tachiyomi.animeextension.all.webdav

import android.util.Xml
import org.xmlpull.v1.XmlPullParser
import java.io.IOException
import java.io.InputStream
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

internal data class NfoMetadata(
    val title: String? = null,
    val originalTitle: String? = null,
    val plot: String? = null,
    val outline: String? = null,
    val premiered: String? = null,
    val premieredMillis: Long? = null,
    val year: Int? = null,
    val genres: List<String> = emptyList(),
    val studio: String? = null,
    val status: String? = null,
    val season: Int? = null,
    val episode: Int? = null,
    val runtimeMinutes: Int? = null,
    val mpaa: String? = null,
    val rating: String? = null,
)

/** Minimal, defensive parser for Kodi/Jellyfin-compatible NFO sidecar metadata. */
internal object NfoXml {
    private val textTags = setOf(
        "title",
        "originaltitle",
        "plot",
        "outline",
        "premiered",
        "year",
        "genre",
        "studio",
        "status",
        "season",
        "episode",
        "runtime",
        "mpaa",
        "userrating",
    )

    fun parse(input: InputStream): NfoMetadata {
        val parser = Xml.newPullParser().apply {
            setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, true)
            setFeature("http://xmlpull.org/v1/doc/features.html#process-docdecl", false)
            setInput(input, "UTF-8")
        }

        val values = linkedMapOf<String, MutableList<String>>()
        var event = parser.eventType
        while (event != XmlPullParser.END_DOCUMENT) {
            when (event) {
                XmlPullParser.DOCDECL -> throw IOException("NFO XML에서 DOCTYPE 선언은 허용되지 않습니다.")
                XmlPullParser.START_TAG -> {
                    val tag = parser.name.substringAfterLast(':').lowercase(Locale.ROOT)
                    if (tag in textTags) {
                        val value = parser.nextText().trim()
                        if (value.isNotEmpty()) values.getOrPut(tag) { mutableListOf() }.add(value)
                    }
                }
            }
            event = parser.next()
        }

        fun first(tag: String): String? = values[tag]?.firstOrNull()
        fun number(tag: String): Int? = first(tag)?.let { raw ->
            Regex("-?\\d+").find(raw)?.value?.toIntOrNull()
        }
        val premiered = first("premiered")
        val genres = values["genre"].orEmpty().distinct()

        return NfoMetadata(
            title = first("title"),
            originalTitle = first("originaltitle"),
            plot = first("plot"),
            outline = first("outline"),
            premiered = premiered,
            premieredMillis = premiered?.let(::parseDate),
            year = number("year"),
            genres = genres,
            studio = first("studio"),
            status = first("status"),
            season = number("season"),
            episode = number("episode"),
            runtimeMinutes = number("runtime"),
            mpaa = first("mpaa"),
            rating = first("userrating"),
        )
    }

    private fun parseDate(value: String): Long? {
        val formats = listOf("yyyy-MM-dd", "yyyy-MM-dd'T'HH:mm:ss", "yyyy")
        for (pattern in formats) {
            try {
                val formatter = SimpleDateFormat(pattern, Locale.US).apply {
                    isLenient = false
                    timeZone = TimeZone.getTimeZone("UTC")
                }
                formatter.parse(value)?.let { return it.time }
            } catch (_: Exception) {
                // Try the next known NFO date representation.
            }
        }
        return null
    }
}
