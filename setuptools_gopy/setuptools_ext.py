import logging
from typing import List, Literal, Type, cast

from setuptools.command.build_ext import build_ext
from setuptools.dist import Distribution
from tomllib import load as toml_load

from .cmd_build import build_gopy
from .extension import GopyExtension

logger = logging.getLogger(__name__)


def add_gopy_extension(dist: Distribution) -> None:
    build_ext_base_class = cast(
        Type[build_ext], dist.cmdclass.get("build_ext", build_ext)
    )

    class build_ext_gopy_extension(build_ext_base_class):  # type: ignore[misc,valid-type]
        def run(self) -> None:
            super().run()
            cmd = cast(build_gopy, self.get_finalized_command("build_gopy"))
            cmd.build_lib = self.build_lib
            cmd.build_temp = self.build_temp
            self.run_command("build_gopy")

    dist.cmdclass["build_ext"] = build_ext_gopy_extension


def gopy_extensions(
    dist: Distribution, attr: Literal["gopy_extensions"], value: List[GopyExtension]
) -> None:
    assert attr == "gopy_extensions"
    has_gopy_extensions = len(value) > 0

    # Monkey patch has_ext_modules to include Gopy extensions.
    orig_has_ext_modules = dist.has_ext_modules
    dist.has_ext_modules = lambda: (orig_has_ext_modules() or has_gopy_extensions)  # type: ignore[method-assign]

    if has_gopy_extensions:
        add_gopy_extension(dist)


def pyprojecttoml_config(dist: Distribution) -> None:
    try:
        with open("pyproject.toml", "rb") as f:
            cfg = toml_load(f).get("tool", {}).get("setuptools-gopy")
    except FileNotFoundError:
        return None

    if cfg:
        modules = list(
            map(lambda config: GopyExtension(**config), cfg.get("ext-packages", []))
        )
        dist.gopy_extensions = modules  # type: ignore[attr-defined]
        gopy_extensions(dist, "gopy_extensions", dist.gopy_extensions)  # type: ignore[attr-defined]
