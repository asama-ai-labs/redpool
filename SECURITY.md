# Security

The test corpus in `fixtures/` is the [redpool-fixtures](https://github.com/asama-ai-labs/redpool-fixtures) submodule. It holds captures of lab servers only, with serial numbers, MAC addresses and host addresses replaced before a capture is added. The repository is dedicated under CC0 1.0; its `NOTICE.md` says where the data comes from and which rights stay with the vendors.

Report a vulnerability, or a fixture that still contains an identifier that should have been removed, by opening a private security advisory on this repository. Do not file a public issue for either case.

## Credentials and tenancy

Redpool does not authenticate its callers. It forwards whatever credentials a request carries to the BMC, and it keeps the following guarantees:

- A request runs only on a BMC session that matches its own credential. Unauthenticated requests use a separate anonymous client, so they can never reach a session opened by another caller.
- Cached responses are keyed by credential, so one caller's cached reads are never served to another.
- Redpool does not create BMC sessions itself. Basic auth is sent on each request, and session tokens are forwarded from the caller.

Operational consequences:

- Each BMC can have up to two TCP connections from one Redpool instance: one anonymous and one authenticated. Callers alternating between credentials on the same BMC cause reconnects.
- Collectors that use session tokens no longer share cached responses with each other.
- Redpool is not multi-tenant. Run one instance per trust boundary.

## Threat model

Redpool is a forward proxy. A caller sends `http(s)://<bmc>/redfish/...` and Redpool fetches it from that BMC and returns the JSON. Anyone who can reach the listener can therefore make Redpool connect to a host of their choosing, so the listener must only be reachable by callers you trust.

What Redpool does:

- **Listens on loopback by default.** `redpool-proxy` binds `127.0.0.1`, as do the shard front and its Prometheus service-discovery endpoint. The shipped systemd files and `docker-compose.yml` do the same. To serve other hosts you change the bind on purpose (`--listen-host 0.0.0.0`, `REDPOOL_SHARD_FRONT_HOST`, or the compose port mapping).
- **Serves Redfish paths only.** A path must be `/redfish` or below it after decoding and normalizing, so `/etc/passwd`, `/redfish/../x` and `%2e%2e` are refused with 403. `proxy.require_redfish_path` turns this off.
- **Can restrict targets.** `proxy.allowed_targets` (or `REDPOOL_ALLOWED_TARGETS`, comma-separated) lists the hosts a caller may name: exact names, `*` globs, and CIDRs. Anything else gets 403. The list is empty by default, which allows any host. A CIDR matches only a request that names an IP. Names are never resolved, so list names and CIDRs separately.
- **Bounds its own state.** It tracks at most `proxy.max_targets` BMCs (default 2048) and drops the least recently used past that, closing their connections. A target with a request in flight is kept.
- **Keeps callers' credentials apart** (see above).

What Redpool does not do:

- **It does not authenticate callers.** A bind address and an allowlist are not authentication. If the listener is reachable by anything you do not trust, add authentication or network controls. mitmproxy's `proxyauth` works: `redpool-proxy --set proxyauth=user:pass`, or `--set proxyauth=@/etc/redpool/htpasswd`. Collectors then use `https_proxy=http://user:pass@host:port`. This uses `Proxy-Authorization`, so it does not interfere with the BMC credentials in `Authorization`. Keep the credentials out of shell history and process listings, for example by using the htpasswd file.
- **It does not verify BMC TLS certificates by default.** `proxy.tls_verify` is `false`, so Redpool accepts any certificate a BMC presents, and the Basic-auth credentials it forwards can be read by anyone on the path to the BMC. A startup warning says so. To turn verification on, set `proxy.tls_verify: true`. Then BMC certificates must chain to `proxy.ca_file`, or to the system bundle when `ca_file` is empty. Expect a BMC with a self-signed or privately issued certificate to fail until you add its CA to `ca_file`. A failed verification is logged as an SSL certificate error for that BMC. The client gets a 500 with no BMC response. Verification also checks the name. A BMC addressed by IP must have that IP in its certificate.

  Keep verification off only on a network you trust end to end, and say so in your deployment notes.
- **It does not authenticate the metrics port.** `/metrics` lists the BMC hostnames, vendors and models the proxy has reached. It binds `127.0.0.1` by default. To let a remote Prometheus scrape it, set `proxy.metrics_host` or `REDPOOL_METRICS_HOST` (for example `0.0.0.0`) and limit who can reach the port. Redpool logs a warning when it binds a non-loopback address. The container image sets `0.0.0.0` so a published port works, and `docker-compose.yml` publishes it on `127.0.0.1` only. A sharded deployment that scrapes workers from another host needs `REDPOOL_METRICS_HOST` and `--worker-host` (`REDPOOL_SHARD_WORKER_HOST` in the systemd env file) set to match.
- **`DEBUG` logs URLs, not headers.** `proxy.log_level: DEBUG` sets mitmproxy's `flow_detail` to 1. Redpool also pins the `redfish` (python-redfish) logger to WARNING, because that library logs request and response headers, including `X-Auth-Token`, at DEBUG. Levels 2 and above print request headers, including `Authorization` and `X-Auth-Token`, so do not raise it on a host whose logs others can read.

Without an allowlist, any host that can reach the listener can make Redpool open connections to any address Redpool itself can reach, including ones the caller cannot. Set `allowed_targets` to your BMC networks on any shared host.
