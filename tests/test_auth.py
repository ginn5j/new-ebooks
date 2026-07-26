import pytest
import requests

from new_ebooks import auth
from new_ebooks.auth import (
    KEYCHAIN_SERVICE,
    credential_key,
    get_stored_credentials,
    is_authenticated,
    login,
)


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, key):
        return self.store.get((service, key))

    def set_password(self, service, key, value):
        self.store[(service, key)] = value


class FakeResponse:
    def __init__(self, text: str = "", url: str = "", status_code: int = 200):
        self.text = text
        self.url = url
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    """Stands in for requests.Session; returns queued responses and records posts."""

    def __init__(self, get_responses: list, post_responses: list):
        self.get_responses = list(get_responses)
        self.post_responses = list(post_responses)
        self.posts: list[tuple[str, dict]] = []
        self.cookies = requests.cookies.RequestsCookieJar()

    def get(self, url, timeout=None) -> FakeResponse:
        return self.get_responses.pop(0)

    def post(self, url, data=None, timeout=None, allow_redirects=True) -> FakeResponse:
        self.posts.append((url, data))
        return self.post_responses.pop(0)


def test_credential_key_plain_and_consortial():
    assert credential_key("https://spl.overdrive.com/") == "https://spl.overdrive.com"
    assert (
        credential_key("https://consortium.overdrive.com", "Hamilton East")
        == "https://consortium.overdrive.com::Hamilton East"
    )


def test_get_stored_credentials_parses_card_and_pin(monkeypatch):
    kr = FakeKeyring()
    kr.set_password(KEYCHAIN_SERVICE, "https://spl.overdrive.com", "12345:9:99")
    monkeypatch.setattr(auth, "keyring", kr)
    # Only the first colon separates: the PIN may contain colons.
    assert get_stored_credentials("https://spl.overdrive.com") == ("12345", "9:99")


def test_get_stored_credentials_missing(monkeypatch):
    monkeypatch.setattr(auth, "keyring", FakeKeyring())
    assert get_stored_credentials("https://spl.overdrive.com") is None


def test_get_stored_credentials_malformed_secret(monkeypatch):
    kr = FakeKeyring()
    kr.set_password(KEYCHAIN_SERVICE, "https://spl.overdrive.com", "no-separator")
    monkeypatch.setattr(auth, "keyring", kr)
    assert get_stored_credentials("https://spl.overdrive.com") is None


def test_is_authenticated_normal_page():
    assert is_authenticated("<html><title>Search results</title><p>Books</p></html>")


def test_is_authenticated_false_on_password_form():
    html = '<html><form><input type="password" name="pin"></form></html>'
    assert is_authenticated(html) is False


def test_is_authenticated_false_on_signin_title():
    assert is_authenticated("<html><title>Sign In</title></html>") is False
    assert is_authenticated("<html><title>Library Login</title></html>") is False


LOGIN_FORM_PAGE = """<html><body>
<form action="/account/signin">
  <input type="hidden" name="csrf" value="tok123">
  <input type="text" name="username">
  <input type="password" name="password">
</form>
</body></html>"""


def test_login_submits_card_and_pin_with_hidden_fields():
    signin = FakeResponse(LOGIN_FORM_PAGE, url="https://spl.overdrive.com/account/oauthsignin")
    session = FakeSession([signin], [FakeResponse("<html>ok</html>")])
    session.cookies.set("session", "abc")

    cookies = login(session, "https://spl.overdrive.com", None, "12345", "9999")

    assert len(session.posts) == 1
    action, data = session.posts[0]
    # Relative form action is resolved against the signin page URL.
    assert action == "https://spl.overdrive.com/account/signin"
    assert data == {"csrf": "tok123", "username": "12345", "password": "9999"}
    assert cookies == {"session": "abc"}


MEMBER_SELECT_PAGE = """<html><body>
<form action="/account/selectlibrary">
  <input type="hidden" name="csrf" value="sel1">
  <select name="libraryId">
    <option value="">Choose your library</option>
    <option value="41">Fishers Library</option>
    <option value="42">Hamilton East Public Library</option>
    <option value="43">Other Library</option>
  </select>
</form>
</body></html>"""


def test_login_selects_member_library_then_signs_in():
    signin = FakeResponse(MEMBER_SELECT_PAGE, url="https://consortium.overdrive.com/account/oauthsignin")
    after_select = FakeResponse(LOGIN_FORM_PAGE, url="https://consortium.overdrive.com/account/signin")
    session = FakeSession([signin], [after_select, FakeResponse("<html>ok</html>")])

    login(session, "https://consortium.overdrive.com", "Hamilton East", "12345", "9999")

    assert len(session.posts) == 2
    select_action, select_data = session.posts[0]
    assert select_action == "https://consortium.overdrive.com/account/selectlibrary"
    assert select_data["csrf"] == "sel1"
    assert select_data["libraryId"] == "42"  # matched by name, submits the value
    _, login_data = session.posts[1]
    assert login_data["username"] == "12345"


def test_login_returns_cookies_on_overdrive_oauth_403():
    """A 403 from the overdrive.com OAuth callback is tolerated; the caller
    verifies the session by checking the next page instead."""
    signin = FakeResponse(LOGIN_FORM_PAGE, url="https://spl.overdrive.com/account/oauthsignin")
    forbidden = FakeResponse("", url="https://oauth.overdrive.com/callback", status_code=403)
    session = FakeSession([signin], [forbidden])
    session.cookies.set("session", "abc")

    cookies = login(session, "https://spl.overdrive.com", None, "12345", "9999")
    assert cookies == {"session": "abc"}


def test_login_reraises_non_overdrive_403():
    signin = FakeResponse(LOGIN_FORM_PAGE, url="https://spl.overdrive.com/account/oauthsignin")
    forbidden = FakeResponse("", url="https://other.example.com/callback", status_code=403)
    session = FakeSession([signin], [forbidden])

    with pytest.raises(requests.HTTPError):
        login(session, "https://spl.overdrive.com", None, "12345", "9999")


def test_login_raises_when_no_form_present():
    signin = FakeResponse("<html><body>No forms here</body></html>", url="https://spl.overdrive.com/account/oauthsignin")
    session = FakeSession([signin], [])
    with pytest.raises(RuntimeError, match="login form"):
        login(session, "https://spl.overdrive.com", None, "12345", "9999")
