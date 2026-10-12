#!/usr/bin/env python3
"""Controlli deterministici per outreach-sequencer (solo libreria standard).

  lint_plan.py check-context            profile/positioning esistono e sono compilati
  lint_plan.py lint PLAN [--tracker]    limiti di lunghezza, struttura, proof point
  lint_plan.py track PLAN               lint + append righe in tracker.csv (dedupe)
"""
import argparse
import csv
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORIES = {"warm_path", "headhunter", "hiring_manager", "recruiter_interno"}
LIMITS = {  # tipo blocco -> (unità, massimo)
    "linkedin": ("chars", 300),
    "message": ("words", 120),
    "intro": ("words", 120),
    "followup-d5": ("words", 120),
    "closing-d12": ("words", 120),
}
TRACKER_COLS = ["azienda", "ruolo", "persona", "categoria", "canale",
                "data_contatto", "prossimo_followup", "stato"]
BANNED = [  # cortesie vuote e aggettivi autocelebrativi
    "spero che questa", "spero stia bene", "i hope this", "hope you are well",
    "appassionat", "visionari", "eccellenza", "dinamic", "passionate",
    "results-driven", "world-class", "esperto di successo",
]
ALLOWED_NUMBERS = {"15"}  # "15 minuti" è la richiesta standard
FENCE = re.compile(r"```([\w-]+)\n(.*?)```", re.DOTALL)
FIELD = re.compile(r"^([A-Za-zÀ-ÿ][^:\n]{0,30}):[ \t]*(.*)$", re.MULTILINE)


def parse_fields(text):
    return {k.strip().lower(): v.strip() for k, v in FIELD.findall(FENCE.sub("", text))}


def words(s):
    return len(s.split())


def check_context(root):
    errors = []
    for name in ("profile.md", "positioning.md"):
        p = root / "context" / name
        if not p.exists():
            errors.append(f"manca context/{name} (copia da templates/{name[:-3]}.template.md)")
        elif "<<" in p.read_text(encoding="utf-8"):
            errors.append(f"context/{name} contiene ancora segnaposto <<...>>")
    return errors


