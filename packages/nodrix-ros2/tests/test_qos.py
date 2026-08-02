from types import SimpleNamespace

import pytest

import nodrix_ros2.qos as qos


class Profile:
    def __init__(self, **values):
        self.__dict__.update(values)


def _fake_qos_module():
    return SimpleNamespace(
        ReliabilityPolicy=SimpleNamespace(
            RELIABLE="reliable", BEST_EFFORT="best_effort"
        ),
        DurabilityPolicy=SimpleNamespace(
            TRANSIENT_LOCAL="transient_local", VOLATILE="volatile"
        ),
        HistoryPolicy=SimpleNamespace(KEEP_ALL="keep_all", KEEP_LAST="keep_last"),
        QoSProfile=Profile,
        qos_profile_sensor_data=Profile(
            depth=5,
            reliability="best_effort",
            durability="volatile",
            history="keep_last",
        ),
    )


def test_sensor_qos_preset_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setattr(qos.importlib, "import_module", lambda _: _fake_qos_module())
    profile = qos.build_qos_profile(
        {"preset": "sensor_data", "reliability": "reliable", "depth": 8}
    )
    assert profile.depth == 8
    assert profile.reliability == "reliable"
    assert profile.history == "keep_last"


def test_qos_rejects_unknown_enums(monkeypatch) -> None:
    monkeypatch.setattr(qos.importlib, "import_module", lambda _: _fake_qos_module())
    with pytest.raises(ValueError, match="reliability"):
        qos.build_qos_profile({"reliability": "sometimes"})
