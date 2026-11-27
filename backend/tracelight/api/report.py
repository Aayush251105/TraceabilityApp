"""
Traceability report: one self-contained, print-ready HTML document per run.

`render_report(data)` is a pure function (no database), so it is easy to test.
The API route builds `data` from the results reader:

    {"run": {...}, "summary": {...}, "requirements": [detail, ...],
     "code": {"files": [...], "components": N, "traced": M}, "generated_at": datetime}

Sections
  1. Summary: verdict counts, a distribution bar, code coverage, one plain sentence
  2. Requirements at a glance: one row per requirement
  3. Needs attention: requirements that are not (fully) supported, with the reason
  4. Requirement details: text, verdict, claims with cited code, linked code
  5. Code coverage by file
  6. About this report: what the verdicts mean, models and versions

The page is styled for A4 print (Save as PDF from the browser) and reads well on
screen. Everything is escaped; the only script is the Print button.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

# verdict -> (label, glyph, css class). Glyph + label, never colour alone.
VERDICT_META = {
    "supported": ("Supported", "✓", "ok"),
    "partially_supported": ("Partially supported", "◐", "part"),
    "not_supported_by_candidate": ("Not supported", "✕", "bad"),
    "not_found": ("Not found", "○", "nf"),
    "insufficient_evidence": ("Insufficient evidence", "?", "ins"),
    "needs_review": ("Needs review", "!", "rev"),
    "pending": ("Pending", "·", "nf"),
}
ORDER = ["supported", "partially_supported", "not_supported_by_candidate", "not_found",
         "insufficient_evidence", "needs_review", "pending"]
ATTENTION = ("partially_supported", "not_supported_by_candidate", "not_found", "insufficient_evidence",
             "needs_review")
CLAIM_META = {"supported": ("Supported", "✓", "ok"), "not_supported": ("Not supported", "✕", "bad"),
              "insufficient_evidence": ("Insufficient evidence", "?", "ins")}
MODEL_ROLES = (("docagent", "Docstrings (DocAgent)"), ("srs", "Requirement extraction"),
               ("judge", "Candidate judge"), ("verifier", "Verifier"))


def e(value: Any) -> str:
    return escape("" if value is None else str(value))


def short(component_id: str) -> str:
    """Last two dotted parts: 'lib.models.loan.Loan.renew' -> 'Loan.renew'."""
    parts = (component_id or "").split(".")
    return ".".join(parts[-2:]) if len(parts) > 1 else component_id or ""


def pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "—"


def chip(status: Optional[str], meta=VERDICT_META) -> str:
    label, glyph, cls = meta.get(status or "pending", (status or "—", "·", "nf"))
    return f'<span class="chip {cls}"><span class="g" aria-hidden="true">{glyph}</span>{e(label)}</span>'


def first_sentence(text: str, limit: int = 220) -> str:
    text = " ".join((text or "").split())
    for stop in (". ", "! ", "? "):
        i = text.find(stop)
        if 0 < i < limit:
            return text[: i + 1]
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fmt_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y, %H:%M")
        except ValueError:
            return value
    return "—"


def codebase_label(run: Dict[str, Any]) -> str:
    """A Git URL is shown in full; a local folder or ZIP only by its name (no local paths in a shared report)."""
    kind, ref = run.get("source_kind"), run.get("source_ref") or ""
    sha = (run.get("commit_sha") or "")[:10]
    if kind == "git":
        out = ref + (f" @ {run['git_ref']}" if run.get("git_ref") else "")
        return out + (f" (commit {sha})" if sha else "")
    name = PurePosixPath(ref.replace("\\", "/")).name or ref
    return f"{name} ({'ZIP upload' if kind == 'zip' else 'local folder'})" + (f", commit {sha}" if sha else "")


def verdict_status(req: Dict[str, Any]) -> str:
    return (req.get("verdict") or {}).get("status") or "pending"


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _header(run: Dict[str, Any], generated_at: Any) -> str:
    models = ((run.get("settings") or {}).get("models") or {})
    model_rows = "".join(f"<tr><th>{e(label)}</th><td><code>{e(models[k])}</code></td></tr>"
                         for k, label in MODEL_ROLES if models.get(k))
    return f"""
