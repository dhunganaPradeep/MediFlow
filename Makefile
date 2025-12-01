.PHONY: up down logs seed test integration forecast backup lint fmt dbt

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

seed:
	python -m data_generation.generate --days 365 --hospitals 5 --load

test:
	pytest -m unit -q

integration:
	pytest -m integration -q

forecast:
	python -c "from forecasting.runner import retrain_all, predict_all; retrain_all(promote_if_better=False); predict_all()"

dbt:
	cd dbt/mediflow && dbt deps && dbt run && dbt test

backup:
	bash scripts/backup.sh

lint:
	ruff check . && black --check .

fmt:
	ruff check --fix . && black .
