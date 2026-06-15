# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**New eBooks** is an app that finds titles added to a hosted library collection since the last time the library was checked. It supports two providers — **Overdrive** and **CloudLibrary** — and can track multiple media formats per library (e.g. an eBook format plus audiobooks), each with its own independent anchor.

Results are rendered to an HTML page (opened in the browser) and can optionally be emailed via SMTP. On macOS, a weekly check can be scheduled with launchd.

## Core Algorithm

For each configured library, each tracked format is checked independently:

1. Load the stored anchor (the "most recent" title) for that format from the previous run.
2. Open the provider's search results for the configured library, filtered to the format and any language filter, sorted by date added (newest first).
3. Paginate through results, collecting titles, until the stored anchor is found.
   - If the anchor is **not** on the current page: add all titles on the page to the new list, then advance to the next page.
   - If the anchor **is** found: add only the titles that appear before it on the page, then stop.
4. Save the first title from this run's new list as the new anchor for that format.
5. If the anchor is never found (removed from the collection, or beyond `MAX_PAGES`), the run is flagged so the results carry a warning rather than being trusted.
6. Present the collected lists (grouped by media kind) to the user.

## State Persistence

The app persists per-library, per-format anchors between runs (a JSON state file, written atomically with private permissions, with timestamped backups) so it knows where to stop on the next check. Config and state default to `~/.config/new_ebooks/`.
