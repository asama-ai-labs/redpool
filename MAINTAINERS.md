# Maintainers

Maintainers review and merge pull requests, triage issues, cut releases, and enforce the [Code of Conduct](CODE_OF_CONDUCT.md).

| GitHub | Area |
|---|---|
| [@jj-asama](https://github.com/jj-asama) | All |

The project has one maintainer today. That is a risk, and the project would like more. A maintainer can approve any change except their own, so until there is a second one, the maintainer's own pull requests merge after CI passes and a contributor has had the chance to comment.

## How decisions are made

- A change to code, fixtures or docs merges when a maintainer approves it and CI passes.
- A change that alters normalized output, Prometheus labels, or a public command or option is called out in [CHANGELOG.md](CHANGELOG.md). A maintainer asks for discussion in an issue first when users could break.
- A disagreement is settled by discussion on the issue or pull request. If maintainers disagree, the project's goals decide: Redpool normalizes what the BMC already reports and does not invent data. See [docs/REDPOOL_CONTRIBUTOR_GUIDE.md](docs/REDPOOL_CONTRIBUTOR_GUIDE.md).

## Becoming a maintainer

A contributor who has had several non-trivial changes merged, and reviews others' work well, can be nominated by a current maintainer in an issue. The nomination is accepted when the other maintainers agree. A maintainer who is no longer active can step down by opening a pull request that edits this file, and a maintainer who has been inactive for a year may be moved to an emeritus list the same way.

## Contacting maintainers

Use the issue tracker. For anything private, including a Code of Conduct report, open a private security advisory on this repository as described in [SECURITY.md](SECURITY.md).
