import pytest

from app.extraction import AmendmentPayload, ExtractionError, extract_amendment

VALID_JSON = '{"customer_name": "Smith", "panel": {"max_amperage": 200}, "breakers": [{"amps": 20, "poles": 1, "quantity": 3}]}'


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeModel:
    def __init__(self, text=None, error=None):
        self.text, self.error = text, error

    def generate_content(self, prompt, generation_config=None):
        if self.error:
            raise self.error
        return FakeResponse(self.text)


def factory_for(models):
    calls = []

    def factory(name):
        calls.append(name)
        return models[len(calls) - 1]

    factory.calls = calls
    return factory


def test_valid_extraction():
    factory = factory_for([FakeModel(text=VALID_JSON)])
    payload = extract_amendment("swap the panel", model_factory=factory, model_names=["m1"], max_output_tokens=512)
    assert payload.customer_name == "Smith"
    assert payload.panel.max_amperage == 200
    assert payload.breakers[0].quantity == 3


def test_falls_back_to_next_model_on_bad_json():
    factory = factory_for([FakeModel(text="not json"), FakeModel(text=VALID_JSON)])
    payload = extract_amendment("x", model_factory=factory, model_names=["m1", "m2"], max_output_tokens=512)
    assert payload.customer_name == "Smith"
    assert factory.calls == ["m1", "m2"]


def test_all_models_fail_raises():
    factory = factory_for([FakeModel(error=RuntimeError("quota")), FakeModel(text="{}")])
    with pytest.raises(ExtractionError):
        extract_amendment("x", model_factory=factory, model_names=["m1", "m2"], max_output_tokens=512)


def test_no_panel_is_fine():
    factory = factory_for([FakeModel(text='{"customer_name": "Jones", "breakers": []}')])
    payload = extract_amendment("x", model_factory=factory, model_names=["m1"], max_output_tokens=512)
    assert payload.panel is None
    assert isinstance(payload, AmendmentPayload)
