<?php
/**
 * Plugin Name:       TC Growth Connector
 * Plugin URI:        https://github.com/lukaszkomartc/tc_ai_growth
 * Description:        Thin, secure connector that exposes controlled SEO/content/product data to
 *                     the TC AI Growth agent system and accepts AI-proposed changes as DRAFTS ONLY.
 *                     Never publishes, never touches prices, availability, bookings, or checkout.
 * Version:           0.1.0
 * Requires at least: 6.4
 * Requires PHP:      8.0
 * Author:            Tossa Cycling
 * License:           GPL-2.0-or-later
 * Text Domain:       tc-growth-connector
 *
 * @package TC_Growth_Connector
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit; // No direct access.
}

define( 'TC_GROWTH_VERSION', '0.1.0' );
define( 'TC_GROWTH_NAMESPACE', 'tc-growth/v1' );
define( 'TC_GROWTH_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );

require_once TC_GROWTH_PLUGIN_DIR . 'includes/class-tc-growth-audit.php';
require_once TC_GROWTH_PLUGIN_DIR . 'includes/class-tc-growth-auth.php';
require_once TC_GROWTH_PLUGIN_DIR . 'includes/class-tc-growth-rest.php';

/**
 * Boot the connector.
 */
function tc_growth_bootstrap() {
	TC_Growth_Audit::init();
	( new TC_Growth_REST() )->register_hooks();
}
add_action( 'plugins_loaded', 'tc_growth_bootstrap' );

/**
 * Register the private "growth asset" post type. AI-proposed assets (ad copy, GBP posts, FAQ
 * blocks, internal-link plans) are stored here as DRAFTS so they are reviewable in one place in
 * wp-admin. Not public, not queryable on the front end — it never affects the live site.
 */
function tc_growth_register_asset_cpt() {
	register_post_type( 'tc_growth_asset', array(
		'label'           => __( 'Growth Drafts', 'tc-growth-connector' ),
		'public'          => false,
		'show_ui'         => true,
		'show_in_menu'    => true,
		'menu_icon'       => 'dashicons-chart-line',
		'capability_type' => 'post',
		'supports'        => array( 'title', 'editor', 'custom-fields' ),
		'has_archive'     => false,
		'rewrite'         => false,
		'exclude_from_search' => true,
	) );
}
add_action( 'init', 'tc_growth_register_asset_cpt' );

/**
 * Human-approval meta box for connector SEO drafts.
 *
 * Approval is the gate for Phase 3 publishing: the publish-seo-draft endpoint only applies a
 * draft whose _tc_growth_approved meta is '1'. That flag is written here, and ONLY when the
 * saving user can publish_posts — a capability the contributor-level agent user does not have.
 * So the agent can propose, but only a human editor can approve.
 */
function tc_growth_add_approval_metabox() {
	foreach ( array( 'post', 'page' ) as $screen ) {
		add_meta_box(
			'tc_growth_approval',
			__( 'TC Growth — Approve to apply', 'tc-growth-connector' ),
			'tc_growth_render_approval_metabox',
			$screen,
			'side',
			'high'
		);
	}
}
add_action( 'add_meta_boxes', 'tc_growth_add_approval_metabox' );

/**
 * Render the approval checkbox — only for posts that are connector SEO drafts.
 *
 * @param WP_Post $post Post being edited.
 */
function tc_growth_render_approval_metabox( $post ) {
	$source = get_post_meta( $post->ID, '_tc_growth_source_post', true );
	if ( ! $source ) {
		echo '<p>' . esc_html__( 'Not an AI SEO draft.', 'tc-growth-connector' ) . '</p>';
		return;
	}
	if ( ! current_user_can( 'publish_posts' ) ) {
		echo '<p>' . esc_html__( 'You do not have permission to approve.', 'tc-growth-connector' ) . '</p>';
		return;
	}
	wp_nonce_field( 'tc_growth_approval', 'tc_growth_approval_nonce' );

	// Show the reviewer EVERYTHING they are approving. The proposed meta description lives in a
	// hidden custom field (it is only written to the SEO plugin's field on approved apply), so
	// without this block it is invisible in wp-admin — a review-usability gap found in the
	// 2026-07-06 validation draft test.
	$meta_desc = get_post_meta( $post->ID, '_tc_growth_proposed_meta_description', true );
	$rationale = get_post_meta( $post->ID, '_tc_growth_rationale', true );

	$source_link = get_edit_post_link( (int) $source );
	echo '<p class="description">' . esc_html__( 'Source page: ', 'tc-growth-connector' );
	if ( $source_link ) {
		echo '<a href="' . esc_url( $source_link ) . '">#' . (int) $source . '</a>';
	} else {
		echo '#' . (int) $source;
	}
	echo '</p>';

	echo '<p><strong>' . esc_html__( 'Proposed meta description', 'tc-growth-connector' ) . '</strong>';
	echo '<br /><em>' . esc_html__( '(applied to the SEO plugin field on the live page only after approval; the empty Yoast box on this draft is expected)', 'tc-growth-connector' ) . '</em></p>';
	if ( $meta_desc ) {
		// qTranslate-tagged strings are shown raw on purpose so the reviewer sees both languages.
		echo '<blockquote style="margin:0 0 8px;padding:6px 8px;background:#f6f7f7;border-left:3px solid #2271b1;white-space:pre-wrap;">' . esc_html( $meta_desc ) . '</blockquote>';
	} else {
		echo '<p class="description">' . esc_html__( '(none proposed)', 'tc-growth-connector' ) . '</p>';
	}

	if ( $rationale ) {
		echo '<p><strong>' . esc_html__( 'Agent rationale', 'tc-growth-connector' ) . '</strong></p>';
		echo '<blockquote style="margin:0 0 8px;padding:6px 8px;background:#f6f7f7;border-left:3px solid #999;white-space:pre-wrap;">' . esc_html( $rationale ) . '</blockquote>';
	}

	$checked = '1' === (string) get_post_meta( $post->ID, '_tc_growth_approved', true );
	echo '<hr /><label><input type="checkbox" name="tc_growth_approved" value="1" ' . checked( $checked, true, false ) . ' /> ';
	echo esc_html__( 'Approve: allow the agent to apply this to the live page.', 'tc-growth-connector' ) . '</label>';
}

/**
 * Persist the approval flag — guarded by nonce + publish_posts capability.
 *
 * @param int $post_id Post id.
 */
function tc_growth_save_approval( $post_id ) {
	if ( defined( 'DOING_AUTOSAVE' ) && DOING_AUTOSAVE ) {
		return;
	}
	if ( ! isset( $_POST['tc_growth_approval_nonce'] ) || ! wp_verify_nonce( sanitize_text_field( wp_unslash( $_POST['tc_growth_approval_nonce'] ) ), 'tc_growth_approval' ) ) {
		return;
	}
	if ( ! current_user_can( 'publish_posts' ) ) {
		return;
	}
	if ( ! get_post_meta( $post_id, '_tc_growth_source_post', true ) ) {
		return;
	}
	if ( isset( $_POST['tc_growth_approved'] ) && '1' === $_POST['tc_growth_approved'] ) {
		update_post_meta( $post_id, '_tc_growth_approved', '1' );
		update_post_meta( $post_id, '_tc_growth_approved_by', get_current_user_id() );
	} else {
		delete_post_meta( $post_id, '_tc_growth_approved' );
	}
}
add_action( 'save_post', 'tc_growth_save_approval' );

/**
 * On activation, create the audit table.
 */
function tc_growth_activate() {
	TC_Growth_Audit::install();
}
register_activation_hook( __FILE__, 'tc_growth_activate' );
