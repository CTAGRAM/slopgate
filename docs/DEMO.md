# SlopGate: live demo and pitch (3 minutes)

## Before you go on stage

1. Start the server and the webhook relay on the demo laptop:
   ```bash
   uv run slopgate serve
   ```
   ```bash
   npx smee-client --url "$(grep SMEE_URL .env.local | cut -d= -f2)" --target http://localhost:8000/webhook
   ```
2. Open two browser tabs: the arena at `http://localhost:8000`, and
   `https://github.com/CTAGRAM/slopgate-demo/pulls`.
3. On a **second laptop**, a teammate logs in to GitHub with **their own account** (`gh auth login`), so
   the demo PRs come from an outside contributor, not the repo owner. They clone this repo and keep a
   terminal ready at its root.
4. Click each arena preset once to warm the connections.
5. Keep the backup: a screen recording of steps 2 and 3 below, in case the venue Wi-Fi drops.

## The pitch

**1. Hook (20 s).**
"This year Hacktoberfest stopped counting pull requests, because spam was burning maintainers out.
GitHub is weighing a switch that lets maintainers turn pull requests off entirely. Closing the door on
everyone is the wrong fix. SlopGate keeps it open: an open-weight gatekeeper that reads every PR in
about a tenth of a second."

**2. Live gate (45 s).** The teammate runs:
```bash
demo/open-pr.sh spam
```
Within seconds the PR gets the `slopgate:spam` label and a scorecard comment, and it appears in the
arena's live feed. Point at "Follows this repo's CONTRIBUTING rules: 0%": SlopGate judges PRs against
*the project's own rules*.

Then:
```bash
demo/open-pr.sh injection
```
"This one sneaks `curl | bash` into CI, and hides a note telling AI reviewers to approve it."
SlopGate flags **prompt injection** and **risky files**, and a flagged PR can never be fast-tracked.
It reads the PR as data, never as instructions.

**3. Arena (45 s).** Click **OpsiMate#1077 (labelled spam)**. Every judge races on the same real PR:
SlopGate on two open models, an open-weight chat LLM, anti-slop's 34 rules, and what CodeRabbit
actually posted. SlopGate answers in about a second; CodeRabbit's flag took minutes. Point at the
scorecard: the PR claims to add tests, but "Diff does what the PR claims" is near 0%.

**4. Honest numbers (30 s).** Scroll to the scoreboard: 101 real PRs from 29 repositories, including
Godot, scikit-learn and Scrapy, where maintainers labelled the spam. "When SlopGate says spam, it is
right most of the time, and it never closes anything." Then the discovery: scrapy got three PRs
fixing the same bug within hours from three different accounts, all labelled spam. No judge can see
that from one PR, so SlopGate now detects **swarms** across PRs.

**5. Open all the way (20 s).** Open weights (OpenJev and Clef-flash, Apache-2.0), MIT code, an
Agent Skill validated against the open standard, a GitHub Action in ten lines of YAML, and a server
you can point at your own GPU so no code leaves your infrastructure.

**Close.** "SlopGate: keep the door open, keep the slop out."

## Likely questions

- **Why not just ask an LLM?** We did, side by side. A chat model ranks PRs about as well once it gets
  SlopGate's facts, but it returns one self-reported number, sometimes malformed. SlopGate returns
  nine calibrated signals in one read that cannot go off-schema, and only calls an LLM when it is unsure.
- **False positives?** 2 to 7% of merged PRs in our test, depending on the model. That is why it
  labels and explains, and never closes.
- **Why does it miss some spam?** Much of what maintainers call spam in 2026 is plausible-looking AI
  work, recognisable only in context. That is what swarm detection and CONTRIBUTING rules address,
  and the scoreboard shows the remaining gap honestly.
- **Privacy?** Point `OPENJEV_BASE_URL` at your own GPU running the Apache-2.0 OpenJev server.
- **Cost?** The read is a few thousand input tokens and no output tokens; Codiv serves it free during
  its public experiment.
