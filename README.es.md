<p align="center"><img src="docs/assets/keelokit-icon.svg" width="120" alt="Ícono de Keelokit: una tabla con hidrofoil volando sobre el agua"></p>

# Keelokit

**Mi harness personal de Claude Code para construir aplicaciones en monorepos TypeScript.**

*[keelokit.com](https://keelokit.com) · [Read in English](README.md)*

Soy [Leopoldo Simini](https://leopoldosimini.com). Hace muchos años que escribo software y casi
toda la vida que emprendo cosas. Los agentes de código cambiaron mi forma de construir: ideas que
antes esperaban un equipo o un mes libre ahora tienen una primera versión real. Keelokit es el
harness que uso para eso —mi stack, mis reglas, mi forma de trabajar— y lo mantengo como hobby,
los fines de semana y en noches de música y código, aprendiendo sobre la marcha.

Lo comparto por si le sirve a alguien que está dando sus primeros pasos con agentes, o a
emprendedores y equipos —técnicos o no— que están armando la base de su primer MVP. Es opinado y
está hecho a mi gusto, así que no va a encajar en todos los proyectos ni en todos los equipos.
Tomá lo que te sirva.

## La idea

Cuando construyo con agentes, las reglas importantes no pueden vivir solo en un prompt. Por eso en
Keelokit cada regla apunta a algo que la verifica —un test, una regla de lint, un hook de git, un job
de CI— y un script chico (`doctor`) avisa cuando una regla se quedó sin su verificación. Lo que
no se sabe queda escrito como pregunta abierta en vez de adivinarse, y el agente que escribe el
código no es el que dice que está terminado.

## Qué hace

| Comando | Qué pasa |
|---|---|
| `/keelokit:kickstart` | De una idea a un esqueleto que funciona: una entrevista que escribe el contexto del producto, un PRD corto, el stack, un monorepo generado con CI y un primer backlog |
| `/keelokit:adopt` | Para un repo existente: suma solo el harness (`.keelokit/`), mapea sus reglas a los checks que el repo ya tiene y deja el resto como excepciones con fecha |
| `/keelokit:intake` | Lee lo que ya tenés y pregunta solo lo que falta; lo que nadie sabe todavía queda como pregunta abierta |
| `/keelokit:backlog` | Épicas e historias con escenarios de aceptación y los invariantes que cuidan, agrupadas para que el trabajo en paralelo no toque los mismos archivos ni la misma área crítica |
| `/keelokit:build` | Una historia: un verificador escribe primero los tests de aceptación, un builder los hace pasar, un revisor lee el diff, un breaker intenta romperla (de nuevo después del rebase si main avanzó) y el verificador la recorre en la app corriendo |
| `/keelokit:bugbash` | Una cacería de bugs en datos, API, integridad, UX, i18n, accesibilidad, seguridad y más; cada bug que se escapó suma un check para toda su clase, para que no vuelva |
| `/keelokit:doctor` | ¿Cada regla sigue verificada? Sumar una regla, registrar una excepción |
| `/keelokit:upgrade` | Llevar un proyecto a un template más nuevo sin tocar el código del producto |
| `/keelokit` | Dónde está el proyecto, qué sigue y qué espera tu decisión |

## El stack que genera

pnpm workspaces · TypeScript strict · NestJS + Prisma + PostgreSQL · Vite + React · Expo · Astro ·
contratos zod e i18n en un paquete compartido · tokens de diseño en otro · Vitest, Jest,
Playwright con axe · GitHub Actions · Fly.io. Elegís qué apps necesita cada producto. Los motivos
están en [`template/.keelokit/harness/stack.md`](template/.keelokit/harness/stack.md).

## Probarlo

Necesitás Node 22 con pnpm 10, Python 3.11+, [uv](https://docs.astral.sh/uv/) (corre
[Copier](https://copier.readthedocs.io/)), Docker y git. macOS o Linux.

```bash
claude plugin marketplace add leosimini/keelokit
claude plugin install keelokit@keelokit
```

Después, en una carpeta vacía, abrí Claude Code y corré `/keelokit:kickstart`. En un repo que ya
tenés, `/keelokit:adopt`. Para generar desde tu propio fork: `KEELOKIT_TEMPLATE=gh:<vos>/keelokit`.

## Bueno saber

- Es opinado a propósito. Si tu stack es otro, `adopt` igual te da las reglas, el guard y los
  checks, pero no el esqueleto.
- `build` y `bugbash` usan varios agentes por historia y consumen más tokens que un chat solo.
  Para cambios chicos existe `build --light`.
- El guard que frena a los agentes para que no salteen hooks ni escriban secretos es un reductor
  de velocidad, no un sandbox. Los hooks de git y el CI son el respaldo real.
- `doctor` puede ver que un check existe y está prendido, no que sea un buen check. En el código
  crítico eso lo mide el mutation testing; en el resto, las revisiones y las cacerías de bugs.
- Los bugs vienen en clases, así que el harness apunta a clases: las reglas que siempre tienen
  que cumplirse (los totales cierran, un aviso sale una sola vez, un límite aguanta dos requests
  a la vez) se escriben como invariantes y se prueban con tests de propiedades, de concurrencia
  y de repetición; el código donde un bug cuesta más se marca como área crítica y se construye
  de a una historia. Ver [`docs/design.md`](docs/design.md#bugs-come-in-classes).
- Los skills entienden pedidos en español y en inglés.

## Datos y red

Keelokit no tiene servidor propio y no recolecta nada. Lo que escribe (contexto, PRD, backlog,
código) queda en tu repo. El tráfico de red es el que ya hacen tus herramientas de siempre:

- **GitHub:** `kickstart`, `adopt` y `upgrade` bajan el template con Copier
  (`gh:leosimini/keelokit`, o tu fork con `KEELOKIT_TEMPLATE`). `kickstart` pregunta antes de
  crear un repo privado con `gh repo create --push`, que sube tu código a tu cuenta.
- **Registros de paquetes y Docker Hub:** para instalar las dependencias e imágenes del proyecto generado.
- **Fly.io:** solo el CI del proyecto generado hace deploy ahí, con un secret `FLY_API_TOKEN`
  que creás vos en la configuración del repo. El plugin nunca lo lee.

La entrevista no registra datos personales de personas reales: las cuentas se nombran por rol,
nunca con credenciales.

## Cómo está hecho

[`docs/design.md`](docs/design.md) explica las piezas: el plugin, el template, las reglas de la
casa y qué puede ver `doctor` y qué no. Keelokit se prueba a sí mismo:
`python3 -m unittest discover -s tests` para el guard y `doctor`, y `scripts/test-template.sh`
para generar proyectos y correr todos sus checks.

## Ideas de las que aprendí

El desarrollo guiado por especificaciones ([OpenSpec](https://github.com/Fission-AI/OpenSpec),
[Spec Kit](https://github.com/github/spec-kit)), [Superpowers](https://github.com/obra/superpowers)
por separar quién construye de quién revisa, [Copier](https://copier.readthedocs.io/) por los
templates que se pueden actualizar, y mucha prueba y error en mis propios proyectos.

## Licencia

MIT — ver [LICENSE](LICENSE). Hecho por [Leopoldo Simini](https://leopoldosimini.com).
