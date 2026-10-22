"""Command line interface: validate, audit, build, master-cv."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from datetime import date
from pathlib import Path

from cvforge.build import LatexError, compile_tex
from cvforge.checks.ats import AtsReport, ats_check
from cvforge.config import Config, load_config
from cvforge.guard import GuardError, check_message_file, check_staged, check_tree
from cvforge.profile.model import ProfileError, load_master, localized
from cvforge.render.cv import build_cv_view, render_view
from cvforge.render.letter import ASSETS_DIR, letter_context, render_letter_context
from cvforge.tailor.audit import Finding, audit, audit_rendered, load_tailored
from cvforge.track import stages as stages_mod
from cvforge.track import tracker
from cvforge.track.due import due_report

SECTIONS = ("summary", "experience", "skills", "education", "certificates", "languages")
LARGE_PAGE_CAP = 1000


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _ascii(text).lower()).strip("-")


def file_part(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", _ascii(text)).strip("_")


def name_parts(name: str) -> tuple[str, str]:
    first, _, last = name.strip().partition(" ")
    return file_part(first), file_part(last.replace(" ", "_"))


def untailored(master: dict, lang: str, angle: str | None = None) -> dict:
    """A full tailored dict (everything in the master) so the normal renderer can be reused."""
    summary = {}
    summaries = master.get("x-summaries", [])
    chosen = next((s for s in summaries if angle and angle in s.get("angles", [])), None)
    if chosen is None and angle and summaries:
        raise ProfileError(f"no summary with angle '{angle}'")
    chosen = chosen or (summaries[0] if summaries else None)
    if chosen:
        summary = {"ref": chosen["id"], "text": localized(chosen["text"], lang, item_id=chosen["id"])}
    experience = [
        {"ref": w["id"], "positions": [
            {"ref": p["id"], "bullets": [
                {"ref": h["id"], "text": localized(h["impact"], lang, item_id=h["id"])}
                for h in p.get("highlights", [])]}
            for p in w.get("positions", [])]}
        for w in master.get("work", [])
    ]
    return {
        "lang": lang,
        "summary": summary,
        "experience": experience,
        "skills": [{"ref": s["id"], "keywords": s["keywords"]} for s in master.get("skills", [])],
        "education": [e["id"] for e in master.get("education", [])],
        "certificates": [c["id"] for c in master.get("certificates", [])],
        "languages": [language["id"] for language in master.get("languages", [])],
    }


def _headings(view: dict) -> list[str]:
    return [view["headings"][s] for s in SECTIONS if view.get(s)]


def _cv_required(view: dict, name: str) -> list[str]:
    """Text the CV text layer must contain: the name, the summary opening, every contact item."""
    summary = [view["summary"][:40]] if view["summary"] else []
    return [name, *summary, *(link["text"] for link in view["contact"]["links"])]


def _engine(cfg: Config, name: str) -> str:
    engine = getattr(cfg, name)
    if not engine:
        raise LatexError(f"no {name} engine configured")
    return engine


def _report(label: str, report: AtsReport) -> None:
    status = "ok" if report.ok else "FAILED"
    print(f"{label}: {status} ({report.pages} page(s), {report.extractor or 'no extractor'})")
    for problem in report.problems:
        print(f"  - {problem}")


def _publish(pdf: Path, out: Path, filename: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    dest = out / filename
    shutil.copyfile(pdf, dest)
    return dest


def _print_findings(findings: list[Finding]) -> None:
    for f in findings:
        print(f"{f.kind} {f.ref}: {f.message}")


def _confidential_blocked(master: dict, **rendered) -> bool:
    """The one confidential-term check on everything about to be compiled (None parts are skipped)."""
    findings = audit_rendered(master, **rendered)
    _print_findings(findings)
    return bool(findings)


def cmd_validate(args) -> int:
    load_master(Path(args.master))
    print("ok")
    return 0


def cmd_audit(args) -> int:
    findings = audit(load_tailored(Path(args.tailored)), load_master(Path(args.master)))
    _print_findings(findings)
    return 1 if findings else 0


def cmd_build(args) -> int:
    master = load_master(Path(args.master))
    tailored = load_tailored(Path(args.tailored))
    findings = audit(tailored, master)
    if findings:
        _print_findings(findings)
        return 1
    view = build_cv_view(tailored, master)
    letter = letter_context(tailored, master) if tailored.get("letter") and not args.no_letter else None
    if _confidential_blocked(master, cv=view, letter=letter):
        return 1
    cfg = load_config()
    target = tailored["target"]
    first, last = name_parts(master["basics"]["name"])
    company = file_part(target["company"])
    out = Path(args.out) if args.out else (
        cfg.data_dir / "applications" / f"{slug(target['company'])}-{slug(target['role'])}")
    name = master["basics"]["name"]

    cv_pdf = compile_tex(render_view(view), engine=_engine(cfg, "lualatex"),
                         build_dir=cfg.build_dir, jobname="cv", assets=ASSETS_DIR)
    cv_report = ats_check(cv_pdf, max_pages=2, required=_cv_required(view, name),
                          headings=_headings(view))
    dest = _publish(cv_pdf, out, f"{first}_{last}_CV_{company}.pdf")
    print(f"CV: {dest}")
    _report("CV", cv_report)
    ok = cv_report.ok

    if letter:
        letter_pdf = compile_tex(render_letter_context(letter), engine=_engine(cfg, "xelatex"),
                                 build_dir=cfg.build_dir, jobname="letter", assets=ASSETS_DIR)
        letter_report = ats_check(letter_pdf, max_pages=1, exact_pages=True, required=[name])
        dest = _publish(letter_pdf, out, f"{first}_{last}_Cover_Letter_{company}.pdf")
        print(f"Letter: {dest}")
        _report("Letter", letter_report)
        ok = ok and letter_report.ok
    return 0 if ok else 1


def cmd_master_cv(args) -> int:
    master = load_master(Path(args.master))
    tailored = untailored(master, args.lang, args.angle)
    view = build_cv_view(tailored, master)
    if _confidential_blocked(master, cv=view):
        return 1
    cfg = load_config()
    first, last = name_parts(master["basics"]["name"])
    out = Path(args.out) if args.out else cfg.data_dir / "review"
    pdf = compile_tex(render_view(view), engine=_engine(cfg, "lualatex"),
                      build_dir=cfg.build_dir, jobname="cv", assets=ASSETS_DIR)
    report = ats_check(pdf, max_pages=LARGE_PAGE_CAP,
                       required=_cv_required(view, master["basics"]["name"]), headings=_headings(view))
    dest = _publish(pdf, out, f"{first}_{last}_CV_master_{args.lang}.pdf")
    print(f"Master CV: {dest}")
    _report("Master CV (informational)", report)
    return 0


def cmd_guard(args) -> int:
    if args.what == "staged":
        problems = check_staged(load_config())
    elif args.what == "tree":
        problems = check_tree(load_config())
    else:
        problems = check_message_file(Path(args.file), load_config())
    for problem in problems:
        print(problem)
    return 1 if problems else 0


def _today() -> date:
    return date.today()


def cmd_track(args) -> int:
    cfg = load_config()
    path = cfg.data_dir / "tracker.csv"
    app_dir = cfg.data_dir / "applications" / args.slug
    today = _today()
    if args.action in ("stage", "done") and not any(
            r["slug"] == args.slug for r in tracker.load(path)
        ):
        print(f"unknown slug '{args.slug}'", file=sys.stderr)
        return 1
    if args.action == "add":
        rows = tracker.load(path)
        existing = next((r for r in rows if r["slug"] == args.slug), None) or tracker.find(
            rows, url=args.url, company=args.company, role=args.role)
        if existing:
            print(f"already tracked: {existing['slug']} ({existing['status']})")
            return 3
        row = {"slug": args.slug, "company": args.company, "role": args.role,
               "date": today.isoformat(), "status": "drafted"}
        for key in ("url", "channel", "source", "deadline"):
            if getattr(args, key):
                row[key] = getattr(args, key)
        if row.get("channel") and row["channel"] not in tracker.CHANNELS:
            print(f"unknown channel '{row['channel']}'", file=sys.stderr)
            return 1
        tracker.upsert(path, row)
        print(f"added {args.slug}")
    elif args.action == "status":
        if args.status == "applied":
            count = tracker.applied_on(tracker.load(path), today)
            if count >= cfg.daily_cap:
                print(f"warning: daily cap reached ({count} applied today, cap {cfg.daily_cap})")
        try:
            tracker.set_status(path, args.slug, args.status, today, note=args.note or "")
        except (KeyError, ValueError) as exc:
            print(str(exc.args[0]), file=sys.stderr)
            return 1
        print(f"{args.slug}: {args.status}")
    elif args.action == "stage":
        try:
            due = date.fromisoformat(args.due) if args.due else None
            stages_mod.add_stage(app_dir, args.name, args.kind, due)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"stage added: {args.name}")
    else:
        try:
            stages_mod.complete_stage(app_dir, args.name)
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            return 1
        print(f"stage done: {args.name}")
    return 0


def cmd_due(args) -> int:
    cfg = load_config()
    report = due_report(tracker.load(cfg.data_dir / "tracker.csv"),
                        cfg.data_dir / "applications", _today())
    print("Stages")
    for slug_, st in report.stages:
        print(f"  {slug_}: {st.name} ({st.kind}) due {st.due}")
    print("Follow up")
    for row in report.followups:
        print(f"  {row['slug']}: {row['company']} / {row['role']} ({row['status']}, last update {row['last_update'] or row['date']})")
    print("Stale")
    for row in report.stale:
        print(f"  {row['slug']}: {row['company']} / {row['role']} ({row['status']}, last update {row['last_update'] or row['date']})")
    for error in report.errors:
        print(f"bad stages file, {error}", file=sys.stderr)
    return 1 if report.errors else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cvforge")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate", help="validate a master profile")
    p.add_argument("master")
    p.set_defaults(func=cmd_validate)
    p = sub.add_parser("audit", help="audit a tailored selection against the master")
    p.add_argument("tailored")
    p.add_argument("--master", required=True)
    p.set_defaults(func=cmd_audit)
    p = sub.add_parser("build", help="audit, render, compile and check a CV and letter")
    p.add_argument("tailored")
    p.add_argument("--master", required=True)
    p.add_argument("--out")
    p.add_argument("--no-letter", action="store_true")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("master-cv", help="build an untailored full CV for review")
    p.add_argument("master")
    p.add_argument("--lang", required=True, choices=["en", "pt-BR", "pt-PT"])
    p.add_argument("--angle")
    p.add_argument("--out")
    p.set_defaults(func=cmd_master_cv)
    p = sub.add_parser("guard", help="privacy and attribution checks for git hooks")
    guard = p.add_subparsers(dest="what", required=True)
    guard.add_parser("staged", help="check staged files")
    guard.add_parser("tree", help="check every tracked file")
    msg = guard.add_parser("msg", help="check a commit message file")
    msg.add_argument("file")
    p.set_defaults(func=cmd_guard)
    p = sub.add_parser("track", help="record and update applications")
    track = p.add_subparsers(dest="action", required=True)
    t = track.add_parser("add", help="add an application as drafted")
    t.add_argument("slug")
    t.add_argument("--company", required=True)
    t.add_argument("--role", required=True)
    for opt in ("url", "channel", "source", "deadline"):
        t.add_argument(f"--{opt}")
    t = track.add_parser("status", help="set an application status")
    t.add_argument("slug")
    t.add_argument("status", choices=tracker.STATUSES)
    t.add_argument("--note")
    t = track.add_parser("stage", help="add a stage to an application")
    t.add_argument("slug")
    t.add_argument("name")
    t.add_argument("--kind", required=True, choices=stages_mod.KINDS)
    t.add_argument("--due")
    t = track.add_parser("done", help="mark a stage done")
    t.add_argument("slug")
    t.add_argument("name")
    p.set_defaults(func=cmd_track)
    p = sub.add_parser("due", help="stages, follow-ups and stale applications")
    p.set_defaults(func=cmd_due)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (ProfileError, LatexError, GuardError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
