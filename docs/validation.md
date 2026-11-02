# Validation record

Local validation completed on 2026-11-02 using Python 3.12.13.

| Check | Result |
|---|---|
| Offline pytest suite | 124 passed; external sockets disabled; warnings treated as errors |
| Runtime line coverage | 95.21%; 90% minimum enforced |
| PostgreSQL 16 integration | 2 passed against isolated temporary databases over a private Unix socket |
| Strict package type checking | Zero errors, warnings or notes |
| Ruff lint and formatting | Passed |
| Requirement evidence | All 46 completed rules have collected dedicated test markers |
| Wheel and source distribution | Built successfully |
| Twine metadata validation | Both artifacts passed strict checks |
| Offline installed-wheel smoke | Passed with a prepared production-dependency wheelhouse, isolated interpreter and no editable-checkout import |
| Negative assertion check | Deliberately wrong construction-validation count failed; original file restored and targeted test passed |

Alembic revisions are validated by schema parity, data-preserving upgrades,
downgrade/upgrade round trips, application-autogenerate protection and PostgreSQL
SQL generation. They are excluded from the runtime line-coverage denominator.
The installed-wheel smoke exercises packaged revision discovery, upgrades and
SQLite CRUD, and checks that py.typed is included.

CI is configured for Python 3.12/3.13 and PostgreSQL 16. The review fixes were
validated locally; remote results for the updated PR must be checked separately.
Real Brevo/Resend requests are mocked. Live keys, verified sender
settings and a controlled recipient are still required for manual provider checks.
No real messages were sent, no application database was migrated/deleted, and no
package publishing was performed during validation. Review fixes remain on the same
feature branch and PR. The temporary PostgreSQL cluster was stopped afterward.

The current packaged migration head is nk_0003. Run the application's Alembic
upgrade heads before startup. Historical unversioned draft databases require the
explicit conversion/replacement process documented in docs/README.md; startup
will not silently stamp or change them.

See [testing guide](testing.md) for reproducible commands and the separate
PostgreSQL test configuration.
