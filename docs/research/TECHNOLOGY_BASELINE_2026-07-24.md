# Technology Baseline — 2026-07-24

This document records externally verified assumptions that influence the initial architecture. Re-check these sources before changing provider integrations or relying on platform-specific behavior.

## AvalAI

### Verified capabilities

- AvalAI supports the official OpenAI SDKs through a custom base URL.
- OpenAI-compatible base URL: `https://api.avalai.ir/v1`.
- The documented JavaScript example uses the Responses API.
- Available models can be listed through the authenticated `/v1/models` endpoint or the public `/public/models` endpoint.
- AvalAI also exposes a User API under `https://api.avalai.ir/user/v1` for credit, transaction, provider, model, and cost data.
- User API transaction retention is guaranteed for at least 90 days; Simorgh must persist its own long-term cost ledger.

### Architectural consequence

The first provider adapter uses the official OpenAI SDK, but Simorgh owns a provider-neutral interface and a separate cost/usage ledger.

### Sources

- https://docs.avalai.ir/en/libraries
- https://docs.avalai.ir/en/quickstart
- https://docs.avalai.ir/en/api-reference/user

## Android UI operation

### Verified capabilities

- `AccessibilityService` can receive UI events and may query active-window content when configured for that capability.
- Gesture dispatch is available through `dispatchGesture` for services declaring gesture capability.
- Android exposes accessibility input-method APIs from API level 33 when the service enables the appropriate flag.
- The service lifecycle is controlled by the Android system and becomes active after the user enables it in device settings.
- Accessibility nodes and screenshots provide different information; the architecture should support both.

### Architectural consequence

The generic operator uses a hybrid accessibility-tree and vision strategy. UI actions are device-side and always followed by a fresh observation.

### Sources

- https://developer.android.com/reference/android/accessibilityservice/AccessibilityService
- https://developer.android.com/reference/android/accessibilityservice/GestureDescription
- https://developer.android.com/reference/android/accessibilityservice/InputMethod
- https://developer.android.com/guide/topics/ui/accessibility/service

## Android screen capture

### Verified capabilities

- MediaProjection grants an application the ability to capture screen content through a user-started capture session.
- The capture stream is rendered through a virtual display.
- Android 14 introduced single-application screen sharing in addition to full-display sharing.

### Architectural consequence

Screen capture is a long-lived device capability session managed by the Android app, not a server-side operation. Vision calls receive bounded artifacts rather than unrestricted live display access.

### Sources

- https://developer.android.com/reference/android/media/projection/MediaProjection
- https://developer.android.com/media/grow/media-projection

## SEO and analytics integrations

### Google Search Console

The Search Console API supports search analytics queries, verified-site listing, and sitemap management. It is a primary data source for the SEO agent.

Source: https://developers.google.com/webmaster-tools/

### Google Analytics

The Google Analytics Data API provides report, batch, pivot, realtime, metadata, compatibility, and audience-related methods. It returns report data aligned with the property's configured reporting identity.

Source: https://developers.google.com/analytics/devguides/reporting/data/v1

### Google Ads

The Google Ads API provides read and mutate services across campaigns, assets, audiences, bidding, conversions, reports, recommendations, and batch jobs. Connector versions must be isolated because the API is versioned and updated regularly.

Sources:

- https://developers.google.com/google-ads/api/docs/concepts/overview
- https://developers.google.com/google-ads/api/reference/rpc/v22/overview

### Google Business Profile

Business Profile APIs expose business information, posts, media, reviews, notifications, Q&A, and performance-related operations across multiple service endpoints. Access and service versions must be verified before implementation.

Source: https://developers.google.com/my-business/ref_overview

## Engineering implications

1. Model names and capabilities are runtime data and must not be embedded throughout the codebase.
2. Android operation is an observation-action-verification system, not coordinate scripting.
3. SEO and marketing agents require first-party measurement connectors before content automation is considered complete.
4. Cost attribution must combine local mission traces with AvalAI transaction data.
5. Platform APIs are versioned dependencies; every connector requires capability metadata and contract tests.
