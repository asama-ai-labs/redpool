# Fixtures

The sanitized Redfish captures used by the mock server, the proxy tests, and the Prometheus golden files live in the [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures) repository, which is the `fixtures/` submodule here. It holds captures of lab servers only and is dedicated under CC0 1.0; its `NOTICE.md` says where the data comes from and which rights stay with the vendors. Clone with `--recurse-submodules`, or run `git submodule update --init fixtures` in an existing clone. The submodule's own `README.md` says what each tool writes. Each model lives at `fixtures/<Vendor>/<Model>/`.

## Layout

Both trees use the DMTF mockup layout, the format written by [Redfish-Mockup-Creator](https://github.com/DMTF/Redfish-Mockup-Creator) and served by [Redfish-Mockup-Server](https://github.com/DMTF/Redfish-Mockup-Server). The resource at `/redfish/v1/<path>` is stored as `redfish/v1/<path>/index.json`:

```
fixtures/Dell/PowerEdge_R640/
├── metadata.json
├── original/redfish/v1/index.json                         # /redfish/v1
├── original/redfish/v1/Systems/index.json                 # /redfish/v1/Systems
├── original/redfish/v1/Systems/System.Embedded.1/index.json
└── normalized/redfish/v1/Systems/System.Embedded.1/index.json
```

- `original/` is the sanitized capture. Any DMTF mockup tool can read it, and the golden scripts serve it as the BMC.
- `normalized/` exists only for resources whose body changed when it passed through the proxy. A path with no file here is served unchanged from `original/`.
- A URI segment is used as the directory name exactly as the BMC sent it, after sanitizing, so `%23` stays `%23` (for example `iDRAC.Embedded.1%23Host.1`). A directory name is sanitized the same way as the `@odata.id` that points to it, so links still resolve.
- Captures in the older `<parent>/<leaf>.json` layout convert with `uv run python scripts/convert_fixtures_to_mockup.py --fixtures <dir>`.
- Prometheus goldens sit next to those trees: `redfish_inventory_exporter_direct.prom`, `redfish_inventory_exporter_redpool.prom`, and the matching `fishymetrics_*` files. Regenerate them with the scripts in `scripts/`. Do not edit the `.prom` files by hand.
- Normalized documents are checked against the DMTF schema named by `@odata.type`. See [SCHEMA_VALIDATION.md](SCHEMA_VALIDATION.md).

## How a capture is sanitized

Five layers run in this order. The first three are in `redfish-snapshot/src/redfish_snapshot/sanitize.py` and `postprocess.py`, the fourth is `temporal.py`.

1. **Key rules** replace known fields with placeholders:
   - serials, asset tags and service tags, including `*Serial`, `*SerialNum` and `*AssetTag` names
   - MACs, WWNs, NAA, EUI-64 and volume identifiers, and UUIDs, each given its own placeholder so that distinct devices stay distinct
   - host and domain names, account names, contact names and phone numbers
   - secrets named `*Password`, `*Passphrase`, `*Secret`, `*Token`, `*Keytab`, `AuthenticationKey` or `EncryptionKey`
   - SNMP communities and engine IDs, SSH host and user keys, licence keys and signatures, TPM endorsement keys and measurements, PPIN and ChipId
   - `Location.PostalAddress`, `Placement.Row` and `Rack`, coordinates, and certificate subjects and issuers that are not a public vendor CA
2. **Identifier pass.** The real serials, MACs, customer and account names of one capture are collected from its raw documents. They are then removed from every value, dictionary key, path and `metadata.json` string of that capture, ignoring case and separators and including hex and base64 forms. The list is saved per capture, so a later run still finds values it saw earlier.
3. **Pattern rules** catch identifier shapes that sit outside a known field. These include IP addresses, e-mail addresses and DNS names (also upper case, such as Kerberos realms), URIs (host, credentials and path), LDAP distinguished names, iSCSI IQNs and NVMe NQNs, PEM and bare base64 certificates (also truncated ones), OpenSSH public keys, boot-order drive serials, log user names, Dell job and entitlement IDs, task-monitor tokens, session IDs and switch ports. The same rules run on resource paths and on `collected_urls` in `metadata.json`.
4. **Time policy** (`--mask-time`). Every timestamp in a capture moves by one offset that is derived from a secret key and the capture's name. Time zones and UTC offsets become UTC, manufacture and licence dates are rounded, uptime counters are scaled, and `collection_timestamp` becomes a shifted date. `metadata.json` records `time_policy` so later runs skip the capture.
5. **Etags** are recomputed last. A hash-shaped `@odata.etag` becomes the same hash of the sanitized body, so it verifies and reveals nothing about the original.

The rules cannot recognise free text a person typed: a system `Name` or `Description`, a volume name, a boot option label, a log message. That is why every new capture also gets an LLM review and a human review (steps 5 and 6 below).

### Commands

Run these from the repository root, in this order:

```bash
export REDPOOL_SANITIZE_STATE=<directory outside every repository>   # real identifiers are saved here
export REDPOOL_SANITIZE_SECRET=<secret key>                           # needed for --mask-time

uv run python scripts/trim_log_entry_collections.py --models <Vendor/Model> --max 20
uv run python scripts/sanitize_fixtures_original.py --mask-time [--vendor V --model M]
uv run python scripts/generate_normalized_outputs.py
# regenerate the goldens; see docs/GOLDEN_FILES.md
uv run python scripts/check_fixture_leaks.py
```

A new `redfish-snapshot clone` already trims each log collection to 20 entries and applies the time policy. The two commands above are for a capture that is already on disk. Trim before that sanitize, so the etags of the collections it edits are recomputed. The state directory and the secret key hold or protect real identifiers: keep them out of git, and keep the key out of both repositories. The sanitizer refuses a state directory inside a git work tree. If your home directory is a git work tree, choose a directory outside it.

### Release check

`scripts/check_fixture_leaks.py` must exit 0 before a release. It scans `original/`, `normalized/`, `metadata.json` and the `.prom` files for:

- the detector table, plus hex and base64 that decode to serial-like text
- etags that do not verify
- non-UTC time zones
- placeholder keys that hold values
- `S-RESAN`: any captured document, path or `collected_urls` entry that the current sanitizer would still change. A capture made with `--no-sanitize`, or sanitized before a rule existed, fails here.
- with `REDPOOL_SANITIZE_STATE` set, every identifier saved for that capture

Run it by hand before a release and before you push fixtures. `REDPOOL_SANITIZE_STATE` is optional; set it when you have the sanitizer state directory so saved identifiers are checked too. Each finding prints only the first 6 characters of the match.

When you add a sanitizer rule, re-run `sanitize_fixtures_original.py` over the whole tree in the same change. Otherwise `S-RESAN` fails for every capture the new rule would touch.

## Contributing a fixture

Treat a new capture as confidential until it has passed every step below. Do the work on your own machine, and do not push a branch, open a draft pull request or share the files until step 7. Commands run from the repository root.

### 1. Prepare the BMC

Capture a lab machine if you can. Before capturing, remove what you can at the source, because the safest value is one the BMC never returns:

- Set the BMC and host names to something generic (`bmc-lab`, `host-lab`).
- Remove LDAP, Active Directory, Kerberos and RADIUS settings, SNMP trap and alert destinations, SMTP relays, syslog servers, event subscriptions and remote-support registration.
- Delete local accounts other than the vendor defaults, and any SSH user keys.
- Eject virtual media, and clear HTTP, PXE and iSCSI boot targets.
- Clear or export the system event log and Lifecycle or IML logs if you do not need them.
- Leave the asset tag, `Location` and contact fields empty.

### 2. Set up the state directory and key

```bash
export REDPOOL_SANITIZE_STATE=~/redpool-sanitize-state         # outside every git work tree, on an encrypted disk
export REDPOOL_SANITIZE_SECRET="$(openssl rand -hex 32)"       # yours alone; never commit or share it
export REDFISH_SNAPSHOT_PASSWORD='<BMC password>'               # read by the capture tool; never passed on the command line
```

Use a fresh random key for your own captures. It only has to stay the same while you re-run the sanitizer on the same capture.

### 3. Capture

```bash
uv run --project redfish-snapshot redfish-snapshot clone \
  --host <bmc-address> --username <user> --vendor <Vendor> --model <Model>
unset REDFISH_SNAPSHOT_PASSWORD
```

- The capture goes to `fixtures/<Vendor>/<Model>/original/`. Name the model as the vendor does, with underscores (`PowerEdge_R760`). Add `_2` for a second capture of the same model.
- Never use `--no-sanitize` for a fixture. The clone sanitizes as it writes. It then keeps 20 distinct log entries per collection and, because `REDPOOL_SANITIZE_SECRET` is set, applies the time policy in the same pass that removes collected identifiers. `--trim-logs 0` keeps every log entry. `--no-mask-time` leaves timestamps alone.
- Do not `git add` anything yet.

### 4. Run the automated check

```bash
uv run python scripts/check_fixture_leaks.py --vendor <Vendor> --model <Model>
```

This must print `0 finding(s)`, with `REDPOOL_SANITIZE_STATE` still set so that saved identifiers are checked too. A finding means a rule missed something. Fix the rule in `sanitize.py`, add a test for it under `redfish-snapshot/tests/`, re-run `scripts/sanitize_fixtures_original.py --mask-time` for that model, and run this check again. Do not hand-edit the value away: the next capture from the same vendor would leak it again.

### 5. LLM review

The rules only know the shapes they were written for. Next, have an LLM read the capture for anything that identifies a site, a person, a device or a secret.

The LLM sees the data before anyone knows it is clean. Use only a model your organization approves for confidential data: a local model, or a hosted one under an agreement that excludes training on and retention of your inputs. If you have neither, skip this step and do step 6 more thoroughly.

Run the prompt below from the repository root, in an agent that can read files, such as Claude Code. Replace `<Vendor>/<Model>`.

```text
You are reviewing a sanitized Redfish BMC capture before it is published in a public open
source repository. Treat every value as possibly confidential. A leak is any value that could
identify the organization that owns the server, its site, a person, an individual device,
or that is a secret.

Scope: fixtures/<Vendor>/<Model>/ — every file under original/, plus metadata.json. Also
check directory and file names, because Redfish resource Ids become directory names.

Placeholders are safe, so do not report them: values that contain DUMMY, DUMMY.example.invalid,
DUMMY@example.invalid, 192.0.2.1, ::1, 00:1B:44:AA:BB:CC (and its forms without separators or
with :00:00), UUIDs starting 550e8400-e29b-41d4-a716-, zero-padded storage identifiers such as
0000000000000001, iqn.2000-01.invalid.example:DUMMY, CN=DUMMY,DC=example,DC=invalid, and
public vendor or CA names (Dell, HPE, Lenovo, Supermicro, Intel, Microsoft, VMware, Canonical).
Firmware versions that look like IPv4 addresses (2.85.85.85) are not addresses.

Look for, at minimum:
1. Names a person typed: system, chassis, manager, volume or boot-option Name, Description,
   DisplayName, AssetTag, BIOS custom strings, LCD text, event subscription Context.
2. Host, domain, site and organization names anywhere in text: log messages, MessageArgs,
   URIs, certificate subjects, LDAP and Kerberos settings, NTP and DNS servers.
3. People: user and account names (other than vendor defaults such as root, ADMIN,
   Administrator and USERID), e-mail addresses, phone numbers, street addresses, rack,
   row and room names.
4. Device identifiers in any field or encoding: serial numbers, service tags, licence and
   entitlement IDs, MAC, WWN, EUI, NAA, GUIDs, PPIN, TPM data. Include identifiers inside
   hex or base64 blobs, JSON stored in a string, URL paths and directory names.
5. Secrets: passwords, keys, tokens (including tokens in URLs such as task monitors),
   certificates, licence signatures, SNMP communities.
6. Timestamps or epoch-based IDs that look unshifted, or time zones other than UTC.
7. Anything else that, combined with public information, would let someone work out whose
   server this is or where it runs.

Rules for your report:
- Never print a full value. Show at most the first 3 and last 2 characters (ab…yz).
- For each finding give: file path, JSON key path, what kind of value it is, why it might
  identify someone, how many times it appears, and High, Medium or Low confidence.
- List the classes of data you checked and found clean.
- List the field names or value shapes that a key-name or regex sanitizer would miss here,
  so a rule can be added for them.
- Do not edit any file.
```

For each finding, decide whether it is real. Fix real ones with a sanitizer rule and a test, as in step 4. Note false positives in the pull request.

### 6. Human review

Read these yourself even when the LLM found nothing. They are the free-text places where people type names:

- `Systems/*`, `Chassis/*` and `Managers/*`: `Name`, `Description`, `AssetTag`, `HostName`
- `Managers/*/NetworkProtocol`, `EthernetInterfaces`, `AccountService`, `EventService/Subscriptions`, `SessionService`
- `Systems/*/Bios` attributes and `BootOptions`, `Storage/*/Volumes` names
- the first few entries of each `LogServices/*/Entries`
- `metadata.json`

### 7. Normalize, regenerate and open the pull requests

```bash
uv run python scripts/generate_normalized_outputs.py
uv run python scripts/validate_redfish_schema.py --strict
# regenerate the goldens for the new model; see docs/GOLDEN_FILES.md
uv run python scripts/check_fixture_leaks.py --vendor <Vendor> --model <Model>
```

Then open one pull request in the fixtures repository with the capture, and one in this repository that carries any sanitizer or normalizer change. Sign off every commit (`git commit -s`). The fixtures pull request description says:

- where the capture comes from (lab, or production with the owner's approval) and that you may publish it
- the scanner result from step 4, run with the state directory
- whether the LLM review in step 5 ran, which model you used, and what you did with each finding
- any value you kept on purpose, and why

Keep the state directory after the pull request is merged. It lets a later re-sanitize, or the release check, find the identifiers again. Never attach it, or any part of it, to an issue or pull request.

### If a leak is found after merge

Report it privately as described in [SECURITY.md](../SECURITY.md). The maintainers fix the rule, re-sanitize the tree, and rewrite the fixtures history so the value is gone from every commit. Rotate anything secret that was exposed, such as BMC certificates, keys and licence keys.
