# Study Reference Schema

Use `reference/study.reference.json` as the internal machine-readable cache for generation. Before reviewer approval it is drafted from raw context. After the reviewer uploads or approves the generated source Markdown recorded in `approval.review_file`, regenerate or confirm this JSON from that Markdown file and treat the Markdown as authoritative.

## Required Top-Level Shape

```json
{
  "meta": {},
  "source": {},
  "template_fields": {},
  "approval": {},
  "study": {},
  "parties": {},
  "sites": [],
  "population": {},
  "design": {},
  "objectives": {},
  "endpoints": {},
  "procedures": {},
  "statistics": {},
  "risks_benefits": {},
  "generated": {},
  "regulatory": {},
  "needs_review": []
}
```

## Field Guidance

- `meta`: run metadata and identifiers, such as `protocol_number`, `version`, `date`, `study_type`, `document_set`, and `icf_template`. `study_type` must normalize to `Prospective`, `Ambispective`, or `Retrospective`. For prospective and ambispective runs, `icf_template` must be `Advarra` or `Sterling` before source-of-truth generation; retrospective runs leave it unset.
- `source`: intake channel, preserved context summary, source Markdown metadata, and draft extraction provenance, such as `channel`, `raw_files`, `transcript_files`, `notes`, `field_candidates`, `source_of_truth_file`, `source_of_truth_md`, `source_of_truth_status`, and source Markdown timestamps. Use `field_candidates` as described in the branch input contract so conflicting starred inputs can be detected deterministically.
- `template_fields`: compatibility values for client templates that use legacy flat placeholders, especially n8n-style protocol fields such as `AI_shortTitle` and `protocolNumber`.
- `approval`: review workflow state, such as `status`, `review_file`, `approved_by`, `approved_at`, and `notes`. Use `pending_review`, `changes_requested`, or `approved`.
- `study`: core study facts, such as `title`, `short_title`, `condition`, `background`, `unmet_need`, `hypothesis`, and `timeline`.
- `parties`: sponsor, funding source, principal investigator, sub-investigators, study coordinator, IRB/ethics committee, and other responsible parties.
- `sites`: array of site objects with facility, address, contact, backup contact, and investigator details.
- `population`: sample size, sample justification, inclusion criteria, exclusion criteria, ages, sex/gender, and study population wording.
- `design`: study design, number of sites, arms/groups, intervention/test articles, control articles, masking/blinding, bias minimization, and data sources.
- `objectives`: primary, secondary, and exploratory objectives.
- `endpoints`: primary, secondary, exploratory, and safety endpoints. Keep endpoint text and timing separate when possible.
- `procedures`: visit schedule, assessments, data collection, case selection, privacy protocol, and study procedure text.
- `statistics`: analysis plan, analysis data sets, methodology, considerations, sample size justification, enrollment, and groups.
- `risks_benefits`: risks, benefits, side effects, combined compensation/reimbursement form input, and participant-facing text for ICF content.
- `generated`: agent-generated text that templates use directly. Group by document, for example `generated.protocol.introduction`, `generated.icf.study_purpose`, and `generated.short.summary`.
- `regulatory`: XML-specific values and flags. Keep jurisdiction-specific mappings here instead of hardcoding them in scripts. For ClinicalTrials.gov PRS XML, put reviewer-controlled values under `regulatory.prs`.
- `needs_review`: array of review items with `field`, `issue`, and optional `source` and `kind`. For a starred-field conflict in any branch, set `kind` to `conflict`; ordinary review notes remain nonblocking.

## Minimal Example

