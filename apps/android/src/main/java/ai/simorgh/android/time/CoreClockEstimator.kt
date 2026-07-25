package ai.simorgh.android.time

import android.os.SystemClock
import kotlin.math.abs

data class CoreClockReading(
    val generation: Long,
    val estimatedCoreTimeMs: Long,
    val earliestCoreTimeMs: Long,
    val latestCoreTimeMs: Long,
    val uncertaintyMs: Long,
    val sampleAgeMs: Long,
    val lastRoundTripTimeMs: Long,
    val sampleCount: Int,
    val discontinuityCount: Int,
    val wallClockJumpCount: Int,
)

enum class CoreDeadlineUnavailableReason {
    INVALID_DEADLINE,
    CLOCK_UNAVAILABLE,
    UNCERTAINTY,
    EXPIRED,
}

sealed interface CoreDeadlineBudget {
    data class Available(
        val guaranteedRemainingMs: Long,
        val reading: CoreClockReading,
    ) : CoreDeadlineBudget

    data class Unavailable(
        val kind: CoreDeadlineUnavailableReason,
        val reason: String,
        val reading: CoreClockReading? = null,
    ) : CoreDeadlineBudget
}

data class CoreClockSampleOutcome(
    val accepted: Boolean,
    val reading: CoreClockReading?,
    val wallClockJumpDetected: Boolean,
    val coreDiscontinuityDetected: Boolean,
    val detail: String,
)

interface CoreClock {
    fun elapsedRealtimeMs(): Long

    fun reading(): CoreClockReading?

    fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget

    fun estimatedCoreTimeMs(): Long? = reading()?.estimatedCoreTimeMs
}

