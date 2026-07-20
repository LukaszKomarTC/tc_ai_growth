"""Import every tool module so the registry is populated, then expose the registry.

Importing a tool module has the side effect of registering its tools. Centralising the imports
here means the runtime just calls `load_all()` and gets the full, provider-neutral tool set.
"""

from __future__ import annotations

from .base import ToolRegistry, registry


def load_all() -> ToolRegistry:
    # Import for side effects (registration). Ordered by lever priority: SEO first.
    from . import search_console  # noqa: F401  SEO
    from . import wordpress  # noqa: F401       SEO drafts + site data
    from . import ga4  # noqa: F401             revenue attribution
    from . import google_ads  # noqa: F401      Google Ads
    from . import meta_ads  # noqa: F401        Meta Ads
    from . import gbp  # noqa: F401             local
    from . import pagespeed  # noqa: F401       performance
    from . import budget  # noqa: F401          ad-budget recommendations (dry-run)
    from . import cases  # noqa: F401           case memory (agent-maintained institutional memory)
    from . import site_intel  # noqa: F401      Site Intelligence snapshots (WP-06)

    return registry
