from ai.models import AIJob, ReviewSummary, TaskEmbedding


def test_ai_job_model_exists():
    assert AIJob.__name__ == "AIJob"


def test_task_embedding_model_exists():
    assert TaskEmbedding.__name__ == "TaskEmbedding"


def test_review_summary_model_exists():
    assert ReviewSummary.__name__ == "ReviewSummary"
