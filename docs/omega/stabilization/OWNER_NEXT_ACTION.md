# Owner Next Action (one step, on the phone)

Re-run the verification at the fixed commit. In Termux, paste one line at a time:

```bash
C=3a8ca868ccb609dae4368e68db8d8e94941b05c6
F="$HOME/android-verify-3a8ca86.sh"
curl -fL --retry 3 -o "$F" "https://raw.githubusercontent.com/jamdav688y-source/forgeworld-runtime/$C/scripts/android-verify.sh"
echo "ff4309de8df7679305f66903d3ba5effecb95416fb367091aa1dfa3a6088fe83  $F" | sha256sum -c -
bash "$F" "$C"
```

* The `sha256sum` line must print `OK`. If it prints `FAILED`, stop.
* The script reuses your existing `~/omega-verify` checkout; it never touches files outside it. If it says `Local changes … refusing`, run `rm -rf ~/omega-verify/forgeworld-runtime` and repeat the last line.
* It takes about 1 minute and ends with **one** verdict:
  * `VERDICT: PASS` with `TESTS: 100 passed, 1 skipped` (the skip is the optional Ollama test). Gate 4 is satisfied. Reply "PASS" plus the `EVIDENCE:` line.
  * `VERDICT: FAIL`: reply with the four lines `VERDICT`, `NEXT`, `TESTS`, `EVIDENCE`. The evidence folder holds the full log; nothing needs interpreting.
  * `VERDICT: BLOCKED`: run the command it prints, then repeat the last line.
