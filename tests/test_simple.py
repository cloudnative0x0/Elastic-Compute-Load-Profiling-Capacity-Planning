import unittest
from pathlib import Path

from capacity_planner.io import load_catalog, load_project_metrics
from capacity_planner.models import HardwareSku
from capacity_planner.simple import ProjectMetrics, build_business_summary


class SimplePlannerTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog(cls.ROOT / "configs/providers.full.json")

    def test_snapshot_contains_requested_providers_and_full_aws_feed(self) -> None:
        providers = {sku.provider for sku in self.catalog}
        self.assertEqual(
            providers,
            {
                "AWS",
                "Microsoft Azure",
                "Google Cloud",
                "Nebius AI Cloud",
                "Yandex Cloud",
                "Cloud.ru",
            },
        )
        self.assertEqual(sum(sku.provider == "AWS" for sku in self.catalog), 1143)
        self.assertEqual(sum(sku.provider == "Cloud.ru" for sku in self.catalog), 52)
        self.assertEqual(sum(sku.provider == "Nebius AI Cloud" for sku in self.catalog), 17)

    def test_business_load_calculation(self) -> None:
        result = build_business_summary(
            ProjectMetrics(
                mau=1000,
                dau_percent=10,
                business_events_per_user_day=10,
                rpc_per_event=2,
                active_hours_day=10,
                peak_factor=3,
                cpu_ms_per_rpc=5,
                latency_ms=100,
                growth_percent=0,
            ),
            self.catalog,
        )
        self.assertAlmostEqual(result["load"]["peak_event_rps"], 1 / 12)
        self.assertAlmostEqual(result["load"]["peak_rpc"], 1 / 6)
        self.assertEqual(len(result["recommendations"]), 6)

    def test_project_metrics_load_from_yaml(self) -> None:
        metrics = load_project_metrics(self.ROOT / "configs/project.yaml")
        self.assertEqual(metrics.mau, 1_000)
        self.assertEqual(metrics.availability_sla_percent, 99.9)
        self.assertIsNone(metrics.min_instances)

    def test_default_recommendations_are_x86_and_have_n_plus_one(self) -> None:
        result = build_business_summary(ProjectMetrics(), self.catalog)
        aws = next(row for row in result["recommendations"] if row["provider"] == "AWS")
        selected = next(sku for sku in self.catalog if sku.provider == "AWS" and sku.sku == aws["vm"])
        self.assertEqual(selected.architecture, "x86_64")
        self.assertGreaterEqual(aws["reserve_instances"], 1)

    def test_optimizer_changes_vm_when_load_crosses_capacity_threshold(self) -> None:
        catalog = [
            HardwareSku("Test", "test-1", "small", 1, 2, 10 / 730, 10, "2026-01-01", "https://example.com"),
            HardwareSku("Test", "test-1", "large", 4, 8, 25 / 730, 25, "2026-01-01", "https://example.com"),
        ]
        low = ProjectMetrics(mau=1_000, dau_percent=5, min_instances=1, reserve_instances=0)
        high = ProjectMetrics(
            mau=10_000_000,
            dau_percent=50,
            business_events_per_user_day=100,
            rpc_per_event=5,
            active_hours_day=8,
            peak_factor=5,
            cpu_ms_per_rpc=10,
            min_instances=1,
            reserve_instances=0,
        )
        self.assertEqual(build_business_summary(low, catalog)["cheapest"]["vm"], "small")
        self.assertEqual(build_business_summary(high, catalog)["cheapest"]["vm"], "large")

    def test_base_ram_is_reserved_on_each_instance(self) -> None:
        catalog = [
            HardwareSku("Test", "test-1", "too-small", 2, 1, 1 / 730, 1, "2026-01-01", "https://example.com"),
            HardwareSku("Test", "test-1", "fits", 2, 2, 2 / 730, 2, "2026-01-01", "https://example.com"),
        ]
        result = build_business_summary(ProjectMetrics(base_ram_gib=1), catalog)
        self.assertEqual(result["cheapest"]["vm"], "fits")

    def test_yandex_native_price_uses_720_hours_and_sla_is_separate(self) -> None:
        metrics = ProjectMetrics(
            mau=1_000,
            dau_percent=5,
            business_events_per_user_day=20,
            rpc_per_event=3,
            active_hours_day=8,
            peak_factor=4,
            cpu_ms_per_rpc=5,
            latency_ms=100,
            memory_mib_per_inflight=1,
            base_ram_gib=1,
            target_cpu_percent=65,
            growth_percent=30,
            billing_hours_month=720,
            availability_sla_percent=99.9,
        )
        result = build_business_summary(metrics, self.catalog)
        yandex = next(
            row for row in result["recommendations"]
            if row["provider"] == "Yandex Cloud"
        )
        self.assertEqual(yandex["vm"], "standard-v3 / 2 vCPU 20% / 2 GiB")
        self.assertAlmostEqual(yandex["monthly_native_without_reserve"], 1224.0)
        self.assertAlmostEqual(yandex["monthly_native_ha"], 2448.0)
        self.assertEqual(yandex["working_instances"], 1)
        self.assertEqual(yandex["reserve_instances"], 1)

    def test_shared_cpu_is_not_counted_as_full_cpu(self) -> None:
        gcp = next(sku for sku in self.catalog if sku.sku == "e2-small")
        self.assertEqual(gcp.vcpu, 2)
        self.assertAlmostEqual(gcp.vcpu * gcp.cpu_capacity_factor, 0.5)
        aws = next(sku for sku in self.catalog if sku.provider == "AWS" and sku.sku == "t3a.small")
        self.assertEqual(aws.vcpu, 2)
        self.assertAlmostEqual(aws.vcpu * aws.cpu_capacity_factor, 0.4)

    def test_sla_target_changes_minimum_topology(self) -> None:
        low_result = build_business_summary(
            ProjectMetrics(mau=1, availability_sla_percent=99.0), self.catalog
        )
        high_result = build_business_summary(
            ProjectMetrics(mau=1, availability_sla_percent=99.99), self.catalog
        )
        low = low_result["cheapest"]
        high = high_result["cheapest"]
        self.assertEqual(low["instances"], 1)
        self.assertGreaterEqual(high["instances"], 4)
        self.assertAlmostEqual(high_result["load"]["downtime_budget_minutes_month"], 4.32)

    def test_catalog_has_consistent_720_hour_reference_prices(self) -> None:
        for sku in self.catalog:
            self.assertAlmostEqual(sku.monthly_price_usd, sku.hourly_price_usd * 720)
            self.assertGreater(sku.cpu_capacity_factor, 0)


if __name__ == "__main__":
    unittest.main()
