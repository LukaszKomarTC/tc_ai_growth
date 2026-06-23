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
 * On activation, create the audit table.
 */
function tc_growth_activate() {
	TC_Growth_Audit::install();
}
register_activation_hook( __FILE__, 'tc_growth_activate' );