<header class="cover">
  <div class="kicker">Tracelight · Requirements traceability report</div>
  <h1>{e(run.get('name') or f"Run #{run.get('run_id')}")}</h1>
  <table class="meta">
    <tr><th>Requirements document</th><td>{e(run.get('srs_filename'))}</td></tr>
    <tr><th>Codebase</th><td>{e(codebase_label(run))}</td></tr>
    <tr><th>Run</th><td>#{e(run.get('run_id'))}, started {e(fmt_date(run.get('created_at')))}, finished {e(fmt_date(run.get('finished_at')))}</td></tr>
    <tr><th>Report generated</th><td>{e(fmt_date(generated_at))}</td></tr>
    {model_rows}
  </table>
</header>"""


def _summary(summary: Dict[str, Any], reqs: List[Dict[str, Any]]) -> str:
    n = len(reqs)
    counts = {k: 0 for k in ORDER}
    for r in reqs:
        counts[verdict_status(r) if verdict_status(r) in counts else "pending"] += 1
    sup, part = counts["supported"], counts["partially_supported"]
    missing = counts["not_supported_by_candidate"] + counts["not_found"]
    unsure = counts["insufficient_evidence"] + counts["needs_review"] + counts["pending"]
    comps = summary.get("components") or {}
    total_c, cited = comps.get("total") or 0, comps.get("cited_as_evidence") or 0
    overridden = summary.get("overridden") or 0

    sentence = (f"Of the {n} requirements, {sup} ({pct(sup, n)}) are supported by the code, "
                f"{part} ({pct(part, n)}) are partially supported and {missing} ({pct(missing, n)}) "
                f"could not be matched to code that implements them.")
    if unsure:
        sentence += f" {unsure} could not be decided and need a person to look at them."
    if overridden:
        sentence += f" A reviewer changed or confirmed {overridden} verdict{'s' if overridden != 1 else ''}."

    tiles = [("Requirements", n, ""), ("Supported", sup, "ok"), ("Partially supported", part, "part"),
             ("Not supported / not found", missing, "bad"), ("Undecided", unsure, "ins"),
             ("Reviewer verdicts", overridden, "")]
    tiles_html = "".join(f'<div class="tile {cls}"><div class="num">{v}</div><div class="lbl">{e(l)}</div></div>'
                         for l, v, cls in tiles)
    bar = "".join(f'<span class="seg {VERDICT_META[k][2]}" style="width:{100 * counts[k] / n:.2f}%" '
                  f'title="{e(VERDICT_META[k][0])}: {counts[k]}"></span>'
                  for k in ORDER if counts[k]) if n else ""
    legend = "".join(f'<span class="leg">{chip(k)} {counts[k]}</span>' for k in ORDER if counts[k])
    coverage = (f"<p><strong>Code coverage:</strong> {cited} of {total_c} functions and classes "
                f"({pct(cited, total_c)}) are cited as evidence for at least one supported requirement.</p>"
                if total_c else "")
    return f"""
<section>
  <h2>1. Summary</h2>
  <p class="lead">{e(sentence)}</p>
  <div class="tiles">{tiles_html}</div>
  <div class="bar" role="img" aria-label="Verdict distribution">{bar}</div>
  <div class="legend">{legend}</div>
  {coverage}
