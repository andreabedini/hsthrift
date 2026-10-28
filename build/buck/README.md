# Building with Buck2

Work in progress: building hsthrift with [Buck2](https://buck2.build). So
far this covers the C++ dependencies that `new_install_deps.sh` builds with
getdeps; the Haskell packages still build with cabal.

## The C++ dependencies

Each dependency has a BUCK file in `deps/<name>/`, written by
`generate.py` from its getdeps manifest (in `build/fbcode_builder/manifests`,
or in `manifests/` for the ones getdeps does not have). It holds:

- `<name>-src`: an `http_archive` of the pinned source;
- `<name>-build`: a `getdeps_project` (`project.bzl`), one action that runs
  the project's CMake or configure/make build and installs it into a
  prefix;
- `<name>`: a `prebuilt_cxx_library` of what was installed, to depend on.

Libraries are static and position-independent. Dependencies that getdeps
takes from the distribution are in `deps/system/BUCK`, as linker flags.

Build folly and run a program using it:

    buck2 build //build/buck/deps/folly:folly
    buck2 test //build/buck/tests:folly_smoke-test

The builds use the compilers, cmake and ninja in `PATH`, and system
packages for the dependencies in `deps/system/BUCK`. On Fedora these are
`boost-devel`, `glog-devel`, `gflags-devel`, `libevent-devel`,
`libsodium-devel`, `libdwarf-devel`, `libunwind-devel`, `lz4-devel`,
`snappy-devel`, `libzstd-devel`, `xz-devel`, `openssl-devel` and zlib.

## Regenerating

After changing a manifest, a revision in `build/deps/github_hashes` or
`generate.py`:

    python3 build/buck/generate.py

Revisions of git manifests that `github_hashes` does not pin (fizz, wangle,
mvfst) are pinned in `deps/sources.json` the first time, with the sha256 of
every GitHub archive. Delete an entry to update it.

## Differences from getdeps

- liburing is built from source: folly uses it whenever `<liburing.h>`
  exists, and needs 2.15 or later (see `manifests/liburing`).
- Static rather than shared libraries (`build.sh` asks getdeps for shared
  ones).
