```markdown
# Simorgh Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill teaches you how to contribute effectively to the Simorgh Python codebase. You'll learn the project's coding conventions, how to implement features with proper documentation and tests, and how to use and extend CI validation workflows for patches. The guide includes step-by-step instructions, code examples, and suggested commands for common development tasks.

## Coding Conventions

### File Naming

- Use **snake_case** for all Python files.
  - Example: `my_module.py`, `data_processor.py`

### Import Style

- Use **relative imports** within packages.
  - Example:
    ```python
    from .utils import validate_input
    from ..models import UserModel
    ```

### Export Style

- Use **named exports** (i.e., define specific functions/classes to be imported).
  - Example:
    ```python
    # In services/core/src/validation.py
    def validate_data(data):
        ...
    ```

### Commit Messages

- Follow **conventional commit** format with prefixes like `ci`, `core`, `docs`.
  - Example:
    ```
    core: add validation for user input length
    docs: update validation rules for new feature
    ci: update workflow for patch validation
    ```

## Workflows

### CI Validation Patch Workflow

**Trigger:** When you want to introduce and validate a new patch via CI before merging.  
**Command:** `/ci-validate-patch`

1. **Stage the patch file** in the `tools/` directory.
   - Example: `tools/fix_typo.patch`
2. **Create or update** a corresponding CI workflow file in `.github/workflows/` to validate the patch.
   - Example: `.github/workflows/validate_fix_typo.yml`
3. **Iterate on the workflow file** to enable PR validation and cleanup.
   - Edit the workflow YAML to ensure it applies the patch and runs relevant checks.
   - Example snippet:
     ```yaml
     name: Validate Patch
     on: [pull_request]
     jobs:
       patch-test:
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v2
           - name: Apply patch
             run: git apply tools/fix_typo.patch
           - name: Run tests
             run: pytest
     ```

### Feature Implementation with Docs and Tests

**Trigger:** When you want to add a new core feature or enforce a new rule/limit.  
**Command:** `/new-feature-docs-tests`

1. **Implement or update core logic** in `services/core/src/`.
   - Example: `services/core/src/new_feature.py`
2. **Add or update documentation** in `docs/validation/`.
   - Example: `docs/validation/new_feature.md`
3. **Add or update tests** in `services/core/tests/`.
   - Example: `services/core/tests/test_new_feature.py`
   - Test file pattern: `*.test.*`
4. **Optionally update CI workflow and patch files** if the feature requires new validation steps or patches.
   - Example: `.github/workflows/test_new_feature.yml`, `tools/new_feature.patch`

#### Example: Adding a New Feature

```python
# services/core/src/new_feature.py
def process_data(input_data):
    # Core logic here
    return input_data.strip().lower()
```

```python
# services/core/tests/test_new_feature.py
from ..src.new_feature import process_data

def test_process_data():
    assert process_data("  Hello ") == "hello"
```

```markdown
<!-- docs/validation/new_feature.md -->
# New Feature: Data Processing

This feature trims and lowercases input data for consistency.
```

## Testing Patterns

- **Test files** follow the pattern `*.test.*` and are located in `services/core/tests/`.
- **Testing framework** is not explicitly specified, but tests are written as Python functions (pytest style is recommended).
- **Example test file:**
  ```python
  # services/core/tests/test_validation.test.py
  from ..src.validation import validate_data

  def test_validate_data_accepts_valid_input():
      assert validate_data("valid input") is True
  ```

## Commands

| Command                 | Purpose                                                      |
|-------------------------|--------------------------------------------------------------|
| /ci-validate-patch      | Start the CI validation workflow for a staged patch          |
| /new-feature-docs-tests | Scaffold a new feature with docs and tests                   |
```
