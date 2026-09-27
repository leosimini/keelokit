#!/usr/bin/env python3
"""Keelokit dashboard: one HTML page that shows where a project is, read from the repo.

    python3 dashboard.py [--root DIR] [--lang es|en] [--out FILE] [--standalone] [--json]

Everything comes from files and git: `.keelokit/state.toml` (gate approvals), `docs/context/`,
`docs/prd.md`, `docs/stack.md`, `docs/decisions/`, `docs/diagnosis.md`, `backlog/` and the
`Story:` trailers on main. Nothing is stored by the page itself, so regenerating it after any
change (or in a new session) always shows the current state.

The page follows `../references/design.md`. By default it is written for the Artifact tool (no
<html>/<head>, the viewer adds them) to `.keelokit/out/dashboard.html`; `--standalone` writes a
full document to open straight in a browser. `--json` prints the computed state instead.
Stdlib only (Python 3.11+ for tomllib).
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}).", file=sys.stderr)
    sys.exit(1)

import argparse  # noqa: E402
import base64  # noqa: E402
import datetime as dt  # noqa: E402
import html  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CONTEXT_FILES = ["product.md", "domain.md", "constraints.md", "environments.md", "gaps.md"]
GATES = {
    "project": ["intake", "product", "stack", "skeleton", "backlog"],  # /keelokit:kickstart
    "harness": ["intake", "adopt", "backlog"],  # /keelokit:adopt
}
GAP_ROW_RE = re.compile(r"^\|\s*(GAP-\d+)\s*\|")
GAP_REF_RE = re.compile(r"\[(GAP-\d+)\]")
INV_RE = re.compile(r"(?m)^\s*[-*]\s*\[(INV-\d{3})\]\s*(.*)$")

# ---------------------------------------------------------------------------------------------
# Copy. Plain words for people who have never run a software project; the terms of art are
# explained once, in the stage that introduces them and in the glossary.

T = {
    "es": {
        "title": "Tablero de {name}",
        "eyebrow": "Tablero del proyecto",
        "where": "Dónde estamos",
        "next": "Próximo paso",
        "waiting": "Te espera a vos",
        "nothing_waiting": "Nada por ahora.",
        "copy": "Copiar",
        "copied": "Copiado",
        "copy_hint": "Pegalo en el chat de Claude Code.",
        "stages": "Etapas",
        "approved_on": "Aprobada el {date}",
        "st_done": "Aprobada",
        "st_review": "Para revisar",
        "st_current": "En curso",
        "st_todo": "Pendiente",
        "what": "Qué es",
        "review": "Qué revisar antes de aprobar",
        "how_approve": "Para aprobar, escribí en el chat «apruebo» o decí qué querés cambiar.",
        "docs": "Documentos",
        "open_github": "Abrir en GitHub",
        "open_file": "Abrir archivo",
        "not_yet": "Todavía no hay nada acá: aparece cuando la etapa arranca.",
        "gaps": "Preguntas abiertas (gaps)",
        "gaps_none": "No hay preguntas abiertas.",
        "gap_cols": ["Id", "Falta", "Quién responde", "Pregunta", "Bloquea"],
        "yes": "sí",
        "no": "no",
        "invariants": "Reglas que nunca se pueden romper (invariantes)",
        "metrics": "Métricas de éxito",
        "scope": "Alcance",
        "apps": "Aplicaciones elegidas",
        "house_stack": "Stack de la casa",
        "decisions": "Decisiones registradas",
        "skeleton_facts": "Estado del repositorio",
        "generated": "Proyecto generado con Keelokit",
        "first_commit": "Primer commit",
        "remote": "Repositorio en GitHub",
        "health": "Salud del harness",
        "backlog_total": "{done} de {total} historias terminadas",
        "by_wave": "Por ola",
        "by_epic": "Por épica",
        "wave": "Ola de desarrollo {n}",
        "wave_note": "Las historias de una ola no tocan los mismos archivos: se pueden construir a la vez.",
        "epic": "Épica",
        "story_done": "Terminada",
        "story_ready": "Lista para construir",
        "story_blocked": "Espera a {deps}",
        "story_gap": "Espera respuesta a {gaps}",
        "depends": "Depende de",
        "modes": "Cómo construir: en serie o en paralelo",
        "modes_intro": "Cuando hay varias historias listas en la misma ola, Keelokit te pregunta cómo seguir. Las dos formas producen el mismo resultado y la misma calidad; cambia la velocidad, el uso de Claude y cuánto tenés que revisar a la vez.",
        "serial": "En serie",
        "serial_body": "Una historia por vez. Cada una se construye, se prueba y entra al producto antes de empezar la siguiente. Es más lento, pero seguís el avance paso a paso y el uso de Claude se reparte en el tiempo.",
        "serial_when": "Conviene para la primera ola, para historias delicadas (pagos, datos de otras personas) o si es tu primer proyecto con agentes.",
        "parallel": "En paralelo",
        "parallel_body": "Varias historias de la misma ola al mismo tiempo, cada una en su propia copia del repositorio (un worktree) con su propio equipo de agentes. Termina antes, pero consume más uso de Claude a la vez y te llegan varios resultados juntos para revisar.",
        "parallel_when": "Es seguro porque las historias de una ola no tocan los mismos archivos. Conviene cuando la ola tiene varias historias independientes y ya confiás en el proceso.",
        "glossary": "Glosario",
        "footer": "Generado el {when} a partir del repositorio · Keelokit {version} · Para actualizarlo: /keelokit:dashboard",
        "next_review": "Revisá la etapa «{stage}» y aprobala",
        "next_review_d": "Todo lo que hay que mirar está en su sección de este tablero.",
        "next_continue": "Seguir con la etapa «{stage}»",
        "next_continue_d": "Keelokit retoma desde donde quedó.",
        "next_gaps": "Responder las preguntas que bloquean",
        "next_gaps_d": "Hay {n} preguntas abiertas que bloquean el avance.",
        "next_build": "Construir {sid}: {title}",
        "next_build_d": "Hay {n} historias listas en la ola {wave}. En serie: una por vez. En paralelo: «/keelokit:build {n}».",
        "next_blocked": "Destrabar la próxima ola",
        "next_blocked_d": "Ninguna historia está lista: cada una espera a otra que todavía no terminó.",
        "next_more": "Planificar lo que sigue",
        "next_more_d": "Todas las historias están terminadas. Sumá la próxima parte del producto.",
        "next_doctor": "Revisar la salud del harness",
        "next_doctor_d": "El doctor encontró {n} errores.",
        "wait_gate": "Aprobar «{stage}»",
        "wait_gap": "{gap}: {question}",
        "wait_errors": "{n} errores del harness para revisar",
        "build_stage": "Construcción",
        "build_what": "Cada historia la construye un agente y la controlan otros, independientes: uno escribe las pruebas antes del código, otro revisa los cambios y otro intenta romperlos. Recién entonces entra al producto.",
    },
    "en": {
        "title": "{name} dashboard",
        "eyebrow": "Project dashboard",
        "where": "Where we are",
        "next": "Next step",
        "waiting": "Waiting on you",
        "nothing_waiting": "Nothing right now.",
        "copy": "Copy",
        "copied": "Copied",
        "copy_hint": "Paste it into the Claude Code chat.",
        "stages": "Stages",
        "approved_on": "Approved on {date}",
        "st_done": "Approved",
        "st_review": "Ready for review",
        "st_current": "In progress",
        "st_todo": "Not started",
        "what": "What it is",
        "review": "What to check before approving",
        "how_approve": "To approve, say \"approved\" in the chat, or say what you want changed.",
        "docs": "Documents",
        "open_github": "Open on GitHub",
        "open_file": "Open file",
        "not_yet": "Nothing here yet: it appears when the stage starts.",
        "gaps": "Open questions (gaps)",
        "gaps_none": "No open questions.",
        "gap_cols": ["Id", "Missing", "Who answers", "Question", "Blocking"],
        "yes": "yes",
        "no": "no",
        "invariants": "Rules that must never break (invariants)",
        "metrics": "Success metrics",
        "scope": "Scope",
        "apps": "Apps chosen",
        "house_stack": "House stack",
        "decisions": "Recorded decisions",
        "skeleton_facts": "Repository",
        "generated": "Project generated with Keelokit",
        "first_commit": "First commit",
        "remote": "GitHub repository",
        "health": "Harness health",
        "backlog_total": "{done} of {total} stories done",
        "by_wave": "By wave",
        "by_epic": "By epic",
        "wave": "Development wave {n}",
        "wave_note": "Stories in a wave never touch the same files, so they can be built at the same time.",
        "epic": "Epic",
        "story_done": "Done",
        "story_ready": "Ready to build",
        "story_blocked": "Waits for {deps}",
        "story_gap": "Waits for an answer to {gaps}",
        "depends": "Depends on",
        "modes": "How to build: one at a time or in parallel",
        "modes_intro": "When several stories of the same wave are ready, Keelokit asks how to go on. Both ways give the same result and the same quality; what changes is speed, Claude usage and how much you review at once.",
        "serial": "One at a time",
        "serial_body": "One story at a time. Each one is built, tested and lands in the product before the next starts. Slower, but you follow every step and Claude usage is spread over time.",
        "serial_when": "Best for the first wave, for sensitive stories (payments, other people's data) or for your first project with agents.",
        "parallel": "In parallel",
        "parallel_body": "Several stories of the same wave at once, each in its own copy of the repository (a worktree) with its own team of agents. Finishes sooner, but uses more Claude at the same time and you get several results to review together.",
        "parallel_when": "It is safe because stories in a wave never touch the same files. Best when the wave has several independent stories and you already trust the process.",
        "glossary": "Glossary",
        "footer": "Generated {when} from the repository · Keelokit {version} · To refresh: /keelokit:dashboard",
        "next_review": "Review the \"{stage}\" stage and approve it",
        "next_review_d": "Everything to look at is in its section of this dashboard.",
        "next_continue": "Continue the \"{stage}\" stage",
        "next_continue_d": "Keelokit resumes where it stopped.",
        "next_gaps": "Answer the blocking questions",
        "next_gaps_d": "{n} open questions block progress.",
        "next_build": "Build {sid}: {title}",
        "next_build_d": "{n} stories are ready in wave {wave}. One at a time, or in parallel with \"/keelokit:build {n}\".",
        "next_blocked": "Unblock the next wave",
        "next_blocked_d": "No story is ready: each one waits for another that isn't done yet.",
        "next_more": "Plan what comes next",
        "next_more_d": "Every story is done. Add the next slice of the product.",
        "next_doctor": "Check the harness health",
        "next_doctor_d": "The doctor found {n} errors.",
        "wait_gate": "Approve \"{stage}\"",
        "wait_gap": "{gap}: {question}",
        "wait_errors": "{n} harness errors to review",
        "build_stage": "Build",
        "build_what": "Each story is built by one agent and checked by others that work independently: one writes the tests before the code, one reviews the changes and one tries to break them. Only then does it land in the product.",
    },
}

STAGES = {
    "es": {
        "intake": ("Contexto",
                   "Una entrevista para entender el problema, quién lo tiene, las reglas del negocio y los límites (plazos, presupuesto, leyes). Lo que todavía no sabemos queda anotado como pregunta abierta, nunca inventado.",
                   ["¿Describe bien tu problema y a tus usuarios?", "¿Hay algo inventado, o algo importante que falte?", "Las preguntas abiertas que bloquean: ¿quién las responde y cuándo?"]),
        "product": ("Producto (PRD)",
                    "El PRD (Product Requirements Document, documento de requisitos del producto) dice qué se construye en la primera versión, qué queda afuera a propósito y con qué números vamos a saber si funcionó. Es el acuerdo entre vos y los agentes: lo que no está en el alcance no se construye.",
                    ["Alcance: ¿lo que entra es lo mínimo para lanzar? ¿Lo que queda afuera puede esperar?", "Métricas: ¿cada una tiene un número y una fecha que aceptás?", "Riesgos y preguntas abiertas: ¿falta alguno?"]),
        "stack": ("Tecnología (stack)",
                  "El stack es el conjunto de tecnologías con que se construye el producto. Keelokit trae uno ya elegido y probado; en esta etapa solo se decide qué aplicaciones necesita tu producto (API, web, móvil, sitio público) y si usa mapas o ubicación.",
                  ["¿Las aplicaciones elegidas llegan a tus usuarios por los canales que usan?", "Si algo se aparta del stack de la casa, ¿el motivo está escrito y lo aceptás?"]),
        "skeleton": ("Esqueleto",
                     "Se genera el proyecto base: el repositorio con las aplicaciones elegidas, los controles de calidad y la integración continua funcionando desde el primer día. Todavía no tiene funcionalidades de tu producto.",
                     ["No hay nada que aprobar, salvo tus cuentas (GitHub, Fly.io) si querés un entorno de pruebas en internet (staging)."]),
        "adopt": ("Harness",
                  "Se instala Keelokit en tu repositorio sin tocar tu código. Cada regla de la casa queda cubierta por un control que el repo ya tiene, o registrada como excepción con motivo, responsable y fecha límite.",
                  ["Cada excepción: ¿aceptás el motivo y la fecha límite?", "¿El diagnóstico describe bien el estado real del código?"]),
        "backlog": ("Backlog",
                    "El trabajo se divide en épicas (las grandes capacidades del producto) e historias (piezas chicas que se pueden ver funcionando de punta a punta). Las historias se agrupan en olas de desarrollo: todo lo de una ola se puede construir a la vez sin pisarse.",
                    ["¿Cada parte del alcance del PRD tiene al menos una historia?", "¿El orden de las olas tiene sentido para tu negocio? ¿Qué querés ver funcionando primero?", "¿Hay historias que esperan una respuesta tuya?"]),
    },
    "en": {
        "intake": ("Context",
                   "An interview to understand the problem, who has it, the business rules and the limits (dates, budget, laws). Whatever we don't know yet is written down as an open question, never made up.",
                   ["Does it describe your problem and your users well?", "Is anything made up, or is something important missing?", "Blocking open questions: who answers them, and when?"]),
        "product": ("Product (PRD)",
                    "The PRD (Product Requirements Document) says what the first version builds, what is deliberately left out, and which numbers will tell us it worked. It is the agreement between you and the agents: what is not in scope does not get built.",
                    ["Scope: is what's in the minimum to launch? Can what's out wait?", "Metrics: does each one have a number and a date you accept?", "Risks and open questions: is any missing?"]),
        "stack": ("Technology (stack)",
                  "The stack is the set of technologies the product is built with. Keelokit brings one already chosen and tested; this stage only decides which apps your product needs (API, web, mobile, public site) and whether it uses maps or location.",
                  ["Do the chosen apps reach your users through the channels they use?", "If anything departs from the house stack, is the reason written down and do you accept it?"]),
        "skeleton": ("Skeleton",
                     "The base project is generated: the repository with the chosen apps, quality checks and continuous integration working from day one. It has none of your product's features yet.",
                     ["Nothing to approve, except your accounts (GitHub, Fly.io) if you want an online test environment (staging)."]),
        "adopt": ("Harness",
                  "Keelokit is installed in your repository without touching your code. Each house rule is either covered by a check the repo already has, or recorded as an exception with a reason, an owner and an expiry date.",
                  ["Each exception: do you accept the reason and the expiry date?", "Does the diagnosis describe the real state of the code?"]),
        "backlog": ("Backlog",
                    "The work is split into epics (the product's big capabilities) and stories (small pieces you can see working end to end). Stories are grouped into development waves: everything in a wave can be built at the same time without collisions.",
                    ["Does every part of the PRD's scope have at least one story?", "Does the wave order make sense for your business? What do you want working first?", "Do any stories wait for an answer from you?"]),
    },
}

GLOSSARY = {
    "es": [
        ("PRD", "Documento de requisitos del producto: qué se construye, qué no, y cómo se mide el éxito."),
        ("Gap", "Una pregunta abierta. Keelokit la anota con quién la responde en lugar de inventar la respuesta."),
        ("Invariante", "Una regla del negocio que nunca se puede romper, ni con dos usuarios a la vez (por ejemplo: «un turno nunca tiene más reservas que su capacidad»)."),
        ("Stack", "Las tecnologías con que se construye el producto."),
        ("Épica", "Una capacidad grande del producto, como «pagos» o «reservas». Agrupa historias."),
        ("Historia", "Una pieza chica de producto que se puede ver funcionando de punta a punta y que se construye en una sesión."),
        ("Ola de desarrollo", "Un grupo de historias que no tocan los mismos archivos y por eso se pueden construir a la vez."),
        ("Worktree", "Una copia de trabajo separada del mismo repositorio, para que varios agentes trabajen a la vez sin pisarse."),
        ("Staging", "Un entorno en internet igual al real, para probar antes de que llegue a los usuarios."),
    ],
    "en": [
        ("PRD", "Product Requirements Document: what gets built, what doesn't, and how success is measured."),
        ("Gap", "An open question. Keelokit records it with who answers it instead of making the answer up."),
        ("Invariant", "A business rule that must never break, not even with two users at once (for example: \"a slot never holds more bookings than its capacity\")."),
        ("Stack", "The technologies the product is built with."),
        ("Epic", "A big product capability, like \"payments\" or \"bookings\". It groups stories."),
        ("Story", "A small piece of product you can see working end to end, built in one session."),
        ("Development wave", "A group of stories that don't touch the same files, so they can be built at the same time."),
        ("Worktree", "A separate working copy of the same repository, so several agents can work at once without collisions."),
        ("Staging", "An online environment like the real one, to try things before users see them."),
    ],
}

# ---------------------------------------------------------------------------------------------
# Reading the repo


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout if out.returncode == 0 else ""


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".keelokit").is_dir():
            return p
    return start


def answers(root: Path) -> dict:
    """The few flat keys we need from Copier's answers file (it is simple YAML)."""
    out = {}
    for line in read(root / ".keelokit/answers.yml").splitlines():
        if m := re.match(r"^([A-Za-z_]\w*):\s*(.*)$", line):
            out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


