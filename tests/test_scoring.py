import pytest
from app.experiments.scoring import score_forecast


@pytest.mark.parametrize('pred,correct', [(1, True), (3, True), (8, True), (8.01, False), (0.5, False), (-2, False)])
def test_positive_user_example(pred, correct):
    score = score_forecast(3, 'up', pred)
    assert score['direction_correct'] is True
    assert score['return_correct'] is correct
    assert score['accepted_range_pct'] == [1, 8]


def test_negative_and_missing():
    assert score_forecast(-3, 'down', -8)['return_correct']
    assert score_forecast(-3, 'down', -1)['return_correct']
    assert not score_forecast(-3, 'up', 1)['direction_correct']
    assert score_forecast(3, 'up')['return_correct'] is None
    assert score_forecast(0, 'flat', 0)['return_correct']
    assert not score_forecast(0, 'flat', 1)['return_correct']


def test_percentage_point_boundary_ignores_float_rounding():
    actual = 110 / 100 * 100 - 100
    assert score_forecast(actual, 'up', 5)['return_correct']
    assert not score_forecast(actual, 'up', 4.99)['return_correct']
