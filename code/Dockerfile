FROM zero-trust-opa-authorization-api:0.1.0 AS runtime
COPY 03-resource-tenant-isolation/code/app/isolation /app/app/isolation
CMD ["uvicorn", "app.isolation.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM zero-trust-opa-authorization-checks:0.1.0 AS checks
COPY 03-resource-tenant-isolation/code/app/isolation /app/app/isolation
COPY 03-resource-tenant-isolation/code/tests /isolation-tests
CMD ["sh", "-c", "ruff check app/isolation /isolation-tests && ruff format --check app/isolation /isolation-tests && mypy app/isolation && python -m pytest -p no:cacheprovider /isolation-tests /checks /app/tests && opa test /policy -v && python /scripts/mutation_check.py"]