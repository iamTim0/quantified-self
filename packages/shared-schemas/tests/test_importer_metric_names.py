"""No importer may write a metric name the registry does not define.

This reads the transformer sources rather than importing them, on purpose. Each importer
lives in its own virtualenv (AGENTS.md: isolated `pyproject.toml` per service), so a test
that imported all eight would only ever run under whichever environment happened to have
them all — which is none of them. Scanning the source has the further advantage of
catching a name that only appears on a branch no fixture exercises.

The failure this prevents is the one that made the registry necessary: every importer
inventing its own vocabulary, with nothing in the repository able to say so.

It used to scan with one regular expression for ``metric_type: "x"``, and that covered
three of the eight importers. The other five name their metrics in shapes the pattern
could not see — a provider-name-to-canonical-key map in Apple Health and weather,
positional ``_Mapping("whoop_strain", …)`` tuples in WHOOP, module constants built by
``canonical_metric_type()`` in Dawarich, dict *keys* in Yazio — so they were scanned,
found nothing, and passed. The suite reported eight green tests over three importers'
worth of coverage.

So the scan is an AST walk now, and it works in two halves:

* **Naming positions** — the value of a ``"metric_type"`` key, a ``metric_type=``
  keyword, an assignment to ``metric_type``, an argument to
  ``canonical_metric_type()``. A string here *is* a metric name, so anything that is not
  canonical fails: an alias included, because aliases may be read and never written.
* **A permissive sweep** — the first positional argument of any call, and every string in
  any dict literal, kept only when it already is a canonical key. This cannot produce a
  false positive (a string that is a canonical registry key is not a payload field by
  coincidence) and it is what makes the coverage floor below meaningful.

The floor is the part that would have caught the regression: a transformer that yields no
name at all now fails, instead of passing for lack of anything to check.
"""

import ast
from pathlib import Path

