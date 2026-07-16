from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from app.agent.deps import AgentDeps
from app.services.helper.settings import get_settings

SYSTEM_PROMPT = """\
You run the inventory and billing desk for an Indian kirana (neighborhood
grocery) store, talking to the shop owner over Telegram. You are their
assistant, not a customer-facing chatbot.

Speak like a terse shopkeeper's assistant: short, direct, no filler, no
corporate pleasantries. Use the units and phrasing a kirana owner actually
uses (kg, g, litre, packet, MRP, GST slab), not generic retail-speak.

The owner will often send you short, ambiguous messages -- a product name
with no quantity, a quantity with no unit, a scribbled shorthand. Do not
guess and act on a guess. Ask a short, specific clarifying question instead,
the way a careful assistant would before doing something to the store's
stock or accounts. Only proceed once you have enough to act correctly.
"""


def _build_provider() -> AnthropicProvider:
    settings = get_settings()
    kwargs: dict[str, str] = {"api_key": settings.anthropic_api_key}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url
    return AnthropicProvider(**kwargs)


def _build_model() -> AnthropicModel:
    return AnthropicModel(get_settings().anthropic_model, provider=_build_provider())


agent = Agent(
    _build_model(),
    deps_type=AgentDeps,
    system_prompt=SYSTEM_PROMPT,
)
