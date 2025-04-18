import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from setuptools import Command

from .extension import GopyExtension

logger = logging.getLogger(__name__)


class GopyCommand(Command, ABC):
    """Abstract base class for commands which interact with Gopy Extensions."""

    def initialize_options(self) -> None:
        self.extensions: List[GopyExtension] = []

    def finalize_options(self) -> None:
        extensions: Optional[List[GopyExtension]] = getattr(
            self.distribution, "gopy_extensions", None
        )
        if extensions is None:
            # extensions is None if the setup.py file did not contain
            # gopy_extensions keyword; just no-op if this is the case.
            return

        if not isinstance(extensions, list):
            ty = type(extensions)
            raise ValueError(
                "expected list of GopyExtension objects for gopy_extensions "
                f"argument to setup(), got `{ty}`"
            )
        for i, extension in enumerate(extensions):
            if not isinstance(extension, GopyExtension):
                ty = type(extension)
                raise ValueError(
                    "expected GopyExtension object for gopy_extensions "
                    f"argument to setup(), got `{ty}` at position {i}"
                )
        # Extensions have been verified to be at the correct type
        self.extensions = extensions

    def run(self) -> None:
        if not self.extensions:
            logger.info("%s: no gopy_extensions defined", self.get_command_name())
            return

        if self.dry_run:
            return

        for ext in self.extensions:
            self.run_for_extension(ext)

    @abstractmethod
    def run_for_extension(self, extension: GopyExtension) -> None: ...