</section>"""


def _direct(req: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [c for c in req.get("components") or [] if c.get("role") == "direct"]


def _overview(reqs: List[Dict[str, Any]]) -> str:
    rows = []
    for d in reqs:
        r = d["requirement"]
        claims = d.get("claims") or []
        sup = sum(c.get("verdict") == "supported" for c in claims)
        code = ", ".join(f"<code>{e(short(c['component_id']))}</code>" for c in _direct(d)) or '<span class="muted">—</span>'
        rows.append(f"<tr><td class='id'><a href='#req-{e(r['requirement_id'])}'>{e(r['requirement_id'])}</a></td>"
                    f"<td>{e(r.get('title') or first_sentence(r.get('raw_text') or '', 90))}</td>"
                    f"<td class='nowrap'>{chip(verdict_status(d))}</td>"
                    f"<td class='num'>{f'{sup}/{len(claims)}' if claims else '—'}</td><td>{code}</td></tr>")
    return f"""
<section>
  <h2>2. Requirements at a glance</h2>
  <table class="grid">
    <thead><tr><th>ID</th><th>Requirement</th><th>Verdict</th><th>Claims</th><th>Implemented by</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>"""


def _reason(d: Dict[str, Any]) -> str:
    v = d.get("verdict") or {}
    if v.get("source") == "human":
        return "Set by a reviewer" + (f": {v['note']}" if v.get("note") else ".")
    if verdict_status(d) == "not_found":
        return "No code was found that matches this requirement."
    rationale = ((d.get("verification") or {}).get("rationale") or "").replace("[requirement text looks incomplete: "
                                                                               "it introduces a list that is missing] ", "")
    failed = [c for c in d.get("claims") or [] if c.get("verdict") != "supported"]
    if failed and failed[0].get("rationale"):
        return f"“{first_sentence(failed[0].get('text') or '', 120)}”: {first_sentence(failed[0]['rationale'])}"
    return first_sentence(rationale) or "—"


def _attention(reqs: List[Dict[str, Any]]) -> str:
    items = [d for d in reqs if verdict_status(d) in ATTENTION]
    if not items:
        return """
<section>
  <h2>3. Needs attention</h2>
  <p>Every requirement is supported by the code. Nothing needs attention.</p>
</section>"""
    items.sort(key=lambda d: ATTENTION.index(verdict_status(d)))
    rows = "".join(f"<tr><td class='id'><a href='#req-{e(d['requirement']['requirement_id'])}'>"
                   f"{e(d['requirement']['requirement_id'])}</a></td>"
                   f"<td class='nowrap'>{chip(verdict_status(d))}</td><td>{e(_reason(d))}</td></tr>" for d in items)
    return f"""
<section>
  <h2>3. Needs attention</h2>
  <p>These {len(items)} requirements are not fully supported. Each is either a gap in the code, a requirement the
  tool could not match, or a verdict a person should check.</p>
  <table class="grid">
    <thead><tr><th>ID</th><th>Verdict</th><th>Why</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _evidence(ev: Dict[str, Any]) -> str:
    where = f"{e(ev.get('path'))}:{e(ev.get('start_line'))}–{e(ev.get('end_line'))}"
    quote = f"<pre>{e(ev['quote'])}</pre>" if ev.get("quote") else ""
    return f'<div class="ev"><span class="where">{where}</span> <code>{e(short(ev.get("component_id") or ""))}</code>{quote}</div>'


