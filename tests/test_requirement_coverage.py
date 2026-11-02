import re

from tests.conftest import ROOT


def test_should_find_dedicated_evidence_when_requirement_is_marked_complete(request):
    document = (ROOT / "docs/requirements.md").read_text()
    rules = dict(re.findall(r"\*\*(R\d+)\*\* \[([^\]]+)\]", document))
    evidence = set()
    for item in request.session.items:
        markers = list(item.iter_markers("requirement"))
        assert len(markers) <= 1, f"Use a dedicated test per rule: {item.nodeid}"
        for marker in markers:
            assert len(marker.args) == 1 and marker.args[0] in rules, item.nodeid
            evidence.add(marker.args[0])
    missing = {rule for rule, state in rules.items() if state in {"✅", "X"}} - evidence
    assert not missing, (
        f"Completed requirements without collected test evidence: {sorted(missing)}"
    )
