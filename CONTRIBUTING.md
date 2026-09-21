# Contributing to Phantom Workstation

Thank you for your interest in contributing to Phantom Workstation.

## Code Quality and Style Standards

To maintain high engineering standards, all contributions must adhere to the following principles:

1. **Zero Emoji Policy**: No emojis, pictographs, or decorative Unicode characters in code, comments, docstrings, terminal logs, or documentation.
2. **Platform Scope**: This library is strictly macOS-native. Code targeting Linux or Windows should not be introduced unless behind an explicit OS-conditional abstraction that does not affect macOS performance.
3. **Token Efficiency**: Changes to the Accessibility diff engine (`ax_diff.py`) must maintain or improve token reduction ratios and preserve semantic sibling key stability.
4. **Safety and Process Hygiene**: Any background process spawned must be cleanly terminated on exit, with fallback signals to prevent zombie processes.

## Development Workflow

1. Fork the repository and create a feature branch.
2. Set up a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
3. Run the test suite:
   ```bash
   make test
   ```
4. Run the pre-release verification audit:
   ```bash
   make audit
   ```
5. Ensure all checks pass before submitting a pull request.

## License

By contributing to Phantom Workstation, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
