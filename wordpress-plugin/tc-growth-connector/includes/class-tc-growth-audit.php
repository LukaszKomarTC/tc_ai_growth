<?php
/**
 * Audit log for every agent action.
 *
 * @package TC_Growth_Connector
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Stores an append-only record of what the agent read and which drafts it created.
 */
class TC_Growth_Audit {

	const TABLE = 'tc_growth_audit';

	/**
	 * Nothing dynamic to hook yet; placeholder for future filters.
	 */
	public static function init() {}

	/**
	 * Fully-qualified table name.
	 *
	 * @return string
	 */
	public static function table_name() {
		global $wpdb;
		return $wpdb->prefix . self::TABLE;
	}

	/**
	 * Create the audit table.
	 */
	public static function install() {
		global $wpdb;
		$table           = self::table_name();
		$charset_collate = $wpdb->get_charset_collate();

		$sql = "CREATE TABLE {$table} (
			id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
			created_at DATETIME NOT NULL,
			actor VARCHAR(128) NOT NULL,
			action VARCHAR(64) NOT NULL,
			object_type VARCHAR(64) NULL,
			object_id BIGINT UNSIGNED NULL,
			detail LONGTEXT NULL,
			PRIMARY KEY  (id),
			KEY action (action),
			KEY created_at (created_at)
		) {$charset_collate};";

		require_once ABSPATH . 'wp-admin/includes/upgrade.php';
		dbDelta( $sql );
	}

	/**
	 * Record an action.
	 *
	 * @param string      $actor       Identity making the call (e.g. agent user login).
	 * @param string      $action      Short action key, e.g. "create-seo-draft".
	 * @param string|null $object_type Optional object type, e.g. "post".
	 * @param int|null    $object_id   Optional object id.
	 * @param array       $detail      Arbitrary structured detail (stored as JSON).
	 */
	public static function log( $actor, $action, $object_type = null, $object_id = null, $detail = array() ) {
		global $wpdb;
		$wpdb->insert(
			self::table_name(),
			array(
				'created_at'  => current_time( 'mysql', true ),
				'actor'       => substr( (string) $actor, 0, 128 ),
				'action'      => substr( (string) $action, 0, 64 ),
				'object_type' => $object_type ? substr( (string) $object_type, 0, 64 ) : null,
				'object_id'   => $object_id ? (int) $object_id : null,
				'detail'      => wp_json_encode( $detail ),
			),
			array( '%s', '%s', '%s', '%s', '%d', '%s' )
		);
	}
}
