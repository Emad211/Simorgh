# Phase 1.7 context compiler — start record

- Tracking issue: #55
- Parent issue: #36
- Branch: `core/context-compiler`
- Base Phase 1.6 merge: `8fd7cb31275d037cb50a4da0ad86c7871f1be13f`
- Status: architecture and implementation starting

## Trust boundary

Phase 1.7 introduces one Core-owned, zero-external context compiler. It compiles a small deterministic bundle for an already-selected specialist from existing native authorities:

```text
durable task authority
  + exact specialist policy/capability subset
  + remaining budget/deadline/cancellation state
  + exact output/result schema
  + approved typed evidence/result references
  + reviewed tool-schema projections
  + explicitly typed project/goal/decision inputs where supplied
  → bounded taint-aware context bundle
  → canonical ID and SHA-256
  → immutable durable replay
```

The compiler does not execute a model, tool, connector, specialist or Android action. It does not introduce Memory, a Work Graph, embeddings, vector search, dynamic tool discovery or model-generated summarization.

## Required invariants

- trusted authority and untrusted data are different typed sections;
- tainted GitHub/tool/user text can provide data but never instructions, schemas or permissions;
- task, specialist, tool, output-schema, privacy, retention, freshness, budget, deadline and cancellation authority are intersected before commit;
- identical authoritative inputs produce byte-identical canonical content, bundle ID and SHA-256;
- source ordering cannot change canonical output;
- required trusted sections are never silently truncated;
- optional untrusted evidence may be deterministically omitted/truncated with a typed report;
- every section has stable identity, trust label, source hash, byte count and estimated-token count;
- stale required evidence fails closed; stale optional evidence is omitted explicitly;
- strictest admitted privacy/retention and taint survive replay;
- cancelled/expired/fenced work cannot create or hand off a new bundle;
- compilation and replay use zero model/tool/connector/specialist calls and zero usage charge;
- private body text never enters traces, failures or status projections.

## Planned native components

- versioned context contracts and trust/source enums;
- reviewed compiler policy and limits;
- deterministic UTF-8-safe token estimator and compaction rules;
- exact tool/output-schema projections;
- compiler service bound to task/specialist/result/evidence/cancellation authorities;
- immutable in-memory and SQLite WAL context bundle stores;
- privacy-safe compiler trace events;
- acceptance tests for injection resistance, canonical determinism, limits, freshness, privacy, cancellation races, corruption and restart replay;
- ADR, operations guide and exact-head validation record.

## Explicit non-goals

No live provider/connector call, tool execution, mutation, final Persian GitHub report, complete trace overhaul, Voice, Notification, Scheduling, Channels, Delegation, MCP, Memory, Work Graph or new Android behavior.

- Final race hardening rechecks cancellation/deadline authority after material admission and before canonical assembly; the focused test proves assembly and durable claim are never entered when the fence wins.
