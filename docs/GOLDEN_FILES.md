# Golden files

The generators start the mock, the proxy, and the collector for each model, write the scrape, and stop those processes. Do not edit a `.prom` file by hand. If the output is wrong, change the normalizer and run the generator again.

From the repository root, after `uv sync --all-packages --all-extras` and `git submodule update --init --recursive`:

```bash
uv run python scripts/generate_fishymetrics_golden.py
uv run python scripts/generate_fishymetrics_golden.py --no-proxy
uv run python scripts/generate_redfish_inventory_exporter_golden.py
uv run python scripts/generate_redfish_inventory_exporter_golden.py --no-proxy
```

`--model Vendor/Model` limits a run to one model. `--no-proxy` scrapes the mock directly and writes the `*_direct.prom` file. The inventory-exporter generator accepts `--disable-collectors logs,bios` when those families are not part of the change. Build the collector before generating: `make -C third_party/fishymetrics build`, or `go build -o build/redfish-inventory-exporter .` inside `third_party/redfish-inventory-exporter`.

## When a file has only process metrics

Run the same steps by hand for one model, `Dell/PowerEdge_R740`, and confirm the scrape body contains `redfish_*` before trusting the script. Expect `200` from the mock and from the collector's root. A request through the proxy to `http://127.0.0.1:18888/redfish/v1/Systems` may return `200` or `500`; either means the proxy forwarded it.

Mock, from the repository root:

```bash
uv run --no-project --with-requirements third_party/Redfish-Mockup-Server/requirements.txt \
  python third_party/Redfish-Mockup-Server/redfishMockupServer.py \
  --port 18888 \
  --dir "$(pwd)/fixtures/Dell/PowerEdge_R740/original"
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18888/redfish/v1/
```

Proxy. Point `REDPOOL_CONFIG` at a file that moves the proxy's own metrics off the collector's port, and clear `HTTP_PROXY` so the proxy does not proxy itself.

| | Fishymetrics | redfish-inventory-exporter |
| --- | --- | --- |
| Proxy listen | 18080 | 18082 |
| Proxy `metrics_port` | 19101 | 19103 |
| Collector | 10023 | 9611 |

```bash
printf 'proxy:\n  metrics_port: 19101\n' > /tmp/redpool-golden-config.yaml
REDPOOL_CONFIG=/tmp/redpool-golden-config.yaml \
HTTP_PROXY= HTTPS_PROXY= http_proxy= https_proxy= \
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
  uv run redpool-proxy --listen-host 0.0.0.0 --listen-port 18080
```

```bash
curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  -x http://127.0.0.1:18080 \
  http://127.0.0.1:18888/redfish/v1/Systems
```

Fishymetrics. Build with `make -C third_party/fishymetrics build`. Set `HTTP_PROXY` and `HTTPS_PROXY` to `http://127.0.0.1:18080`.

```bash
FISHYMETRICS_DISABLE_404_RETRY=1 \
  ./third_party/fishymetrics/build/usr/bin/fishymetrics \
  --port 10023 --user admin --password password --scheme http --insecure-skip-verify
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:10023/
curl -s -S --max-time 180 \
  "http://127.0.0.1:10023/scrape?target=127.0.0.1:18888&model=generic&proxy_host=127.0.0.1:18080"
```

redfish-inventory-exporter. The config holds the mock's username and password, and the process refuses to start without an allowlist.

```bash
echo '{"default":{"username":"admin","password":"password"},"hosts":{}}' > /tmp/redfish-inventory-exporter-golden.json
HTTP_PROXY=http://127.0.0.1:18082 HTTPS_PROXY=http://127.0.0.1:18082 REDFISH_SCHEME=http \
  ./third_party/redfish-inventory-exporter/build/redfish-inventory-exporter \
  --config /tmp/redfish-inventory-exporter-golden.json \
  --target-allowlist 127.0.0.1
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9611/
curl -s -S --max-time 180 "http://127.0.0.1:9611/redfish?target=127.0.0.1:18888"
```

For the inventory exporter, use proxy port 18082 in the proxy command and in the proxy probe. If the scrape body is only `go_*`, `mux_*`, and `promhttp_*`, the scrape timed out or the collector never used the proxy. Check the proxy log (`REDPOOL_RESPONSE_LOG`) and raise curl `--max-time`, or the script's `--scrape-timeout`.
