"""Authentication and tenant authorization primitives for Nakima Lab.

The Lab app is intentionally separate and unmounted. These dependencies are
fail-closed and require a configured OIDC issuer, audience and JWKS endpoint.
No email, request-body user ID, repository name, or client-supplied tenant ID
is accepted as proof of identity or membership.
"""
