from __future__ import annotations

import json
import os
from contextlib import contextmanager
from typing import Any, Iterable

import pandas as pd


def data_mode() -> str:
    return os.getenv("APP_DATA_MODE", "unity_catalog").strip().lower()


def source_mode() -> str:
    explicit = os.getenv("APP_SOURCE_MODE", "").strip().lower()
    if explicit:
        return explicit
    return "unity_catalog" if data_mode() in {"unity_catalog", "uc", "databricks"} else "local_csv"


def state_mode() -> str:
    explicit = os.getenv("APP_STATE_MODE", "").strip().lower()
    if explicit:
        return explicit
    return "unity_catalog" if data_mode() in {"unity_catalog", "uc", "databricks"} else "local"


def use_unity_catalog_source() -> bool:
    return source_mode() in {"unity_catalog", "uc", "databricks", "catalog"}


def use_unity_catalog_state() -> bool:
    return state_mode() in {"unity_catalog", "uc", "databricks", "catalog"}


def use_unity_catalog() -> bool:
    return use_unity_catalog_source() or use_unity_catalog_state()


def fallback_on_state_error() -> bool:
    setting = os.getenv("APP_STATE_FALLBACK_ON_ERROR", "").strip().lower()
    if setting in {"1", "true", "yes", "on"}:
        return True
    if setting in {"0", "false", "no", "off"}:
        return False
    return use_unity_catalog()


def app_config_summary() -> dict[str, Any]:
    return {
        "data_mode": data_mode(),
        "source_mode": source_mode(),
        "state_mode": state_mode(),
        "source_catalog": os.getenv("APP_SOURCE_CATALOG") or os.getenv("DATABRICKS_CATALOG"),
        "source_schema": os.getenv("APP_SOURCE_SCHEMA") or os.getenv("DATABRICKS_SCHEMA"),
        "source_table": os.getenv("APP_SOURCE_TABLE", "facilities"),
        "result_catalog": os.getenv("APP_RESULT_CATALOG", "dais_readiness_desk"),
        "warehouse_configured": bool(os.getenv("DATABRICKS_WAREHOUSE_ID") or os.getenv("APP_SQL_WAREHOUSE_ID")),
        "host_configured": bool(os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_WORKSPACE_URL")),
        "token_configured": bool(os.getenv("DATABRICKS_TOKEN")),
        "source_row_limit": os.getenv("APP_SOURCE_ROW_LIMIT", ""),
        "state_load_timeout_seconds": os.getenv("APP_STATE_LOAD_TIMEOUT_SECONDS", "20"),
        "fallback_on_state_error": fallback_on_state_error(),
    }


def safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def quote_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def full_name(catalog: str, schema: str, table: str) -> str:
    return ".".join(quote_identifier(part) for part in [catalog, schema, table])


def source_table_name() -> str:
    catalog = os.getenv("APP_SOURCE_CATALOG") or os.getenv("DATABRICKS_CATALOG")
    schema = os.getenv("APP_SOURCE_SCHEMA") or os.getenv("DATABRICKS_SCHEMA")
    table = os.getenv("APP_SOURCE_TABLE", "facilities")
    if not catalog or not schema or not table:
        raise RuntimeError("Missing APP_SOURCE_CATALOG, APP_SOURCE_SCHEMA, or APP_SOURCE_TABLE.")
    return full_name(catalog, schema, table)


def target_table_name(schema: str, table: str) -> str:
    catalog = os.getenv("APP_RESULT_CATALOG", "dais_readiness_desk")
    return full_name(catalog, schema, table)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def json_literal(value: Any) -> str:
    return sql_literal(json.dumps(value, ensure_ascii=False))


def _server_hostname() -> str:
    host = os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_WORKSPACE_URL")
    if not host:
        raise RuntimeError("Missing DATABRICKS_HOST or DATABRICKS_WORKSPACE_URL.")
    return host.removeprefix("https://").removeprefix("http://").rstrip("/")


def _access_token() -> str:
    token = os.getenv("DATABRICKS_TOKEN")
    if token:
        return token

    try:
        from databricks.sdk.config import Config

        headers = Config(host=os.getenv("DATABRICKS_HOST") or os.getenv("DATABRICKS_WORKSPACE_URL")).authenticate()
        authorization = headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            return authorization.removeprefix("Bearer ")
    except Exception as exc:
        raise RuntimeError("Could not resolve Databricks auth token from runtime environment.") from exc

    raise RuntimeError("Could not resolve Databricks auth token from runtime environment.")


@contextmanager
def sql_connection():
    from databricks import sql

    warehouse_id = os.getenv("DATABRICKS_WAREHOUSE_ID") or os.getenv("APP_SQL_WAREHOUSE_ID")
    if not warehouse_id:
        raise RuntimeError("Missing DATABRICKS_WAREHOUSE_ID or APP_SQL_WAREHOUSE_ID.")

    connection = sql.connect(
        server_hostname=_server_hostname(),
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        access_token=_access_token(),
    )
    try:
        yield connection
    finally:
        connection.close()


def read_sql(query: str) -> pd.DataFrame:
    with sql_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            columns = [column[0] for column in cursor.description or []]
            return pd.DataFrame(cursor.fetchall(), columns=columns)


def execute_sql(query: str) -> None:
    with sql_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)


def execute_many(statements: Iterable[str]) -> None:
    with sql_connection() as connection:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
