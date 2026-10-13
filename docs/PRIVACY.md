# Privacy Policy — Vara MCP Server

**Last updated:** October 12, 2026

## Scope

This policy describes data handled by the Vara MCP Server at `https://vara-mcp-server.vercel.app/api/mcp`. It covers requests sent to its MCP tools and the scan results the service creates. The service is operated through the public source repository at https://github.com/kushkillerjsixx66/vara-mcp-server.

## Information processed

When a client calls a tool, the service processes the arguments in that request. Depending on the tool, these may include search keywords, scan configuration, labels, scan identifiers, and filters. A scan can retrieve information from external feeds and websites configured by the Vara pipeline. If the caller enables the Firecrawl integration and it is configured, scan activity may also involve that external service.

Scan results can contain retrieved source URLs, titles, signal content, timestamps, configuration metadata, and derived Vara/Veil/Vault state. Do not submit passwords, access tokens, confidential material, or personal information that you do not have permission to process.

## Storage and retention

The service uses a writable runtime data directory (typically `/tmp` on Vercel) for scan files and state. This runtime storage is temporary and may disappear when a serverless instance is recycled.

If the deployment is configured with `GITHUB_TOKEN` or `GH_TOKEN` and the durable backend is enabled, the service also writes scan reports, an index, and selected state files to the configured GitHub repository and archive branch (by default, `kushkillerjsixx66/vara-mcp-server` and `vara-archive`). These archived records remain until removed from that repository; the service does not currently implement an automatic retention period. Repository visibility and GitHub's own retention and backup behavior affect who can access archived records and how long copies may persist. If the repository is public, archived records may be publicly accessible.

## Service providers and logs

The service runs on Vercel. Vercel may process connection metadata and platform logs under its own policies. When durable GitHub archiving is enabled, the service communicates with the GitHub API to read and write archive files. Scan execution can contact the external source providers configured by the scan pipeline. Those providers process requests under their own terms and privacy policies.

## Use, sharing, and sale

The service does not provide user accounts or payment processing. It does not intentionally sell submitted tool arguments or scan results. Information may be processed by the infrastructure and external providers described above, and archived results may be visible according to repository access settings. No claim is made that third-party infrastructure logs are immediately deleted or controlled by this service.

## Security and user responsibility

Access to the MCP endpoint is currently anonymous unless deployment configuration changes. Treat tool arguments and results accordingly. Do not use this service to store secrets or sensitive personal data. The operator cannot guarantee uninterrupted availability or prevent access to data deliberately written to a publicly accessible repository.

## Changes and contact

This policy may be updated when data handling changes. For questions or privacy-related requests, contact the maintainer through the repository: https://github.com/kushkillerjsixx66/vara-mcp-server/issues. Do not post sensitive personal information in a public issue.
