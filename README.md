# Setuptools plugin for Gopy extensions

`setuptools-gopy` is a plugin for `setuptools` to build Go Python extensions using [`gopy`](https://github.com/go-python/gopy).

## Usage

You can configure `setuptools-gopy` either through `pyproject.toml` or `setup.py`:

```toml
[build-system]
requires = ["setuptools", "setuptools-gopy"]
build-backend = "setuptools.build_meta"

[project]
name = "simple"
version = "0.0.1"

[tool.setuptools.packages]
find = { where = ["python"] }

[[tool.setuptools-gopy.ext-packages]]
# the name of the package to create (e.g. this will create hello.py, _hello.DYLIB_SUFFIX and go.py in the simple package)
name = "simple.hello"
# name of the package to build (as would be accessible through the go cli)
go_package = "github.com/LouisBrunner/setuptools-gopy/examples/simple"
# optional: select which version of Go to install (otherwise expects the system to have it installed)
go_version = "1.24.1"
```

```python
from setuptools import find_packages, setup

from setuptools_gopy import GopyExtension

setup(
    name="simple",
    version="0.0.1",
    packages=find_packages(where="python"),
    package_dir={"": "python"},
    gopy_extensions=[
        GopyExtension(
            # same as above
            "simple.hello",
            "github.com/LouisBrunner/setuptools-gopy/examples/simple",
            go_version="1.24.1"
        )
    ],
)
```

In either case, you need to provide a `target`: this is the name of the Go package which should be built.

Once built, you can import Go symbols like so:

```python
from .hello import Hello
```

Note that the name of the file will match the Go `package` that you imported.

## Examples

 * [`examples/simple`](examples/simple) shows a simple example of calling a Go function from Python
 * Check [`gopy-ha-proton-drive`](https://github.com/LouisBrunner/gopy-ha-proton-drive) for a real-life example

## Acknowledgements

 * This repository is heavily inspired by [`setuptools-rust`](https://github.com/PyO3/setuptools-rust), thanks to them!
