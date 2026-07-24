package ai.simorgh.android.transport

import kotlin.math.min

class ReconnectPolicy(
    private val baseDelayMillis: Long = 1_000,
    private val maxDelayMillis: Long = 30_000,
) {
    init {
        require(baseDelayMillis > 0) { "baseDelayMillis must be positive" }
        require(maxDelayMillis >= baseDelayMillis) {
            "maxDelayMillis must be greater than or equal to baseDelayMillis"
        }
    }

    fun delayMillis(attempt: Int): Long {
        require(attempt >= 1) { "attempt must start at 1" }
        val exponent = min(attempt - 1, 30)
        val multiplier = 1L shl exponent
        val uncapped = if (baseDelayMillis > Long.MAX_VALUE / multiplier) {
            Long.MAX_VALUE
        } else {
            baseDelayMillis * multiplier
        }
        return min(uncapped, maxDelayMillis)
    }
}
