# Backup Restore Runbook

## Nightly Backup
```bash
docker compose exec -T db pg_dump -U postgres taskhub > backups/taskhub-$(date +%F).sql
```

## Restore Procedure
```bash
docker compose down
docker compose up -d db
cat backups/taskhub-YYYY-MM-DD.sql | docker compose exec -T db psql -U postgres -d taskhub
```

## Verification
```bash
docker compose exec -T db psql -U postgres -d taskhub -c "SELECT COUNT(*) FROM tasks_task;"
```

Run monthly restore verification and log results in `docs/progress/run-log.md`.
