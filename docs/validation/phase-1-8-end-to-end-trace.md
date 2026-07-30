# Phase 1.8 durable correlated end-to-end trace — final validation record

## Scope

- Tracking issue: #59.
- Earlier duplicate issue: #57.
- Implementation PR: #60.
- Base authority: Phase 1.7 merge `dab5333140da2d9cf9b982a57ede1a2d08397cf1`.
- Boundary: durable, typed, privacy-safe audit projection only.
- Excluded: live-provider staging, complete GitHub report execution/presentation, mutation, Voice, Notification, Scheduling, Channels, Delegation, MCP, Memory, Personal Work Graph and self-improvement.

## Completed authority

Phase 1.8 provides stable trace/event identities, typed event families, transactional causal sequence, in-memory/SQLite parity, exact restart replay, direct task/invocation/context/result producer projection, classifier and owned model/tool correlation, typed cancellation settlement, supersession/resolution, explicit gaps and uncertainty, whole-trace retention, independent lifespan/path ownership and privacy-safe reconstruction.

Trace never authorizes work, retries execution, mutates source authority or stores task/prompt/context/result/tool/provider body content.

## Runtime-composition acceptance

The final zero-external acceptance uses the actual budgeted classifier, governed GitHub read service, Context Compiler, specialist ownership correlation and SQLite trace store. It proves:

```text
task claim
-> classifier model start/terminal
-> routing
-> context
-> specialist start
-> GitHub tool start/terminal
```

Exact route/tool replay performs no second provider or adapter call and adds no tool usage. SQLite reopen plus retained-source reconciliation reproduces the exact same trace. Private Task, classifier and GitHub body markers are absent from the serialized trace.

## Backup, restore and incident evidence

Acceptance performs SQLite online backup while the source store is open in WAL mode, verifies a point-in-time snapshot, proves later source writes do not change the backup, restores a standalone copy without WAL/SHM sidecars and rejects a payload-corrupted copy on reopen.

## Product candidate evidence

- Product candidate: `6df6a206baf8ffbae5b31272700066a5d3c41d18`.
- Standard CI run: `30507626051` — successful.
- Core: installation, Ruff, strict MyPy and **482 tests** passed.
- JUnit: 482 tests, 0 failures, 0 errors, 0 skipped.
- Android: build, JVM tests, lint and Debug APK upload passed.
- Debug APK artifact: `8745937341`, digest `sha256:508bfd03fc0427e97701800ea8ed3d7975056a5c15e7eaeaa8ada6bfcacf8aa4`.
- Android diagnostics artifact: `8745936843`, digest `sha256:7944024116c173502420d203c1ae52dde12a9ad801b5fb0d0aeffd455bfe3c1f`.
- Core JUnit artifact: `8745928537`, digest `sha256:5ff4d04475b2db5bf4b2c1495bc056cdc35160e5d97348ab4ae24f538d31a925`.
- Core diagnostics artifact: `8745928281`, digest `sha256:afa7b308d1d6c02692c83bf0ff1f7ddb2b6d77178cf49295cc84633b374ce3b6`.
- Ordinary CI made zero live model/provider/connector/MCP or paid external calls.

## Main-synchronized closeout candidate

- Candidate: `63287034b2970fa362ed250ba7ff18d8b33059b6`.
- Standard CI run: `30508738340` — successful.
- Core: installation, Ruff, strict MyPy and **482 tests** passed.
- JUnit: 482 tests, 0 failures, 0 errors, 0 skipped.
- Android: build, JVM tests, lint and Debug APK upload passed.
- Debug APK artifact: `8746311361`, digest `sha256:16afd678f68f867f9e504c082b8bc4396560700cb79e58f03cb50eea93da5cde`.
- Android diagnostics artifact: `8746311029`, digest `sha256:4481f6a080a29b6221a54de256b3dcda33a647d8ee19bb97c00898c948930ca0`.
- Core JUnit artifact: `8746301500`, digest `sha256:f6b7384f2bc08d7a49b8ab156612c50b6291eb91138e15ddb445b1071b314383`.
- Core diagnostics artifact: `8746301261`, digest `sha256:81d8a3448b81d1d2b82ece8ed3f02709e76257690c10731e52686c7f6f715924`.
- The branch contains the real merge from current `main`, uses canonical issue #59 and preserves the Phase 1.7 closeout record.

## Final exact-head gate

This validation-pin commit must independently pass the same standard Core and Android CI. The PR body pins that final exact Head/run/artifact set before Ready-for-Review and merge.
