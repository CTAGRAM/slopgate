"""The verdict in plain English, for people who don't read probabilities.

Every sentence comes from a fact computed in code, a probability from the read, or a rule that failed,
so it can only say things the evidence supports.
"""

HEADLINE = {
    "spam": "This looks like spam",
    "needs_changes": "This looks like a genuine attempt, but it isn't ready yet.",
    "needs_review": "A maintainer should look at this one before anything else happens.",
    "fast_track": "This looks like a good contribution that's ready for review.",
}
SPAM_KIND = {
    "contributor_gaming": ": a low-value change made to collect contribution credit.",
    "self_promotion": ": it mainly promotes the author.",
    "ai_slop": ": unreviewed AI-generated changes.",
    "low_effort": ": a trivial change with no real value.",
}
RULES = {  # anti-slop's check names, in words
    "detect-spam-usernames": "a spam-like username",
    "min-profile-completeness": "a mostly empty profile",
    "blocked-paths": "edits to protected files such as the README",
    "require-maintainer-can-modify": "a branch maintainers can't edit",
    "account-age": "a very new account",
    "global-merge-ratio": "few of the author's past PRs ever merged",
    "max-daily-forks": "many forks in one day",
    "require-description": "no description",
    "require-linked-issue": "no linked issue",
    "require-final-newline": "files missing a final newline",
    "max-added-comments": "lots of added code comments",
    "require-public-profile": "a private profile",
}
ACTION = {
    "spam": "SlopGate labelled it spam; a maintainer can close it with one click.",
    "needs_changes": "SlopGate labelled it needs-changes, so the author knows it isn't ready.",
    "needs_review": "SlopGate labelled it for review and explained why. Nothing was closed.",
    "fast_track": "SlopGate moved it to the front of the review queue.",
}


def explain(verdict: str, spam_type: str | None = None, flags=(), probs: dict | None = None,
            facts: dict | None = None, rules: dict | None = None, uncertain: bool = False) -> str:
    probs, facts, flags = probs or {}, facts or {}, set(flags or ())
    p = lambda k, d=None: probs.get(k, d)
    if "injection" in flags:
        head = "This pull request hides instructions aimed at AI reviewers, so it needs a careful human look."
    elif verdict == "spam":
        head = HEADLINE["spam"] + SPAM_KIND.get(spam_type or "", ".")
    else:
        head = HEADLINE.get(verdict, "SlopGate has a verdict.")

    why: list[str] = []
    if "injection" in flags:
        why.append("it contains text telling AI reviewers to approve it")
    if p("risky", 0) >= .5:
        why.append("it changes CI, dependencies or install scripts, which can run code on your machines")
    if facts.get("own_name"):
        why.append("it adds the author's own name to the project")
    if facts.get("unfilled_template"):
        why.append("the description is the repo's empty pull request template")
    if (facts.get("swarm") or 0) >= 2:
        why.append(f"{facts['swarm']} other people opened near-identical pull requests just before it")
    if p("claims_match", 1) < .4:
        why.append("the change doesn't do what its title and description say")
    if p("matches_issue", 1) < .3:
        why.append("it doesn't do what the linked issue asks")
    if p("follows_rules", 1) < .3:
        why.append("it goes against this repo's contributing guide")
    if p("ai_slop", 0) >= .7 and "injection" not in flags:
        why.append("it reads like unreviewed AI output")
    failed = (rules or {}).get("checks") or []
    if rules and not rules.get("error") and (rules.get("failed") or 0) >= 2:
        words = [RULES.get(c["name"], c["name"].replace("-", " ")) for c in failed[:3]]
        why.append(f"it failed {rules['failed']} of anti-slop's rule checks ({', '.join(words)})")
    age, burst = facts.get("age_days"), facts.get("prs_24h")
    if verdict == "spam" and age is not None and age < 30:
        why.append(f"the account is only {age} days old")
    if verdict == "spam" and burst is not None and burst >= 5:
        why.append(f"the author opened {burst} pull requests across GitHub in the last day")
    if verdict == "fast_track":
        if p("claims_match", 0) >= .8:
            why.append("the change does what it says")
        if p("matches_issue", 0) >= .8:
            why.append("it fixes the linked issue")
        if p("follows_rules", 0) >= .8:
            why.append("it follows the contributing guide")
        if p("needs_tests", 1) < .3 and (facts.get("files") or 0) > 1:
            why.append("it comes with tests")

    parts = [head]
    if why:
        reasons = why[:3]
        text = reasons[0] if len(reasons) == 1 else ", ".join(reasons[:-1]) + " and " + reasons[-1]
        parts.append(text[0].upper() + text[1:] + ".")
    if uncertain:
        parts.append("SlopGate wasn't sure, so it asked a second model and leaves the call to a maintainer.")
    else:
        parts.append(ACTION.get(verdict, ""))
    return " ".join(x for x in parts if x)
