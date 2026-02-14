from collaboration.models import SavedView


def test_views_model_exists():
    assert SavedView.__name__ == "SavedView"
