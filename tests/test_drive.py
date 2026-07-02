from app.drive import FOLDER_MIME, ensure_customer_folder, find_customer_folder, find_file_in_folder, upload_pdf


class FakeFiles:
    def __init__(self, listing):
        self.listing = listing
        self.created = None

    def list(self, q, fields, pageSize):
        self.q = q
        self._result = {"files": self.listing}
        return self

    def create(self, body, media_body=None, fields=""):
        self.created = {"body": body, "media": media_body}
        self._result = {"id": "new-id", "webViewLink": "https://drive.google.com/file/d/abc/view"}
        return self

    def execute(self):
        return self._result


class FakeDrive:
    def __init__(self, listing=()):
        self._files = FakeFiles(list(listing))

    def files(self):
        return self._files


def test_find_folder_builds_query_and_returns_id():
    drive = FakeDrive([{"id": "folder-smith", "name": "Smith"}])
    assert find_customer_folder(drive, "root123", "Smith") == "folder-smith"
    assert "'root123' in parents" in drive.files().q
    assert "mimeType = 'application/vnd.google-apps.folder'" in drive.files().q


def test_find_folder_escapes_quotes():
    drive = FakeDrive([])
    assert find_customer_folder(drive, "root123", "O'Brien") is None
    assert "O\\'Brien" in drive.files().q


def test_upload_pdf_returns_link_and_targets_folder():
    drive = FakeDrive()
    link = upload_pdf(drive, "folder-smith", "Smith_Amendment_20260701120000.pdf", b"%PDF-1.7 fake")
    assert link.startswith("https://drive.google.com/")
    assert drive.files().created["body"]["parents"] == ["folder-smith"]


def test_ensure_customer_folder_returns_existing():
    drive = FakeDrive([{"id": "folder-smith", "name": "Smith"}])
    assert ensure_customer_folder(drive, "root123", "Smith") == "folder-smith"
    assert drive.files().created is None


def test_ensure_customer_folder_creates_when_missing():
    drive = FakeDrive([])
    assert ensure_customer_folder(drive, "root123", "Smith") == "new-id"
    assert drive.files().created["body"]["mimeType"] == FOLDER_MIME
    assert drive.files().created["body"]["parents"] == ["root123"]


def test_find_file_in_folder_hit_and_miss():
    drive = FakeDrive([{"id": "f1", "name": "x.pdf", "webViewLink": "https://drive.google.com/file/d/f1/view"}])
    assert find_file_in_folder(drive, "folder", "x.pdf") == "https://drive.google.com/file/d/f1/view"
    assert find_file_in_folder(FakeDrive([]), "folder", "x.pdf") is None
