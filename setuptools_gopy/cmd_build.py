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
from typing import Dict, List, Optional, TypedDict, Union

from setuptools.errors import (
    CompileError,
)

from ._command import GopyCommand
from .extension import GopyExtension

logger = logging.getLogger(__name__)


class GopyError(Exception):
    pass


IS_WINDOWS = platform.system() == "Windows"
EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
SHLIB_SUFFIX = sysconfig.get_config_var("SHLIB_SUFFIX")
SOABI = sysconfig.get_config_var("SOABI")

type _GoEnv = Dict[str, str]


class _GoCFlags(TypedDict):
    cflags: List[str]
    ldflags: List[str]


class _BuildResult(TypedDict):
    files_to_copy: List[str]


class build_gopy(GopyCommand):
    """Command for building Gopy crates via cargo."""

    description = "build Gopy extensions (compile/link to build directory)"

    build_lib: Optional[str] = None
    build_temp: Optional[str] = None

    user_options = [
        ("build-lib=", "b", "directory for compiled extension modules"),
        ("build-temp=", "t", "directory for temporary files (build by-products)"),
    ]

    def initialize_options(self) -> None:
        super().initialize_options()
        if self.distribution.verbose:
            logger.setLevel(logging.DEBUG)

    def finalize_options(self) -> None:
        super().finalize_options()
        self.set_undefined_options(
            "build_ext",
            ("build_lib", "build_lib"),
            ("build_temp", "build_temp"),
        )

    @staticmethod
    def __run_command(
        *args: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> str:
        fenv = None
        if env is not None:
            fenv = {**os.environ, **env}
        logger.debug(
            f"$ running command {args}{'' if env is None else f' with env {env}'}"
        )
        try:
            return (
                subprocess.check_output(args, cwd=cwd, env=fenv).decode("utf-8").strip()
            )
        except subprocess.CalledProcessError as error:
            raise GopyError(f"command {args} failed: {str(error)}") from error

    @staticmethod
    def __parse_makefile(path: str) -> _GoCFlags:
        with open(path, "r") as file:
            content = file.read()
        lines = content.split("\n")
        result: _GoCFlags = {"cflags": [], "ldflags": []}
        for line in lines:
            for varname in result.keys():
                makevarname = varname.upper()
                if line.startswith(f"{makevarname} = "):
                    _, leftover = line.split("=", 1)
                    result[varname] = shlex.split(leftover)  # type: ignore[literal-required]
        return result

    def run_for_extension(self, extension: GopyExtension) -> None:
        if not self.build_temp:
            raise ValueError("build_temp is required")
        if not self.build_lib:
            raise ValueError("build_lib is required")

        stgp_base = os.path.join(self.build_temp, "setuptools-gopy")
        generated_dir = os.path.join(
            stgp_base, "gen", extension.go_package.replace("/", "-")
        )
        go_install_dir = os.path.join(stgp_base, "go")
        go_download_dir = os.path.join(stgp_base, "go-dl")
        install_dir = os.path.join(self.build_lib, extension.output_folder())

        logger.debug(
            f"building extension {extension.name} (generated_dir={generated_dir}, go_install_dir={go_install_dir}, go_download_dir={go_download_dir})"
        )

        goenv = self.__create_go_env(
            install_dir=go_install_dir,
            temp_dir=go_download_dir,
            wanted_version=extension.go_version,
        )

        res = self.__build(goenv=goenv, generated_dir=generated_dir, ext=extension)

        self.__install(
            files_to_copy=res["files_to_copy"],
            generated_dir=generated_dir,
            install_dir=install_dir,
        )

    def __create_go_env(
        self,
        *,
        install_dir: str,
        temp_dir: str,
        wanted_version: Optional[str] = None,
    ) -> _GoEnv:
        logger.info(
            f"checking we have a suitable version of Go (wanted={wanted_version})"
        )

        # try to get the system Go, if available
        current_version = None
        try:
            current_version = self.__run_command("go", "env", "GOVERSION")
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            logger.warning(f"could not find Go installation: {error}")

        logger.debug(
            f"found system Go version={current_version}, expected={wanted_version}"
        )

        # we have no requirements so whatever we found, that's it
        if wanted_version is None:
            if current_version is None:
                raise CompileError(
                    "Go was not found on this system and no go_version was provided, aborting"
                )
            # we have Go installed and no required version, carry on
            return {}

        # we have the required version, we can stop
        if f"go{wanted_version}" == current_version:
            return {}

        # out of luck, let's install it
        goenv = self.__install_go_env(
            install_dir=install_dir,
            temp_dir=temp_dir,
            wanted_version=wanted_version,
        )

        # final sanity check
        try:
            current_version = self.__run_command("go", "env", "GOVERSION", env=goenv)
        except subprocess.CalledProcessError as error:
            raise CompileError(f"could not find installed Go setup: {error}")

        if f"go{wanted_version}" != current_version:
            raise CompileError(
                f"Installed Go version {wanted_version} does not match the required version {current_version}"
            )

        return goenv

    def __install_go_env(
        self, *, install_dir: str, temp_dir: str, wanted_version: str
    ) -> _GoEnv:
        # let's check first if we already installed it
        goarch = platform.machine().lower()
        if goarch == "aarch64":
            goarch = "arm64"
        goos = platform.system().lower()
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
        return goenv

    def __build(
        self, *, goenv: _GoEnv, generated_dir: str, ext: GopyExtension
    ) -> _BuildResult:
        os.makedirs(generated_dir, exist_ok=True)

        name = ext.package_name()

        logger.info("generating gopy code for %s in %s", ext.go_package, generated_dir)
        extra_gen_args = []
        gotags = []
        if ext.build_tags:
            extra_gen_args.append(f"-build-tags={ext.build_tags}")
            gotags.extend(["-tags", ext.build_tags])
        if ext.rename_to_pep:
            extra_gen_args.append("-rename=true")
        try:
            self.__run_command(
                "go",
                "tool",
                "gopy",
                "gen",
                f"-name={name}",
                f"-output={generated_dir}",
                f"-vm={sys.executable}",
                *extra_gen_args,
                ext.go_package,
                env=goenv,
            )
        except GopyError as error:
            raise CompileError(
                f"gopy failed, make sure it is installed as a tool in your go.mod: {error}"
            ) from error

        logger.info("generating pybindgen C code in %s", generated_dir)
        try:
            self.__run_command(
                sys.executable,
                "-m",
                "build",
                cwd=generated_dir,
            )
        except GopyError as error:
            raise CompileError(f"pybindgen build failed: {error}") from error

        go_files = glob.glob(os.path.join(generated_dir, "*.go"))
        for file in go_files:
            filename = os.path.relpath(file, generated_dir)
            logger.info("auto importing Go packages in %s", filename)
            try:
                self.__run_command(
                    "go",
                    "tool",
                    "goimports",
                    "-w",
                    file,
                    env=goenv,
                )
            except GopyError as error:
                raise CompileError(
                    f"goimports failed for {filename}, make sure it is installed as a tool in your go.mod: {error}"
                ) from error

        prep_ext_name = f"{name}_go{SHLIB_SUFFIX}"
        out_prep_ext = os.path.join(generated_dir, prep_ext_name)
        logger.debug("generating intermediate CGo files in %s", generated_dir)
        try:
            self.__run_command(
                "go",
                "build",
                "-mod=mod",
                "-buildmode=c-shared",
                *gotags,
                "-o",
                out_prep_ext,
                *go_files,
                env=goenv,
            )
        except GopyError as error:
            raise CompileError(f"preparatory go build failed: {error}")
        os.remove(out_prep_ext)

        logger.info("building Go dynamic library for %s in %s", name, generated_dir)
        ext_name = f"_{name}{EXT_SUFFIX}"
        makeflags = self.__parse_makefile(os.path.join(generated_dir, "Makefile"))
        build_env = {
            **goenv,
            "CGO_CFLAGS": " ".join(
                [
                    os.environ.get("CGO_CFLAGS", ""),
                    "-fPIC",
                    "-Ofast",
                    *makeflags["cflags"],
                ],
            ),
            "CGO_LDFLAGS": " ".join(
                [os.environ.get("CGO_LDFLAGS", ""), *makeflags["ldflags"]]
            ),
        }
        try:
            self.__run_command(
                "go",
                "build",
                "-mod=mod",
                "-buildmode=c-shared",
                *gotags,
                "-o",
                ext_name,
                ".",
                cwd=generated_dir,
                env=build_env,
            )
        except GopyError as error:
            raise CompileError(f"go build failed: {error}")

        try:
            pkg_name = self.__run_command(
                "go",
                "list",
                "-f",
                "{{.Name}}",
                ext.go_package,
                env=goenv,
            ).strip()
        except GopyError as error:
            raise CompileError(
                f"go list failed for {ext.go_package}: {error}"
            ) from error

        # FIXME: for some reason gopy only rename half the files...
        orig_name = f"{pkg_name}.py"
        py_name = f"{name}.py"
        if orig_name != py_name:
            shutil.copyfile(
                os.path.join(generated_dir, orig_name),
                os.path.join(generated_dir, py_name),
            )

        return {
            "files_to_copy": [
                py_name,
                ext_name,
                "go.py",
            ]
        }

    def __install(
        self, *, generated_dir: str, install_dir: str, files_to_copy: List[str]
    ) -> None:
        os.makedirs(install_dir, exist_ok=True)
        logger.debug("installing in %s", install_dir)

        for file in files_to_copy:
            src_path = os.path.join(generated_dir, file)
            dst_path = os.path.join(install_dir, file)
            logger.info(
                "installing file %s, copy from %s to %s", file, src_path, dst_path
            )
            shutil.copyfile(src_path, dst_path)
