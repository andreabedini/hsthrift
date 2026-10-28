# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

"""Build a project in one action, the way getdeps does.

`getdeps_project` builds the project with its `builder` (cmake or autoconf,
see build_project.py) and installs it into a prefix, the rule's default
output (a directory). The prefixes of its `deps` are on `CMAKE_PREFIX_PATH`,
transitively. Subtargets give the parts of the prefix that a
`prebuilt_cxx_library` needs: `[include]`, and `[lib<name>]` for each name
in `libraries` (the static archive `lib/lib<name>.a`). `patches` are
applied to the sources first, with `patch -p1`.

Libraries are static and position-independent. The action uses the
compilers and build tools found in PATH, and the system packages the
project's build finds, so it is local only.
"""

load("@prelude//python_bootstrap:python_bootstrap.bzl", "PythonBootstrapToolchainInfo")

GetdepsPrefixInfo = provider(fields = {
    # The prefixes of this project and of every project it depends on.
    "prefixes": provider_field(list[Artifact]),
})

# What build.sh does to every getdeps build. folly needs the same
# architecture flags when built and when used (see
# folly/container/detail/F14IntrinsicsAvailability.h).
_HOST_CXXFLAGS = select({
    "config//cpu:x86_64": ["-march=haswell"],
    "DEFAULT": [],
})

_HOST_DEFINES = select({
    "config//cpu:arm64": {"CMAKE_LIBRARY_ARCHITECTURE": "aarch64"},
    "DEFAULT": {},
})

def _getdeps_project_impl(ctx: AnalysisContext) -> list[Provider]:
    prefix = ctx.actions.declare_output("prefix", dir = True)

    dep_prefixes = []
    for dep in ctx.attrs.deps:
        for p in dep[GetdepsPrefixInfo].prefixes:
            if p not in dep_prefixes:
                dep_prefixes.append(p)

    defines = {
        "BUILD_SHARED_LIBS": "OFF",
        "CMAKE_BUILD_TYPE": "RelWithDebInfo",
        "CMAKE_INSTALL_LIBDIR": "lib",
        "CMAKE_POSITION_INDEPENDENT_CODE": "ON",
    } | ctx.attrs.host_defines | ctx.attrs.defines

    cmd = cmd_args(
        ctx.attrs._python[PythonBootstrapToolchainInfo].interpreter,
        ctx.attrs._script,
        "--builder",
        ctx.attrs.builder,
        "--src",
        ctx.attrs.src,
        "--subdir",
        ctx.attrs.subdir,
        "--prefix",
        prefix.as_output(),
        [cmd_args("--dep-prefix", p) for p in dep_prefixes],
        [cmd_args("--define", "{}={}".format(k, v)) for k, v in defines.items()],
        [cmd_args("--configure-arg=" + a) for a in ctx.attrs.configure_args],
        [cmd_args("--build-arg=" + a) for a in ctx.attrs.build_args],
        [cmd_args("--install-arg=" + a) for a in ctx.attrs.install_args],
        [cmd_args("--patch", p) for p in ctx.attrs.patches],
    )
    ctx.actions.run(
        cmd,
        env = {
            "CFLAGS": " ".join(["-O2", "-g", "-fPIC"] + ctx.attrs.host_cxxflags),
            "CXXFLAGS": " ".join(ctx.attrs.host_cxxflags),
        },
        category = ctx.attrs.builder,
        local_only = True,
    )

    sub_targets = {"include": [DefaultInfo(default_output = prefix.project("include"))]}
    for lib in ctx.attrs.libraries:
        sub_targets["lib" + lib] = [DefaultInfo(default_output = prefix.project("lib/lib{}.a".format(lib)))]

    return [
        DefaultInfo(default_output = prefix, sub_targets = sub_targets),
        GetdepsPrefixInfo(prefixes = dep_prefixes + [prefix]),
    ]

_getdeps_project = rule(
    impl = _getdeps_project_impl,
    attrs = {
        "build_args": attrs.list(attrs.string(), default = []),
        "builder": attrs.enum(["cmake", "autoconf"]),
        "configure_args": attrs.list(attrs.string(), default = []),
        "defines": attrs.dict(attrs.string(), attrs.string(), sorted = False, default = {}),
        "deps": attrs.list(attrs.dep(providers = [GetdepsPrefixInfo]), default = []),
        "host_cxxflags": attrs.list(attrs.string(), default = []),
        "host_defines": attrs.dict(attrs.string(), attrs.string(), sorted = False, default = {}),
        "install_args": attrs.list(attrs.string(), default = []),
        "libraries": attrs.list(attrs.string(), default = []),
        "patches": attrs.list(attrs.source(), default = []),
        "src": attrs.source(allow_directory = True),
        "subdir": attrs.string(default = ""),
        "_python": attrs.toolchain_dep(default = "toolchains//:python_bootstrap", providers = [PythonBootstrapToolchainInfo]),
        "_script": attrs.source(default = "root//build/buck:build_project.py"),
    },
)

def getdeps_project(**kwargs):
    _getdeps_project(
        host_cxxflags = _HOST_CXXFLAGS,
        host_defines = _HOST_DEFINES,
        **kwargs
    )
