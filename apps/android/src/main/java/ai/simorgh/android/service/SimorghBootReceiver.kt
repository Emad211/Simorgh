package ai.simorgh.android.service

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class SimorghBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (
            intent.action != Intent.ACTION_BOOT_COMPLETED &&
            intent.action != Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            return
        }

        val config = SecureConnectionStore(context).loadForBoot() ?: return
        SimorghConnectionService.start(context, config)
    }
}