def md_section(text: str, title: str) -> str:
    """Body of the first `## <title>` section (up to the next heading of the same or higher level)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and m.group(2).strip().lower().startswith(title.lower()):
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                h = re.match(r"^(#{1,6})\s", nxt)
                if h and len(h.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    return ""


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("|") and not re.match(r"^\|[\s:|-]+\|?$", s):
            rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def split_story(text: str) -> tuple[dict, str]:
    m = re.match(r"\+\+\+\n(.*?)\n\+\+\+\n?", text, re.S)
    if not m:
        return {}, text
    try:
        return tomllib.loads(m.group(1)), text[m.end():]
    except tomllib.TOMLDecodeError:
        return {}, text[m.end():]


def github_base(root: Path) -> str | None:
    url = git(root, "remote", "get-url", "origin").strip()
    m = re.match(r"^(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return f"https://github.com/{m.group(1)}/blob/main/" if m else None


def main_ref(root: Path) -> str:
    for ref in ("origin/main", "main"):
        if git(root, "rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return "HEAD"


def collect(root: Path) -> dict:
    state_file = root / ".keelokit/state.toml"
    try:
        state = tomllib.loads(read(state_file)) if state_file.exists() else {}
    except tomllib.TOMLDecodeError:
        state = {}
    gates = {k: str(v) for k, v in state.get("gates", {}).items()}
    ans = answers(root)
    layout = "harness" if ans.get("mode") == "harness" or "adopt" in gates else "project"

    prd = read(root / "docs/prd.md")
    name = (ans.get("project_name") or state.get("dashboard", {}).get("product")
            or (re.sub(r"\s+[—-]\s+PRD\s*$", "", m.group(1)) if (m := re.match(r"#\s+(.+)", prd)) else "")
            or root.resolve().name)

    context = {f: read(root / "docs/context" / f) for f in CONTEXT_FILES if (root / "docs/context" / f).exists()}
    gaps = []
    for row in table_rows(context.get("gaps.md", "")):
        if GAP_ROW_RE.match("| " + row[0] + " |"):
            cells = row + [""] * 6
            gaps.append({"id": cells[0], "file": cells[1], "missing": cells[2], "owner": cells[3],
                         "question": cells[4], "blocking": cells[5].lower() in ("yes", "sí", "si", "true")})
    open_gaps = {g["id"] for g in gaps}
    invariants = [{"id": i, "text": t.strip()} for i, t in INV_RE.findall(context.get("domain.md", ""))]

    decisions = sorted(p for p in (root / "docs/decisions").glob("*.md") if p.name.lower() != "readme.md") \
        if (root / "docs/decisions").is_dir() else []

    in_git = git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    has_commits = bool(git(root, "rev-parse", "--verify", "--quiet", "HEAD").strip()) if in_git else False
    done = set()
    if has_commits:
        trailers = git(root, "log", main_ref(root), "--format=%(trailers:key=Story,valueonly,separator=%x2C)")
        done = {s.strip() for line in trailers.splitlines() for s in line.split(",") if s.strip()}
    first_commit = (git(root, "log", "--reverse", "--format=%h %s").splitlines() or [""])[0] if has_commits else ""

    stories = []
    for path in sorted((root / "backlog/stories").glob("*.md")) if (root / "backlog/stories").is_dir() else []:
        meta, body = split_story(read(path))
        if not meta.get("id"):
            continue
        stories.append({
            "id": meta["id"], "title": meta.get("title", ""), "epic": meta.get("epic", ""),
            "wave": meta.get("wave", 0) if isinstance(meta.get("wave"), int) else 0,
            "depends_on": list(meta.get("depends_on", [])),
            "gaps": sorted(set(GAP_REF_RE.findall(body)) & open_gaps),
            "path": path.relative_to(root).as_posix(), "body": body,
        })
    by_id = {s["id"]: s for s in stories}
    for s in stories:
        waiting = [d for d in s["depends_on"] if d not in done]
        if s["id"] in done:
            s["status"] = "done"
        elif waiting:
            s["status"], s["waits"] = "blocked", waiting
        elif s["gaps"]:
            s["status"] = "gap"
        else:
            s["status"] = "ready"
    stories.sort(key=lambda s: (s["wave"], s["id"]))

    epics = {}
    for row in table_rows(read(root / "backlog/epics.md")):
        if row and re.fullmatch(r"[A-Z][A-Z0-9]*", row[0]) and len(row) > 1:
            epics.setdefault(row[0], next((c for c in row[1:] if c), ""))
    for s in stories:
        epics.setdefault(s["epic"], "")

    doctor = []
    if (root / ".keelokit/bin/doctor.py").exists():
        try:
            out = subprocess.run([sys.executable, ".keelokit/bin/doctor.py", "--brief"], cwd=root,
                                 capture_output=True, text=True, timeout=120)
            doctor = [line for line in out.stdout.splitlines() if line.strip()]
        except (OSError, subprocess.TimeoutExpired):
            doctor = []
    errors = next((int(m.group(1)) for line in doctor if (m := re.search(r"Harness errors:\s*(\d+)", line))), 0)

    outputs = {
        "intake": [f"docs/context/{f}" for f in context],
        "product": ["docs/prd.md"] if prd else [],
        "stack": [p for p in ["docs/stack.md"] if (root / p).exists()]
                 + [d.relative_to(root).as_posix() for d in decisions],
        "skeleton": [".keelokit/answers.yml"] if ans and layout == "project" else [],
        "adopt": [p for p in [".keelokit/rules.local.toml", ".keelokit/exceptions.toml", "docs/diagnosis.md"]
                  if (root / p).exists()] if layout == "harness" else [],
        "backlog": (["backlog/epics.md"] if (root / "backlog/epics.md").exists() else []),
    }
    ready_evidence = {
        "intake": len(context) == len(CONTEXT_FILES),
        "product": bool(prd),
        "stack": bool(outputs["stack"]) or bool(ans.get("apps")),
        "skeleton": bool(ans) and has_commits,
        "adopt": bool(ans),
        "backlog": bool(stories),
    }
    order = GATES[layout]
    pending = next((g for g in order if not gates.get(g)), None)
    stages = []
    for g in order:
        if gates.get(g):
            status = "done"
        elif g == pending:
            status = "review" if ready_evidence[g] else "current"
        else:
            status = "todo"
        stages.append({"id": g, "status": status, "date": gates.get(g, ""), "outputs": outputs[g]})

    return {
        "root": root, "name": name, "layout": layout, "gates": gates, "pending": pending,
        "stages": stages, "answers": ans, "prd": prd, "context": context, "gaps": gaps,
        "invariants": invariants, "decisions": [d.relative_to(root).as_posix() for d in decisions],
        "stack_doc": read(root / "docs/stack.md"), "diagnosis": read(root / "docs/diagnosis.md"),
        "stories": stories, "by_id": by_id, "epics": epics, "done": done,
        "has_commits": has_commits, "first_commit": first_commit, "github": github_base(root),
        "doctor": doctor, "errors": errors,
    }


def next_step(s: dict, lang: str) -> dict:
    t, names = T[lang], {k: v[0] for k, v in STAGES[lang].items()}
    blocking = [g for g in s["gaps"] if g["blocking"]]
    flow = "/keelokit:adopt" if s["layout"] == "harness" else "/keelokit:kickstart"
    if s["pending"]:
        stage = next(x for x in s["stages"] if x["id"] == s["pending"])
        if stage["status"] == "review":
            return {"title": t["next_review"].format(stage=names[stage["id"]]), "detail": t["next_review_d"],
                    "command": None, "anchor": f"stage-{stage['id']}"}
        return {"title": t["next_continue"].format(stage=names[stage["id"]]), "detail": t["next_continue_d"],
                "command": flow, "anchor": f"stage-{stage['id']}"}
    if s["errors"]:
        return {"title": t["next_doctor"], "detail": t["next_doctor_d"].format(n=s["errors"]),
                "command": "/keelokit:doctor", "anchor": "stage-build"}
    if blocking:
        return {"title": t["next_gaps"], "detail": t["next_gaps_d"].format(n=len(blocking)),
                "command": "/keelokit", "anchor": "stage-intake"}
    ready = [x for x in s["stories"] if x["status"] == "ready"]
    if ready:
        first = ready[0]
        same = [x for x in ready if x["wave"] == first["wave"]]
        return {"title": t["next_build"].format(sid=first["id"], title=first["title"]),
                "detail": t["next_build_d"].format(n=len(same), wave=first["wave"]),
                "command": f"/keelokit:build {first['id']}", "anchor": "stage-build"}
    if s["stories"] and any(x["status"] != "done" for x in s["stories"]):
        return {"title": t["next_blocked"], "detail": t["next_blocked_d"], "command": "/keelokit",
                "anchor": "stage-backlog"}
    return {"title": t["next_more"], "detail": t["next_more_d"], "command": "/keelokit:backlog",
            "anchor": "stage-backlog"}


def waiting_on_user(s: dict, lang: str) -> list[dict]:
    t, names = T[lang], {k: v[0] for k, v in STAGES[lang].items()}
    items = [{"text": t["wait_gate"].format(stage=names[x["id"]]), "anchor": f"stage-{x['id']}"}
             for x in s["stages"] if x["status"] == "review"]
    items += [{"text": t["wait_gap"].format(gap=g["id"], question=g["question"] or g["missing"]),
               "anchor": "stage-intake"} for g in s["gaps"] if g["blocking"]]
    if s["errors"]:
        items.append({"text": t["wait_errors"].format(n=s["errors"]), "anchor": "stage-build"})
    return items


# ---------------------------------------------------------------------------------------------
# Markdown → HTML. Small on purpose: headings, paragraphs, lists, tables, code, quotes, and
# inline code / bold / italics / links. Everything is escaped first, so a document can never
# inject markup into the page.

def esc(text) -> str:
    return html.escape(str(text), quote=True)


class Links:
    def __init__(self, github: str | None, standalone: bool, out_dir: Path, root: Path):
        self.github, self.standalone, self.out_dir, self.root = github, standalone, out_dir, root

    def href(self, rel: str) -> str | None:
        if self.github:
            return self.github + rel
        if self.standalone:
            return Path(os.path.relpath(self.root / rel, self.out_dir)).as_posix()
        return None


def inline(text: str, links: Links | None = None, base: str = "") -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{esc(part[1:-1])}</code>")
            continue
        s = esc(part)

        def link(m):
            label, url = m.group(1), html.unescape(m.group(2))
            if re.match(r"^https?://", url):
                return f'<a href="{esc(url)}" target="_blank" rel="noopener">{label}</a>'
            if links and not url.startswith("#"):
                rel = (Path(base).parent / url).as_posix() if base else url
                rel = re.sub(r"(^|/)\./", r"\1", rel)
                while re.search(r"[^/]+/\.\./", rel):
                    rel = re.sub(r"[^/]+/\.\./", "", rel, count=1)
                if href := links.href(rel):
                    return f'<a href="{esc(href)}" target="_blank" rel="noopener">{label}</a>'
            return f"<span class=\"ref\">{label}</span>"

        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"\[(GAP-\d+|INV-\d{3})\]", r'<span class="tag">\1</span>', s)
        s = re.sub(r"\[(MUST(?: NOT)?)\]", r'<span class="tag must">\1</span>', s)
        out.append(s)
    return "".join(out)


def markdown(text: str, links: Links | None = None, base: str = "") -> str:
    lines = text.splitlines()
    out, i = [], 0
    para: list[str] = []

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para), links, base)}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(f'<div class="scroll"><pre><code>{esc(chr(10).join(code))}</code></pre></div>')
            i += 1
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)$", s):
            flush()
            level = min(len(m.group(1)) + 2, 6)
            out.append(f"<h{level}>{inline(m.group(2), links, base)}</h{level}>")
            i += 1
            continue
        if s.startswith("|"):
            flush()
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in block]
            has_head = len(rows) > 1 and all(re.fullmatch(r":?-{2,}:?", c) for c in rows[1] if c)
            head, body = (rows[0], rows[2:]) if has_head else ([], rows)
            h = "".join(f"<th>{inline(c, links, base)}</th>" for c in head)
            b = "".join("<tr>" + "".join(f"<td>{inline(c, links, base)}</td>" for c in r) + "</tr>" for r in body)
            out.append(f'<div class="scroll"><table>{f"<thead><tr>{h}</tr></thead>" if h else ""}<tbody>{b}</tbody></table></div>')
            continue
        if re.match(r"^([-*+]|\d+[.)])\s+", s):
            flush()
            ordered = bool(re.match(r"^\d", s))
            items = []
            while i < len(lines) and (m := re.match(r"^\s*([-*+]|\d+[.)])\s+(.*)$", lines[i])):
                items.append(m.group(2))
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() \
                        and not re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                    items[-1] += " " + lines[i].strip()
                    i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x, links, base)}</li>" for x in items) + f"</{tag}>")
            continue
        if s.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append(f"<blockquote>{inline(' '.join(quote), links, base)}</blockquote>")
            continue
        if not s:
            flush()
        else:
            para.append(s)
        i += 1
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# Page

CSS = """
:root{
  --bg:#F3F6FB;--surface:#FFFFFF;--sunk:#E9EFF8;--ink:#0B1B3A;--muted:#4F5F7C;--line:#D5DFEC;
  --accent:#0B4CC4;--accent-ink:#FFFFFF;--accent-soft:#E3ECFB;--foil:#C85A12;--foil-soft:#FCEBDD;
  --good:#1D7F52;--good-soft:#E0F2E9;--bad:#B3322A;--bad-soft:#F9E3E1;--todo:#6B7A93;
  --shadow:0 1px 2px rgba(11,27,58,.06),0 4px 16px rgba(11,27,58,.06);
  --display:"Bricolage Grotesque","Avenir Next","Segoe UI",system-ui,sans-serif;
  --body:"Manrope","Segoe UI",system-ui,-apple-system,sans-serif;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
  --bg:#061127;--surface:#0C1D3D;--sunk:#0A1833;--ink:#E4ECF9;--muted:#9DB0CD;--line:#1C3260;
  --accent:#63C0FB;--accent-ink:#061127;--accent-soft:#10305E;--foil:#F7963A;--foil-soft:#3A2412;
  --good:#52C992;--good-soft:#0F3326;--bad:#F2786D;--bad-soft:#3D1715;--todo:#7F91AF;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);}}
:root[data-theme="dark"]{color-scheme:dark;
  --bg:#061127;--surface:#0C1D3D;--sunk:#0A1833;--ink:#E4ECF9;--muted:#9DB0CD;--line:#1C3260;
  --accent:#63C0FB;--accent-ink:#061127;--accent-soft:#10305E;--foil:#F7963A;--foil-soft:#3A2412;
  --good:#52C992;--good-soft:#0F3326;--bad:#F2786D;--bad-soft:#3D1715;--todo:#7F91AF;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 4px 16px rgba(0,0,0,.25);}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 var(--body)}
a{color:var(--accent)}
a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
code{font-family:var(--mono);font-size:.86em;background:var(--sunk);padding:.1em .35em;border-radius:4px}
.bar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--surface);border-bottom:1px solid var(--line)}
.bar-in{max-width:1080px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.bar img{width:28px;height:28px;border-radius:7px}
.wordmark{font:700 16px/1 var(--display);letter-spacing:.01em}
.bar .sep{color:var(--line)}
.bar .product{font-weight:600;color:var(--muted);overflow-wrap:anywhere}
.bar .ver{margin-left:auto;font:500 12px var(--mono);color:var(--muted)}
.page{max-width:1080px;margin:0 auto;padding-inline:16px;padding-block:24px 48px;display:flex;flex-direction:column;gap:28px}
.eyebrow{font:600 12px/1 var(--body);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0}
h1{font:700 clamp(26px,4.5vw,36px)/1.1 var(--display);margin:6px 0 0;text-wrap:balance}
h2{font:700 22px/1.2 var(--display);margin:0;text-wrap:balance}
h3{font:700 16px/1.3 var(--body);margin:0}
.now{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:14px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:8px;box-shadow:var(--shadow)}
.panel.next{border-color:var(--accent);background:var(--accent-soft)}
.panel.wait{border-color:var(--foil)}
.panel .big{font:700 18px/1.3 var(--display)}
.panel p{margin:0;color:var(--muted)}
.panel ul{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px}
.cmd{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.cmd code{font-size:14px;padding:6px 10px;background:var(--surface);border:1px solid var(--line);overflow-wrap:anywhere}
button{font:600 13px var(--body);cursor:pointer;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);padding:6px 12px}
button.ghost{background:transparent;color:var(--accent)}
button[aria-pressed="true"]{background:var(--accent);color:var(--accent-ink)}
.hint{font-size:12px;color:var(--muted)}
.rail{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;counter-reset:st}
.rail a{display:flex;flex-direction:column;gap:4px;text-decoration:none;color:var(--ink);background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;height:100%}
.rail a:hover{border-color:var(--accent)}
.rail .n{font:600 12px var(--mono);color:var(--muted)}
.rail .nm{font-weight:700}
.pill{display:inline-flex;align-items:center;gap:6px;font:600 12px/1 var(--body);padding:4px 9px;border-radius:999px;white-space:nowrap;width:fit-content}
.pill::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}
.pill.done{color:var(--good);background:var(--good-soft)}
.pill.review{color:var(--foil);background:var(--foil-soft)}
.pill.current{color:var(--accent);background:var(--accent-soft)}
.pill.todo{color:var(--todo);background:var(--sunk)}
.pill.ready{color:var(--accent);background:var(--accent-soft)}
.pill.blocked,.pill.gap{color:var(--bad);background:var(--bad-soft)}
.stage{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px;display:flex;flex-direction:column;gap:14px;scroll-margin-top:72px}
.stage.review{border-color:var(--foil);box-shadow:0 0 0 3px var(--foil-soft)}
.stage-head{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}
.stage-head .n{font:600 13px var(--mono);color:var(--muted)}
.stage-head .when{font-size:13px;color:var(--muted)}
.what{margin:0;max-width:72ch;color:var(--ink)}
.check{background:var(--foil-soft);border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.check h3{color:var(--foil)}
.check ul{margin:0;padding-left:18px}
.check p{margin:0;font-weight:600}
.block{display:flex;flex-direction:column;gap:8px}
.muted{color:var(--muted);margin:0}
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--line)}
th{font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);font-weight:600}
details.doc{border:1px solid var(--line);border-radius:10px;background:var(--bg)}
details.doc>summary{cursor:pointer;padding:10px 12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;list-style:none}
details.doc>summary::-webkit-details-marker{display:none}
details.doc>summary::before{content:"▸";color:var(--muted);transition:transform .15s}
details.doc[open]>summary::before{transform:rotate(90deg)}
details.doc>summary .path{font:500 13px var(--mono);overflow-wrap:anywhere}
details.doc>summary a{margin-left:auto;font-size:13px}
.md{padding:4px 16px 14px;border-top:1px solid var(--line);max-width:100%;overflow-wrap:anywhere}
.md h3,.md h4,.md h5,.md h6{margin:16px 0 6px;font-family:var(--display)}
.md p{margin:8px 0;max-width:75ch}
.md pre{margin:8px 0;padding:10px;background:var(--sunk);border-radius:8px;font:13px/1.5 var(--mono)}
.md pre code{background:none;padding:0}
.md.bare{padding:0;border:0}
.out{margin:0;padding:10px 12px;background:var(--sunk);border-radius:8px;font:13px/1.5 var(--mono)}
.out code{background:none;padding:0}
.md blockquote{margin:8px 0;padding:6px 12px;border-left:3px solid var(--line);color:var(--muted)}
.tag{font:600 11px var(--mono);padding:1px 6px;border-radius:5px;background:var(--sunk);color:var(--muted);white-space:nowrap}
.tag.must{color:var(--foil);background:var(--foil-soft)}
.ref{font-family:var(--mono);font-size:.9em}
.facts{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:0}
.facts dt{color:var(--muted)}
.facts dd{margin:0;overflow-wrap:anywhere}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.progress{height:6px;border-radius:999px;background:var(--sunk);overflow:hidden;min-width:80px;flex:1;max-width:220px}
.progress i{display:block;height:100%;background:var(--good)}
.group{display:flex;flex-direction:column;gap:6px}
.group-head{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.group-head .count{font:500 13px var(--mono);color:var(--muted)}
.stories{display:flex;flex-direction:column;gap:6px}
.story>summary .sid{font:600 13px var(--mono)}
.story>summary .stitle{flex:1;min-width:12ch}
.chip{font:600 11px var(--mono);padding:2px 7px;border-radius:5px;border:1px solid var(--line);color:var(--muted)}
.modes{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.mode{border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:8px;background:var(--bg)}
.mode p{margin:0}
.mode .when{color:var(--muted);font-size:14px}
.gloss{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px 24px;margin:0}
.gloss div{display:flex;flex-direction:column;gap:2px}
.gloss dt{font-weight:700}
.gloss dd{margin:0;color:var(--muted)}
footer{font-size:12px;color:var(--muted);text-align:center}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  function copy(btn){
    var text=btn.getAttribute('data-copy'), done=btn.getAttribute('data-done'), label=btn.textContent;
    function ok(){btn.textContent=done;setTimeout(function(){btn.textContent=label},1600)}
    function fallback(){var r=document.createRange(),el=btn.previousElementSibling;if(!el)return;
      r.selectNodeContents(el);var s=window.getSelection();s.removeAllRanges();s.addRange(r)}
    try{navigator.clipboard.writeText(text).then(ok,fallback)}catch(e){fallback()}
  }
  document.querySelectorAll('button[data-copy]').forEach(function(b){b.addEventListener('click',function(){copy(b)})});
  var views=document.querySelectorAll('[data-view]'), btns=document.querySelectorAll('button[data-show]');
  function show(v){views.forEach(function(el){el.hidden=el.getAttribute('data-view')!==v});
    btns.forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-show')===v))});
    try{localStorage.setItem('keelokit-backlog-view',v)}catch(e){}}
  btns.forEach(function(b){b.addEventListener('click',function(){show(b.getAttribute('data-show'))})});
  if(btns.length){var v='wave';try{v=localStorage.getItem('keelokit-backlog-view')||'wave'}catch(e){}show(v)}
})();
"""


def logo() -> str:
    svg = read(PLUGIN_ROOT / ".claude-plugin/icon.svg")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode() if svg else ""


def doc_block(rel: str, text: str, links: Links, t: dict, open_: bool = False) -> str:
    href = links.href(rel)
    label = t["open_github"] if links.github else t["open_file"]
    a = f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(label)}</a>' if href else ""
    return (f'<details class="doc"{" open" if open_ else ""}><summary><span class="path">{esc(rel)}</span>{a}</summary>'
            f'<div class="md">{markdown(text, links, rel)}</div></details>')


def copy_cmd(cmd: str, t: dict) -> str:
    return (f'<div class="cmd"><code>{esc(cmd)}</code><button type="button" class="ghost" '
            f'data-copy="{esc(cmd)}" data-done="{esc(t["copied"])}">{esc(t["copy"])}</button></div>')


def stage_body(s: dict, stage: dict, links: Links, t: dict, lang: str) -> str:
    sid, root, parts = stage["id"], s["root"], []
    if sid == "intake":
        if s["context"]:
            if s["gaps"]:
                rows = "".join(
                    f'<tr><td><span class="tag">{esc(g["id"])}</span></td><td>{inline(g["missing"])}</td>'
                    f'<td>{esc(g["owner"])}</td><td>{inline(g["question"])}</td>'
                    f'<td>{esc(t["yes"] if g["blocking"] else t["no"])}</td></tr>' for g in s["gaps"])
                head = "".join(f"<th>{esc(c)}</th>" for c in t["gap_cols"])
                parts.append(f'<div class="block"><h3>{esc(t["gaps"])}</h3><div class="scroll"><table>'
                             f'<thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></div>')
            else:
                parts.append(f'<div class="block"><h3>{esc(t["gaps"])}</h3><p class="muted">{esc(t["gaps_none"])}</p></div>')
            if s["invariants"]:
                items = "".join(f'<li><span class="tag">{esc(i["id"])}</span> {inline(i["text"])}</li>' for i in s["invariants"])
                parts.append(f'<div class="block"><h3>{esc(t["invariants"])}</h3><ul>{items}</ul></div>')
            docs = "".join(doc_block(f"docs/context/{f}", txt, links, t) for f, txt in s["context"].items())
            parts.append(f'<div class="block"><h3>{esc(t["docs"])}</h3>{docs}</div>')
    elif sid == "product" and s["prd"]:
        for key, title in (("metrics", "Success metrics"), ("scope", "Scope")):
            if body := md_section(s["prd"], title):
                parts.append(f'<div class="block"><h3>{esc(t[key])}</h3><div class="md bare">{markdown(body, links, "docs/prd.md")}</div></div>')
        parts.append(f'<div class="block"><h3>{esc(t["docs"])}</h3>{doc_block("docs/prd.md", s["prd"], links, t)}</div>')
    elif sid == "stack":
        if s["stack_doc"]:
            parts.append(f'<div class="block"><h3>{esc(t["apps"])}</h3><div class="md bare">{markdown(s["stack_doc"], links, "docs/stack.md")}</div></div>')
        elif s["answers"].get("apps"):
            parts.append(f'<div class="block"><h3>{esc(t["apps"])}</h3><p><code>{esc(s["answers"]["apps"])}</code></p></div>')
        if s["decisions"]:
            docs = "".join(doc_block(d, read(root / d), links, t) for d in s["decisions"])
            parts.append(f'<div class="block"><h3>{esc(t["decisions"])}</h3>{docs}</div>')
        house = read(PLUGIN_ROOT / "template/.keelokit/harness/stack.md")
        if house and stage["status"] != "todo":
            parts.append(f'<div class="block"><h3>{esc(t["house_stack"])}</h3>'
                         f'<details class="doc"><summary><span class="path">house stack · Keelokit</span></summary>'
                         f'<div class="md">{markdown(house)}</div></details></div>')
    elif sid == "skeleton" and (s["answers"] or s["has_commits"]):
        facts = []
        if s["answers"]:
            facts.append((t["generated"], f'Keelokit {esc(s["answers"].get("_commit", ""))}'))
            if apps := s["answers"].get("apps"):
                facts.append((t["apps"], f"<code>{esc(apps)}</code>"))
        if s["first_commit"]:
            facts.append((t["first_commit"], f"<code>{esc(s['first_commit'])}</code>"))
        if s["github"]:
            repo = s["github"].removesuffix("/blob/main/")
            facts.append((t["remote"], f'<a href="{esc(repo)}" target="_blank" rel="noopener">{esc(repo.removeprefix("https://"))}</a>'))
        dl = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in facts)
        parts.append(f'<div class="block"><h3>{esc(t["skeleton_facts"])}</h3><dl class="facts">{dl}</dl></div>')
    elif sid == "adopt":
        for rel in stage["outputs"]:
            parts.append(doc_block(rel, read(root / rel), links, t))
    elif sid == "backlog" and s["stories"]:
        parts.append(backlog_block(s, links, t))
    if not parts:
        parts.append(f'<p class="muted">{esc(t["not_yet"])}</p>')
    return "\n".join(parts)


def story_row(st: dict, s: dict, links: Links, t: dict) -> str:
    status = st["status"]
    label = {
        "done": t["story_done"], "ready": t["story_ready"],
        "blocked": t["story_blocked"].format(deps=", ".join(st.get("waits", []))),
        "gap": t["story_gap"].format(gaps=", ".join(st["gaps"])),
    }[status]
    href = links.href(st["path"])
    a = f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(t["open_github"] if links.github else t["open_file"])}</a>' if href else ""
    deps = (f'<p class="muted">{esc(t["depends"])}: ' + ", ".join(f"<code>{esc(d)}</code>" for d in st["depends_on"]) + "</p>") \
        if st["depends_on"] else ""
    return (f'<details class="doc story"><summary><span class="sid">{esc(st["id"])}</span>'
            f'<span class="stitle">{esc(st["title"])}</span><span class="chip">{esc(st["epic"])}</span>'
            f'<span class="pill {status}">{esc(label)}</span></summary>'
            f'<div class="md">{a and f"<p>{a}</p>"}{deps}{markdown(st["body"], links, st["path"])}</div></details>')


def group(title: str, items: list[dict], s: dict, links: Links, t: dict, note: str = "") -> str:
    done = sum(1 for x in items if x["status"] == "done")
    pct = round(100 * done / len(items)) if items else 0
    return (f'<div class="group"><div class="group-head"><h3>{title}</h3>'
            f'<span class="count">{done}/{len(items)}</span><span class="progress"><i style="width:{pct}%"></i></span></div>'
            + (f'<p class="muted">{esc(note)}</p>' if note else "")
            + '<div class="stories">' + "".join(story_row(x, s, links, t) for x in items) + "</div></div>")


def backlog_block(s: dict, links: Links, t: dict) -> str:
    stories = s["stories"]
    done = sum(1 for x in stories if x["status"] == "done")
    waves = sorted({x["wave"] for x in stories})
    by_wave = "".join(group(esc(t["wave"].format(n=w)), [x for x in stories if x["wave"] == w], s, links, t, t["wave_note"])
                      for w in waves)
    by_epic = "".join(
        group(f'{esc(t["epic"])} <code>{esc(e)}</code>' + (f" · {inline(goal)}" if goal else ""),
              [x for x in stories if x["epic"] == e], s, links, t)
        for e, goal in s["epics"].items() if any(x["epic"] == e for x in stories))
    epics_doc = doc_block("backlog/epics.md", read(s["root"] / "backlog/epics.md"), links, t) \
        if (s["root"] / "backlog/epics.md").exists() else ""
    return (f'<div class="toolbar"><strong>{esc(t["backlog_total"].format(done=done, total=len(stories)))}</strong>'
            f'<span class="progress"><i style="width:{round(100 * done / len(stories))}%"></i></span>'
            f'<button type="button" class="ghost" data-show="wave" aria-pressed="true">{esc(t["by_wave"])}</button>'
            f'<button type="button" class="ghost" data-show="epic" aria-pressed="false">{esc(t["by_epic"])}</button></div>'
            f'<div class="block" data-view="wave">{by_wave}</div><div class="block" data-view="epic" hidden>{by_epic}</div>'
            f'{epics_doc}')


def render(s: dict, lang: str, standalone: bool, out_dir: Path, version: str) -> str:
    t, stage_copy = T[lang], STAGES[lang]
    links = Links(s["github"], standalone, out_dir, s["root"])
    nxt, waiting = next_step(s, lang), waiting_on_user(s, lang)
    current = next((x for x in s["stages"] if x["status"] in ("review", "current")), None)
    all_done = current is None

    rail = []
    for n, st in enumerate(s["stages"], 1):
        rail.append(f'<li><a href="#stage-{st["id"]}"><span class="n">{n:02d}</span>'
                    f'<span class="nm">{esc(stage_copy[st["id"]][0])}</span>'
                    f'<span class="pill {st["status"]}">{esc(t["st_" + st["status"]])}</span></a></li>')
    if s["stories"]:
        n = len(s["stages"]) + 1
        state = "current" if all_done else "todo"
        rail.append(f'<li><a href="#stage-build"><span class="n">{n:02d}</span><span class="nm">{esc(t["build_stage"])}</span>'
                    f'<span class="pill {state}">{esc(t["st_" + state])}</span></a></li>')

    sections = []
    for n, st in enumerate(s["stages"], 1):
        name, what, checks = stage_copy[st["id"]]
        when = f'<span class="when">{esc(t["approved_on"].format(date=st["date"]))}</span>' if st["date"] else ""
        check = ""
        if st["status"] == "review":
            items = "".join(f"<li>{esc(c)}</li>" for c in checks)
            check = (f'<div class="check"><h3>{esc(t["review"])}</h3><ul>{items}</ul>'
                     f'<p>{esc(t["how_approve"])}</p></div>')
        sections.append(
            f'<section class="stage {st["status"]}" id="stage-{st["id"]}"><div class="stage-head">'
            f'<span class="n">{n:02d}</span><h2>{esc(name)}</h2><span class="pill {st["status"]}">{esc(t["st_" + st["status"]])}</span>{when}</div>'
            f'<p class="what">{esc(what)}</p>{check}{stage_body(s, st, links, t, lang)}</section>')
    if s["stories"]:
        n = len(s["stages"]) + 1
        ready = [x for x in s["stories"] if x["status"] == "ready"]
        cmd_serial = f"/keelokit:build {ready[0]['id']}" if ready else "/keelokit:build"
        same = [x for x in ready if ready and x["wave"] == ready[0]["wave"]]
        cmd_parallel = f"/keelokit:build {max(len(same), 2)}"
        modes = (f'<div class="block"><h3>{esc(t["modes"])}</h3><p class="what">{esc(t["modes_intro"])}</p><div class="modes">'
                 f'<div class="mode"><h3>{esc(t["serial"])}</h3><p>{esc(t["serial_body"])}</p><p class="when">{esc(t["serial_when"])}</p>{copy_cmd(cmd_serial, t)}</div>'
                 f'<div class="mode"><h3>{esc(t["parallel"])}</h3><p>{esc(t["parallel_body"])}</p><p class="when">{esc(t["parallel_when"])}</p>{copy_cmd(cmd_parallel, t)}</div>'
                 f'</div></div>')
        health = ""
        if s["doctor"]:
            health = (f'<div class="block"><h3>{esc(t["health"])}</h3><div class="scroll"><pre class="out"><code>'
                      f'{esc(chr(10).join(s["doctor"]))}</code></pre></div></div>')
        state = "current" if all_done else "todo"
        sections.append(
            f'<section class="stage {state}" id="stage-build"><div class="stage-head"><span class="n">{n:02d}</span>'
            f'<h2>{esc(t["build_stage"])}</h2><span class="pill {state}">{esc(t["st_" + state])}</span></div>'
            f'<p class="what">{esc(t["build_what"])}</p>{modes}{health}</section>')

    where = stage_copy[current["id"]][0] if current else t["build_stage"]
    where_pill = f'<span class="pill {current["status"]}">{esc(t["st_" + current["status"]])}</span>' if current else ""
    wait_html = ("<ul>" + "".join(f'<li><a href="#{esc(w["anchor"])}">{inline(w["text"])}</a></li>' for w in waiting) + "</ul>") \
        if waiting else f'<p>{esc(t["nothing_waiting"])}</p>'
    cmd = (copy_cmd(nxt["command"], t) + f'<span class="hint">{esc(t["copy_hint"])}</span>') if nxt["command"] else ""
    gloss = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in GLOSSARY[lang])
    when = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    img = logo()

    page = f"""<title>{esc(t["title"].format(name=s["name"]))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=JetBrains+Mono:wght@500;600&family=Manrope:wght@400;500;600;700&display=swap">
<style>{CSS}</style>
<header class="bar"><div class="bar-in">{f'<img src="{img}" alt="">' if img else ""}<span class="wordmark">Keelokit</span><span class="sep">/</span><span class="product">{esc(s["name"])}</span><span class="ver">v{esc(version)}</span></div></header>
<main class="page">
<section aria-labelledby="where">
<p class="eyebrow">{esc(t["eyebrow"])}</p>
<h1 id="where">{esc(s["name"])}</h1>
<div class="now">
<div class="panel"><p class="eyebrow">{esc(t["where"])}</p><div class="big"><a href="#{f'stage-{current["id"]}' if current else 'stage-build'}">{esc(where)}</a></div>{where_pill}</div>
<div class="panel next"><p class="eyebrow">{esc(t["next"])}</p><div class="big"><a href="#{esc(nxt["anchor"])}">{esc(nxt["title"])}</a></div><p>{esc(nxt["detail"])}</p>{cmd}</div>
<div class="panel wait"><p class="eyebrow">{esc(t["waiting"])}</p>{wait_html}</div>
</div>
</section>
<nav aria-label="{esc(t["stages"])}"><ol class="rail">{"".join(rail)}</ol></nav>
{"".join(sections)}
<section class="stage" id="glossary"><h2>{esc(t["glossary"])}</h2><dl class="gloss">{gloss}</dl></section>
<footer>{esc(t["footer"].format(when=when, version=version))}</footer>
</main>
<script>{JS}</script>
"""
    if standalone:
        return (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>\n'
                f"<body>{page}</body></html>\n")
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--lang", choices=sorted(T), default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--standalone", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = (args.root or find_root(Path.cwd())).resolve()
    s = collect(root)
    try:
        dash = tomllib.loads(read(root / ".keelokit/state.toml")).get("dashboard", {})
    except tomllib.TOMLDecodeError:
        dash = {}
    lang = args.lang or (dash.get("lang") if dash.get("lang") in T else "en")

    if args.json:
        view = {k: v for k, v in s.items() if k not in ("root", "by_id", "context", "prd", "stack_doc", "diagnosis")}
        view["stories"] = [{k: v for k, v in x.items() if k != "body"} for x in s["stories"]]
        view["done"] = sorted(s["done"])
        view["next"] = next_step(s, lang)
        view["waiting"] = waiting_on_user(s, lang)
        print(json.dumps(view, indent=2, ensure_ascii=False))
        return 0

    out = args.out or root / ".keelokit/out/dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.parent == root / ".keelokit/out" and not (out.parent / ".gitignore").exists():
        (out.parent / ".gitignore").write_text("*\n")
    try:
        version = json.loads(read(PLUGIN_ROOT / ".claude-plugin/plugin.json")).get("version", "")
    except json.JSONDecodeError:
        version = ""
    out.write_text(render(s, lang, args.standalone, out.parent, version), encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
