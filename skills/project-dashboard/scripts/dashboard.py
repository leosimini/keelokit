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
A --root that isn't a folder exits 2 and a write that fails (a read-only checkout) exits 1, each
with one line naming the path.
Stdlib only (Python 3.11+ for tomllib).
"""
import sys

if sys.version_info < (3, 11):
    print(f"Keelokit needs Python 3.11+ (found {sys.version.split()[0]}).", file=sys.stderr)
    sys.exit(1)

import argparse  # noqa: E402
import base64  # noqa: E402
import bisect  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import html  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tomllib  # noqa: E402
import unicodedata  # noqa: E402
from pathlib import Path  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CONTEXT_FILES = ["product.md", "domain.md", "constraints.md", "environments.md", "gaps.md"]
GATES = {
    "project": ["intake", "product", "stack", "skeleton", "backlog"],  # /keelokit:project-new
    "harness": ["intake", "adopt", "backlog"],  # /keelokit:project-adopt
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
        "health_log": "Salida del doctor (doctor.py --brief), tal como la imprime, en inglés:",
        "health_ok": "El doctor no encontró errores",
        "backlog_total": ("{done} de {n} historia terminada", "{done} de {n} historias terminadas"),
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
        "footer": "Generado el {when} a partir del repositorio · Keelokit {version} · Para actualizarlo: /keelokit:project-dashboard",
        "next_review": "Revisá la etapa «{stage}» y aprobala",
        "next_review_d": "Todo lo que hay que mirar está en su sección de este tablero.",
        "next_continue": "Seguir con la etapa «{stage}»",
        "next_continue_d": "Keelokit retoma desde donde quedó.",
        "next_gaps": "Responder las preguntas que bloquean",
        "next_gaps_d": ("Hay {n} pregunta abierta que bloquea el avance.", "Hay {n} preguntas abiertas que bloquean el avance."),
        "next_build": "Construir {sid}: {title}",
        "next_build_d": ("{ids} es la única historia lista en la ola {wave}.",
                         "Hay {n} historias listas en la ola {wave}. En serie: una por vez. En paralelo: «/keelokit:build-story {ids}»."),
        "next_blocked": "Destrabar la próxima ola",
        "next_blocked_d": "Ninguna historia está lista: cada una espera a otra que todavía no terminó.",
        "next_more": "Planificar lo que sigue",
        "next_more_d": "Todas las historias están terminadas. Sumá la próxima parte del producto.",
        "next_doctor": "Revisar la salud del harness",
        "next_doctor_d": ("El doctor encontró {n} error.", "El doctor encontró {n} errores."),
        "wait_gate": "Aprobar «{stage}»",
        "wait_gap": "{gap}: {question}",
        "wait_errors": ("{n} error del harness para revisar", "{n} errores del harness para revisar"),
        "wait_no_main": "No hay main ni origin/main: ninguna historia cuenta como terminada hasta que lo traigas (git fetch origin main)",
        "build_stage": "Construcción",
        "profile_k": "Qué es el proyecto",
        "kinds": {"web-product": "Producto web", "mobile-app": "App móvil", "api-service": "Servicio (API)",
                  "library": "Librería", "cli": "Herramienta de línea de comandos", "plugin": "Plugin",
                  "static-site": "Sitio estático", "other": "Otro"},
        "traits": {"typescript": "TypeScript", "ui": "con interfaz", "web": "web", "mobile": "móvil", "site": "sitio público",
                   "api": "API", "database": "base de datos", "hosted": "se hostea", "i18n": "varios idiomas",
                   "personal-data": "datos personales", "payments": "pagos", "developer-facing": "para desarrolladores"},
        "traits_none": "sin interfaz, sin base de datos, sin hosting",
        "wait_profile_unknown": "Diagnosticar qué es el proyecto (decide qué reglas aplican)",
        "wait_profile_drift": "El perfil del proyecto quedó desactualizado",
        "wait_profile_drift_seen": "El perfil del proyecto quedó desactualizado: el repo tiene `{trait}` ({seen}) y el perfil no lo lista",
        "wait_profile_drift_missing": "El perfil del proyecto quedó desactualizado: el perfil lista `{trait}` y nada en el repo lo muestra todavía",
        "act_profile": "Actualizar el perfil",
        "credit_k": "Firma Keelokit",
        "credit_names": {"visible": "visible", "quiet": "discreta", "off": "sin firma"},
        "credit_what": {"visible": "el badge «Built with Keelokit» en el README y una línea al pie del sitio público",
                        "quiet": "el badge en el README y una etiqueta invisible en el HTML",
                        "off": "nada"},
        "credit_to": "Pasar a {level}",
        "credit_ask": "Cambiá la firma de Keelokit a «{level}»: {what}.",
        "credit_thanks": "Gracias por firmar: así Keelokit llega a más gente.",
        "theme_dark": "Tema oscuro",
        "theme_light": "Tema claro",
        "env_h": "Entornos",
        "env_what": "Dónde corre el producto: staging, para probar cada cambio antes de que lo vean los usuarios, y producción, donde están los usuarios. Cada entorno tiene su lista de pasos, verificados uno por uno.",
        "env_none": "Todavía no hay guía de despliegue. /keelokit:ship-setup la arma, hace lo que no necesita tus cuentas y verifica cada paso.",
        "env_steps": ("{done} de {n} paso listo", "{done} de {n} pasos listos"),
        "env_nosteps": "Sin pasos todavía",
        "env_sum": ("{ready} de {n} entorno listo", "{ready} de {n} entornos listos"),
        "act_setup": "Preparar los entornos",
        "act_release": "Sacar una versión",
        "act_security": "Revisar seguridad y privacidad",
        "act_upgrade": "Actualizar el harness",
        "sec_h": "Seguridad y privacidad",
        "sec_what": "Una revisión a fondo: qué datos personales guarda el producto y por qué, qué pide la ley de cada mercado, cómo alguien podría abusar de cada recorrido crítico, y escaneos de dependencias y de staging. Cada problema se corrige con un test y deja un control para que no vuelva.",
        "sec_none": "Todavía no se hizo ninguna. Conviene antes del primer lanzamiento a producción.",
        "sec_run": "Revisión del {date}",
        "found_h": "Lo que encontramos",
        "found_stack": "Stack",
        "found_ci": "Integración continua",
        "found_hosting": "Despliegue",
        "found_tests": "Tests",
        "rules_h": "Reglas de la casa en este repo",
        "rules_counts": "De {house}: {mapped} · {exc} · el resto, con los controles de Keelokit",
        "n_rules": ("{n} regla", "{n} reglas"),
        "n_mapped": ("{n} cubierta por lo que el repo ya tenía", "{n} cubiertas por lo que el repo ya tenía"),
        "n_dated_exc": ("{n} excepción con fecha", "{n} excepciones con fecha"),
        "exc_cols": ["Regla", "Motivo", "Aprobó", "Vence"],
        "harness_k": "Harness",
        "harness_behind": "v{have} · hay v{new}",
        "harness_ok": "v{have}, al día",
        "wait_harness": "Actualizar el harness: v{have} → v{new}",
        "h_security": "Revisión de seguridad",
        "wait_sec": "Decidir lo pendiente de la revisión de seguridad del {date} ({n})",
        "act_decide_sec_t": "Sobre las decisiones pendientes de la revisión de seguridad del {date}: ",
        "type": "Tipo de proyecto",
        "greenfield": "Producto nuevo (greenfield)",
        "brownfield": "Repositorio existente (brownfield)",
        "greenfield_d": "Se arma desde cero con el esqueleto de Keelokit.",
        "brownfield_d": "Keelokit se sumó a un código que ya existía, sin reescribirlo.",
        "apps_k": "Aplicaciones",
        "adrs_k": "Decisiones registradas",
        "no_adrs": "Ningún desvío del stack de la casa.",
        "ask_h": "Pedile a Claude",
        "ask_ph": "Elegí una acción del tablero o escribí lo que necesites…",
        "ask_send": "Enviar a Claude",
        "ask_copy": "Copiar",
        "ask_sent": "Enviado. Claude lo recibe en la sesión que mira este tablero y responde en los comentarios.",
        "ask_copy_only": "Copialo y pegalo en el chat de Claude Code.",
        "ask_no_session": "Ahora no hay una sesión de Claude mirando este tablero: copiá el texto y pegalo en el chat.",
        "ask_writers": "Solo quien edita el tablero puede enviarle pedidos a Claude. Podés copiarlo.",
        "ask_consent": "No se envió: falta tu permiso para comentar desde la página. Probá de nuevo y aceptalo.",
        "ask_rate": "Esperá un momento antes de enviar otro pedido.",
        "ask_failed": "No se pudo enviar. Copiá el texto y pegalo en el chat.",
        "act_approve": "Aprobar",
        "act_approve_t": "Apruebo la etapa «{stage}».",
        "act_change": "Pedir cambios",
        "act_change_t": "En la etapa «{stage}» quiero cambiar esto: ",
        "act_answer": "Responder",
        "act_answer_t": "Respuesta a {gap}: ",
        "act_continue_t": "{cmd}",
        "act_build": "Construir {sid}",
        "act_build_wave": "Construir la ola {w} en paralelo",
        "act_bugbash": "Hacer un bug bash",
        "act_feature": "Sumar una funcionalidad",
        "act_feature_t": "Quiero sumar esta funcionalidad al producto (hacé el intake y ampliá el backlog): ",
        "act_refresh": "Actualizar el tablero",
        "act_doctor": "Revisar la salud",
        "act_decide": "Decidir",
        "act_decide_t": "Sobre las decisiones pendientes del bug bash del {date}: ",
        "act_build_one": "Construir esta historia",
        "actions": "Acciones",
        "history": "Historial",
        "history_sum": "Eventos: {n} · el último, el {date}",
        "h_story": "Historia terminada",
        "h_bugbash": "Bug bash",
        "h_gate": "Etapa aprobada",
        "h_gate_auto": "Etapa aprobada automáticamente",
        "bb": "Bug bashes",
        "bb_what": "Un bug bash es una cacería de errores en todo el producto: varios agentes lo recorren por dimensiones (datos, seguridad, textos, accesibilidad…), otro confirma cada hallazgo, se corrige la causa y se agrega un control para que ese tipo de error no vuelva. Lo que no se corrige en el momento pasa al backlog como historia.",
        "bb_sum": "Ejecutados: {n} · hallazgos: {found} · corregidos: {fixed} · historias nuevas: {stories}",
        "bb_none": "Todavía no se hizo ninguno. Conviene uno al terminar cada ola.",
        "bb_run": "Bug bash del {date}",
        "bb_counts": "Hallazgos: {found} · corregidos: {fixed} · por decidir: {pending} · abiertos: {open}",
        "bb_cols": ["Id", "Severidad", "Hallazgo", "Estado", "Control agregado"],
        "bb_pending": "Decisiones pendientes",
        "bb_stories": "Historias que generó",
        "wait_bb": "Decidir lo pendiente del bug bash del {date} ({n})",
        "decisions_h": "Decisiones del proyecto",
        "run_mode": "Modo de ejecución",
        "run_auto": "Automático",
        "run_step": "Por etapas",
        "run_auto_d": "Avanza solo en todo lo que puede. Se detiene únicamente donde hace falta una persona: aprobar el PRD o un desvío del stack, preguntas que solo vos podés responder, cuentas y credenciales, producción, dinero, temas legales y borrar datos.",
        "run_step_d": "Se detiene al terminar cada etapa para que la revises y la apruebes, y entre una historia y la siguiente.",
        "build_mode": "Forma de construir",
        "build_serial": "En serie",
        "build_parallel": "En paralelo · hasta {n} a la vez",
        "undecided": "Sin definir: Keelokit lo pregunta una sola vez, al empezar.",
        "decided_on": "Definido el {date}",
        "locked_note": "Son fijas: Keelokit no las vuelve a preguntar ni las cambia por su cuenta. Para cambiarlas, pedilo explícitamente en el chat.",
        "wait_decide": "Elegir el modo de ejecución y la forma de construir",
        "auto_on": "Aprobada automáticamente el {date}",
        "st_auto": "Automática",
        "chosen": "Elegido",
        "what_means": "Qué significa cada opción",
        "current_stage": "Etapa actual",
        "all_gates": "Todas las etapas aprobadas",
        "sum_intake": "{docs} · {gaps} ({blocking}) · {inv}",
        "n_docs": ("{n} documento", "{n} documentos"),
        "n_open_q": ("{n} pregunta abierta", "{n} preguntas abiertas"),
        "n_blocking": ("{n} bloquea", "{n} bloquean"),
        "n_inv": ("{n} invariante", "{n} invariantes"),
        "sum_product": "{metrics} · {inn} en el alcance · {out} afuera",
        "n_metrics": ("{n} métrica", "{n} métricas"),
        "sum_stack": "Aplicaciones: {apps}",
        "sum_skeleton": "Primer commit {commit}",
        "sum_adopt": ("{n} excepción registrada", "{n} excepciones registradas"),
        "sum_backlog": "{total} · {waves} · {epics}",
        "n_stories": ("{n} historia", "{n} historias"),
        "n_waves": ("{n} ola", "{n} olas"),
        "n_epics": ("{n} épica", "{n} épicas"),
        "sum_build": ("{done} de {n} historia terminada", "{done} de {n} historias terminadas"),
        "sum_none": "Todavía no empezó",
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
        "health_log": "The doctor's output (doctor.py --brief), as it prints it:",
        "health_ok": "The doctor found no errors",
        "backlog_total": ("{done} of {n} story done", "{done} of {n} stories done"),
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
        "footer": "Generated {when} from the repository · Keelokit {version} · To refresh: /keelokit:project-dashboard",
        "next_review": "Review the \"{stage}\" stage and approve it",
        "next_review_d": "Everything to look at is in its section of this dashboard.",
        "next_continue": "Continue the \"{stage}\" stage",
        "next_continue_d": "Keelokit resumes where it stopped.",
        "next_gaps": "Answer the blocking questions",
        "next_gaps_d": ("{n} open question blocks progress.", "{n} open questions block progress."),
        "next_build": "Build {sid}: {title}",
        "next_build_d": ("{ids} is the only story ready in wave {wave}.",
                         "{n} stories are ready in wave {wave}. One at a time, or in parallel with \"/keelokit:build-story {ids}\"."),
        "next_blocked": "Unblock the next wave",
        "next_blocked_d": "No story is ready: each one waits for another that isn't done yet.",
        "next_more": "Plan what comes next",
        "next_more_d": "Every story is done. Add the next slice of the product.",
        "next_doctor": "Check the harness health",
        "next_doctor_d": ("The doctor found {n} error.", "The doctor found {n} errors."),
        "wait_gate": "Approve \"{stage}\"",
        "wait_gap": "{gap}: {question}",
        "wait_errors": ("{n} harness error to review", "{n} harness errors to review"),
        "wait_no_main": "No main or origin/main here: no story counts as done until you fetch it (git fetch origin main)",
        "build_stage": "Build",
        "profile_k": "What the project is",
        "kinds": {"web-product": "Web product", "mobile-app": "Mobile app", "api-service": "Service (API)",
                  "library": "Library", "cli": "Command-line tool", "plugin": "Plugin",
                  "static-site": "Static site", "other": "Other"},
        "traits": {"typescript": "TypeScript", "ui": "with a UI", "web": "web", "mobile": "mobile", "site": "public site",
                   "api": "API", "database": "database", "hosted": "hosted", "i18n": "several languages",
                   "personal-data": "personal data", "payments": "payments", "developer-facing": "for developers"},
        "traits_none": "no UI, no database, no hosting",
        "wait_profile_unknown": "Diagnose what the project is (it decides which rules apply)",
        "wait_profile_drift": "The project's profile is out of date",
        "wait_profile_drift_seen": "The project's profile is out of date: the repo shows `{trait}` ({seen}) but the profile doesn't list it",
        "wait_profile_drift_missing": "The project's profile is out of date: the profile lists `{trait}` but nothing in the repo shows it yet",
        "act_profile": "Update the profile",
        "credit_k": "Keelokit credit",
        "credit_names": {"visible": "visible", "quiet": "quiet", "off": "off"},
        "credit_what": {"visible": "the “Built with Keelokit” badge in the README and a line at the foot of the public site",
                        "quiet": "the README badge and an invisible tag in the HTML",
                        "off": "nothing"},
        "credit_to": "Switch to {level}",
        "credit_ask": "Change the Keelokit credit to “{level}”: {what}.",
        "credit_thanks": "Thanks for the credit: it's how Keelokit reaches more people.",
        "theme_dark": "Dark theme",
        "theme_light": "Light theme",
        "env_h": "Environments",
        "env_what": "Where the product runs: staging, to try every change before users see it, and production, where the users are. Each environment has its list of steps, each one verified.",
        "env_none": "No deploy guide yet. /keelokit:ship-setup writes it, does what doesn't need your accounts and verifies every step.",
        "env_steps": ("{done} of {n} step ready", "{done} of {n} steps ready"),
        "env_nosteps": "No steps yet",
        "env_sum": ("{ready} of {n} environment ready", "{ready} of {n} environments ready"),
        "act_setup": "Set up the environments",
        "act_release": "Release a version",
        "act_security": "Review security and privacy",
        "act_upgrade": "Upgrade the harness",
        "sec_h": "Security and privacy",
        "sec_what": "An in-depth review: which personal data the product keeps and why, what each market's law asks, how someone could abuse each critical journey, and scans of the dependencies and of staging. Every problem is fixed with a test and leaves a check so it can't come back.",
        "sec_none": "None yet. Worth doing before the first production release.",
        "sec_run": "Review of {date}",
        "found_h": "What we found",
        "found_stack": "Stack",
        "found_ci": "Continuous integration",
        "found_hosting": "Deploys",
        "found_tests": "Tests",
        "rules_h": "House rules in this repo",
        "rules_counts": "Of {house}: {mapped} · {exc} · the rest, by Keelokit's own checks",
        "n_rules": ("{n} rule", "{n} rules"),
        "n_mapped": ("{n} covered by what the repo already had", "{n} covered by what the repo already had"),
        "n_dated_exc": ("{n} dated exception", "{n} dated exceptions"),
        "exc_cols": ["Rule", "Reason", "Approved by", "Expires"],
        "harness_k": "Harness",
        "harness_behind": "v{have} · v{new} available",
        "harness_ok": "v{have}, up to date",
        "wait_harness": "Upgrade the harness: v{have} → v{new}",
        "h_security": "Security review",
        "wait_sec": "Decide what is pending from the {date} security review ({n})",
        "act_decide_sec_t": "About the pending decisions of the {date} security review: ",
        "type": "Project type",
        "greenfield": "New product (greenfield)",
        "brownfield": "Existing repository (brownfield)",
        "greenfield_d": "Built from scratch on the Keelokit skeleton.",
        "brownfield_d": "Keelokit joined code that already existed, without rewriting it.",
        "apps_k": "Apps",
        "adrs_k": "Recorded decisions",
        "no_adrs": "No deviation from the house stack.",
        "ask_h": "Ask Claude",
        "ask_ph": "Pick an action on the dashboard or write what you need…",
        "ask_send": "Send to Claude",
        "ask_copy": "Copy",
        "ask_sent": "Sent. Claude gets it in the session watching this dashboard and answers in the comments.",
        "ask_copy_only": "Copy it and paste it into the Claude Code chat.",
        "ask_no_session": "No Claude session is watching this dashboard right now: copy the text and paste it into the chat.",
        "ask_writers": "Only editors of the dashboard can send requests to Claude. You can copy it.",
        "ask_consent": "Not sent: the page needs your permission to comment. Try again and allow it.",
        "ask_rate": "Wait a moment before sending another request.",
        "ask_failed": "It couldn't be sent. Copy the text and paste it into the chat.",
        "act_approve": "Approve",
        "act_approve_t": "I approve the \"{stage}\" stage.",
        "act_change": "Ask for changes",
        "act_change_t": "In the \"{stage}\" stage I want to change this: ",
        "act_answer": "Answer",
        "act_answer_t": "Answer to {gap}: ",
        "act_continue_t": "{cmd}",
        "act_build": "Build {sid}",
        "act_build_wave": "Build wave {w} in parallel",
        "act_bugbash": "Run a bug bash",
        "act_feature": "Add a feature",
        "act_feature_t": "I want to add this feature to the product (run the intake and extend the backlog): ",
        "act_refresh": "Refresh the dashboard",
        "act_doctor": "Check the health",
        "act_decide": "Decide",
        "act_decide_t": "About the pending decisions of the {date} bug bash: ",
        "act_build_one": "Build this story",
        "actions": "Actions",
        "history": "History",
        "history_sum": "Events: {n} · latest on {date}",
        "h_story": "Story done",
        "h_bugbash": "Bug bash",
        "h_gate": "Stage approved",
        "h_gate_auto": "Stage approved automatically",
        "bb": "Bug bashes",
        "bb_what": "A bug bash hunts for errors across the whole product: several agents walk it by dimension (data, security, copy, accessibility…), another confirms each finding, the cause gets fixed and a check is added so that kind of error can't come back. Whatever isn't fixed on the spot goes to the backlog as a story.",
        "bb_sum": "Runs: {n} · findings: {found} · fixed: {fixed} · new stories: {stories}",
        "bb_none": "None yet. One after each wave is a good habit.",
        "bb_run": "Bug bash of {date}",
        "bb_counts": "Findings: {found} · fixed: {fixed} · to decide: {pending} · open: {open}",
        "bb_cols": ["Id", "Severity", "Finding", "Status", "Check added"],
        "bb_pending": "Pending decisions",
        "bb_stories": "Stories it created",
        "wait_bb": "Decide what is pending from the {date} bug bash ({n})",
        "decisions_h": "Project decisions",
        "run_mode": "Run mode",
        "run_auto": "Automatic",
        "run_step": "Stage by stage",
        "run_auto_d": "Goes on alone wherever it can. It stops only where a person is needed: approving the PRD or a stack deviation, questions only you can answer, accounts and credentials, production, money, legal matters and deleting data.",
        "run_step_d": "Stops at the end of every stage for you to review and approve it, and between one story and the next.",
        "build_mode": "How stories are built",
        "build_serial": "One at a time",
        "build_parallel": "In parallel · up to {n} at once",
        "undecided": "Not set yet: Keelokit asks once, at the start.",
        "decided_on": "Set on {date}",
        "locked_note": "These are fixed: Keelokit doesn't ask again or change them on its own. To change one, ask for it explicitly in the chat.",
        "wait_decide": "Choose the run mode and how stories are built",
        "auto_on": "Approved automatically on {date}",
        "st_auto": "Automatic",
        "chosen": "Chosen",
        "what_means": "What each option means",
        "current_stage": "Current stage",
        "all_gates": "Every stage approved",
        "sum_intake": "{docs} · {gaps} ({blocking}) · {inv}",
        "n_docs": ("{n} document", "{n} documents"),
        "n_open_q": ("{n} open question", "{n} open questions"),
        "n_blocking": ("{n} blocking", "{n} blocking"),
        "n_inv": ("{n} invariant", "{n} invariants"),
        "sum_product": "{metrics} · {inn} in scope · {out} out",
        "n_metrics": ("{n} metric", "{n} metrics"),
        "sum_stack": "Apps: {apps}",
        "sum_skeleton": "First commit {commit}",
        "sum_adopt": ("{n} exception recorded", "{n} exceptions recorded"),
        "sum_backlog": "{total} · {waves} · {epics}",
        "n_stories": ("{n} story", "{n} stories"),
        "n_waves": ("{n} wave", "{n} waves"),
        "n_epics": ("{n} epic", "{n} epics"),
        "sum_build": ("{done} of {n} story done", "{done} of {n} stories done"),
        "sum_none": "Not started yet",
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
        ("Bug bash", "Una cacería de errores en todo el producto, que deja un control nuevo por cada tipo de error encontrado."),
        ("Modo automático", "Keelokit avanza solo y se detiene únicamente donde las reglas de la casa piden a una persona."),
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
        ("Bug bash", "A hunt for errors across the whole product that leaves a new check for every kind of error it finds."),
        ("Automatic mode", "Keelokit goes on alone and stops only where the house rules call for a person."),
    ],
}



def plural(t: dict, key: str, n: int, **kw) -> str:
    """A count in words. t[key] is a (one, other) pair: `one` when n is 1, `other` for the rest,
    zero included, in both languages. Every number that sits before a word goes through here, and
    a phrase with several counts takes them already rendered; tests/test_dashboard.py holds T to it."""
    one, other = t[key]
    return (one if n == 1 else other).format(n=n, **kw)


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


# The sections and fields the dashboard reads out of documents it doesn't write: the PRD
# (skills/project-new/references/prd-template.md), the bug bash and security reports (their skills
# and workflows/check-bugbash-flow.js), the decision records (template/docs/decisions/README.md:
# Status, Context, Decision, Consequences) and docs/stack.md (its apps, from project-new). A project
# writes them in its own language (project-new writes English unless the user asks otherwise),
# whatever the page's language, so each one is found by its name in every language of T, ignoring
# case and accents. A section's heading matches a name as whole words and may go on after it ("In
# (MVP):", "Decisiones pendientes (2)"); `**Label:**` lines are headings too for "in" and "out", which
# the PRD writes that way inside Scope. A field is a `Label: value` line (or `**Label:** value`) naming
# it exactly, or for "status" a heading naming it with the value on the next line.
HEADINGS = {
    "metrics": {"en": ("Success metrics",), "es": ("Métricas de éxito", "Métricas")},
    "scope": {"en": ("Scope",), "es": ("Alcance",)},
    "in": {"en": ("In",), "es": ("Dentro", "Incluido")},
    "out": {"en": ("Out",), "es": ("Afuera", "Fuera", "Excluido")},
    "pending": {"en": ("Pending decisions",), "es": ("Decisiones pendientes",)},
    "status": {"en": ("Status",), "es": ("Estado",)},
    "apps": {"en": ("Apps", "App"), "es": ("Apps", "App", "Aplicaciones", "Aplicación")},
}


def fold(text: str) -> str:
    """Lower case without accents, with runs of spaces as one, for comparing headings."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return " ".join(plain.casefold().split())


