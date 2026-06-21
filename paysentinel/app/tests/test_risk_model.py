import pytest
from risk_model import score_transaction, ScoreResult, _velocity_store


@pytest.fixture(autouse=True)
def clear_velocity():
    _velocity_store.clear()
    yield
    _velocity_store.clear()


def test_normal_transaction():
    result = score_transaction("tx001", 50.0, "grocery", "US", 365)
    assert isinstance(result, ScoreResult)
    assert result.risk_score < 60
    assert result.flagged is False
    assert isinstance(result.reasons, list)


def test_flagged_high_risk_country():
    result = score_transaction("tx002", 50.0, "grocery", "NG", 365)
    assert result.risk_score == 30
    assert any("high-risk country" in r for r in result.reasons)


def test_flagged_high_risk_country_new_account():
    result = score_transaction("tx002b", 600.0, "grocery", "NG", 10)
    assert result.risk_score >= 60
    assert result.flagged is True


def test_flagged_new_account():
    result = score_transaction("tx003", 50.0, "grocery", "US", 5)
    assert any("new account" in r for r in result.reasons)


def test_flagged_excess_amount():
    result = score_transaction("tx004", 10000.0, "grocery", "US", 365)
    assert any("threshold" in r for r in result.reasons)


def test_combined_high_risk():
    result = score_transaction("tx005", 10000.0, "electronics", "RU", 10)
    assert result.flagged is True
    assert result.risk_score == 100 or result.risk_score >= 75


def test_zero_amount():
    result = score_transaction("tx006", 0.0, "grocery", "US", 365)
    assert any("non-positive" in r for r in result.reasons)


def test_negative_amount():
    result = score_transaction("tx007", -1.0, "grocery", "US", 365)
    assert any("non-positive" in r for r in result.reasons)


def test_unknown_merchant_category():
    result = score_transaction("tx008", 500.0, "unknown_cat", "US", 365)
    assert isinstance(result.risk_score, int)


def test_velocity_flagged():
    for i in range(7):
        score_transaction(f"tx_vel_{i}", 10.0, "grocery", "US", 365, account_id="acct_vel")
    result = score_transaction("tx_vel_final", 10.0, "grocery", "US", 365, account_id="acct_vel")
    assert any("velocity" in r for r in result.reasons)


def test_score_capped_at_100():
    result = score_transaction("tx009", 99999.0, "grocery", "NG", 1)
    assert result.risk_score <= 100


def test_relatively_new_account():
    result = score_transaction("tx010", 50.0, "grocery", "US", 60)
    assert any("relatively new" in r for r in result.reasons)
