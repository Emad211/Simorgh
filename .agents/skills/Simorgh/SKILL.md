```markdown
# Simorgh Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns and workflows used in the Simorgh Python codebase. You'll learn about the project's coding conventions, file organization, import/export styles, and how to contribute effectively—especially regarding continuous integration (CI) workflows. This guide is designed to help both new and existing contributors maintain consistency and quality across the repository.

## Coding Conventions

### File Naming
- **Style:** snake_case
- **Example:**  
  ```plaintext
  data_processor.py
  utils/helpers.py
  ```

### Import Style
- **Style:** Relative imports
- **Example:**  
  ```python
  from .utils import helper_function
  from ..core import base_class
  ```

### Export Style
- **Style:** Named exports (explicitly listing what is exported)
- **Example:**  
  ```python
  __all__ = ["MyClass", "my_function"]
  ```

### Commit Messages
- **Type:** Conventional Commits
- **Prefixes:** `ci`, `core`
- **Example:**  
  ```
  ci: add initial GitHub Actions workflow
  core: refactor data loading logic
  ```

## Workflows

### CI Workflow Addition and Iteration
**Trigger:** When someone wants to introduce or update a CI validation process for a new feature or patch.  
**Command:** `/new-ci-workflow`

1. **Create a new workflow file:**  
   Add a new YAML file under `.github/workflows/`, e.g., `.github/workflows/test.yml`.
   ```yaml
   name: Run Tests
   on: [push, pull_request]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v2
         - name: Set up Python
           uses: actions/setup-python@v2
           with:
             python-version: '3.9'
         - name: Install dependencies
           run: pip install -r requirements.txt
         - name: Run tests
           run: pytest
   ```
2. **Iteratively update the workflow:**  
   Refine the YAML file to improve steps, triggers, or add cleanup tasks as needed.
   - Example: Add a job for linting or cache dependencies.
3. **Coordinate with code changes:**  
   If the workflow supports a new feature or patch, ensure related code is updated and tested accordingly.

## Testing Patterns

- **Framework:** Unknown (not explicitly detected)
- **Test File Pattern:** Files matching `*.test.*` (e.g., `utils.test.py`)
- **Example Test File:**
  ```python
  # utils.test.py

  from .utils import add

  def test_add():
      assert add(2, 3) == 5
  ```

## Commands
| Command           | Purpose                                                        |
|-------------------|----------------------------------------------------------------|
| /new-ci-workflow  | Start or update a CI workflow YAML file for validation/testing |
```
