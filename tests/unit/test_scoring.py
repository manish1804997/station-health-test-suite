"""Unit tests for the hygiene-score formula in app.scoring.

No DB, no HTTP, no FastAPI app here -- just the raw arithmetic. The point
is to pin down the two penalty caps and the flagging threshold precisely
enough that nobody can quietly change what "flagged" means during a future
refactor without a test breaking.
"""
import pytest
from app.scoring import (
    ERROR_PENALTY_CAP,
    FLAGGING_THRESHOLD,
    LATENCY_PENALTY_CAP,
    compute_hygiene_score,
    is_flagged,
)

pytestmark = pytest.mark.unit


class TestComputeHygieneScore:
    def test_perfect_station_scores_100(self):
        assert compute_hygiene_score("online", latency_ms=0, error_count=0) == 100.0

    def test_offline_applies_flat_40_point_penalty(self):
        assert compute_hygiene_score("online", 0, 0) - compute_hygiene_score(
            "offline", 0, 0
        ) == 40.0

    def test_errors_below_cap_cost_5_points_each(self):
        assert compute_hygiene_score("online", 0, error_count=3) == 100 - 3 * 5

    def test_error_penalty_is_capped(self):
        uncapped_equivalent = ERROR_PENALTY_CAP / 5  # errors at which cap kicks in
        just_under_cap = compute_hygiene_score("online", 0, int(uncapped_equivalent))
        way_over_cap = compute_hygiene_score("online", 0, error_count=1000)
        assert way_over_cap == just_under_cap == 100 - ERROR_PENALTY_CAP

    def test_latency_penalty_is_linear_below_cap(self):
        # 100ms / 20 = 5 point penalty
        assert compute_hygiene_score("online", latency_ms=100, error_count=0) == 95.0

    def test_latency_penalty_is_capped(self):
        just_under_cap = compute_hygiene_score("online", LATENCY_PENALTY_CAP * 20, 0)
        way_over_cap = compute_hygiene_score("online", latency_ms=50_000, error_count=0)
        assert way_over_cap == just_under_cap == 100 - LATENCY_PENALTY_CAP

    def test_penalties_stack_additively(self):
        # offline (-40) + 2 errors (-10) + 200ms latency (-10) = 40
        assert compute_hygiene_score("offline", latency_ms=200, error_count=2) == 40.0

    def test_score_is_rounded_to_two_decimal_places(self):
        # 121 / 20 comes out to exactly 6.05, so if round() were ever doing
        # something weird with floating-point drift, this is the case that
        # would catch it.
        assert compute_hygiene_score("online", latency_ms=121, error_count=0) == 93.95

    def test_worst_case_score_floors_at_10_not_0(self):
        # Stack every penalty at its cap -- offline (-40), errors capped
        # (-30), latency capped (-20) -- and you land on 10, not 0. That
        # means the `max(score, 0.0)` floor in compute_hygiene_score can't
        # actually be hit by any valid input today; it's dead code. This
        # test just makes that fact visible, so if someone loosens a cap
        # later and the floor becomes reachable, it gets noticed and earns
        # its own test instead of quietly doing nothing.
        worst = compute_hygiene_score("offline", latency_ms=999_999, error_count=999_999)
        assert worst == 10.0

    @pytest.mark.parametrize(
        "connectivity_status,latency_ms,error_count,expected",
        [
            ("online", 0, 0, 100.0),
            ("offline", 0, 0, 60.0),
            # 8 errors -> capped at -30; 40ms latency -> -2 (uncapped): 100-30-2=68
            ("online", 40, 8, 68.0),
        ],
        ids=["healthy", "offline-only", "error-cap-plus-latency"],
    )
    def test_spot_checks_against_hand_computed_values(
        self, connectivity_status, latency_ms, error_count, expected
    ):
        assert compute_hygiene_score(connectivity_status, latency_ms, error_count) == expected


class TestIsFlagged:
    def test_score_above_threshold_is_not_flagged(self):
        assert is_flagged(FLAGGING_THRESHOLD + 0.01) is False

    def test_score_at_threshold_is_not_flagged(self):
        # is_flagged uses strict `<`, so a station scoring exactly 60 counts
        # as healthy, not flagged. This is probably the single most
        # important boundary in the whole service, and nothing else in the
        # suite pins it down.
        assert is_flagged(FLAGGING_THRESHOLD) is False

    def test_score_just_below_threshold_is_flagged(self):
        assert is_flagged(FLAGGING_THRESHOLD - 0.01) is True

    def test_zero_score_is_flagged(self):
        assert is_flagged(0.0) is True
