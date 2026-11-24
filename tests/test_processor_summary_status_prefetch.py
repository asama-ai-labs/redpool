# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Asama Inc.

"""ComputerSystem: synthesize ProcessorSummary.Status from CPU processor members."""

from __future__ import annotations

from typing import Any, Dict

from normalizers import evaluate
from normalizers.systems.computer_system.base import BaseComputerSystemNormalizer
from normalizers.types import NormalizationContext
from redpool.config import RedpoolConfig


class _FakeResp:
    def __init__(self, body: Dict[str, Any], status: int = 200) -> None:
        self.status = status
        self.dict = body


class _FakeClient:
    def __init__(self, mapping: Dict[str, Dict[str, Any]]) -> None:
        self._mapping = mapping

    def get(self, path: str, args: Any = None, headers: Any = None) -> _FakeResp:
        body = self._mapping.get(path, {})
        return _FakeResp(body)


class _FakeLogger:
    def error(self, *args: object, **kwargs: object) -> None:
        pass


def _ctx(
    data: dict,
    client: _FakeClient | None,
    *,
    prefetch: bool = True,
    proc_summary_status: bool = True,
) -> NormalizationContext:
    cfg = RedpoolConfig(
        overrides={
            "normalization": {"build_processor_summary_status": proc_summary_status}
        }
    )
    ctx = NormalizationContext(
        data=data,
        client=client,
        logger=_FakeLogger(),
        config=cfg,
    )
    if client is not None and prefetch:
        BaseComputerSystemNormalizer().prefetch(ctx)
    return ctx


def test_synthesizes_status_when_processor_summary_missing():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    p2 = f"{proc_coll}/cpu1"
    client = _FakeClient(
        {
            proc_coll: {
                "Members": [
                    {"@odata.id": p1},
                    {"@odata.id": p2},
                ]
            },
            p1: {
                "ProcessorType": "CPU",
                "Status": {"Health": "OK", "State": "Enabled"},
            },
            p2: {
                "ProcessorType": "CPU",
                "Status": {"Health": "OK", "State": "Enabled"},
            },
        }
    )
    data = {
        "@odata.id": sys_path,
        "Processors": {"@odata.id": proc_coll},
    }
    ctx = _ctx(data, client)
    n = BaseComputerSystemNormalizer()
    out = evaluate(n.field_map(), ctx)["ProcessorSummary"]
    assert out["Status"]["Health"] == "OK"
    assert out["Status"]["HealthRollup"] == "OK"
    assert out["Status"]["State"] == "Enabled"


def test_worst_health_across_cpus():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    p2 = f"{proc_coll}/cpu1"
    client = _FakeClient(
        {
            proc_coll: {
                "Members": [{"@odata.id": p1}, {"@odata.id": p2}],
            },
            p1: {"ProcessorType": "CPU", "Status": {"Health": "OK"}},
            p2: {"ProcessorType": "CPU", "Status": {"Health": "Warning"}},
        }
    )
    data = {"@odata.id": sys_path, "Processors": {"@odata.id": proc_coll}}
    ctx = _ctx(data, client)
    out = evaluate(BaseComputerSystemNormalizer().field_map(), ctx)["ProcessorSummary"]
    assert out["Status"]["Health"] == "Warning"
    assert out["Status"]["HealthRollup"] == "Warning"


def test_mixed_state_is_omitted():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    p2 = f"{proc_coll}/cpu1"
    client = _FakeClient(
        {
            proc_coll: {"Members": [{"@odata.id": p1}, {"@odata.id": p2}]},
            p1: {"ProcessorType": "CPU", "Status": {"State": "Enabled"}},
            p2: {"ProcessorType": "CPU", "Status": {"State": "Disabled"}},
        }
    )
    data = {
        "@odata.id": sys_path,
        "Processors": {"@odata.id": proc_coll},
    }
    ctx = _ctx(data, client)
    out = evaluate(BaseComputerSystemNormalizer().field_map(), ctx)["ProcessorSummary"]
    # "Unknown" is not a Status.State value, so mixed states leave State out.
    assert "State" not in out.get("Status", {})


def test_preserves_bmc_healthrollup_when_filling_health():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    client = _FakeClient(
        {
            proc_coll: {"Members": [{"@odata.id": p1}]},
            p1: {
                "ProcessorType": "CPU",
                "Status": {"Health": "OK", "State": "Enabled"},
            },
        }
    )
    data = {
        "@odata.id": sys_path,
        "Processors": {"@odata.id": proc_coll},
        "ProcessorSummary": {"Status": {"HealthRollup": "OK"}},
    }
    ctx = _ctx(data, client)
    out = evaluate(BaseComputerSystemNormalizer().field_map(), ctx)["ProcessorSummary"]
    assert out["Status"]["HealthRollup"] == "OK"
    assert out["Status"]["Health"] == "OK"
    assert out["Status"]["State"] == "Enabled"


def test_skips_when_flag_disabled():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    client = _FakeClient(
        {
            proc_coll: {"Members": [{"@odata.id": p1}]},
            p1: {"ProcessorType": "CPU", "Status": {"Health": "Critical"}},
        }
    )
    data = {"@odata.id": sys_path, "Processors": {"@odata.id": proc_coll}}
    ctx = _ctx(data, client, proc_summary_status=False)
    BaseComputerSystemNormalizer().prefetch(ctx)
    assert "processor_summary_status" not in ctx.prefetched


def test_skips_non_cpu_processors():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    g1 = f"{proc_coll}/gpu0"
    client = _FakeClient(
        {
            proc_coll: {"Members": [{"@odata.id": g1}]},
            g1: {"ProcessorType": "GPU", "Status": {"Health": "OK"}},
        }
    )
    data = {"@odata.id": sys_path, "Processors": {"@odata.id": proc_coll}}
    ctx = _ctx(data, client)
    BaseComputerSystemNormalizer().prefetch(ctx)
    assert "processor_summary_status" not in ctx.prefetched


def test_member_health_falls_back_to_healthrollup():
    sys_path = "/redfish/v1/Systems/1"
    proc_coll = f"{sys_path}/Processors"
    p1 = f"{proc_coll}/cpu0"
    client = _FakeClient(
        {
            proc_coll: {"Members": [{"@odata.id": p1}]},
            p1: {"ProcessorType": "CPU", "Status": {"HealthRollup": "Warning"}},
        }
    )
    data = {"@odata.id": sys_path, "Processors": {"@odata.id": proc_coll}}
    ctx = _ctx(data, client)
    out = evaluate(BaseComputerSystemNormalizer().field_map(), ctx)["ProcessorSummary"]
    assert out["Status"]["Health"] == "Warning"
