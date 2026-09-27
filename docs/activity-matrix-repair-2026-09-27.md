# Activity-by-visit matrix repair after bilateral run __05

## Cause and reproduction

Run __05 used commit 6f25f38 and stopped before rendering after 637.462 seconds. All three Visits and Examinations responses failed the same coverage check for procedures.assessments and procedures.visit_schedule.

The fresh approved reference represented these fields, and visit_schedule_table, as activity-by-visit matrix rows. The previous approved reference used typed visit records. Generic scalar grounding treated the X membership marks as material words that must appear in clinical prose. Local replay reproduced the three failures; the same drafts passed the activity-label check without the markers.

The downstream schedule normalizer also skipped matrix rows because they did not contain visit/visitName/visitNumber fields. It returned zero visits. Ignoring X in drafting alone would therefore have left a table-construction defect.

## Repair

One read-only assessment_matrix decoder supplies clinical visits, procedure relationships and the complete activity inventory to drafting evidence projection, rendered Sterling checks, normalized visit records and table inventory construction.

Recognition requires named activities, rectangular binary cells, and recognizable clinical visit/timepoint columns or unambiguous authority from the explicit visit inventory. Binary metadata such as required:true, an empty header, or a cohort header without visit authority remains raw evidence. Unknown cell contents are not inferred into attendance or procedure assignment.

X/blank cells are preserved as active/blank table relationships, rather than narrative words. Source-supported visit inventory order can restore matrix column order after object-key sorting. Activity labels and clinical numbers remain evidence. Activities with no allocated visit remain notes; they do not receive an invented assignment. Matrix records already represented by table rows are not repeated as raw marker notes.

The independent content reviewer receives explicit instructions to compare matrix relationships with schedule tables and clinical prose. This adds no model call, response-format requirement, retry increase, deadline extension or dependency change. Source approval and bytes remain unchanged. Typed visit records retain their prior behavior.

## Verification

- All three real rejected Visits and Examinations responses pass replay.
- The source matrix yields five visits in the explicit inventory order and the exact approved activity-by-visit cells.
- Equivalent typed records and matrix inputs yield the same schedule rows.
- Unallocated activities, custom explicitly declared visits, sorted keys, source immutability and unknown cells are covered.
- Missing 66 cm and changed 5 mL quantities still fail clinical grounding.
- Review found and reproduced a metadata-as-visit recognition defect; header authority and negative regressions resolved it before commit. Standards and spec re-reviews cleared.
- 19 new matrix tests and the full focused selection passed: **303 tests**. Static Python compilation and diff whitespace checks passed.

No full suite or live study generation ran. A fresh Hermes run must still verify candidate assembly, rendering and independent review. This repair supports the approved matrix shape generally; it does not establish that all possible source layouts are supported or that every future generation will succeed.
