from sre_copilot.rag.loader import chunk_markdown, load_runbooks

RUNBOOK = """# KubePodCrashLooping

A pod is crash looping.

## Symptoms

- Restarts increasing.
- CrashLoopBackOff status.

## Diagnosis

1. Check logs.
2. Describe the pod.

## Remediation

- Roll back the deploy.
"""

NO_HEADING_RUNBOOK = """Just some prose without any headings.

Second paragraph.
"""


def test_chunk_markdown_splits_by_section():
    chunks = chunk_markdown("crashloopbackoff", RUNBOOK)

    assert [chunk.section for chunk in chunks] == [
        "KubePodCrashLooping",
        "Symptoms",
        "Diagnosis",
        "Remediation",
    ]
    assert all(chunk.runbook == "crashloopbackoff" for chunk in chunks)
    assert all(chunk.title == "KubePodCrashLooping" for chunk in chunks)
    assert [chunk.id for chunk in chunks] == [
        "crashloopbackoff::0",
        "crashloopbackoff::1",
        "crashloopbackoff::2",
        "crashloopbackoff::3",
    ]


def test_chunk_markdown_keeps_heading_in_chunk_text():
    chunks = chunk_markdown("crashloopbackoff", RUNBOOK)
    diagnosis = next(chunk for chunk in chunks if chunk.section == "Diagnosis")
    assert diagnosis.text.startswith("## Diagnosis")
    assert "Check logs." in diagnosis.text


def test_chunk_markdown_without_headings_yields_single_overview_chunk():
    chunks = chunk_markdown("notes", NO_HEADING_RUNBOOK)
    assert len(chunks) == 1
    assert chunks[0].section == "overview"
    assert chunks[0].title == "notes"


def test_chunk_markdown_empty_content_yields_no_chunks():
    assert chunk_markdown("empty", "  \n\n") == []


def test_load_runbooks_reads_all_markdown_files(tmp_path):
    (tmp_path / "alpha.md").write_text("# Alpha\n\n## One\n\nAlpha body.\n")
    (tmp_path / "beta.md").write_text("# Beta\n\n## One\n\nBeta body.\n")
    (tmp_path / "ignored.txt").write_text("not a runbook")

    chunks = load_runbooks(tmp_path)

    assert {chunk.runbook for chunk in chunks} == {"alpha", "beta"}
    assert len(chunks) == 4  # title section + one section per file


def test_load_runbooks_missing_directory_returns_empty(tmp_path):
    assert load_runbooks(tmp_path / "does-not-exist") == []
