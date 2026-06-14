from app import task_state


def reset_task_state():
    task_state.finish_task()


def test_task_state_allows_only_one_running_task():
    reset_task_state()
    try:
        assert task_state.try_start_task("first")
        assert not task_state.try_start_task("second")

        running = task_state.get_task_state()
        assert running["running"] is True
        assert running["task_name"] == "first"

        task_state.finish_task(summary={"done": True})
        finished = task_state.get_task_state()
        assert finished["running"] is False
        assert finished["last_summary"] == {"done": True}
        assert finished["last_error"] == ""

        assert task_state.try_start_task("second")
    finally:
        reset_task_state()


def test_task_state_records_error():
    reset_task_state()
    try:
        assert task_state.try_start_task("failed-task")
        task_state.finish_task(error="boom")
        state = task_state.get_task_state()
        assert state["running"] is False
        assert state["last_error"] == "boom"
    finally:
        reset_task_state()
