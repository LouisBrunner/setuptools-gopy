from typing import Optional


class GopyExtension:
    """Used to define a gopy extension package and its build configuration.

    Args:
        name: The full name of the extension, including any packages – ie. not a filename or pathname, but Python dotted name.
        go_package: The fullname of the Go package to compile.
        build_tags: Go build tags to use.
        rename_to_pep: Whether to rename symbols to PEP snake_case.
        go_version: The version of Go to use, it will be download automatically if not found.
    """

    def __init__(
        self,
        name: str,
        go_package: str,
        *,
        build_tags: Optional[str] = None,
        rename_to_pep: Optional[bool] = None,
        go_version: Optional[str] = None,
    ):
        self.name = name
        self.go_package = go_package
        self.build_tags = build_tags
        self.rename_to_pep = rename_to_pep
        self.go_version = go_version

        folder, file = self.name.rsplit(".", 1)
        self._folder = folder.replace(".", "/")
        self._file_name = file

    def package_name(self) -> str:
        return self._file_name

    def output_folder(self) -> str:
        return self._folder
