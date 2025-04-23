import os
import platform
import tarfile
import urllib.request
import zipfile
from typing import Dict, Optional, Union

from setuptools.errors import CompileError

from .utils import IS_WINDOWS, GopyError, logger, run_command

type GoEnv = Dict[str, str]


def arch_to_go(arch: str) -> str:
    if arch == "aarch64":
        return "arm64"
    elif arch == "x86_64":
        return "amd64"
    elif arch == "i386":
        return "386"
    return arch


def arch_from_go(arch: str) -> str:
    if arch == "arm64":
        return "aarch64"
    elif arch == "amd64":
        return "x86_64"
    elif arch == "386":
        return "i386"
    return arch


_BASE_GO_ENV = {
    "CGO_ENABLED": "1",
}


class GoManager:
    @staticmethod
    def get_system_version() -> Optional[str]:
        current_version = None
        try:
            current_version = run_command("go", "env", "GOVERSION")
        except GopyError as error:
            logger.warning(f"could not find Go installation: {error}")

        logger.debug(f"found system Go version={current_version}")
        return current_version

    @classmethod
    def create_go_env(
        cls,
        *,
        install_dir: str,
        temp_dir: str,
        wanted_version: Optional[str] = None,
    ) -> GoEnv:
        baseenv = {**_BASE_GO_ENV}

        logger.info(
            f"checking we have a suitable version of Go (wanted={wanted_version})"
        )

        # try to get the system Go, if available
        current_version = cls.get_system_version()

        # we have no requirements so whatever we found, that's it
        if wanted_version is None:
            if current_version is None:
                raise CompileError(
                    "Go was not found on this system and no go_version was provided, aborting"
                )
            # we have Go installed and no required version, carry on
            logger.info(f"using installed Go {current_version}")
            return baseenv

        # we have the required version, we can stop
        if f"go{wanted_version}" == current_version:
            return baseenv

        # out of luck, let's install it
        goarch = arch_to_go(platform.machine().lower())
        goos = platform.system().lower()
        goenv = cls.install_go_env(
            goos=goos,
            goarch=goarch,
            install_dir=install_dir,
            temp_dir=temp_dir,
            wanted_version=wanted_version,
        )

        # final sanity check
        current_version = run_command(
            "go",
            "env",
            "GOVERSION",
            env=goenv,
            compileerr="could not find installed Go setup",
        )

        if f"go{wanted_version}" != current_version:
            raise CompileError(
                f"Installed Go version {wanted_version} does not match the required version {current_version}"
            )

        return {**baseenv, **goenv}

    @classmethod
    def install_go_env(
        cls,
        *,
        install_dir: str,
        temp_dir: str,
        wanted_version: str,
        goos: str,
        goarch: str,
    ) -> GoEnv:
        # let's check first if we already installed it
        gobase = os.path.abspath(os.path.join(install_dir, wanted_version))
        goroot = os.path.join(gobase, "go")
        gopath = os.path.join(gobase, "path")
        goenv = {
            **_BASE_GO_ENV,
            "GOBASE": gobase,
            "GOROOT": goroot,
            "GOPATH": gopath,
            "GOCACHE": os.path.join(gobase, "cache"),
            "GOMODCACHE": os.path.join(gopath, "pkg"),
            "PATH": os.pathsep.join(
                [os.path.join(goroot, "bin"), os.environ.get("PATH", "")]
            ),
        }
        logger.debug(
            f"checking if Go {wanted_version} is already installed at {goroot}"
        )
        if os.path.exists(goroot):
            logger.info(f"found Go {wanted_version} at {goroot}")
            return goenv

        # all failed, we need to install it
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(gobase, exist_ok=True)
        archive_ext = ".zip" if IS_WINDOWS else ".tar.gz"
        archive_name = f"go{wanted_version}.{goos}-{goarch}{archive_ext}"
        archive_url = f"https://go.dev/dl/{archive_name}"
        archive_path = os.path.join(temp_dir, archive_name)
        logger.debug(
            f"downloading {archive_name} from {archive_url} into {archive_path}"
        )

        urllib.request.urlretrieve(archive_url, archive_path)
        extractor: Union[zipfile.ZipFile, tarfile.TarFile]
        if IS_WINDOWS:
            extractor = zipfile.ZipFile(archive_path, "r")
        else:
            extractor = tarfile.open(archive_path, "r:gz")
        with extractor as ext:
            ext.extractall(gobase)
        os.remove(archive_path)

        logger.info(f"installed Go {wanted_version} at {goroot}")
        return goenv
