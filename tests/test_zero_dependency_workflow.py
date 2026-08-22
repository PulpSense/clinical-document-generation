from __future__ import annotations

import json
import io
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_static_toc import audit  # noqa: E402
from build_n8n_prospective_fields import build_fields as build_prospective_fields  # noqa: E402
from build_prs_xml_fields import blocking_missing_items, build_fields as build_prs_fields  # noqa: E402
from check_required_inputs import missing_inputs  # noqa: E402
from create_run import main as create_run_main  # noqa: E402
from create_source_truth_md import document_markdown  # noqa: E402
from export_docx_to_pdf import export_docx, main as export_docx_main, renderer_order  # noqa: E402
from icf_template_selection import (  # noqa: E402
    BUNDLED_ICF_TEMPLATES,
    ensure_run_icf_template,
    resolve_icf_template_choice,
)
from pdf_text import extract_pdf_pages  # noqa: E402
from refresh_static_toc import refresh_docx  # noqa: E402
from render_templates import (  # noqa: E402
    render_docx,
    render_xml,
    render_text_template,
    run_generation,
    unresolved_in_docx,
    visible_text_from_word_xml,
)
from scan_placeholders import scan_path  # noqa: E402
from study_type_branches import (  # noqa: E402
    AMBISPECTIVE_STARRED_FIELDS,
    DOC_TEMPLATES,
    PROSPECTIVE_STARRED_FIELDS,
    RETROSPECTIVE_STARRED_FIELDS,
    STARRED_FILLOUT_FIELDS,
    content_completeness_missing,
    validate_branch,
)
from validate_reference import blocking_review_items, main as validate_reference_main  # noqa: E402
from workflow import branch_contract, validated_client_outputs  # noqa: E402


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def write_docx(path: Path, document_xml: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr(
            "word/settings.xml",
            f'<w:settings xmlns:w="{WORD_NS}"></w:settings>',
        )


def write_pdf(path: Path, lines: list[str]) -> None:
    escaped_lines = [
        line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        for line in lines
    ]
    stream = "\n".join(
        f"BT /F1 12 Tf ({line}) Tj ET" for line in escaped_lines
    ).encode("cp1252")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Count 1 /Kids [3 0 R] >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        ),
        (
            b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>\nendobj\n"
        ),
        b"5 0 obj\n<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream\nendobj\n",
    ]
    path.write_bytes(b"%PDF-1.4\n" + b"".join(objects) + b"%%EOF\n")


