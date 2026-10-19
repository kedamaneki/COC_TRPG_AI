# External Source Manifest

The accepted source is external and immutable.

- Session: `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`
- Root variable: `CORBITT_V13_SOURCE_ROOT`
- Control root variable: `CORBITT_V13_CONTROL_ROOT`
- Expected files: `373`
- Aggregate SHA-256: `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`
- Aggregate rule: SHA-256 of sorted `relative POSIX path + NUL + file SHA-256 + LF`
- Machine-readable contract: `manifests/PORTABILITY_EXTERNAL_SOURCE.json`

Copy the complete Raw directory and its control directory to the second PC, set both variables,
then run `python tools/verify_portability.py`. Do not regenerate checkpoints, segments, or logs.
