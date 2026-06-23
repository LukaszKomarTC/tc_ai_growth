"""Tossa Cycling AI growth orchestrator.

Layering (enforced for provider portability):

    tools/    -> pure API clients (WordPress, Search Console, GA4, Google Ads, Meta, GBP,
                 PageSpeed). NO AI-SDK imports.
    core/     -> provider-neutral business logic: KPIs, opportunity scoring, approval rules.
                 NO AI-SDK imports.
    runtime/  -> the ONLY layer that imports a specific AI provider SDK. Swapping Claude for
                 another model means adding a sibling adapter here, not touching tools/ or core/.
"""

__version__ = "0.1.0"
