package ai.simorgh.android.actions

import java.security.MessageDigest

/**
 * Hash a String using an explicit, platform-independent UTF-8 encoding.
 *
 * Java's MessageDigest accepts bytes rather than text. Keeping this conversion in one
 * package-local overload prevents accidental use of the device default charset in action
 * idempotency hashes.
 */
internal fun MessageDigest.digest(value: String): ByteArray =
    digest(value.toByteArray(Charsets.UTF_8))