def _detail(d: Dict[str, Any]) -> str:
    r = d["requirement"]
    v = d.get("verdict") or {}
    ver = d.get("verification") or {}
    source = ""
    if v.get("source") == "human":
        source = (f"Verdict set by a reviewer (the verifier said: {e(VERDICT_META.get(v.get('machine') or '', ('—',))[0])})"
                  + (f'. Note: “{e(v["note"])}”' if v.get("note") else "."))
    elif ver.get("model"):
        source = f"Verdict by the verifier model <code>{e(ver['model'])}</code>."
    extra = ""
    for key, label in (("sub_requirements", "Sub-requirements"), ("conditions", "Conditions"),
                       ("error_conditions", "Error conditions")):
        values = [x for x in r.get(key) or [] if x]
        if values:
            extra += f"<div class='sub'><strong>{label}:</strong><ul>{''.join(f'<li>{e(x)}</li>' for x in values)}</ul></div>"

    claims = d.get("claims") or []
    claim_rows = "".join(
        f"<tr><td class='num'>{i}</td><td>{e(c.get('text'))}"
        f"{'<div class=muted>' + e(first_sentence(c.get('rationale') or '', 260)) + '</div>' if c.get('rationale') else ''}</td>"
        f"<td class='nowrap'>{chip(c.get('verdict'), CLAIM_META)}</td>"
        f"<td>{''.join(_evidence(x) for x in c.get('evidence') or []) or '<span class=muted>—</span>'}</td></tr>"
        for i, c in enumerate(claims, start=1))
    claims_html = (f"<table class='grid claims'><thead><tr><th>#</th><th>Claim</th><th>Verdict</th><th>Cited code</th>"
                   f"</tr></thead><tbody>{claim_rows}</tbody></table>") if claims else ""

    comps = d.get("components") or []
    code_rows = "".join(
        f"<tr><td><code>{e(short(c['component_id']))}</code></td><td>{e((c.get('role') or '').capitalize())}</td>"
        f"<td class='mono'>{e(c.get('path'))}:{e(c.get('start_line'))}–{e(c.get('end_line'))}</td></tr>"
        for c in sorted(comps, key=lambda c: c.get("role") != "direct"))
    code_html = (f"<table class='grid compact'><thead><tr><th>Linked code</th><th>Role</th><th>Location</th></tr>"
                 f"</thead><tbody>{code_rows}</tbody></table>") if comps else "<p class='muted'>No code was linked to this requirement.</p>"
    summary = first_sentence(ver.get("rationale") or "", 400) if v.get("source") != "human" else ""
    return f"""
<article class="req" id="req-{e(r['requirement_id'])}">
  <div class="req-head"><span class="rid">{e(r['requirement_id'])}</span><span class="rtitle">{e(r.get('title'))}</span>{chip(verdict_status(d))}</div>
  <blockquote>{e(r.get('raw_text'))}</blockquote>
  {extra}
  {f'<p class="src">{source}</p>' if source else ''}
  {f'<p>{e(summary)}</p>' if summary else ''}
  {claims_html}
  {code_html}
</article>"""


def _details(reqs: List[Dict[str, Any]]) -> str:
    return f"""
<section class="break">
  <h2>4. Requirement details</h2>
  <p class="muted">For each requirement: its text, the verdict, the claims it was split into with the code each
  claim cites, and the code linked to it. Cited lines are quoted from the source exactly.</p>
  {''.join(_detail(d) for d in reqs)}
</section>"""


def _coverage(code: Optional[Dict[str, Any]]) -> str:
    files = [f for f in (code or {}).get("files") or [] if f.get("total")]
    if not files:
        return ""
    files.sort(key=lambda f: f["path"])
    rows = "".join(f"<tr><td class='mono'>{e(f['path'])}</td><td class='num'>{f['total']}</td>"
                   f"<td class='num'>{f['traced']}</td><td class='num'>{pct(f['traced'], f['total'])}</td></tr>"
                   for f in files)
    return f"""
<section class="break">
  <h2>5. Code coverage by file</h2>
  <p class="muted">A function or class counts as traced when the mapping links it to at least one requirement.
  Untraced code may be helper code, or functionality that the specification does not describe.</p>
  <table class="grid compact">
    <thead><tr><th>File</th><th>Components</th><th>Traced</th><th>Share</th></tr></thead>
    <tbody>{rows}</tbody>
    <tfoot><tr><th>Total</th><th class="num">{code.get('components', 0)}</th><th class="num">{code.get('traced', 0)}</th>
    <th class="num">{pct(code.get('traced', 0), code.get('components', 0))}</th></tr></tfoot>
  </table>
</section>"""