def is_named(title: str, key: str, whole: bool = False) -> bool:
    """Whether `title` names `key` of HEADINGS in some language: exactly with `whole`, otherwise as its
    first words ("In (MVP):", "Dentro del MVP", but not "Integrations" or "In-store")."""
    title = fold(title)
    return any(title == n or (not whole and title.startswith(n) and title[len(n)] in " (:")
               for n in (fold(x) for xs in HEADINGS[key].values() for x in xs))


def md_section(text: str, key: str) -> str:
    """Body of the first heading that names section `key` of HEADINGS, in any language (up to the next
    heading of the same or higher level)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m and is_named(m.group(2), key):
            level = len(m.group(1))
            body = []
            for nxt in lines[i + 1:]:
                h = re.match(r"^(#{1,6})\s", nxt)
                if h and len(h.group(1)) <= level:
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    return ""


def md_field(text: str, key: str, heading: bool = False) -> str:
    """Value of the first `Label: value` line (also `**Label:** value`, `- Label: value`) whose label
    names field `key` of HEADINGS in any language; with `heading`, also a heading that names it, with
    the value on the next line. A label with nothing after it takes the next line too."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(?:[-*]\s+)?\**\s*([^:*#\n]+?)\s*\**\s*:\s*\**\s*(.*)$", line)
        h = re.match(r"^#{1,6}\s+(.+?)\s*$", line) if heading else None
        if (m and is_named(m.group(1), key, whole=True)) or (h and is_named(h.group(1), key, whole=True)):
            value = m.group(2).strip() if m else ""
            return value or next((x.strip() for x in lines[i + 1:] if x.strip()), "")
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


def main_ref(root: Path) -> str | None:
    """origin/main, else main; None when neither resolves. Never HEAD: a branch's own `Story:`
    trailers would count as done (INV-005)."""
    for ref in ("origin/main", "main"):
        if git(root, "rev-parse", "--verify", "--quiet", ref).strip():
            return ref
    return None


def collect(root: Path) -> dict:
    state_file = root / ".keelokit/state.toml"
    try:
        state = tomllib.loads(read(state_file)) if state_file.exists() else {}
    except tomllib.TOMLDecodeError:
        state = {}
    gates = {k: str(v) for k, v in state.get("gates", {}).items()}
    run = {k: v for k, v in state.get("run", {}).items() if k in ("mode", "build", "parallel", "decided")}
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
    ref = main_ref(root) if has_commits else None
    if ref:
        trailers = git(root, "log", ref, "--format=%(trailers:key=Story,valueonly,separator=%x2C)")
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
            "path": path.relative_to(root).as_posix(), "body": body, "origin": str(meta.get("origin", "")),
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
    drift = [read_drift(line) for line in doctor if line.startswith("Profile drift:")]

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
        value = gates.get(g, "")
        stages.append({"id": g, "status": status, "date": value[:10], "auto": value.endswith("auto"),
                       "outputs": outputs[g]})

    adrs = []
    for d in decisions:
        text = read(d)
        title = m.group(1).strip() if (m := re.search(r"(?m)^#\s+(.+)$", text)) else d.stem
        status = md_field(text, "status", heading=True)
        adrs.append({"path": d.relative_to(root).as_posix(), "title": title, "status": status})

    # Stories by `origin`, sorted, so each run finds the ones it made (their origin starts with
    # "<kind>:<date>", one block of the sorted list) without a scan of the backlog per run (NFR-1).
    origins = sorted((x["origin"], i) for i, x in enumerate(stories))

    def made_by(prefix: str) -> list[str]:
        at, hits = bisect.bisect_left(origins, (prefix,)), []
        while at < len(origins) and origins[at][0].startswith(prefix):
            hits.append(origins[at][1])
            at += 1
        return [stories[i]["id"] for i in sorted(hits)]

    def reports(folder: str, origin: str) -> list[dict]:
        runs = []
        for report in sorted((root / folder).glob("*/report.md"), reverse=True) if (root / folder).is_dir() else []:
            text = read(report)
            findings = []
            for row in table_rows(text):
                if re.fullmatch(r"[A-Z0-9]{2,5}-\d+", row[0]) and len(row) >= 5:
                    cells = row + [""] * 7
                    findings.append({"id": cells[0], "lens": cells[1], "severity": cells[2].upper()[:2],
                                     "title": cells[3], "status": cells[4], "commit": cells[5], "check": cells[6]})
            date = report.parent.name
            runs.append({
                "date": date, "path": report.relative_to(root).as_posix(), "text": text, "findings": findings,
                "sha": m.group(0) if (m := re.search(r"\b[0-9a-f]{7,40}\b", md_section(text, "scope") or text)) else "",
                "pending": md_section(text, "pending"),
                "stories": made_by(f"{origin}:{date}"),
            })
        return runs

    security = reports("docs/security", "security")
    bugbashes = reports("docs/bugbash", "bugbash")

    history = []
    if ref:
        for line in git(root, "log", ref, "-n", "400",
                        "--format=%as%x1f%h%x1f%s%x1f%(trailers:key=Story,valueonly,separator=%x2C)").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 4 and parts[3].strip():
                for sid in parts[3].split(","):
                    history.append({"date": parts[0], "kind": "story", "id": sid.strip(), "commit": parts[1],
                                    "title": by_id.get(sid.strip(), {}).get("title", parts[2])})
    history += [{"date": b["date"], "kind": "bugbash", "id": b["date"], "commit": b["sha"][:7], "title": b["path"]}
                for b in bugbashes]
    history += [{"date": b["date"], "kind": "security", "id": b["date"], "commit": b["sha"][:7], "title": b["path"]}
                for b in security]
    history += [{"date": v[:10], "kind": "gate", "id": g, "commit": "", "title": "auto" if v.endswith("auto") else ""}
                for g, v in gates.items() if v]
    history.sort(key=lambda e: e["date"], reverse=True)

    # Environments: the table in docs/context/environments.md, and each one's checklist in docs/deploy.md.
    deploy = read(root / "docs/deploy.md")
    envs = {}
    for row in table_rows(context.get("environments.md", "")):
        if row and row[0] and row[0].lower() not in ("environment", "entorno"):
            envs[row[0].strip("*` ")] = {"name": row[0].strip("*` "), "purpose": row[1] if len(row) > 1 else "",
                                         "url": row[2] if len(row) > 2 else "", "steps": []}
    for m in re.finditer(r"(?ms)^##\s+(.+?)\s*$(.*?)(?=^##\s|\Z)", deploy):
        env_name = m.group(1).strip()
        env = envs.setdefault(env_name, {"name": env_name, "purpose": "", "url": "", "steps": []})
        env["steps"] = [{"done": x.lower() == "x", "text": t.strip()}
                        for x, t in re.findall(r"(?m)^\s*[-*]\s+\[([ xX])\]\s+(.+)$", m.group(2))]
        if not env["purpose"]:
            first = next((l.strip() for l in m.group(2).splitlines() if l.strip() and not l.lstrip().startswith(("-", "*"))), "")
            env["purpose"] = first
    environments = [e for e in envs.values() if e["name"].lower() not in ("local",)]

    # What project-adopt found in an existing repo, and how the house rules map onto it.
    # The project's profile (kind, traits, what was detected); survey.toml was its name before 0.7.
    survey = {}
    for f in (".keelokit/profile.toml", ".keelokit/survey.toml"):
        if (root / f).exists():
            try:
                survey = tomllib.loads(read(root / f))
            except tomllib.TOMLDecodeError:
                survey = {}
            break
    profile = {"kind": survey.get("kind", ""), "traits": list(survey.get("traits", []))} if "kind" in survey else None
    def toml_list(path, key):
        try:
            return tomllib.loads(read(root / path)).get(key, []) if (root / path).exists() else []
        except tomllib.TOMLDecodeError:
            return []
    house_rules = len(re.findall(r"(?m)^id = \"", read(root / ".keelokit/harness/rules.toml")))
    mapping = {"house": house_rules, "mapped": len(toml_list(".keelokit/rules.local.toml", "rule")),
               "exceptions": toml_list(".keelokit/exceptions.toml", "exception")}

    # The harness this project runs (the template version it was generated from or last upgraded to).
    harness = ans.get("_commit", "").lstrip("v")
    # "Built with Keelokit": the template's `credit` answer (visible by default; adopted repos start without it).
    # Not stored when left at its default, so the README's marked block tells what the project really carries.
    credit = ans.get("credit") or ("visible" if "keelokit:credit" in read(root / "README.md") else "off")
    try:
        plugin_version = json.loads(read(PLUGIN_ROOT / ".claude-plugin/plugin.json")).get("version", "")
    except json.JSONDecodeError:
        plugin_version = ""

    # **In (MVP):** is a heading; other bold lines (**Buyers**) stay text inside In or Out.
    scope = re.sub(r"(?m)^\*\*([^*\n]+?)\*\*\s*$",
                   lambda m: f"## {m[1]}" if is_named(m[1], "in") or is_named(m[1], "out") else m[0], md_section(prd, "scope"))
    scope_in = md_section(scope, "in")
    scope_out = md_section(scope, "out")
    counts = {
        "metrics": max(len(table_rows(md_section(prd, "metrics"))) - 1, 0),
        "in": len(re.findall(r"(?m)^\s*[-*]\s", scope_in)),
        "out": len(re.findall(r"(?m)^\s*[-*]\s", scope_out)),
        "exceptions": len(re.findall(r"(?m)^\s*\[\[exception\]\]", read(root / ".keelokit/exceptions.toml"))),
    }

    return {
        "root": root, "name": name, "layout": layout, "gates": gates, "pending": pending,
        "stages": stages, "answers": ans, "prd": prd, "context": context, "gaps": gaps,
        "invariants": invariants, "decisions": [d.relative_to(root).as_posix() for d in decisions],
        "stack_doc": read(root / "docs/stack.md"), "diagnosis": read(root / "docs/diagnosis.md"),
        "stories": stories, "by_id": by_id, "epics": epics, "done": done,
        "has_commits": has_commits, "first_commit": first_commit, "github": github_base(root),
        "doctor": doctor, "errors": errors, "run": run, "counts": counts,
        "adrs": adrs, "bugbashes": bugbashes, "history": history, "security": security,
        "environments": environments, "has_deploy": bool(deploy), "survey": survey, "mapping": mapping,
        "harness": harness, "plugin_version": plugin_version, "credit": credit,
        "profile": profile, "drift": drift, "no_main": bool(has_commits and stories and not ref),
    }


# doctor.py --brief words drift in English (its DRIFT_SEEN and DRIFT_MISSING). The page reads each
# line back into the trait and what shows it and words it in its own language (I18N-1); a line it
# can't read (a doctor that words it otherwise) is still drift, said without the doctor's words.
DRIFT_LINES = [re.compile(r"the repo shows `(?P<trait>[^`]+)` \((?P<seen>.+)\) but the profile doesn't list it"),
               re.compile(r"the profile lists `(?P<trait>[^`]+)` but nothing in the repo shows it yet")]


