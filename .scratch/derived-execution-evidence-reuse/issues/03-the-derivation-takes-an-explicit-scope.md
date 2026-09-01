# 03 — The derivation takes an explicit scope instead of a request

**What to build:** A named identity for the scope that Derived Execution Evidence
belongs to, so that later tickets have something to key reuse on. Behaviour does
not change at all; this is the prefactor that makes the change after it easy.

Today the derivation is handed a whole request and pulls fields off it
defensively, because four different request shapes reach it and not all of them
carry the same fields. That is workable while the result is thrown away every
time, and unworkable the moment the result has to be retained: "whatever this
request happened to carry" cannot be a key, and a key assembled ad hoc at each
call site would drift between them.

After this ticket the derivation is asked for a scope, and the scope is derived
from a request in exactly one place.

**Blocked by:** 01 (the scope is named using the agreed term).

**Status:** ready-for-agent

- [ ] The scope identity covers the repository scan roots, the complete Database
      identity the request routes to, and the wrapper contract selector
- [ ] The scope is built from a request in one place, not at each call site
- [ ] The derivation is asked for a scope rather than reaching into a request for
      the fields it needs
- [ ] Every existing call site is migrated, including the ones that derive over a
      subset of files chosen by requested program names
- [ ] No behaviour changes: the whole existing suite passes unmodified
- [ ] Two requests differing only in a field that cannot change the derived
      evidence produce the same scope identity
- [ ] Two requests differing in the Database identity, or in the wrapper contract
      selector, produce different scope identities
- [ ] The scope identity is comparable and usable as a key by construction, so a
      later ticket does not have to reshape it
