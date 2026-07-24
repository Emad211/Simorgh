package ai.simorgh.android.transport

import android.content.Context

class CoreConnectionPreferences(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun loadEndpoint(): String = preferences.getString(
        KEY_ENDPOINT,
        CoreConnectionConfig.DEFAULT_ENDPOINT,
    ) ?: CoreConnectionConfig.DEFAULT_ENDPOINT

    fun saveEndpoint(endpoint: String) {
        preferences.edit().putString(KEY_ENDPOINT, endpoint).apply()
    }

    private companion object {
        const val PREFERENCES_NAME = "simorgh_core_connection"
        const val KEY_ENDPOINT = "endpoint"
    }
}
