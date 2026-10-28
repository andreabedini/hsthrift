#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Write a BUCK file for each C++ dependency, from its getdeps manifest.

    build/buck/generate.py [NAME ...]

The NAMEs are the dependencies to build from source; the default is the
list new_install_deps.sh builds. Each gets build/buck/deps/NAME/BUCK with

  - NAME-src, an http_archive of the source the manifest pins (a tarball
    with its sha256, or for a git manifest the GitHub archive of the
    revision in build/deps/github_hashes),
  - NAME-build, a getdeps_project (project.bzl) building it with the
    manifest's builder (cmake or autoconf) and its CMake defines or
    configure and make arguments, on top of the builds of its dependencies,
  - NAME, a prebuilt_cxx_library of what it installs.

Every other dependency named by a manifest is a system library: a target
of build/buck/deps/system/BUCK carrying only linker flags, as getdeps uses
the distribution's package for it. Which libraries those are is in
SYSTEM_LIBRARIES, and libraries this machine does not have are left out,
the way the CMake builds leave out an optional dependency they do not find.

Manifests are read from build/buck/manifests, then from fbcode_builder's,
and the patchfile of a manifest from build/buck/patches, then from
fbcode_builder's. The patch is copied next to the BUCK file.

Revisions not in github_hashes and the sha256 of GitHub archives are
looked up once and kept in build/buck/deps/sources.json; delete an entry
to look it up again.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FBCODE_BUILDER = os.path.join(ROOT, "build", "fbcode_builder")
MANIFESTS = [os.path.join(HERE, "manifests"), os.path.join(FBCODE_BUILDER, "manifests")]
PATCHES = [os.path.join(HERE, "patches"), os.path.join(FBCODE_BUILDER, "patches")]
GITHUB_HASHES = os.path.join(ROOT, "build", "deps", "github_hashes")
OUT = os.path.join(HERE, "deps")
SOURCES = os.path.join(OUT, "sources.json")
PACKAGE = "//build/buck/deps"

sys.path.insert(0, FBCODE_BUILDER)
from getdeps.manifest import ManifestContext, ManifestParser  # noqa: E402
from getdeps.getdeps_platform import HostType  # noqa: E402

# What new_install_deps.sh builds from source, in order, and liburing.
DEFAULT = ["fmt", "fast_float", "liburing", "folly", "fizz", "wangle", "mvfst", "fbthrift"]

# The defines build.sh adds to every build, except that we build static
# (position-independent) libraries rather than shared ones.
EXTRA_DEFINES = {
    "BUILD_EXAMPLES": "OFF",
    "BUILD_TESTS": "OFF",
    "BOOST_LINK_STATIC": "OFF",
}

# Features of a project to turn off, among the ones its manifest turns on
# by default (as a dependent would ask getdeps with `name = !feature`).
FEATURES_OFF = {
    # The benchmark programs need Google Benchmark, and nothing uses them.
    "fbthrift": ["benchmark"],
}

# Dependencies of our own for a project, added to its manifest's.
EXTRA_DEPENDENCIES = {
    # folly uses liburing whenever <liburing.h> exists (see
    # folly/io/async/Liburing.h), and at build/deps/github_hashes it needs
    # 2.15 or later, which some distributions do not have (Fedora 44 has
    # 2.13). Its manifest does not list it. See build/buck/manifests/liburing.
    # folly also links zlib and bzip2 when CMake finds them (they are in the
    # Libs.private of the libfolly.pc it installs), which the manifest lists
    # on Windows only.
    "folly": ["liburing", "zlib", "bzip2"],
}

# Tools getdeps adds as dependencies; they come from PATH here.
TOOLS = {"cmake", "ninja", "autoconf", "automake", "libtool", "patchelf"}

# The static libraries each source build installs, in link order.
LIBRARIES = {
    "fmt": ["fmt"],
    "fast_float": [],
    "liburing": ["uring"],
    "folly": ["folly"],
    "fizz": ["fizz"],
    "wangle": ["wangle"],
    # mvfst, wangle and folly also install an archive for each component,
    # which the one named here has all of.
    "mvfst": ["mvfst"],
    # Merged (see MERGED_LIBRARIES).
    "fbthrift": ["fbthrift"],
}

# Projects that install an archive for each component and none with all of
# them: the archive to make of them all (merge_archives.py). Linking it needs
# no order among the components.
MERGED_LIBRARIES = {
    "fbthrift": "fbthrift",
}

# The libraries of each system dependency, as the name given to -l.
SYSTEM_LIBRARIES = {
    "bzip2": ["bz2"],
    "boost": [
        "boost_context",
        "boost_filesystem",
        "boost_program_options",
        "boost_regex",
        # Not boost_system: it is header-only, and its libboost_system.so (a
        # linker script, on Fedora) is not something GHC can load for
        # Template Haskell.
        "boost_thread",
    ],
    "double-conversion": ["double-conversion"],
    "gflags": ["gflags"],
    "glog": ["glog"],
    "googletest": [],
    "libaio": ["aio"],
    "libdwarf": ["dwarf"],
    "libevent": ["event"],
    "libiberty": ["iberty"],
    "liboqs": ["oqs"],
    "libsodium": ["sodium"],
    "libunwind": ["unwind"],
    "lz4": ["lz4"],
    "openssl": ["ssl", "crypto"],
    "snappy": ["snappy"],
    "xxhash": ["xxhash"],
    "xz": ["lzma"],
    "zlib": ["z"],
    "zstd": ["zstd"],
}

