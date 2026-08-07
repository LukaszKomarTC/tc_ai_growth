"""WP-U5 collectors. Each one is named, bounded, read-only, and reports `unknown` rather than
guessing when its source cannot be read.

U5.1 ships only the fixture collector: the foundation is what is under review here, and a real
collector whose source has not yet been agreed would be scope the reviewer did not approve. The
first four real ones (`wp.inventory`, `platform.services`, `host.capacity`, `logs.signatures`)
land in U5.2.
"""

from .fixture import FixtureCollector

__all__ = ["FixtureCollector"]
