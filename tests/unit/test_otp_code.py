"""The sign-in code generator, ported from the Node `otp-code-generator` spec. Task: 7.1."""

import pytest

from app.services.otp import IssuedOtp, generate_code


def test_a_code_is_six_digits() -> None:
    code = generate_code()

    assert (len(code), code.isdecimal()) == (6, True)


@pytest.mark.parametrize(
    ("draw", "expected"),
    [(0, "100000"), (900_000 - 1, "999999")],
    ids=["lowest", "highest"],
)
def test_the_code_range_is_100000_to_999999(
    monkeypatch: pytest.MonkeyPatch, draw: int, expected: str
) -> None:
    # The two ends of what `secrets.randbelow(900000)` can return: the range holds by construction, not by luck.
    monkeypatch.setattr("app.services.otp.secrets.randbelow", lambda _bound: draw)

    assert generate_code() == expected


def test_codes_vary_between_calls() -> None:
    codes = {generate_code() for _ in range(50)}

    assert len(codes) > 1


def test_the_issued_code_is_not_in_the_repr() -> None:
    issued = IssuedOtp("account-id", "482913")

    assert "482913" not in repr(issued)
