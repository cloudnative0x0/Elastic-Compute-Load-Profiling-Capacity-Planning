from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .models import HardwareSku


@dataclass(frozen=True)
class ProjectMetrics:
    """Small business-facing input model used by the main notebook."""

    mau: int = 100_000
    dau_percent: float = 20.0
    business_events_per_user_day: float = 20.0
    rpc_per_event: float = 3.0
    active_hours_day: float = 12.0
    peak_factor: float = 4.0
    cpu_ms_per_rpc: float = 5.0
    latency_ms: float = 100.0
    memory_mib_per_inflight: float = 1.0
    base_ram_gib: float = 1.0
    target_cpu_percent: float = 65.0
    growth_percent: float = 30.0
    billing_hours_month: float = 720.0
    availability_sla_percent: float = 99.9
    min_instances: int | None = None
    reserve_instances: int | None = None

    def __post_init__(self) -> None:
        positive = (
            "mau",
            "business_events_per_user_day",
            "rpc_per_event",
            "active_hours_day",
            "peak_factor",
            "cpu_ms_per_rpc",
            "latency_ms",
            "target_cpu_percent",
            "billing_hours_month",
        )
        for name in positive:
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if not 0 < self.dau_percent <= 100:
            raise ValueError("dau_percent must be in (0, 100]")
        if not 0 < self.target_cpu_percent <= 100:
            raise ValueError("target_cpu_percent must be in (0, 100]")
        if self.memory_mib_per_inflight < 0 or self.base_ram_gib < 0:
            raise ValueError("memory values must be >= 0")
        if not 0 < self.availability_sla_percent < 100:
            raise ValueError("availability_sla_percent must be in (0, 100)")
        if self.min_instances is not None and self.min_instances < 1:
            raise ValueError("min_instances must be >= 1 when provided")
        if self.reserve_instances is not None and self.reserve_instances < 0:
            raise ValueError("reserve_instances must be >= 0 when provided")
        if self.growth_percent < 0:
            raise ValueError("growth and instance policy values are invalid")


def deployment_policy(metrics: ProjectMetrics) -> tuple[int, int, str]:
    """Translate a planning SLA target into a simple failure-tolerant topology."""

    sla = metrics.availability_sla_percent
    if sla >= 99.99:
        automatic = (4, 1, "multi-zone: 3 working + 1 reserve")
    elif sla >= 99.95:
        automatic = (3, 1, "multi-zone: 2 working + 1 reserve")
    elif sla >= 99.9:
        automatic = (2, 1, "two instances: 1 working + 1 reserve")
    else:
        automatic = (1, 0, "single instance; no failover")
    minimum = metrics.min_instances if metrics.min_instances is not None else automatic[0]
    reserve = (
        metrics.reserve_instances
        if metrics.reserve_instances is not None
        else automatic[1]
    )
    return minimum, reserve, automatic[2] if metrics.min_instances is None else "manual override"


def calculate_project_metrics(metrics: ProjectMetrics) -> dict[str, float]:
    """Convert a compact set of business assumptions into peak infrastructure demand."""

    growth = 1 + metrics.growth_percent / 100
    dau = metrics.mau * metrics.dau_percent / 100
    events_day = dau * metrics.business_events_per_user_day * growth
    average_event_rps = events_day / (metrics.active_hours_day * 3600)
    peak_event_rps = average_event_rps * metrics.peak_factor
    peak_rpc = peak_event_rps * metrics.rpc_per_event
    monthly_rpc = events_day * metrics.rpc_per_event * 30
    concurrency = peak_rpc * metrics.latency_ms / 1000
    cpu_cores = peak_rpc * metrics.cpu_ms_per_rpc / 1000
    variable_ram_gib = concurrency * metrics.memory_mib_per_inflight / 1024
    required_vcpu = cpu_cores / (metrics.target_cpu_percent / 100)
    required_ram_gib = metrics.base_ram_gib + variable_ram_gib
    downtime_budget_minutes_month = (
        (100 - metrics.availability_sla_percent) / 100 * 30 * 24 * 60
    )
    return {
        "mau": float(metrics.mau),
        "dau": dau,
        "events_day": events_day,
        "peak_event_rps": peak_event_rps,
        "peak_rpc": peak_rpc,
        "monthly_rpc": monthly_rpc,
        "concurrency": concurrency,
        "cpu_cores_at_peak": cpu_cores,
        "variable_ram_gib": variable_ram_gib,
        "required_vcpu": required_vcpu,
        "required_ram_gib": required_ram_gib,
        "downtime_budget_minutes_month": downtime_budget_minutes_month,
    }


