from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_architecture_is_exactly_six_python_files():
    names = sorted(path.name for path in (ROOT / "scripts").glob("*.py"))
    assert names == ["contracts.py", "drafting.py", "prs_xml.py", "quality.py", "rendering.py", "workflow.py"]


def test_contracts_is_the_only_governed_resource_selector():
    forbidden_selectors = (
        "prospective-protocol.template.docx",
        "ambispective-protocol.template.docx",
        "retrospective-protocol.template.docx",
        "prospective-icf.template.docx",
        "ambispective-icf.template.docx",
        "sterling-icf.template.docx",
        "protocol-reference.docx",
        "advarra-icf-reference.docx",
        "sterling-icf-reference.docx",
        "clinicaltrials_prs_full_placeholder_template.xml",
        "prs-manual-reference.xml",
        "fixed-clinical-boilerplate.json",
    )
    consumers = ("drafting.py", "rendering.py", "quality.py", "workflow.py")
    for name in consumers:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "contracted_template_bundle" in source
        assert not any(selector in source for selector in forbidden_selectors)


def test_no_hidden_python_runtime_package_remains():
    assert not list((ROOT / "clinical_document_core").glob("*.py"))
    assert not list((ROOT / "scripts").glob("runtime_*.py"))
    source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "scripts").glob("*.py"))
    assert "clinical_document_core" not in source


def test_workflow_is_only_cli_entrypoint():
    for path in (ROOT / "scripts").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert ("argparse" in text) == (path.name == "workflow.py")


def test_shipped_workflow_owns_the_real_hermes_desktop_adapter():
    production = (ROOT / "scripts/workflow.py").read_text(encoding="utf-8")
    certification = (ROOT / "tests/hermes_e2e.py").read_text(encoding="utf-8")

    assert "def run_production_desktop_operation(" in production
    assert '"hermes", "chat", "-q"' in production
    assert '"--safe-mode"' in production
    assert 'parser.add_argument("--desktop-operation"' in production
    assert "certified_workflow.run_production_desktop_operation(" in certification
    assert "final_result = desktop_operation(" not in certification[
        certification.index("def run_release_certification_operation("):
        certification.index("def _case_artifact_findings(")
    ]


def test_skill_requires_source_truth_as_file_not_inline_chat():
    instructions = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "review_delivery" in instructions
    assert "Do not paste the Source-of-Truth contents into chat" in instructions


def test_skill_keeps_hermes_orchestration_context_path_only_and_bounded():
    instructions = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Use the returned `handoffs` as routing metadata" in instructions
    assert "Keep request contents out of the parent orchestration context" in instructions
    assert "one request path to each subagent" in instructions
    assert "bounded wait for every exact `response_path`" in instructions
    assert "The next `generate` call is the authoritative response validator" in instructions


def test_skill_documents_natural_pagination_exact_visual_bytes_and_runtime_safe_resume():
    instructions = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs/specs/render-assurance-fallbacks.md").read_text(encoding="utf-8")
    for phrase in (
        "natural content-driven pagination",
        "exact DOCX, PDF, and page-image hashes",
        "resolve_python_runtime",
        "cross-process UTC deadline",
    ):
        assert phrase in instructions
        assert phrase in architecture


def test_governed_renderer_authorities_require_host_office_and_only_pdfium():
    authority_paths = (
        ROOT / "CONTEXT.md",
        ROOT / "README.md",
        ROOT / "SKILL.md",
        ROOT / "docs/adr/0009-renderer-portable-word-targeted-docx.md",
        ROOT / "docs/adr/0018-own-render-assurance-capabilities.md",
        ROOT / "docs/renderer-preflight.md",
        ROOT / "docs/specs/clinical-document-generation-quality.md",
        ROOT / "docs/specs/clinical-document-generation-v2-rebuild.md",
        ROOT / "docs/specs/render-assurance-fallbacks.md",
    )
    authority = "\n".join(path.read_text(encoding="utf-8") for path in authority_paths)
    for stale_contract in (
        "Pages, then",
        "release-local verified LibreOffice",
        "release-local LibreOffice fallback",
        "without making the host a prerequisite",
        "Poppler `pdftoppm`",
        "MuPDF `mutool`",
        "optional PyMuPDF",
        "only renderer fallback location",
        "verified local fallbacks",
        "smoke-test its fallback stack",
    ):
        assert stale_contract not in authority

    context = (ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    assert "**Host Office Renderer**:" in context
    assert "**Release-Owned Page Renderer**:" in context
    assert "Microsoft Word or LibreOffice" in context
    assert "single manifest-bound `pypdfium2`" in context

    quality = (ROOT / "scripts/quality.py").read_text(encoding="utf-8")
    workflow = (ROOT / "scripts/workflow.py").read_text(encoding="utf-8")
    assert 'PAGE_RENDERER_BACKENDS = ("pypdfium2",)' in quality
    assert '"kind": "pypdfium2"' in workflow
    assert "runtime/**/soffice" not in quality
    assert "runtime/**/program/soffice" not in quality
    assert "provision_fallback_stack" not in workflow
    assert "fallback_pages" not in workflow
    rasterize_contract = quality[
        quality.index("def rasterize_pdf("):quality.index("\ndef renderers(")
    ]
    for stale_interface in ("every backend", "environment"):
        assert stale_interface not in rasterize_contract
    assert "timeout_seconds" in rasterize_contract
    assert "subprocess.Popen" in rasterize_contract
    assert "--internal-pdfium-worker" in workflow
