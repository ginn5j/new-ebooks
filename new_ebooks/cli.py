from __future__ import annotations
import argparse
import os
import sys
import time
import tempfile
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Optional

import requests

from new_ebooks.config import (
    DEFAULT_CONFIG_PATH,
    EmailConfig,
    LibraryConfig,
    Config,
    load_config,
    save_config,
)
from new_ebooks.state import (
    DEFAULT_STATE_PATH,
    EBookState,
    LibraryState,
    State,
    load_state,
    save_state,
)
from new_ebooks.scraper import EBook, build_search_url, parse_page
from new_ebooks.auth import (
    get_credentials,
    get_stored_credentials,
    login,
    is_authenticated,
)
import new_ebooks.cloudlibrary as cl
from new_ebooks.checker import check_for_new_ebooks
from new_ebooks.renderer import (
    format_date,
    page_heading,
    render_html,
    render_email_html,
    write_and_open,
)
from new_ebooks.emailer import get_smtp_password, send_email


def _make_session(cookies: dict) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
    })
    for k, v in cookies.items():
        session.cookies.set(k, v)
    return session


def _fetch_with_auth(
    session: requests.Session,
    lib_config: LibraryConfig,
    lib_state: LibraryState,
    delay: float = 0.0,
) -> callable:
    is_cloudlibrary = lib_config.provider == "cloudlibrary"

    extra_headers = {"Accept": "application/json"} if is_cloudlibrary else {}

    def fetcher(url: str) -> str:
        if delay:
            time.sleep(delay)
        try:
            resp = session.get(url, timeout=30, headers=extra_headers)
        except requests.exceptions.Timeout:
            print("Request timed out; re-authenticating and retrying...", file=sys.stderr)
            try:
                if is_cloudlibrary:
                    new_cookies = cl.init_session(session, lib_config.library_base_url)
                else:
                    creds = get_stored_credentials(lib_config.library_base_url, lib_config.member_library)
                    if creds:
                        card_number, pin = creds
                        new_cookies = login(session, lib_config.library_base_url, lib_config.member_library, card_number, pin)
                    else:
                        new_cookies = None
                if new_cookies is not None:
                    lib_state.session_cookies = new_cookies
            except Exception as auth_e:
                print(f"Re-authentication failed: {auth_e}", file=sys.stderr)
            resp = session.get(url, timeout=60, headers=extra_headers)
        resp.raise_for_status()
        text = resp.text
        auth_check = cl.is_authenticated if is_cloudlibrary else is_authenticated
        if not auth_check(text):
            print("Session expired. Re-authenticating...")
            try:
                if is_cloudlibrary:
                    new_cookies = cl.init_session(session, lib_config.library_base_url)
                else:
                    card_number, pin = get_credentials(lib_config.library_base_url, lib_config.member_library)
                    new_cookies = login(session, lib_config.library_base_url, lib_config.member_library, card_number, pin)
                lib_state.session_cookies = new_cookies
            except Exception as e:
                raise RuntimeError(f"session expired and re-authentication failed: {e}") from e
            resp = session.get(url, timeout=30, headers=extra_headers)
            resp.raise_for_status()
            text = resp.text
            # Returning an unauthenticated page would be misread downstream
            # as "no books on this page" — fail loudly instead.
            if not auth_check(text):
                raise RuntimeError("session expired and re-authentication did not restore access")
        return text
    return fetcher


def _provider_tools(lib_config: LibraryConfig) -> tuple[callable, callable]:
    """Return (url_builder, page_parser) for the library's provider.

    The configured language filter is bound into the url_builder so the
    checker's url_builder(base_url, format, page) call is unchanged.
    """
    language = lib_config.language
    if lib_config.provider == "cloudlibrary":
        return (
            partial(cl.build_search_url, language=language),
            partial(cl.parse_page, library_base_url=lib_config.library_base_url),
        )
    return partial(build_search_url, language=language), parse_page


def _default_language(provider: str) -> str:
    """The language token matching each provider's current default behavior."""
    return "all" if provider == "overdrive" else "english"


