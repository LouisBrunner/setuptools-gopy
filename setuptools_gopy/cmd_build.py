from __future__ import annotations

import fileinput
import logging
import os
import platform
import shutil
import sys
import sysconfig
from typing import (
    Any,
    Dict,
    List,
    Optional,
    TypedDict,
    cast,
)

from setuptools.errors import (
    CompileError,
)

from ._command import GopyCommand
from .docker import DockerManager
from .extension import GopyExtension
from .flags import Flags
from .go import GoEnv, GoManager
from .utils import IS_WINDOWS, CommandRunner, logger, parse_makefile, run_command

APP_NAME = "setuptools-gopy"
EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
SHLIB_SUFFIX = sysconfig.get_config_var("SHLIB_SUFFIX")


class _GenerateResult(TypedDict):
    dir: str
    name: str
    go_files: List[str]
    gotags: List[str]


class _BuildResult(TypedDict):
    files_to_copy: List[str]


class build_gopy(GopyCommand):
    """Command for building Gopy crates via cargo."""

    description = "build Gopy extensions (compile/link to build directory)"

    build_lib: Optional[str] = None
    build_temp: Optional[str] = None
    plat_name: Optional[str] = None

    user_options = [
        ("build-lib=", "b", "directory for compiled extension modules"),
        ("build-temp=", "t", "directory for temporary files (build by-products)"),
        (
            "plat-name=",
            "p",
            "platforms to cross-compile (can be multiple separated by `,`)",
        ),
    ]

    go_manager: GoManager = GoManager()
    docker_manager: DockerManager = DockerManager()
    flags: Flags = Flags()

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
        self.set_undefined_options(
            "build",
            ("plat_name", "plat_name"),
        )

    def run_for_extension(self, extension: GopyExtension) -> None:
        if not self.build_temp:
            raise ValueError("build_temp is required")
        if not self.build_lib:
            raise ValueError("build_lib is required")

        defcache = os.path.expanduser("~/.cache")
        if IS_WINDOWS:
            defcache = os.getenv("LOCALAPPDATA", defcache)
        elif platform.system() == "Darwin":
            defcache = os.path.expanduser("~/Library/Caches")

        xdg_cache = os.getenv("XDG_CACHE_HOME", defcache)

        stgp_base = os.path.join(self.build_temp, APP_NAME)
        generated_dir = os.path.join(
            stgp_base, "gen", extension.go_package.replace("/", "-")
        )
        go_install_dir = os.path.join(xdg_cache, APP_NAME, "go")
        go_download_dir = os.path.join(stgp_base, "go-dl")
        install_dir = os.path.join(self.build_lib, extension.output_folder())
        cwd = os.getcwd()

        local_platform = sysconfig.get_platform()
        plat_name = self.plat_name
        override_plat_name = self.flags.override_plat_name()
        if override_plat_name:
            plat_name = override_plat_name
        platforms = plat_name.split(",") if plat_name else []
        local_plat_name = False
        if not platforms:
            local_plat_name = True
        if local_platform in platforms and not self.flags.force_cross_compile():
            local_plat_name = True
            platforms = list(filter(lambda x: x != local_platform, platforms))
        xcompile_platforms = platforms

        if local_plat_name:
            logger.debug(
                f"building extension {extension.name} locally (cwd={cwd}, generated_dir={generated_dir}, go_install_dir={go_install_dir}, go_download_dir={go_download_dir})"
            )

            goenv = self.go_manager.create_go_env(
                install_dir=go_install_dir,
                temp_dir=go_download_dir,
                wanted_version=extension.go_version,
            )

            res = self.__local_build(
                goenv=goenv, generated_dir=generated_dir, ext=extension
            )

        if xcompile_platforms:
            logger.debug(
                f"building extension {extension.name} for {xcompile_platforms} (cwd={cwd}, generated_dir={generated_dir})"
            )
            res = self.__docker_build(
                platforms=xcompile_platforms,
                generated_dir=generated_dir,
                ext=extension,
                go_install_dir=go_install_dir,
                go_download_dir=go_download_dir,
            )

        self.__install(
            files_to_copy=res["files_to_copy"],
            generated_dir=generated_dir,
            install_dir=install_dir,
        )

    def __build_generate(
        self,
        *,
        generated_dir: str,
        ext: GopyExtension,
        run: CommandRunner,
        python_path: str = sys.executable,
        real_gen_dir: Optional[str] = None,
    ) -> _GenerateResult:
        name = ext.package_name()

        real_gen_dir = real_gen_dir or generated_dir

        logger.info("generating gopy code for %s in %s", ext.go_package, generated_dir)
        extra_gen_args = []
        gotags = []
        if ext.build_tags:
            extra_gen_args.append(f"-build-tags={ext.build_tags}")
            gotags.extend(["-tags", ext.build_tags])
        if ext.rename_to_pep:
            extra_gen_args.append("-rename=true")
        run(
            "go",
            "tool",
            "gopy",
            "gen",
            f"-name={name}",
            f"-output={generated_dir}",
            f"-vm={python_path}",
            *extra_gen_args,
            ext.go_package,
            compileerr="gopy failed, make sure it is installed as a tool in your go.mod",
        )

        logger.info("generating pybindgen C code in %s", generated_dir)
        run(
            sys.executable,
            "-m",
            "build",
            cwd=real_gen_dir,
            compileerr="pybindgen build failed",
        )

        go_files = [os.path.join(generated_dir, f"{name}.go")]
        for file in go_files:
            filename = os.path.relpath(file, generated_dir)
            logger.info("auto importing Go packages in %s", filename)
            run(
                "go",
                "tool",
                "goimports",
                "-w",
                file,
                compileerr=f"goimports failed for {filename}, make sure it is installed as a tool in your go.mod",
            )
            for line in fileinput.FileInput(
                os.path.join(real_gen_dir, filename), inplace=True
            ):
                if line.startswith("#cgo LDFLAGS: "):
                    pieces = line.split(" ")
                    print(
                        " ".join(
                            [p for p in pieces if not p.startswith('"-lpython3.')]
                        ),
                        end="",
                    )
                else:
                    print(line, end="")

        return {
            "name": name,
            "gotags": gotags,
            "go_files": go_files,
            "dir": generated_dir,
        }

    def __build_compile(
        self,
        *,
        ext: GopyExtension,
        run: CommandRunner,
        gen: _GenerateResult,
        real_gen_dir: Optional[str] = None,
        lib_ext: str = SHLIB_SUFFIX,
        ext_ext: str = EXT_SUFFIX,
    ) -> _BuildResult:
        name = gen["name"]
        generated_dir = gen["dir"]
        gotags = gen["gotags"]
        go_files = gen["go_files"]
        real_gen_dir = real_gen_dir or generated_dir

        prep_ext_name = f"{name}_go{lib_ext}"
        logger.debug("generating intermediate CGo files in %s", generated_dir)
        run(
            "go",
            "build",
            "-mod=mod",
            "-buildmode=c-shared",
            *gotags,
            "-o",
            os.path.join(generated_dir, prep_ext_name),
            *go_files,
            compileerr="preparatory go build failed",
        )
        os.remove(os.path.join(real_gen_dir, prep_ext_name))

        logger.info("building Go dynamic library for %s in %s", name, generated_dir)
        ext_name = f"_{name}{ext_ext}"
        makeflags = parse_makefile(os.path.join(real_gen_dir, "Makefile"))
        build_env = {
            "CGO_CFLAGS": " ".join(
                [
                    os.environ.get("CGO_CFLAGS", ""),
                    "-fPIC",
                    "-Ofast",
                    *makeflags["cflags"],
                ],
            ),
            "CGO_LDFLAGS": " ".join(
                [
                    os.environ.get("CGO_LDFLAGS", ""),
                    *[
                        x
                        for x in makeflags["ldflags"]
                        if not x.startswith("-lpython3.")
                    ],
                ]
            ),
        }
        run(
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
            compileerr="go build failed",
        )

        pkg_name = run(
            "go",
            "list",
            "-f",
            "{{.Name}}",
            ext.go_package,
            compileerr=f"go list failed for {ext.go_package}",
        ).strip()

        # FIXME: for some reason gopy only rename half the files...
        orig_name = f"{pkg_name}.py"
        py_name = f"{name}.py"
        if orig_name != py_name:
            shutil.copyfile(
                os.path.join(real_gen_dir, orig_name),
                os.path.join(real_gen_dir, py_name),
            )

        return {
            "files_to_copy": [
                py_name,
                ext_name,
                "go.py",
            ]
        }

    def __local_build(
        self, *, goenv: GoEnv, generated_dir: str, ext: GopyExtension
    ) -> _BuildResult:
        os.makedirs(generated_dir, exist_ok=True)

        def local_runner(
            *args: str, env: Optional[Dict[str, str]] = None, **kwargs: Any
        ) -> str:
            fenv = goenv
            if env is not None:
                fenv = {**env, **goenv}
            return run_command(*args, env=fenv, **kwargs)

        generated = self.__build_generate(
            generated_dir=generated_dir,
            ext=ext,
            run=local_runner,
        )

        return self.__build_compile(gen=generated, ext=ext, run=local_runner)

    def __docker_build(
        self,
        platforms: List[str],
        generated_dir: str,
        ext: GopyExtension,
        go_install_dir: str,
        go_download_dir: str,
    ) -> _BuildResult:
        if ext.go_version is not None:
            go_version = ext.go_version
        else:
            system_version = self.go_manager.get_system_version()
            if system_version is None:
                raise CompileError(
                    "Go version not specified and none found, please provide one through the configuration"
                )
            go_version = system_version

        mounted_source_dir = "/src"
        mounted_generated_dir = os.path.join(
            mounted_source_dir, "build", "setuptools-gopy-docker"
        )
        mounts = [
            (os.getcwd(), mounted_source_dir, "rw"),
            (generated_dir, mounted_generated_dir, "rw"),
        ]

        all_files = []

        for plat in platforms:
            image = self.docker_manager.image_for_platform(plat)
            arch = self.docker_manager.get_arch_for_image(image)
            goenv, path, gomount = self.docker_manager.install_go_env(
                arch=arch,
                install_dir=go_install_dir,
                temp_dir=go_download_dir,
                version=go_version,
            )
            logger.info(f"compiling for {platform} (arch {arch} on {image})")

            with self.docker_manager.run_container(
                image=image,
                platform=arch,
                mounts=[*mounts, gomount],
                cwd=mounted_source_dir,
                env=goenv,
                appendpath=path,
            ) as container:
                docker_python = (
                    f"python{'.'.join([str(x) for x in sys.version_info[:2]])}"
                )

                def inject_runner(cmd: str, *args: str, **kwargs: Any) -> str:
                    if cmd == sys.executable:
                        return run_command(cmd, *args, **kwargs)
                    return container.run(cmd, *args, **kwargs)

                generated = self.__build_generate(
                    real_gen_dir=generated_dir,
                    generated_dir=mounted_generated_dir,
                    ext=ext,
                    run=cast(CommandRunner, inject_runner),
                    python_path=docker_python,
                )
                ext_suffix = container.run(
                    docker_python,
                    "-c",
                    "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))",
                )
                compiled = self.__build_compile(
                    real_gen_dir=generated_dir,
                    gen=generated,
                    ext=ext,
                    run=container.run,
                    lib_ext=".so",
                    ext_ext=ext_suffix.strip(),
                )
                all_files.extend(compiled["files_to_copy"])

        return {
            "files_to_copy": list(set(all_files)),
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
