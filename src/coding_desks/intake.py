"""`desk intake`: print a prompt that turns a paragraph into office.yaml.

The harness the user is already sitting in does the parsing. No API key.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

RULES = """\
Rules for the manifest you write:
- Keep the two hats exactly as `owner` and `engineer`. They may be one person.
- Every gate has two columns. The engineer's column is evidence (estimates,
  test results, read-backs, receipts). The owner's column is a decision
  (scope, priority, verdict, acceptance). Keep `order: engineer-first` on any
  gate where a decision would otherwise be made on no evidence.
- One desk per role the text names (product manager, developer, reviewer,
  ...). Use `harness: claude` unless the text says otherwise. Leave `budget`
  unset unless the text gives a number.
- Threads are the concrete pieces of work the text names. Each thread has one
  desk and, where the text gives one, a milestone.
- Milestones are dated where the text gives dates; otherwise omit `due`.
- Do not invent work the text does not mention. Leave a `# TODO:` comment
  where the text is silent on something the schema needs.
- Write the file to {target} and nothing else. Then say: run `desk check`.
"""


def build_prompt(paragraph: str, target: Path) -> str:
    template = resources.files("coding_desks").joinpath("templates/office.yaml").read_text()
    return (
        "You are setting up a coding office from the owner's own words.\n\n"
        "Here is the owner's description, verbatim:\n\n"
        "<<<\n" + paragraph.strip() + "\n>>>\n\n"
        "Produce an `office.yaml` that follows this template's schema exactly:\n\n"
        "```yaml\n" + template + "```\n\n" + RULES.format(target=target)
    )