```json
{
  "meta": {
    "protocol_number": "MB-25-01",
    "version": "1.0",
    "date": "08 Dec 2025",
    "study_type": "Retrospective",
    "document_set": ["protocol_docx", "icf_docx", "short_docx", "xml"]
  },
  "source": {
    "channel": "manual_context",
    "raw_files": ["input/raw_context.md"],
    "notes": "Created from unstructured study notes.",
    "source_of_truth_file": null,
    "source_of_truth_md": null,
    "source_of_truth_status": null
  },
  "template_fields": {},
  "approval": {
    "status": "pending_review",
    "review_file": "reference/source-of-truth--mb-25-01--unity-vcs-27g-vs-constellation-27g-efficiency.md",
    "approved_by": null,
    "approved_at": null,
    "notes": null
  },
  "study": {
    "title": "Unity VCS 27G platform advantage over Constellation 27G",
    "short_title": "Unity VCS 27G vs. Constellation 27G Efficiency",
    "condition": "Retinal disease",
    "background": null,
    "hypothesis": null
  },
  "parties": {
    "sponsor": {
      "name": "Drs Berrocal & Associates",
      "address": "150 Avenida de Diego, San Juan Health Centre, Suite 404, San Juan, PR 00907"
    },
    "principal_investigator": {
      "name": "Maria Berrocal, MD",
      "title": null,
      "affiliation": "Drs Berrocal & Associates"
    }
  },
  "sites": [
    {
      "facility": {
        "name": "Drs Berrocal & Associates",
        "address": {
          "city": "San Juan",
          "state": null,
          "country": null,
          "zip": null
        }
      }
    }
  ],
  "population": {
    "sample_size": "100 eyes",
    "sample_justification": null,
    "inclusion_criteria": [],
    "exclusion_criteria": []
  },
  "design": {
    "study_design": "Retrospective, single-surgeon video review",
    "arms": []
  },
  "objectives": {
    "primary": []
  },
  "endpoints": {
    "primary": [],
    "secondary": []
  },
  "procedures": {},
  "statistics": {},
  "risks_benefits": {},
  "generated": {
    "protocol": {},
    "icf": {},
    "short": {},
    "xml": {}
  },
  "regulatory": {
    "jurisdiction": null,
    "xml_profile": null,
    "prs": {
      "provider_study_id": null,
      "provider_name": "NLM_DES",
      "org_name": null,
      "overall_status": null,
      "irb_approval_status": null,
      "study_uid": null,
      "lead_sponsor_agency": null,
      "collaborator_agency": null,
      "last_follow_up_date": null,
      "last_follow_up_date_type": null,
      "study_timing": null
    }
  },
  "needs_review": [
    {
      "field": "regulatory.xml_profile",
      "issue": "Exact XML structure has not been provided yet."
    }
  ]
}
```

## Study Type Document Sets

Set `meta.document_set` from the study type branch unless the user/client explicitly requests an optional output:

```json
{
  "Prospective": ["protocol_docx", "icf_docx", "xml"],
  "Ambispective": ["protocol_docx", "icf_docx", "xml"],
  "Retrospective": ["protocol_docx"]
}
```

Use `short_docx` only when a shorter summary document is requested or a short template is intentionally provided.

## Review Item Format

Use this shape for every unresolved issue:

```json
{
  "field": "population.minimum_age",
  "issue": "Minimum age was not stated in the source material.",
  "source": "input/raw_context.md"
}
```

## Approval Format

New runs start in review mode. Once the source Markdown exists, use it as the review file:

```json
{
  "approval": {
    "status": "pending_review",
    "review_file": "reference/source-of-truth--<protocol>--<study-slug>.md",
    "approved_by": null,
    "approved_at": null,
    "notes": null
  }
}
```

Use `changes_requested` while corrections are being applied. Use `approved` only after explicit reviewer approval of the source Markdown, then validate and render with `--require-approval`.

## n8n Branch Template Fields

For prospective protocol, ICF, and XML variables from the existing workflow, run:

```bash
python3 scripts/build_n8n_prospective_fields.py --run-dir <run-dir>
```

For ambispective protocol, ICF, and XML variables from the existing workflow, run:

```bash
python3 scripts/build_n8n_ambispective_fields.py --run-dir <run-dir>
```

For retrospective protocol templates from the existing workflow, run:

```bash
python3 scripts/build_n8n_retrospective_protocol_fields.py --run-dir <run-dir>
```

These populate `template_fields` with legacy placeholders such as `AI_shortTitle`, `AI_introduction`, `AI_populationLong`, `AI_studyDesignLong`, and `sampleSizeJustification`. Keep module prose under `generated.protocol` or `generated.icf`; `template_fields` is only the rendering adapter.

For prospective or ambispective PRS XML, run `scripts/build_prs_xml_fields.py` after the n8n mapper. It populates PRS placeholders under `template_fields`, sets `regulatory.xml_profile` to `clinicaltrials-prs`, and records repeated XML counts under `template_fields.__prs_counts`.
