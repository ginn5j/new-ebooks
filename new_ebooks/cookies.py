from __future__ import annotations


def cookie_dict(jar) -> dict:
    """Snapshot a cookie jar as a plain ``{name: value}`` dict.

    ``dict(jar)`` on a requests CookieJar goes through its mapping interface,
    which raises CookieConflictError when the same cookie name is set for two
    domains (e.g. overdrive.com and a library subdomain). Iterating the jar
    avoids the conflict check; for duplicate names the last cookie wins.
    """
    return {cookie.name: cookie.value for cookie in jar}
