# New eBooks

A Python CLI tool that finds eBooks added to a library's digital collection since the last time you checked. Supports both **Overdrive** and **CloudLibrary** (Bibliotheca) hosted collections, including consortial Overdrive sites.

## Requirements

- Python 3.9+
- Any OS with a supported [`keyring`](https://pypi.org/project/keyring/) backend (macOS Keychain, Windows Credential Locker, Linux Secret Service) — credentials are stored there, never on disk
- The `schedule`, `unschedule`, and `update-cache` commands are macOS-only (they rely on launchd); everything else works cross-platform

## Installation

```
pip install -e .
```

This installs the `new-ebooks` command.

## Setup

### Add a library

```
new-ebooks init
```

You will be prompted for:
- **Library name** — a display name of your choosing
- **Base URL** — e.g. `https://hepl.overdrive.com` or `https://ebook.yourcloudlibrary.com/library/scpl`
- **Provider** — `overdrive` (default) or `cloudlibrary`
- **Formats** — one or more media formats to track, comma-separated. Each format is searched separately, keeps its own anchor, and gets its own section in the results.
  - Overdrive: e.g. `ebook-epub-adobe`, `ebook-kindle`, `audiobook`
  - CloudLibrary: `ebook` and/or `audiobook`
  - Audiobook values: both providers use `audiobook`. Combine an eBook format with an audiobook format to track both, e.g. `ebook-kindle, audiobook` (Overdrive) or `ebook, audiobook` (CloudLibrary).
- **Language filter** — `all` or `english`. Restricts the search to a single language. The default matches each provider's existing behavior: Overdrive defaults to `all` (no filter), CloudLibrary defaults to `english`.
- **Request delay** — seconds to wait between page fetches (default: 1.0)

For **Overdrive** libraries only:
- **Consortial site** — if `y`, you will also be prompted for your member library name as it appears on the Overdrive sign-in page
- **Library card number and PIN** — stored securely in the macOS Keychain; not written to disk

CloudLibrary collections are public catalogs and do not require a card number or PIN to browse.

On first run, the most recently added title for each configured format is recorded as that format's anchor. Run `new-ebooks check` afterwards to start seeing new additions.

## Commands

### `new-ebooks check`

Checks all configured libraries for new eBooks and opens an HTML results page in your browser. Each book card shows the cover, title, author, a short description, and a **Borrow** or **Place a Hold** button linking directly to the title page. When a library tracks more than one format, the results are grouped into sections (new eBooks, then new audiobooks) with quick-jump navigation links between them.

```
new-ebooks check
new-ebooks check --library "Hamilton East Public Library"
new-ebooks check --no-open          # write HTML but don't open browser
new-ebooks check --email            # send results by email, don't open browser
new-ebooks check --email --open     # send results by email and open browser
```

`--library` (here and in `edit`/`reset`) matches the configured library name exactly, including case.

If there are no new eBooks since the last check, prints a message to the terminal. With `--email`, a "no new eBooks" message is still sent.

### `new-ebooks email`

Interactively configure SMTP settings for email delivery. The SMTP password is stored in the macOS Keychain under the service name `new-ebooks-smtp`; all other settings are saved to `config.json`.

```
new-ebooks email
```

You will be prompted for:
- **SMTP host** — e.g. `smtp.gmail.com`
- **SMTP port** — default `587`
- **SMTP username**
- **SMTP password** — stored in the macOS Keychain, not written to disk
- **From address** — defaults to the SMTP username
- **To address** — where results are delivered
- **TLS** — whether to use STARTTLS (default: yes)

### `new-ebooks schedule`

Sets up a weekly automatic check using macOS's built-in scheduler (launchd). If the computer is asleep or offline at the scheduled time, the check runs automatically at the next wake.

```
new-ebooks schedule
```

You will be prompted for:
- **Day of week** — e.g. `Monday` (default)
- **Time** — 24-hour `HH:MM` format (default `09:00`)

If email is configured, the scheduled check runs with `--email`. Otherwise it runs with `--no-open` and writes results to the results directory (see [Result files](#result-files)). Output from each run is appended to `~/.config/new_ebooks/check.log`.

The `schedule`, `unschedule`, and `update-cache` commands are macOS-only and exit with a clear message on other platforms.

### `new-ebooks unschedule`

Removes the scheduled check.

```
new-ebooks unschedule
```

### `new-ebooks update-cache`

Refreshes the local package copy used by the scheduled job. Because the scheduled job runs outside the iCloud Drive security context, the package source is copied to `~/.config/new_ebooks/pkg/` at schedule-time. If you modify the source code after setting up a schedule, run this command to push the changes into the cache.

```
new-ebooks update-cache
```

### `new-ebooks status`

Prints the current configuration and anchor state for all libraries, including the result files directory, result and state-backup retention, and email and schedule settings if configured — no network calls made.

```
new-ebooks status
```

### `new-ebooks config`

Sets global (not per-library) options: how many state backups and result HTML files to keep. Run with no flags to be prompted interactively (current values shown as defaults; press Enter to keep), or pass flags to set values non-interactively. A value of `0` disables that kind of pruning. These are the only ways to change these settings short of editing `config.json` by hand.

```
new-ebooks config                          # interactive
new-ebooks config --max-result-files 5
new-ebooks config --max-state-backups 0    # disable state backups
```

### `new-ebooks edit`

Interactively edit a library's configuration (name, URL, formats, language filter, delay, provider, member library). Formats are entered comma-separated. Shows current values as defaults; press Enter to keep them.

```
new-ebooks edit
new-ebooks edit --library "Hamilton East Public Library"
```

After editing, run `new-ebooks reset` to re-establish the anchor with the updated settings.

### `new-ebooks reset`

Clears the anchors for a library and re-establishes one per configured format from the current first page of results. Use this after editing a library's configuration or if an anchor book has been removed from the collection.

```
new-ebooks reset
new-ebooks reset --library "Hamilton East Public Library"
```

## Global flags

| Flag | Description |
|------|-------------|
| `--config PATH` | Use an alternate config file (default: `~/.config/new_ebooks/config.json`) |
| `--state PATH` | Use an alternate state file (default: `~/.config/new_ebooks/state.json`) |
| `--verbose` / `-v` | Print additional diagnostic output |

## How it works

The core algorithm is the same for both providers, and runs once per configured format (each format has its own anchor):

1. Load the stored anchor for the format (most recently added title from the previous run).
2. Fetch the library's search results for that format, sorted by **date added**, newest first.
3. Paginate through results until the anchor is found:
   - Books on pages before the anchor are all new.
   - On the anchor's page, only books appearing before it are new.
4. Save the first new book as the next anchor for that format.
5. Group each format's new books into sections by media type (eBooks, then audiobooks), render an HTML page with cover images, titles, authors, and Borrow/Place a Hold links, and open it in the browser (or send by email if `--email` is used).

A safety valve stops pagination at 50 pages. If the stored anchor is never found — because it was removed from the collection or pushed past the 50-page limit — the run is flagged: a warning banner appears at the top of the rendered results (and email), a notice is printed to the terminal, and the format's list may include already-seen titles rather than being trusted. Run `new-ebooks reset` to re-establish the anchor.

### Overdrive

Book data is read from `window.OverDrive.titleCollection` embedded in the search page HTML. Authentication uses a library card number and PIN stored in the macOS Keychain.

### CloudLibrary

Book data is fetched as JSON via the Remix `_data` route endpoint (`?_data=routes%2Flibrary.%24name.search`), sorted by `-dateadded`. The standardized format tokens `ebook` and `audiobook` are mapped to CloudLibrary's `digital` and `audio` query values internally. By default the search is filtered to English-language titles; set the library's language filter to `all` to include every language. Session initialisation requires only a GET to the library's base URL, which sets a `__config_PROD` cookie — no patron credentials are needed to browse the catalog.

## Credentials

Overdrive card number and PIN are stored in the macOS Keychain under the service name `new-ebooks`. They are never written to the config or state files. For consortial libraries, credentials are keyed by `{library_base_url}::{member_library}`.

The SMTP password is stored separately under the service name `new-ebooks-smtp`, keyed by the SMTP username.

CloudLibrary libraries do not store any credentials.

## Configuration files

| File | Purpose |
|------|---------|
| `~/.config/new_ebooks/config.json` | Library names, URLs, formats (one or more per library), language filters, providers, member libraries, backup/retention settings |
| `~/.config/new_ebooks/state.json` | Per-format anchor books, last-checked timestamps, cached session cookies |
| `~/.config/new_ebooks/state.json.{timestamp}` | State backups (see [State backups](#state-backups)) |
| `~/.config/new_ebooks/results/` | Rendered HTML result files (see [Result files](#result-files)) |

Loading config ignores unrecognized keys, so a config file written by a newer version still loads on an older one.

## Result files

Each `check` that finds new titles writes its rendered HTML to `~/.config/new_ebooks/results/` with a timestamped, library-named filename (e.g. `new_ebooks_hamilton-east-public-library_20260615_090000.html`). Files are kept rather than overwritten so you can review recent runs.

Once the number of result files exceeds the configured limit, the oldest are deleted. The default limit is 10. Change it with `new-ebooks config --max-result-files N` (or interactively with `new-ebooks config`); set it to `0` to disable pruning and keep every run. The value lives in `config.json` as `max_result_files` and can also be edited there by hand.

## State backups

Before each state save, the current `state.json` is copied to `state.json.{mtime}` where `{mtime}` is the file's last-modified timestamp. Once the number of backups exceeds the configured limit, the oldest are deleted.

The default limit is 10. Change it with `new-ebooks config --max-state-backups N` (or interactively with `new-ebooks config`); set it to `0` to disable backups entirely. The value lives in `config.json` as `max_state_backups` and can also be edited there by hand.

## Development

```
pip install -e ".[test]"
pytest
ruff check .    # lint (pip install ruff)
```

CI lints with ruff and runs the test suite on Python 3.9 through 3.13 for every pull request and push to `main`.
