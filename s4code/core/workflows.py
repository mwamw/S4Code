"""Reusable software-engineering task definitions."""


class ReviewWorkflow:
    def prompt(self, target=None):
        return (
            f"Review {target or 'the current uncommitted diff'} in this repository.\n"
            "Identify bugs, behavioral regressions, risky assumptions, and missing tests.\n"
            "Findings first, ordered by severity, with file paths and concrete reasoning.\n"
            "Use git diff and targeted code reads. Keep the summary short."
        )


class CommitWorkflow:
    def prompt(self):
        return (
            "Inspect the current git diff and propose one conventional commit message.\n"
            "Summarize the changes and risks. Do not execute git commit unless explicitly instructed."
        )
