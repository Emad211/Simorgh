package ai.simorgh.android.actions

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@Serializable
enum class ActionLedgerPhase {
    @SerialName("active")
    ACTIVE,

    @SerialName("completed")
    COMPLETED,
}

@Serializable
data class PersistedActionEntry(
    @SerialName("schema_version")
    val schemaVersion: String = ACTION_LEDGER_SCHEMA_VERSION,
    @SerialName("command_envelope_id")
    val commandEnvelopeId: String,
    @SerialName("command_hash")
    val commandHash: String,
    val command: AndroidActionCommand,
    val phase: ActionLedgerPhase,
    @SerialName("result_message_id")
    val resultMessageId: String? = null,
    val result: AndroidActionResult? = null,
    @SerialName("result_acknowledged")
    val resultAcknowledged: Boolean = false,
) {
    fun validated(): PersistedActionEntry {
        require(schemaVersion == ACTION_LEDGER_SCHEMA_VERSION) {
            "unsupported action ledger schema version"
        }
        requireUuid(commandEnvelopeId, "command_envelope_id")
        requireLowercaseHex(commandHash, 64, "command_hash")
        val normalizedCommand = AndroidActionContractValidator.validate(command)
        require(normalizedCommand == command) {
            "persisted command must already be normalized"
        }

        when (phase) {
            ActionLedgerPhase.ACTIVE -> {
                require(resultMessageId == null && result == null && !resultAcknowledged) {
                    "active ledger entry cannot contain a result"
                }
            }

            ActionLedgerPhase.COMPLETED -> {
                val messageId = requireNotNull(resultMessageId) {
                    "completed ledger entry requires result_message_id"
                }
                requireUuid(messageId, "result_message_id")
                val completedResult = requireNotNull(result) {
                    "completed ledger entry requires result"
                }
                AndroidActionContractValidator.validate(completedResult)
                require(completedResult.commandId == command.commandId) {
                    "result command_id does not match persisted command"
                }
                require(completedResult.actionId == command.actionId) {
                    "result action_id does not match persisted command"
                }
            }
        }
        return this
    }

    private fun requireUuid(value: String, field: String) {
        require(runCatching { java.util.UUID.fromString(value) }.isSuccess) {
            "$field must be a UUID"
        }
    }

    private fun requireLowercaseHex(value: String, length: Int, field: String) {
        require(
            value.length == length &&
                value.all { character ->
                    character in '0'..'9' || character in 'a'..'f'
                },
        ) { "$field must be $length lowercase hexadecimal characters" }
    }
}

sealed interface ActionLedgerLoadResult {
    data object Empty : ActionLedgerLoadResult

    data class Loaded(val entry: PersistedActionEntry) : ActionLedgerLoadResult

    data class Corrupt(val detail: String) : ActionLedgerLoadResult
}

interface ActionLedger {
    fun load(): ActionLedgerLoadResult

    fun save(entry: PersistedActionEntry)

    fun clear()
}

class PersistentActionLedger(context: Context) : ActionLedger {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    override fun load(): ActionLedgerLoadResult {
        val encodedIv = preferences.getString(KEY_IV, null)
            ?: return ActionLedgerLoadResult.Empty
        val encodedCiphertext = preferences.getString(KEY_CIPHERTEXT, null)
            ?: return ActionLedgerLoadResult.Corrupt("action ledger ciphertext is missing")

        return runCatching {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                getOrCreateKey(),
                GCMParameterSpec(GCM_TAG_LENGTH_BITS, Base64.decode(encodedIv, Base64.NO_WRAP)),
            )
            val plaintext = cipher.doFinal(
                Base64.decode(encodedCiphertext, Base64.NO_WRAP),
            ).toString(Charsets.UTF_8)
            val entry = AndroidActionJson.codec
                .decodeFromString<PersistedActionEntry>(plaintext)
                .validated()
            ActionLedgerLoadResult.Loaded(entry)
        }.getOrElse { error ->
            ActionLedgerLoadResult.Corrupt(error.javaClass.simpleName)
        }
    }

    override fun save(entry: PersistedActionEntry) {
        val validated = entry.validated()
        val plaintext = AndroidActionJson.codec.encodeToString(validated)
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
        val ciphertext = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))

        val committed = preferences.edit()
            .putString(KEY_IV, Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .putString(KEY_CIPHERTEXT, Base64.encodeToString(ciphertext, Base64.NO_WRAP))
            .commit()
        check(committed) { "failed to persist encrypted action ledger" }
    }

    override fun clear() {
        preferences.edit().clear().commit()
    }

    private fun getOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEY_STORE).apply { load(null) }
        val existing = keyStore.getKey(KEY_ALIAS, null) as? SecretKey
        if (existing != null) {
            return existing
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
        const val ACTION_LEDGER_SCHEMA_VERSION = "1.0"
        const val PREFERENCES_NAME = "simorgh_action_ledger"
        const val KEY_IV = "ledger_iv"
        const val KEY_CIPHERTEXT = "ledger_ciphertext"
        const val KEY_ALIAS = "simorgh_action_ledger_key_v1"
        const val ANDROID_KEY_STORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val GCM_TAG_LENGTH_BITS = 128
    }
}

private const val ACTION_LEDGER_SCHEMA_VERSION = "1.0"
