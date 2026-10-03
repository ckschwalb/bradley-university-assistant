from review import answer_issues, cited_links, indexed_url_set, unindexed_links

INDEXED = indexed_url_set(["https://www.bradley.edu/academics/nursing/"])


def kinds(text, indexed=INDEXED):
    return [i["kind"] for i in answer_issues(text, indexed)]


def test_clean_answer_with_indexed_citation_has_no_issues():
    assert kinds("See [Nursing](https://www.bradley.edu/academics/nursing).") == []


def test_no_answer_phrases_are_flagged():
    assert "no_answer" in kinds("I couldn't find that information.")
    assert "no_answer" in kinds("Sorry, I don’t have any specific information about that.")


def test_unindexed_bradley_link_is_flagged_but_other_domains_are_not():
    assert kinds("[x](https://www.bradley.edu/made-up-page)") == ["unknown_link"]
    assert kinds("[x](https://example.com/page)") == []


def test_fragment_and_trailing_slash_do_not_matter_when_matching_links():
    assert unindexed_links("https://www.bradley.edu/academics/nursing#apply", INDEXED) == []


def test_hedging_without_citation_is_flagged_as_unsupported():
    assert "unsupported" in kinds("Classes usually start in August.")
    assert "unsupported" not in kinds("Classes usually start in August. [Calendar](https://example.com/cal)")


def test_code_fence_is_flagged_as_formatting():
    assert "formatting" in kinds("```\nraw\n```")


def test_cited_links_dedupes_and_skips_mailto():
    text = "[A](https://a.com/x) and https://a.com/x and [mail](mailto:x@y.com)."
    assert cited_links(text) == [{"label": "A", "url": "https://a.com/x"}]