def read_drift(line: str) -> dict:
    text = line.split(":", 1)[1].strip() if line.startswith("Profile drift:") else line.strip()
    m = next((m for rx in DRIFT_LINES if (m := rx.fullmatch(text))), None)
    return {"trait": m["trait"], "seen": m.groupdict().get("seen")} if m else {"trait": None, "seen": None}


def drift_sentence(d: dict, t: dict) -> str:
    if not d["trait"]:
        return t["wait_profile_drift"]
    return t["wait_profile_drift_seen" if d["seen"] else "wait_profile_drift_missing"].format(trait=d["trait"], seen=d["seen"])


def next_step(s: dict, lang: str) -> dict:
    t, names = T[lang], {k: v[0] for k, v in STAGES[lang].items()}
    blocking = [g for g in s["gaps"] if g["blocking"]]
    flow = "/keelokit:project-adopt" if s["layout"] == "harness" else "/keelokit:project-new"
    if s["pending"]:
        stage = next(x for x in s["stages"] if x["id"] == s["pending"])
        if stage["status"] == "review":
            return {"title": t["next_review"].format(stage=names[stage["id"]]), "detail": t["next_review_d"],
                    "command": None, "anchor": f"stage-{stage['id']}"}
        return {"title": t["next_continue"].format(stage=names[stage["id"]]), "detail": t["next_continue_d"],
                "command": flow, "anchor": f"stage-{stage['id']}"}
    if s["errors"]:
        return {"title": t["next_doctor"], "detail": plural(t, "next_doctor_d", s["errors"]),
                "command": "/keelokit:check-health", "anchor": "health"}
    if blocking:
        return {"title": t["next_gaps"], "detail": plural(t, "next_gaps_d", len(blocking)),
                "command": "/keelokit", "anchor": "stage-intake"}
    ready = [x for x in s["stories"] if x["status"] == "ready"]
    if ready:
        first = ready[0]
        same = [x for x in ready if x["wave"] == first["wave"]]
        return {"title": t["next_build"].format(sid=first["id"], title=first["title"]),
                "detail": plural(t, "next_build_d", len(same), wave=first["wave"], ids=story_ids(same)),
                "command": f"/keelokit:build-story {first['id']}", "anchor": "stage-build"}
    if s["stories"] and any(x["status"] != "done" for x in s["stories"]):
        return {"title": t["next_blocked"], "detail": t["next_blocked_d"], "command": "/keelokit",
                "anchor": "stage-backlog"}
    last_story = max((e["date"] for e in s["history"] if e["kind"] == "story"), default="")
    last_bb = max((b["date"] for b in s["bugbashes"]), default="")
    if s["stories"] and last_story and last_bb < last_story:
        return {"title": t["act_bugbash"], "detail": t["bb_none"] if not last_bb else t["next_more_d"],
                "command": "/keelokit:check-bugbash", "anchor": "bugbash"}
    return {"title": t["next_more"], "detail": t["next_more_d"], "command": "/keelokit:plan-backlog",
            "anchor": "stage-backlog"}


def behind(s: dict) -> bool:
    """The project's harness is older than the installed plugin."""
    def v(x):
        return tuple(int(p) for p in re.findall(r"\d+", x)[:3]) if re.match(r"^\d+\.\d+\.\d+", x or "") else None
    have, new = v(s["harness"]), v(s["plugin_version"])
    return bool(have and new and have < new)


def waiting_on_user(s: dict, lang: str) -> list[dict]:
    t, names = T[lang], {k: v[0] for k, v in STAGES[lang].items()}
    items = [{"text": t["wait_gate"].format(stage=names[x["id"]]), "anchor": f"stage-{x['id']}",
              "ask": t["act_approve_t"].format(stage=names[x["id"]]), "act": t["act_approve"]}
             for x in s["stages"] if x["status"] == "review"]
    items += [{"text": t["wait_gap"].format(gap=g["id"], question=g["question"] or g["missing"]),
               "anchor": "stage-intake", "ask": t["act_answer_t"].format(gap=g["id"]), "act": t["act_answer"]}
              for g in s["gaps"] if g["blocking"]]
    if s["errors"]:
        items.append({"text": plural(t, "wait_errors", s["errors"]), "anchor": "health"})
    if s["no_main"]:
        items.append({"text": t["wait_no_main"], "anchor": "stage-build"})
    for b in s["bugbashes"]:
        pending = [f for f in b["findings"] if f["status"].lower().startswith(("pending", "pendiente"))]
        if pending:
            items.append({"text": t["wait_bb"].format(n=len(pending), date=b["date"]), "anchor": f"bb-{b['date']}",
                          "ask": t["act_decide_t"].format(date=b["date"]), "act": t["act_decide"]})
    for b in s["security"]:
        pending = [f for f in b["findings"] if f["status"].lower().startswith(("pending", "pendiente"))]
        if pending:
            items.append({"text": t["wait_sec"].format(n=len(pending), date=b["date"]),
                          "anchor": f"sec-{b['date']}", "ask": t["act_decide_sec_t"].format(date=b["date"]), "act": t["act_decide"]})
    if s["profile"] and s["profile"]["kind"] in ("", "unknown"):
        items.append({"text": t["wait_profile_unknown"], "anchor": "decisions", "ask": "/keelokit:check-health", "act": t["act_profile"]})
    elif s["drift"]:
        items.append({"text": drift_sentence(s["drift"][0], t), "anchor": "decisions",
                      "ask": "/keelokit:check-health", "act": t["act_profile"]})
    if behind(s):
        items.append({"text": t["wait_harness"].format(have=s["harness"], new=s["plugin_version"]), "anchor": "decisions",
                      "ask": "/keelokit:harness-upgrade", "act": t["act_upgrade"]})
    if s["gates"] and not s["run"].get("mode"):
        items.append({"text": t["wait_decide"], "anchor": "decisions"})
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
# Page — the look of keelokit.com: foam ground, the sea gradient, Cormorant Garamond for display,
# Karla for text, Fragment Mono for ids and commands, board yellow for what you can act on.
# See ../references/design.md.

