# PEREZ-AI Migration / Disaster-Recovery Toolkit

This toolkit prepares PEREZ-AI for a controlled move between EC2, Oracle Cloud, or another Linux VPS.

## Safety contract

- Migration tooling is **paper-only** by default.
- It refuses to proceed if the current `perez-ai.service` reports `PAPER_MODE` other than `true` or `ORDERS_ENABLED` other than `false`.
- It never commits `.env`, `/etc/perez-ai/*`, SSH keys, Nginx passwords, or TLS private keys.
- It does not start trading services on a newly bootstrapped server.
- The old server remains the rollback source until the new server passes verification.

## Architecture

```text
                    GitHub
                      |
             known-good commit
                      |
        +-------------+-------------+
        |                           |
     CURRENT EC2                 NEW VPS
        |                           |
  inventory/backup             bootstrap
        |                           |
        +------ encrypted ---------+
               persistent data
                      |
                 restore/verify
                      |
                shadow PAPER
                      |
                   cutover
                      |
                 rollback-ready
```

## Scripts

### 1. `inventory.sh`
Read-only inventory of the current host: OS, architecture, disk/RAM, services, safety flags, repo commit, persistent DBs, configuration locations, and network listeners. It does not change trading settings.

### 2. `backup-current.sh`
Creates an off-repo migration bundle under `~/PEREZ-MIGRATION-BACKUPS/`:

- exact Git commit and repository metadata
- SQLite online backups for known PEREZ databases
- persistent JSON/JSONL runtime/control state where present
- systemd unit files from the repository
- non-secret infrastructure inventory
- `/etc/perez-ai` is copied into a separate restricted `secrets/` archive and is **never** staged by Git

The script records SHA-256 checksums and SQLite `PRAGMA integrity_check` results.

### 3. `bootstrap-vps.sh`
For a fresh Ubuntu VPS. Installs base packages, sets `Asia/Kolkata`, clones PEREZ-AI at a specified commit, creates the Python venv, installs dependencies, and prepares systemd units. It deliberately leaves trading services stopped.

### 4. `restore.sh`
Restores the persistent application state from a migration bundle. It uses SQLite `.backup` output rather than copying a live SQLite database file directly. It does not start services.

### 5. `verify.sh`
Runs a migration readiness check: architecture, Python/imports, repo commit, SQLite integrity, required services/files, safety flags, dashboard bind configuration, and absence of live-order API patterns. It returns non-zero on a failed safety check.

## Recommended Oracle workflow

Oracle's current Always Free Ampere A1 allocation is up to 2 OCPUs and 12 GB RAM total, but it is ARM64 and must be validated against the project's Python/native dependencies before becoming primary. The migration process therefore starts with a parallel PAPER_MODE server, not an immediate cutover.

1. Create the Oracle VM with an Ubuntu image marked Always Free Eligible.
2. Restrict SSH to your own IP where practical; expose only required ports.
3. Run `bootstrap-vps.sh` with the exact production commit.
4. Transfer the migration bundle over SSH/SCP.
5. Run `restore.sh`.
6. Run `verify.sh`.
7. Start only the dashboard/observation components needed for shadow testing, still paper-only.
8. Compare one or more full market sessions with EC2.
9. Only after explicit approval, perform a final backup and DNS/public-dashboard cutover.
10. Keep EC2 available for rollback until the new VPS is proven.

## Example commands

On the current EC2:

```bash
cd ~/PEREZ-AI-Trading-Bot && bash ops/migration/inventory.sh
cd ~/PEREZ-AI-Trading-Bot && bash ops/migration/backup-current.sh
```

On a fresh VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/perez272/PEREZ-AI-Trading-Bot/main/ops/migration/bootstrap-vps.sh | bash -s -- --commit <KNOWN_GOOD_COMMIT>
```

Then transfer the generated migration bundle and run:

```bash
cd ~/PEREZ-AI-Trading-Bot && bash ops/migration/restore.sh /path/to/PEREZ-MIGRATION-BACKUPS/<timestamp>
bash ops/migration/verify.sh
```

Do not put secrets into shell history, GitHub, issue comments, or this repository.
