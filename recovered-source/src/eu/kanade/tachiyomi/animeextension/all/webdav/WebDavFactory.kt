package eu.kanade.tachiyomi.animeextension.all.webdav

import eu.kanade.tachiyomi.animesource.AnimeSource
import eu.kanade.tachiyomi.animesource.AnimeSourceFactory

@Suppress("unused")
class WebDavFactory : AnimeSourceFactory {
    override fun createSources(): List<AnimeSource> {
        val firstWebDav = WebDav("1")
        val instanceCount = firstWebDav.preferences
            .getString(WebDav.INSTANCE_COUNT_KEY, WebDav.INSTANCE_COUNT_DEFAULT)!!
            .toIntOrNull()
            ?.coerceIn(1, 10)
            ?: WebDav.INSTANCE_COUNT_DEFAULT.toInt()

        return buildList(instanceCount) {
            add(firstWebDav)
            for (i in 2..instanceCount) {
                add(WebDav(i.toString()))
            }
        }
    }
}
