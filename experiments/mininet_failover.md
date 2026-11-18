# Mininet static-path vs SDN failover experiment

This experiment measures the actual SDN path change. Run it in the Ubuntu/Mininet VM; the automated localhost benchmark does not emulate OpenFlow or link failures.

1. Start OS-Ken and Mininet as described in the README. Start the receiver in the background (`h2 python3 server.py &`).
2. Generate a large payload on the sender host: `h1 dd if=/dev/urandom of=/tmp/failover.bin bs=1M count=32`.
3. **Static baseline:** bring down the alternate path (`link s1 s3 down`), transfer the file, and save the client/controller logs. This forces the one remaining path and provides a static-path throughput baseline.
4. Restore the alternate path (`link s1 s3 up`). Start a new large transfer and, while it is active, run `link s1 s2 down`. Record timestamps for the CLI command, `SDN path changed`, `Installed UDP file-transfer routes`, and the first subsequent client progress/retransmission message.
5. Repeat each condition at least three times. Record file size, elapsed seconds, throughput, retransmissions, SHA-256 match, controller path, and recovery interval. A successful transfer must have matching SHA-256.
6. Restore both links and remove any `tc netem` rules after the experiment.

| Trial | Condition | Size (bytes) | Duration (s) | Throughput (Mbps) | Retransmissions | Recovery (s) | SHA-256 match |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | Static single path | | | | | N/A | |
| 1 | Failover enabled | | | | | | |
| 2 | Static single path | | | | | N/A | |
| 2 | Failover enabled | | | | | | |
| 3 | Static single path | | | | | N/A | |
| 3 | Failover enabled | | | | | | |

Do not fill the table with estimated values. Save real terminal output and flow dumps in `evidence/`.