class CoreClockEstimator(
    private val monotonicMillis: () -> Long = SystemClock::elapsedRealtime,
    private val wallClockMillis: () -> Long = System::currentTimeMillis,
    private val maximumEstimateAgeMs: Long = DEFAULT_MAXIMUM_ESTIMATE_AGE_MS,
    private val wallClockJumpThresholdMs: Long = DEFAULT_WALL_CLOCK_JUMP_THRESHOLD_MS,
    private val coreDiscontinuityThresholdMs: Long = DEFAULT_CORE_DISCONTINUITY_THRESHOLD_MS,
) : CoreClock {
    private val lock = Any()

    private var generation: Long? = null
    private var lowerOffsetMs: Long? = null
    private var upperOffsetMs: Long? = null
    private var lastSampleReceivedElapsedMs: Long? = null
    private var lastRoundTripTimeMs: Long = 0
    private var sampleCount: Int = 0
    private var estimateStable: Boolean = false
    private var discontinuityCount: Int = 0
    private var wallClockJumpCount: Int = 0
    private var wallAnchorElapsedMs: Long? = null
    private var wallAnchorTimeMs: Long? = null

    init {
        require(maximumEstimateAgeMs > 0)
        require(wallClockJumpThresholdMs >= 0)
        require(coreDiscontinuityThresholdMs >= 0)
    }

    fun beginGeneration(newGeneration: Long) {
        require(newGeneration >= 0)
        val elapsed = monotonicMillis().coerceAtLeast(0)
        val wall = wallClockMillis().coerceAtLeast(0)
        synchronized(lock) {
            generation = newGeneration
            lowerOffsetMs = null
            upperOffsetMs = null
            lastSampleReceivedElapsedMs = null
            lastRoundTripTimeMs = 0
            sampleCount = 0
            estimateStable = false
            discontinuityCount = 0
            wallClockJumpCount = 0
            wallAnchorElapsedMs = elapsed
            wallAnchorTimeMs = wall
        }
    }

    fun invalidate(expectedGeneration: Long? = null) {
        synchronized(lock) {
            if (expectedGeneration != null && generation != expectedGeneration) {
                return
            }
            generation = null
            lowerOffsetMs = null
            upperOffsetMs = null
            lastSampleReceivedElapsedMs = null
            lastRoundTripTimeMs = 0
            sampleCount = 0
            estimateStable = false
            wallAnchorElapsedMs = null
            wallAnchorTimeMs = null
        }
    }

    fun recordSample(
        sampleGeneration: Long,
        requestSentElapsedMs: Long,
        responseReceivedElapsedMs: Long,
        serverTimeMs: Long,
        responseReceivedWallClockMs: Long = wallClockMillis(),
    ): CoreClockSampleOutcome {
        if (
            sampleGeneration < 0 ||
            requestSentElapsedMs < 0 ||
            responseReceivedElapsedMs < requestSentElapsedMs ||
            serverTimeMs < 0 ||
            responseReceivedWallClockMs < 0
        ) {
            return CoreClockSampleOutcome(
                accepted = false,
                reading = reading(),
                wallClockJumpDetected = false,
                coreDiscontinuityDetected = false,
                detail = "clock sample contained invalid time values",
            )
        }

        val roundTripTimeMs = responseReceivedElapsedMs - requestSentElapsedMs
        val sampleLowerOffset = saturatingSubtract(serverTimeMs, responseReceivedElapsedMs)
        val sampleUpperOffset = saturatingSubtract(serverTimeMs, requestSentElapsedMs)

        var wallJump = false
        var coreDiscontinuity = false
        synchronized(lock) {
            if (generation != sampleGeneration) {
                return CoreClockSampleOutcome(
                    accepted = false,
                    reading = readingLocked(responseReceivedElapsedMs),
                    wallClockJumpDetected = false,
                    coreDiscontinuityDetected = false,
                    detail = "clock sample belongs to an obsolete connection generation",
                )
            }

            wallJump = detectWallClockJumpLocked(
                elapsedMs = responseReceivedElapsedMs,
                wallTimeMs = responseReceivedWallClockMs,
            )

            val currentLower = lowerOffsetMs
            val currentUpper = upperOffsetMs
            if (currentLower == null || currentUpper == null) {
                lowerOffsetMs = sampleLowerOffset
                upperOffsetMs = sampleUpperOffset
                estimateStable = true
            } else {
                val intersectionLower = maxOf(currentLower, sampleLowerOffset)
                val intersectionUpper = minOf(currentUpper, sampleUpperOffset)
                if (intersectionLower <= intersectionUpper) {
                    lowerOffsetMs = intersectionLower
                    upperOffsetMs = intersectionUpper
                    estimateStable = true
                } else {
                    val gap = if (sampleLowerOffset > currentUpper) {
                        nonNegativeDifference(sampleLowerOffset, currentUpper)
                    } else {
                        nonNegativeDifference(currentLower, sampleUpperOffset)
                    }
                    if (gap > coreDiscontinuityThresholdMs) {
                        lowerOffsetMs = sampleLowerOffset
                        upperOffsetMs = sampleUpperOffset
                        estimateStable = false
                        discontinuityCount += 1
                        coreDiscontinuity = true
                    } else {
                        lowerOffsetMs = minOf(currentLower, sampleLowerOffset)
                        upperOffsetMs = maxOf(currentUpper, sampleUpperOffset)
                        estimateStable = true
                    }
                }
            }

            sampleCount += 1
            lastSampleReceivedElapsedMs = responseReceivedElapsedMs
            lastRoundTripTimeMs = roundTripTimeMs
        }

        return CoreClockSampleOutcome(
            accepted = true,
            reading = readingAt(responseReceivedElapsedMs),
            wallClockJumpDetected = wallJump,
            coreDiscontinuityDetected = coreDiscontinuity,
            detail = when {
                coreDiscontinuity ->
                    "Core clock interval changed discontinuously; another consistent sample is required"
                wallJump ->
                    "device wall clock jumped; Core estimate remains anchored to elapsedRealtime"
                else -> "Core clock sample accepted"
            },
        )
    }

    override fun elapsedRealtimeMs(): Long = monotonicMillis().coerceAtLeast(0)

    override fun reading(): CoreClockReading? = readingAt(elapsedRealtimeMs())

    override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget {
        if (deadlineCoreTimeMs < 0) {
            return CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.INVALID_DEADLINE,
                reason = "deadline cannot be negative",
            )
        }
        val current = reading()
            ?: return CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.CLOCK_UNAVAILABLE,
                reason = "Core clock estimate is unavailable, unstable, or stale",
            )
        val centeredRemaining = saturatingSubtract(
            deadlineCoreTimeMs,
            current.estimatedCoreTimeMs,
        )
        if (centeredRemaining <= current.uncertaintyMs) {
            return CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.UNCERTAINTY,
                reason = "clock uncertainty consumes the remaining command deadline budget",
                reading = current,
            )
        }
        val guaranteedRemaining = saturatingSubtract(
            deadlineCoreTimeMs,
            current.latestCoreTimeMs,
        )
        if (guaranteedRemaining <= 0) {
            return CoreDeadlineBudget.Unavailable(
                kind = CoreDeadlineUnavailableReason.EXPIRED,
                reason = "command deadline has elapsed in the bounded Core clock interval",
                reading = current,
            )
        }
        return CoreDeadlineBudget.Available(
            guaranteedRemainingMs = guaranteedRemaining,
            reading = current,
        )
    }

    private fun readingAt(nowElapsedMs: Long): CoreClockReading? = synchronized(lock) {
        readingLocked(nowElapsedMs)
    }

    private fun readingLocked(nowElapsedMs: Long): CoreClockReading? {
        val currentGeneration = generation ?: return null
        val lower = lowerOffsetMs ?: return null
        val upper = upperOffsetMs ?: return null
        val sampledAt = lastSampleReceivedElapsedMs ?: return null
        if (!estimateStable || nowElapsedMs < sampledAt) {
            return null
        }
        val age = nowElapsedMs - sampledAt
        if (age > maximumEstimateAgeMs) {
            return null
        }

        val earliest = saturatingAdd(nowElapsedMs, lower)
        val latest = saturatingAdd(nowElapsedMs, upper)
        val width = nonNegativeDifference(latest, earliest)
        val uncertainty = halfCeiling(width)
        val estimate = midpoint(earliest, latest)
        return CoreClockReading(
            generation = currentGeneration,
            estimatedCoreTimeMs = estimate,
            earliestCoreTimeMs = earliest,
            latestCoreTimeMs = latest,
            uncertaintyMs = uncertainty,
            sampleAgeMs = age,
            lastRoundTripTimeMs = lastRoundTripTimeMs,
            sampleCount = sampleCount,
            discontinuityCount = discontinuityCount,
            wallClockJumpCount = wallClockJumpCount,
        )
    }

    private fun detectWallClockJumpLocked(
        elapsedMs: Long,
        wallTimeMs: Long,
    ): Boolean {
        val anchorElapsed = wallAnchorElapsedMs
        val anchorWall = wallAnchorTimeMs
        if (anchorElapsed == null || anchorWall == null || elapsedMs < anchorElapsed) {
            wallAnchorElapsedMs = elapsedMs
            wallAnchorTimeMs = wallTimeMs
            return false
        }
        val expectedWallDelta = elapsedMs - anchorElapsed
        val actualWallDelta = wallTimeMs - anchorWall
        val jump = absoluteDifference(expectedWallDelta, actualWallDelta) >
            wallClockJumpThresholdMs
        if (jump) {
            wallClockJumpCount += 1
            wallAnchorElapsedMs = elapsedMs
            wallAnchorTimeMs = wallTimeMs
        }
        return jump
    }

    private fun absoluteDifference(left: Long, right: Long): Long {
        val difference = saturatingSubtract(left, right)
        return if (difference == Long.MIN_VALUE) Long.MAX_VALUE else abs(difference)
    }

    private fun nonNegativeDifference(upper: Long, lower: Long): Long {
        if (upper <= lower) {
            return 0
        }
        return if (upper - lower < 0) Long.MAX_VALUE else upper - lower
    }

    private fun halfCeiling(value: Long): Long = value / 2 + value % 2

    private fun midpoint(lower: Long, upper: Long): Long =
        (lower and upper) + ((lower xor upper) shr 1)

    private fun saturatingAdd(left: Long, right: Long): Long = when {
        right > 0 && left > Long.MAX_VALUE - right -> Long.MAX_VALUE
        right < 0 && left < Long.MIN_VALUE - right -> Long.MIN_VALUE
        else -> left + right
    }

    private fun saturatingSubtract(left: Long, right: Long): Long = when {
        right > 0 && left < Long.MIN_VALUE + right -> Long.MIN_VALUE
        right < 0 && left > Long.MAX_VALUE + right -> Long.MAX_VALUE
        else -> left - right
    }

    private companion object {
        const val DEFAULT_MAXIMUM_ESTIMATE_AGE_MS = 5 * 60 * 1_000L
        const val DEFAULT_WALL_CLOCK_JUMP_THRESHOLD_MS = 2_000L
        const val DEFAULT_CORE_DISCONTINUITY_THRESHOLD_MS = 2_000L
    }
}

object CoreClockBus : CoreClock {
    val estimator: CoreClockEstimator = CoreClockEstimator()

    override fun elapsedRealtimeMs(): Long = estimator.elapsedRealtimeMs()

    override fun reading(): CoreClockReading? = estimator.reading()

    override fun deadlineBudget(deadlineCoreTimeMs: Long): CoreDeadlineBudget =
        estimator.deadlineBudget(deadlineCoreTimeMs)
}
