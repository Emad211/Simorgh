package ai.simorgh.android.actions

import org.junit.Assert.assertEquals
import org.junit.Test

class OpenAppDeepLinkContractTest {
    @Test
    fun `front-door open accepts target package as complete goal`() {
        val validated = AndroidActionContractValidator.validate(
            command(uri = null, nodePackage = null),
        )

        assertEquals(TARGET_PACKAGE, (validated.operation as OpenAppOperation).packageName)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `deep link without destination predicate is rejected`() {
        AndroidActionContractValidator.validate(
            command(uri = TARGET_URI, nodePackage = null),
        )
    }

    @Test
    fun `deep link accepts a target-package destination predicate`() {
        val validated = AndroidActionContractValidator.validate(
            command(uri = TARGET_URI, nodePackage = TARGET_PACKAGE),
        )

        assertEquals(2, validated.verification.predicates.size)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `open app rejects node predicate from another package`() {
        AndroidActionContractValidator.validate(
            command(uri = TARGET_URI, nodePackage = OTHER_PACKAGE),
        )
    }

    private fun command(
        uri: String?,
        nodePackage: String?,
    ): AndroidActionCommand {
        val predicates = buildList<UiPredicate> {
            add(ActivePackageEqualsPredicate(TARGET_PACKAGE))
            if (nodePackage != null) {
                add(
                    NodeExistsPredicate(
                        AndroidNodeSelector(
                            packageName = nodePackage,
                            viewId = "$nodePackage:id/item_42",
                        ),
                    ),
                )
            }
        }
        return AndroidActionCommand(
            commandId = COMMAND_ID,
            actionId = ACTION_ID,
            issuedAtMs = 1_000,
            deadlineAtMs = 11_000,
            precondition = ObservationPrecondition(),
            operation = OpenAppOperation(
                packageName = TARGET_PACKAGE,
                uri = uri,
            ),
            verification = AndroidVerificationPolicy(
                predicates = predicates,
                timeoutMs = 1_000,
                stableSamples = 1,
            ),
        )
    }

    private companion object {
        const val COMMAND_ID = "11111111-1111-1111-1111-111111111111"
        const val ACTION_ID = "22222222-2222-2222-2222-222222222222"
        const val TARGET_PACKAGE = "com.example.target"
        const val OTHER_PACKAGE = "com.example.other"
        const val TARGET_URI = "example://items/42"
    }
}
