from app import task_state


def use_temp_task_db(monkeypatch, tmp_path):
    monkeypatch.setattr(task_state.settings, "discovery_db_path", tmp_path / "tasks.db")
    task_state._current_task_id = None


def reset_task_state():
    task_state.finish_task()


def test_task_state_allows_only_one_running_task(monkeypatch, tmp_path):
    use_temp_task_db(monkeypatch, tmp_path)
    reset_task_state()
    try:
        task = task_state.try_start_task("first")
        assert task is not None
        assert task["task_id"] > 0
        assert task_state.try_start_task("second") is None

        running = task_state.get_task_state()
        assert running["running"] is True
        assert running["task_id"] == task["task_id"]
        assert running["task_name"] == "first"

        task_state.finish_task(summary={"done": True})
        finished = task_state.get_task_state()
        assert finished["running"] is False
        assert finished["last_summary"] == {"done": True}
        assert finished["last_error"] == ""

        assert task_state.try_start_task("second") is not None
    finally:
        reset_task_state()


def test_task_state_records_error(monkeypatch, tmp_path):
    use_temp_task_db(monkeypatch, tmp_path)
    reset_task_state()
    try:
        assert task_state.try_start_task("failed-task") is not None
        task_state.finish_task(error="boom")
        state = task_state.get_task_state()
        assert state["running"] is False
        assert state["last_error"] == "boom"
    finally:
        reset_task_state()