def _about(reqs: Iterable[Dict[str, Any]]) -> str:
    prompts = sorted({(d.get("verification") or {}).get("prompt_version") for d in reqs} - {None})
    return f"""
<section>
  <h2>6. About this report</h2>
  <p>Tracelight extracted the requirements from the document, searched the code for each one, and asked a local
  language model to check the linked code claim by claim. A claim counts as supported only when the model cites
  lines whose text matches the source. Docstrings are never accepted as evidence.</p>
  <table class="grid compact">
    <tbody>
      <tr><td>{chip('supported')}</td><td>Every claim of the requirement is supported by cited code.</td></tr>
      <tr><td>{chip('partially_supported')}</td><td>Some claims are supported; others are missing or differ.</td></tr>
      <tr><td>{chip('not_supported_by_candidate')}</td><td>Code was found, but it does not do what the requirement says.</td></tr>
      <tr><td>{chip('not_found')}</td><td>No code matching the requirement was found.</td></tr>
      <tr><td>{chip('insufficient_evidence')}</td><td>The code shown was not enough to decide.</td></tr>
      <tr><td>{chip('needs_review')}</td><td>The verifier failed on this requirement; a person should check it.</td></tr>
    </tbody>
  </table>
  <p class="muted">Verdicts are produced automatically and can be wrong, most often by rejecting code that does
  implement a requirement. Treat them as a starting point for review, not as a certificate.
  {f"Verifier prompt: {e(', '.join(prompts))}." if prompts else ""}</p>
</section>"""


