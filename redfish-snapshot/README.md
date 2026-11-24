# Redfish Snapshot

A tool for capturing Redfish API responses from BMCs with built-in sanitization. Saves a point-in-time snapshot to disk in the DMTF mockup layout, for use with DMTF Redfish-Mockup-Server and the redpool test suite.

## Installation

From this repository:

```bash
uv sync
uv run redfish-snapshot --help
```

A published release installs with `uv pip install redfish-snapshot`.

## Usage

After installation, you can use the `redfish-snapshot` command directly:

```bash
# Password: export REDFISH_SNAPSHOT_PASSWORD=... first, or run from a terminal to be prompted.

# Show help
redfish-snapshot --help

# Basic usage (sanitization and compact JSON enabled by default)
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640

# Disable sanitization
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640 \
  --no-sanitize

# Use pretty JSON formatting
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640 \
  --pretty

# Exclude specific URL prefixes
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640 \
  --exclude /redfish/v1/Managers/ /redfish/v1/AccountService/

# Limit processing to first N items in collections (default: 50)
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640 \
  --member-limit 25

# Combine multiple options
redfish-snapshot \
  --host your-redfish-host \
  --username admin \
  --vendor Dell \
  --model PowerEdge_R640 \
  --member-limit 100 \
  --parallel 10 \
  --pretty \
  --exclude /redfish/v1/Managers/
```

## Features

- **Automatic sanitization**: Masks serial numbers (including **ServiceTag** and other OEM fields such as `Oem.Dell.ServiceTag` in service root, and BIOS attributes like `SystemServiceTag`), MAC addresses, and IP addresses by default. Sanitization is applied recursively to all nested objects; use `--no-sanitize` only when you intend to redact manually. Older snapshots or runs with `--no-sanitize` may contain real serials—review fixtures before publishing.
- **Compact JSON output**: Saves space with compact JSON formatting by default
- **Parallel processing**: Configurable concurrent requests for faster data collection
- **Flexible exclusions**: Exclude specific URL prefixes from collection
- **Member limiting**: Limit processing to first N items in collections to control data size. After clone, collection JSON is automatically fixed so `Members` and `Members@odata.count` match the member files actually saved (required when using `--member-limit`).
- **Metadata generation**: Creates metadata files with collection information

## Data Storage

By default, data is saved to `fixtures/{vendor}/{model}/original/` relative to the current directory:

```
fixtures/
└── {vendor}/
    └── {model}/
        ├── metadata.json
        └── original/
            └── redfish/v1/
                ├── index.json              # /redfish/v1
                ├── Chassis/index.json      # /redfish/v1/Chassis
                ├── Systems/
                └── ... (all collected Redfish endpoints)
```

This is the DMTF mockup layout (`redfish/v1/<path>/index.json`), the same one Redfish-Mockup-Creator writes, so DMTF Redfish-Mockup-Server and the redpool test suite can serve it. Use `--output-path` to override the destination.

## Sanitize an existing mockup

`clone` sanitizes as it captures. To sanitize a mockup captured by another tool, such as DMTF [Redfish-Mockup-Creator](https://github.com/DMTF/Redfish-Mockup-Creator), which does no redaction, run:

```bash
redfish-snapshot sanitize path/to/mockup [more/mockups ...]
```

It rewrites every `*.json` in place and renames directories whose names carry identifying tokens. One placeholder map is built across all the paths given. It does not touch the Creator's `README` or `index.xml` files, so check those by hand before publishing.

## Fix collections (after clone or on existing fixtures)

Collection documents have a `Members` array and `Members@odata.count`. If the member directories on disk differ (e.g. you truncated a collection), run the following. It works on any DMTF-layout mockup, including Redfish-Mockup-Creator output:

```bash
# Fix collections under one or more directories (default: current dir)
redfish-snapshot fix-collections fixtures/Dell/PowerEdge_R630/original

# Dry run
redfish-snapshot fix-collections fixtures/Dell/PowerEdge_R630/original --dry-run

# Pretty-print updated JSON
redfish-snapshot fix-collections fixtures/Dell/PowerEdge_R630/original --pretty
```

This updates each collection file so `Members` and `Members@odata.count` match the actual `*.json` files in the member directory (e.g. `Entries.json` → `Entries/*.json`), and removes `Members@odata.nextLink`. **Clone always runs this step after saving** so that when you use `--member-limit`, the collection JSON reflects only the members that were written to disk.

## Command Line Options (clone)

- `--host`: Redfish endpoint host (required)
- `--username`: Username for authentication (required)
- Password: read from `REDFISH_SNAPSHOT_PASSWORD`, or prompted for when run from a terminal. There is no `--password` option, so the password does not appear in shell history or `ps`.
- `--tls-warnings`: show urllib3's warnings about unverified BMC certificates. They are hidden by default.
- `--vendor`: Vendor name, e.g. Dell, HPE, Lenovo, Supermicro (required)
- `--model`: Model name, e.g. PowerEdge_R640 (required)
- `--output-path`: Override output directory (default: `fixtures/<vendor>/<model>/original`)
- `--exclude`: URL prefixes to exclude (optional)
- `--parallel`: Maximum number of parallel requests (default: 5)
- `--pretty`: Pretty-print JSON (compact by default)
- `--no-sanitize`: Disable sanitization of sensitive data
- `--member-limit`: Limit URL extraction to first N items per response (default: 50)

## Dependencies

- `redfish>=3.3.1` - Redfish REST API client
- `urllib3>=1.26.0` - HTTP client library
