test:
	python3 -m venv venv
	. venv/bin/activate && pip install ../.. && pip install --no-build-isolation -v --log install.log .
	. venv/bin/activate && python3 -m unittest discover
.PHONY: test
