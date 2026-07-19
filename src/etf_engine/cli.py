import json

import typer

from etf_engine.pipeline import run as run_pipeline
from etf_engine.services.build_classifications import build as build_classifications
from etf_engine.services.public_builder import build_public
from etf_engine.services.sync_holdings import sync as sync_holdings
from etf_engine.services.sync_tw_entities import sync as sync_tw_entities
from etf_engine.validation import validate as validate_seed

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate():
    errors = validate_seed()
    if errors:
        typer.echo("\n".join(errors))
        raise typer.Exit(1)
    typer.echo("Seed validation passed")


@app.command("run")
def run(market: str = typer.Option("all", help="all, TW, or US")):
    result = run_pipeline(
        market.upper() if market.lower() != "all" else "all"
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("build-public")
def public():
    build_public()
    typer.echo("Public JSON built")


@app.command("sync-tw-entities")
def sync_tw(minimum_tw_count: int = 200):
    result = sync_tw_entities(minimum_tw_count=minimum_tw_count)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("build-classifications")
def classifications():
    result = build_classifications()
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("sync-holdings")
def holdings(market: str = typer.Option("all", help="all, TW, or US")):
    normalized = market.upper() if market.lower() != "all" else "all"
    result = sync_holdings(normalized)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
