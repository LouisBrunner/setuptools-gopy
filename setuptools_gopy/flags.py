import os
from typing import Optional


class Flags:
    @classmethod
    def keep_docker_image(cls) -> bool:
        return os.getenv("SETUPTOOLS_GOPY_LEAVE_DOCKER", "") == "y"

    @classmethod
    def override_plat_name(cls) -> Optional[str]:
        return os.getenv("SETUPTOOLS_GOPY_PLAT_NAME", None)

    @classmethod
    def cross_compile_image(cls) -> Optional[str]:
        return os.getenv("SETUPTOOLS_GOPY_XCOMPILE_IMAGE", None)

    @classmethod
    def force_cross_compile(cls) -> bool:
        return os.getenv("SETUPTOOLS_GOPY_XCOMPILE_FORCE", "") == "y"
