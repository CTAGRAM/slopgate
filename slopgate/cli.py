"""slopgate triage <pr-url> [--apply] | slopgate serve"""

import argparse
import dataclasses
import json

from . import config, report


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="slopgate", description="System One triage for pull requests.")
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("triage", help="triage one pull request")
    t.add_argument("url", help="https://github.com/OWNER/REPO/pull/N")
    t.add_argument("--apply", action="store_true", help="label the PR and post the scorecard comment")
    t.add_argument("--json", action="store_true", help="print machine-readable output")
    t.add_argument("--model", help="System One model id (default: SLOPGATE_MODEL or openjev-latest)")
    t.add_argument("--no-escalate", action="store_true", help="never ask the System Two LLM")
    c = sub.add_parser("compare", help="judge one PR with every contender, side by side")
    c.add_argument("url")
    c.add_argument("--json", action="store_true")
    s = sub.add_parser("serve", help="run the GitHub webhook server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("slopgate.server:app", host=args.host, port=args.port)
        return
    if args.cmd == "compare":
        _compare(args.url, args.json)
        return

    from .pipeline import SlopGate, summary

    settings = config.load()
    if args.model:
        settings = dataclasses.replace(settings, model=args.model)
    gate = SlopGate(settings)
    pr, triage = gate.triage(args.url, escalate=not args.no_escalate)
    if args.apply:
        gate.apply(pr, triage)
    if args.json:
        print(json.dumps(summary(pr, triage), indent=2))
    else:
        print(report.comment(triage, pr.linked_issue["number"] if pr.linked_issue else None))


def _compare(url: str, as_json: bool) -> None:
    from .arena import compare, contenders
    from .github import GitHub
    from .judge import build_state

    settings = config.load()
    gh = GitHub(settings.github_token)
    pr = gh.pull_request(url)
    opinions = compare(pr, build_state(pr), contenders(settings, gh))
    if as_json:
        print(json.dumps([dataclasses.asdict(o) for o in opinions], indent=2))
        return

    def when(sec: float | None) -> str:
        if sec is None:
            return "-"
        return f"{sec * 1000:.0f} ms" if sec < 1 else f"{sec:.1f} s" if sec < 120 else f"{sec / 60:.1f} min"

    print(f"{pr.url}\n{pr.title}\n")
    print(f"{'Contender':34} {'Kind':11} {'Verdict':14} {'P(spam)':>7} {'Time':>9} {'Tokens':>7}  Notes")
    for o in opinions:
        p = f"{o.p_spam:.2f}" if o.p_spam is not None else "-"
        print(f"{o.contender:34} {o.kind:11} {(o.verdict or '-'):14} {p:>7} {when(o.seconds):>9} "
              f"{(o.tokens or '-')!s:>7}  {o.error or o.detail}")


if __name__ == "__main__":
    main()
