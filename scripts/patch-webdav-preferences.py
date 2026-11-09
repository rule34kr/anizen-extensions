#!/usr/bin/env python3
"""Patch WebDAV's plain Preference construction for the pinned extension API.

The upstream compile-time Preference stub intentionally has no Context constructor.
At runtime AniZen supplies the real androidx.preference.Preference class, so the
Context constructor must be resolved reflectively (the same approach used by the
pinned upstream PreferenceFactory).
"""
from __future__ import annotations

from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: patch-webdav-preferences.py <upstream-checkout>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    candidates = list((root / "src" / "all" / "webdav" / "src").rglob("WebDav.kt"))
    if len(candidates) != 1:
        raise SystemExit(
            f"Expected exactly one WebDav.kt under src/all/webdav/src; found {len(candidates)}"
        )

    source = candidates[0]
    content = source.read_text(encoding="utf-8")

    helper_name = "newContextPreference"
    if helper_name in content:
        print(f"{source}: {helper_name} already present; nothing to do")
        return 0

    replacements = (
        (
            "Preference(screen.context).apply {",
            "newContextPreference(screen.context).apply {",
            "connection-test preference",
        ),
        (
            "): Preference = Preference(context).apply {",
            "): Preference = newContextPreference(context).apply {",
            "credential preference",
        ),
    )

    for old, new, label in replacements:
        count = content.count(old)
        if count != 1:
            raise SystemExit(
                f"Expected exactly one {label} constructor expression; found {count}"
            )
        content = content.replace(old, new, 1)

    marker = "    private fun secretPreference("
    if content.count(marker) != 1:
        raise SystemExit("Could not identify the secretPreference helper insertion point")

    helper = """    /**
     * Create a plain Preference using the host app's real AndroidX implementation.
     *
     * The extension compile-time stub deliberately omits Preference(Context), so
     * resolve the constructor reflectively just like the pinned upstream helper.
     */
    private fun newContextPreference(context: Context): Preference =
        runCatching {
            Preference::class.java
                .getConstructor(Context::class.java)
                .newInstance(context) as Preference
        }.getOrElse { error ->
            throw IllegalStateException(
                "The host app does not expose Preference(Context)",
                error,
            )
        }

"""
    content = content.replace(marker, helper + marker, 1)
    source.write_text(content, encoding="utf-8")
    print(f"Patched {source}: 2 Preference constructor calls now use reflection")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
