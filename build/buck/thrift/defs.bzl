"""Haskell generated from Thrift files by thrift-compiler, as the Makefile's
`thrift-hs` does, for the directories of the plan's packages given to
plan.bxl with --generated."""

def thrift_hs(name: str, package: str, files: list[str], options: list[str] = [], **kwargs):
    """A gen-hs2 directory: what `thrift-compiler --hs` makes of the files.

    Args:
      name: the name of the target
      package: the cabal_package target of the plan the files are in
      files: the Thrift files, relative to the package, each compiled on
        its own as the Makefile does it from the package's directory
      options: more options of thrift-compiler, for every file
    """
    compile = [
        "$(exe //:exe-thrift-compiler) --hs {} $(location {})/{} -o $TMP".format(" ".join(options), package, f)
        for f in files
    ]
    native.genrule(
        name = name,
        out = "gen-hs2",
        cmd = " && ".join(compile + ["mv $TMP/gen-hs2 $OUT"]),
        **kwargs
    )
