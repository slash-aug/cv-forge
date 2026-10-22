"""Command line interface: validate, audit, build, master-cv, intake, check, track."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from cvforge.answers.bank import load_bank, lookup, save_answers
from cvforge.answers.facts import knockout_facts
from cvforge.apply import http as apply_http
from cvforge.apply.check import Verdict, check
from cvforge.apply.companies import (
    add_company,
    add_sponsor,
    find_company,
    load_registry,
)
from cvforge.apply.experience import engineering_months
from cvforge.apply.intake import (
    IntakeError,
    fetch_posting,
    posting_from_text,
    refuse_linkedin,
    resolve_shortlink,
)
from cvforge.apply.posting import Posting, canonical_url
from cvforge.apply.requirements import load_requirements, posting_text, quote_problems
from cvforge.apply.workspace import create_app_dir
from cvforge.build import LatexError, compile_tex
from cvforge.checks.ats import AtsReport, ats_check
from cvforge.config import Config, ConfigError, load_config
from cvforge.guard import GuardError, check_message_file, check_staged, check_tree
from cvforge.kit.data import build_kit
from cvforge.kit.render import render_kit
from cvforge.money.normalise import Money
from cvforge.money.rates import MoneyError, load_rates
from cvforge.profile.model import ProfileError, load_master, localized
from cvforge.render.cv import build_cv_view, render_view
from cvforge.render.letter import ASSETS_DIR, letter_context, render_letter_context
from cvforge.salary.market import load_market, match_market
from cvforge.salary.suggest import Suggestion, below_floor, displays, suggest
from cvforge.tailor.audit import Finding, audit, audit_rendered, figures, load_tailored
from cvforge.text import file_part, split_name
from cvforge.track import stages as stages_mod
from cvforge.track import tracker
from cvforge.track.due import due_report

SECTIONS = ("summary", "experience", "skills", "education", "certificates", "languages")
LARGE_PAGE_CAP = 1000


def name_parts(name: str) -> tuple[str, str]:
    first, last = split_name(name)
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


class DataError(Exception):
    """A file under the data directory that cannot be used as it is."""


SALARY_KEYS = ("amount", "currency", "period", "brl_month", "eur_year", "usd_year")


def _load_salary(app_dir: Path) -> dict | None:
    """salary.json as written by `cvforge salary`, or None; a damaged file is a DataError."""
    path = app_dir / "salary.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DataError(f"{path}: unreadable ({exc}); rerun cvforge salary") from None
    if not isinstance(data, dict):
        raise DataError(f"{path}: expected an object; rerun cvforge salary")
    if data.get("confirmed"):
        missing = [k for k in SALARY_KEYS if k not in data]
        if missing:
            raise DataError(f"{path}: missing {', '.join(missing)}; rerun cvforge salary")
        try:
            for key in ("amount", "brl_month", "eur_year", "usd_year"):
                data[key] = float(data[key])
        except (TypeError, ValueError):
            raise DataError(f"{path}: {key} is not a number; rerun cvforge salary") from None
    return data


def _answer_figures(master: dict, lang: str, app_dir: Path) -> set[str]:
    """Numbers an honest screening answer may hold that no highlight has: the knock-out facts
    (years from dates, notice) and, once confirmed, the salary as `cvforge salary` shows it."""
    facts = knockout_facts(master, engineering_months(master, _today()), lang)
    found = figures(*facts.values())
    salary = _load_salary(app_dir)
    if salary and salary.get("confirmed"):
        amount = salary["amount"]
        found |= figures(f"{amount:g}", f"{amount:.0f}", f"{amount:,.0f}", f"{amount:,.2f}")
        for key in ("brl_month", "eur_year", "usd_year"):
            found |= figures(f"{salary[key]:.0f}", f"{salary[key]:,.0f}")
    return found


def _audit_tailored(tailored: dict, master: dict, app_dir: Path) -> list[Finding]:
    return audit(tailored, master,
                 extra_allowed=_answer_figures(master, tailored["lang"], app_dir))


def cmd_audit(args) -> int:
    path = Path(args.tailored)
    master = load_master(Path(args.master))
    findings = _audit_tailored(load_tailored(path), master, path.resolve().parent)
    _print_findings(findings)
    return 1 if findings else 0


def cmd_build(args) -> int:
    master = load_master(Path(args.master))
    tailored_path = Path(args.tailored)
    tailored = load_tailored(tailored_path)
    findings = _audit_tailored(tailored, master, tailored_path.resolve().parent)
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
    # Default: next to the tailored.yaml, which is the application folder intake created.
    out = Path(args.out) if args.out else tailored_path.resolve().parent
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


def cmd_intake(args) -> int:
    cfg = load_config()
    path = cfg.data_dir / "tracker.csv"
    today = _today()
    if args.channel and args.channel not in tracker.CHANNELS:
        print(f"unknown channel '{args.channel}'", file=sys.stderr)
        return 1
    paste = args.target == "-"
    if paste and not (args.company and args.role):
        print("pasted text needs --company and --role", file=sys.stderr)
        return 1

    def tracked(**kw) -> bool:
        existing = tracker.find(tracker.load(path), **kw)
        if existing and not args.force:
            print(f"already tracked: {existing['slug']} ({existing['status']})")
            return True
        return False

    try:
        if paste:
            if tracked(company=args.company, role=args.role):
                return 3
            posting = posting_from_text(sys.stdin.read(), company=args.company, role=args.role,
                                        url="", today=today)
        else:
            url = canonical_url(resolve_shortlink(args.target, apply_http.get))
            refuse_linkedin(url)
            if tracked(url=url):
                return 3
            posting = fetch_posting(url, get=apply_http.get, today=today)
            posting.company = args.company or posting.company
            posting.title = args.role or posting.title
            if tracked(company=posting.company, role=posting.title):
                return 3
    except (IntakeError, apply_http.FetchError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    app_dir = create_app_dir(cfg.data_dir / "applications", posting.company, posting.title)
    try:
        posting.save(app_dir)
    except Exception as exc:
        shutil.rmtree(app_dir, ignore_errors=True)  # no half-written folder to trip the next run
        if not isinstance(exc, OSError):
            raise
        print(f"posting not saved: {exc}", file=sys.stderr)
        return 1
    row = {"slug": app_dir.name, "company": posting.company, "role": posting.title,
           "date": today.isoformat(), "status": "drafted", "source": posting.source, "url": posting.url}
    if args.channel:
        row["channel"] = args.channel
    tracker.upsert(path, row)
    print(app_dir.name)
    print(posting.guard["verdict"])
    print(f"language: {posting.language or 'unknown'}")
    return 0


def cmd_track(args) -> int:
    cfg = load_config()
    path = cfg.data_dir / "tracker.csv"
    app_dir = cfg.data_dir / "applications" / args.slug
    today = _today()
    if args.action == "show":
        return _show_application(path, app_dir, args.slug, today)
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
        except stages_mod.StagesError as exc:
            print(f"bad stages file, {exc}", file=sys.stderr)
            return 1
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"stage added: {args.name}")
    else:
        try:
            stages_mod.complete_stage(app_dir, args.name)
        except stages_mod.StagesError as exc:
            print(f"bad stages file, {exc}", file=sys.stderr)
            return 1
        except KeyError as exc:
            print(str(exc.args[0]), file=sys.stderr)
            return 1
        print(f"stage done: {args.name}")
    return 0


SHOW_FIELDS = ("slug", "status", "channel", "date", "last_update", "company", "role", "url",
               "notes", "skip_reason")


def _show_application(path: Path, app_dir: Path, slug_: str, today: date) -> int:
    """Read-only view of one tracker row and its stages."""
    row = next((r for r in tracker.load(path) if r["slug"] == slug_), None)
    if row is None:
        print(f"unknown slug '{slug_}'", file=sys.stderr)
        return 1
    for key in SHOW_FIELDS:
        print(f"{key}: {row[key] or '-'}")
    try:
        quiet = (today - date.fromisoformat(row["last_update"] or row["date"])).days
    except ValueError:
        quiet = None
    print(f"days_quiet: {quiet if quiet is not None else '-'}")
    try:
        found = stages_mod.load_stages(app_dir)
    except stages_mod.StagesError as exc:
        print(f"bad stages file, {exc}", file=sys.stderr)
        return 1
    print("stages:" + ("" if found else " -"))
    for st in found:
        print(f"  {st.name} ({st.kind}) due {st.due or '-'}, {'done' if st.done else 'open'}")
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


def _write_verdict(app_dir: Path, today: date, verdict: str, *, results: Verdict | None = None,
                   problems=(), override: str | None = None) -> None:
    data = {"verdict": verdict, "checked": today.isoformat(), "override": override,
            "problems": list(problems), "results": [], "warnings": [], "caveats": {}}
    if results is not None:
        data["results"] = [asdict(r) for r in results.results]
        data["warnings"] = results.warnings
        data["caveats"] = results.caveats
    (app_dir / "verdict.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _salary_stated(req: dict) -> bool:
    salary = req.get("salary") or {}
    return salary.get("max") is not None or salary.get("min") is not None


def _print_caveats(caveats: dict) -> None:
    """Information only: caveats never change the verdict or the exit code."""
    for key, label in (("hiring_model", "hiring model"), ("timezone", "time zone"),
                       ("travel", "travel")):
        item = caveats.get(key)
        if item:
            print(f"INFO {label}: {item.get('type') or item.get('requirement')}")
            print(f'    "{item["quote"]}"')
    for sentence in caveats.get("uncaptured", []):
        print(f'WARN uncaptured: "{sentence}"')


def cmd_check(args) -> int:
    cfg = load_config()
    app_dir = cfg.data_dir / "applications" / args.slug
    if not (app_dir / "posting.json").exists():
        print(f"unknown slug '{args.slug}'", file=sys.stderr)
        return 1
    today = _today()
    posting = Posting.load(app_dir)
    try:
        req = load_requirements(app_dir / "requirements.yaml")
    except ProfileError as exc:
        print(str(exc))
        _write_verdict(app_dir, today, "invalid", problems=[str(exc)])
        return 1
    problems = quote_problems(req, posting_text(posting))
    if problems:
        for problem in problems:
            print(problem)
        _write_verdict(app_dir, today, "invalid", problems=problems)
        return 1
    master = load_master(Path(args.master) if args.master
                         else cfg.data_dir / "profile" / "master.yaml")
    company = find_company(load_registry(cfg.data_dir / "companies.yaml"), posting.company)
    try:
        rates = (load_rates(cfg.data_dir / "salary", today, apply_http.get)
                 if _salary_stated(req) else None)
        verdict = check(req, posting, master, company, rates, today, clt_factor=cfg.clt_factor)
    except MoneyError as exc:
        print(str(exc), file=sys.stderr)
        _write_verdict(app_dir, today, "invalid", problems=[str(exc)])
        return 1
    for r in verdict.results:
        print(f"{'PASS' if r.ok else 'SKIP'} {r.rule}: {r.message}")
        if r.quote:
            print(f'    "{r.quote}"')
    for warning in verdict.warnings:
        print(f"warning: {warning}")
    _print_caveats(verdict.caveats)
    path = cfg.data_dir / "tracker.csv"
    current = next((r["status"] for r in tracker.load(path) if r["slug"] == args.slug), "")
    if verdict.passed:
        _write_verdict(app_dir, today, "pass", results=verdict)
        if current == "skipped":  # an earlier skip no longer holds
            _track(path, args.slug, "drafted", today, clear_skip_reason=True)
        print("verdict: pass")
        return 0
    if args.override:
        _write_verdict(app_dir, today, "pass", results=verdict, override=args.override)
        status = "drafted" if current in ("", "skipped") else current
        _track(path, args.slug, status, today, note=f"override: {args.override}",
               clear_skip_reason=current == "skipped")
        print(f"verdict: pass (override: {args.override})")
        return 0
    _write_verdict(app_dir, today, "skip", results=verdict)
    reason = "; ".join(f"{r.rule}: {r.message}" for r in verdict.results if not r.ok)
    _track(path, args.slug, "skipped", today, skip_reason=reason)
    print("verdict: skip")
    return 2


def _seniority(title: str) -> str:
    words = set(title.casefold().replace("-", " ").split())
    if words & {"senior", "sr", "sr.", "staff", "principal", "lead"}:
        return "senior"
    if words & {"junior", "jr", "jr.", "intern", "trainee"}:
        return "junior"
    return "mid"


def cmd_answers(args) -> int:
    """Look up pasted questions in the answer bank, or save audited answers to it."""
    cfg = load_config()
    app_dir = cfg.data_dir / "applications" / args.slug
    if not app_dir.is_dir():
        print(f"unknown slug '{args.slug}'", file=sys.stderr)
        return 1
    master = load_master(Path(args.master) if args.master
                         else cfg.data_dir / "profile" / "master.yaml")
    bank_path = cfg.data_dir / "answers" / "bank.yaml"
    if args.save:
        tailored_path = app_dir / "tailored.yaml"
        if not tailored_path.exists():
            print(f"no tailored.yaml for '{args.slug}'", file=sys.stderr)
            return 1
        tailored = load_tailored(tailored_path)
        findings = _audit_tailored(tailored, master, app_dir)
        if findings:
            for f in findings:
                print(f"{f.kind} {f.ref}: {f.message}", file=sys.stderr)
            print("answers not saved: audit failed", file=sys.stderr)
            return 1
        n = save_answers(bank_path, tailored.get("answers") or [], tailored["lang"], _today())
        print(f"saved {n} answer(s) to {bank_path}")
        return 0
    lang = args.lang
    if not lang and (app_dir / "tailored.yaml").exists():
        lang = load_tailored(app_dir / "tailored.yaml")["lang"]
    lang = lang or "en"
    q_path = app_dir / "questions.txt"
    if q_path.exists():
        bank = load_bank(bank_path)
        for line in q_path.read_text(encoding="utf-8").splitlines():
            question = line.strip()
            if not question:
                continue
            hit = lookup(bank, question, lang)
            print(f"Q: {question}")
            print(f"A: {hit['answer']}" if hit else "NEW")
    facts = knockout_facts(master, engineering_months(master, _today()), lang)
    print("Knock-out facts:")
    for k, v in facts.items():
        print(f"  {k}: {v}")
    return 0


def cmd_salary(args) -> int:
    """Suggest an expected salary; the kit shows it only once confirmed.

    Market country: requirements location.job_countries[0] when present, else the
    master's basics.location.countryCode (a remote job open to the candidate's country).
    """
    cfg = load_config()
    app_dir = cfg.data_dir / "applications" / args.slug
    if not (app_dir / "posting.json").exists():
        print(f"unknown slug '{args.slug}'", file=sys.stderr)
        return 1
    posting = Posting.load(app_dir)
    req_path = app_dir / "requirements.yaml"
    req = load_requirements(req_path) if req_path.exists() else None
    master = load_master(Path(args.master) if args.master
                         else cfg.data_dir / "profile" / "master.yaml")
    pay_floor = (master.get("x-preferences") or {}).get("payFloor")
    if not pay_floor:
        print("master has no x-preferences.payFloor", file=sys.stderr)
        return 1
    floor = Money(pay_floor["amount"], pay_floor["currency"], pay_floor["period"])
    countries = ((req or {}).get("location") or {}).get("job_countries") or []
    country = countries[0] if countries else (
        (master.get("basics") or {}).get("location") or {}).get("countryCode", "")
    market_path = Path(args.market) if args.market else cfg.data_dir / "salary" / "market.csv"
    rows = match_market(load_market(market_path), role=posting.title,
                        seniority=_seniority(posting.title), country=country)
    confirm_amount = None
    if args.confirm:
        try:
            confirm_amount = float(args.confirm)
        except ValueError:
            confirm_amount = float("nan")
        if not math.isfinite(confirm_amount) or confirm_amount <= 0:
            print(f"invalid amount '{args.confirm}': must be a positive number", file=sys.stderr)
            return 1
    try:
        rates = load_rates(cfg.data_dir / "salary", _today(), apply_http.get)
        s = suggest((req or {}).get("salary") if req and _salary_stated(req) else None,
                    rows, floor, rates, clt_factor=cfg.clt_factor)
        if confirm_amount is not None:
            amount = confirm_amount
            contract = ((req or {}).get("salary") or {}).get("contract") \
                if s.basis == "posting" else "unknown"
            if below_floor(amount, s.currency, s.period, contract or "unknown", floor, rates,
                           clt_factor=cfg.clt_factor):
                print(f"warning: {amount:,.0f} {s.currency}/{s.period} is below your pay floor "
                      f"({pay_floor['amount']} {pay_floor['currency']}/{pay_floor['period']})"
                      f"{' (CLT basis x' + str(cfg.clt_factor) + ')' if contract == 'clt' else ''}",
                      file=sys.stderr)
            brl, eur, usd = displays(amount, s.currency, s.period, rates)
            s = Suggestion(s.basis, amount, s.currency, s.period, brl, eur, usd,
                           [*s.sources, "amount set by candidate"])
    except MoneyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    data = {**asdict(s), "confirmed": args.confirm is not None, "rates_day": rates.day}
    (app_dir / "salary.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Suggested ({s.basis}): {s.amount:,.0f} {s.currency}/{s.period}")
    print(f"  BRL/month: {s.brl_month:,.0f}")
    print(f"  EUR/year:  {s.eur_year:,.0f}")
    print(f"  USD/year:  {s.usd_year:,.0f}")
    print(f"  Rates: ECB {rates.day}")
    for src in s.sources:
        print(f"  Source: {src}")
    print("confirmed" if data["confirmed"] else "not confirmed: rerun with --confirm [AMOUNT]")
    return 0


def _windows_path(path: Path) -> str | None:
    """The Windows form of a WSL path, or None when wslpath is missing or fails."""
    try:
        done = subprocess.run(["wslpath", "-w", str(path)], check=False, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None if done.returncode == 0 else None


def cmd_kit(args) -> int:
    """Write kit.json and kit.html for an application and print where to open them."""
    cfg = load_config()
    app_dir = cfg.data_dir / "applications" / args.slug
    if not (app_dir / "posting.json").exists():
        print(f"unknown slug '{args.slug}'", file=sys.stderr)
        return 1
    if not (app_dir / "tailored.yaml").exists():
        print(f"no tailored.yaml for '{args.slug}'", file=sys.stderr)
        return 1
    posting = Posting.load(app_dir)
    master = load_master(Path(args.master) if args.master
                         else cfg.data_dir / "profile" / "master.yaml")
    tailored = load_tailored(app_dir / "tailored.yaml")
    salary = _load_salary(app_dir)
    first, last = name_parts(master["basics"]["name"])
    company = file_part(tailored["target"]["company"])
    names = {"cv_pdf": f"{first}_{last}_CV_{company}.pdf",
             "letter_pdf": f"{first}_{last}_Cover_Letter_{company}.pdf"}
    files = {k: v for k, v in names.items() if (app_dir / v).exists()}
    findings = _audit_tailored(tailored, master, app_dir)
    kit = build_kit(master, tailored, posting, salary, slug=args.slug, files=files)
    findings += audit_rendered(master, kit=kit)
    if findings:
        _print_findings(findings)
        print("kit not written: audit failed", file=sys.stderr)
        return 1
    (app_dir / "kit.json").write_text(
        json.dumps(kit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html = app_dir / "kit.html"
    html.write_text(render_kit(kit), encoding="utf-8")
    print(_windows_path(html) or html)
    return 0


def _track(path: Path, slug_: str, status: str, today: date, **kw) -> None:
    try:
        tracker.set_status(path, slug_, status, today, **kw)
    except KeyError as exc:
        print(f"warning: {exc.args[0]}; tracker not updated", file=sys.stderr)


def _format_company(entry: dict) -> str:
    lines = [f"name: {entry['name']}"]
    lines.append("aliases: " + (", ".join(entry["aliases"]) or "-"))
    lines.append(f"careers_url: {entry.get('careers_url') or '-'}")
    lines.append(f"ats: {entry.get('ats') or '-'}")
    lines.append("sponsor:" + ("" if entry["sponsor"] else " -"))
    for s in entry["sponsor"]:
        lines.append(f"  {s['type']} ({s['source']}, {s['date']})")
    if entry.get("notes"):
        lines.append(f"notes: {entry['notes']}")
    return "\n".join(lines)


def cmd_company(args) -> int:
    path = load_config().data_dir / "companies.yaml"
    try:
        if args.action == "add":
            entry = add_company(path, args.name, careers_url=args.careers, ats=args.ats,
                                aliases=args.alias)
        elif args.action == "sponsor":
            day = date.fromisoformat(args.date) if args.date else _today()
            entry = add_sponsor(path, args.name, type=args.type, source=args.source, day=day)
        else:
            entry = find_company(load_registry(path), args.name)
            if entry is None:
                print(f"unknown company '{args.name}'", file=sys.stderr)
                return 1
            print(_format_company(entry))
            return 0
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"{args.action}: {entry['name']}")
    return 0


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
    t = track.add_parser("show", help="show an application's tracker row and stages")
    t.add_argument("slug")
    p.set_defaults(func=cmd_track)
    p = sub.add_parser("intake", help="save a posting from a link or pasted text and track it")
    p.add_argument("target", help="job link, or - to read pasted text from stdin")
    p.add_argument("--company")
    p.add_argument("--role")
    p.add_argument("--channel")
    p.add_argument("--force", action="store_true", help="intake even if already tracked")
    p.set_defaults(func=cmd_intake)
    p = sub.add_parser("company", help="company registry and visa sponsor marks")
    company = p.add_subparsers(dest="action", required=True)
    c = company.add_parser("add", help="add a company or fill in its details")
    c.add_argument("name")
    c.add_argument("--careers")
    c.add_argument("--ats")
    c.add_argument("--alias", action="append", default=[])
    c = company.add_parser("sponsor", help="mark a company as a visa sponsor")
    c.add_argument("name")
    c.add_argument("--type", required=True)
    c.add_argument("--source", required=True)
    c.add_argument("--date")
    c = company.add_parser("show", help="show a company")
    c.add_argument("name")
    p.set_defaults(func=cmd_company)
    p = sub.add_parser("check", help="eligibility check of a posting against requirements.yaml")
    p.add_argument("slug")
    p.add_argument("--master", help="master profile (default: <data_dir>/profile/master.yaml)")
    p.add_argument("--override", metavar="REASON", help="continue past a skip and record why")
    p.set_defaults(func=cmd_check)
    p = sub.add_parser("salary", help="suggest an expected salary for the application form")
    p.add_argument("slug")
    p.add_argument("--confirm", nargs="?", const="", metavar="AMOUNT",
                   help="confirm the suggestion, optionally replacing the amount")
    p.add_argument("--market", help="market CSV (default: <data_dir>/salary/market.csv)")
    p.add_argument("--master", help="master profile (default: <data_dir>/profile/master.yaml)")
    p.set_defaults(func=cmd_salary)
    p = sub.add_parser("kit", help="write kit.json and kit.html to copy into application forms")
    p.add_argument("slug")
    p.add_argument("--master", help="master profile (default: <data_dir>/profile/master.yaml)")
    p.set_defaults(func=cmd_kit)
    p = sub.add_parser("answers", help="answer bank lookup and knock-out facts")
    p.add_argument("slug")
    p.add_argument("--save", action="store_true",
                   help="audit tailored.yaml and save its answers to the bank")
    p.add_argument("--lang", help="answer language (default: tailored.yaml lang, else en)")
    p.add_argument("--master", help="master profile (default: <data_dir>/profile/master.yaml)")
    p.set_defaults(func=cmd_answers)
    p = sub.add_parser("due", help="stages, follow-ups and stale applications")
    p.set_defaults(func=cmd_due)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.func(args)
    except (ProfileError, LatexError, GuardError, ConfigError, DataError, MoneyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:  # a damaged JSON file under the data directory
        print(f"unreadable JSON file: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