class RendererTests(unittest.TestCase):
    def test_docx_renderer_handles_split_tokens_and_line_breaks(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{{study.</w:t></w:r><w:r><w:t>title}}</w:t></w:r></w:p>
<w:p><w:r><w:t>{{generated.summary}}</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="12240"/><w:pgMar w:left="1440" w:right="1440"/></w:sectPr>
</w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.docx"
            output = root / "output.docx"
            write_docx(template, document)
            unresolved = render_docx(
                template,
                output,
                {"study": {"title": "A & B"}, "generated": {"summary": "First\nSecond"}},
            )
            self.assertEqual(unresolved, [])
            with zipfile.ZipFile(output) as archive:
                xml = archive.read("word/document.xml").decode()
            self.assertIn("A &amp; B", xml)
            self.assertIn("<w:br/>", xml)
            self.assertIn("First\nSecond", visible_text_from_word_xml(xml))

    def test_all_bundled_docx_templates_render_without_placeholders(self) -> None:
        templates = sorted((REPO_ROOT / "assets/client-templates/docx").glob("*.docx"))
        self.assertTrue(templates)
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary)
            for template in templates:
                fields = {
                    token["name"]: "Line one\nLine two" if token["name"].startswith("AI_") else f"VALUE_{token['name']}"
                    for token in scan_path(template)
                    if token["kind"] == "variable"
                }
                output = output_root / template.name
                render_docx(template, output, fields)
                self.assertEqual(unresolved_in_docx(output), [], template.name)
                with zipfile.ZipFile(output) as archive:
                    self.assertIsNone(archive.testzip(), template.name)

    def test_text_renderer_supports_blocks_and_xml_escaping(self) -> None:
        template = "{#items}<x>{name}</x>{/items}{^missing}<empty/>{/missing}"
        rendered = render_text_template(
            template,
            {"items": [{"name": "A & B"}, {"name": "C"}], "missing": False},
        )
        self.assertEqual(rendered, "<x>A &amp; B</x><x>C</x><empty/>")

    def test_docx_renderer_repeats_table_rows(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body><w:tbl>
<w:tr><w:tc><w:p><w:r><w:t>{{#sites}}{{name}}{{/sites}}</w:t></w:r></w:p></w:tc></w:tr>
</w:tbl></w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template.docx"
            output = root / "output.docx"
            write_docx(template, document)
            render_docx(template, output, {"sites": [{"name": "Alpha"}, {"name": "Beta"}]})
            with zipfile.ZipFile(output) as archive:
                xml = archive.read("word/document.xml").decode()
            self.assertEqual(xml.count("<w:tr>"), 2)
            self.assertIn("Alpha", xml)
            self.assertIn("Beta", xml)

    def test_bundled_prs_xml_renders_with_repeated_blocks(self) -> None:
        template = REPO_ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml"
        fields = {
            token["name"]: True if token["kind"] == "block_start" else f"VALUE_{token['name']}"
            for token in scan_path(template)
            if token["kind"] in {"variable", "block_start"}
        }
        fields["__xml_profile"] = "clinicaltrials-prs"
        fields["__prs_counts"] = {
            "intervention": 3,
            "arm_group": 1,
            "primary_outcome": 1,
            "secondary_outcome": 2,
            "other_outcome": 2,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "study.xml"
            unresolved = render_xml(template, output, fields)
            rendered = output.read_text(encoding="utf-8")
            self.assertEqual(unresolved, [])
            self.assertEqual(rendered.count("<intervention>"), 3)
            self.assertEqual(rendered.count("<arm_group>"), 1)
            self.assertEqual(rendered.count("<secondary_outcome>"), 2)
            self.assertEqual(rendered.count("<other_outcome>"), 2)

    def test_generation_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference = run_dir / "reference/study.reference.json"
            reference.parent.mkdir(parents=True)
            reference.write_text(
                json.dumps({"approval": {"status": "pending_review"}}), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "requires approval"):
                run_generation(run_dir, reference, require_approval=True)


class DeliveryGateTests(unittest.TestCase):
    def write_minimal_run(self, run_dir: Path, reference: dict) -> None:
        (run_dir / "reference").mkdir(parents=True)
        (run_dir / "templates").mkdir()
        (run_dir / "reference/study.reference.json").write_text(
            json.dumps(reference), encoding="utf-8"
        )
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body>
<w:p><w:r><w:t>No placeholders</w:t></w:r></w:p>
</w:body></w:document>'''
        write_docx(run_dir / "templates/protocol.template.docx", document)
        write_docx(run_dir / "templates/icf.template.docx", document)
        (run_dir / "templates/study.template.xml").write_text("<study />", encoding="utf-8")

    def approved_prospective_reference(self) -> dict:
        reference = StarredInputGateTests().complete_reference()
        reference["meta"]["document_set"] = ["protocol_docx", "icf_docx", "xml"]
        reference["approval"] = {"status": "approved"}
        reference["source"]["source_of_truth_file"] = "reference/source.md"
        reference["generated"] = {
            "protocol": {"introduction": "Generated protocol content."},
            "icf": {"study_purpose": "Generated ICF content."},
        }
        reference["regulatory"] = {"xml_profile": "clinicaltrials-prs"}
        reference["template_fields"] = {"AI_introduction": "Generated protocol content."}
        return reference

    def test_require_approval_writes_repair_report_for_incomplete_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            self.write_minimal_run(run_dir, self.approved_prospective_reference())

            argv = ["validate_reference.py", "--run-dir", str(run_dir), "--require-approval"]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(validate_reference_main(), 1)

            repair_report = run_dir / "reference/repair-report.md"
            self.assertTrue(repair_report.is_file())
            report_text = repair_report.read_text(encoding="utf-8")
            self.assertIn("Content Completeness Gate", report_text)
            self.assertIn("Data-Driven Table", report_text)
            self.assertIn("Generated ICF", report_text)
            self.assertIn("Generated PRS XML", report_text)
            self.assertIn("template_fields.data_driven_tables.visit_schedule.rows", report_text)

    def test_content_completeness_passes_with_protocol_icf_and_xml_tables(self) -> None:
        reference = self.approved_prospective_reference()
        reference["template_fields"] = {
            "AI_populationShort": "Adults with the target condition.",
            "AI_introduction": "Protocol introduction.",
            "AI_populationLong": "Population section.",
            "AI_inclusionCriteria": "Eligible adults.",
            "AI_exclusionCriteria": "Concurrent study participation.",
            "AI_studyDesignLong": "Prospective single-arm study.",
            "AI_methods": "Study methods.",
            "AI_visitSchedule": "Screening and Month 3.",
            "AI_visitScheduleDetails": "Visit details.",
            "AI_measurements": "Assessments overview.",
            "AI_measurementsDetails": "Assessment details.",
            "AI_analysisDataSets": "Analysis dataset.",
            "AI_statisticalMethodology": "Statistical methods.",
            "AI_statisticalConsiderations": "Statistical considerations.",
            "AI_risks": "Known risks.",
            "AI_studyPurpose": "Participant-facing purpose.",
            "AI_icfVisitsOverview": "Participant visit overview.",
            "AI_visitsDetails": "Participant visit details.",
            "AI_visitsAndLength": "Study length and participants.",
            "AI_interventionPossibleSideEffects": "Possible side effects.",
            "data_driven_tables": {
                "visit_schedule": {
                    "rows": [
                        {
                            "visitNumber": "1",
                            "visitName": "Screening",
                            "visitWindow": "Day -30 to Day 0",
                            "CRFnumber": "SCR",
                        }
                    ]
                },
                "prs_xml": {
                    "primary_outcomes": {
                        "rows": [
                            {
                                "outcomeMeasure": "Primary endpoint",
                                "outcomeTimeFrame": "Month 3",
                                "uid": "PS-001",
                                "description": "Primary endpoint description.",
                            }
                        ]
                    }
                },
            },
        }

        self.assertEqual(content_completeness_missing(reference), [])

    def test_final_generation_blocks_incomplete_delivery_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            reference_data = self.approved_prospective_reference()
            self.write_minimal_run(run_dir, reference_data)
            reference = run_dir / "reference/study.reference.json"

            with self.assertRaisesRegex(ValueError, "Content Completeness Gate"):
                run_generation(run_dir, reference, require_approval=True)


class TocTests(unittest.TestCase):
    def test_pdf_extractor_and_toc_refresh_use_standard_library(self) -> None:
        document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{WORD_NS}"><w:body>
<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>Section One ........ 1</w:t></w:r></w:p>
<w:p><w:r><w:t>Section One</w:t></w:r></w:p>
<w:sectPr><w:pgSz w:w="12240"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
</w:body></w:document>'''
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            docx = root / "document.docx"
            pdf = root / "document.pdf"
            write_docx(docx, document)
            write_pdf(pdf, ["Section One"])
            self.assertEqual(extract_pdf_pages(pdf), ["Section One\n"])

            before = audit(docx, pdf)
            self.assertEqual(before["entry_count"], 1)
            self.assertEqual(before["alignment_mismatch_count"], 1)
            refreshed = refresh_docx(docx, pdf, docx)
            self.assertEqual(refreshed["aligned_count"], 1)

            after = audit(docx, pdf)
            self.assertEqual(after["mismatch_count"], 0)
            self.assertEqual(after["missing_count"], 0)
            self.assertEqual(after["alignment_mismatch_count"], 0)


class RepositoryContractTests(unittest.TestCase):
    def test_replacement_has_one_public_workflow_and_six_python_ownership_modules(self) -> None:
        expected = {"workflow.py", "contracts.py", "drafting.py", "rendering.py", "quality.py", "prs_xml.py"}
        self.assertTrue(expected.issubset({path.name for path in (REPO_ROOT / "scripts").glob("*.py")}))
        self.assertTrue((REPO_ROOT / "scripts/clinical_document_workflow.py").exists())
        references = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (REPO_ROOT / "README.md", REPO_ROOT / "SKILL.md")
        )
        self.assertNotIn("python3 scripts/clinical_document_workflow.py", references)
        self.assertIn("clinical_document_workflow", references)

    def test_scripts_directory_contains_python_only(self) -> None:
        forbidden = {".js", ".mjs", ".cjs", ".applescript"}
        offenders = [path.name for path in SCRIPTS_DIR.iterdir() if path.suffix in forbidden]
        self.assertEqual(offenders, [])
        self.assertFalse((SCRIPTS_DIR / "package.json").exists())
        self.assertFalse((SCRIPTS_DIR / "package-lock.json").exists())

    def test_all_study_branches_have_stable_document_and_handoff_contracts(self) -> None:
        expected = {
            "Prospective": {"protocol_docx", "icf_docx", "xml"},
            "Ambispective": {"protocol_docx", "icf_docx", "xml"},
            "Retrospective": {"protocol_docx"},
        }
        for study_type, documents in expected.items():
            contract = branch_contract({"meta": {"study_type": study_type}})
            self.assertEqual(set(contract["required_document_set"]), documents)
            self.assertEqual(contract["missing_documents"], [])

        root = Path(tempfile.mkdtemp())
        self.assertEqual(validated_client_outputs(root, {"approval_status": "pending_review", "outputs": []}), [])
        self.assertEqual(validated_client_outputs(root, {"approval_status": "approved", "outputs": [], "delivery_gates": {"status": "failed"}}), [])

    def test_sterling_template_is_clean_and_uses_supported_placeholders(self) -> None:
        template = REPO_ROOT / "assets/client-templates/docx/sterling-icf.template.docx"
        self.assertTrue(template.is_file())
        with zipfile.ZipFile(template) as archive:
            visible_parts = "\n".join(
                archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
                if name in {"word/document.xml", "word/header2.xml"}
            )
        for stale in ("MERGEFIELD", "«", "»", "w:highlight", "xx/xx/xxxx", "XX years"):
            self.assertNotIn(stale, visible_parts)
        token_names = {item["name"] for item in scan_path(template) if item["kind"] == "variable"}
        self.assertIn("AI_studyPurpose", token_names)
        self.assertIn("sterlingIrbId", token_names)


class PortableDocxExporterTests(unittest.TestCase):
    def test_renderer_order_is_platform_aware(self) -> None:
        self.assertEqual(renderer_order("Darwin"), ["pages", "libreoffice"])
        self.assertEqual(renderer_order("Windows"), ["word", "libreoffice"])
        self.assertEqual(renderer_order("Linux"), ["libreoffice"])

    def test_missing_renderer_is_nonblocking_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "document.docx"
            output_path = root / "document.pdf"
            input_path.write_bytes(b"DOCX placeholder for exporter selection test")
            with patch("export_docx_to_pdf.renderer_available", return_value=False):
                result, return_code = export_docx(input_path, output_path)
            self.assertEqual(return_code, 0)
            self.assertEqual(result["status"], "unavailable")
            self.assertTrue(input_path.is_file())
            self.assertFalse(output_path.exists())

    def test_explicit_or_required_renderer_remains_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "document.docx"
            output_path = root / "document.pdf"
            input_path.write_bytes(b"DOCX placeholder for strict renderer test")
            with patch("export_docx_to_pdf.renderer_available", return_value=False):
                explicit_result, explicit_code = export_docx(
                    input_path,
                    output_path,
                    renderer="libreoffice",
                )
                required_result, required_code = export_docx(
                    input_path,
                    output_path,
                    require_renderer=True,
                )
            self.assertEqual(explicit_result["status"], "unavailable")
            self.assertEqual(required_result["status"], "unavailable")
            self.assertEqual(explicit_code, 1)
            self.assertEqual(required_code, 1)

    def test_cli_writes_nonblocking_unavailable_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "document.docx"
            output_path = root / "document.pdf"
            report_path = root / "render-report.json"
            input_path.write_bytes(b"DOCX placeholder for report test")
            with (
                patch("export_docx_to_pdf.renderer_available", return_value=False),
                redirect_stdout(io.StringIO()),
            ):
                return_code = export_docx_main(
                    [str(input_path), str(output_path), "--report", str(report_path)]
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(return_code, 0)
            self.assertEqual(report["status"], "unavailable")
            self.assertFalse(output_path.exists())


class StarredInputGateTests(unittest.TestCase):
    def complete_reference(self, study_type: str = "Prospective") -> dict:
        return {
            "meta": {"study_type": study_type, "icf_template": "Advarra"},
            "source": {"field_candidates": {}},
            "study": {
                "title": "Prospective Study",
                "background": "Background and significance.",
                "hypothesis": "The intervention will improve the primary outcome.",
                "timeline": "Screening through Month 3.",
            },
            "objectives": {"primary": ["Evaluate the primary outcome."]},
            "design": {
                "study_design": "Prospective, single-arm study.",
                "intervention_name": "Study Device",
                "intervention_type": "Device",
                "number_of_sites": "One",
            },
            "endpoints": {
                "primary": ["Primary endpoint at Month 3."],
                "secondary": ["Secondary endpoint at Month 3."],
            },
            "procedures": {
                "assessments": "Baseline and Month 3 assessments.",
                "minimum_days_before_screening_without_participation": 30,
            },
            "population": {
                "sample_size": "40 participants",
                "sample_justification": "Allows for expected dropout.",
                "inclusion_criteria": ["Adults eligible for treatment."],
                "exclusion_criteria": ["Concurrent study participation."],
            },
            "statistics": {"analysis_plan": "Descriptive analysis."},
            "risks_benefits": {"compensation_or_reimbursement": "None"},
            "parties": {
                "sponsor": {"name": "Study Sponsor", "address": "1 Main Street"},
                "principal_investigator": {"name": "Alex Smith", "title": "MD"},
                "study_coordinator": {
                    "name": "Jordan Lee",
                    "title": "CRC",
                    "business_phone": "555-0100",
                    "office_phone": "555-0101",
                    "email": "jordan@example.com",
                },
                "irb": {
                    "name": "Example IRB",
                    "affiliation": "Independent",
                    "phone": "555-0200",
                    "email": "irb@example.com",
                    "address": "2 Review Avenue",
                },
            },
            "sites": [
                {
                    "facility": {
                        "name": "Example Site",
                        "address": {
                            "city": "Boston",
                            "state": "MA",
                            "country": "United States",
                        },
                    },
                    "contact": {"name": "Jordan Lee", "email": "jordan@example.com"},
                    "investigators": [{"name": "Alex Smith", "degrees": "MD"}],
                }
            ],
            "needs_review": [],
        }

    def complete_retrospective_reference(self) -> dict:
        return {
            "meta": {"study_type": "Retrospective"},
            "source": {"field_candidates": {}},
            "study": {
                "title": "Retrospective Outcomes Study",
                "background": "Background and significance.",
                "unmet_need": "Evidence is limited for the selected population.",
                "hypothesis": "The historical cohort will demonstrate the expected association.",
            },
            "objectives": {"primary": ["Evaluate outcomes in existing records."]},
            "design": {
                "study_design": "Retrospective observational study.",
                "number_of_sites": 3,
            },
            "endpoints": {"primary": ["Primary outcome in the historical record."]},
            "procedures": {"assessments": "Existing records from baseline through Month 12."},
            "population": {
                "sample_size": "120 records",
                "sample_justification": "All eligible records in the study period.",
                "inclusion_criteria": ["Eligible historical records."],
                "exclusion_criteria": ["Incomplete historical records."],
            },
            "statistics": {"analysis_plan": "Descriptive and multivariable analysis."},
            "parties": {
                "sponsor": {"name": "Study Sponsor", "address": "1 Main Street"},
                "principal_investigator": {"name": "Alex Smith", "title": "MD"},
                "irb": {"name": "Example IRB", "address": "2 Review Avenue"},
            },
            "sites": [{"facility": {"name": "Primary Facility"}}],
            "needs_review": [],
        }

    def test_both_contracts_share_the_35_starred_fields(self) -> None:
        self.assertEqual(len(STARRED_FILLOUT_FIELDS), 35)
        self.assertIs(PROSPECTIVE_STARRED_FIELDS, STARRED_FILLOUT_FIELDS)
        self.assertIs(AMBISPECTIVE_STARRED_FIELDS, STARRED_FILLOUT_FIELDS)
        for study_type in ("Prospective", "Ambispective"):
            self.assertEqual(missing_inputs(self.complete_reference(study_type)), [])

    def test_retrospective_contract_contains_21_starred_fields(self) -> None:
        self.assertEqual(len(RETROSPECTIVE_STARRED_FIELDS), 21)
        self.assertEqual(
            [item["field"] for item in RETROSPECTIVE_STARRED_FIELDS],
            [
                "study.title",
                "study.background",
                "objectives.primary",
                "study.unmet_need",
                "study.hypothesis",
                "design.study_design",
                "design.number_of_sites",
                "endpoints.primary",
                "procedures.assessments",
                "population.inclusion_criteria",
                "population.exclusion_criteria",
                "population.sample_size",
                "population.sample_justification",
                "statistics.analysis_plan",
                "parties.irb.name",
                "parties.irb.address",
                "parties.sponsor.name",
                "parties.sponsor.address",
                "sites.0.facility.name",
                "parties.principal_investigator.name",
                "parties.principal_investigator.title",
            ],
        )
        self.assertEqual(missing_inputs(self.complete_retrospective_reference()), [])

    def test_whitespace_in_starred_field_is_missing(self) -> None:
        for study_type in ("Prospective", "Ambispective"):
            reference = self.complete_reference(study_type)
            reference["parties"]["study_coordinator"]["title"] = "   "
            missing = missing_inputs(reference)
            self.assertEqual([item["field"] for item in missing], ["parties.study_coordinator.title"])

    def test_distinct_candidates_for_starred_field_block(self) -> None:
        for study_type in ("Prospective", "Ambispective"):
            reference = self.complete_reference(study_type)
            reference["source"]["field_candidates"]["study.title"] = [
                {"value": "Title A", "source": "a.docx"},
                {"value": "Title B", "source": "b.docx"},
            ]
            missing = missing_inputs(reference)
            self.assertEqual([item["field"] for item in missing], ["study.title"])
            self.assertIn("2 distinct source inputs", missing[0]["issue"])

    def test_identical_candidates_and_multi_item_answers_do_not_block(self) -> None:
        reference = self.complete_reference()
        reference["source"]["field_candidates"]["study.title"] = [
            {"value": "Prospective Study", "source": "a.docx"},
            {"value": "Prospective Study", "source": "b.docx"},
        ]
        reference["source"]["field_candidates"]["endpoints.primary"] = [
            {"value": ["Endpoint A", "Endpoint B"], "source": "protocol.docx"}
        ]
        self.assertEqual(missing_inputs(reference), [])

    def test_site_count_conflict_blocks_but_agreement_does_not(self) -> None:
        reference = self.complete_reference()
        self.assertEqual(missing_inputs(reference), [])
        reference["design"]["number_of_sites"] = "Two"
        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["design.number_of_sites"])

    def test_each_starred_site_and_phone_input_must_be_supplied(self) -> None:
        reference = self.complete_reference()
        reference["design"].pop("number_of_sites")
        reference["parties"]["study_coordinator"].pop("business_phone")
        reference["parties"]["study_coordinator"]["phone"] = "555-0100"
        reference["sites"][0].pop("contact")
        reference["sites"][0].pop("investigators")
        missing = missing_inputs(reference)
        self.assertEqual(
            [item["field"] for item in missing],
            [
                "design.number_of_sites",
                "parties.study_coordinator.business_phone",
                "sites.contacts",
                "sites.investigators",
            ],
        )

    def test_tabular_site_input_satisfies_site_groups_before_icf_choice(self) -> None:
        reference = self.complete_reference()
        reference["meta"].pop("icf_template")
        reference["design"]["number_of_sites"] = 2
        reference["sites"] = [
            {
                "facility": {"name": "North Neurology Research Center"},
                "contact": {"name": "Casey Nguyen", "email": "casey.nguyen@example.org"},
                "investigators": [{"name": "Dana Roberts", "degrees": "MD"}],
            },
            {
                "facility": {"name": "Lakeside Headache Institute"},
                "contact": {"name": "Morgan Patel", "email": "morgan.patel@example.org"},
                "investigators": [{"name": "Lee Martinez", "degrees": "DO"}],
            },
        ]
        reference["source"]["field_candidates"].update(
            {
                "sites.facilities": [
                    {
                        "source": "prospective_table_input_no_icf_template.md#Participating Facilities",
                        "value": [site["facility"] for site in reference["sites"]],
                    }
                ],
                "sites.contacts": [
                    {
                        "source": "prospective_table_input_no_icf_template.md#Site Contacts",
                        "value": [site["contact"] for site in reference["sites"]],
                    }
                ],
                "sites.investigators": [
                    {
                        "source": "prospective_table_input_no_icf_template.md#Site Investigators",
                        "value": [site["investigators"] for site in reference["sites"]],
                    }
                ],
            }
        )
        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["meta.icf_template"])

    def test_non_table_site_input_satisfies_site_groups_before_icf_choice(self) -> None:
        reference = self.complete_reference()
        reference["meta"].pop("icf_template")
        reference["design"]["number_of_sites"] = 2
        reference["sites"] = [
            {
                "facility": {"name": "North Neurology Research Center"},
                "contact": {"name": "Casey Nguyen", "email": "casey.nguyen@example.org"},
                "investigators": [{"name": "Dana Roberts", "degrees": "MD"}],
            },
            {
                "facility": {"name": "Lakeside Headache Institute"},
                "contact": {"name": "Morgan Patel", "email": "morgan.patel@example.org"},
                "investigators": [{"name": "Lee Martinez", "degrees": "DO"}],
            },
        ]
        reference["source"]["field_candidates"].update(
            {
                "sites.facilities": [
                    {
                        "source": "prospective_non_table_input_no_icf_template.md#Site narrative",
                        "value": "Site 01 is North Neurology Research Center; Site 02 is Lakeside Headache Institute.",
                    }
                ],
                "sites.contacts": [
                    {
                        "source": "prospective_non_table_input_no_icf_template.md#Site narrative",
                        "value": "Casey Nguyen and Morgan Patel are the site contacts.",
                    }
                ],
                "sites.investigators": [
                    {
                        "source": "prospective_non_table_input_no_icf_template.md#Site narrative",
                        "value": "Dana Roberts, MD, and Lee Martinez, DO, are the site investigators.",
                    }
                ],
            }
        )
        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["meta.icf_template"])

    def test_optional_review_items_do_not_block_starred_branches(self) -> None:
        for study_type in ("Prospective", "Ambispective"):
            reference = self.complete_reference(study_type)
            reference["needs_review"] = [
                {"field": "regulatory.prs.org_name", "issue": "Not supplied."},
                {"field": "endpoints.primary.0.uid", "issue": "Not supplied."},
            ]
            self.assertEqual(missing_inputs(reference), [])
            self.assertEqual(blocking_review_items(reference, reference["needs_review"]), [])

            prs_missing = [
                {"field": "regulatory.prs.org_name", "issue": "Not supplied."},
                {"field": "endpoints.primary.0.uid", "issue": "Not supplied."},
                {"field": "endpoints.primary", "issue": "Primary endpoint missing."},
            ]
            self.assertEqual(
                blocking_missing_items(reference, prs_missing),
                [{"field": "endpoints.primary", "issue": "Primary endpoint missing."}],
            )

    def test_ambispective_legacy_extras_are_not_intake_blockers(self) -> None:
        reference = self.complete_reference("Ambispective")
        reference["needs_review"] = [
            {"field": "meta.protocol_number", "issue": "Not supplied."},
            {"field": "parties.principal_investigator.affiliation", "issue": "Not supplied."},
            {"field": "regulatory.prs.study_uid", "issue": "Not supplied."},
            {"field": "parties.overall_contact", "issue": "Not supplied."},
        ]
        self.assertEqual(missing_inputs(reference), [])
        self.assertEqual(blocking_review_items(reference, reference["needs_review"]), [])
        self.assertEqual(
            blocking_missing_items(reference, reference["needs_review"]),
            [],
        )

    def test_ambispective_final_branch_validation_does_not_restore_legacy_extras(self) -> None:
        reference = self.complete_reference("Ambispective")
        reference["meta"]["document_set"] = ["protocol_docx", "icf_docx", "xml"]
        reference["generated"] = {
            "protocol": {"introduction": "Generated protocol content."},
            "icf": {"study_purpose": "Generated consent content."},
        }
        reference["regulatory"] = {"xml_profile": "clinicaltrials-prs"}
        available = [
            DOC_TEMPLATES["protocol_docx"],
            DOC_TEMPLATES["icf_docx"],
            DOC_TEMPLATES["xml"],
        ]
        missing, _, active = validate_branch(reference, available)
        self.assertEqual(missing, [])
        self.assertEqual(active, available)

    def test_review_item_for_starred_field_blocks(self) -> None:
        for study_type in ("Prospective", "Ambispective"):
            reference = self.complete_reference(study_type)
            reference["needs_review"] = [
                {"field": "study.title", "kind": "conflict", "issue": "Two titles were supplied."},
            ]
            missing = missing_inputs(reference)
            self.assertEqual(missing, [{"field": "study.title", "issue": "Two titles were supplied."}])

    def test_generic_review_note_on_starred_field_does_not_block(self) -> None:
        for study_type in ("Prospective", "Ambispective"):
            reference = self.complete_reference(study_type)
            reference["needs_review"] = [
                {"field": "study.title", "issue": "Confirm capitalization later."},
            ]
            self.assertEqual(missing_inputs(reference), [])

    def test_retrospective_missing_and_conflicting_starred_fields_block(self) -> None:
        reference = self.complete_retrospective_reference()
        reference["study"]["unmet_need"] = "   "
        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["study.unmet_need"])

        reference["study"]["unmet_need"] = "Evidence is limited."
        reference["source"]["field_candidates"]["study.title"] = [
            {"value": "Title A", "source": "a.docx"},
            {"value": "Title B", "source": "b.docx"},
        ]
        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["study.title"])

    def test_retrospective_site_count_is_independent_from_single_facility(self) -> None:
        reference = self.complete_retrospective_reference()
        self.assertEqual(reference["design"]["number_of_sites"], 3)
        self.assertEqual(len(reference["sites"]), 1)
        self.assertEqual(missing_inputs(reference), [])

    def test_retrospective_optional_fields_and_notes_do_not_block(self) -> None:
        reference = self.complete_retrospective_reference()
        reference["needs_review"] = [
            {"field": "meta.protocol_number", "issue": "Not supplied."},
            {"field": "parties.funding_source", "issue": "Not supplied."},
            {"field": "sites.0.facility.address.city", "issue": "Not supplied."},
            {"field": "parties.sub_investigators", "issue": "Not supplied."},
            {"field": "design.test_articles", "issue": "Not supplied."},
            {"field": "source.references", "issue": "Not supplied."},
        ]
        self.assertEqual(missing_inputs(reference), [])
        self.assertEqual(blocking_review_items(reference, reference["needs_review"]), [])

    def test_retrospective_facility_name_and_pi_title_are_independently_required(self) -> None:
        reference = self.complete_retrospective_reference()
        reference["sites"][0]["facility"].pop("name")
        reference["sites"][0]["facility"]["address"] = {"city": "Boston"}
        reference["parties"]["principal_investigator"].pop("title")
        missing = missing_inputs(reference)
        self.assertEqual(
            [item["field"] for item in missing],
            ["sites.0.facility.name", "parties.principal_investigator.title"],
        )

    def test_retrospective_final_branch_validation_uses_only_starred_source_inputs(self) -> None:
        reference = self.complete_retrospective_reference()
        reference["meta"]["document_set"] = ["protocol_docx"]
        reference["generated"] = {"protocol": {"introduction": "Generated protocol content."}}
        available = [DOC_TEMPLATES["protocol_docx"]]
        missing, _, active = validate_branch(reference, available)
        self.assertEqual(missing, [])
        self.assertEqual(active, available)

    def test_prospective_mapper_preserves_structured_visit_table(self) -> None:
        reference = self.complete_reference()
        reference["generated"] = {
            "protocol": {
                "visitScheduleTable": [
                    {
                        "visitNumber": "1",
                        "visitName": "Screening",
                        "visitWindow": "Day -30 to Day 0",
                        "CRFnumber": "SCR",
                    },
                    {
                        "visitNumber": "2",
                        "visitName": "Month 3",
                        "visitWindow": "Day 90 +/- 7",
                        "CRFnumber": "M3",
                    },
                ]
            }
        }

        fields = build_prospective_fields(reference)

        self.assertEqual(fields["visitsTable"], "")
        visit_table = fields["data_driven_tables"]["visit_schedule"]
        self.assertEqual(
            [column["key"] for column in visit_table["columns"]],
            ["visitNumber", "visitName", "visitWindow", "CRFnumber"],
        )
        self.assertEqual(visit_table["rows"][0]["visitName"], "Screening")

    def test_prs_mapper_preserves_structured_xml_tables(self) -> None:
        reference = self.complete_reference()
        reference["template_fields"] = build_prospective_fields(reference)
        reference["study"]["short_title"] = "Prospective Study"
        reference["study"]["condition"] = "Migraine"
        reference["regulatory"] = {
            "prs": {
                "provider_study_id": "PS-001",
                "org_name": "Example Org",
                "overall_status": "Recruiting",
                "irb_approval_status": "Approved",
                "study_uid": "UID-001",
            }
        }
        reference["design"]["arms"] = [
            {
                "label": "Device Arm",
                "type": "Experimental",
                "description": "Participants use the study device.",
                "intervention_type": "Device",
                "intervention_name": "Study Device",
            }
        ]
        reference["design"]["interventions"] = [
            {
                "type": "Device",
                "name": "Study Device",
                "description": "Wearable study device.",
                "arm_group_label": "Device Arm",
            }
        ]
        reference["endpoints"]["primary"] = [
            {
                "outcome_measure": "Change in symptom score",
                "outcome_time_frame": "Month 3",
                "uid": "UID-001",
                "description": "Change from baseline.",
            }
        ]
        reference["endpoints"]["secondary"] = []

        fields, missing = build_prs_fields(
            reference,
            REPO_ROOT / "assets/client-templates/prs/clinicaltrials_prs_full_placeholder_template.xml",
        )

        self.assertEqual(missing, [])
        data_tables = fields["data_driven_tables"]
        self.assertIn("visit_schedule", data_tables)
        prs_tables = data_tables["prs_xml"]
        self.assertEqual(
            [column["key"] for column in prs_tables["interventions"]["columns"]],
            ["interventionType", "interventionName", "interventionDescription", "armGroupLabel"],
        )
        self.assertEqual(prs_tables["interventions"]["rows"][0]["interventionName"], "Study Device")
        self.assertEqual(prs_tables["arm_groups"]["rows"][0]["armGroupLabel"], "Device Arm")
        self.assertEqual(prs_tables["primary_outcomes"]["rows"][0]["outcomeMeasure"], "Change in symptom score")


