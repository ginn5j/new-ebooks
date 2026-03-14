# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**New eBooks** is an app that finds eBooks added to an Overdrive-hosted library collection since the last time the library was checked. It works specifically with libraries that host their eBook collection via Overdrive.

## Core Algorithm

1. Load the stored "most recent eBook" from the previous run (state from prior check).
2. Open the Overdrive advanced search page for the configured library, filtered to the user's desired eBook format, sorted by date added (newest first).
3. Paginate through results, collecting eBooks, until the stored "most recent eBook" is found.
   - If the eBook is **not** on the current page: add all eBooks on the page to the new-books list, then advance to the next page.
   - If the eBook **is** found: add only the eBooks that appear before it on the page to the new-books list, then stop.
4. Save the first eBook from this run's new-books list as the new "most recent eBook" for next time.
5. Present the collected list to the user.

## State Persistence

The app must persist the "most recent eBook" between runs (e.g., a local file or database) so it knows where to stop on the next check.
