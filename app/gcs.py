"""Signed-PDF archive in GCS, keyed by customer prefix. Consumer-account service accounts have zero Drive storage quota (uploads are rejected outright), so the flattened PDFs live in a public-read bucket instead; the Drive folder remains the human-side SoW archive."""


def blob_name(customer_name: str, filename: str) -> str:
    return f"{customer_name.replace(' ', '_')}/{filename}"


def public_url(bucket: str, name: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{name}"


def find_pdf(storage_client, bucket: str, name: str):
    if storage_client.bucket(bucket).blob(name).exists():
        return public_url(bucket, name)
    return None


def upload_pdf(storage_client, bucket: str, name: str, pdf_bytes: bytes) -> str:
    storage_client.bucket(bucket).blob(name).upload_from_string(pdf_bytes, content_type="application/pdf")
    return public_url(bucket, name)
