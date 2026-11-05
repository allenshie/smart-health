"""公開 API 範圍。"""
import smart_health_record


def test_public_api():
    assert sorted(smart_health_record.__all__) == sorted(
        ["HealthMonitor", "NodeRecorder", "StatusServer", "mask_text", "__version__"]
    )
    for name in smart_health_record.__all__:
        assert hasattr(smart_health_record, name)
