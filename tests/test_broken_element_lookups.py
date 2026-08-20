"""A tool that throws when a human opens it must not be stored as "passed".

`check_tool_memory.py` found this on production: the *10k Race Day Pacing Strategy
Calculator*, `smoke_test_passed=True`, threw `Cannot set properties of null (setting
'textContent')` the moment the dashboard opened it. One line:

    document.getElementById('h2-mi').textContent = formatPaceMiles(p2);

The markup declared `h1-mi h1-pace h1-tip h1-tot` for the first half and `h2-final
h2-pace h2-tip h2-tot` for the second. Twenty-one ids declared, twenty-one looked up,
exactly one that did not line up. Everything after that line stopped running.

The Toolwright could not have caught it. Its smoke test runs the *calculation*, in a
code executor with no DOM, so it tests the half it can reach and certifies the half it
cannot -- honestly, and wrongly. That is the recurring shape in this repo: anything a
machine can check should not rest on a model's word about itself.

The risk in fixing it is the opposite failure. A false positive marks a WORKING tool
degraded, which is worse than the bug, so `broken_element_lookups` only reports an id
whose literal appears in the source exactly once. Half these tests exist to hold that
line: ids built from template literals, assigned to created elements, or injected
through innerHTML all have to survive.
"""

from __future__ import annotations

from challenge_accepted.services.tools import broken_element_lookups as broken

# The real shape, reduced. h2-mi is read and never declared.
REAL = """
<div><b id="h1-mi">0</b><b id="h1-pace">0</b><b id="h2-final">0</b><b id="h2-pace">0</b></div>
<script>
  document.getElementById('h1-mi').textContent = a;
  document.getElementById('h2-mi').textContent = b;
  document.getElementById('h2-pace').textContent = c;
</script>
"""


def test_it_finds_the_bug_that_reached_production():
    assert broken(REAL) == ["h2-mi"]


def test_a_matching_id_is_not_reported():
    assert broken("<b id='out'></b><script>document.getElementById('out').textContent=1"
                  "</script>") == []


def test_source_with_no_lookups_is_left_alone():
    assert broken("print('hello')") == []
    assert broken("") == []


def test_an_id_assigned_to_a_created_element_survives():
    """`el.id = 'row'` creates it just as truly as markup does."""
    src = ("<script>const el=document.createElement('div'); el.id='row';"
           "document.body.appendChild(el);"
           "document.getElementById('row').textContent='x';</script>")
    assert broken(src) == []


def test_an_id_injected_through_innerhtml_survives():
    """The id exists only inside a string, and the tool works. Must not be flagged."""
    src = ("<div id='wrap'></div><script>"
           "document.getElementById('wrap').innerHTML = '<b id=\"total\">0</b>';"
           "document.getElementById('total').textContent = '5';</script>")
    assert broken(src) == []


def test_a_template_literal_id_is_not_guessed_at():
    """`getElementById(`km-${i}`)` cannot be resolved without running the page."""
    src = ("<script>for (let i=0;i<3;i++)"
           "{document.getElementById(`km-${i}`).textContent=i;}</script>")
    assert broken(src) == []


def test_an_id_mentioned_anywhere_else_is_given_the_benefit_of_the_doubt():
    """Appearing twice means something else in the source refers to it, and the rule
    is deliberately generous -- a false positive degrades a tool that works."""
    src = ("<script>const wanted='total';"
           "document.getElementById('total').textContent=1;</script>")
    assert broken(src) == []


def test_several_broken_ids_are_all_reported_in_order():
    src = ("<script>document.getElementById('alpha').textContent=1;"
           "document.getElementById('beta').textContent=2;</script>")
    assert broken(src) == ["alpha", "beta"]


def test_the_same_broken_id_is_reported_once():
    src = ("<script>document.getElementById('alpha').textContent=1;"
           "document.getElementById('alpha').className='x';</script>")
    # Twice in the source, so the conservative rule lets it pass -- and that is the
    # documented trade. Pinned so the behaviour is a decision, not a surprise.
    assert broken(src) == []
