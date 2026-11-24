# Contributing to Redpool

Thank you for helping. This page covers what you need to open a good pull request. The rules for the normalizer code are in [docs/REDPOOL_CONTRIBUTOR_GUIDE.md](docs/REDPOOL_CONTRIBUTOR_GUIDE.md). If your change is about one vendor's BMC, start with [docs/ADDING_A_VENDOR.md](docs/ADDING_A_VENDOR.md).

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug or a wrong metric.** Use the bug template. Say which vendor and model, and attach the relevant `original/` resource when you can. Do not paste credentials or unsanitized captures.
- **Report a vulnerability, or a fixture that still holds an identifier that should have been removed.** Do not open an issue. Follow [SECURITY.md](SECURITY.md).
- **Ask for a vendor or model.** Use the vendor-support template.
- **Send a change.** Fix a normalization, add a model, improve the docs, or add a test.

For a large change, open an issue first so a maintainer can say whether it fits before you write it.

## Set up

Redpool is a [uv](https://docs.astral.sh/uv/) workspace. Run Python through `uv`, from the repository root.

```bash
git clone --recurse-submodules <repository-url>
cd redpool
uv sync --all-packages --all-extras
```

Use `--all-packages --all-extras`. A plain `uv sync --extra dev` removes the `redfish-snapshot` workspace member, and its tests then fail to collect.

The submodules are `fixtures` (the test corpus, see "Fixtures" below), `third_party/redfish-inventory-exporter`, `third_party/fishymetrics` and `third_party/Redfish-Mockup-Server`. See [docs/THIRD_PARTY.md](docs/THIRD_PARTY.md).

## Check your change

CI runs all four. Run them before you push.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy redpool
uv run pytest
```

If your change touches normalization, also regenerate the outputs and the goldens for the models it affects, and run the schema check. The commands are in "Changing an existing model" in the contributor guide. Two rules matter:

- **Never edit a `.prom` golden file by hand.** Regenerate it with the scripts in `scripts/`. If the output is wrong, fix the normalizer and regenerate.
- **A change to a base normalizer or the registry must leave every other vendor's outputs unchanged.** Regenerate without a vendor filter and confirm the diff is empty, or explain each difference in the pull request.

## Where the code goes

- A vendor- or model-specific rule goes in that vendor's module under `normalizers/`. It never goes in `redpool/`, in a shared `base.py`, or in a collector.
- Do not change `third_party/` in a drive-by. Ask a maintainer first.
- Put a value the Redfish schema has no property for in `Oem.Redpool`. Never invent a value the BMC did not send.

## Fixtures

`fixtures/` is a submodule: the [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures) repository. It holds sanitized captures of lab servers, the normalized outputs Redpool produces from them, and the Prometheus goldens. It is dedicated under CC0 1.0, and its `NOTICE.md` says which rights stay with the vendors. Tests that need it carry the `requires_fixtures` marker and skip when the submodule is missing.

The public corpus covers the lab models only. Maintainers regenerate the outputs and goldens of the other models listed in the README from captures they hold, so a change to normalization can show no diff for those models in your pull request. When a change affects them, say so in the description and a maintainer regenerates them.

A change to the corpus is two pull requests: one to `redpool-fixtures` with the files, and one here that moves the `fixtures` pointer. Generate the files with the scripts (the commands are in the contributor guide). Do not edit a file under `normalized/` or a `.prom` file by hand. A pull request that only changes a normalizer can prove it with a unit test that builds a small synthetic payload.

Every capture must be sanitized before it leaves your machine. `redfish-snapshot` sanitizes by default, and `redfish-snapshot sanitize` cleans an existing tree. Check the result for identifiers the sanitizer missed.

## Commits and pull requests

- Write the subject in the imperative, under about 72 characters. Say what the change does: "Map BMC placeholder dates to null".
- Keep a pull request to one concern. Explain why in the description.
- Add or update a test with the change.
- Add a line under "Unreleased" in [CHANGELOG.md](CHANGELOG.md) for anything a user would notice: a changed field, label or metric, a new vendor, or a fix.
- New source files start with the SPDX header the neighboring files use.

## Sign your commits (DCO)

Every commit needs a `Signed-off-by` line. It says you wrote the change, or have the right to submit it, under the project's Apache-2.0 license. Add it with:

```bash
git commit -s
```

The line must use your real name and an email you can be reached at:

```text
Signed-off-by: Your Name <you@example.com>
```

The full text you certify is the Developer Certificate of Origin 1.1:

> By making a contribution to this project, I certify that:
>
> (a) The contribution was created in whole or in part by me and I have the right to submit it under the open source license indicated in the file; or
>
> (b) The contribution is based upon previous work that, to the best of my knowledge, is covered under an appropriate open source license and I have the right under that license to submit that work with modifications, whether created in whole or in part by me, under the same open source license (unless I am permitted to submit under a different license), as indicated in the file; or
>
> (c) The contribution was provided directly to me by some other person who certified (a), (b) or (c) and I have not modified it.
>
> (d) I understand and agree that this project and the contribution are public and that a record of the contribution (including all personal information I submit with it, including my sign-off) is maintained indefinitely and may be redistributed consistent with this project or the open source license(s) involved.

The DCO workflow fails a pull request when any commit lacks the line. To fix a missing one, run `git commit --amend -s`, or `git rebase --signoff` for several commits.

## Review

A maintainer reviews every pull request. A change merges when a maintainer approves it and CI passes. Who the maintainers are, and how that changes, is in [MAINTAINERS.md](MAINTAINERS.md).

## License

Redpool is licensed under the [Apache License 2.0](LICENSE). A contribution is made under the same license.
