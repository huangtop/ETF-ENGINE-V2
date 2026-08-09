import io
import zipfile
from datetime import date

import pytest
import requests

from etf_engine.models import ETFEntity
from etf_engine.providers.holdings import FuhwaProvider


def entity(etf_id="TW-00991A"):
    return ETFEntity(
        etf_id=etf_id,
        ticker=etf_id.removeprefix("TW-"),
        quote_symbol=f"{etf_id.removeprefix('TW-')}.TW",
        name="主動復華未來50",
        listing_market="TW",
        listing_exchange="TWSE",
        currency="TWD",
        benchmark_symbol="^TWII",
    )


def workbook(as_of="2026/08/07", count=10):
    strings = [
        f"日期: {as_of}",
        "證券代號",
        "證券名稱",
        "股數",
        "金額",
        "權重(%)",
    ]
    rows = [[0], [1, 2, 3, 4, 5]]
    for index in range(count):
        strings.extend(
            [str(2330 + index), f"公司{index}", "1,000", "1,000,000", f"{10-index/2:.3f}%"]
        )
        start = len(strings) - 5
        rows.append(list(range(start, start + 5)))

    shared = "".join(f"<si><t>{value}</t></si>" for value in strings)
    sheet_rows = []
    for row_number, indexes in enumerate(rows, 1):
        cells = "".join(f'<c t="s"><v>{index}</v></c>' for index in indexes)
        sheet_rows.append(f'<row r="{row_number}">{cells}</row>')
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "xl/sharedStrings.xml",
                f'<sst xmlns="{namespace}">{shared}</sst>',
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{namespace}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
            )
        return output.getvalue()


class Response:
    def __init__(self, status_code=200, content=b"", payload=None):
        self.status_code = status_code
        self.content = content
        self.payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def get(self, url, timeout):
        self.urls.append((url, timeout))
        return next(self.responses)


def test_fetches_latest_available_official_workbook_and_normalizes_symbols():
    session = Session(
        [
            Response(404),
            Response(content=workbook()),
            Response(payload=[{"公司代號": "2330"}]),
        ]
    )
    provider = FuhwaProvider(session=session, today=lambda: date(2026, 8, 8))

    rows = provider.fetch(entity())

    assert session.urls[0][0].endswith("/ETF23/20260808")
    assert session.urls[1][0].endswith("/ETF23/20260807")
    assert len(rows) == 10
    assert rows[0] == {
        "etf_id": "TW-00991A",
        "holding_symbol": "2330.TW",
        "holding_name": "公司0",
        "weight": 0.1,
        "as_of": "2026-08-07",
        "source": "fuhwa",
        "rank": 1,
    }
    assert rows[1]["holding_symbol"] == "2331.TWO"
    assert sum(row["weight"] for row in rows) < 1


def test_rejects_workbook_whose_embedded_date_does_not_match_request():
    session = Session([Response(content=workbook("2026/08/06"))] + [Response(404)] * 10)
    provider = FuhwaProvider(session=session, today=lambda: date(2026, 8, 7))

    with pytest.raises(RuntimeError, match="workbook date is 2026-08-06"):
        provider.fetch(entity())


def test_rejects_empty_or_collapsed_official_workbook():
    session = Session([Response(content=workbook(count=2))] + [Response(404)] * 10)
    provider = FuhwaProvider(session=session, today=lambda: date(2026, 8, 7))

    with pytest.raises(RuntimeError, match="coverage too small"):
        provider.fetch(entity())


def test_unmapped_etf_does_not_make_network_request():
    session = Session([])
    assert FuhwaProvider(session=session).fetch(entity("TW-0050")) == []
    assert session.urls == []
