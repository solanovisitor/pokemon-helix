# Security

Security review currently covers the public host demo, local lab service,
bootstrap, and CI on `main`. There are no supported binary releases.

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/solanovisitor/pokemon-helix/security/advisories/new).
Include the affected commit, synthetic reproduction, expected impact, and a
suggested fix if available. If that form is unavailable, open a content-free
issue asking the maintainer to enable private reporting; do not disclose the flaw.
There is no response-time guarantee.

Never upload credentials, real saves, savestates, human genetic data, personal
profiles, private authoring content, or conversations to an issue or PR. Remove
machine paths and account data from diagnostics. Use fictional fixtures.

The lab service is for device-local loopback only. It has no remote
authentication, shared ownership authority, or internet-facing deployment mode.
Hashes check consistency, not identity or trust. Do not expose its port to a LAN.
Paid inference and telemetry are not enabled by this kickstart.
