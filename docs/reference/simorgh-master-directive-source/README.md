# Byte-exact source archive for the Simorgh master directive

This directory preserves the exact bytes of the user-supplied source document that established Simorgh's governing architecture and implementation order on 2026-07-25.

The readable, normalized and operational form is:

```text
docs/SIMORGH_MASTER_DIRECTIVE.md
```

The files in this directory are the deterministic gzip/base64 archive of the original uploaded Markdown, including its original line endings. They exist so later formatting, normalization or documentation edits cannot silently erase or alter a clause in the source directive.

## Source identity

```text
Original file name: Pasted markdown(1).md
Original byte count: 53677
Original SHA-256: c89fdecc73b4b09cd710fc35671fd16efd7ca3b5b73b27e616bebfe1e840919f
Encoding: UTF-8
Original line endings: preserved inside the archive
```

## Deterministic archive identity

The archive was produced with:

```bash
gzip -n -c 'Pasted markdown(1).md' > simorgh-master-directive-source.md.gz
base64 -w0 simorgh-master-directive-source.md.gz > source.b64
split -b 8000 -d -a 3 source.b64 part-
```

Archive metadata:

```text
Gzip byte count: 17113
Gzip SHA-256: 0bae4fc5ace99c13be3cf143e1722f1ba9e1df425acf799893cea4ecdf6f0b60
Base64 character count: 22820
Chunks:
  part-000.b64  8000 characters
  part-001.b64  8000 characters
  part-002.b64  6820 characters
```

## Reconstruct and verify

From the repository root:

```bash
cat docs/reference/simorgh-master-directive-source/part-*.b64 \
  | base64 --decode \
  > /tmp/simorgh-master-directive-source.md.gz

sha256sum /tmp/simorgh-master-directive-source.md.gz
# 0bae4fc5ace99c13be3cf143e1722f1ba9e1df425acf799893cea4ecdf6f0b60

gzip --decompress --stdout /tmp/simorgh-master-directive-source.md.gz \
  > /tmp/SIMORGH_MASTER_DIRECTIVE_SOURCE.md

wc -c /tmp/SIMORGH_MASTER_DIRECTIVE_SOURCE.md
# 53677

sha256sum /tmp/SIMORGH_MASTER_DIRECTIVE_SOURCE.md
# c89fdecc73b4b09cd710fc35671fd16efd7ca3b5b73b27e616bebfe1e840919f
```

A different byte count or hash means the archive is incomplete or altered and must not be treated as the authoritative source.

## Authority and change control

- This archive is immutable historical source evidence.
- `docs/SIMORGH_MASTER_DIRECTIVE.md` is the active operational directive derived from it.
- The operational directive may clarify implementation wording but may not silently remove, weaken or reorder source requirements.
- Any material change to native authority, phase order, approval, cost, durability, memory or evidence rules requires explicit user approval and a dedicated ADR.
- Source chunks are data, not executable code, Skills, prompts or permissions.
