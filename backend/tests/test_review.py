import json

import pytest

from tracelight.orchestrator.review import (ReviewError, SRSOutputs, add_extracted, apply_review,
                                            build_review_items, review_counts, similar_pairs)


def req(rid, text, **kw):
    r = {"requirement_id": rid, "id_source": "source", "raw_text": text, "normalized_text": text,
         "title": text[:30], "type": "functional", "subtype": "general", "candidate_confidence": "high",
         "candidate_reason": "", "review_required": False, "sub_requirements": [], "conditions": [],
         "constraints": [], "error_conditions": [], "source": {"page": 3, "paragraph": 7}}
    r.update(kw)
    return r


def fake_embed(texts):
    """Texts sharing their first word are 'near-identical' (cosine 1); others orthogonal."""
    words = sorted({t.split()[0].lower() for t in texts.values()})
    return {k: [1.0 if w == t.split()[0].lower() else 0.0 for w in words] for k, t in texts.items()}


@pytest.fixture()
def outputs():
    return SRSOutputs(
        requirements=[
            req("FR-001", "Register a member with name and email."),                        # 0 clean
            req("FR-002", "The system shall reject the checkout when:"),                    # 1 incomplete
            req("FR-003", "Low confidence item about fines.", candidate_confidence="low",
                candidate_reason="vague wording"),                                          # 2 flagged
            req("FR-004", "Renew a loan at most twice."),                                   # 3
            req("FR-005", "Renew loans if no fines are outstanding."),                      # 4 dup of FR-004
            req("FR-001", "Delete a member.", title="Delete member"),                       # 5 duplicate ID
            req("FR-006", "Search books by title.", review_required=True,
                candidate_reason="model unsure"),                                           # 6 flagged
            req("FR-006.1", "Search case-insensitively.", parent_requirement_id="FR-006"),  # 7 child of 6
        ],
        report={
            "segmentation": {
                "warnings": [{"type": "missing_list", "requirement_id": "FR-004",
                              "message": "Text introduces a list or table that is not present in the input."}],
                "skipped_sections": [{"heading": "1.2 Scope", "location": {"paragraph": 7},
                                      "items": ["Catalog management.", "Lending."]},
                                     {"heading": "1.3 Definitions", "location": {"paragraph": 16}}],
                "skipped_tables": [{"reason": "key/value table (metadata or glossary)",
                                    "first_row": ["Field", "Value"], "location": {"table": 1}}]},
            "candidate_review": [{"candidate_id": "C-0002", "decision": "uncertain", "confidence": "low",
                                  "reason": "no shall", "text": "Librarians usually work at the desk.",
                                  "source": {"page": 9}}],
            "extraction_failures": [{"index": 4, "requirement_id": "FR-009", "text": "FR-009 Pay a fine.",
                                     "source": {"page": 5}, "error": "invalid JSON"}],
        },
        candidates=[{"text": "FR-001 Register a member."},
                    {"text": "Librarians usually work at the desk.", "source": {"page": 9},
                     "detection_confidence": "low", "detection_reason": "no modal verb"}],
    )


def by_key(items):
    return {it["key"]: it for it in items}


def resolve(items, **res):
    """res: key -> resolution or (resolution, data); keys use '__' for ':' and '_' for '-'."""
    out = []
    for it in items:
        it = dict(it)
        name = it["key"].replace(":", "__").replace("-", "_")
        if name in res:
            r = res[name]
            it["resolution"], it["resolution_data"] = (r, {}) if isinstance(r, str) else r
        out.append(it)
    return out


def resolve_all(items, default="kept", **res):
    items = resolve(items, **res)
    return [{**it, "resolution": it.get("resolution") or default} for it in items]


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def test_categories_and_order(outputs):
    items = build_review_items(outputs, embed=fake_embed)
    cats = [(it["key"], it["category"]) for it in items]
    assert cats == [
        ("cand:C-0002", "uncertain"),
        ("req:2", "flagged"), ("req:6", "flagged"), ("fail:1", "flagged"),
        ("req:1", "incomplete"), ("req:3", "incomplete"),
        ("req:4", "split"), ("req:5", "split"),
        ("skip:section:1", "uncertain"), ("skip:table:1", "uncertain"),
    ]
    k = by_key(items)
    assert k["req:5"]["payload"]["suggestion"] == {"action": "merge", "target": "FR-001"}
    assert "Same requirement ID" in k["req:5"]["payload"]["reasons"][0]
    assert k["req:4"]["payload"]["suggestion"]["target"] == "FR-004"
    assert k["req:1"]["payload"]["suggestion"] == {"action": "edit"}
    assert k["req:1"]["payload"]["location"] == {"page": 3, "paragraph": 7}


