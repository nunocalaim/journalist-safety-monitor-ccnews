#!/usr/bin/env python3
"""Regenerate data/exports/*.csv (incidents + candidates, every window)
from the current local data, without running a collection cycle.

For an on-demand full compile -- reviewing the data, pulling numbers for
a presentation -- without waiting for the next scheduled run or a
collection cycle. Reuses JournalistSafetyMonitor.export_data() directly
so the output exactly matches what a live run produces (same
config-driven windows, same file names).

Needs data/incidents.db and data/candidates/ to actually be present
locally, not Git LFS pointer stubs -- run `git lfs pull` first if you've
just cloned or pulled without it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from journalist_safety_monitor import JournalistSafetyMonitor  # noqa: E402


def main():
    monitor = JournalistSafetyMonitor(use_database=True)
    try:
        monitor.export_data()
    finally:
        monitor.db.close()


if __name__ == '__main__':
    main()
