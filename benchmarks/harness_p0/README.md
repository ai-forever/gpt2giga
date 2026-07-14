# Harness P0 comparison contract

This directory freezes the offline inputs for the P0.5 Harness versus Omnigent
replacement gate. It does not install either target, use credentials, call a
model, or start a live comparison.

The manifest pins:

- Harness `0.0.1a3` at repository commit `6680aee9a7a231821887826774c475089b01c3f6`;
- Omnigent `0.5.1` at release commit `08285468e098244ac0b0bf98cb470d5c1a1a7070`
  and the SHA-256 of its published universal wheel;
- `gpt2giga` `0.2.3a2`, Codex CLI `0.144.3`, the model route, host runtime,
  five workflow contracts, 25 semantic cells, and three repetitions;
- the deterministic fixture archive and seed Git commit;
- a versioned evidence envelope with bounded, content-addressed artifacts.

Offline validation:

```bash
python scripts/harness_p0_comparison.py validate
```

Prepare one disposable cell without invoking a target:

```bash
python scripts/harness_p0_comparison.py prepare-cell \
  --output /tmp/harness-p0-cell \
  --target harness \
  --workflow read-only-analysis \
  --repetition 1
```

`prepare-cell` fails if the destination already exists. `artifact-entry` only
hashes regular files below its declared evidence root, and `validate-result`
rejects digest drift, path escape, incomplete semantic cells, invalid failure
taxonomy, and unredacted secret-like fields.

Live target execution remains a separate, explicitly approved P0.5 step. Raw
results belong outside Git until they are redacted and reviewed.