def _normalize_language(value: str) -> Optional[str]:
    """Parse user input into a stored token, or None if unrecognized."""
    v = value.strip().lower()
    if v in ("all", "none", ""):
        return "all"
    if v in ("english", "en", "eng"):
        return "english"
    return None


def _prompt_language(provider: str, current: Optional[str] = None) -> Optional[str]:
    """Prompt for a language filter. Returns the token, or None on bad input."""
    default = current if current is not None else _default_language(provider)
    raw = input(f"Language filter (all/english) [{default}]: ").strip() or default
    return _normalize_language(raw)


def _parse_formats(raw: str) -> list[str]:
    """Parse a comma-separated format list, trimming blanks and duplicates."""
    formats: list[str] = []
    for part in raw.split(","):
        fmt = part.strip()
        if fmt and fmt not in formats:
            formats.append(fmt)
    return formats


def _format_hint(provider: str) -> str:
    """A short example of valid formats for the provider, including audiobooks."""
    if provider == "cloudlibrary":
        return "ebook, audiobook"
    return "ebook-epub-adobe, ebook-kindle, audiobook"


def _prompt_formats(provider: str, current: Optional[list[str]] = None) -> list[str]:
    """Prompt for one or more comma-separated formats. Returns the parsed list."""
    if current:
        default = ", ".join(current)
    elif provider == "cloudlibrary":
        default = "ebook"
    else:
        default = "ebook-epub-adobe"
    raw = input(
        f"Formats (comma-separated, e.g. {_format_hint(provider)}) [{default}]: "
    ).strip() or default
    return _parse_formats(raw)


def _ebook_to_state(book: EBook) -> EBookState:
    return EBookState(
        overdrive_id=book.overdrive_id,
        reserve_id=book.reserve_id,
        title=book.title,
        first_creator_name=book.first_creator_name,
    )


