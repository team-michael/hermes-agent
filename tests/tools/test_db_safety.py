from pathlib import Path

from tools.db_safety import apply_postgres_safety_env, validate_local_db_command


def test_postgres_safety_env_sets_timeout_and_result_budgets(monkeypatch):
    env = {"PGOPTIONS": "-c application_name=hermes"}

    apply_postgres_safety_env(env)

    assert "statement_timeout=120000" in env["PGOPTIONS"]
    assert "default_transaction_read_only=on" in env["PGOPTIONS"]
    assert env["HERMES_DB_MAX_RESULT_ROWS"] == "100000"
    assert env["HERMES_DB_MAX_RESULT_BYTES"] == str(128 * 1024 * 1024)


def test_postgres_safety_env_honors_configured_budgets():
    env = {
        "TERMINAL_DB_STATEMENT_TIMEOUT_MS": "30000",
        "TERMINAL_DB_MAX_RESULT_ROWS": "5000",
        "TERMINAL_DB_MAX_RESULT_BYTES": "1048576",
    }

    apply_postgres_safety_env(env)

    assert "statement_timeout=30000" in env["PGOPTIONS"]
    assert env["HERMES_DB_MAX_RESULT_ROWS"] == "5000"
    assert env["HERMES_DB_MAX_RESULT_BYTES"] == "1048576"


def test_postgres_safety_env_is_idempotent():
    env = {}

    apply_postgres_safety_env(env)
    first = env["PGOPTIONS"]
    apply_postgres_safety_env(env)

    assert env["PGOPTIONS"] == first
    assert env["PGOPTIONS"].count("statement_timeout=") == 1


def test_unbounded_fetchall_in_referenced_db_script_is_blocked(tmp_path: Path):
    script = tmp_path / "scan.py"
    script.write_text(
        "import psycopg2\nrows = conn.cursor().fetchall()\n",
        encoding="utf-8",
    )

    reason = validate_local_db_command(f"python3 {script}", str(tmp_path))

    assert reason is not None
    assert "fetchall" in reason


def test_full_tenant_dynamic_union_is_blocked(tmp_path: Path):
    script = tmp_path / "scan.py"
    script.write_text(
        "import psycopg2\n"
        "tables = ['scorecards_' + tenant for tenant in tenants]\n"
        "query = ' UNION ALL '.join(f'SELECT * FROM {table}' for table in tables)\n",
        encoding="utf-8",
    )

    reason = validate_local_db_command(f"python3 {script}", str(tmp_path))

    assert reason is not None
    assert "UNION" in reason


def test_bounded_fetchmany_db_script_is_allowed(tmp_path: Path):
    script = tmp_path / "scan.py"
    script.write_text(
        "import psycopg2\n"
        "row_limit = int(os.environ['HERMES_DB_MAX_RESULT_ROWS'])\n"
        "byte_limit = int(os.environ['HERMES_DB_MAX_RESULT_BYTES'])\n"
        "rows = cursor.fetchmany(min(row_limit, 1000))\n",
        encoding="utf-8",
    )

    assert validate_local_db_command(f"python3 {script}", str(tmp_path)) is None


def test_fetchmany_without_byte_budget_is_blocked(tmp_path: Path):
    script = tmp_path / "scan.py"
    script.write_text(
        "import psycopg2\n"
        "limit = int(os.environ['HERMES_DB_MAX_RESULT_ROWS'])\n"
        "rows = cursor.fetchmany(min(limit, 1000))\n",
        encoding="utf-8",
    )

    reason = validate_local_db_command(f"python3 {script}", str(tmp_path))

    assert reason is not None
    assert "MAX_RESULT_BYTES" in reason


def test_explicit_small_tenant_union_is_allowed():
    command = (
        "python3 -c \"import psycopg2; query = "
        "'SELECT id FROM scorecards_a UNION ALL SELECT id FROM scorecards_b'\""
    )

    assert validate_local_db_command(command) is None


def test_direct_psql_select_requires_limit():
    reason = validate_local_db_command("psql -c 'SELECT id FROM users'")

    assert reason is not None
    assert "LIMIT" in reason
    assert validate_local_db_command("psql -c 'SELECT id FROM users LIMIT 100'") is None
    assert validate_local_db_command("psql -c 'SELECT id FROM users LIMIT 100001'") is not None
    assert validate_local_db_command("psql -c 'SELECT count(*) FROM users'") is None


def test_non_database_fetchall_is_not_blocked():
    assert validate_local_db_command("client.fetchAll()") is None
