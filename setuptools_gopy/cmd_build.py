from __future__ import annotations

import glob
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import urllib.request
import zipfile
from os.path import basename
from typing import Dict, List, Optional, Tuple, Union

from setuptools.errors import (
    CompileError,
)

from ._command import GopyCommand
from .extension import GopyExtension

logger = logging.getLogger(__name__)


class GopyError(Exception):
    pass


IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
SHLIB_SUFFIX = sysconfig.get_config_var("SHLIB_SUFFIX")


class build_gopy(GopyCommand):
    """Command for building Gopy crates via cargo."""

    description = "build Gopy extensions (compile/link to build directory)"

    final_dir: str = ""
    temp_dir: str = ""
    install_dir: str = ""
    source_dir: str = ""
    go_install_folder: str = os.path.join("build", "setuptools-gopy-go")

    def initialize_options(self) -> None:
        super().initialize_options()
        if self.distribution.verbose:
            logger.setLevel(logging.DEBUG)

    def finalize_options(self) -> None:
        super().finalize_options()
        packages = list(
            filter(lambda x: x not in ["tests"], self.distribution.packages)
        )
        if not packages:
            raise ValueError("No packages found")
        self.final_dir = os.path.abspath(self.final_dir)
        self.temp_dir = os.path.abspath(self.temp_dir)
        self.source_dir = os.path.abspath(packages[0].replace(".", os.sep))
        self.install_dir = os.path.join(
            self.final_dir, packages[0].replace(".", os.sep)
        )

    def __run_command(
        self,
        *args: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> str:
        fenv = None
        if env is not None:
            fenv = {**os.environ, **env}
        try:
            logger.info("$ running command: %s", " ".join(args))
            return (
                subprocess.check_output(args, cwd=cwd, env=fenv).decode("utf-8").strip()
            )
        except subprocess.CalledProcessError as error:
            raise GopyError(
                f"failed (exit: {error.returncode}) with: {error.output.decode('utf-8').strip()}"
            ) from error

    def __parse_makefile(self, path: str) -> Tuple[List[str], List[str]]:
        with open(path, "r") as file:
            content = file.read()
        lines = content.split("\n")
        prefixes = ["CFLAGS", "LDFLAGS"]
        result: List[List[str]] = [[], []]
        for line in lines:
            for i, prefix in enumerate(prefixes):
                if line.startswith(f"{prefix} = "):
                    _, leftover = line.split("=", 1)
                    result[i] = shlex.split(leftover)
        return (result[0], result[1])

    def __get_go_env(self, wanted_version: Optional[str] = None) -> Dict[str, str]:
        # 1. try to get the system Go, if available
        current_version = None
        try:
            current_version = self.__run_command("go", "env", "GOVERSION")
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            logger.warning(f"could not find system Go: {error}")

        logger.debug(
            f"found system Go version={current_version}, expected={wanted_version}"
        )

        # 2. we have no requirements so whatever we found, that's it
        if wanted_version is None:
            if current_version is None:
                raise CompileError(
                    "Go was not found on this system and no go_version was provided, aborting"
                )
            # we have Go installed and no required version, carry on
            return {}

        # 3. we have the required version, we can stop
        if f"go{wanted_version}" == current_version:
            return {}

        # 4. let's check first if we already installed it
        goarch = platform.machine().lower()
        goos = platform.system().lower()
        install_dir = f"{self.go_install_folder}.{goos}-{goarch}"
        gobase = os.path.abspath(os.path.join(install_dir, wanted_version))
        goroot = os.path.join(gobase, "go")
        gopath = os.path.join(gobase, "path")
        goenv = {
            "GOROOT": goroot,
            "GOPATH": gopath,
            "PATH": os.pathsep.join(
                [os.path.join(goroot, "bin"), os.environ.get("PATH", "")]
            ),
        }
        logger.debug(
            f"checking if Go {wanted_version} is already installed at {goroot}"
        )
        if os.path.exists(goroot):
            return goenv

        # 5. all failed, we need to install it
        os.makedirs(self.temp_dir, exist_ok=True)

        archive_ext = ".zip" if IS_WINDOWS else ".tar.gz"
        archive_name = f"go{wanted_version}.{goos}-{goarch}{archive_ext}"
        archive_url = f"https://go.dev/dl/{archive_name}"
        archive_path = os.path.join(self.temp_dir, archive_name)
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
        return goenv

    def run_for_extension(self, extension: GopyExtension) -> None:
        build_dir = os.path.join(self.build_dir, extension.target.replace("/", "-"))

        logger.debug(
            "starting execution in %s (build_dir=%s, final_dir=%s, temp_dir=%s, source_dir=%s, install_dir=%s)",
            os.getcwd(),
            build_dir,
            self.final_dir,
            self.temp_dir,
            self.source_dir,
            self.install_dir,
        )

        logger.info("checking we have a suitable version of Go")
        env = self.__get_go_env(extension.go_version)
        try:
            current_version = self.__run_command("go", "env", "GOVERSION", env=env)
            logger.info(f"using Go version {current_version}")
        except subprocess.CalledProcessError as error:
            raise CompileError(f"could not find system Go: {error}")

        logger.info("generating gopy code in %s", build_dir)
        extra_gen_args = []
        gotags = []
        if extension.build_tags:
            extra_gen_args.append(f"-build-tags={extension.build_tags}")
            gotags.extend(["-tags", extension.build_tags])
        if extension.rename_to_pep:
            extra_gen_args.append("-rename=true")
        try:
            self.__run_command(
                "go",
                "tool",
                "gopy",
                "gen",
                f"-output={build_dir}",
                f"-vm={sys.executable}",
                *extra_gen_args,
                extension.target,
                env=env,
            )
        except GopyError as error:
            raise CompileError(
                f"gopy failed, make sure it is installed as a tool in your go.mod: {error}"
            ) from error

        logger.info("generating pybindgen C code in %s", build_dir)
        try:
            self.__run_command(
                sys.executable,
                "-m",
                "build",
                cwd=build_dir,
            )
        except GopyError as error:
            raise CompileError(f"build failed: {error}") from error

        go_files = glob.glob(os.path.join(build_dir, "*.go"))
        for file in go_files:
            filename_in_build = os.path.relpath(file, build_dir)
            logger.info("auto importing Go packages in %s", filename_in_build)
            try:
                self.__run_command(
                    "go",
                    "tool",
                    "goimports",
                    "-w",
                    file,
                    env=env,
                )
            except GopyError as error:
                raise CompileError(
                    f"goimports failed for {filename_in_build}, make sure it is installed as a tool in your go.mod: {error}"
                ) from error

        name = self.distribution.get_name()
        pre_go_lib = f"{name}_go{SHLIB_SUFFIX}"
        go_lib = f"_{name}{EXT_SUFFIX}"
        cflags, ldflags = self.__parse_makefile(os.path.join(build_dir, "Makefile"))
        build_env = {
            **env,
            "CGO_CFLAGS": " ".join(
                [os.environ.get("CGO_CFLAGS", ""), "-fPIC", "-Ofast", *cflags]
            ),
            "CGO_LDFLAGS": " ".join([os.environ.get("CGO_LDFLAGS", ""), *ldflags]),
        }
        logger.info("building Go dynamic library in %s for %s", build_dir, name)
        try:  # this is needed to generate some intermediate files
            self.__run_command(
                "go",
                "build",
                "-mod=mod",
                "-buildmode=c-shared",
                *gotags,
                "-o",
                os.path.join(build_dir, pre_go_lib),
                *go_files,
                env=env,
            )
        except GopyError as error:
            raise CompileError(str(error)) from error
        try:
            self.__run_command(
                "go",
                "build",
                "-mod=mod",
                "-buildmode=c-shared",
                *gotags,
                "-o",
                go_lib,
                ".",
                cwd=build_dir,
                env=build_env,
            )
        except GopyError as error:
            raise CompileError(str(error)) from error
        go_lib = os.path.join(build_dir, go_lib)

        py_files = glob.glob(os.path.join(build_dir, "*.py"))
        py_files = list(
            filter(lambda x: basename(x) not in ["build.py", "__init__.py"], py_files)
        )
        for file in [go_lib, *py_files]:
            filename = basename(file)
            logger.info("installing %s (src)", filename)
            shutil.copyfile(file, os.path.join(self.source_dir, filename))
            logger.info("installing %s (lib)", filename)
            os.replace(file, os.path.join(self.install_dir, filename))
