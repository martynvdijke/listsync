# OIDC and Authelia Authentication

ListSync can require authentication without removing the existing Nginx Proxy
Manager (NPM) / Authelia forward-auth gate.

Two authentication paths are supported:

- **Forward-auth (external access):** NPM asks Authelia to authenticate the
  request and injects `Remote-Email`. ListSync accepts the request when that
  email is in `OIDC_ALLOWED_EMAILS`.
- **Native OIDC (direct/internal access):** when no `Remote-Email` header is
  present, ListSync redirects to Authelia, completes the authorization-code
  flow with PKCE, and stores a sealed session cookie.

With `OIDC_ENABLED=false`, ListSync keeps its previous behaviour: the app is
open to anyone who can reach it.

## Environment

Add these values to the ListSync environment file:

```env
OIDC_ENABLED=true
OIDC_ISSUER=https://authelia.example.com
OIDC_CLIENT_ID=listsync
OIDC_CLIENT_SECRET=replace-with-the-client-secret
OIDC_REDIRECT_URI=https://listsync.example.com/auth/oidc/callback
OIDC_SCOPES=openid email profile groups
OIDC_ALLOWED_EMAILS=you@example.com
OIDC_SESSION_HOURS=8
NUXT_SESSION_PASSWORD=replace-with-at-least-32-random-characters
```

`OIDC_CLIENT_SECRET_FILE` can be used instead of `OIDC_CLIENT_SECRET` when the
secret is mounted as a file.

`OIDC_ALLOWED_EMAILS` accepts a comma, semicolon, or space separated list. Every
authenticated identity must match one of those addresses; there is no
"authenticated users are allowed by default" mode.

`NUXT_SESSION_PASSWORD` seals the login session cookie. Use a random value of at
least 32 characters. If OIDC is enabled and any required value is missing or
invalid, ListSync fails closed at startup.

## Authelia client

Add a confidential client to the Authelia `identity_providers.oidc.clients`
list. The secret below must be an Authelia-compatible PBKDF2 hash; generate one
with `authelia crypto hash generate pbkdf2 --random`.

```yaml
- client_id: listsync
  client_name: ListSync
  client_secret: "$pbkdf2-sha512$..."
  public: false
  authorization_policy: one_factor
  redirect_uris:
    - https://listsync.example.com/auth/oidc/callback
  scopes:
    - openid
    - email
    - profile
    - groups
  grant_types:
    - authorization_code
    - refresh_token
  response_types:
    - code
  response_modes:
    - query
  consent_mode: explicit
  token_endpoint_auth_method: client_secret_basic
  require_pkce: true
  pkce_challenge_method: S256
```

If your Authelia version does not support `require_pkce` or
`pkce_challenge_method`, omit those two keys; ListSync always sends PKCE S256.

## Nginx Proxy Manager

No NPM change is required. Keep the existing Authelia forward-auth includes on
the ListSync proxy host. ListSync trusts `Remote-Email` only when the proxy
injects it.

The ListSync container should not publish ports 3222 or 4222 directly. If it
does, clients that can reach those ports can bypass NPM and spoof the
`Remote-Email` header. Keep the app on the internal Docker network and expose it
through NPM.

## Signing out

ListSync's sign-out button clears its local OIDC session. When the request came
through NPM forward-auth, the Authelia session is shared with other apps and is
not ended by ListSync; the login page explains this. Sign out of Authelia
separately if you want to end the single sign-on session.

## Troubleshooting

- **Startup error about OIDC configuration:** check all required variables,
  especially `NUXT_SESSION_PASSWORD` length and the client secret.
- **Redirect URI mismatch:** `OIDC_REDIRECT_URI` must exactly match the URI
  registered in Authelia.
- **`not_allowed` after login:** add the email returned by Authelia to
  `OIDC_ALLOWED_EMAILS`.
- **External login loops:** confirm NPM still injects `Remote-Email` and that
  the address is allowlisted.
