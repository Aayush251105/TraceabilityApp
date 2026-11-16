"""All judge prompts for the SRS Agent extractor benchmark, in one place."""

import json

SYSTEM_PROMPT = (
    "You are an expert requirements engineer evaluating how well a software requirement was "
    "converted into a structured record. Follow instructions exactly. Always end with the required XML tags."
)

TASK = (
    "An extraction model read the requirement text below (taken verbatim from an SRS) and produced the "
    "structured record shown. Downstream, the record is used to search a Python codebase for the code that "
    "implements the requirement and to verify that code. Evaluate the record against the requirement text only."
)

RUBRICS = {
    "faithfulness": {
        "label": "Faithfulness (no invention)",
        "instruction": (
            "Does every field state only what the requirement says or directly implies?\n"
            "1 - Invents behaviours, actors, values or technologies, or contradicts the text.\n"
            "2 - Several unsupported additions or a changed meaning.\n"
            "3 - Mostly faithful; one or two unsupported details.\n"
            "4 - Faithful; at most a trivial over-interpretation.\n"
            "5 - Fully faithful; nothing added that the text does not support."),
    },
    "completeness": {
        "label": "Completeness",
        "instruction": (
            "Does the record capture every behaviour, condition, constraint, exact value and list item?\n"
            "1 - Misses most of the requirement.\n"
            "2 - Misses several important parts or values.\n"
            "3 - Captures the main behaviour; misses some conditions, values or list items.\n"
            "4 - Captures nearly everything; minor omission.\n"
            "5 - Captures every behaviour, condition, value and list item."),
    },
    "structure": {
        "label": "Field Structure",
        "instruction": (
            "Is information in the right fields (actors vs entities, conditions vs constraints vs error "
            "conditions, inputs/outputs, sub_requirements), and are type/subtype sensible?\n"
            "1 - Fields mostly misused or empty when the text has the information.\n"
            "3 - Reasonable, with several misplaced items.\n"
            "5 - Every item is in the correct field; type and subtype are right."),
    },
    "normalized_text": {
        "label": "Normalized Text",
        "instruction": (
            "Is normalized_text a clear, precise, self-contained restatement that keeps the meaning?\n"
            "1 - Empty, wrong or meaningless.\n3 - Understandable but vague or lossy.\n"
            "5 - Precise, complete and unambiguous."),
    },
    "retrieval": {
        "label": "Code-Search Usefulness",
        "instruction": (
            "Would title, retrieval_text, actions, entities, domain_terms and synonyms help find the code that "
            "implements this requirement (specific nouns and verbs a developer would use in identifiers)?\n"
            "1 - Generic or misleading terms.\n3 - Some useful terms mixed with filler.\n"
            "5 - Specific, varied, well-chosen search terms."),
    },
    "conciseness": {
        "label": "Conciseness",
        "instruction": (
            "Does the record avoid padding, repetition and duplicated items across fields?\n"
            "1 - Very repetitive or padded.\n3 - Some redundancy.\n5 - Tight; every item earns its place."),
    },
}

PAIRWISE_CRITERIA = (
    "In order of importance: (1) faithful to the requirement text, with nothing invented; "
    "(2) complete: every behaviour, condition, value and list item captured; "
    "(3) information placed in the correct fields; "
    "(4) useful search terms for finding the implementing code; (5) concise."
)

SHOWN_FIELDS = ("title", "type", "subtype", "normalized_text", "actor", "actions", "entities", "inputs",
                "outputs", "preconditions", "postconditions", "conditions", "constraints", "error_conditions",
                "sub_requirements", "domain_terms", "synonyms", "retrieval_text")


def render_record(_item_id, req) -> str:
    return "```json\n" + json.dumps({k: req.get(k) for k in SHOWN_FIELDS}, indent=1, ensure_ascii=False) + "\n```"


def render_context(raw_text: str, section: str | None) -> str:
    head = f"(SRS section: {section})\n" if section else ""
    return f"{head}```text\n{raw_text}\n```"
