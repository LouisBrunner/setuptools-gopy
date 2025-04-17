from __future__ import annotations

import glob
import logging
import os
import platform
import shlex
import shutil
import subprocess
import sys
from os.path import basename
from typing import List, Optional

from setuptools.errors import (
    CompileError,
)

from ._command import GopyCommand
from .extension import GopyExtension

logger = logging.getLogger(__name__)


class GopyError(Exception):
    pass


class build_gopy(GopyCommand):
    """Command for building Gopy crates via cargo."""

    description = "build Gopy extensions (compile/link to build directory)"

    final_dir: str = ""

    def __run_command(self, *args: str, cwd: Optional[str] = None) -> str:
        try:
            logger.info("$ running command: %s", " ".join(args))
            return subprocess.check_output(args, cwd=cwd).decode("utf-8").strip()
        except subprocess.CalledProcessError as error:
            raise GopyError(
                f"failed (exit: {error.returncode}) with: {error.output.decode('utf-8').strip()}"
            ) from error

    def __parse_makefile(self, path: str) -> List[str]:
        with open(path, "r") as file:
            content = file.read()
        lines = content.split("\n")
        prefixes = ["CFLAGS", "LDFLAGS"]
        flags = []
        for line in lines:
            for prefix in prefixes:
                if line.startswith(f"{prefix} = "):
                    _, leftover = line.split("=", 1)
                    flags.extend(shlex.split(leftover))
        return flags

    def run_for_extension(self, extension: GopyExtension) -> None:
        is_windows = platform.system() == "Windows"
        is_macos = platform.system() == "Darwin"

        logger.info("generating gopy code in %s", self.build_dir)
        extra_gen_args = []
        if extension.build_tags:
            extra_gen_args.append(f"-build-tags={extension.build_tags}")
        if extension.rename_to_pep:
            extra_gen_args.append("-rename=true")
        try:
            self.__run_command(
                "go",
                "tool",
                "gopy",
                "gen",
                f"-output={self.build_dir}",
                f"-vm={sys.executable}",
                *extra_gen_args,
                extension.target,
            )
        except GopyError as error:
            raise CompileError(
                f"gopy failed, make sure it is installed as a tool in your go.mod: {error}"
            ) from error

        logger.info("generating pybindgen C code in %s", self.build_dir)
        try:
            self.__run_command(
                sys.executable,
                "-m",
                "build",
                cwd=self.build_dir,
            )
        except GopyError as error:
            raise CompileError(f"build failed: {error}") from error

        go_files = glob.glob(os.path.join(self.build_dir, "*.go"))
        for file in go_files:
            filename_in_build = os.path.relpath(file, self.build_dir)
            logger.info("auto importing Go packages in %s", filename_in_build)
            try:
                self.__run_command(
                    "go",
                    "tool",
                    "goimports",
                    "-w",
                    file,
                )
            except GopyError as error:
                raise CompileError(
                    f"goimports failed for {filename_in_build}, make sure it is installed as a tool in your go.mod: {error}"
                ) from error

        name = self.distribution.get_name()
        lib_ext = "dll" if is_windows else "so"
        go_lib = os.path.join(self.build_dir, f"{name}_go.{lib_ext}")
        logger.info("building Go dynamic library in %s for %s", self.build_dir, name)
        try:
            self.__run_command(
                "go",
                "build",
                "-mod=mod",
                "-buildmode=c-shared",
                "-o",
                go_lib,
                *go_files,
            )
        except GopyError as error:
            raise CompileError(str(error)) from error

        logger.info("find Go's C compiler")
        try:
            gocc = self.__run_command(
                "go",
                "env",
                "CC",
            )
        except GopyError as error:
            raise CompileError(str(error)) from error

        c_files = glob.glob(os.path.join(self.build_dir, "*.c"))
        extra_gcc_args = []
        if is_macos:
            extra_gcc_args.append("-dynamiclib")
        c_lib = os.path.join(self.build_dir, f"_{name}.{lib_ext}")
        extracted_flags = self.__parse_makefile(
            os.path.join(self.build_dir, "Makefile")
        )
        logger.info("building C dynamic library in %s", self.build_dir)
        try:
            self.__run_command(
                gocc,
                *c_files,
                *extra_gcc_args,
                go_lib,
                "-o",
                c_lib,
                *extracted_flags,
                "-fPIC",
                "--shared",
                "-w",
            )
        except GopyError as error:
            raise CompileError(str(error)) from error

        py_files = glob.glob(os.path.join(self.build_dir, "*.py"))
        py_files = list(
            filter(lambda x: basename(x) not in ["build.py", "__init__.py"], py_files)
        )
        packages = list(filter(lambda x: x not in ["test"], self.distribution.packages))
        if not packages:
            raise ValueError("No packages found")
        source_dir = packages[0].replace(".", os.sep)
        install_dir = os.path.join(self.final_dir, packages[0].replace(".", os.sep))
        to_install = [c_lib, *py_files]
        if is_macos:
            to_install.append(go_lib)
        for file in to_install:
            filename = basename(file)
            logger.info("installing %s (src)", filename)
            shutil.copyfile(file, os.path.join(source_dir, filename))
            logger.info("installing %s (lib)", filename)
            os.replace(file, os.path.join(install_dir, filename))
