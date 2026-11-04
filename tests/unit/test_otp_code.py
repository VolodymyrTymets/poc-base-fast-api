"""The sign-in code generator, ported from the Node `otp-code-generator` spec. Task: 7.1."""

from app.services.otp import IssuedOtp, generate_code


def test_a_code_is_six_digits() -> None:
    code = generate_code()

    assert (len(code), code.isdecimal()) == (6, True)


def test_a_code_never_has_a_leading_zero_and_stays_in_range() -> None:
    codes = [int(generate_code()) for _ in range(500)]

    assert (min(codes) >= 100000, max(codes) <= 999999) == (True, True)


def test_codes_vary_between_calls() -> None:
    codes = {generate_code() for _ in range(50)}

    assert len(codes) > 1


def test_the_issued_code_is_not_in_the_repr() -> None:
    issued = IssuedOtp("account-id", "+380000000001", "482913")

    assert "482913" not in repr(issued)
