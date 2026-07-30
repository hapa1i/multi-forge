"""Pure module resolution, scope, and runtime-selection policy."""

from __future__ import annotations

from .exceptions import ForgeInstallError
from .models import (
    MODULE_DEPENDENCIES,
    MODULE_RUNTIME_OWNERS,
    PROFILE_MODULES,
    InstallModule,
    InstallPlan,
    InstallProfile,
    InstallScope,
    ModulePlan,
)
from .skill_planning import RuntimeSelection, RuntimeSelectionOrigin

_RUNTIME_HOOK_MODULES = {InstallModule.HOOKS}
_USER_SCOPE_OMITTED_MODULES = {InstallModule.STATUSLINE}


def _format_modules(modules: set[InstallModule]) -> str:
    return ", ".join(sorted(module.value for module in modules))


def _scope_omitted_modules(scope: InstallScope) -> set[InstallModule]:
    if scope == InstallScope.USER:
        return set(_USER_SCOPE_OMITTED_MODULES)
    return set(_RUNTIME_HOOK_MODULES)


def apply_scope_module_policy(
    modules: set[InstallModule],
    *,
    scope: InstallScope,
    explicit_modules: set[InstallModule] | None = None,
) -> set[InstallModule]:
    """Return modules that are writable at the requested scope."""

    omitted = _scope_omitted_modules(scope)
    explicit_conflicts = omitted & (explicit_modules or set())
    if explicit_conflicts:
        if scope == InstallScope.USER:
            raise ForgeInstallError(
                f"module(s) {_format_modules(explicit_conflicts)} are project/local-scope only; "
                "statusLine stays project-scoped; install it at project/local scope."
            )
        raise ForgeInstallError(
            f"module(s) {_format_modules(explicit_conflicts)} are user-scope only; "
            "run 'forge extension enable --scope user' to install runtime hooks."
        )
    return modules - omitted


def resolve_modules(
    profile: InstallProfile,
    with_modules: set[InstallModule] | None = None,
    without_modules: set[InstallModule] | None = None,
) -> set[InstallModule]:
    """Resolve the module set from profile, toggles, and dependencies."""

    modules = PROFILE_MODULES[profile].copy()
    if with_modules:
        modules |= with_modules
    if without_modules:
        modules -= without_modules
    for module in list(modules):
        if deps := MODULE_DEPENDENCIES.get(module):
            modules |= deps
    return modules


def filter_modules_by_runtime(
    modules: set[InstallModule],
    *,
    selection: RuntimeSelection,
    explicit_modules: set[InstallModule] | None,
) -> tuple[set[InstallModule], list[ModulePlan], list[str]]:
    """Apply runtime selection after profile, dependency, and scope resolution."""

    selected = set(selection.runtime_ids)
    effective = {module for module in modules if MODULE_RUNTIME_OWNERS[module] & selected}
    outcomes: list[ModulePlan] = []
    conflicts: list[str] = []
    for module in sorted(modules, key=lambda item: item.value):
        if module in effective:
            outcomes.append(ModulePlan(module=module.value, action="install", reason="runtime_selected"))
            continue
        action = "conflict" if module in (explicit_modules or set()) else "skip"
        outcomes.append(ModulePlan(module=module.value, action=action, reason="runtime_excluded"))
        if action == "conflict":
            selected_names = ", ".join(selection.runtime_ids)
            conflicts.append(f"Module: {module.value} - module is not owned by selected runtime(s): {selected_names}")

    if selection.origin == RuntimeSelectionOrigin.EXPLICIT and not effective:
        selected_names = ", ".join(selection.runtime_ids)
        conflicts.append(
            f"Runtime selection: {selected_names} - no modules remain after profile, scope, and runtime filtering"
        )
    return effective, outcomes, conflicts


def validate_file_plan_ownership(plan: InstallPlan) -> None:
    """Reject file provenance outside the plan's resolved module/runtime set."""

    resolved_modules: set[InstallModule] = set()
    for module_value in plan.modules:
        try:
            resolved_modules.add(InstallModule(module_value))
        except ValueError as e:
            raise ForgeInstallError(f"Install plan contains unknown module {module_value!r}") from e

    selected_runtimes = set(plan.selected_runtimes)
    allowed_pairs = {
        (module.value, runtime)
        for module in resolved_modules
        for runtime in MODULE_RUNTIME_OWNERS[module] & selected_runtimes
    }
    for file_plan in plan.files:
        pair = (file_plan.module, file_plan.runtime)
        if pair not in allowed_pairs:
            raise ForgeInstallError(
                f"File plan '{file_plan.target_path}' has ownership {pair!r} outside the resolved "
                "module/runtime set; refusing before filesystem mutation"
            )
