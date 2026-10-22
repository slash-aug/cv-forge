"""Command line interface: validate, audit, build, master-cv."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
import unicodedata
from pathlib import Path

from cvforge.build import LatexError, compile_tex
from cvforge.checks.ats import AtsReport, ats_check
from cvforge.config import Config, load_config
from cvforge.guard import GuardError, check_message_file, check_staged, check_tree
from cvforge.profile.model import ProfileError, load_master, localized
from cvforge.render.cv import build_cv_view, render_view
from cvforge.render.letter import ASSETS_DIR, letter_context, render_letter_context
from cvforge.tailor.audit import Finding, audit, audit_rendered, load_tailored

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
    required = [name] + ([view["summary"][:40]] if view["summary"] else [])
    cv_report = ats_check(cv_pdf, max_pages=2, required=required, headings=_headings(view))
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
    report = ats_check(pdf, max_pages=LARGE_PAGE_CAP, required=[master["basics"]["name"]],
                       headings=_headings(view))
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
