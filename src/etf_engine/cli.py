import json
import typer
from etf_engine.pipeline import run as run_pipeline
from etf_engine.services.public_builder import build_public
from etf_engine.validation import validate as validate_seed

app = typer.Typer(no_args_is_help=True)


@app.command()
def validate():
    errors = validate_seed()
    if errors:
        typer.echo('\n'.join(errors))
        raise typer.Exit(1)
    typer.echo('Seed validation passed')


@app.command('run')
def run(market: str = typer.Option('all', help='all, TW, or US')):
    result = run_pipeline(market.upper() if market.lower() != 'all' else 'all')
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command('build-public')
def public():
    build_public()
    typer.echo('Public JSON built')


if __name__ == '__main__':
    app()
