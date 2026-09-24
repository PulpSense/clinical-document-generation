# Brad review coverage

Source: `protocol (1).docx`, the 17 Sep 2026 generated Protocol annotated with 15 comments. This register tracks the exact comment IDs. A code or contract change is **implemented**; a comment is **verified** only after a new study-specific Protocol has been reviewed in Word or LibreOffice with the approved source. Brad's edited example is editorial reference, not study evidence for a new run.

| ID | Brad's comment | Governed behavior | Current evidence | New-run check |
| --- | --- | --- | --- | --- |
| 0 | Header needs short title | Approved `study.short_title` populates the running header; source intake flags a full title copied into that field or an absent short title for a long full title. | `rendering.py`, `contracts.py`, `test_brad_editorial_feedback.py` | Header on every page contains the approved short title, with no full title. |
| 1 | State | The Section 3 Variables synopsis uses a complete “Primary endpoint” label and points to the section that owns the endpoint inventory. | `rendering.py`, `test_brad_editorial_feedback.py` | Variables cell reads as a complete, accurate summary. |
| 2 | Just include the postoperative visit | When the final approved visit is explicitly postoperative, Section 3 Duration / Follow-up names that visit alone. Other studies retain their approved timeline. | `rendering.py`, `test_brad_editorial_feedback.py` | For Brad's study, the summary names the postoperative visit and omits enrollment, surgery, and analysis inventory. |
| 3–4 | Nonsense, introduction | Section 5 drafting asks for the supported clinical problem, evidence gap, and rationale in direct language. | `contracts.py`, `drafting.py` | Both introductory paragraphs convey approved facts without manufactured product claims or repeated title/hypothesis text. |
| 5 | Study purpose, not endpoint list | Section 6 owns purpose and objectives; Section 8.1 owns the endpoint inventory. | `contracts.py`, `test_brad_editorial_feedback.py` | Section 6 states the purpose concisely. |
| 6 | Repeated, bias | Section 8.2 asks for bias controls without restating design, masking, or control-arm absence. | `contracts.py`, `test_brad_editorial_feedback.py` | No duplicate design sentence. |
| 7 | Nonsense, measurements | Section 9.3 describes measurement method rather than restating the hypothesis. | `contracts.py`, `test_brad_editorial_feedback.py` | Each sentence gives an operational measurement fact. |
| 8 | Visit | Controlled boilerplate uses “unscheduled visit.” | `fixed-clinical-boilerplate.json`, `test_brad_editorial_feedback.py` | Section 9.4 says visit when describing an in-person visit. |
| 9 | Verbose, statistical methods | Section 10.2 groups endpoints sharing one method and avoids repeating full measure names and time points. | `contracts.py` | Methods are concise and cover each approved endpoint group. |
| 10 | Nonsense, general considerations | Section 10.3 requires a source-supported interpretation point rather than a self-reference. | `contracts.py`, `test_brad_editorial_feedback.py` | Section 10.3 adds a real methodological consideration or states only what source supports. |
| 11 | Inconsistent formatting | Section 15 matrix activity labels start with a capital letter and retain table styling. | `rendering.py`, `test_brad_editorial_feedback.py` | All activity rows use consistent typography and capitalization. |
| 12 | Nonsense, schedule restatement | Section 15 prose introduces its source-derived table briefly; the table and notes own the inventory. | `contracts.py`, `drafting.py`, `test_brad_editorial_feedback.py` | No prose repeats table rows beneath it. |
| 13 | Not detailed enough, confidentiality | Section 16 requests supplied operational details about data handling, access, retention, and disclosure. | `contracts.py`, `test_brad_editorial_feedback.py` | Every supplied privacy procedure appears; unsupported details remain absent. |
| 14 | Repeated, study completion | Section 18.5 states the approved completion trigger and closeout, without the full schedule. | `contracts.py`, `test_brad_editorial_feedback.py` | Completion is distinct from withdrawal and repeats no visit inventory. |

## Sterling ICF template obligations

The uploaded Sterling document is a template, not Brad's annotated ICF. Its historical resolved comments are editorial history. Two open template comments govern the current run: Sterling IRB's first-page merge fields remain for IRB completion, and the exact ClinicalTrials.gov statement appears when the approved registry-disclosure flag is true. The fixed authorization introduction, INFORMATION, voluntary-participation, QUESTIONS, and participant-statement sections are retained or populated deterministically under `sterling-clause-contract.json`; study-specific narrative sections are drafted from the approved source. `test_sterling_template_comments.py` checks the controlled first-page and registry behavior.

## Completion gate

After receiving the study input, generate Protocol and ICF from the same approved source. Inspect every comment target in the rendered Protocol, compare the ICF with the selected template, run exact-artifact content and page review, and record pass or a specific remaining defect for each row above. Prompt and unit-test coverage alone cannot mark Brad's prose comments verified.
