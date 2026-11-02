import re

import pytest
from utils.db import create_database, drop_database, new_database_name

# Nothing listens here: a refused name must raise before any connection is tried.
UNREACHABLE = "postgresql+asyncpg://u:p@127.0.0.1:1/postgres"

NOT_OURS = [
    "postgres",
    "template1",
    "poc_migrations_1a2b3c4d",
    "poc_test_x; DROP TABLE y",
    'poc_test_x"',
    "POC_TEST_upper",
    "poc_test_",
]


@pytest.mark.parametrize("name", NOT_OURS)
def test_drop_database_refuses_a_name_the_suite_did_not_generate(name: str) -> None:
    with pytest.raises(ValueError, match="not a database of this test suite"):
        drop_database(UNREACHABLE, name)


@pytest.mark.parametrize("name", NOT_OURS)
def test_create_database_refuses_such_a_name_as_target_or_template(name: str) -> None:
    with pytest.raises(ValueError, match="not a database of this test suite"):
        create_database(UNREACHABLE, name)
    with pytest.raises(ValueError, match="not a database of this test suite"):
        create_database(UNREACHABLE, "poc_test_module_ab12cd34", template=name)


def test_a_generated_name_is_one_the_suite_may_drop() -> None:
    name = new_database_name("module")

    assert re.fullmatch(r"poc_test_module_[0-9a-f]{8}", name)