class IcfTemplateSelectionTests(unittest.TestCase):
    def reference(self, study_type: str = "Prospective", irb_name: str = "Example IRB") -> dict:
        return {
            "meta": {"study_type": study_type, "document_set": ["protocol_docx", "icf_docx", "xml"]},
            "parties": {"irb": {"name": irb_name}},
        }

    def test_detects_a_single_template_mention(self) -> None:
        result = resolve_icf_template_choice(
            self.reference(),
            raw_text="Please use the Sterling IRB consent template.",
        )
        self.assertEqual(result["choice"], "Sterling")
        self.assertEqual(result["reason"], "detected")

    def test_ambiguous_or_unsupported_irb_requires_a_choice(self) -> None:
        ambiguous = resolve_icf_template_choice(
            self.reference(),
            raw_text="Compare the Advarra and Sterling templates.",
        )
        self.assertIsNone(ambiguous["choice"])
        self.assertIn("Both Advarra and Sterling", ambiguous["issue"])

        unsupported = resolve_icf_template_choice(self.reference(irb_name="Central Review IRB"))
        self.assertIsNone(unsupported["choice"])
        self.assertIn("only the Advarra and Sterling", unsupported["issue"])

    def test_missing_selection_blocks_before_source_truth(self) -> None:
        reference = StarredInputGateTests().complete_reference()
        reference["meta"].pop("icf_template")
        missing = missing_inputs(reference)
        self.assertEqual(missing[0]["field"], "meta.icf_template")
        self.assertIn("before creating the source-of-truth file", missing[0]["issue"])

    def test_sterling_template_is_shared_by_prospective_and_ambispective(self) -> None:
        self.assertEqual(
            BUNDLED_ICF_TEMPLATES["Prospective"]["Sterling"],
            BUNDLED_ICF_TEMPLATES["Ambispective"]["Sterling"],
        )

    def test_selection_copies_template_and_records_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "input").mkdir()
            (run_dir / "input/raw_context.md").write_text("Use Sterling IRB.", encoding="utf-8")
            reference = self.reference("Ambispective")
            result = ensure_run_icf_template(run_dir, reference)
            destination = run_dir / "templates/icf.template.docx"
            self.assertEqual(result["choice"], "Sterling")
            self.assertEqual(reference["meta"]["icf_template"], "Sterling")
            self.assertEqual(
                destination.read_bytes(),
                BUNDLED_ICF_TEMPLATES["Ambispective"]["Sterling"].read_bytes(),
            )
            manifest = json.loads((run_dir / "input/source_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["templates"]["icf_template"]["selection"], "Sterling")

    def test_create_run_auto_selects_sterling_from_raw_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_context = root / "request.md"
            raw_context.write_text("Please generate this study using the Sterling ICF template.", encoding="utf-8")
            argv = [
                "create_run.py",
                "--root",
                str(root),
                "--slug",
                "auto-sterling",
                "--study-type",
                "prospective",
                "--raw-context",
                str(raw_context),
            ]
            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(create_run_main(), 0)

            run_dir = root / "auto-sterling"
            reference = json.loads((run_dir / "reference/study.reference.json").read_text(encoding="utf-8"))
            manifest = json.loads((run_dir / "input/source_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(reference["meta"]["icf_template"], "Sterling")
            self.assertEqual(manifest["templates"]["icf_template"]["selection"], "Sterling")
            self.assertTrue((run_dir / "templates/icf.template.docx").is_file())

    def test_template_choice_is_not_in_source_of_truth_markdown(self) -> None:
        reference = StarredInputGateTests().complete_reference()
        reference["meta"]["icf_template"] = "Sterling"
        rendered = document_markdown(reference)
        self.assertNotIn("meta.icf_template", rendered)
        self.assertNotIn("### Icf template", rendered)

    def test_retrospective_never_requires_icf_selection(self) -> None:
        reference = self.reference("Retrospective")
        reference["meta"]["document_set"] = ["protocol_docx"]
        result = resolve_icf_template_choice(reference, raw_text="Sterling")
        self.assertFalse(result["required"])
        self.assertIsNone(result["choice"])


class FinalInputFixtureTests(unittest.TestCase):
    FIXTURE_DIR = REPO_ROOT / "tests" / "final_inputs"

    def complete_reference_without_icf_choice(self) -> dict:
        reference = StarredInputGateTests().complete_reference()
        reference["meta"].pop("icf_template", None)
        reference["parties"]["irb"]["name"] = "PulpSense Central Review Board"
        reference["design"]["number_of_sites"] = 2
        reference["sites"] = [
            {
                "facility": {"name": "North Neurology Research Center"},
                "contact": {"name": "Casey Nguyen", "email": "casey.nguyen@example.org"},
                "investigators": [{"name": "Dana Roberts", "degrees": "MD"}],
            },
            {
                "facility": {"name": "Lakeside Headache Institute"},
                "contact": {"name": "Morgan Patel", "email": "morgan.patel@example.org"},
                "investigators": [{"name": "Lee Martinez", "degrees": "DO"}],
            },
        ]
        return reference

    def assert_fixture_leaves_only_icf_choice(self, fixture_name: str) -> None:
        raw_text = (self.FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
        lowered = raw_text.lower()
        self.assertNotIn("advarra", lowered)
        self.assertNotIn("sterling", lowered)
        self.assertNotIn("icf", lowered)
        self.assertNotIn("icf template", lowered)

        reference = self.complete_reference_without_icf_choice()
        selection = resolve_icf_template_choice(reference, raw_text=raw_text)
        self.assertTrue(selection["required"])
        self.assertIsNone(selection["choice"])
        self.assertEqual(selection["reason"], "missing")

        missing = missing_inputs(reference)
        self.assertEqual([item["field"] for item in missing], ["meta.icf_template"])

    def test_final_table_input_leaves_only_icf_template_choice(self) -> None:
        self.assert_fixture_leaves_only_icf_choice("prospective_table_input_no_icf_template.md")

    def test_final_non_table_input_leaves_only_icf_template_choice(self) -> None:
        self.assert_fixture_leaves_only_icf_choice("prospective_non_table_input_no_icf_template.md")


if __name__ == "__main__":
    unittest.main()
