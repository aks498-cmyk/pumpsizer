<!-- Keep it short. Delete sections that don't apply. -->

## What & why

<!-- One or two sentences: what this changes and the reason. Link the issue: Closes #NN -->

## Type

- [ ] Bug fix
- [ ] New feature / capability
- [ ] Calculation / model change (numbers move)
- [ ] Catalogue or data-table update
- [ ] Docs / tooling / CI only

## Notes for the reviewer

<!-- Anything non-obvious: a method reference, a trade-off, a known limitation,
     why a magic number is what it is. -->

## Checklist

- [ ] `py -m pytest -q` passes locally (the pre-push hook enforces this)
- [ ] New behaviour has a test; changed numbers have a comment saying why
- [ ] Physics stays SI-internal; unit conversion only at the edges
- [ ] Datasheet-digitised catalogue entries set `verified: true` only after a second check
- [ ] README / `pumpsizer schema` / `docs/` updated if inputs or outputs changed
- [ ] Commit messages have an imperative subject and a *why* in the body
