from logos.normalise.taxonomy import TaxonomyNormaliser


def _build_preview():
    return {
        "entities": {
            "persons": [
                {
                    "id": "p1",
                    "name": "Alex Sponsor",
                    "hints": {"role": "Internal sponsor"},
                }
            ],
            "orgs": [
                {
                    "id": "o1",
                    "name": "Regulator",  # falls back to role hint
                    "hints": {"stakeholder_type": "Regulator"},
                }
            ],
            "risks": [
                {
                    "id": "r1",
                    "title": "Budget exposure",
                    "category": "commercial risk",
                }
            ],
        }
    }


def test_taxonomy_normalises_hints_and_scores_matches():
    normaliser = TaxonomyNormaliser()
    preview = _build_preview()

    normalised = normaliser.normalise_preview(preview)
    person = normalised["entities"]["persons"][0]
    stakeholder_result = person.get("hint_resolution", {}).get("stakeholder_types")

    assert stakeholder_result
    assert stakeholder_result["canonical_id"] == "st_internal_sponsor"
    assert stakeholder_result["status"] == "matched"
    assert person.get("type") == "st_internal_sponsor"
    assert stakeholder_result.get("score", 0) > 0.9

    org = normalised["entities"]["orgs"][0]
    org_result = org.get("hint_resolution", {}).get("stakeholder_types")
    assert org_result
    assert org_result["canonical_id"] == "st_regulator"

    risk = normalised["entities"]["risks"][0]
    risk_result = risk.get("hint_resolution", {}).get("risk_categories")
    assert risk_result
    assert risk_result["canonical_id"] == "rc_commercial"
    assert risk_result["score"] >= 0.75

