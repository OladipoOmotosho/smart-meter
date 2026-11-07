# Pinned development toolchain

Task 2.1 records the versions used to prepare the reproducible project setup. Tasks 2.2–2.4 add the commands, isolated configuration and check harness; the clean-checkout gate remains Task 2.5.

| Component | Pin | Source |
| --- | --- | --- |
| Python | 3.12.x (`.python-version`) | Python 3.12 interpreter; create a fresh project virtual environment |
| Python direct requirements | `pipeline/requirements.txt` | Exact versions for packages this prototype uses |
| Python complete graph | `pipeline/requirements.lock` | Generated with pip-tools 7.6.2 on Python 3.12; exact transitive versions |
| Foundry (`forge`, `anvil`, `cast`) | stable `v1.9.0`, Git commit `6056c5845d34205a83cf7108042adb137325c9df` | [Foundry release](https://github.com/foundry-rs/foundry/releases/tag/v1.9.0) |
| Solidity compiler | `0.8.24` | `contracts/foundry.toml` (`solc_version`) |
| OpenZeppelin Contracts | `v5.4.0`, Git commit `c64a1edb67b6e3f4a15cca8909c9482ad33a02b0` | [release](https://github.com/OpenZeppelin/openzeppelin-contracts/releases/tag/v5.4.0) |
| forge-std | `v1.16.2`, Git commit `bf647bd6046f2f7da30d0c2bf435e5c76a780c1b` | [release](https://github.com/foundry-rs/forge-std/releases/tag/v1.16.2) |

The Git commit IDs above were verified against upstream release tags on 2026-11-06. Foundry v1.9.0 was installed in `~/.local/bin` on macOS arm64 from the [official release archive](https://github.com/foundry-rs/foundry/releases/download/v1.9.0/foundry_v1.9.0_darwin_arm64.tar.gz), verified with SHA-256 `38f9af72b266c38ce2e4dfc659ae9cbd1f78c01b34738a76b6c4cb9610579426`. Both `anvil --version` and `forge --version` report commit `6056c5845d34205a83cf7108042adb137325c9df`; an owned disposable Anvil process returned JSON-RPC chain ID `0x7a69` and was stopped. On 2026-11-06, `scripts/install_contract_libs.sh` installed both libraries under ignored `contracts/lib/` and verified their exact commits. `make build` compiled 28 files successfully with solc 0.8.24; the remaining mutability warnings come from unfinished registry methods. `make test-contracts` reached all seven scaffold tests, which are still explicitly skipped, so its report gate correctly fails.

## Installation method

Use a Python 3.12 interpreter to create `.venv`, then install with `python -m pip install -r pipeline/requirements.lock`. The lock file carries exact versions for the full transitive graph; it does not contain artifact hashes, so the package index remains part of the trust boundary. `requirements.txt` is the reviewed direct-dependency input. `pandas` and `matplotlib` were removed because the inspected prototype imports neither. SQLite, CSV, decimal arithmetic and SHA-256 come from Python's standard library.

Install Foundry **v1.9.0**, then verify `forge --version` and `anvil --version` before using it. `make install` runs `scripts/install_contract_libs.sh`, which checks out each Solidity library in `contracts/lib/` at the exact commit above and verifies `git -C contracts/lib/<name> rev-parse HEAD`. The directory is Git ignored. Do not use a floating branch or `forge install` without a revision. The source locations match `foundry.toml` remappings. A compiler download may occur on the first `forge build`; `foundry.toml` fixes the compiler version.

## Updating pins

Update one component at a time on a task branch. Change a direct Python pin in `requirements.txt`, regenerate `requirements.lock` with pip-tools 7.6.2 using Python 3.12 (`pip-compile --output-file=pipeline/requirements.lock pipeline/requirements.txt`), install it in a fresh environment, then run the relevant test gates. For Foundry or Solidity libraries, verify the release tag and exact commit, update this document, build the contract and run its required tests. Record the new versions, generated lock diff and test results in the task evidence before committing. No dependency should change just because a newer version exists.
