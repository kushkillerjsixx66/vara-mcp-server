# Deployment

Production runs the canonical Vara architecture (Fork 2 port, PR #14,
landed via PR #15 on 2026-10-23) with the durable archive on Vercel Blob
(`VARA_DURABLE_BACKEND=blob`).

This file's creation doubles as the git-triggered deployment used to
verify that a push-built production deployment picks up the Blob token
environment — the API-created deployments built the same evening did
not demonstrably take production traffic.