CSS = """
:root { --fg:#1d1f23; --fg2:#4a4f57; --fg3:#7a808a; --line:#d9dce1; --sub:#f5f6f8; --accent:#2f5fb3;
  --ok:#1f7a45; --ok-bg:#e5f3ea; --part:#9a6a00; --part-bg:#fbf1dc; --bad:#b3261e; --bad-bg:#fbe6e4;
  --nf:#5d6470; --nf-bg:#eceef1; --ins:#6b4fa3; --ins-bg:#efeaf8; --rev:#b35c00; --rev-bg:#fcebdc; }
* { box-sizing: border-box; }
html { background: #e9ebee; }
body { margin: 0 auto; max-width: 210mm; background: #fff; color: var(--fg); padding: 18mm 16mm;
  font: 10.5pt/1.5 "Segoe UI", "Helvetica Neue", Arial, sans-serif; }
h1 { font-size: 22pt; margin: 4px 0 14px; letter-spacing: -0.01em; }
h2 { font-size: 14pt; margin: 26px 0 10px; padding-bottom: 4px; border-bottom: 2px solid var(--fg); }
p { margin: 6px 0 10px; }
a { color: var(--accent); text-decoration: none; }
code, .mono, pre { font-family: "Cascadia Mono", Consolas, "SFMono-Regular", Menlo, monospace; font-size: 9pt; }
pre { margin: 3px 0 0; padding: 4px 6px; background: var(--sub); border-left: 2px solid var(--line);
  white-space: pre-wrap; word-break: break-word; }
.kicker { color: var(--fg3); font-size: 9pt; text-transform: uppercase; letter-spacing: .08em; }
.cover { border-bottom: 1px solid var(--line); padding-bottom: 12px; }
.meta th { text-align: left; color: var(--fg3); font-weight: 500; padding: 2px 16px 2px 0; vertical-align: top; white-space: nowrap; }
.meta td { padding: 2px 0; }
.lead { font-size: 11.5pt; }
.muted { color: var(--fg3); }
.tiles { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; margin: 12px 0; }
.tile { border: 1px solid var(--line); border-radius: 6px; padding: 8px; }
.tile .num { font-size: 18pt; font-weight: 600; line-height: 1.1; }
.tile .lbl { font-size: 8.5pt; color: var(--fg2); }
.tile.ok .num { color: var(--ok); } .tile.part .num { color: var(--part); }
.tile.bad .num { color: var(--bad); } .tile.ins .num { color: var(--ins); }
.bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden; background: var(--sub); margin: 8px 0 6px; }
.seg.ok { background: var(--ok); } .seg.part { background: var(--part); } .seg.bad { background: var(--bad); }
.seg.nf { background: var(--nf); } .seg.ins { background: var(--ins); } .seg.rev { background: var(--rev); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 9pt; margin-bottom: 8px; }
.chip { display: inline-flex; align-items: center; gap: 4px; border-radius: 10px; padding: 0 8px; font-size: 8.5pt;
  font-weight: 500; white-space: nowrap; line-height: 18px; }
.chip .g { font-weight: 700; }
.chip.ok { color: var(--ok); background: var(--ok-bg); } .chip.part { color: var(--part); background: var(--part-bg); }
.chip.bad { color: var(--bad); background: var(--bad-bg); } .chip.nf { color: var(--nf); background: var(--nf-bg); }
.chip.ins { color: var(--ins); background: var(--ins-bg); } .chip.rev { color: var(--rev); background: var(--rev-bg); }
table.grid { width: 100%; border-collapse: collapse; margin: 6px 0 12px; }
table.grid th, table.grid td { border-bottom: 1px solid var(--line); padding: 5px 6px; text-align: left; vertical-align: top; }
table.grid thead th { background: var(--sub); font-size: 9pt; color: var(--fg2); font-weight: 600; }
table.grid tfoot th { border-top: 2px solid var(--line); }
table.compact td, table.compact th { padding: 3px 6px; }
.id, .rid { font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; white-space: nowrap; }
.num { text-align: right; white-space: nowrap; } .nowrap { white-space: nowrap; }
.req { border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; margin: 10px 0 14px; }
.req-head { display: flex; align-items: baseline; gap: 10px; }
.req-head .rid { font-weight: 600; } .req-head .rtitle { flex: 1; font-weight: 600; }
blockquote { margin: 8px 0; padding: 6px 10px; background: var(--sub); border-left: 3px solid var(--fg3); }
.sub ul { margin: 2px 0 6px 18px; padding: 0; } .src { color: var(--fg2); font-size: 9.5pt; }
.claims td:first-child { width: 22px; } .claims td:nth-child(2) { width: 50%; }
.ev + .ev { margin-top: 6px; } .ev .where { font-family: Consolas, monospace; font-size: 8.5pt; color: var(--fg2); }
.toolbar { position: sticky; top: 0; display: flex; gap: 8px; justify-content: flex-end; margin: -10mm 0 6mm; }
.toolbar button { font: inherit; padding: 6px 12px; border-radius: 6px; border: 1px solid var(--line); background: #fff; cursor: pointer; }
.toolbar button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid var(--line); color: var(--fg3); font-size: 8.5pt; }
@page { size: A4; margin: 14mm 12mm 16mm; }
@media print {
  html { background: #fff; }
  body { max-width: none; padding: 0; font-size: 9.5pt; }
  .toolbar { display: none; }
  .break { break-before: page; }
  .req, tr, .tile { break-inside: avoid; }
  h2 { break-after: avoid; }
  a { color: inherit; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}
@media (max-width: 720px) { body { padding: 16px; } .tiles { grid-template-columns: repeat(3, 1fr); } }
"""


def render_report(data: Dict[str, Any]) -> str:
    run = data.get("run") or {}
    reqs = data.get("requirements") or []
    title = f"Traceability report — {run.get('name') or 'Run #' + str(run.get('run_id'))}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="toolbar"><button class="primary" onclick="window.print()">Print / Save as PDF</button></div>
{_header(run, data.get('generated_at'))}
{_summary(data.get('summary') or {}, reqs)}
{_overview(reqs)}
{_attention(reqs)}
{_details(reqs)}
{_coverage(data.get('code'))}
{_about(reqs)}
<footer>Generated by Tracelight on {e(fmt_date(data.get('generated_at')))} · Run #{e(run.get('run_id'))}</footer>
</body>
</html>"""
