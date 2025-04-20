import logging
import os
import platform
import shlex
import subprocess
from typing import Dict, List, Optional, Protocol, TypedDict, TypeVar

from setuptools.errors import CompileError

T = TypeVar("T")

logger = logging.getLogger("setuptools-gopy")

IS_WINDOWS = platform.system() == "Windows"


class GopyError(Exception):
    pass


def flatten(lst: List[List[T]]) -> List[T]:
    return [item for sublist in lst for item in sublist]


class GoCFlags(TypedDict):
    cflags: List[str]
    ldflags: List[str]


def parse_makefile(makefile_path: str) -> GoCFlags:
    with open(makefile_path, "r") as file:
        content = file.read()
    lines = content.split("\n")
    result: GoCFlags = {"cflags": [], "ldflags": []}
    for line in lines:
        for varname in result.keys():
            makevarname = varname.upper()
            if line.startswith(f"{makevarname} = "):
                _, leftover = line.split("=", 1)
                result[varname] = shlex.split(leftover)  # type: ignore[literal-required]
    return result


class CommandRunner(Protocol):
    def __call__(
        self,
        *args: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        compileerr: Optional[str] = None,
    ) -> str: ...


def run_command(
    *args: str,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    compileerr: Optional[str] = None,
) -> str:
    fenv = None
    if env is not None:
        fenv = {**os.environ, **env}
    logger.debug(
        f"$ running command {args} in {os.getcwd() if cwd is None else cwd}{'' if env is None else f' with env {env}'}",
    )
    try:
        try:
            return (
                subprocess.check_output(args, cwd=cwd, env=fenv).decode("utf-8").strip()
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            stdout = (
                error.stdout.decode("utf-8")
                if isinstance(error, subprocess.CalledProcessError)
                and error.stdout is not None
                else ""
            )
            stderr = (
                error.stderr.decode("utf-8")
                if isinstance(error, subprocess.CalledProcessError)
                and error.stderr is not None
                else ""
            )
            msg = f"exec error: {str(error)} (stdout: {stdout}, stderr: {stderr})"
            logger.debug(msg)
            raise GopyError(msg) from error
    except GopyError as error:
        if compileerr is None:
            raise
        raise CompileError(f"{compileerr}: {error}")
