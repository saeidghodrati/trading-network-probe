# Recovery

This package can restore the current paper-trading system on another Ubuntu server.

## Restore

1. Copy this folder to the new server.
2. Become root.
3. Run:

```bash
cd /path/to/trading-bot
bash restore-server.sh
```

The script creates the `trader` user if needed, installs the application under:

```text
/home/trader/trading-bot
```

and enables:

```text
wallex-monitor.service
wallex-paper-trader.timer
```

## Restore state

If a backup contains the `data` directory, keep it inside this folder before running the restore script.

Important state files:

```text
data/paper.db
data/monitor.jsonl
```

No exchange API keys or secrets are included in GitHub.
