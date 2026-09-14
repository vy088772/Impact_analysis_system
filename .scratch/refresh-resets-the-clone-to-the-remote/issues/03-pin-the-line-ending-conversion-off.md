# 03 — A clone holds the same bytes whatever host created it

**What to build:** A maintainer moves a clone between a Windows machine and a macOS machine, and git reports no change. Today Git for Windows converts every line ending as it writes a file to disk, macOS git converts nothing, and the two hosts therefore disagree about every file in the clone. That disagreement is what made two clones permanently unrefreshable.

The refresh states its line-ending behaviour in the git command itself, so the host's own git configuration cannot change the result. This follows the existing practice of disabling the credential helper per command.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Every git command that writes the working tree carries an explicit argument turning line-ending conversion off.
- [ ] The clone, the fetch, and the reset all carry it.
- [ ] No clone's own git config records the setting.
- [ ] A clone created with the conversion enabled holds byte-identical content, after one refresh, to a clone created with it disabled.
