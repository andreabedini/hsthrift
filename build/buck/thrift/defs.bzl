"""Code generated from Thrift files, as the Makefile's `thrift-hs` and
`thrift-cpp` make it, for the directories of the plan's packages given to
plan.bxl with --generated."""

_ANNOTATION = "//thrift:annotation"
_FBTHRIFT = "//build/buck/deps/fbthrift:fbthrift-build"

def thrift_file(package: str, path: str, options: list[str] = []) -> struct:
    """A Thrift file to compile.

    Args:
      package: the cabal_package target of the plan the file is in
      path: the file, relative to the package: the compiler takes it, and
        what it includes, from a copy of the package's directory, where
        "thrift/annotation" is the annotations, as the Makefile runs it in
        the package's directory
      options: more options of the compiler
    """
    return struct(package = package, path = path, options = options)

def _compile(name: str, out: str, files: list[struct], setup: list[str], command: str, annotation: str | None = _ANNOTATION, **kwargs):
    """A genrule running `command` for each file.

    The command is formatted with `dir` (the copy of the file's package),
    `options` and `file`; the output directory is $T. `annotation`, if not
    None, is copied to thrift/annotation in each copy."""

    # Each package once, in a directory of its own.
    packages = {p: "$TMP/src{}".format(i) for i, p in enumerate({f.package: None for f in files}.keys())}
    cmd = ["set -e", "T=`realpath $TMP`/out", "mkdir -p $T"] + setup
    for package, dir in packages.items():
        cmd.extend([
            "mkdir -p {}/thrift".format(dir),
            "cp -RL $(location {})/. {}/".format(package, dir),
        ])
        if annotation:
            cmd.append("cp -RLf $(location {})/annotation {}/thrift/".format(annotation, dir))
    for f in files:
        cmd.append(command.format(dir = packages[f.package], options = " ".join(f.options), file = f.path))
    cmd.append("mv $T/{} $OUT".format(out))
    native.genrule(name = name, out = out, cmd = "\n".join(cmd), **kwargs)

def thrift_hs(name: str, files: list[struct], compiler: str = "//:exe-thrift-compiler", annotation: str | None = _ANNOTATION, **kwargs):
    """A gen-hs2 directory: what `thrift-compiler --hs` makes of the files.

    Each file is compiled on its own.

    Args:
      name: the name of the target
      files: the files, made with thrift_file
      compiler: the thrift-compiler executable, of the plan's (a label is
        relative to the BUCK file using this)
      annotation: the annotations to put at thrift/annotation in the copy of
        each package (see thrift_file); None for the package's own
      **kwargs: more attributes of the genrule
    """

    # NOTE: not from the package's directory: $(exe_target) is a command
    # whose environment has paths relative to this one. The compiler is
    # built for the target platform, as the packages are, so that what it
    # links (fb-util, folly) is not built twice.
    _compile(name, "gen-hs2", files, [], "$(exe_target " + compiler + ") --hs -I {dir} {options} {file} -o $T", annotation = annotation, **kwargs)

def thrift_cpp(name: str, files: list[struct], **kwargs):
    """A gen-cpp2 directory: what `thrift1 --gen mstch_cpp2` makes of the files.

    Each file is compiled on its own. thrift1 is the one of the fbthrift
    that the packages link: built for them, not for the tools, so that
    fbthrift is not built twice.

    Args:
      name: the name of the target
      files: the files, made with thrift_file
      **kwargs: more attributes of the genrule
    """
    _compile(
        name,
        "gen-cpp2",
        files,
        ["F=`realpath $(location {})`".format(_FBTHRIFT)],
        "(cd {dir} && $F/bin/thrift1 -I $F/include -I . --gen mstch_cpp2 {options} -o $T {file})",
        **kwargs
    )
