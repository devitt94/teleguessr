import pytest
from teleguessr.odds import probability_to_odds


from hypothesis import given, strategies as st


@given(probability=st.floats(min_value=0.075, max_value=0.925))
def test_probability_to_odds__margin_always_between_3_and_5_percent(probability):
    odds = probability_to_odds(probability)
    assert odds is not None
    margin = odds.implied_probability - probability
    assert 0.0325 <= margin <= 0.0575


def test_probability_to_odds__invalid_probability_raises_value_error():
    with pytest.raises(ValueError):
        probability_to_odds(-0.1)
    with pytest.raises(ValueError):
        probability_to_odds(1.1)


def test_very_high_probability_returns_none():
    assert probability_to_odds(0.9995) is None
    assert probability_to_odds(1.0) is None


def test_zero_probability_returns_none():
    assert probability_to_odds(0.0) is None
