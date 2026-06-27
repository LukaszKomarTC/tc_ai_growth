<?php
/**
 * Authentication & authorization for connector endpoints.
 *
 * Two layers:
 *   1. WordPress Application Password (standard REST auth) → identifies a dedicated agent user.
 *   2. A shared HMAC signature header → proves the request came from our orchestrator and was
 *      not tampered with. Defends against a leaked app password alone being enough to write.
 *
 * The signing secret is stored as a constant in wp-config.php:
 *   define( 'TC_GROWTH_SIGNING_KEY', '...32+ random bytes...' );
 *
 * @package TC_Growth_Connector
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Auth helpers shared by the REST controller.
 */
class TC_Growth_Auth {

	const SIGNATURE_HEADER = 'X-TC-Signature';
	const TIMESTAMP_HEADER = 'X-TC-Timestamp';
	const MAX_SKEW_SECONDS = 300;

	/**
	 * Capability the agent user must hold. We use a dedicated capability rather than a built-in
	 * role so the agent identity can be tightly scoped.
	 *
	 * @return string
	 */
	public static function required_capability() {
		return 'edit_posts';
	}

	/**
	 * Permission callback for READ endpoints: logged-in agent user + valid signature.
	 *
	 * @param WP_REST_Request $request Request.
	 * @return true|WP_Error
	 */
	public static function can_read( WP_REST_Request $request ) {
		return self::authorize( $request, self::required_capability() );
	}

	/**
	 * Permission callback for DRAFT-WRITE endpoints. Same surface as read for now (drafts only),
	 * kept separate so Phase 3 can tighten it independently.
	 *
	 * @param WP_REST_Request $request Request.
	 * @return true|WP_Error
	 */
	public static function can_write_draft( WP_REST_Request $request ) {
		return self::authorize( $request, self::required_capability() );
	}

	/**
	 * Core authorization: capability check + HMAC signature verification.
	 *
	 * @param WP_REST_Request $request    Request.
	 * @param string          $capability Capability required.
	 * @return true|WP_Error
	 */
	protected static function authorize( WP_REST_Request $request, $capability ) {
		if ( ! is_user_logged_in() || ! current_user_can( $capability ) ) {
			return new WP_Error(
				'tc_growth_forbidden',
				__( 'Authentication required.', 'tc-growth-connector' ),
				array( 'status' => 401 )
			);
		}

		$signature_ok = self::verify_signature( $request );
		if ( is_wp_error( $signature_ok ) ) {
			return $signature_ok;
		}

		return true;
	}

	/**
	 * Verify the HMAC signature over "{timestamp}.{method}.{route}.{body}".
	 *
	 * @param WP_REST_Request $request Request.
	 * @return true|WP_Error
	 */
	protected static function verify_signature( WP_REST_Request $request ) {
		if ( ! defined( 'TC_GROWTH_SIGNING_KEY' ) || '' === TC_GROWTH_SIGNING_KEY ) {
			return new WP_Error(
				'tc_growth_misconfigured',
				__( 'TC_GROWTH_SIGNING_KEY is not configured.', 'tc-growth-connector' ),
				array( 'status' => 500 )
			);
		}

		$signature = $request->get_header( self::SIGNATURE_HEADER );
		$timestamp = $request->get_header( self::TIMESTAMP_HEADER );

		if ( empty( $signature ) || empty( $timestamp ) ) {
			return new WP_Error(
				'tc_growth_unsigned',
				__( 'Missing signature headers.', 'tc-growth-connector' ),
				array( 'status' => 401 )
			);
		}

		// Reject stale requests to limit replay.
		if ( abs( time() - (int) $timestamp ) > self::MAX_SKEW_SECONDS ) {
			return new WP_Error(
				'tc_growth_stale',
				__( 'Signature timestamp out of range.', 'tc-growth-connector' ),
				array( 'status' => 401 )
			);
		}

		$method  = $request->get_method();
		$route   = $request->get_route();
		$body    = $request->get_body();
		$payload = $timestamp . '.' . $method . '.' . $route . '.' . $body;
		$expected = hash_hmac( 'sha256', $payload, TC_GROWTH_SIGNING_KEY );

		if ( ! hash_equals( $expected, (string) $signature ) ) {
			return new WP_Error(
				'tc_growth_bad_signature',
				__( 'Signature verification failed.', 'tc-growth-connector' ),
				array( 'status' => 401 )
			);
		}

		return true;
	}
}
