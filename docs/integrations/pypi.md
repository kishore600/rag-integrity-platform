# Publish `ragguard-cli` to PyPI

The package lives in [clients/python](../../clients/python). Its README is the PyPI page. Version 0.1.0 was published on
16 November 2026: https://pypi.org/project/ragguard-cli/. The name `ragguard` belongs to a different project, so do not use it.

## Once

1. Create an account on [pypi.org](https://pypi.org/account/register/) and turn on two-factor authentication (PyPI requires it).
2. Create an API token: Account settings, API tokens, "Add API token", scope "Entire account" for the first upload. After the first
   upload, replace it with a token scoped to `ragguard-cli` only.

## Every release

From the repository folder:

```bash
python -m pip install --upgrade build twine
python -m build clients/python --outdir dist-cli
python -m twine check dist-cli/*
python -m twine upload dist-cli/*
```

`twine upload` asks for a username and password: the username is `__token__` and the password is the API token. Type it yourself;
never paste it into a chat or a file in the repository.

Before each new release, raise `version` in `clients/python/pyproject.toml` and `__version__` in
`clients/python/ragguard_cli/__init__.py` (PyPI refuses a version that already exists).

## After the first upload

- Check the page: https://pypi.org/project/ragguard-cli/
- Check it installs: `pip install ragguard-cli` then `ragguard --version`.
- In `docs/guides/09-use-ragguard-from-your-ai-assistant.md` and the main README, the install line can then become simply
  `pip install ragguard-cli` (the MCP server is included).
- Then list the MCP server: [mcp-registries.md](mcp-registries.md).
