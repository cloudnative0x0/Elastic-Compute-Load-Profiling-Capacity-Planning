#!/usr/bin/env python3
"""Build a dated VM snapshot from official provider price feeds.

The first adapter covers every Linux on-demand EC2 instance returned for the
selected AWS region. Other providers remain in the seed catalog until their
official inventory adapters (which require credentials/API keys) are enabled.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import certifi
except ImportError:  # pragma: no cover - system CA remains the fallback
    certifi = None


AWS_URL = (
    "https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/"
    "ec2-ondemand-without-sec-sel/EU%20(Frankfurt)/Linux/index.json"
)
RUB_PER_USD = 84.3363


def _supplemental_skus(price_date: str) -> list[dict[str, Any]]:
    """Verified public-price shapes and complete public preset tables."""

    def row(
        provider: str,
        region: str,
        sku: str,
        vcpu: float,
        ram: float,
        hourly: float,
        currency: str,
        source: str,
        category: str = "general_purpose",
        cpu_capacity_factor: float = 1.0,
        tax_included: bool = False,
        capacity_basis: str = "full_vcpu",
        catalog_scope: str = "partial",
    ) -> dict[str, Any]:
        hourly_usd = hourly if currency == "USD" else hourly / RUB_PER_USD
        return {
            "provider": provider,
            "region": region,
            "sku": sku,
            "vcpu": vcpu,
            "ram_gib": ram,
            "hourly_price": hourly,
            "price_currency": currency,
            "hourly_price_usd": hourly_usd,
            "monthly_price": hourly * 720,
            "monthly_price_usd": hourly_usd * 720,
            "price_date": price_date,
            "source": source,
            "category": category,
            "architecture": "x86_64",
            "cpu_capacity_factor": cpu_capacity_factor,
            "tax_included": tax_included,
            "capacity_basis": capacity_basis,
            "catalog_scope": catalog_scope,
            "pricing_model": "on_demand",
        }

    result = [
        row(
            "Microsoft Azure", "westeurope", "Standard_B1s", 1, 1,
            0.012, "USD",
            "https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Virtual%20Machines%27%20and%20armRegionName%20eq%20%27westeurope%27%20and%20armSkuName%20eq%20%27Standard_B1s%27%20and%20priceType%20eq%20%27Consumption%27",
            "burstable", 0.10, False, "guaranteed_baseline_cpu", "partial",
        ),
        row(
            "Microsoft Azure", "westeurope", "Standard_B1ms", 1, 2,
            0.024, "USD",
            "https://prices.azure.com/api/retail/prices?$filter=serviceName%20eq%20%27Virtual%20Machines%27%20and%20armRegionName%20eq%20%27westeurope%27%20and%20armSkuName%20eq%20%27Standard_B1ms%27%20and%20priceType%20eq%20%27Consumption%27",
            "burstable", 0.20, False, "guaranteed_baseline_cpu", "partial",
        ),
        row(
            "Google Cloud", "us-central1 (Iowa)", "e2-micro", 2, 1,
            0.008376428, "USD",
            "https://cloud.google.com/products/compute/pricing/general-purpose",
            "shared_core", 0.125, False, "fractional_effective_cpu", "partial",
        ),
        row(
            "Google Cloud", "us-central1 (Iowa)", "e2-small", 2, 2,
            0.016752855, "USD",
            "https://cloud.google.com/products/compute/pricing/general-purpose",
            "shared_core", 0.25, False, "fractional_effective_cpu", "partial",
        ),
        row(
            "Google Cloud", "us-central1 (Iowa)", "e2-medium", 2, 4,
            0.03350571, "USD",
            "https://cloud.google.com/products/compute/pricing/general-purpose",
            "shared_core", 0.50, False, "fractional_effective_cpu", "partial",
        ),
        row(
            "Yandex Cloud", "ru-central1", "standard-v3 / 2 vCPU 100% / 2 GiB",
            2, 2, 3.14, "RUB",
            "https://yandex.cloud/ru/docs/compute/pricing",
            "general_purpose", 1.0, True, "full_vcpu", "documented_examples",
        ),
        row(
            "Yandex Cloud", "ru-central1", "standard-v3 / 2 vCPU 20% / 2 GiB",
            2, 2, 1.70, "RUB",
            "https://yandex.cloud/ru/docs/compute/pricing",
            "shared_core", 0.20, True, "guaranteed_cpu_share", "documented_examples",
        ),
    ]

    nebius_source = "https://docs.nebius.com/compute/resources/pricing"
    for family, shapes in {
        "cpu-d3": [(2, 8), (4, 16), (8, 32), (16, 64), (32, 128), (48, 192), (64, 256), (96, 384), (128, 512)],
        "cpu-e2": [(2, 8), (4, 16), (8, 32), (16, 64), (32, 128), (48, 192), (64, 256), (80, 320)],
    }.items():
        for cpu, ram in shapes:
            result.append(row(
                "Nebius AI Cloud", "eu-north1", f"{family} / {cpu}vCPU-{ram}GB",
                cpu, ram, cpu * 0.012 + ram * 0.0032, "USD", nebius_source,
                "compute_optimized", 1.0, False, "full_vcpu",
                "complete_non_gpu_presets",
            ))

    cloud_source = "https://cdn.cloud.ru/docs/legal/tariffs/evolution/current-version/evolution-compute.pdf"
    cloud_shapes = {
        1.0: [
            (12,24,23.7534),(12,48,32.025),(12,96,52.0208),(16,128,48.1656),
            (16,256,80.7152),(16,32,23.7656),(16,64,31.9152),(1,1,1.2444),
            (1,2,1.48535),(24,192,72.2484),(24,32,31.48576),(24,48,35.6484),
            (24,96,47.8728),(2,16,8.2228),(2,4,2.9707),(2,8,5.5022),
            (32,128,63.8304),(32,256,96.3312),(32,64,47.5312),(40,320,120.414),
            (4,16,7.9788),(4,32,12.0414),(4,64,20.1788),(4,8,5.9414),
            (64,128,95.0624),(64,256,127.6608),(8,128,40.3576),(8,16,11.8828),
            (8,32,15.9576),(8,64,24.0828),
        ],
        0.10: [(1,1,.4148),(1,2,.49511666),(2,4,.99023334),(4,16,2.6596),(4,32,4.0138),(4,8,1.98046666),(8,16,3.96093334),(8,32,5.3192)],
        0.30: [(16,32,14.388192),(16,64,22.87744),(1,1,.64233),(1,2,.899262),(24,48,21.582288),(2,4,1.798524),(32,64,28.776384),(4,16,5.71936),(4,32,7.70796),(4,64,11.56194),(4,8,3.597048),(8,16,7.194096),(8,32,11.43872),(8,64,15.41592)],
    }
    for share, shapes in cloud_shapes.items():
        prefix = "VM" if share == 1 else f"VM {int(share * 100)}%"
        for cpu, ram, hourly in shapes:
            result.append(row(
                "Cloud.ru", "Russia / Evolution", f"{prefix} {cpu}vCPU/{ram}GB RAM",
                cpu, ram, hourly, "RUB", cloud_source,
                "general_purpose" if share == 1 else "shared_core", share, True,
                "full_vcpu" if share == 1 else "guaranteed_cpu_share",
                "complete_published_cpu_tariff",
            ))
    return result


def _number(value: str) -> float:
    match = re.search(r"[\d,.]+", value)
    if not match:
        raise ValueError(f"no number in {value!r}")
    return float(match.group().replace(",", ""))


def _network_mbps(value: str) -> float | None:
    match = re.search(r"([\d.]+)\s*(Gigabit|Megabit)", value, re.I)
    if not match:
        return None
    amount = float(match.group(1))
    return amount * 1000 if match.group(2).lower().startswith("giga") else amount


def _local_storage_gib(value: str) -> float | None:
    if value.lower() == "ebs only":
        return 0.0
    match = re.search(r"(?:(\d+)\s*x\s*)?([\d.]+)\s*(TB|GB)", value, re.I)
    if not match:
        return None
    count = int(match.group(1) or 1)
    size = float(match.group(2))
    return count * size * (1000 if match.group(3).upper() == "TB" else 1)


def _category(family: str) -> str:
    normalized = family.lower()
    if "gpu" in normalized:
        return "gpu"
    if "fpga" in normalized:
        return "fpga"
    if "asic" in normalized or "machine learning" in normalized:
        return "ml_accelerator"
    return normalized.replace(" ", "_")


def _aws_burstable_factor(sku: str) -> float | None:
    """Guaranteed CPU baseline as a fraction of every visible vCPU."""

    match = re.match(r"^(t1|t2|t3a?|t4g)\.([a-z0-9]+)$", sku)
    if not match:
        return None
    family, size = match.groups()
    if family == "t1":
        return 0.10
    if family == "t2":
        return {
            "nano": 0.05, "micro": 0.10, "small": 0.20, "medium": 0.20,
            "large": 0.30, "xlarge": 0.225, "2xlarge": 0.16875,
        }.get(size)
    return {
        "nano": 0.05, "micro": 0.10, "small": 0.20, "medium": 0.20,
        "large": 0.30, "xlarge": 0.40, "2xlarge": 0.40,
    }.get(size)


def _read_url_or_file(source: str) -> tuple[dict[str, Any], str]:
    if source.startswith(("http://", "https://")):
        ssl_context = (
            ssl.create_default_context(cafile=certifi.where())
            if certifi is not None
            else ssl.create_default_context()
        )
        with urllib.request.urlopen(source, timeout=120, context=ssl_context) as response:
            payload = response.read()
        origin = source
    else:
        path = Path(source)
        payload = path.read_bytes()
        origin = AWS_URL
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    return json.loads(payload), origin


def aws_skus(source: str, price_date: str) -> list[dict[str, Any]]:
    raw, origin = _read_url_or_file(source)
    region_name, records = next(iter(raw["regions"].items()))
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in records.values():
        sku = item["Instance Type"]
        if sku in seen:
            continue
        seen.add(sku)
        hourly = float(item["price"])
        if hourly <= 0:
            continue
        burstable_factor = _aws_burstable_factor(sku)
        burstable = burstable_factor is not None
        result.append(
            {
                "provider": "AWS",
                "region": "eu-central-1",
                "sku": sku,
                "vcpu": _number(item["vCPU"]),
                "ram_gib": _number(item["Memory"]),
                "max_iops": None,
                "disk_throughput_mb_s": None,
                "network_mbps": _network_mbps(item.get("Network Performance", "")),
                "hourly_price": hourly,
                "hourly_price_usd": hourly,
                "price_currency": "USD",
                "monthly_price": hourly * 720,
                "monthly_price_usd": hourly * 720,
                "price_date": price_date,
                "source": origin,
                "spec_source": origin,
                "category": "burstable" if burstable else _category(item["Instance Family"]),
                "architecture": "arm64" if re.match(r"^[a-z]+\d+g", sku) else "x86_64",
                "cpu_capacity_factor": burstable_factor or 1.0,
                "tax_included": False,
                "capacity_basis": (
                    "guaranteed_cpu_credit_baseline" if burstable else "full_vcpu"
                ),
                "catalog_scope": "complete_region_price_feed",
                "local_storage_gib": _local_storage_gib(item.get("Storage", "")),
                "pricing_model": "on_demand_linux",
                "performance_basis": "official_price_feed",
                "price_formula": "hourly_price * billing_hours_month",
                "supported_components": ["*"],
            }
        )
    return sorted(result, key=lambda row: row["sku"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default="configs/providers.full.json")
    parser.add_argument("--aws-source", default=AWS_URL)
    parser.add_argument("--price-date", default="2026-09-15")
    parser.add_argument("--output", default="configs/providers.full.json")
    args = parser.parse_args()

    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    non_aws = [
        row for row in seed["skus"]
        if row["provider"] not in {"AWS", "Nebius", "Nebius AI Cloud", "Cloud.ru"}
    ]
    merged_non_aws = {
        (row["provider"], row["region"], row["sku"]): row
        for row in non_aws + _supplemental_skus(args.price_date)
    }
    try:
        aws_rows = aws_skus(args.aws_source, args.price_date)
        aws_refresh_status = "downloaded from official feed"
    except (urllib.error.URLError, TimeoutError) as exc:
        aws_rows = [row for row in seed["skus"] if row["provider"] == "AWS"]
        if not aws_rows:
            raise
        aws_refresh_status = f"retained seed snapshot; refresh failed: {type(exc).__name__}"
        print(f"WARNING: AWS refresh failed; retaining {len(aws_rows)} seed rows")
    all_skus = aws_rows + list(merged_non_aws.values())
    default_scopes = {
        "AWS": "complete_region_price_feed",
        "Microsoft Azure": "partial",
        "Google Cloud": "partial",
        "Nebius AI Cloud": "complete_non_gpu_presets",
        "Yandex Cloud": "documented_examples",
        "Cloud.ru": "complete_published_cpu_tariff",
    }
    for sku in all_skus:
        if sku["provider"] == "AWS":
            burstable_factor = _aws_burstable_factor(sku["sku"])
            if burstable_factor is not None:
                sku["category"] = "burstable"
                sku["cpu_capacity_factor"] = burstable_factor
                sku["capacity_basis"] = "guaranteed_cpu_credit_baseline"
                sku["capacity_source"] = "https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html"
        hourly_usd = sku.get("hourly_price_usd")
        if hourly_usd is None:
            hourly_usd = (
                sku["hourly_price"]
                if sku.get("price_currency", "USD") == "USD"
                else sku["hourly_price"] / RUB_PER_USD
            )
        sku["hourly_price_usd"] = hourly_usd
        sku["monthly_price"] = sku["hourly_price"] * 720
        sku["monthly_price_usd"] = hourly_usd * 720
        sku["cpu_capacity_factor"] = sku.get("cpu_capacity_factor", 1.0)
        sku["tax_included"] = sku.get("tax_included", False)
        sku["capacity_basis"] = sku.get("capacity_basis", "full_vcpu")
        sku["catalog_scope"] = sku.get(
            "catalog_scope", default_scopes.get(sku["provider"], "partial")
        )
        sku["price_formula"] = "hourly_price * billing_hours_month"
    output = {
        "catalog_version": args.price_date,
        "comparison_basis": {
            "reference_hours_month": 720,
            "currency": "USD",
            "fx_note": "Native prices are authoritative; USD is comparison-only.",
            "excludes": ["storage", "public IP", "traffic", "support", "discounts"],
        },
        "fx_rates": {
            "RUB_per_USD": RUB_PER_USD,
            "as_of": args.price_date,
            "purpose": "comparison only; native totals are also returned",
            "source": "https://www.cbr.ru/currency_base/daily/",
        },
        "coverage": {
            "AWS": "complete Linux on-demand price feed for eu-central-1; burst credits require workload-specific validation",
            "Microsoft Azure": "partial verified sample in westeurope; not an exhaustive VM inventory",
            "Google Cloud": "partial verified E2 sample in us-central1; not an exhaustive VM inventory",
            "Nebius AI Cloud": "complete published non-GPU presets for eu-north1",
            "Yandex Cloud": "documented standard-v3 examples; platform supports custom configurations",
            "Cloud.ru": "complete CPU VM table from Evolution tariff 260619, effective 2026-06-29",
        },
        "refresh_status": {"AWS": aws_refresh_status},
        "skus": all_skus,
    }
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(all_skus)} SKUs to {args.output}")


if __name__ == "__main__":
    main()
