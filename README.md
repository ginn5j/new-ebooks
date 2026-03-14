# New eBooks

A Python CLI tool that finds eBooks added to an Overdrive-hosted library collection since the last time you checked. Supports single libraries and consortial Overdrive sites.

## Requirements

- Python 3.9+
- macOS (credentials are stored in the macOS Keychain via `keyring`)

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
- **Overdrive base URL** — e.g. `https://hepl.overdrive.com`
- **Format** — e.g. `ebook-epub-adobe` or `ebook-kindle`
- **Request delay** — seconds to wait between page fetches (default: 1.0)
- **Consortial site** — if `y`, you will also be prompted for your member library name as it appears on the Overdrive sign-in page
- **Library card number and PIN** — stored securely in the macOS Keychain; not written to disk

On first run, the most recently added eBook is recorded as the anchor. Run `new-ebooks check` afterwards to start seeing new additions.

## Commands

### `new-ebooks check`

Checks all configured libraries for new eBooks and opens an HTML results page in your browser. Each book card shows the cover, title, author, a short description, and a **Borrow** or **Place a Hold** button linking directly to the Overdrive title page.

```
new-ebooks check
new-ebooks check --library "Hamilton East Public Library"
new-ebooks check --no-open   # write HTML but don't open browser
```

If there are no new eBooks since the last check, prints a message to the terminal instead.

### `new-ebooks status`

Prints the current configuration and anchor state for all libraries — no network calls made.

```
new-ebooks status
```

### `new-ebooks edit`

Interactively edit a library's configuration (name, URL, format, delay, member library). Shows current values as defaults; press Enter to keep them.

```
new-ebooks edit
new-ebooks edit --library "Hamilton East Public Library"
```

After editing, run `new-ebooks reset` to re-authenticate and re-establish the anchor with the updated settings.

### `new-ebooks reset`

Clears the anchor for a library and re-establishes it from the current first page of results. Use this after editing a library's configuration or if the anchor book has been removed from the collection.

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

1. Loads the stored anchor (most recently added eBook from the previous run).
2. Fetches the library's Overdrive search page sorted by **Newly Added**, filtered to the configured format.
3. Book order and data are read from `window.OverDrive.titleCollection` embedded in the page.
4. Paginates through results until the anchor is found:
   - Books on pages before the anchor are all new.
   - On the anchor's page, only books appearing before it are new.
5. Saves the first new book as the next anchor.
6. Renders an HTML page with cover images, titles, authors, and Borrow/Place a Hold links, and opens it in the browser.

A safety valve stops pagination at 50 pages. If this triggers, the anchor was likely removed from the collection — run `new-ebooks reset`.

## Credentials

Card number and PIN are stored in the macOS Keychain under the service name `new-ebooks`. They are never written to the config or state files. For consortial libraries, credentials are keyed by `{library_base_url}::{member_library}`.

## Configuration files

| File | Purpose |
|------|---------|
| `~/.config/new_ebooks/config.json` | Library names, URLs, formats, member libraries, backup settings |
| `~/.config/new_ebooks/state.json` | Anchor books, last-checked timestamps, cached session cookies |
| `~/.config/new_ebooks/state.json.{timestamp}` | State backups (see below) |

## State backups

Before each state save, the current `state.json` is copied to `state.json.{mtime}` where `{mtime}` is the file's last-modified timestamp. Once the number of backups exceeds the configured limit, the oldest are deleted.

The default limit is 10. To change it, set `max_state_backups` in `config.json`:

```json
{
  "max_state_backups": 5,
  "libraries": [...]
}
```

Set `max_state_backups` to `0` to disable backups entirely.
