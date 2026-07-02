from app.gcs import blob_name, find_pdf, public_url, upload_pdf


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self.uploaded = None

    def exists(self):
        return self.name in self.store

    def upload_from_string(self, data, content_type=""):
        self.store[self.name] = {"data": data, "content_type": content_type}


class FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, name):
        return FakeBlob(self.store, name)


class FakeStorageClient:
    def __init__(self, store=None):
        self.store = store if store is not None else {}

    def bucket(self, name):
        self.bucket_name = name
        return FakeBucket(self.store)


def test_blob_name_prefixes_by_customer():
    assert blob_name("Smith", "Smith_Amendment_1.pdf") == "Smith/Smith_Amendment_1.pdf"
    assert blob_name("Van Der Berg", "x.pdf") == "Van_Der_Berg/x.pdf"


def test_public_url_shape():
    assert public_url("bkt", "Smith/x.pdf") == "https://storage.googleapis.com/bkt/Smith/x.pdf"


def test_find_pdf_miss_then_hit():
    client = FakeStorageClient()
    assert find_pdf(client, "bkt", "Smith/x.pdf") is None
    upload_pdf(client, "bkt", "Smith/x.pdf", b"%PDF-fake")
    assert find_pdf(client, "bkt", "Smith/x.pdf") == "https://storage.googleapis.com/bkt/Smith/x.pdf"


def test_upload_pdf_sets_content_type_and_returns_url():
    client = FakeStorageClient()
    url = upload_pdf(client, "bkt", "Smith/x.pdf", b"%PDF-fake")
    assert url == "https://storage.googleapis.com/bkt/Smith/x.pdf"
    assert client.store["Smith/x.pdf"]["content_type"] == "application/pdf"
