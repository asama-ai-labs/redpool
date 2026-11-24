## What and why

<!-- What does this change do, and why? Link the issue it closes. -->

## Checklist

- [ ] Every commit is signed off (`git commit -s`). See [CONTRIBUTING.md](../CONTRIBUTING.md).
- [ ] `ruff check`, `ruff format --check`, `mypy redpool` and `pytest` pass.
- [ ] A vendor- or model-specific rule is in that vendor's module under `normalizers/`, not in `redpool/`, a shared `base.py`, or a collector.
- [ ] If normalization changed: I regenerated the normalized outputs and the affected goldens in `fixtures/` with the scripts, ran `validate_redfish_schema.py`, and opened the matching pull request in [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures). I did not edit any `.prom` file by hand. A maintainer regenerates the models that are not in the public fixtures.
- [ ] If I touched a base normalizer or the registry: every other vendor's outputs are unchanged, or I explain each difference below.
- [ ] If I added or changed fixtures: they come from a lab or test server, they are sanitized, and the `fixtures` pointer here matches my pull request in redpool-fixtures.
- [ ] I added or updated a test.
- [ ] I added a line to `CHANGELOG.md` under "Unreleased" for anything a user would notice.

## Fixtures and goldens affected

<!-- Which vendor/model outputs changed, and why each difference is expected. -->
