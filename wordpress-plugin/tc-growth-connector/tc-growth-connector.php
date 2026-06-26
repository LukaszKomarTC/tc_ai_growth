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
 * On activation, create the audit table.
 */
function tc_growth_activate() {
	TC_Growth_Audit::install();
}
register_activation_hook( __FILE__, 'tc_growth_activate' );