def lint(plan_path, root, check_tracker=False):
    errors, warnings = [], []
    text = plan_path.read_text(encoding="utf-8")
    if not re.match(r"\d{4}-\d{2}-\d{2}_.+\.md$", plan_path.name):
        errors.append("nome file atteso: AAAA-MM-GG_azienda_ruolo.md")
    head = parse_fields(text.split("\n## ", 1)[0])
    for k in ("azienda", "ruolo", "data", "fit"):
        if not head.get(k):
            errors.append(f"intestazione: manca '{k.capitalize()}:'")
    if "skip" in head.get("fit", "").lower():
        errors.append("fit = SKIP: per i ruoli SKIP non si crea nessun piano")
    profile_file = root / "context" / "profile.md"
    profile = profile_file.read_text(encoding="utf-8") if profile_file.exists() else ""
    if not profile:
        errors.append("context/profile.md assente: impossibile validare i proof point")

    sections = re.split(r"(?m)^### (?=P\d)", text)[1:]
    if not 1 <= len(sections) <= 5:
        errors.append(f"persone nel piano: {len(sections)} (ammesse 1-5)")
    cats = []
    for sec in sections:
        title = sec.splitlines()[0]
        tag = f"[{title[:40]}]"
        f = parse_fields(sec)
        cat = f.get("categoria", "")
        cats.append(cat)
        if cat not in CATEGORIES:
            errors.append(f"{tag} categoria '{cat}' non valida {sorted(CATEGORIES)}")
        for k in ("persona", "confidenza", "canale"):
            if not f.get(k):
                errors.append(f"{tag} manca '{k.capitalize()}:'")
        if "[ricerca manuale]" in f.get("persona", "").lower() and not f.get("ricerca linkedin"):
            errors.append(f"{tag} nome non trovato: serve 'Ricerca LinkedIn:' esatta")
        try:
            d0 = date.fromisoformat(f.get("data d0", ""))
            for lab, delta in (("data d+5", 5), ("data d+12", 12)):
                if f.get(lab) != (d0 + timedelta(days=delta)).isoformat():
                    errors.append(f"{tag} '{lab}' deve essere D0+{delta} = {d0 + timedelta(days=delta)}")
        except ValueError:
            errors.append(f"{tag} 'Data D0' mancante o non ISO (AAAA-MM-GG)")

        blocks = {}
        for kind, body in FENCE.findall(sec):
            blocks.setdefault(kind, []).append(body.strip())
        required = ["followup-d5", "closing-d12"]
        required += ["intro"] if cat == "warm_path" else ["linkedin", "message"]
        for kind in required:
            if kind not in blocks:
                errors.append(f"{tag} manca il blocco ```{kind}")
        for kind, bodies in blocks.items():
            if kind not in LIMITS:
                errors.append(f"{tag} tipo blocco sconosciuto '{kind}'")
                continue
            if len(bodies) > 1:
                errors.append(f"{tag} più blocchi ```{kind} (max 1; max 2 follow-up in totale)")
            unit, mx = LIMITS[kind]
            for b in bodies:
                n = len(b) if unit == "chars" else words(b)
                if n > mx:
                    errors.append(f"{tag} {kind}: {n} {unit} > {mx}")
                low = b.lower()
                for bad in BANNED:
                    if bad in low:
                        errors.append(f"{tag} {kind}: formula vietata '{bad}'")
                for num in re.findall(r"\d[\d.,]*\d|\d", b):
                    num = num.rstrip(".,")
                    if num not in ALLOWED_NUMBERS and num not in profile:
                        errors.append(f"{tag} {kind}: numero '{num}' assente da profile.md")

    if "hiring_manager" not in cats:
        errors.append("manca almeno 1 persona hiring_manager")
    if not {"warm_path", "headhunter"} & set(cats):
        errors.append("serve almeno 1 warm_path o 1 headhunter oltre all'hiring manager")

    if check_tracker:
        rows = read_tracker(root)
        for sec in sections:
            f = parse_fields(sec)
            key = (head.get("azienda", ""), head.get("ruolo", ""), tracker_name(f))
            if key not in {(r["azienda"], r["ruolo"], r["persona"]) for r in rows}:
                errors.append(f"tracker.csv: manca la riga {key}")
    return errors, warnings, head, sections


def tracker_name(f):
    """Più persone senza nome nello stesso piano non devono collassare nel dedupe."""
    n = f.get("persona", "")
    return f"{n} {f.get('categoria', '')}" if "[ricerca manuale]" in n.lower() else n


def read_tracker(root):
    p = root / "tracker.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def track(plan_path, root):
    errors, _, head, sections = lint(plan_path, root)
    if errors:
        return errors, 0
    p = root / "tracker.csv"
    rows = read_tracker(root)
    seen = {(r["azienda"], r["ruolo"], r["persona"]) for r in rows}
    new = []
    for sec in sections:
        f = parse_fields(sec)
        key = (head["azienda"], head["ruolo"], tracker_name(f))
        if key in seen:
            continue
        new.append({"azienda": key[0], "ruolo": key[1], "persona": key[2],
                    "categoria": f["categoria"], "canale": f["canale"],
                    "data_contatto": f["data d0"], "prossimo_followup": f["data d+5"],
                    "stato": "da contattare"})
    write_header = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TRACKER_COLS)
        if write_header:
            w.writeheader()
        w.writerows(new)
    return [], len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=ROOT, help="radice progetto (default: repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check-context")
    for name in ("lint", "track"):
        sp = sub.add_parser(name)
        sp.add_argument("plan", type=Path)
        if name == "lint":
            sp.add_argument("--tracker", action="store_true", help="verifica anche le righe in tracker.csv")
    a = ap.parse_args()

    if a.cmd == "check-context":
        errs = check_context(a.root)
        print("\n".join(f"ERRORE: {e}" for e in errs) or "OK: contesto completo")
        sys.exit(1 if errs else 0)
    if a.cmd == "lint":
        errs, _, _, _ = lint(a.plan, a.root, a.tracker)
        print("\n".join(f"ERRORE: {e}" for e in errs) or "OK: piano valido")
        sys.exit(1 if errs else 0)
    errs, n = track(a.plan, a.root)
    print("\n".join(f"ERRORE: {e}" for e in errs) or f"OK: {n} righe aggiunte a tracker.csv")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
