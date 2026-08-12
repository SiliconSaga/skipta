import pytest

from app.proposals import Candidate, ProposalParseError, ProposalTooLarge, fetch_pdf, parse_proposal, search_proposals

FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"


class FakeDrive:
    """Routes files.list by query content; serves get/export/media from a dict of file records."""

    def __init__(self, folders=(), files_by_folder=None, records=None):
        self.folders = list(folders)  # [{"id","name"}]
        self.files_by_folder = files_by_folder or {}  # folder_id -> [{"id","name","mimeType"}]
        self.records = records or {}  # file_id -> {"name","mimeType","size","content": bytes}

    def files(self):
        return self

    def list(self, q, fields, pageSize):
        if f"mimeType = '{FOLDER_MIME}'" in q:
            self._result = {"files": self.folders}
        else:
            folder_id = q.split("'")[1]
            children = self.files_by_folder.get(folder_id, [])
            if "mimeType = 'application/pdf'" in q:  # honor the proposal-type filter like real Drive
                children = [c for c in children if c["mimeType"] in ("application/pdf", DOC_MIME)]
            self._result = {"files": children}
        return self

    def get(self, fileId, fields=""):
        rec = self.records[fileId]
        self._result = {"name": rec["name"], "mimeType": rec["mimeType"], "size": str(rec.get("size", len(rec["content"])))}
        return self

    def get_media(self, fileId):
        self._result = self.records[fileId]["content"]
        return self

    def export_media(self, fileId, mimeType):
        assert mimeType == "application/pdf"
        self._result = b"%PDF-exported-" + self.records[fileId]["content"]
        return self

    def execute(self):
        return self._result


def make_drive():
    return FakeDrive(
        folders=[{"id": "f-rasmus", "name": "Rasmus"}, {"id": "f-smith", "name": "Smith"}],
        files_by_folder={
            "f-rasmus": [
                {"id": "p1", "name": "span-panel-proposal.pdf", "mimeType": "application/pdf"},
                {"id": "p2", "name": "old-invoice.pdf", "mimeType": "application/pdf"},
                {"id": "img1", "name": "span-panel-photo.jpg", "mimeType": "image/jpeg"},
            ],
            "f-smith": [{"id": "p3", "name": "span-quote.pdf", "mimeType": "application/pdf"}],
        },
        records={
            "p1": {"name": "span-panel-proposal.pdf", "mimeType": "application/pdf", "content": b"%PDF-real"},
            "g1": {"name": "quote-doc", "mimeType": DOC_MIME, "content": b"gdoc-bytes"},
            "big": {"name": "huge.pdf", "mimeType": "application/pdf", "size": 11 * 1024 * 1024, "content": b"x"},
        },
    )


def test_search_prefers_customer_folder_and_hint_tokens():
    got = search_proposals(make_drive(), "root", "Rasmus", "SPAN panel proposal")
    assert [c.file_id for c in got][:2] == ["p1", "p2"]  # Rasmus folder first, hint-matching file on top
    assert got[0].folder == "Rasmus"
    assert all(isinstance(c, Candidate) for c in got)


def test_search_no_customer_folder_still_searches_all():
    got = search_proposals(make_drive(), "root", "Jones", "span quote")
    assert any(c.file_id == "p3" for c in got)


def test_search_offers_only_proposal_types():
    got = search_proposals(make_drive(), "root", "Rasmus", "span panel")
    assert all(c.file_id != "img1" for c in got)  # the photo never reaches the pick-list


def test_fetch_pdf_plain():
    assert fetch_pdf(make_drive(), "p1") == b"%PDF-real"


def test_fetch_pdf_exports_google_doc():
    assert fetch_pdf(make_drive(), "g1").startswith(b"%PDF-exported-")


def test_fetch_pdf_too_large():
    with pytest.raises(ProposalTooLarge):
        fetch_pdf(make_drive(), "big")


def test_fetch_pdf_doc_without_size_metadata_capped_after_download():
    drive = make_drive()
    drive.records["gbig"] = {"name": "huge-doc", "mimeType": DOC_MIME, "size": "", "content": b"x" * (11 * 1024 * 1024)}
    with pytest.raises(ProposalTooLarge):
        fetch_pdf(drive, "gbig")


FACTS_JSON = '{"proposal_title": "SPAN Panel Upgrade", "original_total": 12345.67, "customer_email": "r@x.com", "customer_address": "1 Main St"}'


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeParseModel:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error
        self.contents = None

    def generate_content(self, contents, generation_config=None):
        if self.error:
            raise self.error
        self.contents = contents
        return FakeResponse(self.text)


def parse_factory(models):
    calls = []

    def factory(name):
        calls.append(name)
        return models[len(calls) - 1]

    factory.calls = calls
    return factory


def test_parse_proposal_returns_facts_and_sends_pdf_part():
    model = FakeParseModel(text=FACTS_JSON)
    facts = parse_proposal(b"%PDF-real", model_factory=parse_factory([model]), model_names=["m1"], max_output_tokens=512)
    assert facts.original_total == 12345.67 and facts.customer_email == "r@x.com"
    assert isinstance(model.contents, list) and len(model.contents) == 2  # [pdf Part, prompt]


def test_parse_missing_total_is_none():
    model = FakeParseModel(text='{"proposal_title": "T", "customer_email": "", "customer_address": ""}')
    facts = parse_proposal(b"%PDF", model_factory=parse_factory([model]), model_names=["m1"], max_output_tokens=512)
    assert facts.original_total is None


def test_parse_all_models_fail_raises():
    factory = parse_factory([FakeParseModel(text="junk"), FakeParseModel(error=RuntimeError("quota"))])
    with pytest.raises(ProposalParseError):
        parse_proposal(b"%PDF", model_factory=factory, model_names=["m1", "m2"], max_output_tokens=512)
