"""The checks that stand between the copy and the publish button."""

from screencast.qc import (
    Issue,
    blocking,
    check_chapters,
    check_description,
    check_links,
    check_tags,
    check_title,
    mechanical,
    report,
)

ROWS = [(0.0, "Intro"), (56.0, "Installer Jan"), (128.0, "Utiliser Jan"), (615.0, "Les modèles")]


def test_a_normal_title_passes():
    assert check_title("Jan : faire tourner un LLM en local") == []


def test_a_title_over_the_platform_limit_blocks():
    issues = check_title("x" * 101)
    assert issues[0].severity == "bloquant"
    assert "100" in issues[0].what


def test_a_long_but_legal_title_is_only_a_remark():
    # truncated in search results, still accepted by the upload form
    assert check_title("x" * 80)[0].severity == "remarque"


def test_an_empty_title_blocks():
    assert check_title("   ")[0].severity == "bloquant"


def test_an_empty_description_is_flagged_without_blocking():
    assert check_description("")[0].severity == "à revoir"


def test_a_description_past_the_limit_blocks():
    assert check_description("x" * 5001)[0].severity == "bloquant"


def test_tags_within_budget_pass():
    assert check_tags(["jan", "llm local", "mcp"]) == []


def test_tags_over_budget_block():
    assert check_tags(["x" * 100] * 6)[0].severity == "bloquant"


def test_a_well_formed_chapter_list_passes():
    assert check_chapters(ROWS, duration=949) == []


def test_a_list_not_starting_at_zero_blocks():
    # YouTube ignores the whole set, silently — the worst kind of failure
    issues = check_chapters([(5.0, "Intro"), *ROWS[1:]])
    assert issues[0].severity == "bloquant"
    assert "0:00" in issues[0].what


def test_fewer_than_three_chapters_blocks():
    assert blocking(check_chapters(ROWS[:2]))


def test_a_chapter_shorter_than_ten_seconds_blocks():
    rows = [(0.0, "Intro"), (5.0, "Trop court"), (128.0, "Suite")]
    assert any("5s" in i.what for i in blocking(check_chapters(rows)))


def test_a_chapter_starting_after_the_end_blocks():
    rows = [*ROWS, (2000.0, "Après la fin")]
    assert any("après la fin" in i.what for i in blocking(check_chapters(rows, duration=949)))


def test_an_empty_label_is_flagged():
    rows = [(0.0, "Intro"), (56.0, "  "), (128.0, "Suite")]
    assert any(i.where == "chapitres" and "vide" in i.what for i in check_chapters(rows))


def test_no_chapters_at_all_is_flagged():
    assert check_chapters([])[0].where == "chapitres"


def test_a_link_left_without_a_url_is_reported():
    issues = check_links([{"name": "Browser MCP", "url": ""}, {"name": "Jan", "url": "https://jan.ai"}])
    assert issues[0].severity == "à revoir"
    assert "Browser MCP" in issues[0].what


def test_links_all_resolved_say_nothing():
    assert check_links([{"name": "Jan", "url": "https://jan.ai"}]) == []


def test_clean_copy_produces_no_issues():
    assert mechanical("Un titre correct", "Une description.", ["jan"], ROWS, [], 949) == []


def test_the_report_says_so_when_there_is_nothing_to_say():
    assert "Rien à signaler" in report([], "Un titre")


def test_the_report_groups_by_severity_worst_first():
    issues = [
        Issue("remarque", "titre", "un peu long"),
        Issue("bloquant", "chapitres", "pas de 0:00"),
    ]
    text = report(issues, "Un titre")
    assert text.index("Bloquant") < text.index("Remarque")


def test_the_report_carries_the_suggested_fix():
    text = report([Issue("à revoir", "titre", "faute", "écrire MCP")], "T")
    assert "écrire MCP" in text


def test_blocking_keeps_only_what_stops_a_publish():
    issues = [Issue("bloquant", "a", "x"), Issue("remarque", "b", "y")]
    assert len(blocking(issues)) == 1
