=== TC Growth Connector ===
Contributors: tossacycling
Requires at least: 6.4
Requires PHP: 8.0
Stable tag: 0.1.0
License: GPLv2 or later

Thin, secure bridge between the Tossa Cycling website and the external TC AI Growth agent
system. Exposes controlled SEO/content/product data and accepts AI-proposed changes as
DRAFTS ONLY.

== Description ==

This plugin is intentionally minimal. It does NOT contain any AI logic — the "brain" runs
externally. Its only job is to safely connect the site to the growth agent system.

Design guarantees:

* **Draft-only writes.** Endpoints create drafts / native revisions. Nothing is ever published,
  and prices, stock, availability, the booking plugin, and checkout are never modified.
* **Provider-neutral.** The connector makes no assumption about which AI provider calls it. It is
  a plain signed REST API; Claude, OpenAI, Gemini, or any orchestrator can use it.
* **Fully removable.** It is independent of the booking plugin (`tc-booking-flow-next`).
  Uninstalling drops only this plugin's own audit table and `_tc_growth_*` post meta. Rentals,
  orders, and payments are untouched.
* **Audited.** Every read and draft-write is recorded in an append-only audit table.

== Configuration ==

Add a signing key to wp-config.php:

    define( 'TC_GROWTH_SIGNING_KEY', 'a-long-random-secret-32-bytes-or-more' );

Create a dedicated WordPress user for the agent with an Application Password and the
`edit_posts` capability. The orchestrator authenticates with that Application Password AND signs
every request with the shared key (HMAC-SHA256 over timestamp.method.route.body).

== Endpoints (namespace: tc-growth/v1) ==

Read:
* GET  /site-map
* GET  /pages
* GET  /products
* GET  /rentals
* GET  /seo-audit-data?post_id=ID

Draft-write (Phase 1-2):
* POST /create-seo-draft
* POST /create-product-revision
* POST /create-draft-asset       (ad copy / GBP posts -> "Growth Drafts")
* POST /log-agent-action

Controlled execution (Phase 3, human-approved only):
* POST /publish-seo-draft        (applies an approved SEO draft to the live page)

== Changelog ==

= 0.1.0 =
* Initial Phase 0 scaffold: read endpoints, draft-only writes, HMAC auth, audit log.
