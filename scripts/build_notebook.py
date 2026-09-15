#!/usr/bin/env python3
"""Generate the deliberately small bilingual business notebook."""

from __future__ import annotations

from pathlib import Path

import nbformat as nbf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "01_capacity_planning.ipynb"


def md(text: str):
    return nbf.v4.new_markdown_cell(text.strip())


def code(text: str):
    return nbf.v4.new_code_cell(text.strip())


nb = nbf.v4.new_notebook()
nb["metadata"]["kernelspec"] = {
    "display_name": "Project .venv (Python 3.12)",
    "language": "python",
    "name": "python3",
}
nb["cells"] = [
    md("""
# Калькулятор нагрузки и VM / Load & VM calculator

**RU:** Измените `configs/project.yaml` и запустите **Run All**. Результат: пиковая нагрузка, необходимая мощность, подходящая VM у каждого провайдера и месячная стоимость.

**EN:** Edit `configs/project.yaml` and run **Run All**. The result shows peak load, required capacity, one suitable VM layout per provider, and monthly cost.
"""),
    code("""
from pathlib import Path
import importlib
import sys
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, Markdown

ROOT = Path.cwd().resolve()
if ROOT.name == "notebooks":
    ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "src"))

import capacity_planner.models as models_module
import capacity_planner.io as io_module
import capacity_planner.simple as planner

# A running Jupyter kernel caches imported Python modules. Reload project code so
# Run All always uses the current calculator schema after a git pull or edit.
importlib.reload(models_module)
planner = importlib.reload(planner)
io_module = importlib.reload(io_module)

catalog_file = ROOT / "configs" / "providers.full.json"
project_config_file = ROOT / "configs" / "project.yaml"
catalog = io_module.load_catalog(catalog_file)
metrics = io_module.load_project_metrics(project_config_file)
print(f"Loaded {len(catalog):,} VM records from {catalog_file.name}")
print(f"Loaded project parameters from {project_config_file.name}")
print(f"Python kernel: {sys.executable}")
if ".venv1" in sys.executable:
    display(Markdown(
        "⚠️ **Restart required / Нужен перезапуск:** select `Kernel → Change Kernel → "
        "Project .venv (Python 3.12)`, then run all cells."
    ))
"""),
    md("""
## 1. Входные данные / Inputs

**RU:** Параметры загружаются из `configs/project.yaml`. Изменяйте YAML, а не код notebook. `rpc_per_event` — сколько внутренних вызовов сервисов создаёт одно действие пользователя.

**EN:** Parameters are loaded from `configs/project.yaml`. Edit YAML, not notebook code. `rpc_per_event` is the number of internal service calls caused by one user action.
"""),
    code("""
input_values = pd.DataFrame(
    [{"Parameter / Параметр": key, "Value / Значение": value}
     for key, value in metrics.__dict__.items()]
)
display(input_values.style.hide(axis="index"))
"""),
    md("""
## 2. Результат для бизнеса / Business result

**RU:** Здесь только показатели, необходимые для решения о мощности и бюджете.

**EN:** Only the metrics needed for a capacity and budget decision are shown here.
"""),
    code("""
result = planner.build_business_summary(metrics, catalog)
load = result["load"]

kpis = pd.DataFrame([
    ["DAU", f'{load["dau"]:,.0f}', "Daily active users / Активных в день"],
    ["Peak RPS", f'{load["peak_event_rps"]:,.1f}', "Peak user actions/s / Пиковых действий/с"],
    ["Peak RPC", f'{load["peak_rpc"]:,.1f}', "Peak internal calls/s / Внутренних вызовов/с"],
    ["Required vCPU", f'{load["required_vcpu"]:,.2f}', "At target utilization / При целевой загрузке"],
    ["Required RAM", f'{load["required_ram_gib"]:,.2f} GiB', "Working set estimate / Оценка рабочей памяти"],
    ["Monthly RPC", f'{load["monthly_rpc"]:,.0f}', "Including growth / С учётом роста"],
    ["SLA downtime budget", f'{load["downtime_budget_minutes_month"]:,.2f} min/month', "Target, not provider guarantee / Цель, не гарантия"],
], columns=["Metric / Метрика", "Value / Значение", "Meaning / Смысл"])
display(kpis.style.hide(axis="index"))
"""),
    md("""
## 3. Что купить / What to buy

**RU:** Самый дешёвый подходящий вариант для каждого провайдера. Показаны две цены: без резерва и с топологией под заданный SLA. Для российских облаков исходная цена в рублях является основной; USD нужен только для сравнения. Сеть, диски, IP, лицензии и скидки считаются отдельно.

**EN:** Lowest-cost feasible option for each provider. Both prices are shown: without reserve and HA with a reserve VM. Network, disks, licences, and discounts are separate.
"""),
    code("""
# Recalculate here too, so running this cell never reuses a stale result.
result = planner.build_business_summary(metrics, catalog)
offers = pd.DataFrame(result["recommendations"])
required_columns = {
    "peak_cpu_utilization_percent", "peak_ram_utilization_percent",
    "limiting_factor", "catalog_choices",
}
missing_columns = required_columns.difference(offers.columns)
if missing_columns:
    raise RuntimeError(
        "Stale calculator module. Restart the kernel, select Project .venv "
        f"(Python 3.12), and Run All. Missing: {sorted(missing_columns)}"
    )
visible = offers[[
    "provider", "region", "vm", "working_instances", "reserve_instances",
    "total_vcpu", "total_effective_vcpu", "total_ram_gib",
    "peak_cpu_utilization_percent", "peak_ram_utilization_percent",
    "limiting_factor", "monthly_native_without_reserve", "monthly_native_ha",
    "price_currency", "monthly_usd_without_reserve", "monthly_usd",
    "catalog_scope", "catalog_choices"
]].copy()
visible["Native/month without reserve"] = visible.apply(
    lambda x: f'{x["monthly_native_without_reserve"]:,.2f} {x["price_currency"]}', axis=1
)
visible["Native/month SLA"] = visible.apply(
    lambda x: f'{x["monthly_native_ha"]:,.2f} {x["price_currency"]}', axis=1
)
visible = visible.drop(columns=[
    "monthly_native_without_reserve", "monthly_native_ha", "price_currency"
])
visible.columns = [
    "Provider / Провайдер", "Region / Регион", "VM", "Working VM", "Reserve VM",
    "Physical vCPU", "Effective vCPU", "RAM GiB total", "Peak CPU %", "Peak RAM %",
    "Why / Причина", "USD/month without reserve", "USD/month SLA",
    "Catalog scope", "VM checked", "Native/month without reserve", "Native/month SLA"
]
display(visible.style.format({
    "Peak CPU %": "{:,.2f}%", "Peak RAM %": "{:,.2f}%",
    "USD/month without reserve": "${:,.2f}", "USD/month SLA": "${:,.2f}"
}).hide(axis="index"))

if not visible.empty:
    ax = visible.sort_values("USD/month SLA").plot.barh(
        x="Provider / Провайдер",
        y=["USD/month without reserve", "USD/month SLA"],
        figsize=(8, 3.5), color=["#4C78A8", "#F58518"]
    )
    ax.set_title("Monthly VM cost / Месячная стоимость VM")
    ax.set_xlabel("USD/month")
    plt.tight_layout()
    plt.show()

limited = visible.loc[
    visible["Catalog scope"].isin(["partial", "documented_examples"]),
    "Provider / Провайдер"
].tolist()
if limited:
    display(Markdown(
        "⚠️ **Catalog limitation / Ограничение каталога:** catalog is not exhaustive for "
        + ", ".join(limited)
        + ". Their result is based on verified examples, not a provider-wide exhaustive optimum."
    ))
"""),
    md("""
## 4. Решение и ограничения / Decision and limits

**RU:** `availability_sla_percent` задаёт целевую топологию калькулятора: ниже 99.9% — 1 VM; 99.9% — 2 VM; 99.95% — 3 VM; 99.99% — 4 VM. Это инженерный запас, а не юридическая гарантия SLA. Выберите провайдера не только по минимальной цене: проверьте зоны доступности, договорной SLA и стоимость трафика/дисков. Значения `cpu_ms_per_rpc` и памяти должны быть заменены результатами короткого нагрузочного теста.

**EN:** `availability_sla_percent` maps to a planning topology: below 99.9% — 1 VM; 99.9% — 2 VMs; 99.95% — 3 VMs; 99.99% — 4 VMs. This is engineering redundancy, not a contractual SLA guarantee. Validate availability zones, contractual SLA, traffic, and disk cost. Replace CPU and memory assumptions with a short load test.

**RU:** Цена меняется ступенчато, а не вместе с каждым изменением MAU. Пока нагрузка помещается в ту же минимальную VM и действует `min_instances`, тип VM и месячная цена останутся прежними. `Why / Причина` показывает, ограничен ли выбор CPU, RAM или политикой доступности.

**EN:** VM pricing is stepwise. While the workload still fits the same smallest VM and `min_instances` applies, the VM and monthly price correctly remain unchanged. `Why / Причина` identifies whether CPU, RAM, or the availability floor drives the purchase.

<details><summary>Техническая проверка / Technical audit</summary>

The compact model uses: DAU = MAU × DAU%; peak RPS = daily events / active seconds × peak factor; peak RPC = peak RPS × RPC/event; required vCPU = peak RPC × CPU seconds / target utilization. These are audit equations, not additional business inputs.

</details>
"""),
    md("""
## 5. Охват каталога / Catalog coverage

**RU:** Эта таблица нужна только для контроля полноты каталога, а не для принятия решения.

**EN:** This table is only a catalog-completeness check, not part of the decision flow.
"""),
    code("""
coverage = (
    pd.DataFrame([{"provider": x.provider, "category": x.category, "vm": x.sku} for x in catalog])
    .groupby(["provider", "category"])["vm"].nunique().rename("VM count").reset_index()
)
display(coverage)
"""),
]
nbf.write(nb, OUTPUT)
print(f"Wrote {OUTPUT}")
