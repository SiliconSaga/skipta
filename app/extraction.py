"""Gemini structured-output extraction of the amendment payload. Anti-hallucination is downstream and deterministic (pricing match) — this layer only shapes the request."""
import logging

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("skipta.extraction")


class BreakerRequirement(BaseModel):
    amps: int = Field(..., description="Amperage of the breaker, e.g. 20, 30, 50")
    poles: int | None = Field(default=None, description="Number of poles, usually 1 or 2; None when the note doesn't say")
    quantity: int = Field(..., ge=1, description="Quantity requested")


class PanelRequirement(BaseModel):
    max_amperage: int = Field(..., description="Maximum amperage capacity of the panel, e.g. 100, 200")


class AmendmentPayload(BaseModel):
    customer_name: str = Field(..., min_length=1)
    intent: str = Field(default="new", pattern="^(new|amend)$")
    proposal_hint: str = ""
    panel: PanelRequirement | None = None
    breakers: list[BreakerRequirement] = Field(default_factory=list)


class ExtractionError(Exception):
    """Every configured model failed to produce a schema-valid payload."""


# Vertex structured-output schema (OpenAPI subset — hand-written; pydantic's json_schema
# emits $defs, which Gemini's response_schema does not accept).
AMENDMENT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "customer_name": {"type": "STRING", "description": "Surname or identifier of the customer"},
        "intent": {
            "type": "STRING",
            "enum": ["new", "amend"],
            "description": "amend when the note references an existing proposal/quote/document to modify; otherwise new",
        },
        "proposal_hint": {
            "type": "STRING",
            "description": "The document reference exactly as spoken, e.g. \"Rasmus' SPAN panel proposal\"; empty when none",
        },
        "panel": {
            "type": "OBJECT",
            "nullable": True,
            "properties": {"max_amperage": {"type": "INTEGER"}},
            "required": ["max_amperage"],
        },
        "breakers": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "amps": {"type": "INTEGER"},
                    "poles": {"type": "INTEGER"},
                    "quantity": {"type": "INTEGER"},
                },
                "required": ["amps", "quantity"],
            },
        },
    },
    "required": ["customer_name"],
}

PROMPT = (
    "You are extracting a field change-order for a residential electrical job from a technician's dictated note. "
    "Extract ONLY parts the note explicitly mentions — never invent parts, quantities, or a customer name. "
    "Set intent to 'amend' only when the note references an existing proposal, quote, or document to modify, and "
    "copy that reference into proposal_hint exactly as spoken; otherwise intent is 'new' and proposal_hint is empty. "
    "Omit poles when the note does not state them.\n\nNote:\n{voice_text}"
)


def extract_amendment(voice_text, *, model_factory, model_names, max_output_tokens):
    from vertexai.generative_models import GenerationConfig

    config = GenerationConfig(
        response_mime_type="application/json",
        response_schema=AMENDMENT_SCHEMA,
        max_output_tokens=max_output_tokens,
    )
    for name in model_names:
        try:
            response = model_factory(name).generate_content(PROMPT.format(voice_text=voice_text), generation_config=config)
            return AmendmentPayload.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            logger.warning("model %s returned schema-invalid output: %s", name, exc)
        except Exception as exc:  # API errors: quota, permission, model-not-found
            logger.warning("model %s failed: %s", name, exc)
    raise ExtractionError(f"all models failed for extraction: {model_names}")
