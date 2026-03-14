"""data.gov.my live API client and dataset catalog.

Provides a curated catalog of high-value datasets whose metadata gets
indexed into the vector store.  At chat time, when retrieval matches a
catalog entry the client fetches fresh rows from the REST API so the
LLM can answer with up-to-date numbers.

API docs: https://developer.data.gov.my/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)

API_BASE = "https://api.data.gov.my"

# Unauthenticated limit is 4 req/min.  With a token it's 10 req/min.
_DEFAULT_TIMEOUT = 15
_DEFAULT_LIMIT = 20


# ---------------------------------------------------------------------------
# Dataset catalog
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CatalogEntry:
    """Describes one dataset on data.gov.my that we want discoverable."""

    dataset_id: str
    endpoint: str  # "data-catalogue" or "opendosm"
    title_en: str
    title_ms: str
    description_en: str
    description_ms: str
    columns: list[str]
    frequency: str  # e.g. "weekly", "monthly", "annual"
    category: str
    default_sort: str = "-date"
    default_limit: int = _DEFAULT_LIMIT


# Curated high-value datasets.  Extend this list as needed.
CATALOG: list[CatalogEntry] = [
    CatalogEntry(
        dataset_id="fuelprice",
        endpoint="data-catalogue",
        title_en="Weekly Fuel Prices",
        title_ms="Harga Minyak Mingguan",
        description_en=(
            "Weekly retail fuel prices in Malaysia for RON95, RON97, and diesel, "
            "set by the government under the Automatic Pricing Mechanism (APM)."
        ),
        description_ms=(
            "Harga runcit minyak mingguan di Malaysia untuk RON95, RON97, dan diesel, "
            "ditetapkan oleh kerajaan di bawah Mekanisme Harga Automatik (APM)."
        ),
        columns=["date", "ron95", "ron97", "diesel", "series_type"],
        frequency="weekly",
        category="prices",
    ),
    CatalogEntry(
        dataset_id="cpi_headline",
        endpoint="opendosm",
        title_en="Consumer Price Index (CPI) — Headline",
        title_ms="Indeks Harga Pengguna (IHP) — Keseluruhan",
        description_en=(
            "Monthly Consumer Price Index (CPI) headline figures for Malaysia "
            "measuring the average change in prices paid by consumers for goods and services."
        ),
        description_ms=(
            "Angka bulanan Indeks Harga Pengguna (IHP) keseluruhan bagi Malaysia "
            "mengukur purata perubahan harga yang dibayar oleh pengguna untuk barangan dan perkhidmatan."
        ),
        columns=["date", "overall", "food", "non_food"],
        frequency="monthly",
        category="prices",
    ),
    CatalogEntry(
        dataset_id="gdp_qtr_real",
        endpoint="opendosm",
        title_en="Gross Domestic Product (GDP) — Quarterly Real",
        title_ms="Keluaran Dalam Negeri Kasar (KDNK) — Suku Tahunan Sebenar",
        description_en=(
            "Quarterly real Gross Domestic Product for Malaysia, "
            "including absolute values and year-on-year growth rates."
        ),
        description_ms=(
            "Keluaran Dalam Negeri Kasar sebenar suku tahunan bagi Malaysia, "
            "termasuk nilai mutlak dan kadar pertumbuhan tahun ke tahun."
        ),
        columns=["date", "series", "value"],
        frequency="quarterly",
        category="national_accounts",
    ),
    CatalogEntry(
        dataset_id="population_state",
        endpoint="opendosm",
        title_en="Population by State",
        title_ms="Penduduk Mengikut Negeri",
        description_en=(
            "Annual population estimates by state in Malaysia, "
            "including breakdowns by sex and ethnicity."
        ),
        description_ms=(
            "Anggaran penduduk tahunan mengikut negeri di Malaysia, "
            "termasuk pecahan mengikut jantina dan etnik."
        ),
        columns=["date", "state", "sex", "ethnicity", "population"],
        frequency="annual",
        category="demography",
    ),
    CatalogEntry(
        dataset_id="lfs_month",
        endpoint="opendosm",
        title_en="Labour Force Survey — Monthly",
        title_ms="Survei Tenaga Buruh — Bulanan",
        description_en=(
            "Monthly labour force statistics including employment, "
            "unemployment rate, and labour force participation rate for Malaysia."
        ),
        description_ms=(
            "Statistik tenaga buruh bulanan termasuk pekerjaan, "
            "kadar pengangguran, dan kadar penyertaan tenaga buruh bagi Malaysia."
        ),
        columns=["date", "labour_force", "employed", "unemployed", "unemployment_rate", "participation_rate"],
        frequency="monthly",
        category="labour",
    ),
    CatalogEntry(
        dataset_id="exchangerates",
        endpoint="data-catalogue",
        title_en="Daily Exchange Rates",
        title_ms="Kadar Pertukaran Harian",
        description_en=(
            "Daily exchange rates of the Malaysian Ringgit (MYR) "
            "against major currencies published by Bank Negara Malaysia."
        ),
        description_ms=(
            "Kadar pertukaran harian Ringgit Malaysia (MYR) "
            "berbanding mata wang utama diterbitkan oleh Bank Negara Malaysia."
        ),
        columns=["date", "currency", "rate"],
        frequency="daily",
        category="financial",
    ),
    CatalogEntry(
        dataset_id="birth",
        endpoint="opendosm",
        title_en="Live Births",
        title_ms="Kelahiran Hidup",
        description_en=(
            "Annual live birth statistics in Malaysia by state, "
            "ethnicity, and sex of the newborn."
        ),
        description_ms=(
            "Statistik kelahiran hidup tahunan di Malaysia mengikut negeri, "
            "etnik, dan jantina bayi."
        ),
        columns=["date", "state", "sex", "ethnicity", "births"],
        frequency="annual",
        category="demography",
    ),
    CatalogEntry(
        dataset_id="death",
        endpoint="opendosm",
        title_en="Deaths",
        title_ms="Kematian",
        description_en=(
            "Annual death statistics in Malaysia by state, sex, "
            "ethnicity, and age group."
        ),
        description_ms=(
            "Statistik kematian tahunan di Malaysia mengikut negeri, "
            "jantina, etnik, dan kumpulan umur."
        ),
        columns=["date", "state", "sex", "ethnicity", "deaths"],
        frequency="annual",
        category="demography",
    ),
    CatalogEntry(
        dataset_id="iowrt",
        endpoint="opendosm",
        title_en="Industrial Production Index (IPI)",
        title_ms="Indeks Pengeluaran Perindustrian (IPP)",
        description_en=(
            "Monthly industrial output, wholesale, and retail trade indices "
            "for Malaysia tracking manufacturing and trade activity."
        ),
        description_ms=(
            "Indeks pengeluaran perindustrian, perdagangan borong, dan runcit "
            "bulanan bagi Malaysia menjejak aktiviti pembuatan dan perdagangan."
        ),
        columns=["date", "series", "value"],
        frequency="monthly",
        category="economic_sectors",
    ),
    CatalogEntry(
        dataset_id="cpi_2d",
        endpoint="opendosm",
        title_en="CPI by Category (2-digit)",
        title_ms="IHP mengikut Kategori (2-digit)",
        description_en=(
            "Monthly Consumer Price Index broken down by 2-digit COICOP "
            "categories such as Food, Transport, Housing, Health, Education."
        ),
        description_ms=(
            "Indeks Harga Pengguna bulanan dipecahkan mengikut kategori "
            "COICOP 2-digit seperti Makanan, Pengangkutan, Perumahan, Kesihatan, Pendidikan."
        ),
        columns=["date", "division", "index"],
        frequency="monthly",
        category="prices",
    ),
]

CATALOG_BY_ID: dict[str, CatalogEntry] = {entry.dataset_id: entry for entry in CATALOG}


def build_metadata_text(entry: CatalogEntry) -> str:
    """Build a text blob suitable for embedding in the vector store."""
    columns_str = ", ".join(entry.columns)
    return (
        f"{entry.title_en} / {entry.title_ms}\n\n"
        f"{entry.description_en}\n\n"
        f"{entry.description_ms}\n\n"
        f"Dataset ID: {entry.dataset_id}\n"
        f"Columns: {columns_str}\n"
        f"Update frequency: {entry.frequency}\n"
        f"Category: {entry.category}\n"
        f"API endpoint: {entry.endpoint}"
    )


# ---------------------------------------------------------------------------
# Live API client
# ---------------------------------------------------------------------------

@dataclass
class DataGovMyClient:
    """Async client for the data.gov.my REST API."""

    api_token: str | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return a shared httpx client (lazy-created, reuses connections)."""
        if not hasattr(self, "_client_instance"):
            self._client_instance = httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT, follow_redirects=True
            )
        return self._client_instance

    async def fetch_dataset(
        self,
        entry: CatalogEntry,
        *,
        limit: int | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> list[dict]:
        """Fetch rows from data.gov.my for *entry*.

        Returns a list of dicts (JSON rows) or an empty list on error.
        """
        url = f"{API_BASE}/{entry.endpoint}"
        params: dict[str, str] = {"id": entry.dataset_id}
        params["sort"] = entry.default_sort
        params["limit"] = str(limit or entry.default_limit)
        # The API requires date filters as YYYY-MM-DD@column_name
        date_col = "date"
        if date_start:
            params["date_start"] = f"{date_start}@{date_col}" if "@" not in date_start else date_start
        if date_end:
            params["date_end"] = f"{date_end}@{date_col}" if "@" not in date_end else date_end
        if extra_params:
            params.update(extra_params)

        headers: dict[str, str] = {}
        if self.api_token:
            headers["Authorization"] = f"Token {self.api_token}"

        try:
            client = self._get_client()
            resp = await client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            log.warning(
                "data.gov.my API error for %s: %s %s",
                entry.dataset_id,
                exc.response.status_code,
                exc.response.text[:200],
            )
            return []
        except Exception as exc:
            log.warning("data.gov.my request failed for %s: %s", entry.dataset_id, exc)
            return []

        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return []

    def format_rows_for_context(self, entry: CatalogEntry, rows: list[dict]) -> str:
        """Format API rows into a readable text block for the LLM prompt."""
        if not rows:
            return f"[No data returned from data.gov.my for {entry.title_en}]"

        lines = [f"Live data from data.gov.my — {entry.title_en} (most recent {len(rows)} records):"]
        lines.append("")

        # Build a simple table
        if rows:
            cols = list(rows[0].keys())
            header = " | ".join(cols)
            lines.append(header)
            lines.append("-" * len(header))
            for row in rows:
                lines.append(" | ".join(str(row.get(c, "")) for c in cols))

        lines.append("")
        lines.append(
            f"Source: data.gov.my ({entry.endpoint}, id={entry.dataset_id}). "
            f"Updated {entry.frequency}."
        )
        return "\n".join(lines)


def find_catalog_match(metadata: dict) -> CatalogEntry | None:
    """Check if a retrieved chunk's metadata points to a catalog dataset."""
    dataset_id = metadata.get("datagov_dataset_id")
    if isinstance(dataset_id, str):
        return CATALOG_BY_ID.get(dataset_id)
    return None


# ---------------------------------------------------------------------------
# Anthropic tool definition
# ---------------------------------------------------------------------------

def build_tool_definition() -> dict:
    """Return an Anthropic-format tool definition for querying data.gov.my."""
    dataset_ids = [e.dataset_id for e in CATALOG]
    dataset_descriptions = "\n".join(
        f"  - {e.dataset_id}: {e.title_en} ({e.frequency}, columns: {', '.join(e.columns)})"
        for e in CATALOG
    )
    return {
        "name": "query_government_data",
        "description": (
            "Query live Malaysian government data from data.gov.my. "
            "Use this tool when the user asks about current statistics, prices, "
            "economic indicators, or demographic data that may be available from "
            "official government datasets. Available datasets:\n"
            f"{dataset_descriptions}"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset_id": {
                    "type": "string",
                    "enum": dataset_ids,
                    "description": "The dataset to query.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 10, max 100).",
                    "default": 10,
                },
                "date_start": {
                    "type": "string",
                    "description": "Start date filter in YYYY-MM-DD format (optional).",
                },
                "date_end": {
                    "type": "string",
                    "description": "End date filter in YYYY-MM-DD format (optional).",
                },
                "filter": {
                    "type": "string",
                    "description": (
                        "Exact-match filter as value@column (e.g. 'Selangor@state'). Optional."
                    ),
                },
            },
            "required": ["dataset_id"],
        },
    }


async def execute_tool_call(
    client: DataGovMyClient,
    tool_input: dict,
) -> str:
    """Execute a query_government_data tool call and return formatted text."""
    dataset_id = tool_input.get("dataset_id", "")
    entry = CATALOG_BY_ID.get(dataset_id)
    if not entry:
        return f"Unknown dataset: {dataset_id}. Available: {', '.join(CATALOG_BY_ID)}"

    limit = min(tool_input.get("limit", 10), 100)
    extra_params: dict[str, str] = {}
    if tool_input.get("filter"):
        extra_params["filter"] = tool_input["filter"]

    rows = await client.fetch_dataset(
        entry,
        limit=limit,
        date_start=tool_input.get("date_start"),
        date_end=tool_input.get("date_end"),
        extra_params=extra_params if extra_params else None,
    )
    return client.format_rows_for_context(entry, rows)
