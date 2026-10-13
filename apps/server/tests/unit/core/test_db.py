from motionile.core.db import NAMING_CONVENTION, Base


def test_metadata_uses_naming_convention() -> None:
    for key, template in NAMING_CONVENTION.items():
        assert Base.metadata.naming_convention[key] == template


def test_metadata_covers_every_constraint_kind() -> None:
    assert set(NAMING_CONVENTION) == {"ix", "uq", "ck", "fk", "pk"}
