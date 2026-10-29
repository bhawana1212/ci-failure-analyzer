import pytest

from ci_analyzer.analyzer import MAX_LOG_BYTES, analyze_log, redact


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("BUILD FAILURE", "build"),
        ("FAILED tests/test_boot.py::test_boot_sequence - AssertionError", "test"),
        ("main.c:12: error: expected ';'", "compilation"),
        ("Cancelling nested steps due to timeout", "timeout"),
        ("curl: Could not resolve host: example.invalid", "infrastructure"),
        ("No space left on device", "infrastructure"),
    ],
)
def test_failure_categories(message, category):
    result = analyze_log(f"{message}\nFinished: FAILURE")
    assert result.status == "failed"
    assert result.category == category
    assert result.evidence[0].line == 1


def test_extract_tests_and_stage():
    result = analyze_log(
        "[Pipeline] { (unit-tests)\n"
        "[Pipeline] {\n"
        "FAILED tests/test_boot.py::test_boot_sequence - AssertionError\n"
        "FAILED tests/test_boot.py::test_boot_sequence - AssertionError\n"
        "FAILED tests/test_driver.py::test_driver_initialization - AssertionError\n"
        "[Pipeline] }\n[Pipeline] }\nFinished: FAILURE"
    )
    assert result.failed_stage == "unit-tests"
    assert result.failed_tests == [
        "tests/test_boot.py::test_boot_sequence",
        "tests/test_driver.py::test_driver_initialization",
    ]


def test_success_overrides_recovered_errors():
    result = analyze_log("Connection refused\nRetry succeeded\nFinished: SUCCESS")
    assert result.status == "passed"
    assert result.category == "none"
    assert result.evidence == []


def test_last_terminal_status_wins():
    assert analyze_log("Finished: FAILURE\nFinished: SUCCESS").status == "passed"


def test_incomplete_log_is_not_passed():
    assert analyze_log("Starting job...\n10 tests collected").status == "unknown"


@pytest.mark.parametrize("status", ["ABORTED", "UNSTABLE"])
def test_preserves_non_success_status(status):
    assert analyze_log(f"Finished: {status}").status == status.lower()


def test_explicit_failure_without_signature():
    result = analyze_log("Finished: FAILURE")
    assert result.status == "failed"
    assert result.category == "unknown"


@pytest.mark.parametrize(
    ("log", "name"),
    [
        ("[  FAILED  ] Driver.Initialization", "Driver.Initialization"),
        ("FAIL: test_boot (tests.BootTest.test_boot)", "tests.BootTest.test_boot::test_boot"),
        ("[ERROR] org.example.BootTest.boot -- Time elapsed: 0.1 s <<< FAILURE!",
         "org.example.BootTest.boot"),
        ("\x1b[31mFAILED tests/test_a.py::test_a\x1b[0m", "tests/test_a.py::test_a"),
    ],
)
def test_test_runner_formats(log, name):
    result = analyze_log(log + "\nFinished: FAILURE")
    assert result.failed_tests == [name]
    assert result.category == "test"


def test_specific_cause_beats_build_wrapper():
    result = analyze_log("Connection refused\nBUILD FAILURE\nFinished: FAILURE")
    assert result.category == "infrastructure"


def test_redacts_common_credentials():
    result = redact("token=abc password:xyz Bearer abc.xyz https://user:pass@host ghp_abc123")
    for secret in ["abc", "xyz", "user:pass", "ghp_"]:
        assert secret not in result


@pytest.mark.parametrize("log", ["", " \n", "x" * (MAX_LOG_BYTES + 1)])
def test_rejects_empty_or_large_log(log):
    with pytest.raises(ValueError):
        analyze_log(log)