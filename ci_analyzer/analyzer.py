import re
from dataclasses import dataclass

MAX_LOG_BYTES = 2 * 1024 * 1024
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
FINISHED = re.compile(r"^\s*Finished:\s*(SUCCESS|FAILURE|UNSTABLE|ABORTED)\s*$", re.I)
STAGE = re.compile(r"\[Pipeline\]\s*\{\s*\(([^)]+)\)")
RULES = {
    "timeout": re.compile(
        r"\btimed?\s*out\b|\btimeout(?:error|exception)\b|"
        r"cancelling nested steps due to timeout|execution exceeded", re.I
    ),
    "infrastructure": re.compile(
        r"connection (?:refused|reset)|could not resolve host|temporary failure in name resolution|"
        r"no space left on device|cannot connect to the docker daemon|"
        r"agent .* (?:offline|disconnected)|network is unreachable|"
        r"(?:imagepullbackoff|errimagepull)|unable to connect to", re.I
    ),
    "compilation": re.compile(
        r"\bfatal error:|\berror:\s|\bsyntaxerror:|\bcompilation (?:error|failed)|"
        r"\berror (?:CS|TS)\d+|undefined reference to|cannot find symbol", re.I
    ),
    "test": re.compile(
        r"^\s*(?:FAILED|ERROR)\s+\S+::|\bAssertionError\b|"
        r"\[\s*FAILED\s*\]\s+\w+\.|^\s*(?:FAIL|ERROR):\s+test|"
        r"\b[1-9]\d*\s+(?:failed|failures)\b|Failures:\s*[1-9]|Errors:\s*[1-9]|"
        r"<<<\s*(?:FAILURE|ERROR)!|there (?:are|were) test failures", re.I
    ),
    "build": re.compile(
        r"\bBUILD (?:FAILURE|FAILED)\b|script returned exit code [1-9]|"
        r"process (?:completed|exited) with (?:exit )?code [1-9]|"
        r"make(?:\[\d+\])?: \*\*\*|npm ERR!", re.I
    ),
}
TEST_PATTERNS = [
    re.compile(r"^\s*(?:FAILED|ERROR)\s+(\S+::\S+)"),
    re.compile(r"^\s*\[\s*FAILED\s*\]\s+([\w./-]+\.[\w./-]+)"),
    re.compile(r"^\s*(?:FAIL|ERROR):\s+(\S+)\s+\(([^)]+)\)"),
    re.compile(r"^\s*(?:\[ERROR\]\s*)?([\w.$]+)\s*(?:--|Time elapsed:).*<<<\s*(?:FAILURE|ERROR)!"),
]
CAUSES = {
    "timeout": "An operation exceeded its time limit. Check duration, deadlocks and dependencies.",
    "infrastructure": "An agent, network or resource error was detected. Check the CI environment.",
    "compilation": "A compiler or syntax error was detected. Inspect the first diagnostic.",
    "test": "A test failure was detected. Inspect its assertion or setup error.",
    "build": "A build command returned a failure. Inspect its output before the exit message.",
    "unknown": "No specific failure signature matched. The log may be incomplete or unsupported.",
    "none": "The log reports a successful build.",
}


@dataclass
class Evidence:
    line: int
    text: str
    category: str
    stage: str | None


@dataclass
class Analysis:
    status: str
    category: str
    failed_stage: str | None
    failed_tests: list[str]
    evidence: list[Evidence]
    summary: str
    line_count: int


def redact(text: str) -> str:
    text = re.sub(
        r"(?i)\b(password|passwd|token|api[_-]?key|secret)\s*([=:])\s*[^\s,;]+",
        r"\1\2[REDACTED]", text,
    )
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[REDACTED]@", text)
    return re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b", "[REDACTED]", text)


def analyze_log(log: str) -> Analysis:
    if not log.strip():
        raise ValueError("The log must not be empty.")
    if len(log.encode("utf-8")) > MAX_LOG_BYTES:
        raise ValueError("Logs must be at most 2 MiB.")

    lines = ANSI.sub("", redact(log)).splitlines()
    stages: list[str | None] = []
    tests: dict[str, None] = {}
    matches: dict[str, list[Evidence]] = {category: [] for category in RULES}
    final_status = None
    for number, line in enumerate(lines, start=1):
        stage_match = STAGE.search(line)
        if stage_match:
            stages.append(stage_match.group(1)[:200])
        elif re.search(r"\[Pipeline\]\s*\{", line):
            stages.append(None)
        elif re.search(r"\[Pipeline\]\s*\}", line):
            if stages:
                stages.pop()
        stage = next((name for name in reversed(stages) if name), None)
        finished = FINISHED.match(line)
        if finished:
            final_status = finished.group(1).upper()
        for pattern in TEST_PATTERNS:
            test_match = pattern.search(line)
            if test_match and len(tests) < 500:
                name = "::".join(reversed(test_match.groups()))
                tests[name[:500]] = None
                break
        for category, pattern in RULES.items():
            if pattern.search(line) and len(matches[category]) < 8:
                matches[category].append(Evidence(number, line[:600], category, stage))

    if final_status == "SUCCESS":
        return Analysis("passed", "none", None, [], [], CAUSES["none"], len(lines))
    category = next((name for name, evidence in matches.items() if evidence), "unknown")
    if tests and category in {"unknown", "build"}:
        category = "test"
    if final_status == "ABORTED":
        status = "aborted"
    elif final_status == "UNSTABLE":
        status = "unstable"
    elif final_status == "FAILURE" or category != "unknown":
        status = "failed"
    else:
        status = "unknown"
    evidence = sorted(
        [item for items in matches.values() for item in items], key=lambda item: item.line
    )
    primary = matches.get(category, [])
    failed_stage = primary[0].stage if primary else None
    return Analysis(
        status, category, failed_stage, list(tests), evidence, CAUSES[category], len(lines)
    )