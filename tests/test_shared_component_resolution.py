"""`service/shared_component.py` — resolving a screen's ViewComponent and
partial view references to the ViewComponents it actually reaches
(spec.md stories 22-24). Pure module, no I/O; drives the resolver directly
with the plain data `analyze_service` would build from a scan.
"""

from __future__ import annotations

from service.shared_component import resolve_shared_components


def test_a_view_component_invoked_directly_is_resolved() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["CustomerSelector"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/CustomerSelectorViewComponent.cs",
                "CustomerSelectorViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={},
    )
    assert [(c.name, c.file_path, c.entry_method) for c in contributions] == [
        (
            "CustomerSelector",
            "Components/CustomerSelectorViewComponent.cs",
            "InvokeAsync",
        )
    ]


def test_a_view_component_named_by_its_kebab_case_tag_is_resolved() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["customer-selector"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/CustomerSelectorViewComponent.cs",
                "CustomerSelectorViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={},
    )
    assert len(contributions) == 1
    assert contributions[0].file_path == "Components/CustomerSelectorViewComponent.cs"


def test_a_view_component_reached_through_a_partial_view_is_resolved() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Shared/_Header.cshtml": ["Menu"]},
        partial_view_refs={"Views/Order/Index.cshtml": ["_Header"]},
        view_component_classes=[
            (
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={
            "Views/Order/Index.cshtml": ("", "Order", "Index"),
            "Views/Shared/_Header.cshtml": ("", "Shared", "_Header"),
        },
    )
    assert [c.name for c in contributions] == ["Menu"]


def test_a_partial_named_without_its_leading_underscore_still_resolves() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Shared/_Header.cshtml": ["Menu"]},
        partial_view_refs={"Views/Order/Index.cshtml": ["Header"]},
        view_component_classes=[
            (
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={
            "Views/Order/Index.cshtml": ("", "Order", "Index"),
            "Views/Shared/_Header.cshtml": ("", "Shared", "_Header"),
        },
    )
    assert [c.name for c in contributions] == ["Menu"]


def test_a_partial_in_the_same_folder_as_its_caller_is_preferred_over_shared() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={
            "Views/Order/_Summary.cshtml": ["OrderOnly"],
            "Views/Shared/_Summary.cshtml": ["SharedOnly"],
        },
        partial_view_refs={"Views/Order/Index.cshtml": ["_Summary"]},
        view_component_classes=[
            (
                "Components/OrderOnlyViewComponent.cs",
                "OrderOnlyViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            ),
            (
                "Components/SharedOnlyViewComponent.cs",
                "SharedOnlyViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            ),
        ],
        view_identities={
            "Views/Order/Index.cshtml": ("", "Order", "Index"),
            "Views/Order/_Summary.cshtml": ("", "Order", "_Summary"),
            "Views/Shared/_Summary.cshtml": ("", "Shared", "_Summary"),
        },
    )
    assert [c.name for c in contributions] == ["OrderOnly"]


def test_a_partial_reached_recursively_through_another_partial_is_resolved() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Shared/_Inner.cshtml": ["Cart"]},
        partial_view_refs={
            "Views/Order/Index.cshtml": ["_Outer"],
            "Views/Shared/_Outer.cshtml": ["_Inner"],
        },
        view_component_classes=[
            (
                "Components/CartViewComponent.cs",
                "CartViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={
            "Views/Order/Index.cshtml": ("", "Order", "Index"),
            "Views/Shared/_Outer.cshtml": ("", "Shared", "_Outer"),
            "Views/Shared/_Inner.cshtml": ("", "Shared", "_Inner"),
        },
    )
    assert [c.name for c in contributions] == ["Cart"]


def test_a_cyclic_partial_reference_never_loops_forever() -> None:
    contributions = resolve_shared_components(
        "Views/Shared/_A.cshtml",
        view_component_refs={},
        partial_view_refs={
            "Views/Shared/_A.cshtml": ["_B"],
            "Views/Shared/_B.cshtml": ["_A"],
        },
        view_component_classes=[],
        view_identities={
            "Views/Shared/_A.cshtml": ("", "Shared", "_A"),
            "Views/Shared/_B.cshtml": ("", "Shared", "_B"),
        },
    )
    assert contributions == []


def test_a_view_component_reached_by_two_screens_resolves_for_each() -> None:
    classes = [
        (
            "Components/MenuViewComponent.cs",
            "MenuViewComponent",
            "ViewComponent",
            ["InvokeAsync"],
        )
    ]
    refs = {
        "Views/Order/Index.cshtml": ["Menu"],
        "Views/Report/Index.cshtml": ["Menu"],
    }
    for view in refs:
        contributions = resolve_shared_components(
            view,
            view_component_refs=refs,
            partial_view_refs={},
            view_component_classes=classes,
            view_identities={},
        )
        assert [c.name for c in contributions] == ["Menu"]


def test_a_name_matching_no_class_resolves_nothing() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["Unknown"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={},
    )
    assert contributions == []


def test_two_classes_matching_one_name_resolve_ambiguously_to_nothing() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["Menu"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            ),
            (
                "Areas/Admin/Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["InvokeAsync"],
            ),
        ],
        view_identities={},
    )
    assert contributions == []


def test_a_class_with_no_invoke_method_resolves_nothing() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["Menu"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/MenuViewComponent.cs",
                "MenuViewComponent",
                "ViewComponent",
                ["BuildModel"],
            )
        ],
        view_identities={},
    )
    assert contributions == []


def test_a_class_whose_name_does_not_end_in_viewcomponent_needs_the_base_class() -> None:
    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["MenuPresenter"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/MenuPresenter.cs",
                "MenuPresenter",
                "SomeUnrelatedBase",
                ["InvokeAsync"],
            )
        ],
        view_identities={},
    )
    assert contributions == []

    contributions = resolve_shared_components(
        "Views/Order/Index.cshtml",
        view_component_refs={"Views/Order/Index.cshtml": ["MenuPresenter"]},
        partial_view_refs={},
        view_component_classes=[
            (
                "Components/MenuPresenter.cs",
                "MenuPresenter",
                "ViewComponent",
                ["InvokeAsync"],
            )
        ],
        view_identities={},
    )
    assert [c.name for c in contributions] == ["MenuPresenter"]