import pytest
from shared_schemas.metrics import (
    CANONICAL_KEYS,
    DYNAMIC_NAMESPACES,
    UnknownMetricTypeError,
    canonical_metric_type,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
IMPORTERS = REPO_ROOT / "services" / "importers"

CANONICAL = set(CANONICAL_KEYS)


def _transformers() -> list[Path]:
    return sorted(IMPORTERS.rglob("transformer.py"))


def _importer_name(transformer: Path) -> str:
    """`services/importers/<name>/src/<pkg>/transformer.py` -> `<name>`."""
    return transformer.parent.parent.parent.name


def _literal(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _named(tree: ast.AST) -> set[str]:
    """Strings in a position where a string can only be a metric name.

    The first four rules are unambiguous by syntax. The last two are inferred, and they
    are what makes this cover Apple Health, weather and WHOOP — three importers that
    labelled nothing and were therefore checked for nothing:

    * **A metric map.** In a dict literal, if any *value* is already a canonical key then
      the values are metric names (`METRIC_NAME_MAP`, `METRIC_NAMES`: provider name to
      canonical key). If any *key* is, the keys are (Yazio's daily totals, where the
      values are numbers). Only the side that proved itself is read, which is why a
      provider name like `step_count` on the other side is not mistaken for a written
      name.
    * **A record constructor.** If any call to some callee passes a canonical key as its
      first argument, that callee's first argument is a metric name — WHOOP's
      `_Mapping("whoop_strain", "score", "strain")`, where `"strain"` in third position
      is a payload field that happens to be a registered alias.

    Inference has a cost worth naming: both rules need one correct example in the file to
    recognise the shape, so an importer whose *every* name is wrong looks like no map at
    all. That is what the coverage floor below is for.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if _literal(key) == "metric_type" and (found := _literal(value)):
                    names.add(found)
        elif isinstance(node, ast.keyword) and node.arg == "metric_type":
            if found := _literal(node.value):
                names.add(found)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "metric_type" in targets and (found := _literal(node.value)):
                names.add(found)
        elif isinstance(node, ast.Call):
            function = node.func
            called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
            if called == "canonical_metric_type" and node.args and (found := _literal(node.args[0])):
                names.add(found)

    names |= _names_in_metric_maps(tree)
    names |= _names_in_record_constructors(tree)
    return names


def _names_in_metric_maps(tree: ast.AST) -> set[str]:
    """Every string on whichever side of a dict literal holds metric names.

    The two sides are told apart by what the *values* are, because that is what separates
    the two shapes in this codebase:

    * **Values are strings** — a translation map, provider vocabulary to canonical key
      (`METRIC_NAME_MAP`, `SLEEP_STAGE_MAP`, `METRIC_NAMES`). Only the values are names.
      The keys are the provider's own words and are *expected* to be aliases: reading them
      as written names flagged all twenty of Apple Health's, which is how this rule was
      found to be too eager.
    * **Values are not strings** — a name-to-value table (Yazio's daily totals, whose
      values are floats). Then the keys are the names.

    A dict that carries a `"metric_type"` key is skipped entirely: that is an event
    payload, its name is already read by the labelled rule, and inferring over the rest
    picked up its `"source_type": "streak"` as a metric name.
    """
    names: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or not node.values:
            continue
        keys = [_literal(k) for k in node.keys]
        if "metric_type" in keys:
            continue
        values = [_literal(v) for v in node.values]

        if any(value is not None for value in values):
            if any(value in CANONICAL for value in values if value):
                names.update(value for value in values if value)
        elif any(key in CANONICAL for key in keys if key):
            names.update(key for key in keys if key)

    return names


def _names_in_record_constructors(tree: ast.AST) -> set[str]:
    """First arguments of a callee that takes a metric name first."""
    first_arguments: dict[str, set[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
        if not called or (found := _literal(node.args[0])) is None:
            continue
        first_arguments.setdefault(called, set()).add(found)

    return {
        name
        for arguments in first_arguments.values()
        if any(argument in CANONICAL for argument in arguments)
        for name in arguments
    }


def _canonical_anywhere(tree: ast.AST) -> set[str]:
    """Every string in the module that already is a canonical key.

    Two shapes carry the name without labelling it: WHOOP's positional
    ``_Mapping("whoop_strain", "score", "strain")`` and the maps that translate a
    provider's vocabulary, where the canonical key is a dict value (Apple Health,
    weather) or a dict key (Yazio's daily totals). Requiring the string to be canonical
    already is what keeps ``"score"`` and ``"strain"`` out.
    """
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in CANONICAL
    }


def _owns_a_dynamic_namespace(importer: str) -> bool:
    """Whether this importer's metric set is the user's to decide, not ours.

    Home Assistant exports whatever the household has configured, so its transformer
    holds no metric literal by design: it builds the name from the `entity_id` and
    resolves it at run time under the registered `home_assistant_` prefix. That is a
    reason to exempt it from the floor below, and derived from the registry rather than
    written out here, so a new dynamic provider does not need this test edited.

    The comparison is `prefix == f"{importer}_"`, not `prefix.startswith(importer)`: the
    latter is satisfied by any importer whose directory name is a prefix of a namespace,
    so a service called `home` or `apple` would have been exempted from the floor for
    free.
    """
    return any(ns.prefix == f"{importer}_" for ns in DYNAMIC_NAMESPACES)


def _calls(tree: ast.AST, function_name: str) -> bool:
    """Whether the module actually *calls* it, rather than merely importing the name.

    `"canonical_metric_type" in ast.dump(tree)` was the first attempt and it is satisfied
    by the import statement — so an importer that stopped resolving its dynamic names, and
    left the import, would have kept passing the check that exists to require the call.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        called = function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
        if called == function_name:
            return True
    return False


def test_the_importers_are_actually_being_scanned():
    """A scan that finds nothing would make every test below pass silently.

    Two halves, because counting the files is not the same as reading them: the previous
    version of this test asserted only that eight transformers exist, so a broken `_named`
    would have reported the scan healthy while checking nothing.
    """
    found = _transformers()
    assert len(found) >= 8, f"expected every importer to have a transformer, found {found}"
    assert any(
        _named(ast.parse(path.read_text(encoding="utf-8"))) for path in found
    ), "the name scan matched nothing in any transformer, so it is not working"


@pytest.mark.parametrize("transformer", _transformers(), ids=_importer_name)
def test_every_metric_literal_is_canonical(transformer: Path):
    tree = ast.parse(transformer.read_text(encoding="utf-8"))
    offenders: list[str] = []

    for name in sorted(_named(tree)):
        try:
            canonical = canonical_metric_type(name)
        except UnknownMetricTypeError:
            offenders.append(f"{name!r} is not registered")
            continue
        if canonical != name:
            offenders.append(f"{name!r} is a legacy alias of {canonical!r}")

    assert not offenders, (
        f"{transformer.relative_to(REPO_ROOT).as_posix()} writes metric names the "
        f"registry does not accept: {'; '.join(offenders)}"
    )


@pytest.mark.parametrize("transformer", _transformers(), ids=_importer_name)
def test_every_importer_names_at_least_one_registered_metric(transformer: Path):
    """The scan has to be able to see this importer's metrics at all.

    Five importers were invisible to the previous pattern. Nothing failed, because a
    scan that finds no name has no name to reject — the tests were green over an
    importer they never read. This is the assertion that makes coverage a property of
    the suite rather than of the spelling an importer happens to use.
    """
    importer = _importer_name(transformer)
    tree = ast.parse(transformer.read_text(encoding="utf-8"))
    found = _named(tree) | _canonical_anywhere(tree)

    if not found and _owns_a_dynamic_namespace(importer):
        # Then the name is built at run time and must be resolved there.
        assert _calls(tree, "canonical_metric_type"), (
            f"{importer} names no metric statically, which is legitimate under its "
            "dynamic namespace — but then it has to resolve the name it builds through "
            "canonical_metric_type()"
        )
        return

    assert found, (
        f"{transformer.relative_to(REPO_ROOT).as_posix()} yields no metric name this "
        "scan can see. Either it writes none (then it is not a transformer), or it "
        "names them in a shape the scan does not know — extend _named()/"
        "_canonical_anywhere() rather than leaving the importer unchecked."
    )
