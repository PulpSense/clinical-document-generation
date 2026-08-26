import workflow


def _manifest():
    return {
        "status": "passed",
        "client_outputs": [
            {"path": "output/Protocol final.docx", "sha256": "03ac674216f3e15c761ee1a5e255f067953623c8b388b4459e13f978d7c846f4", "bytes": 4},
            {"path": "output/study data.xml", "sha256": "97a6d21df7c51e8289ac1a8c026aaac143e15aa1957f54f42e30d8f8a85c3a55", "bytes": 3},
        ],
    }


def test_desktop_reply_exposes_only_manifest_outputs_as_actionable_file_links(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    assert reply["type"] == "desktop_file_attachments"
    assert [item["filename"] for item in reply["attachments"]] == ["Protocol final.docx", "study data.xml"]
    assert reply["attachments"][0]["absolute_path"] == (tmp_path / "output/Protocol final.docx").as_posix()
    assert reply["attachments"][0]["link"].startswith("[Protocol final.docx](")
    assert reply["client_outputs_only"] is True


def test_desktop_confirmation_opens_every_file_and_accepts_transport_path_variants(tmp_path):
    files = {
        (tmp_path / "output/Protocol final.docx").as_posix(): b"1234",
        (tmp_path / "output/study data.xml").as_posix(): b"567",
    }
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    opened = []

    def opener(path):
        opened.append(path)
        return files[path]

    result = workflow.confirm_desktop_delivery(_manifest(), reply, opener)

    assert result["status"] == "confirmed"
    assert result["confirmed"] is True
    assert [item["filename"] for item in result["opened"]] == ["Protocol final.docx", "study data.xml"]
    assert opened == list(files)


def test_desktop_confirmation_retries_same_bytes_without_regenerating(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    calls = []

    def opener(path):
        calls.append(path)
        if len(calls) == 1:
            raise OSError("temporary transfer failure")
        return b"1234" if path.endswith("Protocol final.docx") else b"567"

    result = workflow.confirm_desktop_delivery(_manifest(), reply, opener, retries=1)

    assert result["status"] == "confirmed"
    assert result["opened"][0]["attempts"] == 2
    assert len(calls) == 3


def test_desktop_confirmation_blocks_mismatch_and_does_not_certify_quality(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)

    result = workflow.confirm_desktop_delivery(_manifest(), reply, lambda path: b"wrong")

    assert result["status"] == "blocked"
    assert result["confirmed"] is False
    assert result["findings"][0]["category"] == "delivery"


def test_desktop_confirmation_blocks_missing_attachment_without_opening_anything(tmp_path):
    reply = workflow.desktop_attachment_reply(_manifest(), run_dir=tmp_path)
    reply["attachments"].pop()
    calls = []

    result = workflow.confirm_desktop_delivery(_manifest(), reply, lambda path: calls.append(path))

    assert result["status"] == "blocked"
    assert calls == []
