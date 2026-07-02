"""HTML → flattened PDF. WeasyPrint imports lazily: hosts without GTK libs can still run every non-PDF code path."""
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def render_amendment_html(record, items, *, crew_signature, customer_signature) -> str:
    return _env.get_template("amendment_pdf.html").render(
        record=record, items=items, crew_signature=crew_signature, customer_signature=customer_signature
    )


def render_pdf(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf()
