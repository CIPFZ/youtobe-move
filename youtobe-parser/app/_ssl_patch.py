"""SSL CA certificate patch.

Import this module FIRST (before any http/https traffic) to replace the
system CA bundle with certifi.  Fixes SSL UNEXPECTED_EOF on machines whose
OpenSSL CA store is outdated (common on older Ubuntu with modern CDN certs).

Usage:
    import app._ssl_patch  # noqa: F401  — must be the very first import
"""

import ssl

import certifi

_ctx = ssl.create_default_context(cafile=certifi.where())
ssl._create_default_https_context = lambda: _ctx
