import os
import shlex
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Dict, Generator, List, Optional, Tuple

from .go import GoEnv, GoManager
from .utils import CommandRunner, GopyError, flatten, logger, run_command

type DockerMount = Tuple[str, str, str]


class RunningContainer(ABC):
    @abstractmethod
    def run(
        self,
        *args: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        compileerr: Optional[str] = None,
    ) -> str: ...


class ScopedContainer(RunningContainer):
    def __init__(self, *, runner: CommandRunner, id: str, appendpath: Optional[str]):
        self.__run = runner
        self.__id = id
        self.__appendpath = appendpath

    def run(
        self,
        *args: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        compileerr: Optional[str] = None,
    ) -> str:
        logger.debug(
            f"# running docker command: {args}{'' if cwd is None else f' in {cwd}'}{'' if env is None else f' with env {env}'}"
        )
        fcwd = ["-w", cwd] if cwd else []
        fenv = [["-e", f"{k}={v}"] for k, v in env.items()] if env else []
        extra_path = f"PATH={self.__appendpath}:$PATH" if self.__appendpath else ""
        return self.__run(
            "docker",
            "exec",
            *fcwd,
            *flatten(fenv),
            self.__id,
            "bash",
            "-c",
            " ".join(
                [
                    extra_path,
                    shlex.join(args),
                ]
            ),
            compileerr=compileerr,
        )


class DockerManager:
    go_manager: GoManager = GoManager()

    @classmethod
    def install_go_env(
        cls, *, arch: str, temp_dir: str, install_dir: str, version: str
    ) -> Tuple[GoEnv, str, DockerMount]:
        goenv = cls.go_manager.install_go_env(
            goos="linux",
            goarch=arch,
            temp_dir=temp_dir,
            install_dir=os.path.join(install_dir, f"manylinux-{arch}"),
            wanted_version=version,
        )
        del goenv["PATH"]
        gobase = goenv["GOBASE"]
        mount = "/go"
        goenv = {k: v.replace(gobase, mount) for k, v in goenv.items()}
        return (
            {k: v for k, v in goenv.items() if k != "PATH"},
            f"{goenv['GOROOT']}/bin",
            (gobase, mount, "rw"),
        )

    @contextmanager
    def run_container(
        self,
        *,
        image: str,
        platform: str,
        cwd: Optional[str] = None,
        mounts: List[DockerMount] = [],
        env: Dict[str, str] = {},
        appendpath: Optional[str] = None,
    ) -> Generator[RunningContainer, None, None]:
        docker_envs = [["-e", f"{k}={v}"] for k, v in env.items()]
        docker_mounts = [
            ["-v", f"{os.path.abspath(src)}:{dst}:{tp}"] for src, dst, tp in mounts
        ]
        docker_cwd = []
        if cwd is not None:
            docker_cwd = ["-w", cwd]

        id = run_command(
            "docker",
            "create",
            "--rm",
            "--platform",
            f"linux/{platform}",
            *docker_cwd,
            *flatten(docker_envs),
            *flatten(docker_mounts),
            image,
            "sleep",
            "infinity",
            compileerr="could not run docker container, ensure docker is installed and running",
        )

        try:
            run_command(
                "docker",
                "start",
                id,
                compileerr="could not start docker container",
            )

            yield ScopedContainer(runner=run_command, id=id, appendpath=appendpath)
        finally:
            if os.getenv("SETUPTOOLS_GOPY_LEAVE_DOCKER", "") != "y":
                try:
                    run_command("docker", "stop", "-t", "5", id)
                except GopyError as e:
                    logger.error("could not stop docker container: %s", e)
