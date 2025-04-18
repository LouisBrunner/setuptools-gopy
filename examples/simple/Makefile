test:
	virtualenv venv
	. venv/bin/activate && pip install ../.. && pip install --no-build-isolation -v --log install.log .
	. venv/bin/activate && python3 -m unittest discover
.PHONY: test
