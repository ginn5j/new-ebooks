from __future__ import annotations
import getpass
import re
from typing import Optional

import keyring
import requests
from bs4 import BeautifulSoup

KEYCHAIN_SERVICE = "new-ebooks"


def credential_key(library_url: str, member_library: Optional[str] = None) -> str:
    library_url = library_url.rstrip("/")
    if member_library:
        return f"{library_url}::{member_library}"
    return library_url


def get_credentials(library_url: str, member_library: Optional[str] = None) -> tuple[str, str]:
    key = credential_key(library_url, member_library)
    secret = keyring.get_password(KEYCHAIN_SERVICE, key)
    if secret:
        parts = secret.split(":", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
    print(f"No stored credentials found for {key}.")
    card_number = input("Library card number: ").strip()
    pin = getpass.getpass("PIN: ").strip()
    keyring.set_password(KEYCHAIN_SERVICE, key, f"{card_number}:{pin}")
    return card_number, pin


def detect_consortium(session: requests.Session, library_url: str) -> Optional[list[str]]:
    library_url = library_url.rstrip("/")
    try:
        resp = session.get(f"{library_url}/account/oauthsignin", timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    # Look for a dropdown with many options (member library selector)
    for s in soup.find_all("select"):
        options = s.find_all("option")
        if len(options) > 3:
            names = [opt.get_text(strip=True) for opt in options if opt.get("value")]
            if len(names) > 1:
                return names
    return None


def login(
    session: requests.Session,
    library_url: str,
    member_library: Optional[str],
    card_number: str,
    pin: str,
) -> dict:
    library_url = library_url.rstrip("/")
    signin_url = f"{library_url}/account/oauthsignin"
    resp = session.get(signin_url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    if member_library:
        # Find and submit member library selection form
        select = None
        for s in soup.find_all("select"):
            options = s.find_all("option")
            for opt in options:
                if member_library.lower() in opt.get_text(strip=True).lower():
                    select = s
                    break
            if select:
                break

        if select:
            form = select.find_parent("form")
            if form:
                action = form.get("action", signin_url)
                if not action.startswith("http"):
                    from urllib.parse import urljoin
                    action = urljoin(library_url, action)
                # Find the matching option value
                target_value = None
                for opt in select.find_all("option"):
                    if member_library.lower() in opt.get_text(strip=True).lower():
                        target_value = opt.get("value")
                        break
                form_data = {inp.get("name"): inp.get("value", "") for inp in form.find_all("input") if inp.get("name")}
                if select.get("name") and target_value:
                    form_data[select.get("name")] = target_value
                resp = session.post(action, data=form_data, timeout=15)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

    # Find login form with card number + PIN fields
    login_form = None
    for form in soup.find_all("form"):
        inputs = form.find_all("input")
        input_names = [inp.get("name", "").lower() for inp in inputs]
        input_types = [inp.get("type", "").lower() for inp in inputs]
        if any(n for n in input_names if "card" in n or "barcode" in n or "user" in n or "name" in n or "login" in n):
            login_form = form
            break
        if "password" in input_types or "pin" in " ".join(input_names):
            login_form = form
            break

    if login_form is None:
        # Try the first form
        forms = soup.find_all("form")
        if forms:
            login_form = forms[0]

    if login_form is None:
        raise RuntimeError("Could not find login form on page")

    action = login_form.get("action", "")
    if not action.startswith("http"):
        from urllib.parse import urljoin
        action = urljoin(resp.url, action)

    form_data = {}
    for inp in login_form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text").lower()
        if itype == "hidden":
            form_data[name] = inp.get("value", "")
        elif itype in ("text", "email"):
            form_data[name] = card_number
        elif itype == "password":
            form_data[name] = pin
        else:
            form_data[name] = inp.get("value", "")

    try:
        resp = session.post(action, data=form_data, timeout=15, allow_redirects=True)
        resp.raise_for_status()
    except requests.HTTPError as e:
        # If the Overdrive OAuth callback returns 403 despite browser-like headers,
        # return whatever session cookies we have and let the caller verify by
        # checking whether the subsequent search page is authenticated.
        if e.response is not None and e.response.status_code == 403:
            from urllib.parse import urlparse
            host = urlparse(e.response.url).hostname or ""
            if "overdrive.com" in host:
                return dict(session.cookies)
        raise
    return dict(session.cookies)


def is_authenticated(html: str) -> bool:
    """Returns False if the page is a login redirect (session expired)."""
    soup = BeautifulSoup(html, "html.parser")
    # Check for common login page indicators
    for form in soup.find_all("form"):
        inputs = form.find_all("input")
        input_types = [inp.get("type", "").lower() for inp in inputs]
        if "password" in input_types:
            return False
    title = soup.find("title")
    if title:
        title_text = title.get_text(strip=True).lower()
        if "sign in" in title_text or "login" in title_text:
            return False
    return True
