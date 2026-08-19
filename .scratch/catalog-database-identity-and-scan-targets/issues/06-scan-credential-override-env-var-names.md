# 06 — The Database Registry Stores Credential Variable Names, Not Values

**What to build:** The file an operator circulates when onboarding a new server carries no secret. A Scan Credential Override registers the *names* of the two environment variables holding it rather than the values; the values live in this repo's environment file. A named variable that cannot be read is a hard error naming the variable, never a silent fall back to the global scan identity — so a forgotten entry announces itself instead of resurfacing later as an unreadable permission failure.

**Blocked by:** None — can start immediately.

**Status:** resolved

- [x] A Scan Credential Override in the Database Registry records two environment variable names in place of the credential value fields.
- [x] Both fields blank means "use the global scan identity", exactly as today. This is the current state of every registered server, so the default path is observably unchanged.
- [x] Exactly one field filled raises. A half-applied edit is an error, not a fallback to the global identity.
- [x] Both fields filled with either named variable unset or empty raises, naming the variable that could not be read. It never falls back to the global identity under any circumstance.
- [x] Both fields filled and both variables readable yields that credential pair for that server, shared by every Database registered under it.
- [x] The values are read from this repo's environment file, loaded through the mechanism the config module already applies at import. No new declared configuration setting is introduced — a variable name is registry data, not a setting.
- [x] Both variable-name fields appear in the environment example file as commented examples, so the mechanism is discoverable without a live secret.
- [x] The scan request contract is unchanged: the caller still sends the resolved credential pair by value. The analysis service requires no change, and its trust boundary — that the scan tool's identity never derives from a scanned application's own configuration — is untouched.
- [x] No credential value, and no credential-variable name, is stored in the System catalog.
- [x] The stale comment beside the registry path setting, which still asserts the file never stores credentials, is rewritten to describe the variable-name rule that now holds.
- [x] Tests cover every resolution branch: both blank; one filled; both filled with a variable unset; both filled with a variable empty; and both filled and readable.