def test_one_item_per_requirement_with_secondary_categories(outputs):
    outputs.requirements[3]["review_required"] = True          # FR-004: incomplete + flagged
    items = by_key(build_review_items(outputs, embed=fake_embed))
    assert items["req:3"]["category"] == "incomplete"
    assert items["req:3"]["payload"]["also"] == ["flagged"]
    assert len(items["req:3"]["payload"]["reasons"]) == 2


def test_parent_child_not_duplicates_and_threshold():
    reqs = [req("FR-006", "Search books."), req("FR-006.1", "Search case-insensitively.",
                                                parent_requirement_id="FR-006")]
    assert similar_pairs(reqs, fake_embed, 0.9) == []
    reqs[1]["parent_requirement_id"] = None
    assert [(i, j) for i, j, _ in similar_pairs(reqs, fake_embed, 0.9)] == [(0, 1)]
    assert similar_pairs(reqs, lambda t: {k: [1.0, 0.0] if k == "0" else [0.6, 0.8] for k in t}, 0.9) == []


def test_without_embeddings_no_similarity_items(outputs):
    keys = by_key(build_review_items(outputs, embed=None))
    assert "req:4" not in keys and "req:5" in keys          # ID duplicates need no embeddings


def test_skipped_content_is_pre_discarded(outputs):
    k = by_key(build_review_items(outputs))
    assert k["skip:section:1"]["resolution"] == "discarded"
    assert k["skip:section:1"]["payload"]["items"] == ["Catalog management.", "Lending."]
    assert "skip:section:2" not in k                        # a heading without items
    counts = review_counts(build_review_items(outputs))
    assert counts["resolved"] == 2 and counts["open_by_category"]["split"] == 1


def test_clean_extraction_has_nothing_open():
    out = SRSOutputs(requirements=[req("FR-001", "Add a book."), req("FR-002", "Remove a book.")])
    assert build_review_items(out, embed=fake_embed) == []


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def test_unresolved_items_block(outputs):
    items = build_review_items(outputs, embed=fake_embed)
    with pytest.raises(ReviewError) as exc:
        apply_review(outputs, items)
    assert "cand:C-0002" in exc.value.keys and "skip:table:1" not in exc.value.keys


def test_keep_everything_requires_resolving_the_duplicate_id(outputs):
    items = build_review_items(outputs, embed=fake_embed)
    with pytest.raises(ReviewError, match="FR-001"):
        apply_review(outputs, resolve_all(items))


def test_full_resolution(outputs):
    items = build_review_items(outputs, embed=fake_embed)
    items = resolve_all(items, default="unreviewed",
                        cand__C_0002="discarded",
                        req__1=("edited", {"text": "The system shall reject a checkout when the member has 5 loans."}),
                        req__2="kept",
                        req__4=("merged", {"into": "FR-004"}),
                        req__5=("kept", {"requirement_id": "FR-010"}),
                        fail__1="kept",
                        skip__section__1="kept")
    result = apply_review(outputs, items)
    ids = [r["requirement_id"] for r in result.requirements]
    assert ids == ["FR-001", "FR-002", "FR-003", "FR-004", "FR-010", "FR-006", "FR-006.1"]
    reqs = {r["requirement_id"]: r for r in result.requirements}
    # edited text replaces raw + normalized text and keeps the original
    assert reqs["FR-002"]["raw_text"].endswith("5 loans.")
    assert reqs["FR-002"]["review"]["original_raw_text"] == "The system shall reject the checkout when:"
    # merge appends the text and records the source
    assert "Renew loans if no fines" in reqs["FR-004"]["raw_text"]
    assert reqs["FR-004"]["review"]["merged_from"] == ["req:4"]
    assert reqs["FR-010"]["review"]["original_requirement_id"] == "FR-001"
    assert reqs["FR-006"]["review"]["status"] == "unreviewed"
    assert "review" not in reqs["FR-001"]                     # needed no decision
    # extraction: the failed candidate and the two items of the restored section
    texts = [c["text"] for c in result.to_extract]
    assert texts == ["FR-009 Pay a fine.", "Catalog management.", "Lending."]
    assert [c["candidate_id"] for c in result.to_extract] == ["fail:1", "skip:section:1#1", "skip:section:1#2"]
    assert result.summary["merged"] == 1 and result.summary["discarded"] == 2


