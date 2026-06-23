<?php
/**
 * Uninstall handler.
 *
 * The connector is designed to be fully removable without affecting rentals, checkout,
 * resources, orders, payments, or the booking plugin. Uninstalling drops ONLY the connector's
 * own audit table and its own post meta. It never touches WooCommerce or booking data.
 *
 * @package TC_Growth_Connector
 */

if ( ! defined( 'WP_UNINSTALL_PLUGIN' ) ) {
	exit;
}

global $wpdb;

// Drop the connector audit table only.
$table = $wpdb->prefix . 'tc_growth_audit';
$wpdb->query( "DROP TABLE IF EXISTS {$table}" ); // phpcs:ignore WordPress.DB.PreparedSQL

// Remove only the connector's own post meta keys (prefixed _tc_growth_).
$wpdb->query(
	"DELETE FROM {$wpdb->postmeta} WHERE meta_key LIKE '\\_tc\\_growth\\_%'" // phpcs:ignore WordPress.DB.PreparedSQL
);
