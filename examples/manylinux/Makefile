export SETUPTOOLS_GOPY_XCOMPILE_FORCE := y

test:
	python3 -m venv venv
	. venv/bin/activate && pip install ../.. build
	. venv/bin/activate && SETUPTOOLS_GOPY_PLAT_NAME=linux-aarch64 pip install --no-build-isolation -v --log install.log .
	. venv/bin/activate && SETUPTOOLS_GOPY_PLAT_NAME=linux-x86_64 python -m build --no-isolation --verbose
	docker run -it -v $(shell pwd):/proj --rm -w /proj quay.io/pypa/manylinux2014_x86_64 sh -c 'python3.13 -m pip install dist/simple-0.0.1-cp313-cp313-linux_x86_64.whl && python3.13 -m unittest discover'
	. venv/bin/activate && SETUPTOOLS_GOPY_PLAT_NAME=linux-x86_64,linux-aarch64 python -m build --no-isolation --verbose
	docker run -it -v $(shell pwd):/proj --rm -w /proj quay.io/pypa/manylinux2014_aarch64 sh -c 'python3.13 -m pip install dist/simple-0.0.1-cp313-cp313-linux_x86_64.linux_aarch64.whl && python3.13 -m unittest discover'
.PHONY: test
