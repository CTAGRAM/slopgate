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
    s = sub.add_parser("serve", help="run the GitHub webhook server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        uvicorn.run("slopgate.server:app", host=args.host, port=args.port)
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


if __name__ == "__main__":
    main()
