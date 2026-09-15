# Elastic Compute Load Profiling & Capacity Planning

Компактный калькулятор, который переводит несколько бизнес-метрик в пиковую нагрузку, подходящие VM и месячный бюджет:

`MAU → DAU → peak RPS/RPC → vCPU/RAM → VM → USD/month`

Проект находится на стадии MVP. Числа в примерах демонстрационные и не являются рекомендацией для production.

## Основной сценарий

Измените `configs/project.yaml`, откройте `notebooks/01_capacity_planning.ipynb` и выполните **Run All**. Notebook покажет:

- DAU, пиковые RPS и RPC;
- требуемые vCPU и RAM;
- самый дешёвый подходящий вариант у каждого провайдера;
- число VM под заданный целевой SLA, цену в исходной валюте и USD для сравнения.

## Быстрый запуск

В репозитории уже создано окружение `.venv`. Для нового окружения:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
jupyter lab notebooks/01_capacity_planning.ipynb
```

Входные данные находятся в `configs/project.yaml`; Python-код notebook менять не нужно.

```yaml
project_metrics:
  mau: 1000
  dau_percent: 5
  business_events_per_user_day: 20
  rpc_per_event: 3
  availability_sla_percent: 99.9
```

Остальные параметры и двуязычные комментарии уже находятся в полном YAML-файле.

Тесты:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Каталог VM

`configs/providers.full.json` — рабочий snapshot на 2026-09-15. Он содержит 1 143 Linux on-demand EC2 VM из feed AWS для `eu-central-1`, полный опубликованный CPU-тариф Cloud.ru Evolution, все опубликованные non-GPU presets Nebius `eu-north1` и проверенные примеры Azure, GCP и Yandex Cloud. Обновление snapshot:

```bash
.venv/bin/python scripts/refresh_catalog.py
```

Важно: каталог пока не следует называть полным для Azure, GCP и Yandex Cloud. Yandex Cloud использует конфигурируемые сочетания vCPU/RAM, а не конечный список SKU. Полнота явно записана в `coverage` и `catalog_scope`, поэтому пример нельзя принять за глобальный optimum провайдера.

База сравнения цен: Linux on-demand/PAYG и 720 часов в месяц без диска, публичного IP, egress, поддержки и скидок. RUB хранится как первичная цена; USD — только сравнительная нормализация. Для shared/burst CPU отдельно учитывается гарантированная доля мощности.

## Важные ограничения

- MAU не определяет RPS без модели поведения и временного профиля.
- `cpu_ms_per_rpc` и память необходимо получить из короткого нагрузочного теста.
- `availability_sla_percent` управляет инженерной избыточностью, но не заменяет договорной SLA провайдера.
- Результат модели нужно калибровать нагрузочными тестами и production telemetry.
- Каталог цен и лимитов провайдера устаревает, поэтому snapshot должен иметь дату и источник.

## Структура

```text
configs/providers.full.json       VM и цены
configs/project.yaml              параметры проекта и SLA
notebooks/01_capacity_planning.ipynb
src/capacity_planner/io.py        загрузка каталога
src/capacity_planner/models.py    запись VM
src/capacity_planner/simple.py    расчёт нагрузки и подбор
scripts/refresh_catalog.py        обновление AWS
scripts/build_notebook.py         воспроизводимая сборка notebook
tests/test_simple.py
reqs.txt                          зависимости Python
```
