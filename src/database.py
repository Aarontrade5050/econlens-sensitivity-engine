# database routines for storing and querying pipeline results
import duckdb
import polars as pl


def save_results(
    df: pl.DataFrame,
    db_path,
    table: str = "sensitivity_results",
    if_exists: str = "replace",
) -> None:
    con = duckdb.connect(str(db_path))
    if if_exists == "replace":
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
    elif if_exists == "append":
        try:
            con.execute(f"INSERT INTO {table} SELECT * FROM df")
        except duckdb.CatalogException:
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM df")
    con.close()


def load_results(
    db_path,
    table: str = "sensitivity_results",
    hs_code: str | None = None,
    actor: str | None = None,
    from_period: str | None = None,
    to_period: str | None = None,
) -> pl.DataFrame:
    con = duckdb.connect(str(db_path))

    filters = []
    if hs_code:
        filters.append(f"hs_code = '{hs_code}'")
    if actor:
        filters.append(f"actor = '{actor}'")
    if from_period:
        filters.append(f"periodo >= '{from_period}'")
    if to_period:
        filters.append(f"periodo <= '{to_period}'")

    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    result = con.execute(f"SELECT * FROM {table} {where}").pl()
    con.close()
    return result
