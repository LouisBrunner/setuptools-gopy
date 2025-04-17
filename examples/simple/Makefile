test:
	virtualenv venv
	. venv/bin/activate && pip install ../.. && pip install --no-build-isolation -v --log install.log .
	python3 -m unittest discover -s python
.PHONY: test
