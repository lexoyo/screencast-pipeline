"""Checking the URLs that ship in a description. No test here touches the network."""

from screencast.links import (
    Result,
    check,
    check_all,
    classify,
    prune,
    report,
    unlink_dead,
    urls_in,
)

OK = "https://jan.ai"
GONE = "https://example.com/moved"
BOT = "https://openai.com"


def fake(status_by_url):
    return lambda url: status_by_url.get(url, 200)


def test_a_live_page_is_usable():
    assert classify(OK, 200).usable


def test_a_redirect_is_a_live_page():
    # urllib follows them; a 3xx that reaches us is still not a dead link
    assert classify(OK, 301).usable


def test_a_404_is_dead():
    result = classify(GONE, 404)
    assert result.status == "mort"
    assert not result.usable


def test_a_403_is_kept_because_the_site_only_refuses_robots():
    # observed on openai.com: 403 to a script, perfectly alive in a browser
    result = classify(BOT, 403)
    assert result.status == "protégé"
    assert result.usable


def test_a_rate_limit_is_not_a_dead_link():
    assert classify(BOT, 429).usable


def test_no_answer_at_all_is_not_usable():
    assert not classify(GONE, 0).usable


def test_a_network_error_does_not_raise():
    def explode(url):
        raise OSError("dns")

    assert check(GONE, explode).status == "injoignable"


def test_an_empty_url_is_not_checked():
    def explode(url):
        raise AssertionError("should not be called")

    assert check("", explode).status == "ok"


def test_each_url_is_checked_once_even_when_repeated():
    seen = []

    def counting(url):
        seen.append(url)
        return 200

    check_all([OK, OK, OK], counting)
    assert seen == [OK]


def test_a_dead_url_is_blanked_but_the_name_survives():
    # knowing what to search for is most of the value
    results = {GONE: Result(GONE, "mort", "404")}
    pruned = prune([{"name": "un outil", "url": GONE, "at": 10}], results)
    assert pruned[0]["url"] == ""
    assert pruned[0]["name"] == "un outil"


def test_a_protected_url_stays_in_the_description():
    results = {BOT: Result(BOT, "protégé", "403")}
    assert prune([{"name": "OpenAI", "url": BOT}], results)[0]["url"] == BOT


def test_pruning_leaves_the_original_untouched():
    original = {"name": "un outil", "url": GONE}
    prune([original], {GONE: Result(GONE, "mort", "404")})
    assert original["url"] == GONE


def test_a_dead_link_in_the_document_becomes_plain_text():
    text = f"On utilise [un outil]({GONE}) tous les jours."
    out = unlink_dead(text, {GONE: Result(GONE, "mort", "404")})
    assert out == "On utilise un outil tous les jours."


def test_a_live_link_in_the_document_is_left_alone():
    text = f"On utilise [Jan]({OK})."
    assert unlink_dead(text, {OK: Result(OK, "ok", "200")}) == text


def test_urls_are_found_in_the_document():
    assert urls_in(f"[a]({OK}) et [b]({GONE})") == [OK, GONE]


def test_a_bare_url_is_not_treated_as_a_link():
    # only markdown links are rewritten; a URL in running text is left as written
    assert urls_in(f"voir {OK} pour la suite") == []


def test_everything_fine_means_nothing_to_report():
    assert report({OK: Result(OK, "ok", "200")}) == []


def test_what_needs_a_look_is_reported():
    lines = report({GONE: Result(GONE, "mort", "404"), BOT: Result(BOT, "protégé", "403")})
    assert len(lines) == 2
    assert any("mort" in line and GONE in line for line in lines)
