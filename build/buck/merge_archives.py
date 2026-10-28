#!/usr/bin/env python3
# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Merge the static archives a project installs into one.

    merge_archives.py PREFIX OUTPUT

Run by the getdeps_project rule (project.bzl) for a project that installs
an archive for each of its components and none with all of them (fbthrift).
Linking the one archive needs no order among the components: the linker
searches an archive until nothing more of it is needed. GNU ar's MRI
scripts keep members of the same name from different archives.
"""

import glob
import os
import subprocess
import sys


def main() -> int:
    prefix, output = sys.argv[1:]
    archives = sorted(glob.glob(os.path.join(prefix, "lib", "lib*.a")))
    if not archives:
        print(f"no archives in {prefix}/lib", file=sys.stderr)
        return 1
    output = os.path.abspath(output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    script = "\n".join(
        [f"create {output}"] + [f"addlib {os.path.abspath(a)}" for a in archives] + ["save", "end", ""]
    )
    return subprocess.run(["ar", "-M"], input=script, text=True).returncode


if __name__ == "__main__":
    sys.exit(main())
