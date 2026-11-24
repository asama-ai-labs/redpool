#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""Write a self-contained HTML browser of invalid normalized Redfish documents.

Usage (from the repository root):

    uv run python scripts/generate_schema_invalid_html.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from redpool.schema_validator import (
    SchemaIssue,
    SchemaResult,
    iter_normalized_documents,
    schema_bundle_available,
    validate_document,
)
from redpool.mockup import relpath_to_uri

_PUBLIC = Path(__file__).resolve().parent.parent
_DEFAULT_OUT = _PUBLIC / "redfish-schema-invalid.html"

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Normalized Redfish schema report</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 24px; color: #e6e6e6; background: #141414;
    font: 14px/1.45 ui-sans-serif, system-ui, sans-serif; }
  h1 { font-size: 22px; font-weight: 600; margin: 0 0 6px; }
  h2 { font-size: 16px; font-weight: 600; margin: 28px 0 8px; }
  p { margin: 0; }
  .muted { color: #a3a3a3; }
  .small { font-size: 12px; color: #8a8a8a; }
  .stats { display: flex; gap: 28px; margin: 18px 0 8px; }
  .stat b { display: block; font-size: 22px; font-weight: 600; }
  .stat span { color: #a3a3a3; font-size: 12px; }
  .ok { color: #3dd68c; }
  .bad { color: #f07167; }
  .pills, .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0; }
  button, select, input[type="search"] {
    font: inherit; border: 1px solid #3a3a3a; background: #1c1c1c; color: inherit;
  }
  button { border-radius: 999px; padding: 4px 10px; cursor: pointer; }
  button.active, button.primary { background: #e8e8e8; color: #141414; border-color: #e8e8e8; }
  button:disabled { opacity: 0.4; cursor: default; }
  select, input[type="search"] { border-radius: 6px; padding: 6px 8px; }
  input[type="search"] { min-width: 280px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a2a2a; vertical-align: top; }
  th { font-weight: 600; }
  th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; width: 72px; }
  tr.pick { cursor: pointer; }
  tr.pick.active td { background: #2a2a2a; }
  code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; }
  .path { word-break: break-all; }
  .detail { border: 1px solid #3a3a3a; margin-top: 16px; padding: 12px 16px; background: #1c1c1c; }
  .detail h3 { margin: 0; font-size: 15px; font-weight: 600; }
  label.show { display: flex; gap: 8px; align-items: center; margin: 12px 0; }
  pre { margin: 0; padding: 12px; background: #101010; color: #e6e6e6; overflow: auto; max-height: 70vh; }
  .bars { margin-top: 8px; }
  .bar-row { display: grid; grid-template-columns: 280px 1fr 72px; gap: 8px; align-items: center;
    margin: 2px 0; font-size: 12px; }
  .track { display: flex; height: 10px; background: #2a2a2a; }
  .track i { display: block; height: 10px; }
  .swatch { display: inline-block; width: 10px; height: 10px; margin-right: 4px; vertical-align: -1px; }
  .fill-ok { background: #1b7f4a; }
  .fill-bad { background: #b42318; }
  .fill-skip { background: #5b7c99; }
</style>
</head>
<body>
  <h1>Normalized Redfish schema report</h1>
  <p class="muted">Each JSON file under fixtures/*/normalized, checked against the DMTF schema named by its @odata.type. Open a document and turn on complete output to see the full JSON. Invalid documents are embedded in this page.</p>
  <div id="stats"></div>
  <h2>Valid and invalid documents by model</h2>
  <p class="small">Source: fixtures normalized trees. Bar length is the document count. Sorted by invalid count.</p>
  <p class="small"><i class="swatch fill-ok"></i>Valid <i class="swatch fill-bad"></i>Invalid <i class="swatch fill-skip"></i>Skipped</p>
  <div id="bars" class="bars"></div>
  <h2>Invalid documents</h2>
  <div id="vendors" class="pills"></div>
  <div class="row">
    <select id="model"></select>
    <input id="query" type="search" placeholder="Filter by path, type, or error">
  </div>
  <div id="families" class="pills"></div>
  <h2>Issues by object and property</h2>
  <p class="small">One row per object type and property. Count is how many times that property fails. Ordered by count.</p>
  <p id="group-range" class="small"></p>
  <table>
    <thead><tr><th class="num">Count</th><th>Object</th><th>Property</th><th>Issue</th><th></th></tr></thead>
    <tbody id="groups"></tbody>
  </table>
  <h2>Documents in the selected group</h2>
  <p id="range" class="small"></p>
  <table>
    <thead><tr><th>Object type</th><th>Property</th><th>Issue</th><th>Model</th><th>Resource</th><th></th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <div class="row">
    <button id="prev" type="button">Previous</button>
    <button id="next" type="button">Next</button>
    <span id="pager" class="small"></span>
  </div>
  <div id="detail"></div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById("payload").textContent);
const PAGE = 20;
const FAMILIES = [
  ["etag", "Null etag"],
  ["unknown", "Unknown property"],
  ["null", "Null value"],
  ["enum", "Bad enum"],
  ["pattern", "Pattern"],
  ["other", "Other"]
];
const state = {
  vendor: "all",
  model: "all",
  family: "all",
  group: "",
  query: "",
  page: 0,
  selected: "",
  showFull: localStorage.getItem("schema-invalid-show-full") === "1"
};

function familyOf(path, message) {
  if (path.includes("etag") && message.startsWith("None is not of type")) return "etag";
  if (message.includes("does not match any of the regexes") || message.startsWith("Additional properties")) return "unknown";
  if (message.includes("is not one of")) return "enum";
  if (message.includes("does not match '") || message.includes('does not match "')) return "pattern";
  if (message.startsWith("None is not of type")) return "null";
  return "other";
}
function hitKey(hit) { return hit[0] + "\\n" + hit[1] + "\\n" + hit[2]; }
function objectTypeName(hit) {
  const raw = hit[3] || "";
  const name = raw.split(".").pop();
  return name || "(no type)";
}
function familyLabel(id) {
  for (const pair of FAMILIES) if (pair[0] === id) return pair[1];
  return "Other";
}
function issueMessage(issue) { return DATA.messages[issue[1]]; }
function propertyName(issue) {
  const names = issueProperties(issue);
  return names.length ? names[0] : issue[0];
}
function issueProperties(issue) {
  const path = issue[0];
  const message = issueMessage(issue);
  if (message.includes("does not match any of the regexes") || message.startsWith("Additional properties")) {
    const cut = message.search(/ do(?:es)? not match| are not allowed/);
    const head = cut >= 0 ? message.slice(0, cut) : message;
    const names = Array.from(head.matchAll(/'([^']+)'/g), (match) => match[1]);
    if (names.length) return names;
  }
  const quoted = message.match(/^'([^']+)'/);
  if ((path === "$" || path.endsWith("]")) && quoted) return [quoted[1]];
  const parts = path.split(".");
  let leaf = parts[parts.length - 1] || path;
  const bracket = leaf.indexOf("[");
  if (bracket >= 0) leaf = leaf.slice(0, bracket);
  if (leaf && leaf !== "$") return [leaf];
  if (quoted) return [quoted[1]];
  return [path];
}
function groupKey(objectName, property, family) {
  return objectName + "\\n" + property + "\\n" + family;
}
function compareIssues(a, b) {
  const byProp = propertyName(a).localeCompare(propertyName(b));
  if (byProp) return byProp;
  const byFamily = familyLabel(familyOf(a[0], issueMessage(a))).localeCompare(
    familyLabel(familyOf(b[0], issueMessage(b)))
  );
  if (byFamily) return byFamily;
  return a[0].localeCompare(b[0]);
}
function primaryIssue(hit) {
  if (!hit[4].length) return null;
  return hit[4].slice().sort(compareIssues)[0];
}
function compareHits(a, b) {
  const byType = (a[3] || "").localeCompare(b[3] || "");
  if (byType) return byType;
  const ia = primaryIssue(a);
  const ib = primaryIssue(b);
  if (ia && ib) {
    const byProp = propertyName(ia).localeCompare(propertyName(ib));
    if (byProp) return byProp;
    const byFamily = familyOf(ia[0], issueMessage(ia)).localeCompare(familyOf(ib[0], issueMessage(ib)));
    if (byFamily) return byFamily;
  }
  return (a[0] + "/" + a[1] + "/" + a[2]).localeCompare(b[0] + "/" + b[1] + "/" + b[2]);
}
function hitFamilies(hit) {
  const found = new Set();
  for (const issue of hit[4]) found.add(familyOf(issue[0], DATA.messages[issue[1]]));
  return found;
}
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}
function hitInGroup(hit, key) {
  for (const issue of hit[4]) {
    const family = familyOf(issue[0], issueMessage(issue));
    if (state.family !== "all" && family !== state.family) continue;
    for (const property of issueProperties(issue)) {
      if (groupKey(objectTypeName(hit), property, family) === key) return true;
    }
  }
  return false;
}
function filtered() {
  const needle = state.query.trim().toLowerCase();
  return DATA.hits.filter((hit) => {
    if (state.vendor !== "all" && hit[0] !== state.vendor) return false;
    if (state.model !== "all" && hit[0] + "/" + hit[1] !== state.model) return false;
    if (state.family !== "all" && !hitFamilies(hit).has(state.family)) return false;
    if (state.group && !hitInGroup(hit, state.group)) return false;
    if (!needle) return true;
    const blob = (hit[2] + " " + hit[3] + " " + hit[4].map((issue) => issue[0] + " " + DATA.messages[issue[1]]).join(" ")).toLowerCase();
    return blob.includes(needle);
  }).slice().sort(compareHits);
}
function baseHits() {
  return DATA.hits.filter((hit) => {
    if (state.vendor !== "all" && hit[0] !== state.vendor) return false;
    if (state.model !== "all" && hit[0] + "/" + hit[1] !== state.model) return false;
    const needle = state.query.trim().toLowerCase();
    if (!needle) return true;
    const blob = (hit[2] + " " + hit[3] + " " + hit[4].map((issue) => issue[0] + " " + DATA.messages[issue[1]]).join(" ")).toLowerCase();
    return blob.includes(needle);
  });
}

function renderStats() {
  const root = document.getElementById("stats");
  root.replaceChildren();
  const wrap = el("div", null, "stats");
  const items = [
    [DATA.checked.toLocaleString(), "Documents checked", ""],
    [DATA.valid.toLocaleString(), "Valid", "ok"],
    [DATA.invalid.toLocaleString(), "Invalid", "bad"],
    [DATA.skipped.toLocaleString(), "Skipped, no DMTF schema", ""]
  ];
  for (const [value, label, tone] of items) {
    const cell = el("div", null, "stat");
    cell.append(el("b", value, tone), el("span", label));
    wrap.append(cell);
  }
  root.append(wrap);
}
function renderBars() {
  const root = document.getElementById("bars");
  root.replaceChildren();
  const max = Math.max(...DATA.models.map((item) => item.checked), 1);
  for (const item of DATA.models) {
    const row = el("div", null, "bar-row");
    row.append(el("span", item.vendor + " " + item.model.replaceAll("_", " ")));
    const track = el("div", null, "track");
    for (const [count, fill] of [[item.valid, "fill-ok"], [item.invalid, "fill-bad"], [item.skipped, "fill-skip"]]) {
      const part = document.createElement("i");
      part.className = fill;
      part.style.width = (count / max * 100) + "%";
      track.append(part);
    }
    row.append(track, el("span", String(item.invalid) + " invalid"));
    root.append(row);
  }
}
function renderVendors() {
  const root = document.getElementById("vendors");
  root.replaceChildren();
  const names = ["all", ...Array.from(new Set(DATA.models.map((item) => item.vendor))).sort()];
  for (const name of names) {
    const button = el("button", name === "all" ? "All vendors" : name);
    button.type = "button";
    if (state.vendor === name) button.className = "active";
    button.addEventListener("click", () => {
      state.vendor = name;
      state.model = "all";
      state.group = "";
      state.page = 0;
      renderVendors();
      renderModels();
      renderFamilies();
      renderGroups();
      renderList();
    });
    root.append(button);
  }
}
function renderModels() {
  const select = document.getElementById("model");
  const current = state.model;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "All models";
  select.append(all);
  for (const item of DATA.models) {
    if (state.vendor !== "all" && item.vendor !== state.vendor) continue;
    const option = document.createElement("option");
    option.value = item.vendor + "/" + item.model;
    option.textContent = item.vendor + " " + item.model.replaceAll("_", " ");
    select.append(option);
  }
  select.value = Array.from(select.options).some((option) => option.value === current) ? current : "all";
  state.model = select.value;
}
function renderFamilies() {
  const root = document.getElementById("families");
  root.replaceChildren();
  const counts = {};
  for (const [id] of FAMILIES) counts[id] = 0;
  for (const hit of baseHits()) {
    for (const id of hitFamilies(hit)) counts[id] += 1;
  }
  const all = el("button", "All issues");
  all.type = "button";
  if (state.family === "all") all.className = "active";
  all.addEventListener("click", () => { state.family = "all"; state.group = ""; state.page = 0; renderFamilies(); renderGroups(); renderList(); });
  root.append(all);
  for (const [id, label] of FAMILIES) {
    if (!counts[id]) continue;
    const button = el("button", label + " " + counts[id].toLocaleString());
    button.type = "button";
    if (state.family === id) button.className = "active";
    button.addEventListener("click", () => { state.family = id; state.group = ""; state.page = 0; renderFamilies(); renderGroups(); renderList(); });
    root.append(button);
  }
}
function renderGroups() {
  const body = document.getElementById("groups");
  body.replaceChildren();
  const groups = new Map();
  for (const hit of baseHits()) {
    for (const issue of hit[4]) {
      const family = familyOf(issue[0], issueMessage(issue));
      if (state.family !== "all" && family !== state.family) continue;
      for (const property of issueProperties(issue)) {
        const key = groupKey(objectTypeName(hit), property, family);
        let group = groups.get(key);
        if (!group) {
          group = {
            key: key,
            object: objectTypeName(hit),
            property: property,
            family: family,
            count: 0,
            sample: hitKey(hit)
          };
          groups.set(key, group);
        }
        group.count += 1;
      }
    }
  }
  if (state.group && !groups.has(state.group)) state.group = "";
  const rows = Array.from(groups.values()).sort((a, b) =>
    b.count - a.count || a.object.localeCompare(b.object) || a.property.localeCompare(b.property) || a.family.localeCompare(b.family)
  );
  document.getElementById("group-range").textContent = rows.length.toLocaleString() + " groups";
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = "No issues match these filters.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const group of rows) {
    const row = document.createElement("tr");
    row.className = "pick" + (state.group === group.key ? " active" : "");
    row.append(
      el("td", group.count.toLocaleString(), "num"),
      el("td", group.object),
      el("td", group.property),
      el("td", familyLabel(group.family))
    );
    const action = document.createElement("td");
    const sample = el("button", "Sample");
    sample.type = "button";
    if (state.selected === group.sample && state.group === group.key) sample.className = "primary";
    sample.addEventListener("click", (event) => {
      event.stopPropagation();
      state.group = group.key;
      state.page = 0;
      state.selected = group.sample;
      state.showFull = true;
      renderGroups();
      renderList();
      renderDetail();
      document.getElementById("detail").scrollIntoView({block: "nearest"});
    });
    action.append(sample);
    row.append(action);
    row.addEventListener("click", () => {
      state.group = state.group === group.key ? "" : group.key;
      state.page = 0;
      state.selected = "";
      renderGroups();
      renderList();
      renderDetail();
    });
    body.append(row);
  }
}
function renderList() {
  const body = document.getElementById("rows");
  body.replaceChildren();
  if (!state.group) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "Select a group to list its documents.";
    row.append(cell);
    body.append(row);
    document.getElementById("range").textContent = "No group selected.";
    document.getElementById("pager").textContent = "";
    document.getElementById("prev").disabled = true;
    document.getElementById("next").disabled = true;
    return;
  }
  const shown = filtered();
  const pages = Math.max(1, Math.ceil(shown.length / PAGE));
  if (state.page > pages - 1) state.page = pages - 1;
  if (state.page < 0) state.page = 0;
  const start = state.page * PAGE;
  const slice = shown.slice(start, start + PAGE);
  body.replaceChildren();
  if (!slice.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.textContent = "No documents match these filters.";
    row.append(cell);
    body.append(row);
  }
  for (const hit of slice) {
    const row = document.createElement("tr");
    const issue = primaryIssue(hit);
    const property = issue ? propertyName(issue) : "";
    const kind = issue ? familyLabel(familyOf(issue[0], issueMessage(issue))) : "";
    row.append(
      el("td", objectTypeName(hit)),
      el("td", property),
      el("td", kind),
      el("td", hit[0] + " " + hit[1].replaceAll("_", " ")),
      el("td", hit[2], "path")
    );
    const action = document.createElement("td");
    const button = el("button", "Open");
    button.type = "button";
    if (hitKey(hit) === state.selected) button.className = "primary";
    button.addEventListener("click", () => {
      state.selected = hitKey(hit);
      renderList();
      renderDetail();
    });
    action.append(button);
    row.append(action);
    body.append(row);
  }
  const end = Math.min(start + PAGE, shown.length);
  document.getElementById("range").textContent = shown.length.toLocaleString() + " documents" +
    (shown.length ? ", showing " + (start + 1) + "–" + end : "");
  document.getElementById("pager").textContent = "Page " + (state.page + 1) + " of " + pages;
  document.getElementById("prev").disabled = state.page === 0;
  document.getElementById("next").disabled = state.page + 1 >= pages;
}
function renderDetail() {
  const root = document.getElementById("detail");
  root.replaceChildren();
  const index = DATA.hits.findIndex((hit) => hitKey(hit) === state.selected);
  if (index < 0) return;
  const hit = DATA.hits[index];
  const box = el("div", null, "detail");
  const head = document.createElement("div");
  head.className = "row";
  const title = el("h3", hit[0] + " / " + hit[1].replaceAll("_", " "));
  const close = el("button", "Close");
  close.type = "button";
  close.addEventListener("click", () => { state.selected = ""; renderList(); renderDetail(); });
  head.append(title, close);
  box.append(head, el("p", hit[3]), el("p", hit[2], "muted path"));
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  hr.append(el("th", "Property"), el("th", "Issue"), el("th", "JSON path"), el("th", "Schema error"));
  thead.append(hr);
  const tbody = document.createElement("tbody");
  for (const issue of hit[4].slice().sort(compareIssues)) {
    const tr = document.createElement("tr");
    tr.append(
      el("td", propertyName(issue)),
      el("td", familyLabel(familyOf(issue[0], issueMessage(issue)))),
      el("td", issue[0], "path"),
      el("td", issueMessage(issue))
    );
    tbody.append(tr);
  }
  table.append(thead, tbody);
  const label = el("label", null, "show");
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = state.showFull;
  checkbox.addEventListener("change", () => {
    state.showFull = checkbox.checked;
    localStorage.setItem("schema-invalid-show-full", state.showFull ? "1" : "0");
    renderDetail();
  });
  label.append(checkbox, document.createTextNode("Show complete output"));
  box.append(table, label);
  if (state.showFull) {
    const pre = document.createElement("pre");
    const doc = DATA.docs[index];
    pre.textContent = typeof doc === "string" ? doc : JSON.stringify(doc, null, 2);
    box.append(pre);
  }
  root.append(box);
}

renderStats();
renderBars();
renderVendors();
renderModels();
renderFamilies();
renderGroups();
renderList();
document.getElementById("model").addEventListener("change", (event) => {
  state.model = event.target.value;
  state.group = "";
  state.page = 0;
  renderFamilies();
  renderGroups();
  renderList();
});
document.getElementById("query").addEventListener("input", (event) => {
  state.query = event.target.value;
  state.group = "";
  state.page = 0;
  renderFamilies();
  renderGroups();
  renderList();
});
document.getElementById("prev").addEventListener("click", () => { state.page -= 1; renderList(); });
document.getElementById("next").addEventListener("click", () => { state.page += 1; renderList(); });
</script>
</body>
</html>
"""


def _load(path: Path) -> tuple[object, SchemaResult]:
    raw = path.read_text(encoding="utf-8")
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        return raw, SchemaResult(
            "invalid", None, "", (SchemaIssue("$", f"invalid JSON: {exc}"),)
        )
    return document, validate_document(document)


def build_payload(fixtures: Path) -> dict:
    counts: Counter[str] = Counter()
    by_model: dict[tuple[str, str], Counter[str]] = {}
    invalid = []
    for path in iter_normalized_documents(fixtures):
        rel = path.relative_to(fixtures)
        parts = rel.parts
        key = (parts[0], parts[1])
        document, result = _load(path)
        bucket = by_model.setdefault(key, Counter())
        bucket[result.status] += 1
        counts[result.status] += 1
        if result.status != "invalid":
            continue
        norm_rel = relpath_to_uri(Path(*parts[3:]))
        invalid.append(
            [
                parts[0],
                parts[1],
                norm_rel,
                result.odata_type or "",
                [[issue.path, issue.message] for issue in result.issues],
                document,
            ]
        )

    messages: list[str] = []
    index: dict[str, int] = {}

    def mid(message: str) -> int:
        found = index.get(message)
        if found is None:
            found = len(messages)
            index[message] = found
            messages.append(message)
        return found

    invalid.sort(key=lambda row: (row[0], row[1], row[2]))
    hits = []
    docs = []
    for vendor, model, path, otype, issues, document in invalid:
        hits.append(
            [vendor, model, path, otype, [[ipath, mid(imsg)] for ipath, imsg in issues]]
        )
        docs.append(document)

    models = []
    for (vendor, model), bucket in sorted(
        by_model.items(), key=lambda item: (-item[1]["invalid"], item[0])
    ):
        models.append(
            {
                "vendor": vendor,
                "model": model,
                "checked": bucket["valid"] + bucket["invalid"] + bucket["skipped"],
                "valid": bucket["valid"],
                "invalid": bucket["invalid"],
                "skipped": bucket["skipped"],
            }
        )
    return {
        "checked": sum(counts.values()),
        "valid": counts["valid"],
        "invalid": counts["invalid"],
        "skipped": counts["skipped"],
        "models": models,
        "messages": messages,
        "hits": hits,
        "docs": docs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()
    if not schema_bundle_available():
        print("DMTF json-schema bundle is missing", file=sys.stderr)
        return 2
    payload = build_payload(_PUBLIC / "fixtures")
    blob = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).replace(
        "<", "\\u003c"
    )
    html = _PAGE.replace("__PAYLOAD__", blob)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(
        args.output,
        "checked",
        payload["checked"],
        "valid",
        payload["valid"],
        "invalid",
        payload["invalid"],
        "docs",
        len(payload["docs"]),
        "bytes",
        args.output.stat().st_size,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