# Preprocessor flags users of a system dependency need, which its CMake
# package would have given them.
SYSTEM_PREPROCESSOR_FLAGS = {
    # glog 0.7's headers refuse to be included without it.
    "glog": ["-DGLOG_USE_GLOG_EXPORT"],
}


def manifest_context() -> ManifestContext:
    host = HostType()
    return ManifestContext(
        {
            "os": host.ostype,
            "distro": host.distro,
            "distro_vers": host.distrovers,
            "distro_family": host.distro_family,
            "fb": "off",
            "fbsource": "off",
            "test": "off",
        }
    )


def find(dirs: list, name: str, what: str) -> str:
    for d in dirs:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    raise SystemExit(f"{name}: no {what}")


def load_sources() -> dict:
    try:
        with open(SOURCES) as f:
            return json.load(f)
    except FileNotFoundError:
        return {"revisions": {}, "sha256": {}}


def save_sources(sources: dict) -> None:
    with open(SOURCES, "w") as f:
        json.dump(sources, f, indent=2, sort_keys=True)
        f.write("\n")


def git_revision(name: str, repo_url: str, sources: dict) -> str:
    """The revision of github_hashes, or else the one recorded in
    sources.json, or else the current HEAD of the repository."""
    owner = repo_url.rstrip("/").split("/")[-2]
    path = os.path.join(GITHUB_HASHES, owner, name + "-rev.txt")
    if os.path.exists(path):
        with open(path) as f:
            return f.read().split()[-1]
    revs = sources["revisions"]
    if name not in revs:
        out = subprocess.run(
            ["git", "ls-remote", repo_url, "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        revs[name] = out.split()[0]
        print(f"{name}: pinned HEAD of {repo_url} at {revs[name]}", file=sys.stderr)
    return revs[name]


def archive_sha256(url: str, sources: dict) -> str:
    hashes = sources["sha256"]
    if url not in hashes:
        print(f"downloading {url}", file=sys.stderr)
        h = hashlib.sha256()
        with urllib.request.urlopen(url) as r:
            for chunk in iter(lambda: r.read(1 << 20), b""):
                h.update(chunk)
        hashes[url] = h.hexdigest()
    return hashes[url]


def source(name: str, manifest: ManifestParser, ctx, sources: dict):
    """The URL, sha256 and top directory of the source of a manifest."""
    url = manifest.get("download", "url", ctx=ctx)
    if url:
        return url, manifest.get("download", "sha256", ctx=ctx), ""
    repo_url = manifest.get_repo_url(ctx)
    if not repo_url or "github.com" not in repo_url:
        raise SystemExit(f"{name}: neither a download nor a GitHub repository")
    repo_url = repo_url.removesuffix(".git")
    rev = git_revision(name, repo_url, sources)
    url = f"{repo_url}/archive/{rev}.tar.gz"
    return url, archive_sha256(url, sources), f"{repo_url.split('/')[-1]}-{rev}"


def starlark(value, indent: str = "") -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        if not value:
            return "[]"
        inner = indent + "    "
        return "[\n" + "".join(f"{inner}{starlark(v, inner)},\n" for v in value) + indent + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + "    "
        return (
            "{\n"
            + "".join(f"{inner}{json.dumps(k)}: {starlark(v, inner)},\n" for k, v in value.items())
            + indent
            + "}"
        )
    raise TypeError(value)


def call(rule: str, **attrs) -> str:
    lines = [f"{rule}("]
    for k, v in attrs.items():
        if v is None:
            continue
        lines.append(f"    {k} = {starlark(v, '    ')},")
    lines.append(")")
    return "\n".join(lines) + "\n"


HEADER = """\
# @generated by build/buck/generate.py from {what}.
# Do not edit by hand: change the manifest or the generator and run it again.
"""


def generate_source_build(name: str, ctx, from_source: set, sources: dict, system: set) -> str:
    path = find(MANIFESTS, name, "manifest")
    manifest = ManifestParser(path)

    # The manifest's default features are on, as in getdeps; an unset
    # feature counts as off.
    ctx = ctx.copy()
    for feature in manifest.default_features - set(FEATURES_OFF.get(name, [])):
        ctx.set("feature_" + feature, "on")
    builder = manifest.get("build", "builder", ctx=ctx)
    if builder not in ("cmake", "autoconf"):
        raise SystemExit(f"{name}: only cmake and autoconf builds are supported, not {builder}")

    url, sha256, top = source(name, manifest, ctx, sources)
    subdir = os.path.join(top, manifest.get("build", "subdir", "", ctx=ctx)).rstrip("/")
    if subdir == ".":
        subdir = ""

    if builder == "cmake":
        defines = {k: v or "" for k, v in manifest.get_section_as_dict("cmake.defines", ctx).items()}
        defines.update(EXTRA_DEFINES)
    else:
        defines = None

    build_deps, lib_deps = [], []
    for dep in manifest.get_dependencies(ctx) + EXTRA_DEPENDENCIES.get(name, []):
        if dep in TOOLS:
            continue
        if dep in from_source:
            build_deps.append(f"{PACKAGE}/{dep}:{dep}-build")
            lib_deps.append(f"{PACKAGE}/{dep}:{dep}")
        else:
            system.add(dep)
            lib_deps.append(f"{PACKAGE}/system:{dep}")

    libraries = LIBRARIES.get(name, [name])

    patches = []
    patchfile = manifest.get("build", "patchfile", ctx=ctx)
    if patchfile:
        if manifest.get("build", "patchfile_opts", ctx=ctx):
            raise SystemExit(f"{name}: patchfile_opts is not supported")
        shutil.copyfile(find(PATCHES, patchfile, "patch"), os.path.join(OUT, name, patchfile))
        patches.append(patchfile)

    out = [HEADER.format(what=os.path.relpath(path, ROOT))]
    out.append('load("//build/buck:project.bzl", "getdeps_project")\n')
    out.append(call("http_archive", name=f"{name}-src", urls=[url], sha256=sha256))
    out.append(
        call(
            "getdeps_project",
            name=f"{name}-build",
            builder=builder,
            src=f":{name}-src",
            subdir=subdir or None,
            defines=defines,
            configure_args=manifest.get_section_as_args("autoconf.args", ctx) or None,
            build_args=manifest.get_section_as_args("make.build_args", ctx) or None,
            install_args=manifest.get_section_as_args("make.install_args", ctx) or None,
            patches=patches or None,
            job_weight_mib=int(manifest.get("build", "job_weight_mib", ctx=ctx) or 0) or None,
            deps=build_deps,
            libraries=[lib for lib in libraries if lib != MERGED_LIBRARIES.get(name)],
            merged_library=MERGED_LIBRARIES.get(name),
            visibility=["PUBLIC"],
        )
    )

    # One prebuilt_cxx_library per archive, each depending on the next, so
    # that they are linked in the order of `libraries`.
    if not libraries:
        out.append(
            call(
                "prebuilt_cxx_library",
                name=name,
                header_only=True,
                header_dirs=[f":{name}-build[include]"],
                exported_deps=lib_deps,
                visibility=["PUBLIC"],
            )
        )
    for i, lib in enumerate(libraries):
        target = name if i == 0 else f"{name}-{lib}"
        rest = [f":{name}-{libraries[i + 1]}"] if i + 1 < len(libraries) else lib_deps
        out.append(
            call(
                "prebuilt_cxx_library",
                name=target,
                static_lib=f":{name}-build[lib{lib}]",
                static_pic_lib=f":{name}-build[lib{lib}]",
                header_dirs=[f":{name}-build[include]"] if i == 0 else None,
                preferred_linkage="static",
                exported_deps=rest,
                visibility=["PUBLIC"],
            )
        )
    return "\n".join(out)


def have_library(lib: str) -> bool:
    for f in (f"lib{lib}.so", f"lib{lib}.a"):
        found = subprocess.run(
            ["cc", f"-print-file-name={f}"], check=True, capture_output=True, text=True
        ).stdout.strip()
        if os.path.isabs(found):
            return True
    return False


def generate_system(names: set) -> str:
    out = [HEADER.format(what="the system libraries found when it ran")]
    for name in sorted(names):
        libs = SYSTEM_LIBRARIES.get(name)
        if libs is None:
            print(f"warning: no libraries known for system dependency {name}", file=sys.stderr)
            libs = []
        found = [lib for lib in libs if have_library(lib)]
        missing = [lib for lib in libs if lib not in found]
        if missing:
            out.append("# Not found: " + ", ".join("lib" + lib for lib in missing))
        out.append(
            call(
                "prebuilt_cxx_library",
                name=name,
                header_only=True,
                exported_preprocessor_flags=SYSTEM_PREPROCESSOR_FLAGS.get(name),
                exported_linker_flags=["-l" + lib for lib in found],
                visibility=["PUBLIC"],
            )
        )
    return "\n".join(out)


def write(path: str, contents: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(contents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("names", nargs="*", default=DEFAULT)
    args = parser.parse_args()

    ctx = manifest_context()
    sources = load_sources()
    from_source = set(args.names)
    system: set = set()
    try:
        for name in args.names:
            os.makedirs(os.path.join(OUT, name), exist_ok=True)
            write(
                os.path.join(OUT, name, "BUCK"),
                generate_source_build(name, ctx, from_source, sources, system),
            )
    finally:
        os.makedirs(OUT, exist_ok=True)
        save_sources(sources)
    write(os.path.join(OUT, "system", "BUCK"), generate_system(system))


if __name__ == "__main__":
    main()