def test_kept_uncertain_candidate_uses_detected_candidate(outputs):
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        cand__C_0002=("kept", {"requirement_id": "FR-050"}))
    result = apply_review(outputs, items)
    cand = result.to_extract[0]
    assert cand["detection_reason"] == "no modal verb"         # from candidates.json
    assert cand["source_requirement_id"] == "FR-050" and cand["candidate_id"] == "cand:C-0002"
    assert cand["candidate_decision"] == "keep"


def test_candidate_merged_into_requirement(outputs):
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        cand__C_0002=("merged", {"into": "FR-001"}))
    result = apply_review(outputs, items)
    fr1 = next(r for r in result.requirements if r["requirement_id"] == "FR-001")
    assert "Librarians usually work" in fr1["raw_text"] and result.to_extract == []


@pytest.mark.parametrize("data,match", [({"into": "FR-404"}, "not a kept"), ({}, "not a kept"),
                                        ({"into": "FR-003"}, "not a kept")])
def test_bad_merge_targets(outputs, data, match):
    # FR-003 is discarded below, so it cannot be a target either
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        req__4=("merged", data))
    with pytest.raises(ReviewError, match=match):
        apply_review(outputs, items)


def test_merge_into_itself(outputs):
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        req__3=("merged", {"into": "FR-004"}))
    with pytest.raises(ReviewError, match="itself"):
        apply_review(outputs, items)


def test_rename_collision_is_reported(outputs):
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        req__2=("kept", {"requirement_id": "FR-004"}), req__3="kept")
    with pytest.raises(ReviewError, match="FR-004"):
        apply_review(outputs, items)


def test_empty_edit_rejected(outputs):
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        req__1=("edited", {"text": "  "}))
    with pytest.raises(ReviewError, match="empty"):
        apply_review(outputs, items)


def test_input_is_not_mutated(outputs):
    before = json.dumps(outputs.requirements, sort_keys=True)
    items = resolve_all(build_review_items(outputs, embed=fake_embed), default="discarded",
                        req__1=("edited", {"text": "new"}), req__4=("merged", {"into": "FR-001"}))
    apply_review(outputs, items)
    assert json.dumps(outputs.requirements, sort_keys=True) == before


# ---------------------------------------------------------------------------
# Requirements extracted after review
# ---------------------------------------------------------------------------


def test_add_extracted_renumbers_and_carries_status():
    existing = [req("FR-001", "a"), req("REQ-001", "b", id_source="generated")]
    to_extract = [{"candidate_id": "cand:C-0002", "review_status": "unreviewed"},
                  {"candidate_id": "fail:1", "review_status": "kept"},
                  {"candidate_id": "skip:section:1#1", "review_status": "kept"}]
    extracted = [req("REQ-001", "c", id_source="generated", candidate_id="cand:C-0002"),
                 req("FR-001", "d", candidate_id="fail:1"),
                 req("FR-077", "e", candidate_id="skip:section:1#1")]
    out = add_extracted(existing, extracted, to_extract)
    assert [r["requirement_id"] for r in out] == ["FR-001", "REQ-001", "REQ-002", "FR-001-2", "FR-077"]
    assert out[2]["review"] == {"status": "unreviewed", "item": "cand:C-0002", "extracted_after_review": True}
    assert extracted[0]["requirement_id"] == "REQ-001"         # input not mutated


def test_load_outputs(tmp_path):
    (tmp_path / "requirements.json").write_text(json.dumps([req("FR-001", "x")]), encoding="utf-8")
    (tmp_path / "document_blocks.json").write_text(json.dumps({"type": "docx", "blocks": [{"kind": "heading"}]}),
                                                   encoding="utf-8")
    out = SRSOutputs.load(tmp_path)
    assert out.requirements[0]["requirement_id"] == "FR-001"
    assert out.blocks == [{"kind": "heading"}] and out.report == {} and out.candidates == []
