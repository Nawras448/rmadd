"""OpResult -> toast severity/message and result-pane markup (M2 Step 2).

Pure classification helpers so the reason matrix is unit-testable without a
running Textual app; `apply` is the only widget-facing entry point.
"""

from rmadd.package_managers.base import FailureReason, OpResult

SEVERITY_BY_REASON = {
    FailureReason.CANCELLED: "warning",
    FailureReason.AUTH_DENIED: "warning",
    FailureReason.AUTH_UNAVAILABLE: "warning",
    FailureReason.AUTH_TIMEOUT: "error",
    FailureReason.TIMEOUT: "error",
    FailureReason.MANAGER_MISSING: "error",
    FailureReason.UNSUPPORTED: "error",
    FailureReason.FAILED: "error",
}

TAIL_EXCERPT_CHARS = 160

_AUTH_PROMPT_MARKERS = ("[sudo] password", "password for", "password required")


def is_auth_prompt(line: str) -> bool:
    """Detect sudo/polkit password prompts streaming through output."""
    lowered = line.lower()
    return any(marker in lowered for marker in _AUTH_PROMPT_MARKERS)


def classify(
    action: str,
    name: str,
    mgr,
    result: OpResult | None,
    cancelled: bool,
) -> tuple[str, str]:
    """Map an outcome to ``(severity, message)``; severity "" == success."""
    label = action.title()
    if result is not None and result.ok:
        return "", ""
    if result is None:  # legacy bool-only callers
        if cancelled:
            return "warning", f"{label} cancelled ({name})"
        return "error", f"{label} failed ({name})"

    reason = result.reason
    if cancelled or reason is FailureReason.CANCELLED:
        return "warning", f"{label} cancelled ({name})"
    severity = SEVERITY_BY_REASON.get(reason, "error")
    describe = result.describe()

    if reason is FailureReason.MANAGER_MISSING:
        mgr_text = getattr(mgr, "value", str(mgr))
        return severity, f"{mgr_text} binary not found — {describe} ({name})"

    message = f"{label} failed: {describe} ({name})"
    if reason is FailureReason.FAILED and action == "remove":
        message += " — it may still be present"
    tail = (result.tail or "").strip()
    if reason is FailureReason.FAILED and tail:
        # Cap AFTER expansion: newline -> " | " grows the string, so the
        # toast context stays bounded regardless of line density.
        excerpt = tail[-TAIL_EXCERPT_CHARS:].replace("\n", " | ")[:TAIL_EXCERPT_CHARS]
        message += f" [{excerpt}]"
    return severity, message


def failure_line(action: str, name: str, result: OpResult | None) -> str:
    """Rich markup for the section result pane on failure."""
    describe = result.describe() if result is not None else "failed"
    return f"[bold red]✗ {action.title()} failed ({name}) — {describe}[/bold red]"


def apply(ui, action: str, name: str, mgr, result: OpResult | None, cancelled: bool):
    """Emit the matching toast; successes stay silent."""
    severity, message = classify(action, name, mgr, result, cancelled)
    if severity:
        ui.notify(message, severity=severity)
