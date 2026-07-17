"""Parses free-text delivery notes into structured JSON via the LLM."""


async def parse_delivery_note(raw_text: str) -> dict:
    """Extract structured fields (e.g. access instructions, preferred time) from free text."""
    raise NotImplementedError
