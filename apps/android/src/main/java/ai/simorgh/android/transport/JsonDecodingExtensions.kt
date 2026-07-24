package ai.simorgh.android.transport

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.serializer

/** Decode a JSON element with the reified serializer for the requested transport type. */
internal inline fun <reified T> Json.decodeFromJsonElement(element: JsonElement): T =
    decodeFromJsonElement(serializer<T>(), element)