def recommend_vm_per_provider(
    metrics: ProjectMetrics,
    catalog: list[HardwareSku],
    *,
    include_accelerators: bool = False,
    allowed_architectures: tuple[str, ...] = ("x86_64",),
) -> list[dict[str, Any]]:
    """Return the lowest monthly-cost feasible VM layout for every provider."""

    load = calculate_project_metrics(metrics)
    min_instances, reserve_instances, topology = deployment_policy(metrics)
    candidates: list[dict[str, Any]] = []
    choices_by_provider: dict[str, int] = {}
    for sku in catalog:
        category = getattr(sku, "category", "general_purpose")
        if sku.architecture not in allowed_architectures:
            continue
        if not include_accelerators and category in {"gpu", "fpga", "ml_accelerator"}:
            continue
        usable_ram_per_instance = sku.ram_gib - metrics.base_ram_gib
        if usable_ram_per_instance <= 0:
            continue
        choices_by_provider[sku.provider] = choices_by_provider.get(sku.provider, 0) + 1
        effective_vcpu = sku.vcpu * sku.cpu_capacity_factor
        cpu_instances = math.ceil(load["required_vcpu"] / effective_vcpu)
        ram_instances = math.ceil(load["variable_ram_gib"] / usable_ram_per_instance)
        availability_instances = max(1, min_instances - reserve_instances)
        working = max(
            cpu_instances,
            ram_instances,
            availability_instances,
        )
        instances = max(min_instances, working + reserve_instances)
        hourly_price_usd = (
            sku.hourly_price_usd
            if sku.hourly_price_usd is not None
            else sku.monthly_price_usd / 730
        )
        monthly_usd = instances * hourly_price_usd * metrics.billing_hours_month
        monthly_usd_without_reserve = (
            working * hourly_price_usd * metrics.billing_hours_month
        )
        monthly_native_without_reserve = (
            working * sku.hourly_price * metrics.billing_hours_month
        )
        if availability_instances >= max(cpu_instances, ram_instances):
            constraint = "minimum availability"
        elif cpu_instances >= ram_instances:
            constraint = "CPU"
        else:
            constraint = "RAM"
        candidates.append(
            {
                "provider": sku.provider,
                "region": sku.region,
                "vm": sku.sku,
                "instances": instances,
                "working_instances": working,
                "reserve_instances": instances - working,
                "total_vcpu": instances * sku.vcpu,
                "total_effective_vcpu": instances * effective_vcpu,
                "total_ram_gib": instances * sku.ram_gib,
                "peak_cpu_utilization_percent": (
                    load["cpu_cores_at_peak"] / (working * effective_vcpu) * 100
                ),
                "peak_ram_utilization_percent": (
                    (working * metrics.base_ram_gib + load["variable_ram_gib"])
                    / (working * sku.ram_gib)
                    * 100
                ),
                "limiting_factor": constraint,
                "monthly_usd": monthly_usd,
                "monthly_usd_without_reserve": monthly_usd_without_reserve,
                "reserve_cost_usd": monthly_usd - monthly_usd_without_reserve,
                "monthly_native_without_reserve": monthly_native_without_reserve,
                "monthly_native_ha": (
                    instances * sku.hourly_price * metrics.billing_hours_month
                ),
                "price_currency": sku.price_currency,
                "tax_included": sku.tax_included,
                "capacity_basis": sku.capacity_basis,
                "catalog_scope": sku.catalog_scope,
                "sla_target_percent": metrics.availability_sla_percent,
                "topology_policy": topology,
                "cost_per_million_rpc_usd": (
                    monthly_usd_without_reserve / load["monthly_rpc"] * 1_000_000
                    if load["monthly_rpc"]
                    else 0.0
                ),
                "category": category,
                "price_date": sku.price_date,
                "price_source": sku.source,
            }
        )

    best: dict[str, dict[str, Any]] = {}
    for item in candidates:
        item["catalog_choices"] = choices_by_provider[item["provider"]]
        current = best.get(item["provider"])
        if current is None or (item["monthly_usd"], item["instances"]) < (
            current["monthly_usd"],
            current["instances"],
        ):
            best[item["provider"]] = item
    return sorted(best.values(), key=lambda row: row["monthly_usd"])


def build_business_summary(
    metrics: ProjectMetrics, catalog: list[HardwareSku]
) -> dict[str, Any]:
    """One-call API used by the notebook and future web UI."""

    load = calculate_project_metrics(metrics)
    recommendations = recommend_vm_per_provider(metrics, catalog)
    return {
        "inputs": asdict(metrics),
        "load": load,
        "recommendations": recommendations,
        "cheapest": recommendations[0] if recommendations else None,
    }
