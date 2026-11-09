package eu.kanade.tachiyomi.animeextension.all.webdav.model

import okhttp3.HttpUrl

internal data class DavEntry(
    val url: HttpUrl,
    val name: String,
    val isCollection: Boolean,
    val size: Long,
    val modified: Long,
    val contentType: String?,
)
