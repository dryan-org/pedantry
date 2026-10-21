"""The ``pedantry`` command line."""

import json
from pathlib import Path
from typing import Annotated

import typer

from pedantry import __version__
from pedantry.content import vendor_install_hint
from pedantry.migrate import execute, plan_migrate
from pedantry.model import PedantryError, ProjectType
from pedantry.sync import (
    apply,
    compute,
    diff,
    npm_pin_command,
    resolve_pin,
    run_npm_pin,
)

app = typer.Typer(
    help="Sync shared lint and format configuration into a repo.",
    no_args_is_help=True,
    add_completion=False,
)

PathOption = Annotated[
    Path, typer.Option("--path", help="Repo root (default: current directory).")
]
TypeOption = Annotated[
    list[ProjectType] | None,
    typer.Option(
        "--type",
        help="Project type; repeat for several. Defaults to the pinned types.",
    ),
]
JsonOption = Annotated[bool, typer.Option("--json", help="Machine-readable output.")]


def fail(err: PedantryError) -> typer.Exit:
    typer.secho(str(err), fg=typer.colors.RED, err=True)
    return typer.Exit(2)


@app.command()
def version() -> None:
    """Print the pedantry version."""
    typer.echo(__version__)


@app.command()
def sync(
    path: PathOption = Path(),
    types: TypeOption = None,
    vendor: Annotated[
        bool,
        typer.Option(
            "--vendor",
            help="Also write the JS configs under .pedantry/ (no GitHub dependency).",
        ),
    ] = False,
    upgrade: Annotated[
        bool, typer.Option("--upgrade", help="Re-pin to the running version first.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show diffs without writing.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite managed files that lack a stamp.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Write the managed files for the pinned version and types."""
    root = path.resolve()
    try:
        resolved = resolve_pin(root, types=types, vendor=vendor, upgrade=upgrade)
        changes = compute(root, resolved, force=force)
    except PedantryError as err:
        raise fail(err) from err

    if not dry_run:
        apply(root, changes)

    npm_command = npm_pin_command(root, resolved.pin.version) if upgrade else None
    npm_note = None
    if npm_command and not dry_run:
        npm_note = run_npm_pin(root, npm_command)

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "version": resolved.pin.version,
                    "dry_run": dry_run,
                    "changes": [{"path": c.path, "status": c.status} for c in changes],
                    "npm": {
                        "command": " ".join(npm_command) if npm_command else None,
                        "ran": bool(npm_command) and not dry_run and npm_note is None,
                        "note": npm_note,
                    },
                },
                indent=2,
            )
        )
        return

    verb = "would write" if dry_run else "wrote"
    for change in changes:
        typer.echo(f"{verb} {change.path}")
        if dry_run:
            typer.echo(diff(change))
    if not changes:
        typer.echo(f"already in sync with pedantry {resolved.pin.version}")
    if npm_command:
        line = " ".join(npm_command)
        if dry_run:
            typer.echo(f"would run {line}")
        elif npm_note:
            typer.echo(npm_note)
        else:
            typer.echo(f"ran {line}")
    if resolved.pin.vendor and (
        hint := vendor_install_hint(frozenset(resolved.pin.types))
    ):
        typer.echo(
            f"Vendored configs import npm packages. Install them with:\n  {hint}"
        )


@app.command()
def check(
    path: PathOption = Path(),
    show_diff: Annotated[
        bool, typer.Option("--diff", help="Show what differs.")
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Exit 1 when managed files differ from what sync would write."""
    root = path.resolve()
    try:
        resolved = resolve_pin(root)
        changes = compute(root, resolved, force=True)
    except PedantryError as err:
        raise fail(err) from err

    if as_json:
        typer.echo(
            json.dumps(
                {
                    "version": resolved.pin.version,
                    "ok": not changes,
                    "changes": [{"path": c.path, "status": c.status} for c in changes],
                },
                indent=2,
            )
        )
    elif changes:
        typer.secho(
            f"Files out of sync with pedantry {resolved.pin.version} (run pedantry "
            "sync):",
            fg=typer.colors.RED,
            err=True,
        )
        for change in changes:
            typer.echo(f"  {change.path} ({change.status})", err=True)
            if show_diff:
                typer.echo(diff(change), err=True)
    else:
        typer.echo(f"in sync with pedantry {resolved.pin.version}")
    if changes:
        raise typer.Exit(1)


@app.command()
def migrate(
    path: PathOption = Path(),
    types: TypeOption = None,
    vendor: Annotated[
        bool, typer.Option("--vendor", help="Vendor the JS configs (no GitHub access).")
    ] = False,
    skip_npm: Annotated[
        bool, typer.Option("--skip-npm", help="Do not run npm install.")
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print the plan without changing anything."),
    ] = False,
    as_json: JsonOption = False,
) -> None:
    """Move a repo from the pedantry submodule and copied files to pedantry 2."""
    root = path.resolve()
    try:
        plan = plan_migrate(root, types=types, vendor=vendor, skip_npm=skip_npm)
        if not dry_run:
            execute(root, plan)
    except PedantryError as err:
        raise fail(err) from err

    report = plan.report
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "types": [t.value for t in plan.types],
                    "files": sorted(plan.edits),
                    **report.as_dict(),
                },
                indent=2,
            )
        )
        return

    typer.echo(
        ("Plan (nothing changed)" if dry_run else "Migrated")
        + f": {', '.join(t.value for t in plan.types)}"
    )
    sections = (
        ("Done" if not dry_run else "Would do", report.actions),
        ("Replaced (matches pedantry or an older copy of it)", report.replaced),
        ("Preserved (per-repo edits)", report.preserved),
        ("Needs a human", report.manual),
    )
    for title, items in sections:
        if items:
            typer.secho(f"\n{title}:", bold=True)
            for item in items:
                typer.echo(f"  - {item}")
    typer.secho(f"\n{'Would write' if dry_run else 'Wrote'}:", bold=True)
    for file_path, text in sorted(plan.edits.items()):
        typer.echo(f"  - {file_path}" + (" (delete)" if text is None else ""))
    if not dry_run:
        typer.echo(
            "\nNothing is committed. Written files are staged (except any your "
            ".gitignore excludes). Review with `git status` and `git diff --staged`."
        )
