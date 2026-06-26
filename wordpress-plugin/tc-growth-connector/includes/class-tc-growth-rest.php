<?php
/**
 * REST controller for the TC Growth Connector.
 *
 * READ endpoints expose controlled SEO/content/product data.
 * WRITE endpoints create DRAFTS / REVISIONS ONLY — they never publish, change status of a live
 * page, touch prices, availability, the booking plugin, or checkout.
 *
 * @package TC_Growth_Connector
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Registers and serves the tc-growth/v1 routes.
 */
class TC_Growth_REST {

	/**
	 * Register the REST routes.
	 */
	public function register_hooks() {
		add_action( 'rest_api_init', array( $this, 'register_routes' ) );
	}

	/**
	 * Route table.
	 */
	public function register_routes() {
		$read  = array( 'TC_Growth_Auth', 'can_read' );
		$write = array( 'TC_Growth_Auth', 'can_write_draft' );

		register_rest_route( TC_GROWTH_NAMESPACE, '/site-map', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_site_map' ),
			'permission_callback' => $read,
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/pages', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_pages' ),
			'permission_callback' => $read,
			'args'                => $this->collection_args(),
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/products', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_products' ),
			'permission_callback' => $read,
			'args'                => $this->collection_args(),
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/rentals', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_rentals' ),
			'permission_callback' => $read,
			'args'                => $this->collection_args(),
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/orders-attribution', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_orders_attribution' ),
			'permission_callback' => $read,
			'args'                => array(
				'days' => array( 'type' => 'integer', 'default' => 28, 'minimum' => 1, 'maximum' => 365 ),
			),
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/seo-audit-data', array(
			'methods'             => WP_REST_Server::READABLE,
			'callback'            => array( $this, 'get_seo_audit_data' ),
			'permission_callback' => $read,
			'args'                => array(
				'post_id' => array( 'type' => 'integer', 'required' => true ),
			),
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/create-seo-draft', array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => array( $this, 'create_seo_draft' ),
			'permission_callback' => $write,
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/create-draft-asset', array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => array( $this, 'create_draft_asset' ),
			'permission_callback' => $write,
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/create-product-revision', array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => array( $this, 'create_product_revision' ),
			'permission_callback' => $write,
		) );

		// Phase 3 — controlled execution. Applies a HUMAN-APPROVED SEO draft to the live page.
		register_rest_route( TC_GROWTH_NAMESPACE, '/publish-seo-draft', array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => array( $this, 'publish_seo_draft' ),
			'permission_callback' => $write,
		) );

		register_rest_route( TC_GROWTH_NAMESPACE, '/log-agent-action', array(
			'methods'             => WP_REST_Server::CREATABLE,
			'callback'            => array( $this, 'log_agent_action' ),
			'permission_callback' => $write,
		) );
	}

	/**
	 * Shared pagination args for collection endpoints.
	 *
	 * @return array
	 */
	protected function collection_args() {
		return array(
			'page'     => array( 'type' => 'integer', 'default' => 1, 'minimum' => 1 ),
			'per_page' => array( 'type' => 'integer', 'default' => 50, 'minimum' => 1, 'maximum' => 100 ),
		);
	}

	/* --------------------------------------------------------------------- READ --------- */

	/**
	 * Lightweight sitemap: published pages + posts with URL and modified date.
	 */
	public function get_site_map( WP_REST_Request $request ) {
		$query = new WP_Query( array(
			'post_type'      => array( 'page', 'post', 'product' ),
			'post_status'    => 'publish',
			'posts_per_page' => 500,
			'fields'         => 'ids',
			'no_found_rows'  => true,
		) );

		$items = array();
		foreach ( $query->posts as $id ) {
			$items[] = array(
				'id'       => $id,
				'type'     => get_post_type( $id ),
				'title'    => get_the_title( $id ),
				'url'      => get_permalink( $id ),
				'modified' => get_post_modified_time( 'c', true, $id ),
			);
		}

		TC_Growth_Audit::log( wp_get_current_user()->user_login, 'read-site-map', null, null, array( 'count' => count( $items ) ) );
		return rest_ensure_response( array( 'items' => $items ) );
	}

	/**
	 * Pages collection.
	 */
	public function get_pages( WP_REST_Request $request ) {
		return $this->get_collection( $request, 'page' );
	}

	/**
	 * Products collection (WooCommerce). Read-only summary — no price writes ever.
	 */
	public function get_products( WP_REST_Request $request ) {
		return $this->get_collection( $request, 'product' );
	}

	/**
	 * Rentals: products in a "rental" category if present, otherwise all products.
	 */
	public function get_rentals( WP_REST_Request $request ) {
		$tax_query = array();
		if ( taxonomy_exists( 'product_cat' ) && get_term_by( 'slug', 'rental', 'product_cat' ) ) {
			$tax_query[] = array(
				'taxonomy' => 'product_cat',
				'field'    => 'slug',
				'terms'    => array( 'rental', 'rentals' ),
			);
		}
		return $this->get_collection( $request, 'product', $tax_query );
	}

	/**
	 * Generic collection reader.
	 *
	 * @param WP_REST_Request $request   Request.
	 * @param string          $post_type Post type.
	 * @param array           $tax_query Optional tax query.
	 * @return WP_REST_Response
	 */
	protected function get_collection( WP_REST_Request $request, $post_type, $tax_query = array() ) {
		$args = array(
			'post_type'      => $post_type,
			'post_status'    => 'publish',
			'posts_per_page' => (int) $request->get_param( 'per_page' ),
			'paged'          => (int) $request->get_param( 'page' ),
		);
		if ( ! empty( $tax_query ) ) {
			$args['tax_query'] = $tax_query; // phpcs:ignore WordPress.DB.SlowDBQuery.slow_db_query_tax_query
		}

		$query = new WP_Query( $args );
		$items = array();
		foreach ( $query->posts as $post ) {
			$items[] = $this->summarize_post( $post );
		}

		TC_Growth_Audit::log( wp_get_current_user()->user_login, 'read-' . $post_type, null, null, array( 'count' => count( $items ) ) );

		return rest_ensure_response( array(
			'items'       => $items,
			'page'        => (int) $request->get_param( 'page' ),
			'per_page'    => (int) $request->get_param( 'per_page' ),
			'total'       => (int) $query->found_posts,
			'total_pages' => (int) $query->max_num_pages,
		) );
	}

	/**
	 * Summarize a post for the agent (no secrets, no internal fields).
	 *
	 * @param WP_Post $post Post.
	 * @return array
	 */
	protected function summarize_post( $post ) {
		$summary = array(
			'id'       => $post->ID,
			'type'     => $post->post_type,
			'title'    => get_the_title( $post ),
			'slug'     => $post->post_name,
			'url'      => get_permalink( $post ),
			'excerpt'  => wp_strip_all_tags( get_the_excerpt( $post ) ),
			'modified' => get_post_modified_time( 'c', true, $post ),
		);

		if ( 'product' === $post->post_type && function_exists( 'wc_get_product' ) ) {
			$product = wc_get_product( $post->ID );
			if ( $product ) {
				// Read-only context only. We surface price for ROI reasoning; we never write it.
				$summary['price']        = $product->get_price();
				$summary['in_stock']     = $product->is_in_stock();
				$summary['categories']   = wp_get_post_terms( $post->ID, 'product_cat', array( 'fields' => 'names' ) );
			}
		}

		return $summary;
	}

	/**
	 * SEO audit data for a single post: title, meta description, slug, schema hints, internal links.
	 */
	public function get_seo_audit_data( WP_REST_Request $request ) {
		$post_id = (int) $request->get_param( 'post_id' );
		$post    = get_post( $post_id );
		if ( ! $post || 'publish' !== $post->post_status ) {
			return new WP_Error( 'tc_growth_not_found', __( 'Post not found.', 'tc-growth-connector' ), array( 'status' => 404 ) );
		}

		$content = $post->post_content;
		$data    = array(
			'id'               => $post_id,
			'url'              => get_permalink( $post ),
			'title'            => get_the_title( $post ),
			'slug'             => $post->post_name,
			'meta_description' => $this->read_meta_description( $post_id ),
			'h1'               => $this->extract_first_tag( $content, 'h1' ),
			'h2'               => $this->extract_all_tags( $content, 'h2' ),
			'word_count'       => str_word_count( wp_strip_all_tags( $content ) ),
			'internal_links'   => $this->extract_internal_links( $content ),
			'images_missing_alt' => $this->count_images_missing_alt( $content ),
		);

		TC_Growth_Audit::log( wp_get_current_user()->user_login, 'read-seo-audit', 'post', $post_id );
		return rest_ensure_response( $data );
	}

	/**
	 * Revenue attribution: recent completed orders aggregated by acquisition source.
	 *
	 * Read-only. Powers the keyword -> ... -> revenue chain by tying bookings to the channel/
	 * source that produced them, using WooCommerce's built-in Order Attribution meta
	 * (_wc_order_attribution_*). Never modifies orders.
	 */
	public function get_orders_attribution( WP_REST_Request $request ) {
		if ( ! function_exists( 'wc_get_orders' ) ) {
			return new WP_Error( 'tc_growth_no_woo', __( 'WooCommerce not active.', 'tc-growth-connector' ), array( 'status' => 412 ) );
		}

		$days  = (int) $request->get_param( 'days' );
		$after = gmdate( 'Y-m-d H:i:s', time() - ( $days * DAY_IN_SECONDS ) );

		$orders = wc_get_orders( array(
			'status'       => array( 'wc-completed', 'wc-processing' ),
			'date_created' => '>=' . $after,
			'limit'        => 500,
			'return'       => 'objects',
		) );

		$by_source = array();
		$totals    = array( 'orders' => 0, 'revenue' => 0.0 );

		foreach ( $orders as $order ) {
			$source = $order->get_meta( '_wc_order_attribution_utm_source' );
			if ( ! $source ) {
				$source = $order->get_meta( '_wc_order_attribution_source_type' );
			}
			$source = $source ? sanitize_text_field( $source ) : 'unknown';
			$total  = (float) $order->get_total();

			if ( ! isset( $by_source[ $source ] ) ) {
				$by_source[ $source ] = array( 'orders' => 0, 'revenue' => 0.0 );
			}
			$by_source[ $source ]['orders']++;
			$by_source[ $source ]['revenue'] += $total;
			$totals['orders']++;
			$totals['revenue'] += $total;
		}

		// Round and sort by revenue desc.
		$rows = array();
		foreach ( $by_source as $source => $agg ) {
			$rows[] = array(
				'source'  => $source,
				'orders'  => $agg['orders'],
				'revenue' => round( $agg['revenue'], 2 ),
			);
		}
		usort( $rows, static function ( $a, $b ) {
			return $b['revenue'] <=> $a['revenue'];
		} );

		TC_Growth_Audit::log( wp_get_current_user()->user_login, 'read-orders-attribution', null, null, array( 'days' => $days, 'orders' => $totals['orders'] ) );

		return rest_ensure_response( array(
			'days'       => $days,
			'currency'   => function_exists( 'get_woocommerce_currency' ) ? get_woocommerce_currency() : '',
			'totals'     => array( 'orders' => $totals['orders'], 'revenue' => round( $totals['revenue'], 2 ) ),
			'by_source'  => $rows,
		) );
	}

	/* -------------------------------------------------------------- DRAFT WRITES -------- */

	/**
	 * Create a DRAFT revision with improved SEO title / meta description / slug suggestion.
	 *
	 * The live post is NEVER modified. We create a draft clone the editor can review and apply.
	 */
	public function create_seo_draft( WP_REST_Request $request ) {
		$params  = $request->get_json_params();
		$post_id = isset( $params['post_id'] ) ? (int) $params['post_id'] : 0;
		$post    = get_post( $post_id );
		if ( ! $post ) {
			return new WP_Error( 'tc_growth_not_found', __( 'Post not found.', 'tc-growth-connector' ), array( 'status' => 404 ) );
		}

		$new_title = isset( $params['title'] ) ? sanitize_text_field( $params['title'] ) : get_the_title( $post );
		$new_slug  = isset( $params['slug'] ) ? sanitize_title( $params['slug'] ) : $post->post_name;
		$meta_desc = isset( $params['meta_description'] ) ? sanitize_text_field( $params['meta_description'] ) : '';
		$rationale = isset( $params['rationale'] ) ? sanitize_textarea_field( $params['rationale'] ) : '';

		// Create a DRAFT clone — status forced to 'draft', never 'publish'.
		$draft_id = wp_insert_post( array(
			'post_type'    => $post->post_type,
			'post_status'  => 'draft',
			'post_title'   => $new_title,
			'post_name'    => $new_slug,
			'post_content' => $post->post_content,
			'post_excerpt' => $post->post_excerpt,
			'post_parent'  => $post->ID,
		), true );

		if ( is_wp_error( $draft_id ) ) {
			return $draft_id;
		}

		// Record provenance + proposed meta on the DRAFT only.
		update_post_meta( $draft_id, '_tc_growth_source_post', $post_id );
		update_post_meta( $draft_id, '_tc_growth_proposed_meta_description', $meta_desc );
		update_post_meta( $draft_id, '_tc_growth_rationale', $rationale );

		TC_Growth_Audit::log(
			wp_get_current_user()->user_login,
			'create-seo-draft',
			'post',
			$draft_id,
			array( 'source_post' => $post_id, 'title' => $new_title, 'slug' => $new_slug )
		);

		return rest_ensure_response( array(
			'draft_id'    => $draft_id,
			'source_post' => $post_id,
			'edit_link'   => get_edit_post_link( $draft_id, 'raw' ),
			'status'      => 'draft',
		) );
	}

	/**
	 * Create a draft "growth asset" (ad copy, GBP post, FAQ block, internal-link plan, ...).
	 *
	 * Stored as a DRAFT of the private tc_growth_asset post type — reviewable in wp-admin under
	 * "Growth Drafts", never published, never touches the live site or any ad platform.
	 */
	public function create_draft_asset( WP_REST_Request $request ) {
		$params = $request->get_json_params();

		$allowed_types = array( 'google_ad', 'meta_ad', 'gbp_post', 'faq', 'internal_links', 'other' );
		$asset_type    = isset( $params['asset_type'] ) ? sanitize_key( $params['asset_type'] ) : 'other';
		if ( ! in_array( $asset_type, $allowed_types, true ) ) {
			$asset_type = 'other';
		}

		$title     = isset( $params['title'] ) ? sanitize_text_field( $params['title'] ) : __( 'Untitled growth draft', 'tc-growth-connector' );
		$body      = isset( $params['body'] ) ? wp_kses_post( $params['body'] ) : '';
		$target    = isset( $params['target_url'] ) ? esc_url_raw( $params['target_url'] ) : '';
		$rationale = isset( $params['rationale'] ) ? sanitize_textarea_field( $params['rationale'] ) : '';
		$meta      = ( isset( $params['meta'] ) && is_array( $params['meta'] ) ) ? $params['meta'] : array();

		$draft_id = wp_insert_post( array(
			'post_type'    => 'tc_growth_asset',
			'post_status'  => 'draft',
			'post_title'   => '[' . $asset_type . '] ' . $title,
			'post_content' => $body,
		), true );

		if ( is_wp_error( $draft_id ) ) {
			return $draft_id;
		}

		update_post_meta( $draft_id, '_tc_growth_asset_type', $asset_type );
		update_post_meta( $draft_id, '_tc_growth_target_url', $target );
		update_post_meta( $draft_id, '_tc_growth_rationale', $rationale );
		foreach ( $meta as $key => $value ) {
			update_post_meta( $draft_id, '_tc_growth_' . sanitize_key( $key ), sanitize_text_field( is_scalar( $value ) ? $value : wp_json_encode( $value ) ) );
		}

		TC_Growth_Audit::log(
			wp_get_current_user()->user_login,
			'create-draft-asset',
			'tc_growth_asset',
			$draft_id,
			array( 'asset_type' => $asset_type, 'title' => $title )
		);

		return rest_ensure_response( array(
			'draft_id'   => $draft_id,
			'asset_type' => $asset_type,
			'edit_link'  => get_edit_post_link( $draft_id, 'raw' ),
			'status'     => 'draft',
		) );
	}

	/**
	 * Create a draft revision of a product DESCRIPTION (content only). Never touches price/stock.
	 */
	public function create_product_revision( WP_REST_Request $request ) {
		$params  = $request->get_json_params();
		$post_id = isset( $params['post_id'] ) ? (int) $params['post_id'] : 0;
		$post    = get_post( $post_id );
		if ( ! $post || 'product' !== $post->post_type ) {
			return new WP_Error( 'tc_growth_not_found', __( 'Product not found.', 'tc-growth-connector' ), array( 'status' => 404 ) );
		}

		$new_description = isset( $params['description'] ) ? wp_kses_post( $params['description'] ) : $post->post_content;
		$rationale       = isset( $params['rationale'] ) ? sanitize_textarea_field( $params['rationale'] ) : '';

		// Store as a native WordPress revision against the product so the editor can diff & restore.
		// We do NOT change the live product; _wp_put_post_revision creates a revision row only.
		$revision_id = _wp_put_post_revision( array(
			'ID'           => $post_id,
			'post_content' => $new_description,
			'post_title'   => $post->post_title,
			'post_excerpt' => $post->post_excerpt,
		) );

		if ( is_wp_error( $revision_id ) || ! $revision_id ) {
			return new WP_Error( 'tc_growth_revision_failed', __( 'Could not create revision.', 'tc-growth-connector' ), array( 'status' => 500 ) );
		}

		update_post_meta( $post_id, '_tc_growth_pending_rationale_' . $revision_id, $rationale );

		TC_Growth_Audit::log(
			wp_get_current_user()->user_login,
			'create-product-revision',
			'product',
			$post_id,
			array( 'revision_id' => $revision_id )
		);

		return rest_ensure_response( array(
			'product_id'  => $post_id,
			'revision_id' => $revision_id,
			'edit_link'   => get_edit_post_link( $post_id, 'raw' ),
			'status'      => 'revision',
		) );
	}

	/**
	 * Apply a HUMAN-APPROVED SEO draft to its live source page (Phase 3, controlled execution).
	 *
	 * Guardrails:
	 *  - The draft must be one created by this connector (carries _tc_growth_source_post).
	 *  - The draft must be explicitly approved by a human: meta _tc_growth_approved === '1'.
	 *    That flag can only be set by a user with `publish_posts` (see the approval meta box),
	 *    a capability the contributor-level agent user does NOT have — so the agent can request
	 *    publication but cannot self-approve it.
	 *  - Applies title, slug, and meta description only. Never touches price/availability/booking.
	 */
	public function publish_seo_draft( WP_REST_Request $request ) {
		$params   = $request->get_json_params();
		$draft_id = isset( $params['draft_id'] ) ? (int) $params['draft_id'] : 0;
		$draft    = get_post( $draft_id );

		if ( ! $draft ) {
			return new WP_Error( 'tc_growth_not_found', __( 'Draft not found.', 'tc-growth-connector' ), array( 'status' => 404 ) );
		}

		$source_id = (int) get_post_meta( $draft_id, '_tc_growth_source_post', true );
		if ( ! $source_id || ! get_post( $source_id ) ) {
			return new WP_Error( 'tc_growth_not_a_draft', __( 'Not a connector SEO draft.', 'tc-growth-connector' ), array( 'status' => 400 ) );
		}

		if ( '1' !== (string) get_post_meta( $draft_id, '_tc_growth_approved', true ) ) {
			return new WP_Error(
				'tc_growth_not_approved',
				__( 'Draft is not human-approved. A human editor must approve it first.', 'tc-growth-connector' ),
				array( 'status' => 403 )
			);
		}

		// Apply title + slug to the live source post (keeps its published status).
		$update = wp_update_post( array(
			'ID'         => $source_id,
			'post_title' => $draft->post_title,
			'post_name'  => $draft->post_name,
		), true );
		if ( is_wp_error( $update ) ) {
			return $update;
		}

		// Apply the proposed meta description to whichever SEO plugin is present.
		$meta_desc = get_post_meta( $draft_id, '_tc_growth_proposed_meta_description', true );
		if ( $meta_desc ) {
			update_post_meta( $source_id, '_yoast_wpseo_metadesc', $meta_desc );
			update_post_meta( $source_id, 'rank_math_description', $meta_desc );
		}

		// Retire the draft so it can't be applied twice.
		wp_update_post( array( 'ID' => $draft_id, 'post_status' => 'trash' ) );

		TC_Growth_Audit::log(
			wp_get_current_user()->user_login,
			'publish-seo-draft',
			'post',
			$source_id,
			array( 'draft_id' => $draft_id )
		);

		return rest_ensure_response( array(
			'source_post' => $source_id,
			'applied'     => true,
			'url'         => get_permalink( $source_id ),
		) );
	}

	/**
	 * Accept an explicit audit entry from the agent (for actions taken on external platforms).
	 */
	public function log_agent_action( WP_REST_Request $request ) {
		$params = $request->get_json_params();
		$action = isset( $params['action'] ) ? sanitize_text_field( $params['action'] ) : 'agent-action';
		$detail = isset( $params['detail'] ) && is_array( $params['detail'] ) ? $params['detail'] : array();

		TC_Growth_Audit::log( wp_get_current_user()->user_login, $action, 'external', null, $detail );
		return rest_ensure_response( array( 'logged' => true ) );
	}

	/* ------------------------------------------------------------------ HELPERS --------- */

	/**
	 * Best-effort read of a meta description from common SEO plugins.
	 *
	 * @param int $post_id Post id.
	 * @return string
	 */
	protected function read_meta_description( $post_id ) {
		// Yoast.
		$yoast = get_post_meta( $post_id, '_yoast_wpseo_metadesc', true );
		if ( $yoast ) {
			return $yoast;
		}
		// Rank Math.
		$rankmath = get_post_meta( $post_id, 'rank_math_description', true );
		if ( $rankmath ) {
			return $rankmath;
		}
		return '';
	}

	/**
	 * Extract the first occurrence of an HTML tag's text.
	 */
	protected function extract_first_tag( $html, $tag ) {
		if ( preg_match( '/<' . preg_quote( $tag, '/' ) . '[^>]*>(.*?)<\/' . preg_quote( $tag, '/' ) . '>/is', $html, $m ) ) {
			return trim( wp_strip_all_tags( $m[1] ) );
		}
		return '';
	}

	/**
	 * Extract all occurrences of an HTML tag's text.
	 */
	protected function extract_all_tags( $html, $tag ) {
		$out = array();
		if ( preg_match_all( '/<' . preg_quote( $tag, '/' ) . '[^>]*>(.*?)<\/' . preg_quote( $tag, '/' ) . '>/is', $html, $m ) ) {
			foreach ( $m[1] as $text ) {
				$out[] = trim( wp_strip_all_tags( $text ) );
			}
		}
		return $out;
	}

	/**
	 * Count internal links in content.
	 */
	protected function extract_internal_links( $html ) {
		$home  = wp_parse_url( home_url(), PHP_URL_HOST );
		$count = 0;
		if ( preg_match_all( '/href=["\']([^"\']+)["\']/i', $html, $m ) ) {
			foreach ( $m[1] as $href ) {
				$host = wp_parse_url( $href, PHP_URL_HOST );
				if ( ! $host || $host === $home ) {
					$count++;
				}
			}
		}
		return $count;
	}

	/**
	 * Count <img> tags missing a non-empty alt attribute.
	 */
	protected function count_images_missing_alt( $html ) {
		$missing = 0;
		if ( preg_match_all( '/<img\b[^>]*>/i', $html, $imgs ) ) {
			foreach ( $imgs[0] as $img ) {
				if ( ! preg_match( '/\balt=["\'][^"\']+["\']/i', $img ) ) {
					$missing++;
				}
			}
		}
		return $missing;
	}
}