def cmd_init(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    state_path = Path(args.state)
    config = load_config(config_path)
    state = load_state(state_path) or State()

    print("=== New eBooks — Initialize Library ===")
    name = input("Library name (e.g. 'Seattle Public Library'): ").strip()
    if not name:
        print("Name cannot be empty.", file=sys.stderr)
        return 1

    library_url = input("Base URL (e.g. https://spl.overdrive.com): ").strip().rstrip("/")
    if not library_url:
        print("URL cannot be empty.", file=sys.stderr)
        return 1

    provider_input = input("Provider (overdrive/cloudlibrary) [overdrive]: ").strip().lower() or "overdrive"
    if provider_input not in ("overdrive", "cloudlibrary"):
        print("Unknown provider. Use 'overdrive' or 'cloudlibrary'.", file=sys.stderr)
        return 1

    formats = _prompt_formats(provider_input)
    if not formats:
        print("At least one format is required.", file=sys.stderr)
        return 1

    language = _prompt_language(provider_input)
    if language is None:
        print("Unknown language filter. Use 'all' or 'english'.", file=sys.stderr)
        return 1

    delay_str = input("Request delay seconds [1.0]: ").strip() or "1.0"
    try:
        delay = float(delay_str)
    except ValueError:
        delay = 1.0

    # Check if library is already configured
    for lib in config.libraries:
        if lib.library_base_url == library_url:
            print(f"Library '{library_url}' is already configured.", file=sys.stderr)
            return 1

    member_library = None
    if provider_input == "overdrive":
        is_consortium = input("Is this a consortial Overdrive site? (y/n) [n]: ").strip().lower()
        if is_consortium == "y":
            member_library = input("Member library name (as it appears on the sign-in page): ").strip()
            if not member_library:
                print("Member library name cannot be empty.", file=sys.stderr)
                return 1

    session = _make_session({})

    lib_config = LibraryConfig(
        name=name,
        library_base_url=library_url,
        formats=formats,
        request_delay_seconds=delay,
        member_library=member_library,
        provider=provider_input,
        language=language,
    )

    print("Authenticating...")
    cookies: dict = {}
    try:
        if provider_input == "cloudlibrary":
            cookies = cl.init_session(session, library_url)
        else:
            card_number, pin = get_credentials(library_url, member_library)
            cookies = login(session, library_url, member_library, card_number, pin)
    except Exception as e:
        print(f"Authentication failed: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    lib_state = LibraryState(session_cookies=cookies)
    fetcher = _fetch_with_auth(session, lib_config, lib_state, delay=0.0)
    _url_builder, _page_parser = _provider_tools(lib_config)

    # Fetch page 1 of each format to establish that format's anchor
    print("Fetching first page of each format to establish anchors...")
    for fmt in formats:
        search_url = _url_builder(library_url, fmt, 1)
        try:
            html = fetcher(search_url)
        except Exception as e:
            print(f"Failed to fetch library page for format '{fmt}': {e}", file=sys.stderr)
            return 1

        books = _page_parser(html)
        if not books:
            print(f"No books found for format '{fmt}'. Check the URL and format.", file=sys.stderr)
            return 1

        anchor = books[0]
        lib_state.anchors[fmt] = _ebook_to_state(anchor)
        print(f"  {fmt}: tracking from \"{anchor.title}\" by {anchor.first_creator_name}")

    lib_state.last_checked = datetime.now(timezone.utc).isoformat()

    config.libraries.append(lib_config)
    state.libraries[library_url] = lib_state

    save_config(config, config_path)
    save_state(state, state_path, config.max_state_backups)

    print("\nInitialized. Run 'new-ebooks check' to see new additions.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    state_path = Path(args.state)
    config = load_config(config_path)
    state = load_state(state_path) or State()

    if not config.libraries:
        print("No libraries configured. Run 'new-ebooks init' first.", file=sys.stderr)
        return 1

    # Select libraries
    if args.library:
        libs = [lib for lib in config.libraries if lib.name == args.library]
        if not libs:
            print(f"Library '{args.library}' not found.", file=sys.stderr)
            return 1
    else:
        libs = config.libraries

    exit_code = 0
    for lib_config in libs:
        url = lib_config.library_base_url
        lib_state = state.libraries.get(url, LibraryState())

        session = _make_session(lib_state.session_cookies)

        if lib_config.provider == "cloudlibrary":
            cl.init_session(session, lib_config.library_base_url)
        _url_builder, _page_parser = _provider_tools(lib_config)

        fetcher = _fetch_with_auth(session, lib_config, lib_state, delay=lib_config.request_delay_seconds)

        # Migrate a legacy single-format anchor onto the primary format.
        primary = lib_config.formats[0]
        if lib_state.legacy_anchor and primary not in lib_state.anchors:
            lib_state.anchors[primary] = lib_state.legacy_anchor
        lib_state.legacy_anchor = None

        now = datetime.now(timezone.utc).isoformat()
        last_checked = lib_state.last_checked or "the beginning"

        print(f"Checking {lib_config.name}...")
        sections: list[tuple[str, list[EBook]]] = []
        failed = False
        for fmt in lib_config.formats:
            had_anchor = fmt in lib_state.anchors
            anchor = lib_state.anchors.get(fmt)
            anchor_id = anchor.overdrive_id if anchor else None
            try:
                new_books, new_anchor = check_for_new_ebooks(
                    lib_config, lib_state, fetcher,
                    url_builder=_url_builder,
                    page_parser=_page_parser,
                    fmt=fmt,
                    anchor_id=anchor_id,
                )
            except Exception as e:
                print(f"Error checking {lib_config.name} ({fmt}): {e}", file=sys.stderr)
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                exit_code = 1
                failed = True
                break

            if not had_anchor:
                # First run for this format — establish the anchor, collect nothing.
                if new_anchor:
                    lib_state.anchors[fmt] = _ebook_to_state(new_anchor)
                    print(f"  {fmt}: initialized, tracking from \"{new_anchor.title}\" by {new_anchor.first_creator_name}")
                else:
                    print(f"  {fmt}: no books found.", file=sys.stderr)
                continue

            # Tracked format — record results and advance the anchor.
            sections.append((fmt, new_books))
            if new_books:
                print(f"  {fmt}: {len(new_books)} new.")
                if new_anchor:
                    lib_state.anchors[fmt] = _ebook_to_state(new_anchor)
            else:
                print(f"  {fmt}: no new titles.")

        if failed:
            continue

        # Persist this library's state (anchors, timestamp, cookies) once.
        lib_state.last_checked = now
        lib_state.session_cookies = dict(session.cookies)
        state.libraries[url] = lib_state
        save_state(state, state_path, config.max_state_backups)

        use_email = args.email
        total_new = sum(len(books) for _, books in sections)

        # Every format was first-run — nothing to present yet.
        if not sections:
            continue

        if total_new == 0:
            print(f"No new titles since {format_date(last_checked)}.")
        else:
            html = render_html(sections, last_checked or "", lib_config.name, lib_config.library_base_url)
            fd, tmp_name = tempfile.mkstemp(suffix=".html", prefix="new_ebooks_")
            os.close(fd)
            tmp = Path(tmp_name)

            auto_open = args.open if use_email else not args.no_open

            write_and_open(html, tmp, auto_open=auto_open)
            if auto_open:
                print(f"Opened results in browser: {tmp}")
            else:
                print(f"Results written to: {tmp}")

        if use_email:
            email_cfg = config.email
            if not email_cfg:
                print("Email not configured. Run 'new-ebooks email' to set up SMTP.", file=sys.stderr)
                exit_code = 1
                continue
            password = get_smtp_password(email_cfg.smtp_user) or ""
            if email_cfg.smtp_user and not password:
                print("SMTP password not set. Run 'new-ebooks email' to store it.", file=sys.stderr)
                exit_code = 1
                continue
            try:
                subject = page_heading(sections, last_checked or "", lib_config.name)
                email_html = render_email_html(sections, last_checked or "", lib_config.name, lib_config.library_base_url)
                send_email(subject, email_html, email_cfg, password)
                print(f"Email sent to {email_cfg.smtp_to}.")
            except Exception as e:
                print(f"Failed to send email: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                exit_code = 1

    return exit_code


def cmd_reset(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    state_path = Path(args.state)
    config = load_config(config_path)
    state = load_state(state_path) or State()

    if not config.libraries:
        print("No libraries configured.", file=sys.stderr)
        return 1

    if args.library:
        libs = [lib for lib in config.libraries if lib.name == args.library]
        if not libs:
            print(f"Library '{args.library}' not found.", file=sys.stderr)
            return 1
    else:
        libs = config.libraries

    for lib_config in libs:
        url = lib_config.library_base_url
        lib_state = state.libraries.get(url, LibraryState())
        session = _make_session(lib_state.session_cookies)

        if lib_config.provider == "cloudlibrary":
            cl.init_session(session, url)
        _url_builder, _page_parser = _provider_tools(lib_config)

        fetcher = _fetch_with_auth(session, lib_config, lib_state)

        print(f"Resetting {lib_config.name}...")
        # A reset rebuilds every format's anchor from scratch.
        lib_state.anchors = {}
        lib_state.legacy_anchor = None
        failed = False
        for fmt in lib_config.formats:
            try:
                url_fetch = _url_builder(url, fmt, 1)
                html = fetcher(url_fetch)
                books = _page_parser(html)
            except Exception as e:
                print(f"Failed to fetch page for format '{fmt}': {e}", file=sys.stderr)
                failed = True
                break

            if not books:
                print(f"No books found for format '{fmt}'.", file=sys.stderr)
                failed = True
                break

            anchor = books[0]
            lib_state.anchors[fmt] = _ebook_to_state(anchor)
            print(f"  {fmt}: tracking from \"{anchor.title}\" by {anchor.first_creator_name}")

        if failed:
            continue

        lib_state.last_checked = datetime.now(timezone.utc).isoformat()
        lib_state.session_cookies = dict(session.cookies)
        state.libraries[url] = lib_state
        save_state(state, state_path, config.max_state_backups)
        print("Reset complete.")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    state_path = Path(args.state)
    config = load_config(config_path)
    state = load_state(state_path)

    if not config.libraries:
        print("No libraries configured. Run 'new-ebooks init' first.")
        return 0

    for lib in config.libraries:
        url = lib.library_base_url
        print(f"\n{lib.name}")
        print(f"  URL:      {url}")
        print(f"  Provider: {lib.provider}")
        print(f"  Formats:  {', '.join(lib.formats)}")
        print(f"  Language: {lib.language or _default_language(lib.provider)}")
        if lib.member_library:
            print(f"  Member:   {lib.member_library}")

        if state:
            lib_state = state.libraries.get(url)
            if lib_state:
                print(f"  Last checked: {lib_state.last_checked or 'never'}")
                print("  Anchors:")
                for fmt in lib.formats:
                    anchor = lib_state.anchors.get(fmt)
                    if anchor is None and fmt == lib.formats[0] and lib_state.legacy_anchor:
                        anchor = lib_state.legacy_anchor
                    if anchor:
                        print(f"    {fmt}: \"{anchor.title}\" by {anchor.first_creator_name} (id={anchor.overdrive_id})")
                    else:
                        print(f"    {fmt}: (none)")
            else:
                print("  (no state — run 'new-ebooks init')")
        else:
            print("  (no state — run 'new-ebooks init')")

    if config.email:
        e = config.email
        print(f"\nEmail")
        print(f"  SMTP:   {e.smtp_host}:{e.smtp_port} (TLS: {e.use_tls})")
        print(f"  User:   {e.smtp_user}")
        print(f"  From:   {e.smtp_from}")
        print(f"  To:     {e.smtp_to}")
    else:
        print("\nEmail: not configured (run 'new-ebooks email' to set up)")

    from new_ebooks.scheduler import get_schedule_info, WEEKDAY_NAMES
    info = get_schedule_info()
    if info:
        day = WEEKDAY_NAMES[info["weekday"]]
        time_str = f"{info['hour']:02d}:{info['minute']:02d}"
        status_str = "active" if info["loaded"] else "not loaded"
        args_str = " ".join(info["check_args"]) or "(none)"
        print(f"\nSchedule ({status_str})")
        print(f"  Every {day} at {time_str}")
        print(f"  Extra args: {args_str}")
    else:
        print("\nSchedule: not configured (run 'new-ebooks schedule' to set up)")

    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = load_config(config_path)

    if not config.libraries:
        print("No libraries configured. Run 'new-ebooks init' first.", file=sys.stderr)
        return 1

    # Select library
    if args.library:
        matches = [lib for lib in config.libraries if lib.name == args.library]
        if not matches:
            print(f"Library '{args.library}' not found.", file=sys.stderr)
            return 1
        lib = matches[0]
    elif len(config.libraries) == 1:
        lib = config.libraries[0]
    else:
        print("Select a library to edit:")
        for i, l in enumerate(config.libraries, 1):
            print(f"  {i}. {l.name}")
        choice = input("Enter number: ").strip()
        try:
            lib = config.libraries[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid selection.", file=sys.stderr)
            return 1

    print(f"Editing '{lib.name}'. Press Enter to keep the current value.")

    name = input(f"Library name [{lib.name}]: ").strip() or lib.name
    library_url = input(f"Overdrive base URL [{lib.library_base_url}]: ").strip().rstrip("/") or lib.library_base_url
    delay_str = input(f"Request delay seconds [{lib.request_delay_seconds}]: ").strip()
    delay = float(delay_str) if delay_str else lib.request_delay_seconds

    current_provider = lib.provider
    provider_input = input(f"Provider (overdrive/cloudlibrary) [{current_provider}]: ").strip().lower() or current_provider
    if provider_input not in ("overdrive", "cloudlibrary"):
        print("Unknown provider. Use 'overdrive' or 'cloudlibrary'.", file=sys.stderr)
        return 1

    formats = _prompt_formats(provider_input, current=lib.formats)
    if not formats:
        print("At least one format is required.", file=sys.stderr)
        return 1

    if provider_input == "cloudlibrary":
        member_library = None
    else:
        current_member = lib.member_library or "(none)"
        default_consortium = "y" if lib.member_library else "n"
        is_consortium = input(f"Is this a consortial Overdrive site? (y/n) [{default_consortium}]: ").strip().lower() or default_consortium
        if is_consortium == "y":
            member_library = input(f"Member library name [{current_member}]: ").strip() or lib.member_library
        else:
            member_library = None

    language = _prompt_language(provider_input, current=lib.language)
    if language is None:
        print("Unknown language filter. Use 'all' or 'english'.", file=sys.stderr)
        return 1

    lib.name = name
    lib.library_base_url = library_url
    lib.formats = formats
    lib.request_delay_seconds = delay
    lib.provider = provider_input
    lib.member_library = member_library
    lib.language = language

    save_config(config, config_path)
    print(f"Saved. Run 'new-ebooks reset --library \"{lib.name}\"' to re-establish the anchor.")
    return 0


def cmd_email_config(args: argparse.Namespace) -> int:
    from new_ebooks.emailer import set_smtp_password, get_smtp_password
    config_path = Path(args.config)
    config = load_config(config_path)
    current = config.email

    print("=== New eBooks — Configure Email ===")
    print("Press Enter to keep the current value.\n")

    current_host = current.smtp_host if current else ""
    smtp_host = input(f"SMTP host [{current_host or 'e.g. smtp.gmail.com'}]: ").strip() or current_host
    if not smtp_host:
        print("SMTP host cannot be empty.", file=sys.stderr)
        return 1

    current_port = str(current.smtp_port) if current else "587"
    port_str = input(f"SMTP port [{current_port}]: ").strip() or current_port
    try:
        smtp_port = int(port_str)
    except ValueError:
        smtp_port = 587

    current_user = current.smtp_user if current else ""
    smtp_user = input(f"SMTP username [{current_user}]: ").strip() or current_user

    change_password = True
    if current and get_smtp_password(current.smtp_user):
        resp = input("SMTP password is already set. Change it? (y/n) [n]: ").strip().lower()
        change_password = resp == "y"
    if change_password:
        import getpass
        password = getpass.getpass("SMTP password: ")
        if password:
            set_smtp_password(smtp_user, password)

    current_from = current.smtp_from if current else smtp_user
    smtp_from = input(f"From address [{current_from}]: ").strip() or current_from

    current_to = current.smtp_to if current else ""
    smtp_to = input(f"To address [{current_to}]: ").strip() or current_to
    if not smtp_to:
        print("To address cannot be empty.", file=sys.stderr)
        return 1

    current_tls = "y" if (current.use_tls if current else True) else "n"
    tls_str = input(f"Use TLS/STARTTLS? (y/n) [{current_tls}]: ").strip().lower() or current_tls
    use_tls = tls_str != "n"

    config.email = EmailConfig(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_from=smtp_from,
        smtp_to=smtp_to,
        use_tls=use_tls,
    )
    save_config(config, config_path)
    print(f"\nEmail configured. Run 'new-ebooks check --email' to send results.")
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    from new_ebooks.scheduler import (
        write_plist, load_plist, unload_plist,
        get_schedule_info, is_loaded, WEEKDAY_NAMES, PLIST_PATH,
    )
    from new_ebooks.config import DEFAULT_CONFIG_DIR

    config_path = Path(args.config)
    config = load_config(config_path)

    # Warn if already scheduled
    existing = get_schedule_info()
    if existing:
        day = WEEKDAY_NAMES[existing["weekday"]]
        time_str = f"{existing['hour']:02d}:{existing['minute']:02d}"
        print(f"A schedule already exists: every {day} at {time_str}.")
        resp = input("Replace it? (y/n) [y]: ").strip().lower() or "y"
        if resp != "y":
            return 0

    print("=== New eBooks — Schedule Weekly Check ===")
    print("Press Enter to accept the default.\n")

    # Day of week
    day_input = input("Day of week [Monday]: ").strip() or "Monday"
    weekday = None
    for i, name in enumerate(WEEKDAY_NAMES):
        if name.lower().startswith(day_input.lower()):
            weekday = i
            break
    if weekday is None:
        try:
            weekday = int(day_input) % 7
        except ValueError:
            print(f"Unrecognised day '{day_input}'. Use a day name or 0–6 (0=Sunday).", file=sys.stderr)
            return 1

    # Time
    time_input = input("Time (HH:MM, 24-hour) [09:00]: ").strip() or "09:00"
    try:
        hour_str, minute_str = time_input.split(":")
        hour, minute = int(hour_str), int(minute_str)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        print(f"Invalid time '{time_input}'. Use HH:MM in 24-hour format.", file=sys.stderr)
        return 1

    # Determine check args
    check_args: list[str] = []
    if config.email:
        check_args = ["--email"]
    else:
        check_args = ["--no-open"]
        print("Note: email is not configured — scheduled check will run with --no-open.")
        print("Run 'new-ebooks email' to configure email delivery.")

    log_path = DEFAULT_CONFIG_DIR / "check.log"

    # Unload existing if loaded, then write and load new plist
    if existing and is_loaded():
        unload_plist()

    write_plist(check_args, weekday, hour, minute, log_path)
    try:
        load_plist()
    except Exception as e:
        print(f"Failed to register schedule with launchd: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    day_name = WEEKDAY_NAMES[weekday]
    print(f"\nScheduled: every {day_name} at {hour:02d}:{minute:02d}.")
    print(f"If the computer is asleep at that time, the check will run at next wake.")
    print(f"Output logged to: {log_path}")
    return 0


def cmd_update_cache(args: argparse.Namespace) -> int:
    from new_ebooks.scheduler import write_launcher, PKG_CACHE_DIR, LAUNCHER_PATH, get_schedule_info

    if not get_schedule_info():
        print("No schedule configured. Run 'new-ebooks schedule' first.", file=sys.stderr)
        return 1

    try:
        write_launcher()
        print(f"Package cache updated: {PKG_CACHE_DIR}")
        print(f"Launcher updated: {LAUNCHER_PATH}")
    except Exception as e:
        print(f"Failed to update cache: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1
    return 0


def cmd_unschedule(args: argparse.Namespace) -> int:
    from new_ebooks.scheduler import unload_plist, is_loaded, PLIST_PATH, get_schedule_info

    if not get_schedule_info():
        print("No schedule configured.")
        return 0

    if is_loaded():
        unload_plist()
    PLIST_PATH.unlink(missing_ok=True)
    print("Schedule removed.")
    return 0


def main() -> None:
    default_config = str(DEFAULT_CONFIG_PATH)
    default_state = str(DEFAULT_STATE_PATH)

    parser = argparse.ArgumentParser(
        prog="new-ebooks",
        description="Find eBooks added to an Overdrive library since your last check.",
    )
    parser.add_argument("--config", default=default_config, metavar="PATH", help="Config file path")
    parser.add_argument("--state", default=default_state, metavar="PATH", help="State file path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    subparsers = parser.add_subparsers(dest="command")

    # init
    subparsers.add_parser("init", help="Add and initialize a library")

    # check
    check_p = subparsers.add_parser("check", help="Check for new eBooks")
    check_p.add_argument("--library", metavar="NAME", help="Check a specific library by name")
    check_p.add_argument("--no-open", action="store_true", help="Don't open results in browser")
    check_p.add_argument("--email", action="store_true", help="Send results by email (skips browser by default)")
    check_p.add_argument("--open", action="store_true", help="Open results in browser even when --email is used")

    # edit
    edit_p = subparsers.add_parser("edit", help="Edit a library's configuration")
    edit_p.add_argument("--library", metavar="NAME", help="Library to edit by name")

    # reset
    reset_p = subparsers.add_parser("reset", help="Reset anchor for a library")
    reset_p.add_argument("--library", metavar="NAME", help="Reset a specific library by name")

    # status
    subparsers.add_parser("status", help="Show config and state")

    # email
    subparsers.add_parser("email", help="Configure SMTP email settings")

    # schedule / unschedule / update-cache
    subparsers.add_parser("schedule", help="Schedule a weekly automatic check")
    subparsers.add_parser("unschedule", help="Remove the scheduled check")
    subparsers.add_parser("update-cache", help="Refresh the local package copy used by the scheduled job")

    args = parser.parse_args()

    if args.command == "init":
        sys.exit(cmd_init(args))
    elif args.command == "edit":
        sys.exit(cmd_edit(args))
    elif args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "reset":
        sys.exit(cmd_reset(args))
    elif args.command == "status":
        sys.exit(cmd_status(args))
    elif args.command == "email":
        sys.exit(cmd_email_config(args))
    elif args.command == "schedule":
        sys.exit(cmd_schedule(args))
    elif args.command == "unschedule":
        sys.exit(cmd_unschedule(args))
    elif args.command == "update-cache":
        sys.exit(cmd_update_cache(args))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
