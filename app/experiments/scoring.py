"""Direction and percentage-point tolerance are separate research scores."""
import math


def direction(change_pct):
    if not math.isfinite(change_pct):
        raise ValueError('Finite percentage required')
    return 'up' if change_pct > 0 else 'down' if change_pct < 0 else 'flat'


def score_forecast(actual_pct, predicted_direction, expected_return_pct=None):
    if predicted_direction not in {'up', 'down', 'flat'}:
        raise ValueError('Unknown direction')
    actual_direction = direction(actual_pct)
    # User-specified band: +3 -> [+1,+8], -3 -> [-8,-1].
    # For fractional moves below 1%, use the sign-preserving portion of +/-5pp.
    if actual_pct >= 1:
        lower, upper = max(1.0, actual_pct - 5), actual_pct + 5
    elif actual_pct <= -1:
        lower, upper = actual_pct - 5, min(-1.0, actual_pct + 5)
    else:
        lower, upper = actual_pct - 5, actual_pct + 5
    direction_correct = predicted_direction == actual_direction
    result = {'actual_direction': actual_direction, 'direction_correct': direction_correct,
              'tolerance_percentage_points': 5, 'accepted_range_pct': [lower, upper],
              'return_correct': None, 'absolute_error_pp': None,
              'return_status': 'missing_expected_return'}
    if expected_return_pct is not None:
        predicted_sign = direction(expected_return_pct)
        result.update(return_status='evaluated',
            absolute_error_pp=abs(expected_return_pct - actual_pct),
            return_correct=direction_correct and predicted_sign == actual_direction
                and lower - 1e-9 <= expected_return_pct <= upper + 1e-9)
    return result
