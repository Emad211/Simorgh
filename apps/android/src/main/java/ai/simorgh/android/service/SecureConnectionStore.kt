package ai.simorgh.android.service

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import ai.simorgh.android.transport.CoreConnectionConfig
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class SecureConnectionStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun save(config: CoreConnectionConfig, connectionEnabled: Boolean = true) {
        val validated = config.validated()
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val encryptedToken = cipher.doFinal(validated.deviceToken.toByteArray(Charsets.UTF_8))

        preferences.edit()
            .putString(KEY_ENDPOINT, validated.endpoint)
            .putString(KEY_TOKEN_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(KEY_TOKEN_CIPHERTEXT, Base64.encodeToString(encryptedToken, Base64.NO_WRAP))
            .putBoolean(KEY_CONNECTION_ENABLED, connectionEnabled)
            .apply()
    }

    fun load(): CoreConnectionConfig? {
        val endpoint = preferences.getString(KEY_ENDPOINT, null) ?: return null
        val encodedIv = preferences.getString(KEY_TOKEN_IV, null) ?: return null
        val encodedCiphertext = preferences.getString(KEY_TOKEN_CIPHERTEXT, null) ?: return null

        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateKey(),
                GCMParameterSpec(GCM_TAG_LENGTH_BITS, Base64.decode(encodedIv, Base64.NO_WRAP)),
            )
            val token = cipher.doFinal(
                Base64.decode(encodedCiphertext, Base64.NO_WRAP),
            ).toString(Charsets.UTF_8)
            CoreConnectionConfig(endpoint = endpoint, deviceToken = token).validated()
        }.getOrNull()
    }

    fun loadForServiceResume(): CoreConnectionConfig? = if (isConnectionEnabled()) load() else null

    fun loadForBoot(): CoreConnectionConfig? = if (isStartOnBootEnabled()) load() else null

    fun setConnectionEnabled(enabled: Boolean) {
        preferences.edit().putBoolean(KEY_CONNECTION_ENABLED, enabled).apply()
    }

    fun isConnectionEnabled(): Boolean = preferences.getBoolean(KEY_CONNECTION_ENABLED, false)

    fun setStartOnBootEnabled(enabled: Boolean) {
        preferences.edit().putBoolean(KEY_START_ON_BOOT, enabled).apply()
    }

    fun isStartOnBootEnabled(): Boolean = preferences.getBoolean(KEY_START_ON_BOOT, false)

    fun clear() {
        preferences.edit().clear().apply()
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }
        val existingKey = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existingKey != null) {
            return existingKey
        }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEY_STORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return generator.generateKey()
    }

    private companion object {
        const val PREFERENCES_NAME = "simorgh_secure_connection"
        const val KEY_ENDPOINT = "endpoint"
        const val KEY_TOKEN_IV = "device_token_iv"
        const val KEY_TOKEN_CIPHERTEXT = "device_token_ciphertext"
        const val KEY_CONNECTION_ENABLED = "connection_enabled"
        const val KEY_START_ON_BOOT = "start_on_boot"
        const val KEY_ALIAS = "simorgh_device_transport_key_v1"
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_TAG_LENGTH_BITS = 128
    }
}
