def pytest_sessionfinish(session, exitstatus) -> None:
    from dryrun_lab.engine import _sweep_test_directories

    _sweep_test_directories()
