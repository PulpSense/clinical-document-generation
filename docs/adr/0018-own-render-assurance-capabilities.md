---
status: accepted
---

# Own the capabilities required for mandatory Render Assurance

Document construction is independent from Render Assurance, while client delivery still requires exact-artifact rendering and page-image review. Environment and tooling faults therefore exhaust a release-owned local fallback ladder instead of becoming failed quality findings; genuine document defects still trigger repair and reassessment. A release becomes active only after its renderer, page renderer, and compatible fonts pass an end-to-end smoke test, and activation retains the previous verified release atomically.

This supersedes ADR-0009's host-prerequisite preflight. We rejected reduced-assurance delivery because it weakens the mandatory Visual QA gate, and rejected host-only prerequisites because a missing font or renderer can prevent otherwise valid documents from being constructed. The consequence is a larger installation and a strict 30-minute ceiling: unresolved defects retain the complete candidate internally but never publish it as a client Branch Document Set.
