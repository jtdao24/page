import page_core


def test_package_imports() -> None:
    assert page_core.__name__ == "page_core"


def test_package_exposes_version() -> None:
    assert page_core.__version__ == "0.1.0"
