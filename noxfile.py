import nox
import nox.command


@nox.session()
def ruff(session: nox.Session):
    session.install("ruff")
    session.run("ruff", "format", "--diff", ".")
    session.run("ruff", "check", ".")


@nox.session()
def mypy(session: nox.Session):
    session.install("mypy", "types-setuptools", ".")
    session.run("mypy", "setuptools_gopy", *session.posargs)
