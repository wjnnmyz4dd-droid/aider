# 01 — MetaEditor Compile Checklist

Target file: `mt5/PhantomBridgeEA.mq5` (`#property version "1.01"`)
Companion template: `mt5/PhantomBridgeEA.set`

This checklist has never been executed against a real MetaEditor in this
project — see `PHANTOM_BRIDGE_EA_PHASE1_VALIDATION_PACKAGE.md` for why.
**Everything in this file requires a real Windows + MetaEditor
installation to complete.**

## Build configuration

- [ ] Copy `mt5/PhantomBridgeEA.mq5` into the terminal's
      `MQL5/Experts/` directory (e.g.
      `%APPDATA%\MetaQuotes\Terminal\<hash>\MQL5\Experts\Phantom\`).
- [ ] Open the file in MetaEditor from that location (not a scratch
      copy) so `#include <Trade/Trade.mqh>` resolves against the
      standard library shipped with the terminal.
- [ ] Compile with the default build target (`Release`); this EA has no
      platform-specific (`x86`/`x64`) conditional code, so a single
      standard compile is sufficient.

## Compiler version

- [ ] Record the exact MetaEditor build number shown in
      **Help -> About** (format: `MetaEditor build NNNN`).
- [ ] Record the MT5 terminal build number the EA will run against
      (**Help -> About** in the terminal). MQL5 language features used
      here (`CTrade`, `ENUM_SYMBOL_TRADE_MODE`,
      `SYMBOL_TRADE_STOPS_LEVEL`, `%I64u` format specifier) have been
      stable for many years, but record the build number anyway so a
      future defect can be correlated to a specific compiler/terminal
      version.

## Zero errors required

- [ ] Press F7 (Compile) and open the **Errors** tab.
- [ ] Confirm **0 errors**. Any error is a hard blocker — do not
      attach this EA to any chart, demo or otherwise, until the error
      count is zero.
- [ ] If errors appear, capture the full text of every one (file,
      line, column, message) before making any change — this is the
      only condition under which code may be modified per the
      governing instructions for this package.

## Zero warnings preferred

- [ ] Open the **Errors** tab's warning filter and review every
      warning. Zero is preferred; each surviving warning must be
      individually understood and accepted, not ignored by default.
- [ ] Known candidate warnings to watch for (not confirmed present —
      only a compiler run can confirm): implicit type conversions
      around `(int)MagicNumber` / `(ulong)MaxSlippagePoints` casts,
      or an "unused variable" warning if a symbol/account function is
      deprecated in the installed terminal build.

## Expected `.ex5` output

- [ ] Confirm `PhantomBridgeEA.ex5` is produced in the same
      `MQL5/Experts/` subfolder as the source `.mq5` file.
- [ ] Confirm the `.ex5` file's timestamp is newer than the `.mq5`
      source file's timestamp (proves it's a fresh compile, not a
      stale artifact from a prior run).
- [ ] Record the `.ex5` file size for the sign-off template.

## Required include files

- [ ] `<Trade/Trade.mqh>` — ships with every standard MT5 installation
      under `MQL5/Include/Trade/Trade.mqh`. No other include is used
      by this file. Confirm this file exists in the installation
      before compiling; if it is missing, the installation itself is
      incomplete/corrupted, not a defect in this EA.

## Required libraries

- [ ] None beyond the standard `CTrade` class pulled in by
      `<Trade/Trade.mqh>`. This EA links no `.ex5`/`.mqh` libraries of
      its own and no DLLs. If MetaEditor's linker reports any
      additional dependency, treat that as a build-environment problem
      to investigate, not something to silence.

## Expected compile artifacts

- [ ] `PhantomBridgeEA.ex5` (the compiled expert, required)
- [ ] Compiler log (MetaEditor's Toolbox "Errors" tab output) — save a
      copy (screenshot or copy-paste into the sign-off template)
      showing the final "0 errors, N warnings" summary line with a
      timestamp.
- [ ] No `.ex5` should be produced if the error count is nonzero —
      MetaEditor will refuse in that case; do not hand-craft or reuse
      an old `.ex5` as a substitute.

## If compilation fails

Per the governing rule for this package ("do not change code unless
an actual compile or demo test discovers a defect"): capture every
error verbatim, then fix **only** what the compiler names as an error.
Do not use a compile failure as license to refactor, add features, or
touch any file outside `mt5/PhantomBridgeEA.mq5`. After any fix, the
entire compile checklist above must be re-run from a clean state.
