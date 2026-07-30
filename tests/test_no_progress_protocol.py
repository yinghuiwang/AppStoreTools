from pathlib import Path


def test_no_progress_protocol_markers_in_src():
    root = Path("src/asc")
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "[PROGRESS:" in text:
            offenders.append(str(path))
    assert offenders == []
