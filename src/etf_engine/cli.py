import json

import typer

from etf_engine.pipeline import run as run_pipeline
from etf_engine.services.build_classifications import build as build_classifications
from etf_engine.services.data_audit import audit_price_caches
from etf_engine.services.public_builder import build_public
from etf_engine.services.sync_holdings import sync as sync_holdings
from etf_engine.services.sync_tw_entities import sync as sync_tw_entities
from etf_engine.services.sync_us_entities import sync as sync_us_entities
from etf_engine.validation import validate as validate_seed
from etf_engine.repository import SeedRepository

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate():
    errors = validate_seed()
    if errors:
        typer.echo("\n".join(errors))
        raise typer.Exit(1)
    typer.echo("Seed validation passed")


@app.command("run")
def run(
    market: str = typer.Option("all", help="all, TW, or US"),
    bootstrap_only: bool = typer.Option(
        False,
        help="Process only ETFs without a local price cache",
    ),
    publish: bool = typer.Option(
        True,
        help="Build and publish validated public JSON after the run",
    ),
):
    result = run_pipeline(
        market.upper() if market.lower() != "all" else "all",
        bootstrap_only=bootstrap_only,
        publish=publish,
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


@app.command("sync-us-entities")
def sync_us(
    apply_new: bool = typer.Option(
        False,
        help="Automatically enroll ETFs first seen after the previous official snapshot",
    ),
):
    result = sync_us_entities(apply_new=apply_new)
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


@app.command("audit-data")
def audit_data(market: str = typer.Option("all", help="all, TW, or US")):
    normalized = market.upper() if market.lower() != "all" else "all"
    entities = [
        entity
        for entity in SeedRepository().entities()
        if entity.active
        and (normalized == "all" or entity.listing_market == normalized)
    ]
    typer.echo(json.dumps(audit_price_caches(entities), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
