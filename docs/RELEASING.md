# Releasing

How a maintainer cuts a release. [CHANGELOG.md](../CHANGELOG.md) is the record, and this page is the procedure.

## Versions

Redpool follows [Semantic Versioning](https://semver.org/). Two packages carry their own version: `redpool` in `pyproject.toml` and `redfish-snapshot` in `redfish-snapshot/pyproject.toml`. They are released together, but a version number moves only when that package changed.

What users see is the contract, so these are **breaking** changes and need a major version (or a minor version while the version is below 1.0):

- Removing or renaming a property in normalized Redfish output, or changing its type.
- Removing or renaming a Prometheus metric or label that Redpool's own tooling produces.
- Removing a command, option, environment variable or config key.
- Dropping support for a vendor or model that was supported.

Adding a vendor, a model, a property, or an option is a minor change. A fix to a wrong value is a patch.

## Before you tag

1. Everything for the release is merged to `main` and CI is green.
2. Move the "Unreleased" entries in `CHANGELOG.md` under a new `## [X.Y.Z] - YYYY-MM-DD` heading, and add an empty "Unreleased" heading above it. Every user-visible change needs a line.
3. Set the new version in `pyproject.toml` and, if it changed, `redfish-snapshot/pyproject.toml`. Run `uv lock`.
4. Check that the submodule pins point at pushed commits: `fixtures`, `third_party/redfish-inventory-exporter`, `third_party/fishymetrics` and `third_party/Redfish-Mockup-Server`. `git submodule status` shows each one.
5. Verify from a clean checkout:

```bash
git submodule update --init --recursive
uv sync --all-packages --all-extras
uv run ruff check . && uv run ruff format --check . && uv run mypy redpool
uv run pytest
uv run python scripts/generate_normalized_outputs.py
uv run python scripts/validate_redfish_schema.py
git -C fixtures status --short   # must show no changes
```

Regenerating the goldens and the normalized outputs must leave `fixtures/` unchanged. If it does not, either the change is not finished or a fixture is stale. The public `fixtures/` holds the lab models only. Run the same generation commands with `REDPOOL_FIXTURES` pointing at the maintainers' full corpus too, and confirm it is unchanged.

## Tag and build

```bash
git commit -am "Release X.Y.Z"
git tag -a vX.Y.Z -m "Redpool X.Y.Z"
make pip-build                       # sdist and wheels for the workspace
VERSION=vX.Y.Z make docker-build     # redpool and redfish-snapshot images
```

Push the commit and the tag only after the build succeeds.

## Publishing

Pushing a `v*` tag runs [.github/workflows/docker-publish.yml](../.github/workflows/docker-publish.yml). It lints, type-checks, tests and validates schemas, then pushes `ghcr.io/<owner>/redpool:<version>` and `ghcr.io/<owner>/redfish-snapshot:<version>` using the workflow's `GITHUB_TOKEN`. A tag without a pre-release suffix also moves `latest`. A tag with a suffix (`v1.2.0-rc1`) does not. A pull request that touches the image inputs builds both images without pushing them.

The workflow does not publish the wheels or create the GitHub release. The maintainers do both from the changelog entry.

## After the release

- Check that the built wheel starts in a clean environment: `uvx --from dist/redpool-<version>-py3-none-any.whl redpool-proxy --help` should print the usage.
- For a vulnerability fix, publish a security advisory that names the fixed version.
- If a release is bad, do not move the tag. Fix forward with a patch release, and say so in the changelog.
