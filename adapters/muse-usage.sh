#!/usr/bin/env bash
# Muse Code subscription usage -> the adapter's usage JSON.
#
#   {"provider":"meta","meters":[
#      {"name":"window","used":0,"resets_at":1788646320,"window_secs":18000},
#      {"name":"weekly","used":72,"resets_at":1788739200,"window_secs":604800}],
#    "error":null}
#
# Mechanism (verified against Muse Code 1.0.2/1.0.3, provider meta): Meta has no usage REST
# endpoint -- every /muse-code/{subscription,usage,quota,entitlement,billing,limits} is a 404.
# The only carrier of the snapshot is a terminal SSE frame on the Model API response stream:
#
#   POST https://api.meta.ai/v1/responses   (stream:true)
#   event: response.subscription_usage
#   data: {"subscription":{"tier":"...","weekly":{"resets_at":..,"used_percent":..},
#                          "window":{"resets_at":..,"used_percent":..,"window_duration_mins":300}}}
#
# which is exactly what the TUI's /usage "Subscription" block renders.  So this makes the
# smallest turn the API accepts (1-token input, max_output_tokens 16 -- the documented floor),
# reads the frame, and drops the connection.  It costs one model request per uncached probe;
# cache the result rather than polling it in a loop.
#
# Credentials, per OS:
#   * META_API_KEY, when set (Muse honours it over the account login).
#   * $XDG_CONFIG_HOME/muse/auth.json -> providers.meta.api_key.  Muse's file credential
#     backend, which is what Linux gets: the minted key sits there in plaintext.
#   * macOS keeps the key in the login Keychain (service ai.meta.dev.credentials), and its ACL
#     is muse-only -- `security find-generic-password -w` opens a blocking GUI prompt, so it is
#     useless headless.  Instead muse itself is asked for it: started with --base-url pointed at
#     a loopback listener and a throwaway XDG_DATA_HOME (a cold model-catalog cache forces the
#     fetch), it issues GET /muse-code/models with `Authorization: Bearer <key>` before it does
#     anything else, and exits on its own with no tty.  The key is held in memory only.
#
# The model and reasoning effort come from config.toml. The Python supervisor enforces
# one 45s total budget (including cleanup); AGENTKIT_MUSE_USAGE_TIMEOUT may shorten it.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
exec python3 "$here/../agentkit/muse_usage.py"
