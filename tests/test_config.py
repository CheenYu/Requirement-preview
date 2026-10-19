from agents.requirement_pre_review.src.config import PROJECT_ROOT


def test_workflow_project_root_points_to_repository() -> None:
    assert (PROJECT_ROOT / "requirements.txt").is_file()
    assert (PROJECT_ROOT / ".env.example").is_file()
