from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HardwareSku:
    provider: str
    region: str
    sku: str
    vcpu: float
    ram_gib: float
    hourly_price: float
    monthly_price_usd: float
    price_date: str
    source: str
    category: str = "general_purpose"
    architecture: str = "x86_64"
    price_currency: str = "USD"
    cpu_capacity_factor: float = 1.0
    hourly_price_usd: float | None = None
    tax_included: bool = False
    capacity_basis: str = "full_vcpu"
    catalog_scope: str = "partial"

    def __post_init__(self) -> None:
        if not self.provider or not self.region or not self.sku:
            raise ValueError("provider, region and sku are required")
        for name in ("vcpu", "ram_gib", "hourly_price", "monthly_price_usd"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be > 0")
        if not 0 < self.cpu_capacity_factor <= 1:
            raise ValueError("cpu_capacity_factor must be in (0, 1]")
        if self.hourly_price_usd is not None and self.hourly_price_usd <= 0:
            raise ValueError("hourly_price_usd must be > 0 when provided")
