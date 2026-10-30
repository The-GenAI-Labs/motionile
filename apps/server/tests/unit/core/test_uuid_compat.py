from langchain_core.utils.uuid import uuid7

from motionile.core.ids import is_uuid7, new_id


def test_application_ids_and_langchain_ids_are_both_uuid_version_seven() -> None:
    assert is_uuid7(new_id())
    assert uuid7().version == 7


def test_application_ids_are_time_ordered() -> None:
    first = new_id()
    second = new_id()

    assert first < second
