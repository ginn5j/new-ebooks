from __future__ import annotations
import argparse
import sys
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from new_ebooks.config import (
    DEFAULT_CONFIG_PATH,
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
    login,
    is_authenticated,
)
from new_ebooks.checker import check_for_new_ebooks
from new_ebooks.renderer import render_html, write_and_open


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
        "Accept-Encoding": "gzip, deflate, br",
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
    def fetcher(url: str) -> str:
        if delay:
            time.sleep(delay)
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text
        if not is_authenticated(html):
            print("Session expired. Re-authenticating...")
            try:
                card_number, pin = get_credentials(lib_config.library_base_url, lib_config.member_library)
                new_cookies = login(session, lib_config.library_base_url, lib_config.member_library, card_number, pin)
                lib_state.session_cookies = new_cookies
                resp = session.get(url, timeout=30)
                resp.raise_for_status()
                html = resp.text
            except Exception as e:
                print(f"Re-authentication failed: {e}", file=sys.stderr)
        return html
    return fetcher


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

    library_url = input("Overdrive base URL (e.g. https://spl.overdrive.com): ").strip().rstrip("/")
    if not library_url:
        print("URL cannot be empty.", file=sys.stderr)
        return 1

    fmt = input("Format (e.g. ebook-epub-adobe, ebook-kindle) [ebook-epub-adobe]: ").strip() or "ebook-epub-adobe"
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

    # Consortium member library
    member_library = None
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
        format=fmt,
        request_delay_seconds=delay,
        member_library=member_library,
    )

    # Authenticate — results may be filtered to the member library's available titles
    card_number, pin = get_credentials(library_url, member_library)
    print("Authenticating...")
    cookies: dict = {}
    try:
        cookies = login(session, library_url, member_library, card_number, pin)
    except Exception as e:
        print(f"Authentication failed: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1

    lib_state = LibraryState(session_cookies=cookies)
    fetcher = _fetch_with_auth(session, lib_config, lib_state, delay=0.0)

    # Fetch page 1 to establish anchor
    search_url = build_search_url(library_url, fmt, 1)
    print("Fetching first page to establish anchor...")
    try:
        html = fetcher(search_url)
    except Exception as e:
        print(f"Failed to fetch library page: {e}", file=sys.stderr)
        return 1

    books = parse_page(html)

    if not books:
        print("No books found on first page. Check the URL and format.", file=sys.stderr)
        return 1

    anchor = books[0]
    lib_state.most_recent_ebook = _ebook_to_state(anchor)
    lib_state.last_checked = datetime.now(timezone.utc).isoformat()

    config.libraries.append(lib_config)
    state.libraries[library_url] = lib_state

    save_config(config, config_path)
    save_state(state, state_path, config.max_state_backups)

    print(f"\nInitialized. Tracking from: \"{anchor.title}\" by {anchor.first_creator_name}")
    print("Run 'new-ebooks check' to see new additions.")
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
    if hasattr(args, "library") and args.library:
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
        fetcher = _fetch_with_auth(session, lib_config, lib_state, delay=lib_config.request_delay_seconds)

        print(f"Checking {lib_config.name}...")
        try:
            new_books, new_anchor = check_for_new_ebooks(lib_config, lib_state, fetcher)
        except Exception as e:
            print(f"Error checking {lib_config.name}: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
            exit_code = 1
            continue

        now = datetime.now(timezone.utc).isoformat()
        last_checked = lib_state.last_checked or "the beginning"

        if lib_state.most_recent_ebook is None:
            # First run — new_anchor is the anchor to save
            if new_anchor:
                lib_state.most_recent_ebook = _ebook_to_state(new_anchor)
                lib_state.last_checked = now
                lib_state.session_cookies = dict(session.cookies)
                state.libraries[url] = lib_state
                save_state(state, state_path, config.max_state_backups)
                print(f"Initialized. Tracking from: \"{new_anchor.title}\" by {new_anchor.first_creator_name}")
                print("Run 'new-ebooks check' again to see new additions.")
            else:
                print("No books found.", file=sys.stderr)
            continue

        if not new_books:
            print(f"No new eBooks since {last_checked}.")
        else:
            print(f"Found {len(new_books)} new eBook(s).")
            # Update state
            if new_anchor:
                lib_state.most_recent_ebook = _ebook_to_state(new_anchor)
            lib_state.last_checked = now
            lib_state.session_cookies = dict(session.cookies)
            state.libraries[url] = lib_state
            save_state(state, state_path, config.max_state_backups)

            # Render HTML
            html = render_html(new_books, last_checked or "", lib_config.name, lib_config.library_base_url)
            tmp = Path(tempfile.mktemp(suffix=".html", prefix="new_ebooks_"))
            auto_open = not (hasattr(args, "no_open") and args.no_open)
            write_and_open(html, tmp, auto_open=auto_open)
            if auto_open:
                print(f"Opened results in browser: {tmp}")
            else:
                print(f"Results written to: {tmp}")

    return exit_code


def cmd_reset(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    state_path = Path(args.state)
    config = load_config(config_path)
    state = load_state(state_path) or State()

    if not config.libraries:
        print("No libraries configured.", file=sys.stderr)
        return 1

    if hasattr(args, "library") and args.library:
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
        fetcher = _fetch_with_auth(session, lib_config, lib_state)

        print(f"Resetting {lib_config.name}...")
        try:
            url_fetch = build_search_url(url, lib_config.format, 1)
            html = fetcher(url_fetch)
            books = parse_page(html)
        except Exception as e:
            print(f"Failed to fetch page: {e}", file=sys.stderr)
            continue

        if not books:
            print("No books found.", file=sys.stderr)
            continue

        anchor = books[0]
        lib_state.most_recent_ebook = _ebook_to_state(anchor)
        lib_state.last_checked = datetime.now(timezone.utc).isoformat()
        lib_state.session_cookies = dict(session.cookies)
        state.libraries[url] = lib_state
        save_state(state, state_path, config.max_state_backups)
        print(f"Reset. Tracking from: \"{anchor.title}\" by {anchor.first_creator_name}")

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
        print(f"  URL:    {url}")
        print(f"  Format: {lib.format}")
        if lib.member_library:
            print(f"  Member: {lib.member_library}")

        if state:
            lib_state = state.libraries.get(url)
            if lib_state:
                print(f"  Last checked: {lib_state.last_checked or 'never'}")
                if lib_state.most_recent_ebook:
                    mre = lib_state.most_recent_ebook
                    print(f"  Anchor: \"{mre.title}\" by {mre.first_creator_name} (id={mre.overdrive_id})")
                else:
                    print("  Anchor: (none)")
            else:
                print("  (no state — run 'new-ebooks init')")
        else:
            print("  (no state — run 'new-ebooks init')")

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
    fmt = input(f"Format [{lib.format}]: ").strip() or lib.format
    delay_str = input(f"Request delay seconds [{lib.request_delay_seconds}]: ").strip()
    delay = float(delay_str) if delay_str else lib.request_delay_seconds

    current_member = lib.member_library or "(none)"
    default_consortium = "y" if lib.member_library else "n"
    is_consortium = input(f"Is this a consortial Overdrive site? (y/n) [{default_consortium}]: ").strip().lower() or default_consortium
    if is_consortium == "y":
        member_library = input(f"Member library name [{current_member}]: ").strip() or lib.member_library
    else:
        member_library = None

    lib.name = name
    lib.library_base_url = library_url
    lib.format = fmt
    lib.request_delay_seconds = delay
    lib.member_library = member_library

    save_config(config, config_path)
    print(f"Saved. Run 'new-ebooks reset --library \"{lib.name}\"' to re-establish the anchor.")
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
    check_p.add_argument("--all", action="store_true", help="Check all libraries (default)")
    check_p.add_argument("--no-open", action="store_true", help="Don't open results in browser")

    # edit
    edit_p = subparsers.add_parser("edit", help="Edit a library's configuration")
    edit_p.add_argument("--library", metavar="NAME", help="Library to edit by name")

    # reset
    reset_p = subparsers.add_parser("reset", help="Reset anchor for a library")
    reset_p.add_argument("--library", metavar="NAME", help="Reset a specific library by name")

    # status
    subparsers.add_parser("status", help="Show config and state")

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
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    main()
