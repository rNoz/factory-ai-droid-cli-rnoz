#!/usr/bin/env python3
"""Focused tests for the isolated Droid keybinding rotation.

Fixtures mirror the serialized keymap bytes observed in real upstream
binaries: the null-separated constant-pool table, the guarded runtime
dispatch statements, the model registry descriptor, and the help/hint
strings (including localized chord styles). Machine kebab-case keys
(``ctrl-g``) are intentionally never rotated; human chord notation
(``Ctrl+G``) is.
"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "patches"))

import patch_keybindings  # noqa: E402

QUEUE_ACTION = b"GH"
EDITOR_ACTION = b"hI"


def keymap_table(queue: bytes = QUEUE_ACTION, editor: bytes = EDITOR_ACTION) -> bytes:
    """Serialized keymap constant-pool slice as found in upstream binaries."""
    return (
        b"ctrl-r\x00CH\x00tD\x00KI\x00"
        b"ctrl-g\x00" + queue + b"\x00"
        b"ctrl-p\x00" + editor + b"\x00"
        b"ctrl-slash\x00X\x00"
        b"c\x00C\x00v\x00V\x00Lt\x00"
        b"model-cycle\x00S\x00"
        b"autonomy-cycle\x00J\x00"
    )


def dispatch_block(
    queue: bytes = QUEUE_ACTION,
    editor: bytes = EDITOR_ACTION,
    *,
    queue_guard: bool = True,
    editor_guard: bool = False,
    split: bool = False,
    stray_ctrl_q: bool = False,
    duplicate_ctrl_g: bool = False,
    duplicate_ctrl_p: bool = False,
) -> bytes:
    """Runtime key dispatch statements (upstream minified style)."""
    queue_stmt = (
        b'mf({key:ZL,input:_A},"ctrl-g")'
        + (b"&&" + queue if queue_guard else b"")
        + b"&&!tD&&!KI)return "
        + queue
        + b"(),!0;"
    )
    editor_stmt = (
        b'mf({key:ZL,input:_A},"ctrl-p")'
        + (b"&&" + editor if editor_guard else b"")
        + b"&&!tD&&!KI)return "
        + editor
        + b"(),!0;"
    )
    pieces = []
    if duplicate_ctrl_g:
        pieces.append(b'mf({key:ZL,input:_A},"ctrl-g")&&GQ&&!tD&&!KI)return GQ(),!0;if(')
    else:
        pieces.append(b'mf({key:ZL,input:_A},"ctrl-r")&&CH&&!tD&&!KI)return CH(),!0;if(')
    pieces.append(queue_stmt)
    if split:
        pieces.append(b'if(mf({key:ZL,input:_A},"ctrl-x"))return Y(),!0;')
    pieces.append(b"if(")
    pieces.append(editor_stmt)
    if duplicate_ctrl_p:
        pieces.append(b'if(mf({key:ZL,input:_A},"ctrl-p")&&!tD&&!KI)return hI(),!0;')
    pieces.append(b'if(mf({key:ZL,input:_A},"ctrl-slash"))return X?.(),!0;')
    if stray_ctrl_q:
        pieces.append(b'if(mf({key:ZL,input:_A},"ctrl-q")&&S&&!tD&&!KI)return S(),!0;')
    pieces.append(
        b'if(ZL.ctrl){if(mf({key:ZL,input:_A},"model-cycle")){if(S&&!tD&&!KI)return S(),!0}'
        b'if(mf({key:ZL,input:_A},"autonomy-cycle")){if(J&&!tD&&!KI)return J(),!0}}'
    )
    return b"".join(pieces)


def model_cycle_descriptor(matcher: bytes = b"Ps1", param: bytes = b"H", key: bytes = b"n") -> bytes:
    return (
        b'modelCycle:{id:"model-cycle",label:"Ctrl+' + key.upper() + b'",'
        b'matcher:(' + param + b")=>" + matcher + b"(" + param + b',"' + key + b'")}'
    )


def display_block() -> bytes:
    return (
        b'editorOverflowHint:"Ctrl+P to open in editor"'
        b'queuedReviewHint:"Ctrl+R to modify queue \xB7 Ctrl+G to pull top \xB7 Ctrl+X to clear queue"'
        b'overlay:"Ctrl + P for editor","Ctrl + N for model cycle"'
        b'statusBar:"shift+tab to cycle modes \xB7 ctrl+N to cycle models"'
        b'onboarding:"4. Cycle models (Ctrl+N)"'
        b'missionHelpMenu:"Quick select \xB7 ctrl-g to edit plan \xB7 ESC Cancel"'
        b'macOverlay:"Alt/Option + P for plan screen"'
        b'commitBindings:["ctrl+s","mac+meta+s","ctrl+p","mac+meta+p"]'
    )


def fixture(**dispatch_options) -> bytes:
    return (
        keymap_table()
        + b"|"
        + dispatch_block(**dispatch_options)
        + b"|"
        + model_cycle_descriptor()
        + b"|"
        + display_block()
    )


def expect_patch_error(data: bytes, *keywords: bytes) -> None:
    try:
        patch_keybindings.apply_patch_bytes(data)
    except patch_keybindings.PatchError as error:
        for keyword in keywords:
            assert keyword in str(error).encode(), f"error {error!r} missing {keyword!r}"
        return
    raise AssertionError("unsafe layout must fail closed")


def test_rotates_editor_model_and_queue_bindings() -> None:
    original = fixture()

    patched = patch_keybindings.apply_patch_bytes(original)

    assert len(patched) == len(original)
    # Serialized keymap table: editor action under Ctrl-G, queue action under Ctrl-N.
    assert b"ctrl-g\x00hI\x00" in patched
    assert b"ctrl-q\x00GH\x00" in patched
    assert b"ctrl-p\x00hI\x00" not in patched
    # Runtime dispatch: guards travel with their actions.
    assert b'mf({key:ZL,input:_A},"ctrl-g")&&!tD&&!KI)return hI(),!0;' in patched
    assert b'mf({key:ZL,input:_A},"ctrl-q")&&GH&&!tD&&!KI)return GH(),!0;' in patched
    assert b'"ctrl-g")&&GH&&!tD&&!KI)return GH()' not in patched
    assert b'"ctrl-p")&&!tD&&!KI)return hI()' not in patched
    # Model registry: cycle model on Ctrl-P.
    assert b'modelCycle:{id:"model-cycle",label:"Ctrl+P",matcher:(H)=>Ps1(H,"p")}' in patched
    # Help/hint rotation across every human chord style.
    assert b'editorOverflowHint:"Ctrl+G to open in editor"' in patched
    assert b"Ctrl+Q to pull top" in patched
    assert b"Ctrl+G to pull top" not in patched
    assert b'"Ctrl + G for editor"' in patched
    assert b'"Ctrl + P for model cycle"' in patched
    assert b"ctrl+P to cycle models" in patched
    assert b"4. Cycle models (Ctrl+P)" in patched
    # Machine kebab keys, unrelated chords, and lowercase mac bindings stay untouched.
    assert b"ctrl-g to edit plan" in patched
    assert b"Ctrl+R to modify queue" in patched
    assert b"Ctrl+X to clear queue" in patched
    assert b'"Alt/Option + P for plan screen"' in patched
    assert b'"ctrl+p"' in patched


def test_display_counts_permute() -> None:
    original = fixture()
    patched = patch_keybindings.apply_patch_bytes(original)

    for template in (b"Ctrl+%s", b"Ctrl + %s", b"ctrl+%s", b"Ctrl-%s"):
        before = {letter: original.count(template % letter) for letter in (b"G", b"N", b"P", b"Q")}
        after = {letter: patched.count(template % letter) for letter in (b"G", b"N", b"P", b"Q")}
        expected = {b"G": before[b"P"], b"N": 0, b"P": before[b"N"], b"Q": before[b"G"]}
        assert after == expected, f"display counts did not rotate for {template!r}: {before} -> {after}"


def test_refuses_ambiguous_bindings() -> None:
    expect_patch_error(fixture(duplicate_ctrl_g=True), b"unique")
    expect_patch_error(fixture(duplicate_ctrl_p=True), b"unique")
    expect_patch_error(fixture(stray_ctrl_q=True), b"Ctrl-Q")


def test_refuses_unsafe_layouts() -> None:
    expect_patch_error(fixture(queue_guard=False), b"guard")
    expect_patch_error(fixture(editor_guard=True), b"guard")
    expect_patch_error(fixture(split=True), b"adjacent")


def test_refuses_partially_patched_binaries() -> None:
    fully_patched = patch_keybindings.apply_patch_bytes(fixture())
    # Table and dispatch rotated but the model registry was left on Ctrl-N.
    matcher_unpatched = fully_patched.replace(
        b'modelCycle:{id:"model-cycle",label:"Ctrl+P",matcher:(H)=>Ps1(H,"p")}',
        model_cycle_descriptor(),
    )
    expect_patch_error(matcher_unpatched, b"partially")
    # Table rotated but the runtime dispatch statements were not.
    table_only = fixture().replace(
        b"ctrl-g\x00GH\x00ctrl-p\x00hI\x00", b"ctrl-g\x00hI\x00ctrl-q\x00GH\x00"
    )
    expect_patch_error(table_only, b"partially")
    # Dispatch rotated but the serialized table was not.
    dispatch_only = fixture().replace(
        b'mf({key:ZL,input:_A},"ctrl-g")&&GH&&!tD&&!KI)return GH(),!0;'
        b'if(mf({key:ZL,input:_A},"ctrl-p")&&!tD&&!KI)return hI(),!0;',
        b'mf({key:ZL,input:_A},"ctrl-g")&&!tD&&!KI)return hI(),!0;'
        b'if(mf({key:ZL,input:_A},"ctrl-q")&&GH&&!tD&&!KI)return GH(),!0;',
    )
    expect_patch_error(dispatch_only, b"partially")


def test_tolerates_minified_identifier_renames() -> None:
    renamed = fixture().replace(b"GH", b"Xq").replace(b"hI", b"Zp")
    renamed = renamed.replace(b"Ps1(H,", b"Qz(e,").replace(b"matcher:(H)=>", b"matcher:(e)=>")
    renamed = renamed.replace(b"!tD&&!KI)", b"!tW&&!KO)")

    patched = patch_keybindings.apply_patch_bytes(renamed)

    assert len(patched) == len(renamed)
    assert b'mf({key:ZL,input:_A},"ctrl-g")&&!tW&&!KO)return Zp(),!0;' in patched
    assert b'mf({key:ZL,input:_A},"ctrl-q")&&Xq&&!tW&&!KO)return Xq(),!0;' in patched
    assert b'modelCycle:{id:"model-cycle",label:"Ctrl+P",matcher:(e)=>Qz(e,"p")}' in patched


def test_is_idempotent() -> None:
    original = fixture()
    patched = patch_keybindings.apply_patch_bytes(original)

    assert patch_keybindings.apply_patch_bytes(patched) == patched


if __name__ == "__main__":
    tests = (
        test_rotates_editor_model_and_queue_bindings,
        test_display_counts_permute,
        test_refuses_ambiguous_bindings,
        test_refuses_unsafe_layouts,
        test_refuses_partially_patched_binaries,
        test_tolerates_minified_identifier_renames,
        test_is_idempotent,
    )
    failures = 0
    for test in tests:
        try:
            test()
            print(f"[PASS] {test.__name__}")
        except (AssertionError, patch_keybindings.PatchError):
            failures += 1
            print(f"[FAIL] {test.__name__}: {traceback.format_exc()}")
    if failures:
        print(f"{failures}/{len(tests)} KEYBINDING TESTS FAILED")
        sys.exit(1)
    print("ALL KEYBINDING TESTS PASSED")
