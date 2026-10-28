#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Build one project and install it into a prefix.

Run by the getdeps_project rule (project.bzl) as a single Buck2 action.
Build tools want absolute paths, and Buck2 gives us paths relative to the
project root, so everything is made absolute here.

  cmake     cmake configure, build and install, out of the source tree.
  autoconf  ./configure --prefix=..., make, make install, in a copy of the
            source tree (they build in place, and the sources are an input
            of the action that must not change).

Patches are applied with `patch -p1` in a copy of the source tree, as
getdeps applies a manifest's patchfile.

As in getdeps, the number of parallel jobs is the memory available divided
by what one job of the project takes (--job-weight-mib, the manifest's
job_weight_mib), and at most the number of CPUs; here only half the memory
available is counted, to leave room for everything else on the machine. And
as in getdeps, each process of the build is limited to ten times that much
virtual memory, so that a runaway compiler fails rather than take the
machine down with it.
"""

import argparse
import os
import resource
import shutil
import subprocess
import sys
import tempfile


def run(cmd, cwd=None):
    print("+ " + " ".join(cmd), file=sys.stderr, flush=True)
    subprocess.run(cmd, check=True, cwd=cwd)


def limit_memory(job_weight_mib):
    limit = job_weight_mib * 10 * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def jobs(job_weight_mib):
    cpus = os.cpu_count() or 1
    try:
        with open("/proc/meminfo") as f:
            meminfo = dict(line.split(":", 1) for line in f)
        available_mib = int(meminfo["MemAvailable"].split()[0]) // 1024
    except (OSError, KeyError, ValueError):
        return 1
    return max(1, min(cpus, available_mib // 2 // job_weight_mib))


def copy_source(src, scratch, patches):
    dst = os.path.join(tempfile.mkdtemp(prefix="src-", dir=scratch), "src")
    shutil.copytree(src, dst, symlinks=True)
    for patch in patches:
        run(["patch", "-p1", "--forward", "-i", patch], cwd=dst)
    return dst


def cmake(args, src, prefix, scratch):
    build_dir = tempfile.mkdtemp(prefix="cmake-", dir=scratch)
    defines = [
        "CMAKE_INSTALL_PREFIX=" + prefix,
        "CMAKE_PREFIX_PATH=" + ";".join(args.dep_prefix),
        # Only look for packages in our prefixes and the system, never in
        # the user's package registry.
        "CMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
    ] + args.define
    run(["cmake", "-S", src, "-B", build_dir, "-G", "Ninja"] + ["-D" + d for d in defines])
    run(["cmake", "--build", build_dir, "-j", str(jobs(args.job_weight_mib))])
    run(["cmake", "--install", build_dir])


def autoconf(args, src, prefix, scratch):
    build_dir = src
    run(
        [
            "./configure",
            "--prefix=" + prefix,
            "--libdir=" + os.path.join(prefix, "lib"),
            "--includedir=" + os.path.join(prefix, "include"),
        ]
        + args.configure_arg,
        cwd=build_dir,
    )
    run(["make", "-j{}".format(jobs(args.job_weight_mib))] + args.build_arg, cwd=build_dir)
    run(["make"] + (args.install_arg or ["install"]), cwd=build_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--builder", choices=["cmake", "autoconf"], required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--subdir", default="")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--dep-prefix", action="append", default=[])
    parser.add_argument("--define", action="append", default=[])
    parser.add_argument("--configure-arg", action="append", default=[])
    parser.add_argument("--build-arg", action="append", default=[])
    parser.add_argument("--install-arg", action="append", default=[])
    parser.add_argument("--patch", action="append", default=[])
    parser.add_argument("--job-weight-mib", type=int, default=1536)
    args = parser.parse_args()

    src = os.path.abspath(os.path.join(args.src, args.subdir))
    prefix = os.path.abspath(args.prefix)
    args.dep_prefix = [os.path.abspath(p) for p in args.dep_prefix]

    scratch = os.environ.get("BUCK_SCRATCH_PATH")
    if scratch:
        scratch = os.path.abspath(scratch)
        os.makedirs(scratch, exist_ok=True)
        # Temporary files of the build go there too, not to /tmp.
        os.environ["TMPDIR"] = scratch

    # Inherited by everything the build runs.
    limit_memory(args.job_weight_mib)

    builders = {"cmake": cmake, "autoconf": autoconf}
    try:
        if args.patch or args.builder == "autoconf":
            src = copy_source(src, scratch, [os.path.abspath(p) for p in args.patch])
        builders[args.builder](args, src, prefix, scratch)
    except subprocess.CalledProcessError as e:
        return e.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
