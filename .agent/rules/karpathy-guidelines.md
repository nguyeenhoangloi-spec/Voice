---
trigger: always_on
---

# ANDREJ KARPATHY GUIDELINES v1.0

This rule enforces the core principles from the **andrej-karpathy-skills** methodology to prevent common LLM coding pitfalls, ensuring high-quality, maintainable, and robust development.

---

## 🧠 1. THINK BEFORE CODING (No Silent Assumptions)
*   **Identify Assumptions:** Never make silent assumptions about requirements, APIs, database schemas, or business logic.
*   **Clarification First:** If a request is ambiguous, incomplete, or technically risky, **STOP** and ask 3-5 specific clarifying questions before writing any code.
*   **State Intent:** Always explain the planned technical approach and constraints briefly in your response before performing actions.

---

## 🛡️ 2. KEEP IT SIMPLE (Anti Over-Engineering)
*   **Minimalist Code:** Write the absolute minimum amount of code necessary to fully solve the problem.
*   **No Speculative Abstractions:** Do NOT create generic architectures, future-proof frameworks, classes, or patterns that are not explicitly requested.
*   **Readability First:** Keep functions small, focused, and direct. Favor readability and simplicity over cleverness.

---

## 🎯 3. MAKE SURGICAL CHANGES (No Scope Creep)
*   **Isolated Changes:** Limit code modifications strictly to the files and regions directly related to the user request.
*   **No Unrelated Refactoring:** Never modify, "clean up," or refactor working code in unrelated sections or files without explicit instructions.
*   **Preserve Context:** Preserve all existing docstrings, logic, comments, and imports unless they are explicitly being replaced.

---

## 🧪 4. DEFINE AND VERIFY SUCCESS (Mandatory Verification)
*   **Concrete Goals:** Break down the request into clear, checkable checklist items (in `task.md`).
*   **Write Tests First (TDD):** Whenever implementing new backend functionality or fixing bugs, write unit/integration tests to verify behavior.
*   **Run Commands to Verify:** Always run python scripts, compile code, run tests, or lint the files before claiming a task is complete.
*   **Evidence-Based Success:** Proactively check logs, exit codes, and output, and include the exact verification results in the final walkthrough report.
