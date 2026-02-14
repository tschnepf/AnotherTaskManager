from core.models import Organization
from tasks.models import Task


def test_privacy_fields_exist_on_organization():
    field_names = {f.name for f in Organization._meta.get_fields()}
    assert "allow_cloud_ai" in field_names
    assert "redact_sensitive_patterns" in field_names


def test_cloud_field_exists_on_task():
    field_names = {f.name for f in Task._meta.get_fields()}
    assert "allow_cloud_processing" in field_names
