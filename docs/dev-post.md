---
title: SlopGate: a 200 ms bouncer for your pull requests, built on open weights
published: false
tags: hacktoberfest, opensource, ai, github
---

*This is a submission for the [Hacktoberfest 2026 Open-Source AI Challenge: Side Hustle](https://dev.to/challenges/hacktoberfest-week2-2026-10-12).*

## What I Built

This October, Hacktoberfest stopped counting pull requests. The reason, in its organisers' own
words, is that maintainers were burning out under low-effort, box-checking PRs, and AI made those
trivial to produce. GitHub is now weighing a switch that lets maintainers turn pull requests off
altogether.

Closing the door on everyone is the wrong fix. **SlopGate** keeps the door open and puts a fast,
honest bouncer in front of it. Every new pull request gets read by an open-weight model in about
200 milliseconds, then labelled and explained:

- **spam**, and what kind (contributor-gaming, self-promotion, AI slop, low effort)
- **unreviewed AI output**
- **prompt injection** aimed at AI reviewers, even inside hidden HTML comments
- **risky changes** to CI, dependencies or install scripts
- whether the diff **does what the PR claims**, what the linked issue asks, and whether it follows
  **the repo's own CONTRIBUTING rules**
- which **area** of the project it belongs to, using the repo's own labels

It never closes anything. It labels, explains, and leaves the decision to a human.

**Who would pay for this?** Anyone whose public repository gets more pull requests than people to
read them: maintainers of popular projects, companies with open-source SDKs whose DevRel teams
triage community PRs, and the organisers of events like Hacktoberfest. The pitch is the time it
saves, and keeping the repo open at all. The self-hosted version is free; the paid side hustle is
the hosted gate for organisations that don't want to run a GPU.

## Demo

Open a PR on the playground repo, [CTAGRAM/slopgate-demo](https://github.com/CTAGRAM/slopgate-demo/pulls),
and SlopGate labels it within seconds. Four real examples:

- [#2](https://github.com/CTAGRAM/slopgate-demo/pull/2): "Update README.md" that adds the author's
  name → **spam (contributor-gaming)**, 100% confident, read in about 100 ms
- [#3](https://github.com/CTAGRAM/slopgate-demo/pull/3): a real bug fix with a test → **fast-track**
- [#4](https://github.com/CTAGRAM/slopgate-demo/pull/4): sneaks `curl | bash` into CI and hides a note
  telling AI reviewers to approve it → **prompt injection** and **risky files**; it can never be fast-tracked
- [#5](https://github.com/CTAGRAM/slopgate-demo/pull/5): a "comprehensive refactor" that renames
  variables → **needs changes**, unreviewed AI output

![SlopGate's scorecard on a pull request](https://raw.githubusercontent.com/CTAGRAM/slopgate/main/docs/scorecard.png)

The **arena** page puts every judge side by side on any PR: SlopGate on two open models, an
open-weight chat LLM, the anti-slop rule set, and what CodeRabbit actually posted.

## Code

{% github CTAGRAM/slopgate %}

## How I Built It

**A System One model, not a chatbot.** [OpenJev](https://github.com/razorback16/openjev) turns
DiffusionGemma 26B (open weights, Apache-2.0) into a decision model: you send a state and typed
questions (yes/no, choice, score), and it returns a calibrated probability for every answer in a
single read. Nothing is generated, so nothing can go off-schema. [Codiv](https://codiv.ai) serves it
free, and the server is open source, so you can run it on your own GPU instead.

**Counting happens in code.** Decision models are weak at arithmetic, so SlopGate computes the
facts itself: account age when the PR was opened, how many PRs the author opened across GitHub that
day, diff size, whether the description is the unfilled PR template, and whether the diff adds the
author's own username.

**A harness with two speeds.** The fast read handles clear cases. When its own probabilities say it
is unsure, SlopGate escalates to an open-weight chat LLM for a written second opinion.

**Everywhere maintainers already are.** A GitHub Action (ten lines of YAML), a webhook server
deployed on a DigitalOcean Droplet, a CLI, and an [Agent Skill](https://agentskills.io) validated with
`skills-ref`, so any coding agent can "triage the open PRs in this repo".

**Tested on real maintainers' decisions.** I collected 101 PRs that maintainers of projects like
Godot, scikit-learn and Scrapy labelled `spam`, plus PRs merged in the same repos, and ran every judge
on them. The misses taught me three things:

1. **Today's spam often looks like real work.** Scrapy got three PRs fixing the same bug within
   hours, from three accounts, each with tests, all labelled spam. So SlopGate now detects *swarms*:
   near-identical PRs from other people just before this one.
2. **Every false alarm was on a PR by the repo's own owner or a collaborator.** CodeRabbit and
   anti-slop never judge those authors for spam. Adopting the same rule removed every one of them.
3. **Review bots write into PR descriptions.** In 34 of 74 PRs, CodeRabbit had edited its summary
   into the description. SlopGate now strips bot-written text, so it judges the contributor's words.

4. **Rules and a model see different things.** The open-source anti-slop filter checks an author's
   merge history and profile; a model can't see those, but it can tell whether a diff does what it
   claims. So SlopGate now runs anti-slop's 34 rules, unmodified, alongside the read and fuses them.

Then I tested on 74 PRs it had never seen, where CodeRabbit had reviewed every one. SlopGate's final call caught
**57%** of the spam (anti-slop alone: 48%, CodeRabbit: 3%), was right **92%** of the times it said spam
(anti-slop: 63%), raised 2 false alarms where anti-slop would have closed 11 good PRs, and waved only
**1 of 40** spam PRs through to fast-track. The rule that fuses the two was chosen on a separate set
of 101 PRs first, so these numbers are not tuned to the test. The README shows every number,
including the misses.

## Why Open Innovation Matters

- **Privacy.** Point SlopGate at your own GPU running the open OpenJev server, and no pull request
  ever leaves your infrastructure. That matters to companies whose "public" repos still carry
  internal context.
- **Cost.** A read is about two thousand input tokens and zero output tokens. Judging every PR on a
  busy repo costs pennies, which is the only way a gate on *every* PR makes sense.
- **No lock-in.** OpenJev speaks the same API as TypeSafe's hosted Jev, and SlopGate can swap between
  open models (OpenJev, Clef-flash) with one setting. The evaluation harness that picked the model is
  open too, so you can re-run it on your own repos.
- **Inspectable.** Every signal comes with a probability, and every decision rule is twenty lines of
  Python you can read. A closed reviewer's "this looks like slop" is a black box; this isn't.