CSS = """
:root{
  --foam:#F6F1E8;--foam-2:rgba(246,241,232,.92);--foam-3:rgba(246,241,232,.52);
  --glass:rgba(246,241,232,.06);--glass-line:rgba(246,241,232,.16);
  --sea-0:#1A64B0;--sea-1:#114D96;--sea-2:#0B3574;--sea-3:#07214E;--abyss:#040F28;
  --board:#FBC82A;--reef:#8FE0C4;--foil:#EE7B24;
  --ground:#F6F1E8;--paper:#FFFDF8;--paper-2:#EFE8DA;--ink:#172126;--ink-2:#4A5552;--ink-3:#5F6661;
  --line:#E3DCCF;--line-2:#D3C9B6;--accent:#114D96;--accent-soft:#E3EBF5;
  --ok:#1C7559;--ok-soft:#DDF2E9;--attn:#9C4C0E;--attn-soft:#FBE7D4;--live:#7A5C00;--live-soft:#FDF0C4;
  --bad:#AE3F2D;--bad-soft:#F8E0DA;--idle:#5F6661;--idle-soft:#ECE5D8;
  --shadow:0 1px 0 rgba(23,33,38,.04),0 18px 40px -28px rgba(7,33,78,.35);
  --display:"Cormorant Garamond",Georgia,"Times New Roman",serif;
  --body:"Karla",system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:"Fragment Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
  --ground:#040F28;--paper:#081834;--paper-2:#0C2147;--ink:#F6F1E8;--ink-2:rgba(246,241,232,.74);--ink-3:rgba(246,241,232,.52);
  --line:rgba(246,241,232,.12);--line-2:rgba(246,241,232,.22);--accent:#8FC0F2;--accent-soft:rgba(143,192,242,.12);
  --ok:#8FE0C4;--ok-soft:rgba(143,224,196,.12);--attn:#FFAE6B;--attn-soft:rgba(238,123,36,.16);--live:#FBC82A;--live-soft:rgba(251,200,42,.13);
  --bad:#FF9A8A;--bad-soft:rgba(255,154,138,.12);--idle:rgba(246,241,232,.58);--idle-soft:rgba(246,241,232,.07);
  --shadow:0 18px 40px -28px rgba(0,0,0,.6);}}
:root[data-theme="dark"]{color-scheme:dark;
  --ground:#040F28;--paper:#081834;--paper-2:#0C2147;--ink:#F6F1E8;--ink-2:rgba(246,241,232,.74);--ink-3:rgba(246,241,232,.52);
  --line:rgba(246,241,232,.12);--line-2:rgba(246,241,232,.22);--accent:#8FC0F2;--accent-soft:rgba(143,192,242,.12);
  --ok:#8FE0C4;--ok-soft:rgba(143,224,196,.12);--attn:#FFAE6B;--attn-soft:rgba(238,123,36,.16);--live:#FBC82A;--live-soft:rgba(251,200,42,.13);
  --bad:#FF9A8A;--bad-soft:rgba(255,154,138,.12);--idle:rgba(246,241,232,.58);--idle-soft:rgba(246,241,232,.07);
  --shadow:0 18px 40px -28px rgba(0,0,0,.6);}
*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.6 var(--body);font-feature-settings:"kern" 1,"liga" 1;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:3px}
:focus-visible{outline:2px solid var(--foil);outline-offset:3px;border-radius:4px}
code{font-family:var(--mono);font-size:.86em;background:var(--paper-2);padding:.08em .38em;border-radius:5px}
.wrap{width:min(100% - 32px,1160px);margin-inline:auto}
.eyebrow{font:600 12px/1.2 var(--body);letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:0}

/* top bar */
.top{display:flex;align-items:center;gap:12px;padding-block:16px;flex-wrap:wrap}
.brand{display:inline-flex;align-items:center;gap:10px;font-weight:600;font-size:17px;letter-spacing:.02em;color:var(--ink)}
.brand img{width:30px;height:30px;border-radius:8px;box-shadow:0 4px 12px rgba(17,77,150,.25)}
.crumb{color:var(--ink-3)}
.top .product{color:var(--ink-2);font-weight:500;overflow-wrap:anywhere}
.top .chips{margin-left:auto;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.theme{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;color:var(--ink);background:var(--paper);border:1px solid var(--line-2);border-radius:50%;padding:0;cursor:pointer}
.theme:hover{border-color:var(--accent)}
.theme svg{width:16px;height:16px}
.chip{font:12px/1 var(--mono);color:var(--ink-2);border:1px solid var(--line-2);padding:6px 10px;border-radius:999px;white-space:nowrap}

/* the sea band: dark in both themes, like the site's sections */
.sea{color:var(--foam);background:linear-gradient(180deg,var(--sea-0) 0%,var(--sea-1) 22%,var(--sea-2) 52%,var(--sea-3) 82%,var(--abyss) 100%)}
.sea .eyebrow{color:var(--foam-2)}
.hero{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);gap:clamp(20px,4vw,48px);align-items:end;padding-block:clamp(28px,5vw,52px) 28px}
.hero h1{font:500 clamp(44px,6.4vw,76px)/.98 var(--display);letter-spacing:-.015em;margin:12px 0 0;text-wrap:balance;overflow-wrap:anywhere}
.lead{margin:16px 0 0;font-size:18px;color:var(--foam-2);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.lead em{font:italic 500 1.45em/1 var(--display);color:var(--foam)}
.next{background:var(--glass);border:1px solid var(--glass-line);border-radius:16px;padding:20px;display:flex;flex-direction:column;gap:10px;backdrop-filter:blur(2px)}
.next .title{font:500 26px/1.15 var(--display);color:var(--foam);text-decoration:none;text-wrap:balance}
.next .title:hover{text-decoration:underline}
.next p{margin:0;color:var(--foam-2);font-size:15px}
.term{position:relative;background:rgba(4,15,40,.72);border:1px solid var(--glass-line);border-radius:12px;padding:14px 92px 14px 16px;font:14px/1.5 var(--mono);color:var(--foam);overflow-wrap:anywhere}
.term .prompt{color:var(--board);user-select:none;margin-right:8px}
.copy{position:absolute;top:50%;right:10px;transform:translateY(-50%);font:600 11px/1 var(--body);letter-spacing:.1em;text-transform:uppercase;color:#172126;background:var(--board);border:0;border-radius:8px;padding:9px 11px;cursor:pointer;transition:background-color .2s ease}
.copy.is-done{background:var(--reef)}
.term.light{background:var(--paper-2);border-color:var(--line);color:var(--ink)}
.term.light .prompt{color:var(--attn)}
.hint{font-size:13px;color:var(--foam-2)}

/* stepper */
.steps{list-style:none;margin:0;padding:0 0 30px;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr))}
.steps li{position:relative;border-top:1px solid var(--glass-line)}
.steps a{display:flex;flex-direction:column;gap:3px;padding:18px 16px 4px 0;color:var(--foam);text-decoration:none}
.steps a:hover .nm{text-decoration:underline}
.steps li::before{content:"";position:absolute;top:-5px;left:0;width:9px;height:9px;border-radius:50%;background:var(--abyss);border:1.5px solid var(--foam-3)}
.steps li.done::before{background:var(--reef);border-color:var(--reef)}
.steps li.review::before{background:var(--foil);border-color:var(--foil);box-shadow:0 0 0 4px rgba(238,123,36,.25)}
.steps li.current::before{background:var(--board);border-color:var(--board);box-shadow:0 0 0 4px rgba(251,200,42,.22)}
.steps .n{font:12px var(--mono);color:var(--foam-2)}
.steps .nm{font-weight:600;font-size:15px}
.steps .st{font-size:13px;color:var(--foam-2)}
@media (max-width:760px){.hero{grid-template-columns:1fr}
  .steps{grid-template-columns:1fr;margin-left:5px}
  .steps li{border-top:0;border-left:1px solid var(--glass-line)}
  .steps li::before{top:22px;left:-5px}
  .steps a{padding:14px 0 14px 22px}}

/* body */
.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:28px;align-items:start;padding-block:28px 56px}
.col{display:flex;flex-direction:column;gap:12px;min-width:0}
.side{align-self:stretch}
@media (max-width:980px){.layout{grid-template-columns:1fr}.side{order:-1}.ask{position:static}}
.card{background:var(--paper);border:1px solid var(--line);border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:12px;box-shadow:var(--shadow)}
.card ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:8px}
.card li{display:flex;gap:10px;align-items:baseline;font-size:15px}
.card li::before{content:"";flex:none;width:7px;height:7px;border-radius:50%;background:var(--attn);transform:translateY(-1px)}
.card li a{color:var(--ink)}
.muted{color:var(--ink-3);margin:0;font-size:14px}
.setting{display:flex;flex-direction:column;gap:2px;padding-block:10px;border-top:1px solid var(--line)}
.setting:first-of-type{border-top:0;padding-top:0}
.setting .k{font-size:13px;color:var(--ink-3)}
.setting .v{display:flex;align-items:center;gap:8px;font-weight:600}
.setting .v svg{width:14px;height:14px;flex:none;color:var(--ink-3)}
.setting .d{font-size:13px;color:var(--ink-3)}
.setting .v.unset{font-weight:500;color:var(--attn)}

/* stages */
details.stage{background:var(--paper);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow);scroll-margin-top:16px}
details.stage.review{border-color:var(--attn)}
details.stage>summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto minmax(0,1fr) auto auto;align-items:center;gap:4px 14px;padding:16px 18px}
details.stage>summary::-webkit-details-marker{display:none}
details.stage>summary .n{grid-area:1/1;font:12px var(--mono);color:var(--ink-3)}
details.stage>summary .nm{grid-area:1/2;font:600 25px/1.1 var(--display);letter-spacing:-.005em}
details.stage>summary .pill{grid-area:1/3}
details.stage>summary .chev{grid-area:1/4}
details.stage>summary .sum{grid-area:2/2/3/5;font-size:14px;color:var(--ink-3)}
details.stage[open]>summary{border-bottom:1px solid var(--line)}
details.stage.todo>summary .nm{color:var(--ink-3)}
.chev{flex:none;width:9px;height:9px;border-right:1.5px solid var(--ink-3);border-bottom:1.5px solid var(--ink-3);transform:rotate(45deg) translateY(-3px);transition:transform .2s ease}
details[open]>summary .chev{transform:rotate(225deg) translateY(-2px)}
@media (max-width:560px){details.stage>summary{grid-template-columns:auto minmax(0,1fr) auto}
  details.stage>summary .pill{grid-area:3/2;justify-self:start}
  details.stage>summary .chev{grid-area:1/3}
  details.stage>summary .sum{grid-area:2/2/3/4}}
.stage-body{padding:18px 20px 22px;display:flex;flex-direction:column;gap:20px}
.what{margin:0;color:var(--ink-2);max-width:68ch}
.check{background:var(--attn-soft);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.check .eyebrow{color:var(--attn)}
.check ul{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:4px}
.check p{margin:0;font-weight:600}
.block{display:flex;flex-direction:column;gap:10px;min-width:0}
.block>h3{font:600 12px/1.2 var(--body);letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);margin:0}
.pill{display:inline-flex;align-items:center;gap:6px;font:600 12px/1 var(--body);padding:5px 10px;border-radius:999px;width:fit-content;max-width:100%}
.pill::before{content:"";flex:none;width:6px;height:6px;border-radius:50%;background:currentColor}
.pill.done{color:var(--ok);background:var(--ok-soft)}
.pill.review{color:var(--attn);background:var(--attn-soft)}
.pill.current{color:var(--live);background:var(--live-soft)}
.pill.todo{color:var(--idle);background:var(--idle-soft)}
.pill.ready{color:var(--accent);background:var(--accent-soft)}
.pill.blocked,.pill.gap{color:var(--bad);background:var(--bad-soft)}
.sea .pill.review{color:#FFC08A;background:#353346}
.sea .pill.current{color:var(--board);background:#2E3C48}
.sea .pill.done{color:var(--reef);background:#1A3C5F}

/* tables and documents */
.scroll{overflow-x:auto;max-width:100%}
table{border-collapse:collapse;width:100%;min-width:520px;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;vertical-align:top;padding:9px 12px 9px 0;border-bottom:1px solid var(--line)}
th{font:600 11px/1.3 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3)}
details.doc{border:1px solid var(--line);border-radius:10px;background:var(--ground)}
details.doc>summary{list-style:none;cursor:pointer;padding:10px 14px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
details.doc>summary::-webkit-details-marker{display:none}
details.doc>summary .path{font:13px var(--mono);overflow-wrap:anywhere;flex:1;min-width:0}
details.doc>summary a{font-size:13px}
.md{padding:6px 16px 16px;border-top:1px solid var(--line);overflow-wrap:anywhere}
.md.bare{padding:0;border:0}
.md h3,.md h4,.md h5,.md h6{font:600 20px/1.2 var(--display);margin:18px 0 6px}
.md p{margin:8px 0;max-width:72ch}
.md ul,.md ol{padding-left:20px;margin:8px 0}
.md pre,.out{margin:8px 0;padding:12px 14px;background:var(--paper-2);border-radius:10px;font:13px/1.55 var(--mono);overflow-x:auto}
.md pre code,.out code{background:none;padding:0}
.md blockquote{margin:8px 0;padding:4px 14px;border-left:2px solid var(--line-2);color:var(--ink-2)}
.tag{font:11px var(--mono);padding:2px 6px;border-radius:5px;background:var(--paper-2);color:var(--ink-2);white-space:nowrap}
.tag.must{color:var(--attn);background:var(--attn-soft)}
.ref{font-family:var(--mono);font-size:.9em}
.facts{display:grid;grid-template-columns:fit-content(40%) minmax(0,1fr);gap:8px 20px;margin:0}
.facts dt{color:var(--ink-3)}
.facts dd{margin:0;overflow-wrap:anywhere}

/* backlog */
.toolbar{display:flex;gap:12px 16px;align-items:center;flex-wrap:wrap}
.toolbar strong{font-weight:600}
.seg{display:inline-flex;border:1px solid var(--line-2);border-radius:999px;padding:3px;margin-left:auto}
.seg button{font:600 13px var(--body);border:0;background:none;color:var(--ink-2);padding:6px 14px;border-radius:999px;cursor:pointer}
.seg button[aria-pressed="true"]{background:var(--ink);color:var(--ground)}
.bar{height:5px;border-radius:999px;background:var(--paper-2);overflow:hidden;width:120px;flex:none}
.bar i{display:block;height:100%;background:var(--ok)}
details.group{border-top:1px solid var(--line)}
details.group>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:12px 0;flex-wrap:wrap}
details.group>summary::-webkit-details-marker{display:none}
details.group>summary .gname{font:600 20px/1.2 var(--display);flex:1 1 auto;min-width:8ch}
details.group>summary .count{font:12px var(--mono);color:var(--ink-3)}
.group-body{display:flex;flex-direction:column;gap:6px;padding-bottom:14px}
.group-body>.muted{margin-bottom:4px}
details.story>summary{padding:9px 12px}
details.story .sid{font:13px var(--mono);color:var(--ink-2);flex:0 1 auto;min-width:0}
details.story .stitle{flex:1;min-width:14ch;font-weight:500}
.epic{font:11px/1 var(--mono);padding:4px 7px;border-radius:5px;border:1px solid var(--line-2);color:var(--ink-3)}

/* build modes */
.modes{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}
.mode{border:1px solid var(--line);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px;background:var(--ground)}
.mode.chosen{border-color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}
.mode h4{margin:0;font:600 21px/1.2 var(--display);display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.mode p{margin:0}
.mode .when{color:var(--ink-3);font-size:14px}
details.plain>summary{cursor:pointer;color:var(--accent);font-weight:600;list-style:none;display:inline-flex;align-items:center;gap:8px}
details.plain>summary::-webkit-details-marker{display:none}
details.plain[open]>summary{margin-bottom:12px}
.card.plain>summary{color:var(--ink-3);display:flex;justify-content:space-between}
.gloss{display:flex;flex-direction:column;gap:10px;margin:0}
.gloss dt{font-weight:600}
.gloss dd{margin:0;color:var(--ink-2);font-size:14px}
/* actions and the ask box */
.acts{display:flex;flex-wrap:wrap;gap:8px}
.act{font:600 13px/1 var(--body);cursor:pointer;border-radius:999px;padding:9px 14px;border:1px solid var(--line-2);background:var(--paper);color:var(--ink);transition:border-color .15s ease,transform .15s ease}
.act:hover{border-color:var(--accent);transform:translateY(-1px)}
.act.primary{background:var(--accent);border-color:var(--accent);color:var(--paper)}
.sea .act{background:var(--board);border-color:var(--board);color:#172126}
.check .acts{margin-top:4px}
.ask{position:sticky;top:16px;border-color:var(--line-2)}
.ask textarea{width:100%;min-height:110px;resize:vertical;font:15px/1.5 var(--body);color:var(--ink);background:var(--ground);border:1px solid var(--line-2);border-radius:10px;padding:10px 12px}
.ask textarea:focus{outline:2px solid var(--accent);outline-offset:1px}
.ask .row{display:flex;gap:8px;flex-wrap:wrap}
.ask .status{font-size:13px;color:var(--ink-3);margin:0;min-height:1.2em}
.ask .status.ok{color:var(--ok)}
.ask .status.warn{color:var(--attn)}
.ask.flash{box-shadow:0 0 0 3px var(--live-soft),var(--shadow)}
.card .waitlist .wi{display:flex;flex-direction:column;align-items:flex-start;gap:6px;min-width:0}
.card .waitlist .act{padding:5px 10px;font-size:12px}
.setting ul{list-style:none;padding:0;margin:4px 0 0;display:flex;flex-direction:column;gap:4px}
.setting ul li{font-size:14px;display:block}
.setting ul li::before{display:none}

/* environments */
.envs{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}
.env{border:1px solid var(--line);border-radius:12px;padding:14px 16px;background:var(--ground);display:flex;flex-direction:column;gap:8px;min-width:0}
.env-head{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap}
.env h4{margin:0;font:600 21px/1.2 var(--display);text-transform:capitalize}
.env p{margin:0}
.env .bar{width:100%}
.env ul.todo{margin:0;padding-left:18px;font-size:14px;color:var(--ink-2);display:flex;flex-direction:column;gap:3px}

/* sections outside the stage sequence */
details.stage.extra>summary .n{font:600 13px var(--mono)}
.sev{font:600 11px/1 var(--mono);padding:3px 6px;border-radius:5px;background:var(--idle-soft);color:var(--ink-2)}
.sev.P0,.sev.P1{background:var(--bad-soft);color:var(--bad)}
.sev.P2{background:var(--live-soft);color:var(--live)}
.timeline{list-style:none;margin:0;padding:0;display:flex;flex-direction:column}
.timeline li{display:grid;grid-template-columns:92px minmax(0,1fr);gap:12px;padding:9px 0;border-top:1px solid var(--line);font-size:14px}
.timeline li:first-child{border-top:0}
.timeline time{font:12px/1.6 var(--mono);color:var(--ink-3)}
.timeline .k{color:var(--ink-3)}
footer .credit{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;width:100%;padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:var(--paper);color:var(--ink-2)}
footer .credit .heart{color:var(--foil);font-size:16px}
footer .credit .acts{margin-left:auto}
footer .credit .act{padding:6px 11px;font-size:12px}
footer{padding-block:0 32px;font-size:13px;color:var(--ink-3);display:flex;gap:6px 16px;flex-wrap:wrap;justify-content:space-between}
footer code{background:none;padding:0}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

JS = """
(function(){
  var root=document.documentElement, marker=document.querySelector('[data-lang]'), lang=marker&&marker.getAttribute('data-lang');
  if(lang)root.setAttribute('lang',lang);
  var themeBtn=document.getElementById('theme');
  function effective(){var a=root.getAttribute('data-theme');if(a==='dark'||a==='light')return a;
    return window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'}
  function paintTheme(){if(!themeBtn)return;var dark=effective()==='dark';
    themeBtn.setAttribute('aria-pressed',String(dark));
    var name=themeBtn.getAttribute(dark?'data-light':'data-dark');themeBtn.setAttribute('aria-label',name);themeBtn.title=name;
    themeBtn.querySelector('.moon').style.display=dark?'none':'';themeBtn.querySelector('.sun').style.display=dark?'':'none'}
  try{var saved=localStorage.getItem('keelokit-theme');if(saved==='dark'||saved==='light')root.setAttribute('data-theme',saved)}catch(e){}
  if(themeBtn){themeBtn.addEventListener('click',function(){var next=effective()==='dark'?'light':'dark';
    root.setAttribute('data-theme',next);try{localStorage.setItem('keelokit-theme',next)}catch(e){}paintTheme()});paintTheme()}
  document.querySelectorAll('button[data-copy]').forEach(function(btn){
    btn.addEventListener('click',function(){
      var text=btn.getAttribute('data-copy'), label=btn.textContent;
      function ok(){btn.textContent=btn.getAttribute('data-done');btn.classList.add('is-done');
        setTimeout(function(){btn.textContent=label;btn.classList.remove('is-done')},1600)}
      function fallback(){var el=btn.parentNode.querySelector('.cmdtext');if(!el)return;var r=document.createRange();
        r.selectNodeContents(el);var s=window.getSelection();s.removeAllRanges();s.addRange(r)}
      try{navigator.clipboard.writeText(text).then(ok,fallback)}catch(e){fallback()}
    });
  });
  var views=document.querySelectorAll('[data-view]'), btns=document.querySelectorAll('button[data-show]');
  function show(v){views.forEach(function(el){el.hidden=el.getAttribute('data-view')!==v});
    btns.forEach(function(b){b.setAttribute('aria-pressed',String(b.getAttribute('data-show')===v))});
    try{localStorage.setItem('keelokit-backlog-view',v)}catch(e){}}
  btns.forEach(function(b){b.addEventListener('click',function(){show(b.getAttribute('data-show'))})});
  if(btns.length){var v='wave';try{v=localStorage.getItem('keelokit-backlog-view')||'wave'}catch(e){}show(v==='epic'?'epic':'wave')}
  // A story is drawn once per backlog view (story-wave-X, story-epic-X): #story-X is the copy in the
  // view showing, and a link into the hidden view switches to it (UI-2).
  function target(id){var el=document.getElementById(id);if(el||id.indexOf('story-')!==0)return el;
    var on=document.querySelector('[data-view]:not([hidden])');
    return document.getElementById('story-'+(on?on.getAttribute('data-view'):'wave')+'-'+id.slice(6))}
  function reveal(id){var el=target(id);if(!el)return;
    for(var n=el;n;n=n.parentElement){if(n.tagName==='DETAILS')n.open=true;
      if(n.hidden&&n.hasAttribute('data-view'))show(n.getAttribute('data-view'))}
    el.scrollIntoView({block:'start'})}
  document.addEventListener('click',function(e){var a=e.target.closest('a[href^="#"]');if(!a)return;
    var id=a.getAttribute('href').slice(1);if(target(id)){e.preventDefault();reveal(id)}});
  if(location.hash.length>1)reveal(location.hash.slice(1));
  window.addEventListener('hashchange',function(){if(location.hash.length>1)reveal(location.hash.slice(1))});

  var box=document.getElementById('ask'), ta=document.getElementById('ask-text'), send=document.getElementById('ask-send'),
      copyBtn=document.getElementById('ask-copy'), status=document.getElementById('ask-status'), comments=null, canSend='off';
  if(!box)return;
  function say(key,cls){status.textContent=box.getAttribute('data-'+key)||'';status.className='status'+(cls?' '+cls:'')}
  function refresh(){
    if(!comments){send.hidden=true;say('copy-only');return Promise.resolve()}
    return comments.canSendToClaude().then(function(v){canSend=v},function(){canSend='off'}).then(function(){
      send.hidden=canSend==='off';send.disabled=canSend!=='available';
      if(canSend==='available')say('');else if(canSend==='no_session')say('no-session','warn');
      else if(canSend==='writers_only')say('writers','warn');else say('copy-only');
    });
  }
  document.querySelectorAll('[data-ask]').forEach(function(b){b.addEventListener('click',function(){
    ta.value=b.getAttribute('data-ask');box.scrollIntoView({block:'nearest'});ta.focus();
    ta.setSelectionRange(ta.value.length,ta.value.length);box.classList.add('flash');
    setTimeout(function(){box.classList.remove('flash')},900);refresh();
  })});
  copyBtn.addEventListener('click',function(){var text=ta.value.trim();if(!text)return;
    function ok(){say('copied','ok')}function fallback(){ta.select()}
    try{navigator.clipboard.writeText(text).then(ok,fallback)}catch(e){fallback()}});
  send.addEventListener('click',function(){var text=ta.value.trim();if(!text||!comments)return;send.disabled=true;
    comments.anchorFor(box).then(function(anchor){return comments.sendToClaude({anchor:anchor,text:text})}).then(function(){
      ta.value='';say('sent','ok');send.disabled=false;
    },function(e){var code=e&&e.code;send.disabled=false;
      if(code==='consent_required')say('consent','warn');else if(code==='rate_limited')say('rate','warn');
      else if(code==='claude_unavailable'){say('no-session','warn');refresh()}
      else if(code==='forbidden'||code==='not_granted'){comments=null;refresh()}else say('failed','warn');
    });
  });
  var use=window.claude&&window.claude.use?window.claude.use('comments'):Promise.resolve(null);
  refresh();
  Promise.resolve(use).then(function(c){comments=c;refresh()},function(){comments=null;refresh()});
})();
"""

LOCK = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
        '<rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>')
CHEV = '<span class="chev" aria-hidden="true"></span>'
MOON = ('<svg class="moon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">'
        '<path d="M13.5 9.5A5.5 5.5 0 0 1 6.5 2.5a5.5 5.5 0 1 0 7 7Z"/></svg>')
SUN = ('<svg class="sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true" style="display:none">'
       '<circle cx="8" cy="8" r="3"/><path d="M8 1v1.5M8 13.5V15M1 8h1.5M13.5 8H15M3 3l1 1M12 12l1 1M3 13l1-1M12 4l1-1"/></svg>')


def logo() -> str:
    svg = read(PLUGIN_ROOT / ".claude-plugin/icon.svg")
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode() if svg else ""


def ext_link(href: str | None, links: Links, t: dict) -> str:
    if not href:
        return ""
    label = t["open_github"] if links.github else t["open_file"]
    return f'<a href="{esc(href)}" target="_blank" rel="noopener">{esc(label)}</a>'


def doc_block(rel: str, text: str, links: Links, t: dict) -> str:
    return (f'<details class="doc"><summary><span class="path">{esc(rel)}</span>'
            f'{ext_link(links.href(rel), links, t)}{CHEV}</summary>'
            f'<div class="md">{markdown(text, links, rel)}</div></details>')


def term(cmd: str, t: dict, light: bool = False) -> str:
    return (f'<div class="term{" light" if light else ""}"><span class="prompt">›</span><span class="cmdtext">{esc(cmd)}</span>'
            f'<button type="button" class="copy" data-copy="{esc(cmd)}" data-done="{esc(t["copied"])}">{esc(t["copy"])}</button></div>')


def story_ids(stories: list) -> str:
    """The ids a build-story prompt sends, in backlog order: "AUTH-001 AUTH-002"."""
    return " ".join(x["id"] for x in stories)


def ask(label: str, text: str, primary: bool = False) -> str:
    return f'<button type="button" class="act{" primary" if primary else ""}" data-ask="{esc(text)}">{esc(label)}</button>'


def block(title: str, inner: str, id_: str = "") -> str:
    attr = f' id="{id_}"' if id_ else ""
    return f'<div class="block"{attr}><h3>{title}</h3>{inner}</div>'


def stage_summary(s: dict, stage: dict, t: dict) -> str:
    sid, c = stage["id"], s["counts"]
    if stage["status"] == "todo" and not stage["outputs"]:
        return t["sum_none"]
    if sid == "intake":
        return t["sum_intake"].format(docs=plural(t, "n_docs", len(s["context"])), gaps=plural(t, "n_open_q", len(s["gaps"])),
                                      blocking=plural(t, "n_blocking", sum(g["blocking"] for g in s["gaps"])),
                                      inv=plural(t, "n_inv", len(s["invariants"])))
    if sid == "product" and s["prd"]:
        return t["sum_product"].format(metrics=plural(t, "n_metrics", c["metrics"]), inn=c["in"], out=c["out"])
    if sid == "stack":
        apps = s["answers"].get("apps", "")
        apps = apps or md_field(s["stack_doc"], "apps")
        apps = re.sub(r"[\[\]\"'*]", "", apps).strip().rstrip(".")
        return t["sum_stack"].format(apps=apps) if apps else t["sum_none"]
    if sid == "skeleton" and s["first_commit"]:
        return t["sum_skeleton"].format(commit=s["first_commit"].split()[0])
    if sid == "adopt":
        return plural(t, "sum_adopt", c["exceptions"])
    if sid == "backlog" and s["stories"]:
        return t["sum_backlog"].format(total=plural(t, "n_stories", len(s["stories"])),
                                       waves=plural(t, "n_waves", len({x["wave"] for x in s["stories"]})),
                                       epics=plural(t, "n_epics", len({x["epic"] for x in s["stories"]})))
    return t["sum_none"]


def stage_body(s: dict, stage: dict, links: Links, t: dict) -> str:
    sid, root, parts = stage["id"], s["root"], []
    if sid == "intake" and s["context"]:
        if s["gaps"]:
            rows = "".join(
                f'<tr><td><span class="tag">{esc(g["id"])}</span></td><td>{inline(g["missing"])}</td>'
                f'<td>{esc(g["owner"])}</td><td>{inline(g["question"])}</td>'
                f'<td>{esc(t["yes"] if g["blocking"] else t["no"])}</td></tr>' for g in s["gaps"])
            head = "".join(f"<th>{esc(c)}</th>" for c in t["gap_cols"])
            parts.append(block(esc(t["gaps"]), f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>'))
        else:
            parts.append(block(esc(t["gaps"]), f'<p class="muted">{esc(t["gaps_none"])}</p>'))
        if s["invariants"]:
            items = "".join(f'<li><span class="tag">{esc(i["id"])}</span> {inline(i["text"])}</li>' for i in s["invariants"])
            parts.append(block(esc(t["invariants"]), f'<div class="md bare"><ul>{items}</ul></div>'))
        parts.append(block(esc(t["docs"]), "".join(doc_block(f"docs/context/{f}", x, links, t) for f, x in s["context"].items())))
    elif sid == "product" and s["prd"]:
        for key in ("metrics", "scope"):
            if body := md_section(s["prd"], key):
                parts.append(block(esc(t[key]), f'<div class="md bare">{markdown(body, links, "docs/prd.md")}</div>'))
        parts.append(block(esc(t["docs"]), doc_block("docs/prd.md", s["prd"], links, t)))
    elif sid == "stack" and stage["status"] != "todo":
        if s["stack_doc"]:
            parts.append(block(esc(t["apps"]), f'<div class="md bare">{markdown(s["stack_doc"], links, "docs/stack.md")}</div>'))
        elif s["answers"].get("apps"):
            parts.append(block(esc(t["apps"]), f'<p><code>{esc(s["answers"]["apps"])}</code></p>'))
        if s["decisions"]:
            parts.append(block(esc(t["decisions"]), "".join(doc_block(d, read(root / d), links, t) for d in s["decisions"])))
        if house := read(PLUGIN_ROOT / "template/.keelokit/harness/stack.md"):
            parts.append(block(esc(t["house_stack"]),
                               f'<details class="doc"><summary><span class="path">Keelokit · stack.md</span>{CHEV}</summary>'
                               f'<div class="md">{markdown(house)}</div></details>'))
    elif sid == "skeleton" and (s["answers"] or s["has_commits"]):
        facts = []
        if s["answers"]:
            facts.append((t["generated"], f'<code>{esc(s["answers"].get("_commit", ""))}</code>'))
            if apps := s["answers"].get("apps"):
                facts.append((t["apps"], f"<code>{esc(apps)}</code>"))
        if s["first_commit"]:
            facts.append((t["first_commit"], f"<code>{esc(s['first_commit'])}</code>"))
        if s["github"]:
            repo = s["github"].removesuffix("/blob/main/")
            facts.append((t["remote"], f'<a href="{esc(repo)}" target="_blank" rel="noopener">{esc(repo.removeprefix("https://"))}</a>'))
        parts.append(block(esc(t["skeleton_facts"]), '<dl class="facts">' + "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in facts) + "</dl>"))
    elif sid == "adopt" and (stage["outputs"] or s["survey"]):
        parts.append(found_block(s, links, t))
        if stage["outputs"]:
            parts.append(block(esc(t["docs"]), "".join(doc_block(rel, read(root / rel), links, t) for rel in stage["outputs"])))
    elif sid == "backlog" and s["stories"]:
        parts.append(backlog_block(s, links, t))
    return "".join(parts) or f'<p class="muted">{esc(t["not_yet"])}</p>'


def story_row(st: dict, links: Links, t: dict, view: str = "") -> str:
    """One story's card. The page draws a story once per place it shows it (the backlog by wave,
    by epic, a bug bash's history), so only the backlog's copies get an id, one per view:
    story-wave-X and story-epic-X. A link to #story-X lands on the copy in the view showing (UI-2)."""
    status = st["status"]
    label = {
        "done": t["story_done"], "ready": t["story_ready"],
        "blocked": t["story_blocked"].format(deps=", ".join(st.get("waits", []))),
        "gap": t["story_gap"].format(gaps=", ".join(st["gaps"])),
    }[status]
    link = ext_link(links.href(st["path"]), links, t)
    build = f'<div class="acts">{ask(t["act_build_one"], "/keelokit:build-story " + st["id"], True)}</div>' if status == "ready" else ""
    deps = (f'<p class="muted">{esc(t["depends"])}: ' + ", ".join(f"<code>{esc(d)}</code>" for d in st["depends_on"]) + "</p>") \
        if st["depends_on"] else ""
    anchor = f' id="story-{view}-{esc(st["id"])}"' if view else ""
    return (f'<details class="doc story"{anchor}><summary><span class="sid">{esc(st["id"])}</span>'
            f'<span class="stitle">{esc(st["title"])}</span><span class="epic">{esc(st["epic"])}</span>'
            f'<span class="pill {status}">{esc(label)}</span>{CHEV}</summary>'
            f'<div class="md">{f"<p>{link}</p>" if link else ""}{deps}{build}'
            f'{markdown(st["body"], links, st["path"])}</div></details>')


def group(title: str, items: list[dict], links: Links, t: dict, open_: bool, note: str = "", action: str = "",
          view: str = "") -> str:
    done = sum(1 for x in items if x["status"] == "done")
    pct = round(100 * done / len(items)) if items else 0
    return (f'<details class="group"{" open" if open_ else ""}><summary><span class="gname">{title}</span>'
            f'<span class="count">{done}/{len(items)}</span><span class="bar"><i style="width:{pct}%"></i></span>{CHEV}</summary>'
            f'<div class="group-body">{f"<p class=muted>{esc(note)}</p>" if note else ""}{action}'
            + "".join(story_row(x, links, t, view) for x in items) + "</div></details>")


def backlog_block(s: dict, links: Links, t: dict) -> str:
    stories = s["stories"]
    done = sum(1 for x in stories if x["status"] == "done")
    # Grouped in one pass, not one scan of the backlog per wave or epic (NFR-1).
    in_wave: dict = {}
    in_epic: dict = {}
    for x in stories:
        in_wave.setdefault(x["wave"], []).append(x)
        in_epic.setdefault(x["epic"], []).append(x)
    waves = sorted(in_wave)
    live = next((w for w in waves if any(x["status"] != "done" for x in in_wave[w])), None)
    def wave_action(w):
        # The button names the wave's ready stories: a count means "the first ready story and more
        # of its wave" to build-story, which is another wave while an earlier one has ready work (UX-2).
        ready = [x for x in in_wave[w] if x["status"] == "ready"]
        return f'<div class="acts">{ask(t["act_build_wave"].format(w=w), "/keelokit:build-story " + story_ids(ready))}</div>' \
            if len(ready) > 1 else ""
    by_wave = "".join(group(esc(t["wave"].format(n=w)), in_wave[w], links, t,
                            w == live, t["wave_note"], wave_action(w), "wave") for w in waves)
    first_epic = next((x["epic"] for x in stories if x["status"] != "done"), None)
    by_epic = "".join(
        group(f'<code>{esc(e)}</code> {inline(goal) if goal else ""}', in_epic[e], links, t, e == first_epic, view="epic")
        for e, goal in s["epics"].items() if e in in_epic)
    epics_doc = doc_block("backlog/epics.md", read(s["root"] / "backlog/epics.md"), links, t) \
        if (s["root"] / "backlog/epics.md").exists() else ""
    pct = round(100 * done / len(stories))
    return (f'<div class="toolbar"><strong>{esc(plural(t, "backlog_total", len(stories), done=done))}</strong>'
            f'<span class="bar"><i style="width:{pct}%"></i></span>'
            f'<span class="seg" role="group"><button type="button" data-show="wave" aria-pressed="true">{esc(t["by_wave"])}</button>'
            f'<button type="button" data-show="epic" aria-pressed="false">{esc(t["by_epic"])}</button></span></div>'
            f'<div data-view="wave">{by_wave}</div><div data-view="epic" hidden>{by_epic}</div>{epics_doc}')


def modes_block(s: dict, t: dict) -> str:
    ready = [x for x in s["stories"] if x["status"] == "ready"]
    same = [x for x in ready if x["wave"] == ready[0]["wave"]] if ready else []
    n = int(s["run"].get("parallel") or max(len(same), 2))
    build = s["run"].get("build")
    cards = []
    for key, cmd in (("serial", f"/keelokit:build-story {ready[0]['id']}" if ready else "/keelokit:build-story"),
                     ("parallel", f"/keelokit:build-story {n}")):
        chosen = f'<span class="pill done">{esc(t["chosen"])}</span>' if build == key else ""
        cards.append(f'<div class="mode{" chosen" if build == key else ""}"><h4>{esc(t[key])}{chosen}</h4>'
                     f'<p>{esc(t[key + "_body"])}</p><p class="when">{esc(t[key + "_when"])}</p>'
                     f'{term(cmd, t, light=True) if not build or build == key else ""}</div>')
    inner = f'<p class="what">{esc(t["modes_intro"])}</p><div class="modes">{"".join(cards)}</div>'
    if build:
        inner = f'<details class="plain"><summary>{esc(t["what_means"])}{CHEV}</summary>{inner}</details>'
    return block(esc(t["modes"]), inner)


def decisions_card(s: dict, links: Links, t: dict) -> str:
    run, root = s["run"], s["root"]
    greenfield = s["layout"] == "project"
    rows = [(t["type"], t["greenfield"] if greenfield else t["brownfield"],
             t["greenfield_d"] if greenfield else t["brownfield_d"], True)]
    prof = s["profile"]
    if prof and prof["kind"] not in ("", "unknown"):
        kinds, traits = t["kinds"], t["traits"]
        label = kinds.get(prof["kind"], prof["kind"])
        desc = ", ".join(traits.get(x, x) for x in prof["traits"]) or t["traits_none"]
        rows.append((t["profile_k"], label, desc, False))
    mode = run.get("mode")
    rows.append((t["run_mode"], t["run_auto"] if mode == "auto" else t["run_step"] if mode else "",
                 t["run_auto_d"] if mode == "auto" else t["run_step_d"] if mode else "", True))
    build = run.get("build")
    rows.append((t["build_mode"], t["build_parallel"].format(n=run.get("parallel", 2)) if build == "parallel"
                 else t["build_serial"] if build else "", "", True))
    apps = s["answers"].get("apps", "")
    apps = apps or md_field(s["stack_doc"], "apps")
    apps = re.sub(r"[\[\]\"'*]", "", apps).strip().rstrip(".")
    stack = s["survey"].get("stack") or s["survey"].get("detected", {}).get("stack")
    if not greenfield and stack:
        rows.append((t["found_stack"], ", ".join(stack) if isinstance(stack, list) else str(stack), "", False))
    elif apps:
        rows.append((t["apps_k"], apps, "", False))
    if s["harness"]:
        rows.append((t["harness_k"], t["harness_behind"].format(have=s["harness"], new=s["plugin_version"]) if behind(s)
                     else t["harness_ok"].format(have=s["harness"]), "", False))
    out = []
    for k, v, d, locked in rows:
        shown = f'<span class="v">{LOCK if locked else ""}{esc(v)}</span>' if v \
            else f'<span class="v unset">{esc(t["undecided"])}</span>'
        out.append(f'<div class="setting"><span class="k">{esc(k)}</span>{shown}'
                   + (f'<span class="d">{esc(d)}</span>' if d else "") + "</div>")
    if greenfield or s["adrs"]:
        # Only a new project has a Stack stage to open; an adopted repo's ADR opens as its file (UX-1).
        def adr_link(a):
            href = "#stage-stack" if greenfield else links.href(a["path"])
            extra = "" if greenfield else ' target="_blank" rel="noopener"'
            return f'<a href="{esc(href)}"{extra}>{esc(a["title"])}</a>' if href else esc(a["title"])
        adrs = "".join(f'<li>{adr_link(a)}'
                       + (f' <span class="muted">· {esc(a["status"])}</span>' if a["status"] else "") + "</li>"
                       for a in s["adrs"])
        out.append(f'<div class="setting"><span class="k">{esc(t["adrs_k"])}</span>'
                   + (f"<ul>{adrs}</ul>" if adrs else f'<span class="d">{esc(t["no_adrs"])}</span>') + "</div>")
    when = f'<p class="muted">{esc(t["decided_on"].format(date=run["decided"]))}</p>' if run.get("decided") else ""
    return (f'<section class="card" id="decisions"><p class="eyebrow">{esc(t["decisions_h"])}</p>'
            f'{"".join(out)}{when}<p class="muted">{esc(t["locked_note"])}</p></section>')


def extra_section(sid: str, mark: str, name: str, pill: str, summary: str, body: str, open_: bool) -> str:
    return (f'<details class="stage extra" id="{sid}"{" open" if open_ else ""}><summary>'
            f'<span class="n">{mark}</span><span class="nm">{esc(name)}</span>{pill}{CHEV}'
            f'<span class="sum">{esc(summary)}</span></summary><div class="stage-body">{body}</div></details>')


def findings_section(runs: list[dict], sid: str, prefix: str, title: str, what: str, none: str, run_title: str,
                     action: tuple[str, str], s: dict, links: Links, t: dict, decide: str = "act_decide_t") -> str:
    def fixed(f): return f["status"].lower().startswith(("fixed", "corregid"))
    def pending(f): return f["status"].lower().startswith(("pending", "pendiente"))
    found = sum(len(b["findings"]) for b in runs)
    summary = t["bb_sum"].format(n=len(runs), found=found, fixed=sum(fixed(f) for b in runs for f in b["findings"]),
                                 stories=sum(len(b["stories"]) for b in runs)) if runs else none
    body = [f'<p class="what">{esc(what)}</p>', f'<div class="acts">{ask(action[0], action[1], True)}</div>']
    open_any = False
    for i, b in enumerate(runs):
        fs = b["findings"]
        n_pending = sum(pending(f) for f in fs)
        counts = t["bb_counts"].format(found=len(fs), fixed=sum(fixed(f) for f in fs), pending=n_pending,
                                       open=sum(not fixed(f) and not pending(f) for f in fs))
        rows = "".join(
            f'<tr><td><span class="tag">{esc(f["id"])}</span></td><td><span class="sev {esc(f["severity"])}">{esc(f["severity"])}</span></td>'
            f'<td>{inline(f["title"])}</td><td>{inline(f["status"])}</td><td>{inline(f["check"])}</td></tr>' for f in fs)
        head = "".join(f"<th>{esc(c)}</th>" for c in t["bb_cols"])
        inner = [f'<p class="muted">{esc(counts)}{" · " + esc(b["sha"][:9]) if b["sha"] else ""}</p>']
        if rows:
            inner.append(f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>')
        if b["pending"]:
            inner.append(block(esc(t["bb_pending"]), f'<div class="md bare">{markdown(b["pending"], links, b["path"])}</div>'
                               f'<div class="acts">{ask(t["act_decide"], t[decide].format(date=b["date"]), True)}</div>'))
        if b["stories"]:
            made = "".join(story_row(s["by_id"][x], links, t) for x in b["stories"] if x in s["by_id"])
            inner.append(block(esc(t["bb_stories"]), made))
        inner.append(doc_block(b["path"], b["text"], links, t))
        is_open = n_pending > 0 or (i == 0 and not open_any)
        open_any = open_any or is_open
        body.append(f'<details class="group" id="{prefix}-{esc(b["date"])}"{" open" if is_open else ""}><summary>'
                    f'<span class="gname">{esc(run_title.format(date=b["date"]))}</span>'
                    f'<span class="count">{len(fs)}</span>{CHEV}</summary><div class="group-body">{"".join(inner)}</div></details>')
    waiting = any(pending(f) for b in runs for f in b["findings"])
    pill = f'<span class="pill review">{esc(t["st_review"])}</span>' if waiting else ""
    return extra_section(sid, prefix.upper()[:3], title, pill, summary, "".join(body), waiting)


def bugbash_section(s: dict, links: Links, t: dict) -> str:
    return findings_section(s["bugbashes"], "bugbash", "bb", t["bb"], t["bb_what"], t["bb_none"], t["bb_run"],
                            (t["act_bugbash"], "/keelokit:check-bugbash"), s, links, t)


def security_section(s: dict, links: Links, t: dict) -> str:
    return findings_section(s["security"], "security", "sec", t["sec_h"], t["sec_what"], t["sec_none"], t["sec_run"],
                            (t["act_security"], "/keelokit:check-security"), s, links, t, "act_decide_sec_t")


def environments_section(s: dict, t: dict) -> str:
    envs = s["environments"]
    def ready(e): return bool(e["steps"]) and all(x["done"] for x in e["steps"])
    cards = []
    for e in envs:
        done, total = sum(x["done"] for x in e["steps"]), len(e["steps"])
        pct = round(100 * done / total) if total else 0
        url = e["url"] if re.match(r"^[\w.-]+\.[a-z]{2,}(/.*)?$|^https?://", e["url"] or "") else ""
        href = url if url.startswith("http") else f"https://{url}" if url else ""
        pending = [x for x in e["steps"] if not x["done"]][:4]
        items = "".join(f"<li>{inline(x['text'])}</li>" for x in pending)
        state = "done" if ready(e) else ("current" if done else "todo")
        cards.append(
            f'<div class="env"><div class="env-head"><h4>{esc(e["name"])}</h4>'
            f'<span class="pill {state}">{esc(plural(t, "env_steps", total, done=done) if total else t["env_nosteps"])}</span></div>'
            + (f'<p class="muted">{inline(e["purpose"])}</p>' if e["purpose"] else "")
            + (f'<p><a href="{esc(href)}" target="_blank" rel="noopener">{esc(url)}</a></p>' if href else "")
            + (f'<span class="bar"><i style="width:{pct}%"></i></span>' if total else "")
            + (f'<ul class="todo">{items}</ul>' if items else "") + "</div>")
    body = f'<p class="what">{esc(t["env_what"])}</p>'
    body += f'<div class="envs">{"".join(cards)}</div>' if cards else ""
    if not s["has_deploy"]:
        body += f'<p class="muted">{inline(t["env_none"])}</p>'
    body += f'<div class="acts">{ask(t["act_setup"], "/keelokit:ship-setup", True)}{ask(t["act_release"], "/keelokit:ship-release")}</div>'
    n_ready = sum(ready(e) for e in envs)
    summary = plural(t, "env_sum", len(envs), ready=n_ready) if envs else t["sum_none"]
    return extra_section("environments", "ENV", t["env_h"], "", summary, body, False)


def found_block(s: dict, links: Links, t: dict) -> str:
    sv, parts = s["survey"], []
    rows = []
    for key, label in (("stack", t["found_stack"]), ("tests", t["found_tests"]), ("ci", t["found_ci"]), ("hosting", t["found_hosting"])):
        value = sv.get(key) or sv.get("detected", {}).get(key)
        if value:
            chips = "".join(f'<span class="epic">{esc(v)}</span> ' for v in (value if isinstance(value, list) else [value]))
            rows.append(f"<dt>{esc(label)}</dt><dd>{chips}</dd>")
    if rows:
        parts.append(block(esc(t["found_h"]), f'<dl class="facts">{"".join(rows)}</dl>'))
    m = s["mapping"]
    if m["house"]:
        exc = m["exceptions"]
        table = ""
        if exc:
            head = "".join(f"<th>{esc(c)}</th>" for c in t["exc_cols"])
            body = "".join(f'<tr><td><span class="tag">{esc(e.get("rule", ""))}</span></td><td>{inline(str(e.get("reason", "")))}</td>'
                           f'<td>{esc(str(e.get("approver", "")))}</td><td>{esc(str(e.get("expires", "")))}</td></tr>' for e in exc)
            table = f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
        parts.append(block(esc(t["rules_h"]), f'<p>{esc(t["rules_counts"].format(house=plural(t, "n_rules", m["house"]), mapped=plural(t, "n_mapped", m["mapped"]), exc=plural(t, "n_dated_exc", len(exc))))}</p>{table}'))
    return "".join(parts)


def history_section(s: dict, t: dict, stage_names: dict) -> str:
    events = s["history"][:60]
    if not events:
        return ""
    items = []
    for e in events:
        if e["kind"] == "story":
            what = f'<span class="k">{esc(t["h_story"])}</span> <code>{esc(e["id"])}</code> {esc(e["title"])}'
        elif e["kind"] == "bugbash":
            what = f'<a href="#bb-{esc(e["id"])}">{esc(t["h_bugbash"])}</a>'
        elif e["kind"] == "security":
            what = f'<a href="#sec-{esc(e["id"])}">{esc(t["h_security"])}</a>'
        else:
            what = f'<span class="k">{esc(t["h_gate_auto"] if e["title"] == "auto" else t["h_gate"])}</span> {esc(stage_names.get(e["id"], e["id"]))}'
        items.append(f'<li><time>{esc(e["date"])}</time><span>{what}</span></li>')
    summary = t["history_sum"].format(n=len(s["history"]), date=events[0]["date"])
    return extra_section("history", "↺", t["history"], "", summary, f'<ul class="timeline">{"".join(items)}</ul>', False)


def credit_block(s: dict, t: dict) -> str:
    level = s["credit"] if s["credit"] in ("visible", "quiet", "off") else "visible"
    names, what = t["credit_names"], t["credit_what"]
    others = "".join(ask(t["credit_to"].format(level=names[x]), t["credit_ask"].format(level=names[x], what=what[x]))
                     for x in ("visible", "quiet", "off") if x != level)
    thanks = f'<span class="muted">{esc(t["credit_thanks"])}</span>' if level != "off" else ""
    return (f'<div class="credit" id="credit"><span class="heart" aria-hidden="true">♥</span>'
            f'<span><strong>{esc(t["credit_k"])}</strong>: {esc(names[level])} · {esc(what[level])}</span>'
            f'{thanks}<span class="acts">{others}</span></div>')


def render(s: dict, lang: str, standalone: bool, out_dir: Path, version: str) -> str:
    t, stage_copy = T[lang], STAGES[lang]
    names = {k: v[0] for k, v in stage_copy.items()}
    links = Links(s["github"], standalone, out_dir, s["root"])
    nxt, waiting = next_step(s, lang), waiting_on_user(s, lang)
    current = next((x for x in s["stages"] if x["status"] in ("review", "current")), None)
    building = current is None and bool(s["stories"])

    def label(st):
        return t["st_auto"] if st["auto"] else t["st_" + st["status"]]

    steps = []
    for n, st in enumerate(s["stages"], 1):
        steps.append(f'<li class="{st["status"]}"><a href="#stage-{st["id"]}"><span class="n">{n:02d}</span>'
                     f'<span class="nm">{esc(names[st["id"]])}</span><span class="st">{esc(label(st))}</span></a></li>')
    if s["stories"]:
        state = "current" if building else "todo"
        steps.append(f'<li class="{state}"><a href="#stage-build"><span class="n">{len(s["stages"]) + 1:02d}</span>'
                     f'<span class="nm">{esc(t["build_stage"])}</span><span class="st">{esc(t["st_" + state])}</span></a></li>')

    sections = []
    for n, st in enumerate(s["stages"], 1):
        name, what, checks = stage_copy[st["id"]]
        check = ""
        if st["status"] == "review":
            items = "".join(f"<li>{esc(c)}</li>" for c in checks)
            check = (f'<div class="check"><p class="eyebrow">{esc(t["review"])}</p><ul>{items}</ul>'
                     f'<p>{esc(t["how_approve"])}</p><div class="acts">'
                     f'{ask(t["act_approve"], t["act_approve_t"].format(stage=name), True)}'
                     f'{ask(t["act_change"], t["act_change_t"].format(stage=name))}</div></div>')
        elif st["status"] == "current":
            flow = "/keelokit:project-adopt" if s["layout"] == "harness" else "/keelokit:project-new"
            check = f'<div class="acts">{ask(t["next_continue"].format(stage=name), flow, True)}</div>'
        date = ""
        if st["date"]:
            date = f' · {esc((t["auto_on"] if st["auto"] else t["approved_on"]).format(date=st["date"]))}'
        sections.append(
            f'<details class="stage {st["status"]}" id="stage-{st["id"]}"{" open" if st is current else ""}><summary>'
            f'<span class="n">{n:02d}</span><span class="nm">{esc(name)}</span>'
            f'<span class="pill {st["status"]}">{esc(label(st))}</span>{CHEV}'
            f'<span class="sum">{esc(stage_summary(s, st, t))}{date}</span></summary>'
            f'<div class="stage-body"><p class="what">{esc(what)}</p>{check}{stage_body(s, st, links, t)}</div></details>')
    # The doctor speaks English only: its output is a quoted log, marked as such (I18N-1). It lands
    # at id="health" whether or not there is a backlog yet: the next step and the waiting list
    # link there whenever it reports errors (UX-1).
    log = (f'<p class="what">{esc(t["health_log"])}</p>'
           f'<pre class="out" lang="en"><code>{esc(chr(10).join(s["doctor"]))}</code></pre>') if s["doctor"] else ""
    if s["stories"]:
        n = len(s["stages"]) + 1
        state = "current" if building else "todo"
        done = sum(1 for x in s["stories"] if x["status"] == "done")
        ready = [x for x in s["stories"] if x["status"] == "ready"]
        acts = []
        if ready:
            acts.append(ask(t["act_build"].format(sid=ready[0]["id"]), f"/keelokit:build-story {ready[0]['id']}", True))
        acts += [ask(t["act_bugbash"], "/keelokit:check-bugbash"), ask(t["act_security"], "/keelokit:check-security"),
                 ask(t["act_release"], "/keelokit:ship-release"), ask(t["act_feature"], t["act_feature_t"]),
                 ask(t["act_setup"], "/keelokit:ship-setup"), ask(t["act_doctor"], "/keelokit:check-health"),
                 ask(t["act_refresh"], "/keelokit:project-dashboard")]
        actions = block(esc(t["actions"]), f'<div class="acts">{"".join(acts)}</div>')
        health = block(esc(t["health"]), log, "health") if log else ""
        sections.append(
            f'<details class="stage {state}" id="stage-build"{" open" if building else ""}><summary>'
            f'<span class="n">{n:02d}</span><span class="nm">{esc(t["build_stage"])}</span>'
            f'<span class="pill {state}">{esc(t["st_" + state])}</span>{CHEV}'
            f'<span class="sum">{esc(plural(t, "sum_build", len(s["stories"]), done=done))}</span></summary>'
            f'<div class="stage-body"><p class="what">{esc(t["build_what"])}</p>{actions}{modes_block(s, t)}{health}</div></details>')
    elif log:
        pill = f'<span class="pill review">{esc(t["st_review"])}</span>' if s["errors"] else ""
        summary = plural(t, "wait_errors", s["errors"]) if s["errors"] else t["health_ok"]
        acts = f'<div class="acts">{ask(t["act_doctor"], "/keelokit:check-health", True)}</div>'
        sections.append(extra_section("health", "DOC", t["health"], pill, summary, acts + log, bool(s["errors"])))
    later = s["stories"] or any(x["id"] in ("skeleton", "adopt") and x["status"] == "done" for x in s["stages"])
    hosted = s["profile"] is None or "hosted" in s["profile"]["traits"]
    if hosted and (later or s["environments"] or s["has_deploy"]):
        sections.append(environments_section(s, t))
    if s["stories"] or s["bugbashes"]:
        sections.append(bugbash_section(s, links, t))
    if later or s["security"]:
        sections.append(security_section(s, links, t))
    sections.append(history_section(s, t, names))

    where = names[current["id"]] if current else (t["build_stage"] if building else t["all_gates"])
    where_pill = f'<span class="pill {current["status"]}">{esc(label(current))}</span>' if current else ""
    wait_html = ('<ul class="waitlist">' + "".join(
        f'<li><div class="wi"><a href="#{esc(w["anchor"])}">{inline(w["text"])}</a>'
        + (ask(w["act"], w["ask"]) if w.get("ask") else "") + "</div></li>"
        for w in waiting) + "</ul>") if waiting else f'<p class="muted">{esc(t["nothing_waiting"])}</p>'
    cmd = ""
    if nxt["command"]:
        cmd = term(nxt["command"], t) + f'<div class="acts">{ask(t["ask_h"], nxt["command"])}</div>'
    elif current and current["status"] == "review":
        cmd = f'<div class="acts">{ask(t["act_approve"], t["act_approve_t"].format(stage=names[current["id"]]))}</div>'
    gloss = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>" for k, v in GLOSSARY[lang])
    mode = s["run"].get("mode")
    chips = f'<span class="chip">{esc(t["greenfield"] if s["layout"] == "project" else t["brownfield"])}</span>'
    if mode:
        chips += f'<span class="chip">{esc(t["run_auto"] if mode == "auto" else t["run_step"])}</span>'
    theme = (f'<button type="button" class="theme" id="theme" aria-pressed="false" data-dark="{esc(t["theme_dark"])}" '
             f'data-light="{esc(t["theme_light"])}" aria-label="{esc(t["theme_dark"])}" title="{esc(t["theme_dark"])}">{MOON}{SUN}</button>')
    when = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    img = logo()

    o = OPS_T[lang]
    page = f"""<title>{esc(o["report_title"].format(name=s["name"]))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500&family=Fragment+Mono&family=Karla:wght@400;500;600&display=swap">
<style>{CSS}
/* the report is read-only: nothing on it sends or prepares requests */
button[data-ask]{{display:none}}.acts:not(:has(:not([data-ask]))){{display:none}}</style>
<div hidden data-lang="{lang}"></div>
<header class="wrap top"><span class="brand">{f'<img src="{img}" alt="">' if img else ""}Keelokit</span><span class="crumb">/</span><span class="product">{esc(s["name"])}</span><span class="chips">{chips}<span class="chip">v{esc(version)}</span>{theme}</span></header>
<div class="sea"><div class="wrap">
<section class="hero" aria-labelledby="where">
<div><p class="eyebrow">{esc(o["report_eyebrow"])}</p><h1 id="where">{esc(s["name"])}</h1>
<p class="lead">{esc(t["current_stage"])}: <em>{esc(where)}</em>{where_pill}</p></div>
<div class="next"><p class="eyebrow">{esc(t["next"])}</p><a class="title" href="#{esc(nxt["anchor"])}">{esc(nxt["title"])}</a><p>{esc(nxt["detail"])}</p>{cmd}</div>
</section>
<nav aria-label="{esc(t["stages"])}"><ol class="steps">{"".join(steps)}</ol></nav>
</div></div>
<main class="wrap layout">
<div class="col">{"".join(sections)}</div>
<aside class="col side">
<section class="card"><p class="eyebrow">{esc(t["waiting"])}</p>{wait_html}</section>
{decisions_card(s, links, t)}
<details class="card plain"><summary class="eyebrow">{esc(t["glossary"])}{CHEV}</summary><dl class="gloss">{gloss}</dl></details>
</aside>
</main>
<footer class="wrap">{credit_block(s, t)}<span>{esc(o["report_footer"].format(when=when, version=version))}</span></footer>
<script>{JS}</script>
"""
    if standalone:
        return (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>\n'
                f"<body>{page}</body></html>\n")
    return page


# ---------------------------------------------------------------------------------------------
# The operational dashboard: one short page for day-to-day work — where the project is, the next
# step and its command, what waits for you, the waves with their stories, health and environments.
# The full page above is the report (`--report`), to read end to end, share or export.

OPS_T = {
    "es": {
        "updated": "Actualizado {when}", "refresh": "Copiar el pedido para actualizar el tablero",
        "stage_of": "Etapa {n} de {total} · {stage}", "all_done": "Todas las etapas aprobadas",
        "serial": "Una historia a la vez", "parallel": "Hasta {n} historias en paralelo",
        "copy": "Copiar", "copied": "Copiado", "copied_ask": "Copiado. Completalo en el chat o abajo.",
        "copy_failed": "No se pudo copiar. El texto es: ", "copy_ask": "Copiar pedido",
        "wait_n": "Te esperan", "nothing": "Nada te espera ahora.",
        "k_decision": "Decisión", "k_gate": "Aprobación", "k_gap": "Pregunta abierta", "k_health": "Harness",
        "k_maint": "Mantenimiento", "k_env": "Entorno", "k_setup": "Configuración",
        "bb_of": "bug bash del {date}", "sec_of": "revisión de seguridad del {date}", "deploy_guide": "guía de despliegue",
        "decide_bb": "Sobre {id} del bug bash del {date}: ", "decide_sec": "Sobre {id} de la revisión de seguridad del {date}: ",
        "env_missing": ("Falta {n} paso para {env}: {steps}.", "Faltan {n} pasos para {env}: {steps}."),
        "waves": "Olas de desarrollo", "of_stories": "{done} de {total} historias", "backlog": "Backlog completo",
        "wave": "Ola {n}", "wave_done": "terminada", "no_wave": "Sin ola",
        "s_done": "Hecha", "s_ready": "Lista · copiar", "s_waits": "Espera a {ids}", "s_gap": "Espera respuesta a {gaps}",
        "from_bb": "del bug bash", "from_sec": "de seguridad", "from_feature": "funcionalidad nueva",
        "review": "Para revisar", "review_docs": "Documentos", "approve": "Aprobar", "change": "Pedir cambios",
        "health": "Salud y entornos", "doctor_ok": "Harness sin errores",
        "doctor_err": ("{n} error del harness", "{n} errores del harness"),
        "bb_line": "{fixed} de {total} corregidos", "to_backlog": ("{n} pasó al backlog", "{n} pasaron al backlog"),
        "decisions_n": ("{n} decisión", "{n} decisiones"), "env_ready": "{env} listo", "env_prep": "{env} en preparación",
        "steps": "{done}/{total} pasos", "docs": "Documentos del proyecto",
        "d_context": "Contexto", "d_prd": "PRD", "d_stack": "Stack", "d_backlog": "Backlog", "d_decisions": "Decisiones ({n})",
        "report": "Generar el reporte completo", "report_ask": "/keelokit:project-report",
        "ask_h": "Pedile a Claude", "ask_ph": "Un botón de arriba lo completa, o escribí tu pedido…",
        "send": "Enviar a Claude", "sent": "Enviado a la sesión de Claude.",
        "no_session": "Ninguna sesión de Claude está mirando este tablero: copiá el pedido y pegalo en el chat.",
        "credit": "Firmado «Built with Keelokit»", "credit_off": "Sin firma de Keelokit",
        "live_wait": "Cargando el tablero…",
        "report_title": "Reporte de {name}", "report_eyebrow": "Reporte del proyecto",
        "report_footer": "Reporte generado el {when} a partir del repositorio · Keelokit {version} · Solo lectura: para trabajar, /keelokit:project-dashboard",
        "live_off": "Esta vista no puede leer los datos del tablero. Pedile a Claude /keelokit:project-dashboard.",
        "live_stale": "Hay una versión nueva del diseño del tablero. Pedile a Claude /keelokit:project-dashboard para actualizarlo.",
    },
    "en": {
        "updated": "Updated {when}", "refresh": "Copy the request to refresh the dashboard",
        "stage_of": "Stage {n} of {total} · {stage}", "all_done": "Every stage approved",
        "serial": "One story at a time", "parallel": "Up to {n} stories in parallel",
        "copy": "Copy", "copied": "Copied", "copied_ask": "Copied. Finish it in the chat or below.",
        "copy_failed": "Couldn't copy. The text is: ", "copy_ask": "Copy request",
        "wait_n": "Waiting on you", "nothing": "Nothing waits for you right now.",
        "k_decision": "Decision", "k_gate": "Approval", "k_gap": "Open question", "k_health": "Harness",
        "k_maint": "Maintenance", "k_env": "Environment", "k_setup": "Setup",
        "bb_of": "bug bash of {date}", "sec_of": "security review of {date}", "deploy_guide": "deploy guide",
        "decide_bb": "About {id} from the bug bash of {date}: ", "decide_sec": "About {id} from the security review of {date}: ",
        "env_missing": ("{n} step left for {env}: {steps}.", "{n} steps left for {env}: {steps}."),
        "waves": "Development waves", "of_stories": "{done} of {total} stories", "backlog": "Whole backlog",
        "wave": "Wave {n}", "wave_done": "done", "no_wave": "No wave",
        "s_done": "Done", "s_ready": "Ready · copy", "s_waits": "Waits for {ids}", "s_gap": "Waits for an answer to {gaps}",
        "from_bb": "from a bug bash", "from_sec": "from security", "from_feature": "new feature",
        "review": "Ready for review", "review_docs": "Documents", "approve": "Approve", "change": "Ask for changes",
        "health": "Health and environments", "doctor_ok": "Harness without errors",
        "doctor_err": ("{n} harness error", "{n} harness errors"),
        "bb_line": "{fixed} of {total} fixed", "to_backlog": ("{n} went to the backlog", "{n} went to the backlog"),
        "decisions_n": ("{n} decision", "{n} decisions"), "env_ready": "{env} ready", "env_prep": "{env} being set up",
        "steps": "{done}/{total} steps", "docs": "Project documents",
        "d_context": "Context", "d_prd": "PRD", "d_stack": "Stack", "d_backlog": "Backlog", "d_decisions": "Decisions ({n})",
        "report": "Generate the full report", "report_ask": "/keelokit:project-report",
        "ask_h": "Ask Claude", "ask_ph": "A button above fills this in, or write your request…",
        "send": "Send to Claude", "sent": "Sent to the Claude session.",
        "no_session": "No Claude session is watching this dashboard: copy the request and paste it in the chat.",
        "credit": "Signed “Built with Keelokit”", "credit_off": "No Keelokit credit",
        "live_wait": "Loading the dashboard…",
        "report_title": "{name} report", "report_eyebrow": "Project report",
        "report_footer": "Report generated {when} from the repository · Keelokit {version} · Read-only: to work on the project, /keelokit:project-dashboard",
        "live_off": "This view can't read the dashboard's data. Ask Claude for /keelokit:project-dashboard.",
        "live_stale": "There's a new version of the dashboard's design. Ask Claude for /keelokit:project-dashboard to update it.",
    },
}


MONTHS = {"es": "ene feb mar abr may jun jul ago sep oct nov dic".split(),
          "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()}


def short_date(value: str, lang: str, time: str = "") -> str:
    """2026-09-24 → "24 sep" / "Sep 24" (and ", 11:20" with a time); anything else as written."""
    try:
        d = dt.date.fromisoformat(value[:10])
    except ValueError:
        return value
    m = MONTHS[lang][d.month - 1]
    day = f"{d.day} {m}" if lang == "es" else f"{m} {d.day}"
    return f"{day}, {time}" if time else day


def n_of(o: dict, key: str, n: int, **kw) -> str:
    one, many = o[key]
    return (one if n == 1 else many).format(n=n, **kw)


def pending_lines(text: str) -> dict[str, str]:
    """`- **CPY-1** — what to decide…` lines of a report's Pending decisions → {id: text}."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(("- **", "* **")):
            continue
        rest = line[4:]
        fid, sep, after = rest.partition("**")
        if sep and fid:
            out[fid.strip()] = after.lstrip(" —–-:").strip()
    return out


def ops_link(href: str | None, text: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{esc(href)}">{esc(text)}</a>' if href else f'<span{c}>{esc(text)}</span>'


def ops_btn(label: str, text: str, cls: str = "quiet", aria: str = "") -> str:
    a = f' aria-label="{esc(aria)}"' if aria else ""
    return f'<button type="button" class="{cls}" data-ask="{esc(text)}"{a}>{esc(label)}</button>'


def render_ops(s: dict, lang: str, standalone: bool, out_dir: Path, version: str) -> dict:
    """The operational page's parts: `when` (the refresh time) and `html` (everything below the top bar)."""
    t, o, stage_copy = T[lang], OPS_T[lang], STAGES[lang]
    names = {k: v[0] for k, v in stage_copy.items()}
    links = Links(s["github"], standalone, out_dir, s["root"])
    nxt = next_step(s, lang)
    current = next((x for x in s["stages"] if x["status"] in ("review", "current")), None)
    building = current is None and bool(s["stories"])
    total = len(s["stages"]) + (1 if s["stories"] else 0)

    # The voyage: where the project is, its fixed decisions, the stepper, the next step.
    if current:
        idx = s["stages"].index(current) + 1
        where = o["stage_of"].format(n=idx, total=total, stage=names[current["id"]])
    elif building:
        where = o["stage_of"].format(n=total, total=total, stage=t["build_stage"])
    else:
        where = o["all_done"]
    chips = [t["greenfield"] if s["layout"] == "project" else t["brownfield"]]
    mode, build = s["run"].get("mode"), s["run"].get("build")
    if mode:
        chips.append(t["run_auto"] if mode == "auto" else t["run_step"])
    if build == "parallel":
        chips.append(o["parallel"].format(n=s["run"].get("parallel", 2)))
    elif build:
        chips.append(o["serial"])
    steps = [(names[x["id"]], x["status"]) for x in s["stages"]]
    if s["stories"]:
        steps.append((t["build_stage"], "current" if building else "todo"))
    step_html = "".join(
        ('<li class="now" aria-current="step">' if st in ("review", "current") else f'<li class="{"done" if st == "done" else ""}">')
        + f"<span>{esc(n)}</span></li>" for n, st in steps)
    story_of = {x["id"]: x for x in s["stories"]}
    title_href = None
    if nxt["command"] and nxt["command"].startswith("/keelokit:build-story "):
        sid = nxt["command"].split()[-1]
        title_href = links.href(story_of[sid]["path"]) if sid in story_of else None
    title = ops_link(title_href, nxt["title"])
    cmd = ""
    if nxt["command"]:
        cmd = (f'<div class="term"><code>{esc(nxt["command"])}</code>'
               f'{ops_btn(o["copy"], nxt["command"], "primary")}</div>')
    elif current and current["status"] == "review":
        name = names[current["id"]]
        cmd = (f'<div class="row">{ops_btn(o["approve"], t["act_approve_t"].format(stage=name), "primary")}'
               f'{ops_btn(o["change"], t["act_change_t"].format(stage=name))}</div>')
    voyage = (f'<section class="card voyage" aria-labelledby="name"><div class="sea"><div><p class="eyebrow">{esc(where)}</p>'
              f'<h1 id="name">{esc(s["name"])}</h1></div>'
              f'<div class="chips">{"".join(f"<span class=chip>{esc(c)}</span>" for c in chips)}</div>'
              f'<ol class="steps" style="--n:{len(steps)}">{step_html}</ol></div>'
              f'<div class="next"><p class="eyebrow">{esc(t["next"])}</p><h2>{title}</h2>{cmd}'
              f'<p class="muted">{inline(nxt["detail"])}</p></div></section>')

    # What waits for the person, most specific first.
    items = []
    for x in s["stages"]:
        if x["status"] == "review":
            name = names[x["id"]]
            items.append(("", o["k_gate"], "", t["wait_gate"].format(stage=name), "",
                          ops_btn(o["approve"], t["act_approve_t"].format(stage=name))))
    for g in s["gaps"]:
        if g["blocking"]:
            items.append(("", o["k_gap"], "", f'{g["id"]}: {g["question"] or g["missing"]}', "",
                          ops_btn(o["copy_ask"], t["act_answer_t"].format(gap=g["id"]))))
    for runs, of, ask_key in ((s["bugbashes"], "bb_of", "decide_bb"), (s["security"], "sec_of", "decide_sec")):
        for b in runs:
            texts = pending_lines(b["pending"])
            source = ops_link(links.href(b["path"]), o[of].format(date=short_date(b["date"], lang)))
            for f in b["findings"]:
                if f["status"].lower().startswith(("pending", "pendiente")):
                    text = texts.get(f["id"], f["title"])
                    items.append((f["severity"], o["k_decision"], source, f'<span class="id">{esc(f["id"])}</span> {inline(text)}',
                                  "html", ops_btn(o["copy_ask"], o[ask_key].format(id=f["id"], date=b["date"]))))
    if s["errors"]:
        items.append(("", o["k_health"], "", n_of(o, "doctor_err", s["errors"]), "",
                      ops_btn(o["copy_ask"], "/keelokit:check-health")))
    if s["no_main"]:
        items.append(("", o["k_setup"], "", t["wait_no_main"], "", ""))
    hosted = s["profile"] is None or "hosted" in s["profile"]["traits"]
    if hosted:
        for e in s["environments"]:
            left = [x["text"] for x in e["steps"] if not x["done"]]
            if e["steps"] and left:
                items.append(("", o["k_env"], ops_link(links.href("docs/deploy.md"), o["deploy_guide"]),
                              n_of(o, "env_missing", len(left), env=e["name"], steps="; ".join(left)), "soft",
                              ops_btn(o["copy_ask"], "/keelokit:ship-setup")))
    if s["profile"] and s["profile"]["kind"] in ("", "unknown"):
        items.append(("", o["k_setup"], "", t["wait_profile_unknown"], "soft", ops_btn(o["copy_ask"], "/keelokit:check-health")))
    elif s["drift"]:
        items.append(("", o["k_setup"], "", drift_sentence(s["drift"][0], t), "soft", ops_btn(o["copy_ask"], "/keelokit:check-health")))
    if behind(s):
        items.append(("", o["k_maint"], "", t["wait_harness"].format(have=s["harness"], new=s["plugin_version"]), "soft",
                      ops_btn(o["copy_ask"], "/keelokit:harness-upgrade")))
    if s["gates"] and not s["run"].get("mode"):
        items.append(("", o["k_setup"], "", t["wait_decide"], "soft", ops_btn(o["copy_ask"], "/keelokit")))
    rows = []
    for sev, kind, source, text, flag, btn in items:
        body = text if flag == "html" else inline(text)
        sev_html = f'<span class="sev">{esc(sev)}</span>' if sev else ""
        src = f" · {source}" if source else ""
        cls = ' class="soft"' if flag == "soft" else ""
        rows.append(f'<li{cls}><p class="kind">{sev_html}{esc(kind)}{src}</p><p class="txt">{body}</p>{btn}</li>')
    wait = (f'<section class="card sec" aria-labelledby="wait-h"><div class="head"><p class="eyebrow" id="wait-h">{esc(o["wait_n"])}</p>'
            f'<span class="count">{len(rows)}</span></div>'
            + (f'<ul class="wait">{"".join(rows)}</ul>' if rows else f'<p class="muted">{esc(o["nothing"])}</p>') + "</section>")

    # The work: a stage up for review before the backlog exists, the waves once it does.
    work = ""
    if current and current["status"] == "review":
        name, what, checks = stage_copy[current["id"]]
        docs = "".join(f"<li>{ops_link(links.href(p), p)}</li>" for p in current.get("outputs", []))
        work = (f'<section class="card sec" aria-labelledby="review-h"><div class="head"><p class="eyebrow" id="review-h">'
                f'{esc(o["review"])} · {esc(name)}</p></div><p>{esc(what)}</p>'
                f'<ul class="checks">{"".join(f"<li>{esc(c)}</li>" for c in checks)}</ul>'
                + (f'<p class="eyebrow">{esc(o["review_docs"])}</p><ul class="docs">{docs}</ul>' if docs else "") + "</section>")
    if s["stories"]:
        waves = {}
        for x in s["stories"]:
            waves.setdefault(x["wave"], []).append(x)
        blocks = []
        for w in sorted(waves, key=lambda k: (k == 0, k)):
            group = waves[w]
            done = sum(1 for x in group if x["status"] == "done")
            bars = "".join(f'<i class="{"d" if x["status"] == "done" else "r" if x["status"] == "ready" else ""}"></i>' for x in group)
            frac = f'{esc(o["wave_done"])} · {done}/{len(group)}' if done == len(group) else f"{done}/{len(group)}"
            lis = []
            for x in group:
                dot = {"done": "d", "ready": "r"}.get(x["status"], "")
                tag = ""
                if x["origin"].startswith("bugbash:"):
                    tag = f'<span class="tag">{esc(o["from_bb"])}</span>'
                elif x["origin"].startswith("security:"):
                    tag = f'<span class="tag">{esc(o["from_sec"])}</span>'
                elif x["origin"].startswith("feature:"):
                    tag = f'<span class="tag">{esc(o["from_feature"])}</span>'
                if x["status"] == "done":
                    st = f'<span class="st">{esc(o["s_done"])}</span>'
                elif x["status"] == "ready":
                    st = ops_btn(o["s_ready"], f"/keelokit:build-story {x['id']}", "cp", f"/keelokit:build-story {x['id']}")
                elif x["status"] == "gap":
                    st = f'<span class="st">{esc(o["s_gap"].format(gaps=", ".join(x["gaps"])))}</span>'
                else:
                    st = f'<span class="st">{esc(o["s_waits"].format(ids=", ".join(x.get("waits", []))))}</span>'
                lis.append(f'<li><span class="dot {dot}"></span>{ops_link(links.href(x["path"]), x["id"], "id")}'
                           f'<span class="t">{esc(x["title"])}{tag}</span>{st}</li>')
            label = o["wave"].format(n=w) if w else o["no_wave"]
            blocks.append(f'<details class="wave"{"" if done == len(group) else " open"}><summary><b>{esc(label)}</b>'
                          f'<span class="bar">{bars}</span><span class="frac">{frac}</span></summary>'
                          f'<ul class="stories">{"".join(lis)}</ul></details>')
        done_all = sum(1 for x in s["stories"] if x["status"] == "done")
        work += (f'<section class="card sec" aria-labelledby="waves-h"><div class="head"><p class="eyebrow" id="waves-h">{esc(o["waves"])}</p>'
                 f'<span class="count">{esc(o["of_stories"].format(done=done_all, total=len(s["stories"])))}</span>'
                 f'{ops_link(links.href("backlog/epics.md"), o["backlog"], "aside")}</div>'
                 f'<div class="waves">{"".join(blocks)}</div></section>')

    # Health and environments: one line each, with the report it comes from.
    hl = []
    if s["doctor"] or s["gates"]:
        if s["errors"]:
            hl.append(("warn", "●", n_of(o, "doctor_err", s["errors"]), "doctor"))
        else:
            hl.append(("ok", "✓", esc(o["doctor_ok"]), "doctor"))
    for runs, of in ((s["bugbashes"], "bb_of"), (s["security"], "sec_of")):
        if runs:
            b = runs[0]
            fixed = sum(1 for f in b["findings"] if f["status"].lower().startswith(("fixed", "corregid")))
            pend = sum(1 for f in b["findings"] if f["status"].lower().startswith(("pending", "pendiente")))
            line = ops_link(links.href(b["path"]), o[of].format(date=short_date(b["date"], lang)).capitalize()) + ": " + esc(
                o["bb_line"].format(fixed=fixed, total=len(b["findings"])))
            if b["stories"]:
                line += ", " + esc(n_of(o, "to_backlog", len(b["stories"])))
            hl.append(("warn" if pend else "ok", "●" if pend else "✓", line, n_of(o, "decisions_n", pend) if pend else ""))
    if hosted:
        for e in s["environments"]:
            if not e["steps"]:
                continue
            done = sum(1 for x in e["steps"] if x["done"])
            ready = done == len(e["steps"])
            name = ops_link(links.href("docs/deploy.md"), e["name"].capitalize())
            text = (o["env_ready"] if ready else o["env_prep"]).replace("{env}", name)
            if e["url"] and ready:
                text += f' · <span class="id">{esc(e["url"])}</span>'
            hl.append(("ok" if ready else "warn", "✓" if ready else "●", text,
                       o["steps"].format(done=done, total=len(e["steps"]))))
    health = ""
    if hl:
        health = (f'<section class="card sec" aria-labelledby="health-h"><p class="eyebrow" id="health-h">{esc(o["health"])}</p>'
                  f'<ul class="health">{"".join(f"<li><span class={c}>{m}</span><span>{x}</span><span class=note>{esc(n)}</span></li>" for c, m, x, n in hl)}</ul></section>')

    # Documents and the report.
    docs = []
    for rel, key in (("docs/context/product.md", "d_context"), ("docs/prd.md", "d_prd"), ("docs/stack.md", "d_stack"),
                     ("backlog/epics.md", "d_backlog")):
        if (s["root"] / rel).exists():
            docs.append(ops_link(links.href(rel), o[key]))
    if s["adrs"]:
        docs.append(ops_link(links.href("docs/decisions/"), o["d_decisions"].format(n=len(s["adrs"]))))
    level = s["credit"] if s["credit"] in ("visible", "quiet", "off") else "visible"
    credit = esc(o["credit_off"] if level == "off" else o["credit"])
    foot = (f'<footer class="foot"><nav aria-label="{esc(o["docs"])}">{"".join(docs)}</nav>'
            f'<span class="right">{ops_btn(o["report"], o["report_ask"])}</span>'
            f'<span class="meta">{credit} · Keelokit {esc(version)}</span></footer>')
    now = dt.datetime.now().astimezone()
    when = short_date(now.date().isoformat(), lang, now.strftime("%H:%M"))
    return {"when": o["updated"].format(when=when), "html": voyage + wait + work + health + foot}


OPS_CSS = """
:root{--ground:#F6F1E8;--paper:#FFFDF8;--sunk:#EFE8DA;--ink:#172126;--ink-2:#4A5552;--ink-3:#5F6661;--line:#E3DCCF;--line-2:#D3C9B6;
--accent:#114D96;--ok:#1C7559;--ok-soft:#DDF2E9;--attn:#9C4C0E;--attn-soft:#FBE7D4;--live:#7A5C00;--idle:#8A8F88;--idle-soft:#ECE5D8;
--board:#FBC82A;--foam:#F6F1E8;--foam-2:rgba(246,241,232,.88);
--display:"Cormorant Garamond",Georgia,serif;--body:"Karla",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"Fragment Mono",ui-monospace,Menlo,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--ground:#040F28;--paper:#081834;--sunk:#0C2147;--ink:#F6F1E8;--ink-2:rgba(246,241,232,.76);--ink-3:rgba(246,241,232,.54);--line:rgba(246,241,232,.12);--line-2:rgba(246,241,232,.22);--accent:#8FC0F2;--ok:#8FE0C4;--ok-soft:rgba(143,224,196,.12);--attn:#FFAE6B;--attn-soft:rgba(238,123,36,.15);--live:#FBC82A;--idle:rgba(246,241,232,.58);--idle-soft:rgba(246,241,232,.07)}}
:root[data-theme="dark"]{color-scheme:dark;--ground:#040F28;--paper:#081834;--sunk:#0C2147;--ink:#F6F1E8;--ink-2:rgba(246,241,232,.76);--ink-3:rgba(246,241,232,.54);--line:rgba(246,241,232,.12);--line-2:rgba(246,241,232,.22);--accent:#8FC0F2;--ok:#8FE0C4;--ok-soft:rgba(143,224,196,.12);--attn:#FFAE6B;--attn-soft:rgba(238,123,36,.15);--live:#FBC82A;--idle:rgba(246,241,232,.58);--idle-soft:rgba(246,241,232,.07)}
*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:var(--ground);color:var(--ink);font:15px/1.55 var(--body);padding-inline:16px;padding-block:18px 40px;overflow-wrap:anywhere}
.page{max-width:680px;margin-inline:auto;display:grid;gap:14px}
[data-slot="body"]{display:contents}
a{color:var(--accent);text-underline-offset:3px;text-decoration-thickness:1px}a:hover{text-decoration-thickness:2px}
.id{font:12.5px/1.3 var(--mono);letter-spacing:-.01em}
a.id{text-decoration:none;border-bottom:1px solid currentColor;justify-self:start}
p{margin:0}
.eyebrow{font:600 11px/1.2 var(--body);letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3)}
.muted{color:var(--ink-3);font-size:13.5px}
.muted code{font:12.5px var(--mono)}
:focus-visible{outline:2px solid var(--attn);outline-offset:2px;border-radius:6px}
.top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.top img{width:22px;height:22px;border-radius:6px}
.top b{font-weight:600}.top .crumb{color:var(--ink-3);min-width:0}
.top .right{margin-left:auto;display:flex;align-items:center;gap:8px}
.icon{width:32px;height:32px;border-radius:50%;border:1px solid var(--line-2);background:var(--paper);color:var(--ink-2);display:grid;place-items:center;cursor:pointer;padding:0}
.icon:hover{border-color:var(--accent);color:var(--accent)}.icon svg{width:15px;height:15px}
.card{background:var(--paper);border:1px solid var(--line);border-radius:16px}
.voyage{overflow:hidden}
.sea{color:var(--foam);background:linear-gradient(165deg,#1A64B0 0%,#0B3574 55%,#040F28 100%);padding:18px 20px 16px;display:grid;gap:14px}
.sea .eyebrow{color:var(--foam-2)}
.sea h1{font:600 34px/1 var(--display);margin:6px 0 0}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font:12px/1 var(--body);color:var(--foam-2);border:1px solid rgba(246,241,232,.22);padding:5px 9px;border-radius:999px}
.steps{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(var(--n),1fr);gap:6px}
.steps li{display:grid;gap:6px;font-size:11.5px;color:var(--foam-2);min-width:0}
.steps li span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.steps li::before{content:"";height:4px;border-radius:2px;background:rgba(246,241,232,.22)}
.steps .done::before{background:#8FE0C4}.steps .now{color:var(--foam)}.steps .now::before{background:var(--board)}
.next{padding:16px 20px 18px;display:grid;gap:10px}
.next h2{font:italic 500 23px/1.2 var(--display);margin:0}
.next h2 a{color:inherit;text-decoration:none}.next h2 a:hover{text-decoration:underline}
.term{display:flex;align-items:center;gap:10px;background:var(--sunk);border-radius:10px;padding:7px 7px 7px 12px}
.term code{flex:1;font:13px/1.4 var(--mono);overflow-wrap:anywhere}
.term code::before{content:"› ";color:var(--live)}
.row{display:flex;gap:8px;flex-wrap:wrap}
button{font:600 12.5px/1 var(--body);border-radius:999px;padding:8px 13px;cursor:pointer;white-space:nowrap;border:1px solid transparent}
.primary{background:var(--board);color:#172126}.primary:hover{filter:brightness(.96)}
.quiet{background:transparent;color:var(--accent);border-color:var(--line-2)}.quiet:hover{border-color:var(--accent)}
.quiet:disabled{opacity:.5;cursor:default}
.sec{padding:16px 20px;display:grid;gap:12px}
.head{display:flex;align-items:baseline;gap:6px 10px;flex-wrap:wrap}
.head .count{font:12px/1 var(--mono);color:var(--ink-3)}
.head .aside{margin-left:auto;font-size:13.5px;white-space:nowrap}
.wait{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.wait li{display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:start;padding:11px 12px 11px 14px;border-radius:12px;background:var(--attn-soft)}
.wait li.soft{background:var(--sunk)}
.wait .kind{display:flex;gap:6px;align-items:center;flex-wrap:wrap;font-size:12px;color:var(--attn);font-weight:600}
.wait .soft .kind{color:var(--ink-3)}
.wait .txt{grid-column:1}.wait .txt code{font:12.5px var(--mono)}
.wait button{grid-column:2;grid-row:1/span 2;align-self:center}
.sev{font:600 11px/1 var(--mono);padding:3px 5px;border-radius:5px;background:var(--attn);color:var(--paper)}
.checks,.docs{margin:0;padding-left:18px;display:grid;gap:4px}
.docs{list-style:none;padding:0}
.waves{display:grid}
details.wave{border-top:1px solid var(--line)}details.wave:first-child{border-top:0}
.wave summary{list-style:none;cursor:pointer;display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding-block:11px}
.wave summary::-webkit-details-marker{display:none}
.wave summary b{font:600 19px/1 var(--display);min-width:56px}
.bar{display:flex;gap:3px}.bar i{flex:1;height:7px;border-radius:2px;background:var(--idle-soft)}
.bar .d{background:var(--ok)}.bar .r{background:var(--board)}
.frac{font:12.5px/1 var(--mono);color:var(--ink-3);display:flex;gap:8px;align-items:center;font-variant-numeric:tabular-nums}
.frac::after{content:"";width:7px;height:7px;border-right:1.5px solid var(--ink-3);border-bottom:1.5px solid var(--ink-3);transform:rotate(45deg);transition:transform .15s}
details[open] .frac::after{transform:rotate(-135deg)}
.stories{list-style:none;margin:0 0 12px;padding:0;display:grid}
.stories li{display:grid;grid-template-columns:12px 96px minmax(0,1fr) fit-content(40%);gap:10px;align-items:center;padding:7px 0;border-top:1px dashed var(--line)}
.stories li:first-child{border-top:0}
.dot{width:9px;height:9px;border-radius:50%;background:var(--idle-soft);border:1.5px solid var(--idle)}
.dot.d{background:var(--ok);border-color:var(--ok)}.dot.r{background:var(--board);border-color:#C99A0E}
.st{font-size:12.5px;color:var(--ink-3);text-align:right}
.tag{font-size:11.5px;color:var(--attn);margin-left:6px;white-space:nowrap}
.cp{border:0;background:none;padding:2px 4px;color:var(--accent);font:600 12px/1 var(--body);text-decoration:underline;text-underline-offset:3px}
.health{list-style:none;margin:0;padding:0;display:grid}
.health li{display:grid;grid-template-columns:18px 1fr auto;gap:10px;align-items:baseline;padding:8px 0;border-top:1px solid var(--line)}
.health li:first-child{border-top:0}
.ok{color:var(--ok)}.warn{color:var(--attn)}
.health .note{font-size:13px;color:var(--ink-3)}
.foot{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;font-size:13.5px;color:var(--ink-3);padding-inline:4px}
.foot nav{display:flex;gap:12px;flex-wrap:wrap}.foot .right{margin-left:auto}.foot .meta{width:100%;font-size:12.5px}
.ask{padding:14px 16px;display:grid;gap:8px}
.ask textarea{width:100%;min-height:64px;resize:vertical;font:14px/1.5 var(--body);color:var(--ink);background:var(--sunk);border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.ask .status{font-size:13px;color:var(--ink-3)}
.stale{padding:10px 14px;border-radius:12px;background:var(--attn-soft);color:var(--attn);font-size:14px}
.toast{position:fixed;left:50%;bottom:calc(20px + env(safe-area-inset-bottom,0px));transform:translate(-50%,8px);opacity:0;background:var(--ink);color:var(--ground);font-size:13px;padding:8px 14px;border-radius:999px;transition:.18s;pointer-events:none;max-width:calc(100% - 32px)}
.toast.on{opacity:1;transform:translate(-50%,0)}
@media (max-width:560px){
  .steps li span{display:none}.steps{gap:4px}
  .stories li{grid-template-columns:12px minmax(0,1fr) fit-content(50%)}.stories li .t{grid-column:2/4;grid-row:2;font-size:14px}
  .wait li{grid-template-columns:1fr}.wait button{grid-column:1;grid-row:auto;justify-self:start}
  .sea h1{font-size:30px}.top .when{display:none}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

OPS_JS = """
(function(){
  var root=document.documentElement, marker=document.querySelector('[data-lang]');
  if(marker)root.setAttribute('lang',marker.getAttribute('data-lang'));
  var toast=document.getElementById('toast'), timer, box=document.getElementById('ask'), ta=document.getElementById('ask-text'),
      send=document.getElementById('ask-send'), status=document.getElementById('ask-status'), comments=null;
  function msg(k){return toast.getAttribute('data-'+k)||''}
  function say(text){toast.textContent=text;toast.classList.add('on');clearTimeout(timer);timer=setTimeout(function(){toast.classList.remove('on')},2200)}
  function copy(text,partial){
    function ok(){say(partial?msg('copied-ask'):msg('copied')+': '+text)}
    function fail(){say(msg('failed')+text)}
    try{navigator.clipboard.writeText(text).then(ok,fail)}catch(e){fail()}
  }
  function refresh(){
    if(!comments){send.hidden=true;return Promise.resolve()}
    return comments.canSendToClaude().then(function(v){return v},function(){return 'off'}).then(function(v){
      send.hidden=v==='off';send.disabled=v!=='available';
      status.textContent=v==='no_session'?box.getAttribute('data-no-session'):'';
    });
  }
  document.addEventListener('click',function(e){
    var b=e.target.closest('button[data-ask]');if(!b)return;
    var text=b.getAttribute('data-ask'), partial=/[:：]\\s$/.test(text);
    copy(text,partial);
    if(box){ta.value=text;if(partial){ta.focus();ta.setSelectionRange(text.length,text.length)}refresh()}
  });
  if(box){
    document.getElementById('ask-copy').addEventListener('click',function(){var t=ta.value.trim();if(t)copy(t,false)});
    send.addEventListener('click',function(){var t=ta.value.trim();if(!t||!comments)return;send.disabled=true;
      comments.anchorFor(box).then(function(a){return comments.sendToClaude({anchor:a,text:t})}).then(function(){
        ta.value='';status.textContent=box.getAttribute('data-sent');send.disabled=false},
      function(){send.disabled=false;status.textContent=box.getAttribute('data-no-session');refresh()});
    });
  }
  var theme=document.getElementById('theme');
  function dark(){var a=root.getAttribute('data-theme');return a?a==='dark':!!(window.matchMedia&&matchMedia('(prefers-color-scheme: dark)').matches)}
  function paint(){theme.setAttribute('aria-label',theme.getAttribute(dark()?'data-light':'data-dark'))}
  try{var saved=localStorage.getItem('keelokit-theme');if(saved==='dark'||saved==='light')root.setAttribute('data-theme',saved)}catch(e){}
  theme.addEventListener('click',function(){var n=dark()?'light':'dark';root.setAttribute('data-theme',n);
    try{localStorage.setItem('keelokit-theme',n)}catch(e){}paint()});
  paint();
  function use(name){return Promise.resolve(window.claude&&window.claude.use?window.claude.use(name):null).catch(function(){return null})}
  use('comments').then(function(c){comments=c;refresh()});

  var live=document.getElementById('live');
  if(!live)return;
  // The live page: its content is one document in the artifact's database, which Claude rewrites
  // on every refresh; open waves stay open across updates.
  var slot=document.querySelector('[data-slot="body"]'), when=document.getElementById('when'), shown=false;
  function note(key){if(shown)return;var p=document.createElement('p');p.className='muted';p.textContent=live.getAttribute('data-'+key);
    slot.textContent='';slot.appendChild(p)}
  function key(d){var s=d.querySelector('summary');return s?s.textContent:''}
  use('db').then(function(db){
    if(!db){note('off');return}
    db.doc('dash/ops').onSnapshot(function(snap){
      var d=snap.exists?snap.data():null;if(!d||typeof d.html!=='string'){note('off');return}
      var open=null;if(shown){open={};slot.querySelectorAll('details').forEach(function(x){open[key(x)]=x.open})}
      slot.innerHTML=d.html;when.textContent=d.when||'';
      if(open)slot.querySelectorAll('details').forEach(function(x){var k=key(x);if(k in open)x.open=open[k]});
      document.getElementById('live-stale').hidden=!d.shell||d.shell===live.getAttribute('data-shell');
      shown=true;
    },function(){note('off')});
  });
})();
"""

REFRESH_ICON = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
                '<path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v3h-3"/></svg>')
THEME_ICON = ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
              '<path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5Z"/></svg>')


def ops_page(name: str, lang: str, parts: dict | None, standalone: bool = False) -> tuple[str, str]:
    """The operational page and its shell id. Without parts it is the live shell: the same page,
    empty, filled from the artifact's database document `dash/ops` and kept current by it."""
    t, o = T[lang], OPS_T[lang]
    live = parts is None
    body = parts["html"] if parts else f'<p class="muted">{esc(o["live_wait"])}</p>'
    when = parts["when"] if parts else ""
    marker = (f'<div hidden id="live" data-shell="SHELL" data-off="{esc(o["live_off"])}"></div>'
              f'<p class="stale" id="live-stale" hidden>{esc(o["live_stale"])}</p>') if live else ""
    img = logo()
    page = f"""<title>{esc(t["title"].format(name=name))}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;1,500&family=Fragment+Mono&family=Karla:wght@400;500;600&display=swap">
<style>{OPS_CSS}</style>
<div hidden data-lang="{lang}"></div>
<div class="page">
<header class="top">{f'<img src="{img}" alt="">' if img else ""}<b>Keelokit</b><span class="crumb">/ {esc(name)}</span>
<span class="right"><span class="muted when" id="when">{esc(when)}</span>{ops_btn("", "/keelokit:project-dashboard", "icon", o["refresh"]).replace("></button>", ">" + REFRESH_ICON + "</button>")}
<button type="button" class="icon" id="theme" data-dark="{esc(t["theme_dark"])}" data-light="{esc(t["theme_light"])}" aria-label="{esc(t["theme_dark"])}">{THEME_ICON}</button></span></header>
{marker}<div data-slot="body">{body}</div>
<section class="card ask" id="ask" data-sent="{esc(o["sent"])}" data-no-session="{esc(o["no_session"])}">
<label class="eyebrow" for="ask-text">{esc(o["ask_h"])}</label>
<textarea id="ask-text" placeholder="{esc(o["ask_ph"])}"></textarea>
<div class="row"><button type="button" class="primary" id="ask-send" hidden>{esc(o["send"])}</button><button type="button" class="quiet" id="ask-copy">{esc(o["copy"])}</button></div>
<p class="status" id="ask-status" aria-live="polite"></p></section>
</div>
<div class="toast" id="toast" role="status" aria-live="polite" data-copied="{esc(o["copied"])}" data-copied-ask="{esc(o["copied_ask"])}" data-failed="{esc(o["copy_failed"])}"></div>
<script>{OPS_JS}</script>
"""
    shell_id = hashlib.sha256(page.encode()).hexdigest()[:12] if live else ""
    page = page.replace('data-shell="SHELL"', f'data-shell="{shell_id}"', 1)
    if standalone:
        page = (f'<!doctype html>\n<html lang="{lang}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head>\n'
                f"<body>{page}</body></html>\n")
    return page, shell_id


def set_dashboard_key(path: Path, key: str, value: str) -> None:
    """Set `key = "value"` in the [dashboard] table of state.toml, keeping everything else as written."""
    lines = read(path).splitlines()
    new = f'{key} = "{value}"'
    start = next((i for i, x in enumerate(lines) if x.strip() == "[dashboard]"), None)
    if start is None:
        lines += ([""] if lines and lines[-1].strip() else []) + ["[dashboard]", new]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        hit = next((i for i in range(start + 1, end) if lines[i].split("=")[0].strip() == key), None)
        if hit is None:
            lines.insert(start + 1, new)
        else:
            lines[hit] = new
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def live(root: Path, s: dict, lang: str, version: str, dash: dict, args) -> int:
    """The live shell (published once, again only when its design changes) and its one data
    document, written to the artifact's database on every refresh without passing through the chat."""
    out = args.out or root / ".keelokit/out/live"
    page, shell_id = ops_page(s["name"], lang, None)
    if args.shell_published:
        try:
            set_dashboard_key(root / ".keelokit/state.toml", "shell", shell_id)
        except OSError as e:
            return fail(1, f"can't write {e.filename} ({e.strerror or e})")
        print(json.dumps({"shell": shell_id, "recorded": ".keelokit/state.toml"}))
        return 0
    doc = {"shell": shell_id, **render_ops(s, lang, False, out, version)}
    try:
        out.mkdir(parents=True, exist_ok=True)
        if out.parent == root / ".keelokit/out" and not (out.parent / ".gitignore").exists():
            (out.parent / ".gitignore").write_text("*\n")
        (out / "shell.html").write_text(page, encoding="utf-8")
        (out / "ops.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        return fail(1, f"can't write {e.filename or out} ({e.strerror or e}); pass --out <a folder you can write>")
    print(json.dumps({
        "url": dash.get("url", ""),
        "shell": {"file": str((out / "shell.html").resolve()), "id": shell_id,
                  "publish": dash.get("shell") != shell_id or not dash.get("url")},
        "data": {"collection": "dash", "doc_id": "ops", "file_path": str((out / "ops.json").resolve())},
    }, indent=1, ensure_ascii=False))
    return 0


LANG_NAMES = {"es": "es", "spa": "es", "español": "es", "espanol": "es", "spanish": "es",
              "en": "en", "eng": "en", "english": "en", "inglés": "en", "ingles": "en"}


def normalise_lang(value: str) -> str:
    """`es`, `es-AR`, `es_UY.UTF-8`, `Español` → `es`. Unknown or missing → `en`."""
    v = str(value).strip().lower()
    return LANG_NAMES.get(v) or LANG_NAMES.get(re.split(r"[-_.]", v)[0], "en") if v else "en"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=Path, default=None)
    ap.add_argument("--lang", default=None, help="es or en (es-AR, Español… also work)")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--standalone", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--report", action="store_true", help="the full report instead of the operational page")
    ap.add_argument("--live", action="store_true",
                    help="write the live shell and its data document for the artifact's database, and print what to do")
    ap.add_argument("--shell-published", action="store_true",
                    help="with --live: record in state.toml that the shell just written is the published one")
    args = ap.parse_args()

    try:
        root = (args.root or find_root(Path.cwd())).resolve()
        what = "" if root.is_dir() else "not a folder" if root.exists() else "does not exist"
    except (OSError, RuntimeError) as e:  # the current folder is gone, or a symlink loop
        what = getattr(e, "strerror", None) or str(e)
    if what:  # never a greenfield page for a folder that isn't there
        where = args.root or "the current folder"
        return fail(2, f"no such project: {where} ({what}); pass --root <project folder>")
    s = collect(root)
    try:
        dash = tomllib.loads(read(root / ".keelokit/state.toml")).get("dashboard", {})
    except tomllib.TOMLDecodeError:
        dash = {}
    lang = normalise_lang(args.lang or dash.get("lang", ""))

    if args.json:
        view = {k: v for k, v in s.items() if k not in ("root", "by_id", "context", "prd", "stack_doc", "diagnosis")}
        view["stories"] = [{k: v for k, v in x.items() if k != "body"} for x in s["stories"]]
        view["done"] = sorted(s["done"])
        view["next"] = next_step(s, lang)
        view["waiting"] = waiting_on_user(s, lang)
        view["bugbashes"] = [{k: v for k, v in b.items() if k != "text"} for b in s["bugbashes"]]
        view["summaries"] = {x["id"]: stage_summary(s, x, T[lang]) for x in s["stages"]}
        print(json.dumps(view, indent=2, ensure_ascii=False))
        return 0

    out = args.out or root / f".keelokit/out/{'report' if args.report else 'dashboard'}.html"
    try:
        version = json.loads(read(PLUGIN_ROOT / ".claude-plugin/plugin.json")).get("version", "")
    except json.JSONDecodeError:
        version = ""
    if args.live:
        return live(root, s, lang, version, dash, args)
    if args.report:
        page = render(s, lang, args.standalone, out.parent, version)
    else:
        page = ops_page(s["name"], lang, render_ops(s, lang, args.standalone, out.parent, version), args.standalone)[0]
    try:  # a read-only checkout, a folder where the page goes, a full disk: say so, no traceback
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.parent == root / ".keelokit/out" and not (out.parent / ".gitignore").exists():
            (out.parent / ".gitignore").write_text("*\n")
        out.write_text(page, encoding="utf-8")
    except OSError as e:
        return fail(1, f"can't write {e.filename or out} ({e.strerror or e}); "
                       "pass --out <a file you can write>, or --json to print the state instead")
    print(out)
    return 0


def fail(code: int, message: str) -> int:
    print(f"dashboard: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
