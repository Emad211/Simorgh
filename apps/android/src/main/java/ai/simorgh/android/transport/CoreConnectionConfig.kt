package ai.simorgh.android.transport

import java.net.URI

data class CoreConnectionConfig(
    val endpoint: String,
    val deviceToken: String,
) {
    fun validated(): CoreConnectionConfig {
        val normalizedEndpoint = endpoint.trim()
        val uri = runCatching { URI(normalizedEndpoint) }
            .getOrElse { throw IllegalArgumentException("Core endpoint is not a valid URI", it) }
        require(uri.scheme == "ws" || uri.scheme == "wss") {
            "Core endpoint must use ws:// or wss://"
        }
        require(!uri.host.isNullOrBlank()) { "Core endpoint must include a host" }
        require(uri.userInfo == null) { "Core endpoint must not contain embedded credentials" }
        require(deviceToken.isNotBlank()) { "Device token is required" }
        return copy(endpoint = normalizedEndpoint, deviceToken = deviceToken.trim())
    }

    companion object {
        const val DEFAULT_ENDPOINT: String = "ws://10.0.2.2:8080/v1/devices/ws"
    }
}
