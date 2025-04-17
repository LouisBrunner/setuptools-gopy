from typing import Optional


class GopyExtension:
    """Used to define a gopy extension package and its build configuration.

    Args:
        target: The fullname of the Go package to compile.
        build_tags: Go build tags to use.
        rename_to_pep: Whether to rename symbols to PEP snake_case.
        go_version: The version of Go to use, it will be download automatically if not found.
    """

    def __init__(
        self,
        target: str,
        *,
        build_tags: Optional[str] = None,
        rename_to_pep: Optional[bool] = None,
        go_version: Optional[str] = None,
    ):
        self.target = target
        self.build_tags = build_tags
        self.rename_to_pep = rename_to_pep
        self.go_version = go_version
