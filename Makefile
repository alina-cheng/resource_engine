PY ?= uv run --frozen python
.PHONY: install test generate demo run docker schemas clean
install:            ## install runtime + dev dependencies
	uv sync --frozen
test:               ## run the test suite (stdlib unittest; pytest also works)
	$(PY) -m pytest -q
generate:           ## create sample ODRS/NDP data, websites, policies in data/generated
	$(PY) -m tools.sample_data_generator --odrs 150 --ndp 80 --seed 7
demo:               ## generate + seed + serve on http://127.0.0.1:8000
	$(PY) -m app.demo
run:                ## serve the existing local database
	$(PY) -m app.main
docker:             ## containerised demo
	docker compose up --build
schemas:            ## replace the vendored HSDS subset with the official v3.2.3 files (needs network)
	$(PY) scripts/fetch_hsds_schemas.py v3.2.3
clean:
	rm -rf var data/generated .pytest_cache
