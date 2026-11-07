# Обгортки для зручності. Те саме можна запускати напряму через python.
PYTHON ?= python3

.PHONY: setup setup-tlaps verify quick demo diagrams clean

setup:          ## завантажити TLC, Apalache, PlantUML у tools/
	$(PYTHON) scripts/setup_tools.py

setup-tlaps:    ## те саме + TLAPS (лише Linux x86_64)
	$(PYTHON) scripts/setup_tools.py --tlaps

verify:         ## усі перевірки (TLC + Apalache [+ TLAPS]) -> results/
	$(PYTHON) scripts/run_all.py

quick:          ## усе, крім довгої Full_4
	$(PYTHON) scripts/run_all.py --quick

demo:           ## три демо-запуски
	$(PYTHON) scripts/run_one.py Full
	$(PYTHON) scripts/run_one.py NoTMRecovery_Deadlock
	$(PYTHON) scripts/run_one.py Mutant

diagrams:       ## рендер усіх .puml у PNG/SVG
	$(PYTHON) scripts/render_diagrams.py

clean:          ## прибрати службові файли TLC/Python
	rm -rf spec/states spec/*_TTrace_* scripts/__pycache__
