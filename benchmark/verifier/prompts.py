"""All judge prompts for the verifier benchmark, in one place."""

SYSTEM_PROMPT = (
    "You are an expert software engineer reviewing requirement-to-code verification reports. "
    "Follow instructions exactly. Always end with the required XML tags."
)

TASK = (
    "A verifier model checked whether the source code below implements the requirement. It split the "
    "requirement into claims, gave each claim a verdict (supported / not_supported / insufficient_evidence) "
    "with cited code lines and a rationale, and an overall status. Evaluate the verification report using the "
    "requirement and the code only."
)

RUBRICS = {
    "verdict": {
        "label": "Verdict Correctness", "short": "Verdict",
        "instruction": (
            "Are the claim verdicts and the overall status right for this code?\n"
            "1 - Wrong: says supported when the code does not do it, or rejects code that clearly does it.\n"
            "3 - Partly right: some claim verdicts are wrong.\n"
            "5 - Every verdict is right."),
    },
    "evidence": {
        "label": "Evidence Quality", "short": "Evidence",
        "instruction": (
            "Do the cited lines actually show the claimed behaviour (and is evidence given for supported claims)?\n"
            "1 - Citations missing, irrelevant or misquoted.\n3 - Some citations relevant, some weak.\n"
            "5 - Every supported claim cites the exact lines that implement it."),
    },
    "consistency": {
        "label": "Rationale Consistency", "short": "Consist.",
        "instruction": (
            "Does each rationale agree with its own verdict (no rationale that says the code does X while the "
            "verdict says not_supported, or the reverse)?\n"
            "1 - Rationales contradict their verdicts.\n3 - One contradiction or hedge.\n"
            "5 - Every rationale clearly justifies its verdict."),
    },
    "reasoning": {
        "label": "Code Reasoning", "short": "Reason.",
        "instruction": (
            "Does the reasoning refer to concrete code behaviour (functions, conditions, values) rather than "
            "names or docstrings alone?\n1 - Generic or name-based guesses.\n3 - Some concrete references.\n"
            "5 - Precise, behaviour-based reasoning about the shown code."),
    },
    "clarity": {
        "label": "Clarity", "short": "Clarity",
        "instruction": "Is the report easy to follow for a reviewer?\n1 - Confusing.\n3 - Mostly clear.\n5 - Very clear.",
    },
    "conciseness": {
        "label": "Conciseness", "short": "Concise.",
        "instruction": "Does it avoid padding and repetition?\n1 - Very verbose.\n3 - Some padding.\n5 - Tight.",
    },
}

PAIRWISE_CRITERIA = (
    "In order of importance: (1) correct verdicts for this code — supporting code that does not implement the "
    "requirement is the worst error, rejecting code that does is the next worst; (2) citations that show the "
    "behaviour; (3) rationales consistent with their verdicts and grounded in the code; (4) clarity and brevity."
)

MAX_CODE_CHARS = 6000


def render_context(case, context_text: str) -> str:
    code = context_text if len(context_text) <= MAX_CODE_CHARS else (
        context_text[:MAX_CODE_CHARS] + "\n... [code truncated for the judge]")
    return f"Requirement {case['requirement_id']}:\n{case['requirement_text']}\n\nSource code shown to the verifier:\n{code}"


def render_report(_item_id, result) -> str:
    lines = [f"Overall status: {result['status']}"]
    for i, c in enumerate(result.get("claims") or [], 1):
        lines.append(f"Claim {i}: {c.get('text')}\n  verdict: {c.get('verdict')}\n  rationale: {c.get('rationale')}")
        for e in c.get("evidence") or []:
            lines.append(f"  cites {e.get('component_id') or e.get('component')} lines {e.get('start_line')}-"
                         f"{e.get('end_line')}: {str(e.get('quote') or '')[:200]}")
    if result.get("summary"):
        lines.append(f"Summary: {result['summary']}")
    return "\n".join(lines)
