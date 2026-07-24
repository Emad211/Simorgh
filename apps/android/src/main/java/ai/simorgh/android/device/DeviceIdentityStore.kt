package ai.simorgh.android.device

import android.content.Context
import java.util.UUID

class DeviceIdentityStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun getOrCreateDeviceId(): String {
        val existing = preferences.getString(KEY_DEVICE_ID, null)
        if (!existing.isNullOrBlank()) {
            return existing
        }

        val created = UUID.randomUUID().toString()
        preferences.edit().putString(KEY_DEVICE_ID, created).apply()
        return created
    }

    private companion object {
        const val PREFERENCES_NAME = "simorgh_device_identity"
        const val KEY_DEVICE_ID = "device_id"
    }
}
